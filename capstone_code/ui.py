"""
ui — 대시보드 (읽기 전용)

★ 이 프로세스에는 판정 로직이 한 줄도 없다.
  safety_monitor가 UDP로 보내주는 상태를 그리기만 하고,
  사용자 버튼 입력만 되돌려 보낸다.
  → 이 창을 닫아도, 멈춰도, 죽어도 전도 감지는 계속 동작한다.

이전 버전(legacy/main_controller.py) 대비 수정:
  [규칙①] 판정·신고 로직을 전부 tipover_monitor / notifier로 이관
  [H4] 화면 깜박임과 전도 확인 팝업이 서로를 가리던 충돌 해결
  [H5] 배터리가 항상 100%로 표시되던 문제 → 실측 불가 시 "측정 안 됨"
  [M1] 스레드에서 tkinter를 건드리던 문제 → 상태는 폴링으로만 읽는다
  [M2] 지도를 초당 10회 재중심시키던 문제 → 위치 변화 시 최대 1 Hz
  [M9] 종료 처리 추가

실행: python ui.py   (safety_monitor.py 가 먼저 떠 있어야 한다)
"""
import os
import math
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext

import config
import console
from states import (CMD_RESET, CMD_USER_NO, CMD_USER_YES, CONN_ERROR,
                    CONN_STALE, TIPOVER_ASKING, TIPOVER_CONFIRMED, TIPOVER_DISPLAY, TIPOVER_NORMAL,
                    TIPOVER_REPORTED, LEVEL_DANGER, LEVEL_OK, LEVEL_WARN,
                    fix_quality_name)
from buttons import CMD_SOS
from status_link import CommandSender, StatusSubscriber
from lidar_preview import PreviewReceiver
from lidar_preview_view import Lidar3DPreview

console.setup()

try:
    import tkintermapview
    MAP_AVAILABLE = True
except ImportError:
    MAP_AVAILABLE = False

C_BG, C_CARD, C_TERM_BG, C_BORDER = "#0d1519", "#172329", "#0a1115", "#334852"
C_BLUE, C_GREEN, C_YELLOW, C_RED = "#00d4ff", "#00ff88", "#ffaa00", "#ff3333"
C_GRAY, C_WHITE, C_DIMWHITE, C_HEADER_BG = "#555555", "#eeeeee", "#888888", "#111111"
C_FLASH_ON = "#ff0000"


def level_color(lv):
    return C_RED if lv == LEVEL_DANGER else C_YELLOW if lv == LEVEL_WARN else C_GREEN


def level_text(lv):
    return "위험" if lv == LEVEL_DANGER else "경고" if lv == LEVEL_WARN else "OK"


def dist_to_level(d):
    if d is None:
        return LEVEL_OK
    if d <= config.DIST_DANGER_M:
        return LEVEL_DANGER
    return LEVEL_WARN if d <= config.DIST_WARN_M else LEVEL_OK


# ══════════════════════════════════════════════════════════
# 위젯
# ══════════════════════════════════════════════════════════
class FlashOverlay:
    """위험 배너의 테두리만 점멸한다. SOS와 점군을 가리지 않는다."""
    FLASH_MS = 300
    ALPHA = 0.35

    def __init__(self, root, target):
        self.root = root
        self.target = target
        self._active = False
        self._visible = False
        self._after = None

    def _tick(self):
        if not self._active:
            return
        self._visible = not self._visible
        self.target.config(highlightbackground=C_RED if self._visible else C_BORDER)
        self._after = self.root.after(self.FLASH_MS, self._tick)

    def start(self):
        if self._active:
            return
        self._active, self._visible = True, False
        self._tick()

    def stop(self):
        self._active = False
        if self._after:
            self.root.after_cancel(self._after)
            self._after = None
        self.target.config(highlightbackground=C_BORDER)
        self._visible = False

    @property
    def active(self):
        return self._active


class BatteryWidget(tk.Canvas):
    def __init__(self, parent, width=90, height=28, bg=C_HEADER_BG):
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0)
        self.w, self.h = width, height

    def update_battery(self, percent, charging):
        self.delete("all")
        # [H5] Pi 5에는 BAT0가 없다. 실측 수단이 붙기 전까지 100%를 그리지 않는다.
        #      틀린 계기판은 없는 계기판보다 나쁘다.
        if percent is None:
            self.create_text(self.w / 2, self.h / 2, text="배터리 측정 안 됨",
                             fill=C_GRAY, font=("Segoe UI", 8))
            return
        pad, tip = 3, 4
        bw = self.w - pad - tip
        color = C_RED if percent <= 20 else C_YELLOW if percent <= 50 else C_GREEN
        self.create_rectangle(pad, pad, bw, self.h - pad, outline="#777", width=2)
        self.create_rectangle(bw, self.h / 2 - 5, self.w - 2, self.h / 2 + 5,
                              fill="#777", outline="")
        fw = max(0, (bw - pad - 2) * (percent / 100.0))
        if fw:
            self.create_rectangle(pad + 2, pad + 2, pad + 2 + fw, self.h - pad - 1,
                                  fill=color, outline="")
        self.create_text(bw / 2 + pad, self.h / 2,
                         text=f"{'⚡' if charging else ''}{int(percent)}%",
                         fill="#000", font=("Segoe UI", 9, "bold"))


class LidarPreview(tk.Canvas):
    """센서 기준 표시 전용 평면도. 안전 판정 입력으로 사용하지 않는다."""
    RANGE_M = 4.0

    def __init__(self, parent):
        super().__init__(parent, bg="#101b20", width=260, height=172,
                         highlightthickness=0)
        self._data = (None, False, False, False)
        self.bind("<Configure>", lambda _e: self._draw())

    def update_scan(self, points, ok, link_ok, simulated=False):
        data = (points, ok, link_ok, simulated)
        if data != self._data:
            self._data = data
            self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20 or h < 20:
            return
        points, ok, link_ok, simulated = self._data
        ox, oy = w / 2, h - 22
        scale = min((w - 26) / (2 * self.RANGE_M), (h - 48) / self.RANGE_M)
        self.create_text(w / 2, 12, text="전방 ↑ · 센서 기준 · 4 m",
                         fill=C_DIMWHITE, font=("Segoe UI", 8))
        for distance in (1.0, 2.0, 3.0, 4.0):
            radius = distance * scale
            self.create_arc(ox-radius, oy-radius, ox+radius, oy+radius,
                            start=0, extent=180, style=tk.ARC, outline="#29414a")
            self.create_text(ox + 6, oy-radius + 6, text=f"{distance:g}m",
                             anchor="w", fill="#66818a", font=("Segoe UI", 7))
        for distance, color in ((config.DIST_WARN_M, "#675124"),
                                (config.DIST_DANGER_M, "#713232")):
            radius = distance * scale
            self.create_arc(ox-radius, oy-radius, ox+radius, oy+radius,
                            start=0, extent=180, style=tk.ARC, outline=color, dash=(3, 3))
        self.create_line(ox, 25, ox, oy, fill="#29414a", dash=(3, 4))
        self.create_polygon(ox, oy-7, ox-6, oy+5, ox+6, oy+5,
                            fill=C_BLUE, outline="")
        self.create_text(ox, h-8, text="센서", fill=C_BLUE, font=("Segoe UI", 8))
        self.create_text(12, oy-6, text="좌", fill=C_DIMWHITE, font=("Segoe UI", 8))
        self.create_text(w-12, oy-6, text="우", fill=C_DIMWHITE, font=("Segoe UI", 8))

        message = None
        if not link_ok:
            message = "연결 끊김 · 그림 표시 불가"
        elif not ok:
            message = "센서 응답 없음"
        elif points is None:
            message = "거리만 수신 · 그림 데이터 없음"
        elif not points:
            message = "이번 측정에 유효 점 없음"
        if message:
            self.create_rectangle(8, h/2-18, w-8, h/2+18, fill="#101b20", outline="")
            self.create_text(w/2, h/2, text=message,
                             fill=C_RED if not (ok and link_ok) else C_DIMWHITE,
                             font=("Segoe UI", 9))
            return

        outside = 0
        for x, y in points:
            distance = math.hypot(x, y)
            if distance > self.RANGE_M:
                outside += 1
                continue
            px, py = ox - y * scale, oy - x * scale
            self.create_oval(px-2.5, py-2.5, px+2.5, py+2.5,
                             fill=level_color(dist_to_level(distance)), outline="", tags="scan_point")
        caption = "모의 점군" if simulated else "측정 윤곽"
        if outside:
            caption += f" · 4m 밖 {outside}점"
        self.create_text(w-8, 29, text=caption, anchor="e",
                         fill=C_YELLOW if simulated else C_BLUE, font=("Segoe UI", 8))


class LidarCard(tk.Frame):
    def __init__(self, parent, title, show_controls=True, show_distance=True, **kw):
        super().__init__(parent, bg=C_CARD, bd=0, highlightthickness=2,
                         highlightbackground=C_BORDER, **kw)
        self.show_controls = show_controls
        self.show_distance = show_distance
        self._title = title
        header = tk.Frame(self, bg=C_CARD)
        header.pack(fill=tk.X, padx=12, pady=(8, 4))
        self.title_label = tk.Label(header, text=title, bg=C_CARD, fg=C_WHITE,
                                    font=("Segoe UI", 13, "bold"))
        self.title_label.pack(side=tk.LEFT)
        self.badge = tk.Label(header, text=" 연결 대기중 ", bg=C_GRAY, fg=C_WHITE,
                              font=("Segoe UI", 10, "bold"), padx=8, pady=3)
        self.badge.pack(side=tk.RIGHT)
        distance_row = tk.Frame(self, bg=C_CARD)
        self.distance_row = distance_row
        if show_distance:
            distance_row.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(4, 8))
        tk.Label(distance_row, text="장애물 거리 · 기존 판정값", bg=C_CARD, fg=C_DIMWHITE,
                 font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.dist = tk.Label(distance_row, text="-", bg=C_CARD, fg=C_GRAY,
                             font=("Segoe UI", 25, "bold"))
        self.dist.pack(side=tk.RIGHT)
        content = tk.Frame(self, bg=C_CARD)
        content.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 2))
        visual = tk.Frame(content, bg=C_CARD)
        visual.pack(fill=tk.BOTH, expand=True)
        modes = tk.Frame(visual, bg=C_CARD)
        if show_controls:
            modes.pack(fill=tk.X)
        self.mode_buttons = {}
        for mode in ("3D", "2D"):
            button = tk.Button(modes, text=mode, bg=C_CARD, fg=C_WHITE,
                               font=("Segoe UI", 9, "bold"), relief=tk.FLAT,
                               padx=12, pady=5, command=lambda m=mode: self.set_mode(m))
            button.pack(side=tk.LEFT, padx=(0, 4))
            self.mode_buttons[mode] = button
        self.views = tk.Frame(visual, bg=C_CARD)
        for text, view in (("정면", "front"), ("사선", "oblique"), ("위", "top"), ("옆", "side")):
            tk.Button(self.views, text=text, command=lambda v=view: self.preview_3d.set_view(v),
                      bg="#26343a", fg=C_WHITE, relief=tk.FLAT,
                      font=("Segoe UI", 8), padx=6, pady=5).pack(side=tk.LEFT, padx=(0, 4))
        self.display = tk.Frame(visual, bg=C_CARD)
        self.display.pack(fill=tk.BOTH, expand=True)
        self.preview = LidarPreview(self.display)
        self.preview_3d = Lidar3DPreview(self.display)
        self.set_mode("3D")

    def set_mode(self, mode):
        if mode not in ("2D", "3D"):
            raise ValueError("Unknown LiDAR display mode")
        self.mode = mode
        self.title_label.config(text=f"{self._title} · {mode}")
        self.preview.pack_forget()
        self.preview_3d.pack_forget()
        self.views.pack_forget()
        for key, button in self.mode_buttons.items():
            button.config(bg="#17576a" if key == mode else C_CARD)
        if mode == "3D":
            if self.show_controls:
                self.views.pack(side=tk.BOTTOM, fill=tk.X)
            self.preview_3d.pack(fill=tk.BOTH, expand=True)
        else:
            self.preview.pack(fill=tk.BOTH, expand=True)

    def update_3d(self, snapshot):
        self.preview_3d.update_snapshot(snapshot)

    def update_card(self, d, ok, link_ok, points=None, simulated=False):
        self.preview.update_scan(points, ok, link_ok, simulated)
        if not link_ok:
            self._flat("  링크 끊김  ", C_RED, "센서 이상")
            return
        if not ok:
            self._flat("  연결 실패  ", C_RED, "연결 안됨")
            return
        lv = dist_to_level(d)
        color = level_color(lv)
        self.badge.config(text=f"  {level_text(lv)}  ", bg=color,
                          fg="#fff" if lv == LEVEL_DANGER else "#000")
        self.config(highlightbackground=color)
        self.dist.config(text="감지 없음" if d is None else f"{d:.2f} m", fg=color)

    def _flat(self, badge, color, text):
        self.badge.config(text=badge, bg=color, fg=C_WHITE)
        self.config(highlightbackground=color)
        self.dist.config(text=text, fg=color)


class IMUCard(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C_CARD, bd=0, highlightthickness=2,
                         highlightbackground=C_BORDER, **kw)
        tk.Label(self, text="IMU / 전도 감지", bg=C_CARD, fg=C_BLUE,
                 font=("Segoe UI", 11, "bold")).pack(pady=(8, 4))
        self.badge = tk.Label(self, text=" 연결 대기중 ", bg=C_GRAY, fg=C_WHITE,
                              font=("Segoe UI", 12, "bold"), padx=12, pady=3)
        self.badge.pack(pady=(0, 4))
        self.state_lbl = tk.Label(self, text="-", bg=C_CARD, fg=C_GRAY,
                                  font=("Segoe UI", 18, "bold"))
        self.state_lbl.pack(pady=(0, 2))
        info = tk.Frame(self, bg=C_CARD)
        info.pack(pady=(0, 4))
        self.vals = {}
        for i, key in enumerate(("Roll", "Pitch", "충격")):
            tk.Label(info, text=f"{key}:", bg=C_CARD, fg=C_DIMWHITE,
                     font=("Segoe UI", 8)).grid(row=i, column=0, padx=3, sticky="e")
            v = tk.Label(info, text="-", bg=C_CARD, fg=C_WHITE,
                         font=("Segoe UI", 8, "bold"))
            v.grid(row=i, column=1, padx=3, sticky="w")
            self.vals[key] = v

    def update_card(self, imu, tipover_state):
        if imu.status in (CONN_ERROR, CONN_STALE) or not imu.valid:
            txt = "응답 없음" if imu.status == CONN_STALE else "연결 안됨"
            self.set_unavailable(txt)
            return
        cfg = TIPOVER_DISPLAY.get(tipover_state)
        if cfg:
            b_txt, b_bg, b_fg, s_txt = cfg
            self.badge.config(text=b_txt, bg=b_bg, fg=b_fg)
            self.state_lbl.config(text=s_txt, fg=b_bg)
            self.config(highlightbackground=C_BORDER if tipover_state == TIPOVER_NORMAL else b_bg)
        self.vals["Roll"].config(text=f"{imu.roll_deg:.1f}°")
        self.vals["Pitch"].config(text=f"{imu.pitch_deg:.1f}°")
        self.vals["충격"].config(text=f"{imu.accel_g:.2f}g")

    def set_unavailable(self, text):
        self.badge.config(text=f"  {text}  ", bg=C_RED, fg=C_WHITE)
        self.state_lbl.config(text=text, fg=C_RED)
        self.config(highlightbackground=C_RED)
        for value in self.vals.values():
            value.config(text="-")


class GPSCard(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C_CARD, bd=0, highlightthickness=2,
                         highlightbackground=C_BORDER, **kw)
        tk.Label(self, text="🛰️  GPS & 트래킹", bg=C_CARD, fg=C_BLUE,
                 font=("Segoe UI", 11, "bold")).pack(pady=(14, 4))
        self.badge = tk.Label(self, text=" 연결 대기중 ", bg=C_GRAY, fg=C_WHITE,
                              font=("Segoe UI", 10, "bold"), padx=10, pady=3)
        self.badge.pack(pady=(0, 4))
        self.detail = tk.Label(self, text="-", bg=C_CARD, fg=C_DIMWHITE,
                               font=("Segoe UI", 8))
        self.detail.pack(pady=(0, 6))
        self.coord = tk.Label(self, text="Lat: -   Lon: -", bg=C_CARD, fg=C_WHITE,
                              font=("Segoe UI", 9, "bold"))
        self.coord.pack(pady=(0, 8))

        self._last_pos = None
        self._last_map_t = 0.0
        self.marker = None
        if MAP_AVAILABLE:
            self.map = tkintermapview.TkinterMapView(self, corner_radius=0)
            self.map.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
            self.map.set_zoom(15)
            self.map.set_position(35.1595, 126.8526)
            self.marker = None
        else:
            c = tk.Label(self, bg="#111", fg=C_DIMWHITE, bd=0, highlightthickness=1,
                         highlightbackground="#333", text="지도 표시 불가", wraplength=170,
                         font=("Segoe UI", 9))
            c.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

    def update_card(self, gps):
        if not gps.valid:
            txt = "응답 없음" if gps.status == CONN_STALE else "연결 안됨"
            self.set_unavailable(txt)
            return

        q = gps.fix_quality
        # RTK 고정(4)일 때만 계획서가 주장하는 cm급 정밀도가 성립한다
        if q == 4:
            bg, txt = C_GREEN, "RTK 고정"
        elif q in (2, 5):
            bg, txt = C_YELLOW, fix_quality_name(q)
        elif q == 1:
            bg, txt = C_YELLOW, "단독측위"
        else:
            bg, txt = C_GRAY, "측위 대기"
        self.badge.config(text=f"  {txt}  ", bg=bg, fg="#000")
        self.config(highlightbackground=bg if q else C_BORDER)
        hdop = f"{gps.hdop:.1f}" if gps.hdop is not None else "-"
        self.detail.config(text=f"위성 {gps.satellites}개 · HDOP {hdop} "
                                f"· UTC {gps.utc or '-'}")

        if not gps.has_position or not q:
            self._clear_position()
            return
        self.coord.config(text=f"Lat: {gps.lat:.6f}\nLon: {gps.lon:.6f}", fg=C_WHITE)

        # [M2] 초당 10회 재중심 → 위치가 실제로 바뀐 경우에만, 최대 1 Hz
        if not MAP_AVAILABLE:
            return
        now = time.time()
        pos = (round(gps.lat, 6), round(gps.lon, 6))
        if pos != self._last_pos and (now - self._last_map_t) >= 1.0:
            self._last_pos, self._last_map_t = pos, now
            self.map.set_position(gps.lat, gps.lon)
            if self.marker is None:
                self.marker = self.map.set_marker(gps.lat, gps.lon, text="현재 위치")
            else:
                self.marker.set_position(gps.lat, gps.lon)

    def _clear_position(self):
        self.coord.config(text="현재 위치 확인 불가", fg=C_GRAY)
        if self.marker is not None:
            self.marker.delete()
            self.marker = None
        self._last_pos = None
        self._last_map_t = 0.0

    def set_unavailable(self, text):
        self.badge.config(text=f"  {text}  ", bg=C_RED, fg=C_WHITE)
        self.config(highlightbackground=C_RED)
        self.detail.config(text="-")
        self._clear_position()


class TerminalCard(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C_TERM_BG, bd=0, highlightthickness=2,
                         highlightbackground=C_BORDER, **kw)
        hdr = tk.Frame(self, bg="#222", height=30)
        hdr.pack(fill=tk.X, side=tk.TOP)
        hdr.pack_propagate(False)
        tk.Label(hdr, text=">_ 시스템 터미널", bg="#222", fg=C_WHITE,
                 font=("Consolas", 10, "bold")).pack(side=tk.LEFT, padx=10)
        self.txt = scrolledtext.ScrolledText(self, bg=C_TERM_BG, fg=C_GREEN,
                                             font=("Consolas", 9), wrap=tk.WORD,
                                             state=tk.DISABLED, bd=0, width=1, height=1)
        self.txt.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        for tag, col in (("INFO", "#00ff88"), ("WARN", "#ffaa00"),
                         ("ERROR", "#ff3333"), ("SYSTEM", "#00d4ff")):
            self.txt.tag_config(tag, foreground=col)

    def append(self, msg, level="INFO"):
        self.txt.config(state=tk.NORMAL)
        self.txt.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n", level)
        self.txt.see(tk.END)
        self.txt.config(state=tk.DISABLED)


# ══════════════════════════════════════════════════════════
# 메인 창
# ══════════════════════════════════════════════════════════
class Dashboard:
    REFRESH_MS = 100

    def __init__(self, root, *, status_subscriber=None, command_sender=None, preview_receiver=None):
        self.root = root
        root.title("노약자 보행 보조 시스템 — 대시보드")
        root.configure(bg=C_BG)
        root.geometry("1024x600")
        root.minsize(1024, 600)
        fullscreen = os.environ.get("WALKER_UI_FULLSCREEN")
        if fullscreen == "1" or (fullscreen is None and
                root.winfo_screenwidth() == 1024 and root.winfo_screenheight() == 600):
            root.attributes("-fullscreen", True)

        self.sub = status_subscriber if status_subscriber is not None else StatusSubscriber()
        self.sub.start()
        self.cmd = command_sender if command_sender is not None else CommandSender()
        self.preview_sub = preview_receiver if preview_receiver is not None else PreviewReceiver(
            port=os.environ.get("WALKER_PREVIEW_PORT", getattr(config, "UDP_PREVIEW_PORT", 9103)),
            bind_host=os.environ.get("WALKER_PREVIEW_BIND", getattr(config, "UDP_PREVIEW_BIND", "127.0.0.1")))
        self.preview_sub.start()

        self._popup = None
        self._flashing = False
        self._last_notice = None
        self._link_warned = False
        self._reset_requested_at = None
        self._sos_requested_at = None
        self._sos_unconfirmed = False
        self._details_visible = False
        self.current_view = "front"
        self.display_mode = "3D"
        self.grid_size_cm = 10

        self._build()
        root.update_idletasks()
        self.flash = FlashOverlay(root, self.status_banner)
        root.protocol("WM_DELETE_WINDOW", self._on_close)   # [M9]
        root.bind("<F11>", self._toggle_fullscreen)
        root.bind("<Escape>", self._escape)
        root.bind("<Configure>", self._resize_labels, add="+")

        self.term.append("대시보드 시작 — safety_monitor 연결 대기", "SYSTEM")
        if self.preview_sub.error:
            self.term.append("3D 수신 포트 사용 불가 — 기존 안전 감시는 계속됩니다", "WARN")
        self._refresh()

    def _build(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)
        hdr = tk.Frame(self.root, bg=C_HEADER_BG)
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(6, 4))
        hdr.columnconfigure(0, weight=1)
        self.header_title = tk.Frame(hdr, bg=C_HEADER_BG)
        self.header_title.grid(row=0, column=0, sticky="new")
        tk.Label(self.header_title, text="보행기 안전 도우미", bg=C_HEADER_BG, fg=C_WHITE,
                 font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT, padx=(8, 12), pady=(4, 2))
        self.batt = BatteryWidget(self.header_title)
        self.batt.pack(side=tk.RIGHT, padx=8)
        self.clock = tk.Label(hdr, text=time.strftime("%H:%M:%S"), bg="#101b20", fg="#ffffff",
                              font=("Consolas", 30, "bold"), width=8,
                              padx=12, pady=6, highlightthickness=1, highlightbackground=C_BORDER)
        self.clock.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(12, 0))
        self.scale_controls = tk.Frame(hdr, bg=C_HEADER_BG)
        self.scale_controls.grid(row=1, column=0, sticky="w", padx=8, pady=(2, 0))
        tk.Label(self.scale_controls, text="화면 확대", bg=C_HEADER_BG, fg=C_WHITE,
                 font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        self.grid_size_buttons = {}
        for centimeters in (1, 5, 10):
            button = tk.Button(self.scale_controls, text=f"{centimeters}cm", width=5,
                               bg=C_CARD, fg=C_WHITE, relief=tk.FLAT,
                               font=("Segoe UI", 10, "bold"), pady=3,
                               command=lambda value=centimeters: self._set_grid_size_cm(value))
            button.pack(side=tk.LEFT, padx=(0, 5))
            self.grid_size_buttons[centimeters] = button
        tk.Label(self.scale_controls, text="한 칸의 실제 거리", bg=C_HEADER_BG, fg=C_DIMWHITE,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(6, 0))
        self.header_controls = tk.Frame(hdr, bg=C_HEADER_BG)
        self.view_buttons = {}
        views = tk.Frame(self.header_controls, bg=C_HEADER_BG)
        views.pack(side=tk.LEFT, padx=(0, 8))
        for text, view in (("정면", "front"), ("사선", "oblique"), ("위", "top"), ("옆", "side")):
            button = tk.Button(views, text=text, bg="#263d47", fg=C_WHITE,
                               relief=tk.FLAT, font=("Segoe UI", 11), padx=8, pady=5,
                               command=lambda v=view: self._set_view(v))
            button.pack(side=tk.LEFT, padx=2)
            self.view_buttons[view] = button
        self.display_mode_buttons = {}
        modes = tk.Frame(self.header_controls, bg=C_HEADER_BG)
        modes.pack(side=tk.LEFT, before=views, padx=(6, 8))
        for mode in ("3D", "2D"):
            button = tk.Button(modes, text=mode, bg=C_CARD, fg=C_WHITE,
                               relief=tk.FLAT, font=("Segoe UI", 11, "bold"),
                               padx=8, pady=5, command=lambda m=mode: self._set_display_mode(m))
            button.pack(side=tk.LEFT, padx=2)
            self.display_mode_buttons[mode] = button

        self.status_banner = tk.Frame(self.root, bg=C_HEADER_BG,
                                      highlightbackground=C_BORDER, highlightthickness=2)
        self.status_banner.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        self.status_banner.columnconfigure(0, weight=1)
        self.overall = tk.Label(self.status_banner, text="●  감시 연결 대기",
                                bg=C_HEADER_BG, fg=C_GRAY, anchor="w", justify=tk.LEFT,
                                wraplength=660, font=("Segoe UI", 15, "bold"))
        self.overall.grid(row=0, column=0, sticky="ew", padx=12, pady=8)
        self.health_lbl = tk.Label(self.status_banner, text="", bg=C_HEADER_BG,
                                   fg=C_DIMWHITE, font=("Segoe UI", 10), wraplength=250)
        self.health_lbl.grid(row=0, column=1, sticky="e", padx=10)
        self.curb_lbl = tk.Label(self.root, text="", bg=C_BG, fg=C_DIMWHITE,
                                 anchor="w", font=("Segoe UI", 11, "bold"))
        self.curb_lbl.grid(row=2, column=0, sticky="ew", padx=16)

        self.main_panel = tk.Frame(self.root, bg=C_BG)
        self.main_panel.grid(row=3, column=0, sticky="nsew", padx=12, pady=4)
        for column in (0, 1):
            self.main_panel.columnconfigure(column, weight=1, uniform="lidar")
        self.main_panel.rowconfigure(0, weight=1)
        self.lidar_l = LidarCard(self.main_panel, "왼쪽 LiDAR", show_controls=False, show_distance=False)
        self.lidar_l.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.lidar_r = LidarCard(self.main_panel, "오른쪽 LiDAR", show_controls=False, show_distance=False)
        self.lidar_r.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        self.details_panel = tk.Frame(self.root, bg=C_BG)
        self.details_panel.rowconfigure(0, weight=1)
        for column, weight in ((0, 1), (1, 1), (2, 2)):
            self.details_panel.columnconfigure(column, weight=weight, uniform="details")
        self.imu_card = IMUCard(self.details_panel)
        self.imu_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.gps_card = GPSCard(self.details_panel)
        self.gps_card.grid(row=0, column=1, sticky="nsew", padx=(6, 6))
        self.term = TerminalCard(self.details_panel)
        self.term.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        summary = tk.Frame(self.root, bg=C_BG)
        summary.grid(row=4, column=0, sticky="ew", padx=16, pady=3)
        summary.columnconfigure(0, weight=1)
        summary.columnconfigure(1, weight=1)
        self.summary_imu = tk.Label(summary, text="전도 감시 연결 대기", bg=C_BG,
                                     fg=C_DIMWHITE, font=("Segoe UI", 11), anchor="w")
        self.summary_imu.grid(row=0, column=0, sticky="ew")
        self.summary_gps = tk.Label(summary, text="현재 위치 확인 대기", bg=C_BG,
                                     fg=C_DIMWHITE, font=("Segoe UI", 11), anchor="e")
        self.summary_gps.grid(row=0, column=1, sticky="ew")
        self.sos_status = tk.Label(self.root, text="", bg=C_BG, fg=C_DIMWHITE,
                                   wraplength=990, justify=tk.LEFT, anchor="w", font=("Segoe UI", 11))
        self.sos_status.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 3))
        actions = tk.Frame(self.root, bg=C_BG)
        actions.grid(row=6, column=0, sticky="ew", padx=12, pady=(2, 6))
        actions.columnconfigure(0, weight=4, uniform="actions")
        actions.columnconfigure(1, weight=5, uniform="actions")
        self.details_button = tk.Button(actions, text="센서 상세 보기", bg="#29414b", fg=C_WHITE,
                                        relief=tk.FLAT, font=("Segoe UI", 13, "bold"),
                                        height=1, pady=10, command=self._toggle_details)
        self.details_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.sos_button = tk.Button(actions, text="긴급 호출 · SOS", bg="#a52b3b", fg="white",
                                    relief=tk.FLAT, font=("Segoe UI", 13, "bold"),
                                    height=1, pady=10, command=self._sos)
        self.sos_button.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        # 복귀 조작은 기본/상세 화면에서 같은 위치를 유지한다.
        recovery_host = tk.Frame(self.root, bg=C_BG, height=1)
        recovery_host.grid(row=7, column=0, sticky="ew", padx=12, pady=(0, 4))
        self.recovery_panel = tk.Frame(recovery_host, bg=C_CARD, highlightthickness=1,
                                       highlightbackground=C_RED)
        self.recovery_label = tk.Label(
            self.recovery_panel, text="", bg=C_CARD, fg=C_YELLOW,
            wraplength=560, justify=tk.LEFT, font=("Segoe UI", 11))
        self.recovery_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, pady=6)
        self.recovery_button = tk.Button(
            self.recovery_panel, text="조치 완료 · 감시 재개", bg=C_GREEN, fg="#000",
            font=("Segoe UI", 12, "bold"), height=1, padx=14, pady=8,
            command=self._request_reset)
        self.recovery_button.pack(side=tk.RIGHT, padx=6, pady=4)
        self._set_display_mode("3D")
        self._set_view("front")
        self._set_grid_size_cm(10)

    def _set_grid_size_cm(self, centimeters):
        if centimeters not in (1, 5, 10):
            raise ValueError("Grid size must be 1, 5 or 10 cm")
        for card in (self.lidar_l, self.lidar_r):
            card.preview_3d.set_grid_size_cm(centimeters)
        self.grid_size_cm = centimeters
        for value, button in self.grid_size_buttons.items():
            button.config(bg="#17576a" if value == centimeters else C_CARD,
                          relief=tk.SUNKEN if value == centimeters else tk.FLAT)

    def _set_display_mode(self, mode):
        self.lidar_l.set_mode(mode)
        self.lidar_r.set_mode(mode)
        self.display_mode = mode
        for key, button in self.display_mode_buttons.items():
            button.config(bg="#17576a" if key == mode else C_CARD)

    def _set_view(self, view):
        self._set_display_mode("3D")
        self.lidar_l.preview_3d.set_view(view)
        self.lidar_r.preview_3d.set_view(view)
        self.current_view = view
        for key, button in self.view_buttons.items():
            button.config(bg="#17576a" if key == view else "#263d47")

    def _toggle_details(self):
        self._details_visible = not self._details_visible
        if self._details_visible:
            self.main_panel.grid_remove()
            self.details_panel.grid(row=3, column=0, sticky="nsew", padx=12, pady=4)
        else:
            self.details_panel.grid_remove()
            self.main_panel.grid()
        self.details_button.config(text="기본 화면" if self._details_visible else "센서 상세 보기")

    def _toggle_fullscreen(self, _event=None):
        self.root.attributes("-fullscreen", not bool(self.root.attributes("-fullscreen")))

    def _escape(self, _event=None):
        if self._details_visible:
            self._toggle_details()
        else:
            self.root.attributes("-fullscreen", False)

    def _resize_labels(self, event):
        if event.widget is self.root:
            self.overall.config(wraplength=max(350, event.width - 330))
            self.sos_status.config(wraplength=max(350, event.width - 40))

    def _update_summary(self, status, alive):
        if not alive or status is None:
            self.summary_imu.config(text="전도 감시 확인 불가", fg=C_RED)
            self.summary_gps.config(text="현재 위치 확인 불가", fg=C_RED)
            return
        imu_ok = status.imu.valid and status.imu.status not in (CONN_ERROR, CONN_STALE)
        state_text = TIPOVER_DISPLAY.get(status.tipover_state, ("", "", "", "확인 중"))[3]
        self.summary_imu.config(text="전도 감시 · " + (state_text if imu_ok else "IMU 응답 없음"),
                                fg=C_GREEN if imu_ok and status.tipover_state == TIPOVER_NORMAL else C_YELLOW if imu_ok else C_RED)
        gps_ok = status.gps.has_position and bool(status.gps.fix_quality)
        self.summary_gps.config(text="현재 위치 · " + (fix_quality_name(status.gps.fix_quality) if gps_ok else "확인 불가"),
                                fg=C_DIMWHITE if gps_ok else C_YELLOW)

    # ────────────────────────────────────────── 갱신
    def _refresh(self):
        self.clock.config(text=time.strftime("%H:%M:%S"))
        if getattr(self, "preview_sub", None) is not None:
            self.lidar_l.update_3d(self.preview_sub.snapshot("left"))
            self.lidar_r.update_3d(self.preview_sub.snapshot("right"))
        st, alive = self.sub.latest()
        self._update_recovery(st, alive)
        self._update_sos(st, alive)
        self._update_summary(st, alive)
        if not alive:
            self.lidar_l.update_card(None, False, False)
            self.lidar_r.update_card(None, False, False)
            self.imu_card.set_unavailable("감시 연결 끊김")
            self.gps_card.set_unavailable("감시 연결 끊김")
            self.curb_lbl.config(text="")
            self.curb_lbl.grid_remove()
            if not self._link_warned:
                self.term.append("⚠ safety_monitor 연결 없음 — "
                                 "python safety_monitor.py 를 실행하세요", "ERROR")
                self._link_warned = True
            self.overall.config(text="●  모니터 연결 끊김", fg=C_RED)
            self.batt.update_battery(None, False)
            last = time.strftime("%H:%M:%S", time.localtime(st.t)) if st and st.t else "없음"
            self.health_lbl.config(text=f"마지막 수신 {last}", fg=C_RED)
            self._close_popup()
            self._set_flash(False)
            self.root.after(self.REFRESH_MS, self._refresh)
            return
        if self._link_warned:
            self.term.append("safety_monitor 연결됨", "SYSTEM")
            self._link_warned = False

        if st.notice and st.notice != self._last_notice:
            self._last_notice = st.notice
            self.term.append(st.notice, "WARN")

        # 배터리·RTK 상태는 safety_monitor가 측정해 보내준 값을 그대로 쓴다.
        # UI가 직접 sysfs를 읽으면 실기(BAT0 없음)에서 또 거짓말을 하게 된다.
        h = st.health
        self.batt.update_battery(h.battery_pct, h.charging)
        bits = []
        if h.ntrip_connected:
            bits.append("RTK보정 " + ("정상" if h.ntrip_healthy else "지연"))
        if h.alerts_pending:
            bits.append(f"알림 대기열 {h.alerts_pending}건")
        if h.battery_volts:
            bits.append(f"{h.battery_volts:.1f}V")
        self.health_lbl.config(
            text="  ·  ".join(bits),
            fg=C_YELLOW if (h.alerts_pending or
                            (h.ntrip_connected and not h.ntrip_healthy))
            else C_DIMWHITE)

        obs = st.obstacle
        self.lidar_l.update_card(obs.left_m, obs.left_ok, obs.link_ok,
                                 obs.left_points_xy, obs.preview_simulated)
        self.lidar_r.update_card(obs.right_m, obs.right_ok, obs.link_ok,
                                 obs.right_points_xy, obs.preview_simulated)
        # 단차(턱) — 기획 배경의 "턱 걸림"
        if obs.curb_m is not None:
            self.curb_lbl.grid()
            kind = "내려가는 턱" if obs.curb_type == "drop" else "올라가는 턱"
            self.curb_lbl.config(
                text=f"⚠  전방 {obs.curb_m:.2f} m  {kind} 감지",
                fg=C_RED if obs.curb_type == "drop" else C_YELLOW)
        else:
            self.curb_lbl.config(text="")
            self.curb_lbl.grid_remove()

        self.imu_card.update_card(st.imu, st.tipover_state)
        self.gps_card.update_card(st.gps)

        # 팝업 (사용자 확인 요청)
        if st.tipover_state == TIPOVER_ASKING and self._popup is None:
            self._show_popup(st.ask_deadline)
        elif st.tipover_state != TIPOVER_ASKING and self._popup is not None:
            self._close_popup()

        # [H4] 팝업이 떠 있는 동안에는 깜박임을 멈춘다.
        #      장애물에 부딪혀 넘어지면 두 경고가 동시에 발생하는데,
        #      예전에는 오버레이가 팝업을 가려 '아니오' 버튼을 누를 수 없었다.
        danger = obs.link_ok and any(
            ok and d is not None and d <= config.DIST_DANGER_M
            for d, ok in ((obs.left_m, obs.left_ok), (obs.right_m, obs.right_ok)))
        # 사고 조치 버튼도 오버레이가 가리지 않게 한다.
        self._set_flash(danger and self._popup is None
                        and st.tipover_state not in (TIPOVER_CONFIRMED, TIPOVER_REPORTED))

        # 헤더 종합 상태
        if st.tipover_state == TIPOVER_REPORTED:
            self.overall.config(text="●  사고 확정 · 조치 확인 대기", fg=C_RED)
        elif st.tipover_state not in (TIPOVER_NORMAL,):
            self.overall.config(text=f"●  {st.tipover_state}", fg=C_RED)
        else:
            faults = []
            if not st.imu.valid or st.imu.status in (CONN_ERROR, CONN_STALE):
                faults.append("IMU")
            lidar_enabled = config.SIM_MODE or config.LIDAR_SOURCE != "none"
            if lidar_enabled and not (obs.link_ok and obs.left_ok and obs.right_ok):
                faults.append("LiDAR")
            distances = [d for d, ok in ((obs.left_m, obs.left_ok),
                                         (obs.right_m, obs.right_ok))
                         if lidar_enabled and obs.link_ok and ok and d is not None]
            lv = max((dist_to_level(d) for d in distances), default=LEVEL_OK)
            if lv != LEVEL_OK:
                text, color = level_text(lv), level_color(lv)
                if faults:
                    text += " · 감시 일부 불가: " + "/".join(faults)
            elif faults:
                text, color = "감시 일부 불가: " + "/".join(faults), C_RED
            elif not lidar_enabled:
                text, color = "정상 · LiDAR 미사용", C_YELLOW
            else:
                text, color = "정상", C_GREEN
            self.overall.config(text="●  " + text, fg=color)

        self.root.after(self.REFRESH_MS, self._refresh)

    def _set_flash(self, on):
        if on and not self._flashing:
            self.flash.start()
            self._flashing = True
            self.term.append("🚨 위험 거리 감지 — 화면 경고 활성화", "ERROR")
        elif not on and self._flashing:
            self.flash.stop()
            self._flashing = False

    def _update_recovery(self, status, alive):
        if status is None or status.tipover_state not in (TIPOVER_CONFIRMED, TIPOVER_REPORTED):
            self.recovery_panel.pack_forget()
            self._reset_requested_at = None
            return

        self.recovery_panel.pack(fill=tk.X, pady=(4, 0))
        if not alive:
            self.recovery_label.config(text="감시 연결 복구 후 조치 완료를 확인하세요.")
            self.recovery_button.config(state=tk.DISABLED, text="감시 연결 대기")
            return
        if status.tipover_state == TIPOVER_CONFIRMED:
            self.recovery_label.config(text="사고 확정 알림을 처리하고 있습니다.")
            self.recovery_button.config(state=tk.DISABLED, text="사고 알림 처리 중")
            return

        if self._reset_requested_at is not None:
            if time.monotonic() - self._reset_requested_at < 2.0:
                self.recovery_label.config(text="감시 재개 요청을 보냈습니다. 상태 확인 중입니다.")
                self.recovery_button.config(state=tk.DISABLED, text="감시 재개 요청 중…")
                return
            self._reset_requested_at = None
            self.term.append("감시 재개 응답을 확인하지 못했습니다. 다시 요청할 수 있습니다.", "WARN")

        self.recovery_label.config(text="조치를 마쳤다면 감시를 재개하세요.")
        self.recovery_button.config(state=tk.NORMAL, text="조치 완료 · 감시 재개")

    def _request_reset(self):
        status, alive = self.sub.latest()
        if not alive or status is None or status.tipover_state != TIPOVER_REPORTED:
            self.term.append("감시 연결과 사고 처리 상태를 확인한 뒤 다시 시도하세요.", "WARN")
            return
        if self._reset_requested_at is not None and time.monotonic() - self._reset_requested_at < 2.0:
            return
        if not messagebox.askyesno(
                "조치 완료 확인", "상황을 확인하고 조치를 마쳤나요?\n\n"
                "확인하면 정상 감시를 재개합니다.\n기존 사고 알림과 기록은 유지됩니다.",
                parent=self.root, default="no"):
            return
        # 확인창이 열린 동안 연결이나 상태가 변했을 수 있다.
        status, alive = self.sub.latest()
        if not alive or status is None or status.tipover_state != TIPOVER_REPORTED:
            self.term.append("감시 상태가 바뀌었습니다. 연결과 현재 상태를 확인하세요.", "WARN")
            return
        self.cmd.send(CMD_RESET)
        self._reset_requested_at = time.monotonic()
        self.term.append("조치 완료 확인 — 정상 감시 재개 요청을 전송했습니다.", "SYSTEM")
        self._update_recovery(status, alive)

    # ────────────────────────────────────────── 팝업
    def _show_popup(self, deadline):
        self.term.append("주의! 비정상 움직임 감지. 사용자 확인 요청중...", "WARN")
        p = tk.Toplevel(self.root)
        self._popup = p
        p.title("긴급 확인")
        p.geometry(f"460x300+{self.root.winfo_x() + (self.root.winfo_width() - 460) // 2}"
                   f"+{self.root.winfo_y() + (self.root.winfo_height() - 300) // 2}")
        p.configure(bg="#2b0000")
        p.attributes("-topmost", True)
        p.protocol("WM_DELETE_WINDOW", lambda: None)     # X로 닫아 회피 못 하게

        tk.Label(p, text="🚨 사고 발생인가요?", bg="#2b0000", fg="#ff4444",
                 font=("Segoe UI", 22, "bold")).pack(pady=(35, 10))
        timer = tk.Label(p, text="", bg="#2b0000", fg=C_YELLOW,
                         font=("Segoe UI", 12, "bold"))
        timer.pack(pady=(0, 20))

        def tick():
            if self._popup is not p:
                return
            left = max(0, int((deadline or 0) - time.time()))
            timer.config(text=f"⏳ {left}초 후 자동으로 신고됩니다.")
            p.after(200, tick)
        tick()

        row = tk.Frame(p, bg="#2b0000")
        row.pack()
        tk.Button(row, text="예 (신고하기)", bg="#ff3333", fg="white",
                  font=("Segoe UI", 12, "bold"), width=14,
                  command=lambda: self._answer(CMD_USER_YES)).pack(side=tk.LEFT, padx=12)
        tk.Button(row, text="아니오 (취소)", bg="#555", fg="white",
                  font=("Segoe UI", 12), width=14,
                  command=lambda: self._answer(CMD_USER_NO)).pack(side=tk.LEFT, padx=12)

    def _sos(self):
        status, alive = self.sub.latest()
        if not alive or status is None:
            self._update_sos(status, False)
            return
        if status.tipover_state in (TIPOVER_CONFIRMED, TIPOVER_REPORTED):
            self._update_sos(status, True)
            return
        if self._sos_requested_at is not None and time.monotonic() - self._sos_requested_at < 2.0:
            return
        if self.cmd.send(CMD_SOS) is False:
            self._sos_unconfirmed = True
            self.sos_status.config(text="SOS 요청 송신 실패 · 다시 요청하세요", fg=C_RED)
            return
        self._sos_requested_at = time.monotonic()
        self._sos_unconfirmed = False
        self.term.append("🆘 SOS 요청 전송 · 모니터 처리 확인 중", "ERROR")
        self._update_sos(status, True)

    def _update_sos(self, status, alive):
        if not alive or status is None:
            self.sos_button.config(state=tk.DISABLED)
            self.sos_status.config(text="감시 연결 끊김 · 화면 SOS 사용 불가", fg=C_RED)
            return
        if status.tipover_state in (TIPOVER_CONFIRMED, TIPOVER_REPORTED):
            self._sos_requested_at = None
            self._sos_unconfirmed = False
            self.sos_button.config(state=tk.DISABLED)
            states = {
                "queued": ("사고 알림 큐 접수 · 전송 대기", C_YELLOW),
                "sending": ("사고 알림 전송 중 · 결과 대기", C_YELLOW),
                "accepted": ("Discord 서버 접수 확인 · 보호자 열람 여부는 확인 불가", C_GREEN),
                "failed": ("사고 알림 전송 실패 · 통신/알림 설정 확인 필요", C_RED),
                "unconfigured": ("외부 알림 설정 없음 · 보호자에게 전송되지 않음", C_RED),
            }
            # 확정 직후에는 이전 사고의 전송 성공을 새 사고에 표시하지 않는다.
            if status.tipover_state == TIPOVER_CONFIRMED:
                text, color = "사고 확정 확인 · 알림 처리 중", C_YELLOW
            else:
                text, color = states.get(status.notification_state,
                    ("사고 알림 처리 확인 · 전송 결과 확인 불가", C_YELLOW))
            self.sos_status.config(text=text, fg=color)
            return
        if self._sos_requested_at is not None:
            if time.monotonic() - self._sos_requested_at < 2.0:
                self.sos_button.config(state=tk.DISABLED)
                self.sos_status.config(text="SOS 요청 전송 · 모니터 처리 확인 중", fg=C_YELLOW)
                return
            self._sos_requested_at = None
            self._sos_unconfirmed = True
        self.sos_button.config(state=tk.NORMAL)
        self.sos_status.config(
            text="SOS 접수 응답 확인 못함 · 다시 요청 가능" if self._sos_unconfirmed else "긴급 호출 대기",
            fg=C_RED if self._sos_unconfirmed else C_DIMWHITE)

    def _answer(self, cmd):
        self.cmd.send(cmd)
        self.term.append(f"사용자 응답 전송: "
                         f"{'사고 확인' if cmd == CMD_USER_YES else '취소'}",
                         "ERROR" if cmd == CMD_USER_YES else "INFO")
        self._close_popup()

    def _close_popup(self):
        if self._popup is not None:
            try:
                self._popup.destroy()
            except Exception:
                pass
            self._popup = None

    # ────────────────────────────────────────── 종료
    def _on_close(self):
        self.sub.stop()
        self.preview_sub.stop()
        self.flash.stop()
        self._close_popup()
        self.root.after(150, self.root.destroy)


def read_battery():
    """
    [H5] 실제로 읽을 수 있을 때만 값을 돌려준다.
    Raspberry Pi 5에는 BAT0가 없으므로 실기에서는 (None, False)가 나온다.
    연료 게이지(INA219/MAX17043)를 붙이면 여기에 I2C 읽기를 넣을 것.
    """
    base = "/sys/class/power_supply/BAT0"
    try:
        if os.path.exists(f"{base}/capacity"):
            with open(f"{base}/capacity") as f:
                pct = float(f.read().strip())
            charging = False
            if os.path.exists(f"{base}/status"):
                with open(f"{base}/status") as f:
                    charging = f.read().strip().lower() in ("charging", "full")
            return pct, charging
    except Exception:
        pass
    return None, False


if __name__ == "__main__":
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()
