"""Offline 3D scenes. No sensors, sockets, alerts or commands are started.

python tools/preview_lidar_3d.py --dashboard --size 1024x600
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui
from lidar_preview import PreviewSnapshot
from jetson.walker_preview.sampling import sample_xyz
from schema import SystemStatus, ImuSample, GpsFix, ObstacleReport
from states import CONN_OK, TIPOVER_NORMAL, TIPOVER_REPORTED


def scene_points(scene):
    if scene == "empty":
        return ()
    points = []
    for i in range(30):
        x = 0.45 + i * 0.043
        for j in range(30):
            y = (j - 14.5) * 0.043
            z = -0.45
            if x >= 1.05 and scene in ("rise", "drop"):
                z += 0.20 if scene == "rise" else -0.20
            points.append([x, y, z])
    if scene in ("rise", "drop"):
        for j in range(30):
            for k in range(8):
                points.append([1.05, (j - 14.5) * 0.043,
                               -0.45 + (1 if scene == "rise" else -1) * k * 0.025])
    if scene == "wall":
        for j in range(30):
            for k in range(24):
                points.append([1.35, (j - 14.5) * 0.043, -0.45 + k * 0.035])
    return tuple(tuple(value / 1000.0 for value in point) for point in sample_xyz(points))


class DemoReceiver:
    def __init__(self, **_kwargs):
        self.error = None
        self.scene = "rise"
        self.right_scene = "drop"
    def start(self):
        return True
    def stop(self):
        pass
    def snapshot(self, side):
        if self.scene == "missing":
            return PreviewSnapshot()
        if self.scene == "stale" or (self.scene == "one_side" and side == "right"):
            return PreviewSnapshot(status="stale")
        scene = self.scene if side == "left" else self.right_scene
        if scene == "one_side":
            scene = "flat"
        if self.scene == "empty":
            scene = "empty"
        points = scene_points(scene)
        return PreviewSnapshot(points, "live" if points else "empty", True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--size", default=None)
    parser.add_argument("--scene", choices=("flat", "rise", "drop", "wall", "empty", "one_side",
                                            "missing", "stale"), default="rise")
    parser.add_argument("--reported", action="store_true")
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--monitor-lost", action="store_true")
    parser.add_argument("--notification-state", default="accepted",
                        choices=("queued", "sending", "accepted", "failed", "unconfigured"))
    parser.add_argument("--duration", type=float, help="close the offline preview after N seconds")
    parser.add_argument("--check-layout", action="store_true")
    args = parser.parse_args()
    receiver = DemoReceiver()
    receiver.scene = args.scene
    root = tk.Tk()
    root.configure(bg=ui.C_BG)
    if args.dashboard:
        status = SystemStatus(tipover_state=TIPOVER_REPORTED if args.reported else TIPOVER_NORMAL,
            notification_id="offline-preview-only", notification_state=args.notification_state,
            imu=ImuSample(valid=True, status=CONN_OK, accel_g=1.01, roll_deg=1.2, pitch_deg=0.8),
            gps=GpsFix(valid=True, status=CONN_OK, fix_quality=4, lat=35.1595, lon=126.8526,
                       satellites=18, hdop=0.7, utc="03:25:00"),
            obstacle=ObstacleReport(left_m=1.25, right_m=2.10, left_ok=True, right_ok=True,
                                    link_ok=True, left_points_xy=[[1.25, 0.2]],
                                    right_points_xy=[[2.1, -0.2]], preview_simulated=True))
        class StatusDemo:
            def start(self): pass
            def stop(self): pass
            def latest(self): return status, not args.monitor_lost
        class CommandDemo:
            def send(self, _command): pass
        ui.StatusSubscriber = StatusDemo
        ui.CommandSender = CommandDemo
        ui.PreviewReceiver = lambda **_kwargs: receiver
        ui.MAP_AVAILABLE = False  # Offline preview must not download map tiles.
        os.environ["WALKER_UI_FULLSCREEN"] = "0"
        dashboard = ui.Dashboard(root)
        dashboard.term.append("모의 화면 — 센서·알림·명령 전송 없음", "SYSTEM")
        left, right = dashboard.lidar_l, dashboard.lidar_r
        root.title("보행 보조 대시보드 · 모의 3D · 알림 전송 없음")
        if args.size:
            root.geometry(args.size)
    else:
        root.title("좌우 LiDAR 3D 미리보기 · 모의 데이터")
        root.geometry(args.size or "1280x380")
        root.minsize(1024, 380)
        controls = tk.Frame(root, bg=ui.C_BG)
        controls.pack(fill=tk.X, padx=14, pady=8)
        body = tk.Frame(root, bg=ui.C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
        body.columnconfigure(0, weight=1, uniform="cards")
        body.columnconfigure(1, weight=1, uniform="cards")
        body.rowconfigure(0, weight=1)
        left, right = ui.LidarCard(body, "왼쪽 LiDAR"), ui.LidarCard(body, "오른쪽 LiDAR")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        left.update_card(1.25, True, True, [[1.25, 0.2]], True)
        right.update_card(2.10, True, True, [[2.1, -0.2]], True)
        def change(scene):
            receiver.scene = receiver.right_scene = scene
        for text, scene in (("평평한 바닥", "flat"), ("올라가는 턱", "rise"), ("내려가는 단차", "drop"),
                            ("벽", "wall"), ("빈 프레임", "empty"), ("오른쪽 중단", "one_side"),
                            ("3D 없음", "missing")):
            tk.Button(controls, text=text, command=lambda s=scene: change(s),
                      bg=ui.C_CARD, fg=ui.C_WHITE, relief=tk.FLAT, pady=6).pack(side=tk.LEFT, padx=(0, 6))
        def refresh():
            left.update_3d(receiver.snapshot("left"))
            right.update_3d(receiver.snapshot("right"))
            root.after(100, refresh)
        refresh()
    if args.check_layout:
        def check_layout():
            root.update_idletasks()
            checked = []
            def check(widget, name):
                assert widget.winfo_ismapped(), f"Hidden widget: {name}"
                child = widget
                while child is not root:
                    parent = child.nametowidget(child.winfo_parent())
                    x, y = child.winfo_x(), child.winfo_y()
                    assert x >= 0 and y >= 0, f"Negative position: {name}"
                    assert x + child.winfo_width() <= parent.winfo_width(), f"Width clipped: {name}"
                    assert y + child.winfo_height() <= parent.winfo_height(), f"Height clipped: {name}"
                    child = parent
                checked.append(name)
            for name, card in (("left", left), ("right", right)):
                if card.show_distance:
                    check(card.dist, name + " distance")
                else:
                    assert not card.dist.winfo_ismapped(), name + " distance must stay hidden"
                check(card.preview_3d, name + " 3D canvas")
                if card.show_controls:
                    for button in card.mode_buttons.values():
                        check(button, name + " mode " + button.cget("text"))
                    for button in card.views.winfo_children():
                        check(button, name + " view " + button.cget("text"))
                card.set_mode("2D")
                root.update_idletasks()
                check(card.preview, name + " 2D canvas")
                card.set_mode("3D")
            if args.dashboard:
                check(dashboard.sos_button, "SOS")
                check(dashboard.sos_status, "SOS result")
                check(dashboard.details_button, "Details toggle")
                check(dashboard.overall, "Overall warning")
                check(dashboard.clock, "Large clock")
                assert int(dashboard.clock.cget("width")) == 8, "Clock width must stay fixed"
                for value, button in dashboard.grid_size_buttons.items():
                    check(button, f"Zoom grid {value}cm")
                assert not dashboard.header_controls.winfo_ismapped(), "Selection toolbar must stay hidden"
                assert dashboard.current_view == "front", "Default camera must be front"
                assert left.mode == right.mode == "3D", "Default view changed"
                assert left.preview_3d.winfo_height() >= 130, (
                    f"3D plot is too short: {left.preview_3d.winfo_height()} px; "
                    f"SOS {dashboard.sos_button.winfo_height()} px; "
                    f"recovery {dashboard.recovery_panel.winfo_height()} px")
                dashboard._toggle_details()
                root.update_idletasks()
                for name, value in dashboard.imu_card.vals.items():
                    check(value, "IMU " + name)
                check(dashboard.gps_card.coord, "GPS coordinates")
                check(dashboard.sos_button, "Details SOS")
                check(dashboard.term.txt, "System log")
                if args.reported:
                    check(dashboard.recovery_button, "Recovery")
                if not args.details:
                    dashboard._toggle_details()
                    root.update_idletasks()
                    check(dashboard.lidar_l.preview_3d, "Restored 3D canvas")
            print(json.dumps({"size": [root.winfo_width(), root.winfo_height()], "checked": checked},
                             ensure_ascii=False), flush=True)
            root.destroy()
        def fail_on_callback(_exc_type, exc, _traceback):
            print(f"Layout failed: {exc}", file=sys.stderr, flush=True)
            root.destroy()
            raise SystemExit(1)
        root.report_callback_exception = fail_on_callback
        root.after(350, check_layout)
    elif args.dashboard and args.details:
        dashboard._toggle_details()
    if args.duration is not None:
        root.after(max(1, int(args.duration * 1000)), root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
