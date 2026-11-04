"""Two direct USB D2 sensors -> existing GUI, with all safety commands disabled."""
import argparse
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jetson.walker_preview.d2_usb import AMPLITUDE, DEPTH, DEPTH_ONLY, DEVICE_INFO, START_3D, STOP, StreamParser, decode_depth, display_depth_xyz, frequency_channel_command
from lidar_preview import PreviewSnapshot
import numpy as np


class UsbReceiver:
    error = None

    def __init__(self, ports, baud=3000000, passive=False, serial_factory=None, clock=time.monotonic, channels=None):
        self.ports, self.baud, self.passive = dict(ports), baud, passive
        self.channels = dict(channels or {})
        if passive and self.channels:
            raise ValueError("Passive mode cannot set frequency channels")
        for side, channel in self.channels.items():
            if side not in self.ports:
                raise ValueError("A frequency channel needs a selected port")
            frequency_channel_command(channel)
        self.serial_factory, self.clock = serial_factory, clock
        self._lock, self._stop = threading.Lock(), threading.Event()
        self._threads, self._latest, self._errors = [], {}, {}
        self.full_resolution = False
        self._selection_version = 0
        self._stats = {side: {"received": 0, "displayed": 0, "bad_checksum": 0,
                              "bad_frame": 0, "points": 0, "bytes": 0,
                              "last_type": None, "last_size": 0, "raw_valid": 0, "in_range": 0,
                              "min_mm": None, "max_mm": None,
                              "requested_channel": self.channels.get(side),
                              "channel_command_sent": None} for side in ("left", "right")}

    def start(self):
        for side, port in self.ports.items():
            thread = threading.Thread(target=self._loop, args=(side, port), daemon=True,
                                      name="USB-3D-" + side)
            self._threads.append(thread)
            thread.start()

    def stop(self):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=1.0)

    def stats(self, side):
        with self._lock:
            return {**self._stats[side], "error": self._errors.get(side, "")}

    def set_full_resolution(self, enabled):
        with self._lock:
            self.full_resolution = bool(enabled)
            self._selection_version += 1
            self._latest.clear()

    def snapshot(self, side):
        with self._lock:
            latest, error = self._latest.get(side), self._errors.get(side)
        if error:
            return PreviewSnapshot(status="unavailable")
        if latest is None:
            return PreviewSnapshot()
        snapshot, arrived = latest
        if self.clock() - arrived >= .5:
            return PreviewSnapshot(status="stale")
        return snapshot

    def ingest(self, side, payload):
        if side not in self._stats or not payload or payload[0] not in (DEPTH, AMPLITUDE):
            return False
        try:
            depth = decode_depth(payload)
        except ValueError:
            with self._lock:
                self._stats[side]["bad_frame"] += 1
            return False
        arrived = self.clock()
        with self._lock:
            self._stats[side]["received"] += 1
            full_resolution, version = self.full_resolution, self._selection_version
            previous = self._latest.get(side)
            if previous is not None and arrived - previous[1] < .1:
                return False  # Latest display is bounded to 10 Hz per sensor.
        points = tuple(map(tuple, display_depth_xyz(depth, full_resolution).tolist()))
        snapshot = PreviewSnapshot(points, "live" if points else "empty", False)
        valid_depth = depth[(depth > 0) & (depth < 4000)]
        with self._lock:
            if version != self._selection_version:
                return False
            self._latest[side] = snapshot, arrived
            self._errors.pop(side, None)
            self._stats[side]["displayed"] += 1
            self._stats[side]["points"] = len(points)
            self._stats[side]["raw_valid"] = int(valid_depth.size)
            self._stats[side]["in_range"] = int(np.count_nonzero((depth >= 50) & (depth <= 2000)))
            self._stats[side]["min_mm"] = int(valid_depth.min()) if valid_depth.size else None
            self._stats[side]["max_mm"] = int(valid_depth.max()) if valid_depth.size else None
        return True

    def _loop(self, side, port):
        factory = self.serial_factory
        if factory is None:
            import serial
            factory = serial.Serial
        while not self._stop.is_set():
            ser, started = None, False
            parser = StreamParser()
            try:
                ser = factory(port=port, baudrate=self.baud, timeout=.1, write_timeout=.5)
                with self._lock:
                    self._stats[side]["channel_command_sent"] = None
                if not self.passive:
                    # SDK startup waits for the device-info request before selecting 3D.
                    ser.write(DEVICE_INFO)
                    if self._stop.wait(3.0):
                        break
                    ser.write(DEPTH_ONLY)
                    if self._stop.wait(.1):
                        break
                    ser.write(START_3D)
                    started = True
                    if side in self.channels:
                        # Match the vendor SDK: select the frequency after run-mode start.
                        channel = self.channels[side]
                        packet = frequency_channel_command(channel)
                        if ser.write(packet) != len(packet):
                            raise OSError("Incomplete frequency-channel command")
                        with self._lock:
                            self._stats[side]["channel_command_sent"] = channel
                while not self._stop.is_set():
                    chunk = ser.read(max(1, min(8192, ser.in_waiting)))
                    if chunk:
                        with self._lock:
                            self._stats[side]["bytes"] += len(chunk)
                        for payload in parser.feed(chunk):
                            with self._lock:
                                self._stats[side]["last_type"] = payload[0]
                                self._stats[side]["last_size"] = len(payload)
                            self.ingest(side, payload)
                        with self._lock:
                            self._stats[side]["bad_checksum"] = parser.bad_checksum
            except Exception as exc:
                with self._lock:
                    self._errors[side] = type(exc).__name__
            finally:
                if ser is not None:
                    try:
                        if started:
                            ser.write(STOP)
                    except Exception:
                        pass
                    try:
                        ser.close()
                    except Exception:
                        pass
            self._stop.wait(1.0)


def create_dashboard(root, receiver):
    import ui
    ui.MAP_AVAILABLE = False
    receiver.set_full_resolution(True)

    class NoStatus:
        def start(self): pass
        def stop(self): pass
        def latest(self): return None, False

    class NoCommands:
        def send(self, _command):
            raise RuntimeError("Safety commands are disabled in USB GUI tests")

    class UsbTestDashboard(ui.Dashboard):
        def _set_full_view(self, enabled):
            for card in (self.lidar_l, self.lidar_r):
                card.preview_3d.set_full_view(enabled)
            self.full_view_button.config(bg="#17576a" if enabled else ui.C_CARD)
            self.detail_view_button.config(bg=ui.C_CARD if enabled else "#17576a")

        def _toggle_full_points(self):
            enabled = not self.preview_sub.full_resolution
            self.preview_sub.set_full_resolution(enabled)
            self.full_points_button.config(text="전체 점군: 켬" if enabled else "전체 점군: 끔",
                                           bg="#17576a" if enabled else ui.C_CARD)
            self._set_full_view(enabled)

        def _refresh(self):
            self.clock.config(text=time.strftime("%H:%M:%S"))
            for side, card in (("left", self.lidar_l), ("right", self.lidar_r)):
                snapshot = self.preview_sub.snapshot(side)
                card.update_3d(snapshot)
                label = {"live": "3D 수신 중", "empty": "유효 점 없음", "stale": "3D 수신 중단",
                         "missing": "3D 수신 대기", "unavailable": "USB 연결 오류"}.get(snapshot.status, "확인 중")
                card._flat(label, ui.C_GREEN if snapshot.status == "live" else ui.C_GRAY, "판정 미실행")
            self.overall.grid_remove()
            left, right = (self.preview_sub.stats(side) for side in ("left", "right"))
            self.health_lbl.config(text=f"수신 USB1 {left['received']} / USB2 {right['received']} 프레임")
            self.batt.update_battery(None, False)
            self.curb_lbl.grid_remove()
            self.summary_imu.config(text="IMU · 시험하지 않음", fg=ui.C_GRAY)
            self.summary_gps.config(text="GPS · 시험하지 않음", fg=ui.C_GRAY)
            self.sos_status.config(text="실제 라이다 점군만 표시 · SOS/보호자 알림/거리 판정 비활성", fg=ui.C_YELLOW)
            self.sos_button.config(state=ui.tk.DISABLED, text="시험 모드 · SOS 비활성")
            self.root.after(self.REFRESH_MS, self._refresh)

    dashboard = UsbTestDashboard(root, status_subscriber=NoStatus(),
                                 command_sender=NoCommands(), preview_receiver=receiver)
    dashboard.display_mode_buttons["2D"].config(state=ui.tk.DISABLED)
    controls = ui.tk.Frame(dashboard.header_controls, bg=ui.C_HEADER_BG)
    controls.pack(side=ui.tk.LEFT, padx=(0, 4))
    dashboard.full_points_button = ui.tk.Button(
        controls, text="전체 점군: 켬", command=dashboard._toggle_full_points,
        bg="#17576a", fg=ui.C_WHITE, relief=ui.tk.FLAT, font=("Segoe UI", 10), padx=8, pady=5)
    dashboard.full_points_button.pack(side=ui.tk.LEFT, padx=(0, 6))
    dashboard.full_view_button = ui.tk.Button(
        controls, text="전체 보기", command=lambda: dashboard._set_full_view(True),
        bg=ui.C_CARD, fg=ui.C_WHITE, relief=ui.tk.FLAT, font=("Segoe UI", 10), padx=8, pady=5)
    dashboard.full_view_button.pack(side=ui.tk.LEFT, padx=(0, 6))
    dashboard.detail_view_button = ui.tk.Button(
        controls, text="10cm 확대", command=lambda: dashboard._set_full_view(False),
        bg="#17576a", fg=ui.C_WHITE, relief=ui.tk.FLAT, font=("Segoe UI", 10), padx=8, pady=5)
    dashboard.detail_view_button.pack(side=ui.tk.LEFT)
    root.title("D2 두 대 USB GUI 시험 · 안전 감시/신고 비활성")
    for number, side, card in ((1, "left", dashboard.lidar_l), (2, "right", dashboard.lidar_r)):
        card._title = f"USB {number} ({receiver.ports[side]})"
        if side in receiver.channels:
            card._title += f" · CH{receiver.channels[side]}"
        card.set_mode("3D")
    dashboard.term.append("USB 3D 표시 시험입니다. 실제 안전 감시와 보호자 알림은 실행하지 않습니다.", "SYSTEM")
    for side, port in receiver.ports.items():
        dashboard.term.append(f"{side}: {port}, {receiver.baud} bps", "SYSTEM")
    return dashboard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list ports without opening a device")
    parser.add_argument("--left", help="left D2 COM port")
    parser.add_argument("--right", help="right D2 COM port")
    parser.add_argument("--baud", type=int, choices=(3000000, 921600, 115200, 57600), default=3000000)
    parser.add_argument("--passive", action="store_true", help="read only, without start/stop commands")
    parser.add_argument("--left-channel", type=int, choices=range(16), help="USB1 frequency channel (default: 0)")
    parser.add_argument("--right-channel", type=int, choices=range(16), help="USB2 frequency channel (default: 1)")
    parser.add_argument("--keep-channels", action="store_true", help="leave sensor channels unchanged")
    parser.add_argument("--duration", type=float)
    args = parser.parse_args()
    explicit_channels = args.left_channel is not None or args.right_channel is not None
    if (args.passive or args.keep_channels) and explicit_channels:
        parser.error("Channel overrides cannot be used with --passive or --keep-channels")
    channels = {} if args.passive or args.keep_channels else {
        "left": 0 if args.left_channel is None else args.left_channel,
        "right": 1 if args.right_channel is None else args.right_channel}
    try:
        import serial.tools.list_ports
    except ImportError:
        parser.error("Install dependencies: python -m pip install pyserial numpy")
    if args.list:
        ports = list(serial.tools.list_ports.comports())
        for port in ports:
            usb = f"USB {port.vid:04X}:{port.pid:04X}" if port.vid is not None and port.pid is not None else "non-USB/system port"
            print(f"{port.device}: {port.description} ({usb})")
        if not ports:
            print("No serial ports detected")
        return 0
    if not args.left or not args.right:
        parser.error("Specify both --left COMx and --right COMy")
    if args.left.casefold() == args.right.casefold():
        parser.error("Left and right ports must be different")
    present = {port.device.casefold() for port in serial.tools.list_ports.comports()}
    if any(port.casefold() not in present for port in (args.left, args.right)):
        parser.error("A selected port is not connected; run --list again")
    import tkinter as tk
    receiver = UsbReceiver({"left": args.left, "right": args.right}, args.baud, args.passive, channels=channels)
    root = tk.Tk()
    create_dashboard(root, receiver)
    def report():
        for side in ("left", "right"):
            print(f"{receiver.ports[side]}: {receiver.stats(side)}", flush=True)
        root.after(5000, report)
    root.after(5000, report)
    if args.duration is not None:
        root.after(max(1, int(args.duration * 1000)), root.destroy)
    try:
        root.mainloop()
    finally:
        receiver.stop()
        for side in ("left", "right"):
            print(f"{receiver.ports[side]}: {receiver.stats(side)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
