import threading
import time
import requests
import tkinter as tk
from tkinter import scrolledtext
import os

try:
    import tkintermapview
    MAP_AVAILABLE = True
except ImportError:
    MAP_AVAILABLE = False

try: from sensors import gps_sensor as gps
except ImportError: gps = None

try: from sensors import lidar_sensor as lidar
except ImportError: lidar = None

try: from sensors import imu_sensor as imu
except ImportError: imu = None

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."

C_BG, C_CARD, C_TERM_BG, C_BORDER = "#0d0d0d", "#1a1a1a", "#050505", "#2a2a2a"
C_BLUE, C_GREEN, C_YELLOW, C_RED = "#00d4ff", "#00ff88", "#ffaa00", "#ff3333"
C_GRAY, C_WHITE, C_DIMWHITE, C_HEADER_BG = "#555555", "#eeeeee", "#888888", "#111111"

# ✅ 추가: 깜박임 관련 색상 상수
C_FLASH_ON  = "#ff0000"   # 깜박임 ON 색상 (강렬한 빨강)
C_FLASH_OFF = "#0d0d0d"   # 깜박임 OFF 색상 (원래 배경)

LEVEL_OK, LEVEL_WARNING, LEVEL_DANGER = 0, 1, 2

def level_color(level: int): return C_RED if level == 2 else C_YELLOW if level == 1 else C_GREEN
def level_text(level: int):  return "위험" if level == 2 else "경고" if level == 1 else "OK"
def dist_to_level(dist):     return 0 if dist is None else 2 if dist <= 0.5 else 1 if dist <= 1.0 else 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ✅ 새로 추가: 화면 전체 깜박임 오버레이 위젯
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class FlashOverlay:
    """
    루트 창 위에 반투명한 빨간 오버레이를 올려서 화면이
    깜박이는 효과를 줍니다.

    사용법:
        overlay = FlashOverlay(root)
        overlay.start()   # 깜박임 시작
        overlay.stop()    # 깜박임 중지
    """
    # 깜박임 간격 (ms) / 오버레이 투명도 (0.0 ~ 1.0)
    FLASH_INTERVAL_MS = 300
    OVERLAY_ALPHA     = 0.35

    def __init__(self, root: tk.Tk):
        self.root      = root
        self._active   = False
        self._visible  = False
        self._after_id = None

        # ── 오버레이 Toplevel 생성 ──────────────────────────
        self.overlay = tk.Toplevel(root)
        self.overlay.overrideredirect(True)          # 타이틀바·테두리 제거
        self.overlay.attributes("-topmost",    True) # 항상 최상위
        self.overlay.attributes("-alpha", self.OVERLAY_ALPHA)
        self.overlay.configure(bg=C_FLASH_ON)
        self.overlay.withdraw()                      # 처음엔 숨김

        # ── 오버레이에 경고 텍스트 표시 ──────────────────────
        self.canvas = tk.Canvas(
            self.overlay, bg=C_FLASH_ON,
            highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self._warning_text_id = None
        self._update_geometry()

        # 루트 창이 이동/크기변경 되면 오버레이도 따라가도록
        root.bind("<Configure>", self._on_root_configure)

    # ── 위치·크기 동기화 ──────────────────────────────────
    def _update_geometry(self):
        self.root.update_idletasks()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        self.overlay.geometry(f"{w}x{h}+{x}+{y}")

        # 텍스트 위치도 갱신
        self.canvas.delete("warning_text")
        self.canvas.create_text(
            w // 2, h // 2,
            text="⚠  위험 거리 감지  ⚠",
            fill="white",
            font=("Segoe UI", 36, "bold"),
            tags="warning_text"
        )
        # 테두리 사각형 (시각적 강조)
        border = 8
        self.canvas.delete("warning_border")
        self.canvas.create_rectangle(
            border, border, w - border, h - border,
            outline="white", width=border,
            tags="warning_border"
        )

    def _on_root_configure(self, event):
        if self._active:
            self._update_geometry()

    # ── 깜박임 루프 ──────────────────────────────────────
    def _flash_loop(self):
        if not self._active:
            return

        if self._visible:
            self.overlay.withdraw()      # 오버레이 숨기기 (OFF 상태)
            self._visible = False
        else:
            self._update_geometry()
            self.overlay.deiconify()     # 오버레이 표시 (ON 상태)
            self._visible = True

        self._after_id = self.root.after(self.FLASH_INTERVAL_MS, self._flash_loop)

    # ── 공개 API ─────────────────────────────────────────
    def start(self):
        """깜박임 시작 (이미 실행 중이면 무시)"""
        if self._active:
            return
        self._active  = True
        self._visible = False
        self._flash_loop()

    def stop(self):
        """깜박임 중지 및 오버레이 숨김"""
        self._active = False
        if self._after_id:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self.overlay.withdraw()
        self._visible = False

    @property
    def is_active(self):
        return self._active


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 기존 위젯들 (변경 없음)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class BatteryWidget(tk.Canvas):
    def __init__(self, parent, width=70, height=28, bg=C_HEADER_BG):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0)
        self.width, self.height = width, height

    def update_battery(self, percent, is_charging):
        percent = max(0.0, min(100.0, percent))
        self.delete("all")
        pad, tip_w = 3, 4
        bw = self.width - pad - tip_w
        color = C_RED if percent <= 20 else C_YELLOW if percent <= 50 else C_GREEN
        self.create_rectangle(pad, pad, bw, self.height - pad, outline="#777777", width=2)
        self.create_rectangle(bw, self.height/2 - 5, self.width - 2, self.height/2 + 5,
                              fill="#777777", outline="")
        fill_w = max(0, (bw - pad - 2) * (percent / 100.0))
        if fill_w > 0:
            self.create_rectangle(pad+2, pad+2, pad+2+fill_w, self.height-pad-1,
                                  fill=color, outline="")
        txt = f"⚡{int(percent)}%" if is_charging else f"{int(percent)}%"
        self.create_text(bw/2 + pad, self.height/2, text=txt,
                         fill="#000000", font=("Segoe UI", 9, "bold"))


class LidarCard(tk.Frame):
    def __init__(self, parent, title: str, **kw):
        super().__init__(parent, bg=C_CARD, bd=0,
                         highlightthickness=2, highlightbackground=C_BORDER, **kw)
        self.title = title
        self._build()

    def _build(self):
        tk.Label(self, text=self.title, bg=C_CARD, fg=C_BLUE,
                 font=("Segoe UI", 11, "bold")).pack(pady=(14, 4))
        self.badge = tk.Label(self, text=" 연결 대기중 ", bg=C_GRAY, fg=C_WHITE,
                              font=("Segoe UI", 10, "bold"), relief=tk.FLAT, padx=10, pady=3)
        self.badge.pack(pady=(0, 10))
        self.dist_label = tk.Label(self, text="-", bg=C_CARD, fg=C_GRAY,
                                   font=("Segoe UI", 28, "bold"))
        self.dist_label.pack(pady=(0, 6))
        tk.Label(self, text="최근접 거리 (m)", bg=C_CARD,
                 fg=C_DIMWHITE, font=("Segoe UI", 9)).pack(pady=(0, 14))

    def update(self, dist, status="정상"):
        if "실패" in status:
            self.badge.config(text="  연결 실패  ", bg=C_RED, fg=C_WHITE)
            self.config(highlightbackground=C_RED)
            self.dist_label.config(text="연결 안됨", fg=C_RED)
            return
        if "대기중" in status:
            self.badge.config(text="  연결 대기중  ", bg=C_GRAY, fg=C_WHITE)
            self.config(highlightbackground=C_GRAY)
            self.dist_label.config(text="-", fg=C_GRAY)
            return

        is_danger = dist is not None and dist <= 0.5
        is_warn   = dist is not None and 0.5 < dist <= 1.0
        color     = C_RED if is_danger else C_YELLOW if is_warn else C_GREEN
        badge_txt = "위험" if is_danger else "경고" if is_warn else "OK"

        self.badge.config(text=f"  {badge_txt}  ",
                          bg=color,
                          fg="#ffffff" if is_danger else "#000000")
        self.config(highlightbackground=(color if dist is not None else C_BORDER))
        self.dist_label.config(
            text="감지 없음" if dist is None else f"{dist:.2f} m",
            fg=color
        )


class IMUCard(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C_CARD, bd=0,
                         highlightthickness=2, highlightbackground=C_BORDER, **kw)
        self._build()

    def _build(self):
        tk.Label(self, text="IMU", bg=C_CARD, fg=C_BLUE,
                 font=("Segoe UI", 11, "bold")).pack(pady=(14, 6))
        self.badge = tk.Label(self, text=" 연결 대기중 ", bg=C_GRAY, fg=C_WHITE,
                              font=("Segoe UI", 13, "bold"), relief=tk.FLAT, padx=12, pady=4)
        self.badge.pack(pady=(0, 8))
        self.state_label = tk.Label(self, text="-", bg=C_CARD, fg=C_GRAY,
                                    font=("Segoe UI", 26, "bold"))
        self.state_label.pack(pady=(0, 4))
        tk.Label(self, text="사고 상태", bg=C_CARD,
                 fg=C_DIMWHITE, font=("Segoe UI", 9)).pack(pady=(0, 6))
        info = tk.Frame(self, bg=C_CARD)
        info.pack(pady=(0, 14))
        tk.Label(info, text="Roll:",  bg=C_CARD, fg=C_DIMWHITE,
                 font=("Segoe UI", 8)).grid(row=0, column=0, padx=4)
        self.roll_lbl = tk.Label(info, text="-", bg=C_CARD, fg=C_WHITE,
                                 font=("Segoe UI", 8, "bold"))
        self.roll_lbl.grid(row=0, column=1, padx=4)
        tk.Label(info, text="Pitch:", bg=C_CARD, fg=C_DIMWHITE,
                 font=("Segoe UI", 8)).grid(row=0, column=2, padx=4)
        self.pitch_lbl = tk.Label(info, text="-", bg=C_CARD, fg=C_WHITE,
                                  font=("Segoe UI", 8, "bold"))
        self.pitch_lbl.grid(row=0, column=3, padx=4)

    def update(self, fall_state="평상시", roll=None, pitch=None, status="정상"):
        if "실패" in status:
            self.badge.config(text="  연결 실패  ", bg=C_RED, fg=C_WHITE)
            self.state_label.config(text="연결 안됨", fg=C_RED)
            self.config(highlightbackground=C_RED)
            self.roll_lbl.config(text="-"); self.pitch_lbl.config(text="-")
            return
        if "대기중" in status:
            self.badge.config(text="  연결 대기중  ", bg=C_GRAY, fg=C_WHITE)
            self.state_label.config(text="대기중", fg=C_GRAY)
            self.config(highlightbackground=C_GRAY)
            self.roll_lbl.config(text="-"); self.pitch_lbl.config(text="-")
            return

        state_map = {
            "평상시":        ("  정상  ",        C_GREEN,   "#000000", "정상",         C_GREEN,  C_BORDER),
            "충격 감지":     ("  충격 감지  ",    C_YELLOW,  "#000000", "안정화 중...", C_YELLOW, C_YELLOW),
            "움직임 분석중": ("  분석중  ",       "#ff6600", "#ffffff", "상태 판별중",  "#ff6600","#ff6600"),
            "응답 대기":     ("  응답 대기  ",    "#ff00ff", "#ffffff", "사용자 확인중","#ff00ff","#ff00ff"),
            "사고 확정":     ("  사고 발생!  ",   C_RED,     "#ffffff", "사고 확정",    C_RED,    C_RED),
            "신고완료-정상": ("  신고완료  ",     C_GREEN,   "#000000", "정상 복귀",    C_GREEN,  C_BORDER),
        }
        cfg = state_map.get(fall_state)
        if cfg:
            b_txt, b_bg, b_fg, s_txt, s_fg, border = cfg
            self.badge.config(text=b_txt, bg=b_bg, fg=b_fg)
            self.state_label.config(text=s_txt, fg=s_fg)
            self.config(highlightbackground=border)
        if roll  is not None: self.roll_lbl.config(text=f"{roll:.1f}°")
        if pitch is not None: self.pitch_lbl.config(text=f"{pitch:.1f}°")


class GPSCard(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C_CARD, bd=0,
                         highlightthickness=2, highlightbackground=C_BORDER, **kw)
        self._build()

    def _build(self):
        tk.Label(self, text="🛰️  GPS & 트래킹", bg=C_CARD, fg=C_BLUE,
                 font=("Segoe UI", 11, "bold")).pack(pady=(14, 4))
        self.badge = tk.Label(self, text=" 연결 대기중 ", bg=C_GRAY, fg=C_WHITE,
                              font=("Segoe UI", 10, "bold"), relief=tk.FLAT, padx=10, pady=3)
        self.badge.pack(pady=(0, 6))
        info = tk.Frame(self, bg=C_CARD)
        info.pack(pady=(0, 8))
        self.lat_lbl = tk.Label(info, text="Lat: -", bg=C_CARD, fg=C_WHITE,
                                font=("Segoe UI", 9, "bold"))
        self.lat_lbl.grid(row=0, column=0, padx=10)
        self.lon_lbl = tk.Label(info, text="Lon: -", bg=C_CARD, fg=C_WHITE,
                                font=("Segoe UI", 9, "bold"))
        self.lon_lbl.grid(row=0, column=1, padx=10)

        if MAP_AVAILABLE:
            self.map_widget = tkintermapview.TkinterMapView(self, corner_radius=0)
            self.map_widget.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
            self.map_widget.set_zoom(15)
            self.map_widget.set_position(35.1595, 126.8526)
            self.marker = None
        else:
            self.map_canvas = tk.Canvas(self, bg="#111111", bd=0,
                                        highlightthickness=1, highlightbackground="#333333")
            self.map_canvas.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
            self.map_canvas.create_text(
                150, 80,
                text="지도를 보려면 터미널에\n'pip install tkintermapview'\n를 입력하세요.",
                fill=C_RED, font=("Segoe UI", 10, "bold"), justify=tk.CENTER
            )

    def update(self, lat, lon, status="정상", fix_quality=0):
        if "실패" in status:
            self.badge.config(text="  연결 실패  ", bg=C_RED, fg=C_WHITE)
            self.config(highlightbackground=C_RED)
            self.lat_lbl.config(text="Lat: -"); self.lon_lbl.config(text="Lon: -")
            return
        if "대기중" in status:
            self.badge.config(text="  연결 대기중  ", bg=C_GRAY, fg=C_WHITE)
            self.config(highlightbackground=C_GRAY)
            self.lat_lbl.config(text="Lat: -"); self.lon_lbl.config(text="Lon: -")
            return

        if fix_quality and fix_quality > 0:
            self.badge.config(text="  정상  ", bg=C_GREEN, fg="#000000")
            self.config(highlightbackground=C_GREEN)
        else:
            self.badge.config(text="  수신중  ", bg=C_YELLOW, fg="#000000")
            self.config(highlightbackground=C_BORDER)

        self.lat_lbl.config(text=f"Lat: {lat:.6f}" if lat else "Lat: -")
        self.lon_lbl.config(text=f"Lon: {lon:.6f}" if lon else "Lon: -")

        if MAP_AVAILABLE and lat and lon:
            self.map_widget.set_position(lat, lon)
            if self.marker is None:
                self.marker = self.map_widget.set_marker(lat, lon, text="현재 위치")
            else:
                self.marker.set_position(lat, lon)


class TerminalCard(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=C_TERM_BG, bd=0,
                         highlightthickness=2, highlightbackground=C_BORDER, **kw)
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg="#222222", height=30)
        hdr.pack(fill=tk.X, side=tk.TOP)
        hdr.pack_propagate(False)
        tk.Label(hdr, text=">_ 시스템 터미널", bg="#222222", fg=C_WHITE,
                 font=("Consolas", 10, "bold")).pack(side=tk.LEFT, padx=10)
        self.txt = scrolledtext.ScrolledText(
            self, bg=C_TERM_BG, fg=C_GREEN,
            font=("Consolas", 9), wrap=tk.WORD,
            state=tk.DISABLED, bd=0
        )
        self.txt.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.txt.tag_config("INFO",   foreground="#00ff88")
        self.txt.tag_config("WARN",   foreground="#ffaa00")
        self.txt.tag_config("ERROR",  foreground="#ff3333")
        self.txt.tag_config("SYSTEM", foreground="#00d4ff",
                            font=("Consolas", 9, "bold"))

    def append_log(self, msg: str, level: str = "INFO"):
        self.txt.config(state=tk.NORMAL)
        ts = time.strftime("%H:%M:%S")
        self.txt.insert(tk.END, f"[{ts}] {msg}\n", level)
        self.txt.see(tk.END)
        self.txt.config(state=tk.DISABLED)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인 GUI 매니저
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class SensorManagerGUI:
    REFRESH_MS = 100

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("노약자 보행 보조 시스템")
        self.root.configure(bg=C_BG)
        self.root.geometry("1280x720")
        self.root.resizable(False, False)

        self._init_done        = False
        self._popup_active     = False
        self._popup_countdown  = 10
        self._alert_sent       = False
        self._force_accident   = False
        self._waiting_recovery = False

        # ✅ 깜박임 상태 추적 변수
        self._flash_danger_active = False   # 현재 깜박임이 켜져 있는지

        self._build_ui()

        # ✅ FlashOverlay는 UI 빌드 후 생성 (루트 창 크기 확정 후)
        self.root.update_idletasks()
        self.flash_overlay = FlashOverlay(self.root)

        self._start_init_sequence()
        self._schedule_refresh()

    # ------------------------------------------------------------------ UI 구성
    def _build_ui(self):
        hdr = tk.Frame(self.root, bg=C_HEADER_BG, height=52)
        hdr.pack(fill=tk.X, side=tk.TOP)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="노약자 보행 보조 시스템", bg=C_HEADER_BG, fg=C_BLUE,
                 font=("Segoe UI", 15, "bold")).pack(side=tk.LEFT, padx=20, pady=10)

        self.lbl_overall = tk.Label(hdr, text="●  시스템 부팅중", bg=C_HEADER_BG,
                                    fg=C_GRAY, font=("Segoe UI", 10, "bold"))
        self.lbl_overall.pack(side=tk.RIGHT, padx=20)

        self.lbl_clock = tk.Label(hdr, text="", bg=C_HEADER_BG,
                                  fg=C_DIMWHITE, font=("Segoe UI", 9))
        self.lbl_clock.pack(side=tk.RIGHT, padx=10)

        self.battery_ui = BatteryWidget(hdr)
        self.battery_ui.pack(side=tk.RIGHT, padx=15, pady=12)

        body = tk.Frame(self.root, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(8, 14))

        top_row = tk.Frame(body, bg=C_BG)
        top_row.pack(fill=tk.X, pady=(0, 10))
        top_row.columnconfigure(0, weight=1, uniform="top")
        top_row.columnconfigure(1, weight=1, uniform="top")

        self.lidar_left  = LidarCard(top_row, title="Left LiDAR")
        self.lidar_left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.lidar_right = LidarCard(top_row, title="Right LiDAR")
        self.lidar_right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        top_row.rowconfigure(0, minsize=190)

        bot_row = tk.Frame(body, bg=C_BG)
        bot_row.pack(fill=tk.BOTH, expand=True)
        bot_row.columnconfigure(0, weight=1)
        bot_row.columnconfigure(1, weight=1)
        bot_row.columnconfigure(2, weight=2)
        bot_row.rowconfigure(0, weight=1)

        self.imu_card = IMUCard(bot_row)
        self.imu_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.gps_card = GPSCard(bot_row)
        self.gps_card.grid(row=0, column=1, sticky="nsew", padx=(6, 6))

        self.terminal = TerminalCard(bot_row)
        self.terminal.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

    # ------------------------------------------------------------------ 유틸
    def _get_pi_battery_status(self):
        percent, is_charging = 100.0, False
        try:
            if os.path.exists("/sys/class/power_supply/BAT0/capacity"):
                with open("/sys/class/power_supply/BAT0/capacity") as f:
                    percent = float(f.read().strip())
                if os.path.exists("/sys/class/power_supply/BAT0/status"):
                    with open("/sys/class/power_supply/BAT0/status") as f:
                        is_charging = f.read().strip().lower() in ["charging", "full"]
        except Exception:
            pass
        return percent, is_charging

    def _sys_log(self, msg: str, level: str = "INFO"):
        self.root.after(0, lambda: self.terminal.append_log(msg, level))

    # ------------------------------------------------------------------ 깜박임 제어
    def _update_flash(self, left_dist, right_dist):
        """
        LiDAR 거리가 0.5 m 이하일 때 깜박임 시작,
        두 센서 모두 0.5 m 초과이면 깜박임 중지.
        """
        left_danger  = left_dist  is not None and left_dist  <= 0.5
        right_danger = right_dist is not None and right_dist <= 0.5
        any_danger   = left_danger or right_danger

        if any_danger and not self._flash_danger_active:
            # ✅ 위험 감지 → 깜박임 시작
            self.flash_overlay.start()
            self._flash_danger_active = True
            side = []
            if left_danger:  side.append(f"좌측 {left_dist:.2f}m")
            if right_danger: side.append(f"우측 {right_dist:.2f}m")
            self._sys_log(
                f"🚨 위험 거리 감지! ({', '.join(side)}) — 화면 경고 활성화",
                "ERROR"
            )

        elif not any_danger and self._flash_danger_active:
            # ✅ 위험 해제 → 깜박임 중지
            self.flash_overlay.stop()
            self._flash_danger_active = False
            self._sys_log("✅ 위험 거리 해제 — 화면 경고 비활성화", "INFO")

    # ------------------------------------------------------------------ 웹훅
    def _send_webhook_task(self, payload, image_bytes=None):
        try:
            if image_bytes:
                import json
                files = {
                    "file": ("map.png", image_bytes, "image/png"),
                    "payload_json": (None, json.dumps(payload), "application/json"),
                }
                resp = requests.post(DISCORD_WEBHOOK_URL, files=files, timeout=10)
            else:
                resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)

            if resp.status_code in [200, 204]:
                self._sys_log("[신고 완료] 디스코드 웹훅 전송 성공", "INFO")
            else:
                self._sys_log(f"[신고 실패] 디스코드 응답 오류 (코드: {resp.status_code})", "ERROR")
        except Exception as e:
            self._sys_log(f"[신고 오류] 웹훅 전송 중 에러 발생: {e}", "ERROR")

    def _fetch_static_map(self, lat, lon, zoom=16, size="600x400"):
        try:
            url = (
                f"https://staticmap.openstreetmap.de/staticmap.php"
                f"?center={lat},{lon}&zoom={zoom}&size={size}"
                f"&markers={lat},{lon},red-pushpin"
            )
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200 and resp.content:
                return resp.content
        except Exception as e:
            self._sys_log(f"[지도] 이미지 수신 실패: {e}", "WARN")
        return None

    def _send_emergency_report(self, lat, lon, accel, roll, pitch):
        self._sys_log("[신고 발송 중] 디스코드 서버로 데이터 전송 시도...", "WARN")
        if not DISCORD_WEBHOOK_URL:
            self._sys_log("웹훅 URL이 설정되지 않았습니다.", "ERROR")
            return

        str_lat   = f"{lat:.5f}"    if lat   is not None else "알 수 없음"
        str_lon   = f"{lon:.5f}"    if lon   is not None else "알 수 없음"
        str_roll  = f"{roll:.1f}°"  if roll  is not None else "알 수 없음"
        str_pitch = f"{pitch:.1f}°" if pitch is not None else "알 수 없음"
        str_accel = f"{accel:.2f}g" if accel is not None else "알 수 없음"

        if lat is not None and lon is not None:
            map_link = (f"https://www.openstreetmap.org/"
                        f"?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}")
        else:
            map_link = "위치 정보 없음"

        payload = {
            "content": "🚨 **[긴급] 사고 발생!**",
            "embeds": [{
                "color": 16711680,
                "title": "📍 사고 발생 위치 및 상태",
                "description": f"[지도에서 보기]({map_link})",
                "fields": [
                    {"name": "📌 위도",      "value": str_lat,   "inline": True},
                    {"name": "📌 경도",      "value": str_lon,   "inline": True},
                    {"name": "🕒 신고 시각", "value": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "inline": True},
                ],
                "image":  {"url": "attachment://map.png"},
                "footer": {"text": "노약자 보행 보조 시스템 | 자동 신고"},
            }],
        }

        def _task():
            image_bytes = None
            if lat is not None and lon is not None:
                self._sys_log("[지도] 정적 지도 이미지 다운로드 중...", "INFO")
                image_bytes = self._fetch_static_map(lat, lon)
                if image_bytes:
                    self._sys_log("[지도] 이미지 첨부 준비 완료", "INFO")
                else:
                    self._sys_log("[지도] 이미지 없이 신고 진행", "WARN")
                    payload["embeds"][0].pop("image", None)
            self._send_webhook_task(payload, image_bytes)

        threading.Thread(target=_task, daemon=True).start()

    # ------------------------------------------------------------------ 팝업
    def _show_fall_popup(self):
        self._popup_active, self._popup_countdown = True, 10
        self._sys_log("주의! 비정상 움직임 감지. 사용자 확인 요청중...", "WARN")

        popup = tk.Toplevel(self.root)
        popup.title("긴급 확인")
        popup.geometry(
            f"450x300"
            f"+{self.root.winfo_x() + (self.root.winfo_width()  - 450) // 2}"
            f"+{self.root.winfo_y() + (self.root.winfo_height() - 300) // 2}"
        )
        popup.configure(bg="#2b0000")
        popup.attributes('-topmost', True)

        tk.Label(popup, text="🚨 사고 발생인가요?", bg="#2b0000", fg="#ff4444",
                 font=("Segoe UI", 22, "bold")).pack(pady=(35, 10))
        lbl_timer = tk.Label(popup, text="⏳ 10초 후 자동으로 신고됩니다.",
                             bg="#2b0000", fg=C_YELLOW, font=("Segoe UI", 12, "bold"))
        lbl_timer.pack(pady=(0, 20))

        btn_frame = tk.Frame(popup, bg="#2b0000")
        btn_frame.pack()

        def close(action):
            if hasattr(imu, "submit_user_response"):
                imu.submit_user_response(action)
            if action == "YES":
                self._force_accident   = True
                self._waiting_recovery = False
            else:
                self._force_accident   = False
                self._waiting_recovery = False
                self._alert_sent       = False
            self._sys_log(
                f"사용자 확인: '{action}' 처리",
                "INFO" if action == "NO" else "ERROR"
            )
            popup.destroy()
            self._popup_active = False

        def tick():
            if not self._popup_active: return
            self._popup_countdown -= 1
            if self._popup_countdown > 0:
                lbl_timer.config(text=f"⏳ {self._popup_countdown}초 후 자동으로 신고됩니다.")
                popup.after(1000, tick)
            else:
                close("YES")

        popup.after(1000, tick)
        tk.Button(btn_frame, text="예 (신고하기)",  bg="#ff3333", fg="white",
                  font=("Segoe UI", 12, "bold"),
                  command=lambda: close("YES")).pack(side=tk.LEFT, padx=15)
        tk.Button(btn_frame, text="아니오 (취소)", bg="#555555", fg="white",
                  font=("Segoe UI", 12),
                  command=lambda: close("NO")).pack(side=tk.LEFT, padx=15)

    # ------------------------------------------------------------------ 갱신 루프
    def _schedule_refresh(self):
        self._refresh()
        self.root.after(self.REFRESH_MS, self._schedule_refresh)

    def _refresh(self):
        # 시계 · 배터리
        self.lbl_clock.config(text=time.strftime("%Y-%m-%d  %H:%M:%S"))
        self.battery_ui.update_battery(*self._get_pi_battery_status())

        # 센서 스냅샷
        snap_lidar = lidar.get_snapshot() if lidar and hasattr(lidar, "get_snapshot") else {}
        snap_imu   = imu.get_snapshot()   if imu   and hasattr(imu,   "get_snapshot") else {}
        snap_gps   = gps.get_snapshot()   if gps   and hasattr(gps,   "get_snapshot") else {}

        # 팝업 트리거
        if snap_imu.get("require_user_check", False) and not self._popup_active:
            self._show_fall_popup()

        # 상태 추출
        l_dict = snap_lidar.get("left",  {})
        r_dict = snap_lidar.get("right", {})

        l_stat = l_dict.get("status", "연결 실패") if l_dict else "연결 실패"
        r_stat = r_dict.get("status", "연결 실패") if r_dict else "연결 실패"
        i_stat = snap_imu.get("status", "연결 실패") if snap_imu else "연결 실패"
        g_stat = snap_gps.get("status", "연결 실패") if snap_gps else "연결 실패"

        left_dist  = l_dict.get("min_dist") if "실패" not in l_stat and "대기" not in l_stat else None
        right_dist = r_dict.get("min_dist") if "실패" not in r_stat and "대기" not in r_stat else None

        raw_fall_state = snap_imu.get("fall_state", "평상시")
        roll  = snap_imu.get("roll")
        pitch = snap_imu.get("pitch")
        lat   = snap_gps.get("lat")
        lon   = snap_gps.get("lon")

        # ✅ 깜박임 상태 업데이트 (연결된 센서만 판단)
        self._update_flash(left_dist, right_dist)

        # 사고 확정 로직
        if self._force_accident:
            display_fall_state = "사고 확정"
            if self._alert_sent and raw_fall_state == "평상시" and not self._waiting_recovery:
                self._waiting_recovery = True
                self._sys_log("✅ IMU 정상 감지 — 사고 처리 완료. 상태를 정상으로 복귀합니다.", "INFO")
            if self._waiting_recovery and raw_fall_state == "평상시":
                display_fall_state     = "평상시"
                self._force_accident   = False
                self._alert_sent       = False
                self._waiting_recovery = False
        else:
            display_fall_state = raw_fall_state

        # UI 업데이트
        self.lidar_left.update(left_dist,  status=l_stat)
        self.lidar_right.update(right_dist, status=r_stat)
        self.imu_card.update(display_fall_state, roll, pitch, status=i_stat)
        self.gps_card.update(lat, lon, status=g_stat,
                             fix_quality=snap_gps.get("fix_quality", 0))

        # 신고 발송
        if display_fall_state == "사고 확정" and not self._alert_sent:
            self._send_emergency_report(
                lat, lon, snap_imu.get("accel_mag", 0.0), roll, pitch
            )
            self._alert_sent = True

        # 헤더 상태 표시
        if self._init_done:
            if "실패" in (l_stat + r_stat + i_stat + g_stat):
                self.lbl_overall.config(text="●  시스템 오류", fg=C_RED)
            else:
                overall = max(dist_to_level(left_dist), dist_to_level(right_dist))
                if display_fall_state == "사고 확정":
                    overall = LEVEL_DANGER
                self.lbl_overall.config(
                    text=f"●  {level_text(overall)}",
                    fg=level_color(overall)
                )

    # ------------------------------------------------------------------ 초기화
    def _start_init_sequence(self):
        threading.Thread(target=self._init_sequence, daemon=True).start()

    def _init_sequence(self):
        self._sys_log("=== 시스템 부팅 시작 ===", "SYSTEM")
        for s, name in [(gps, "GPS"), (lidar, "LiDAR"), (imu, "IMU")]:
            if s is None:
                self._sys_log(f"❌ [{name}] 센서 파일 로드 실패!", "ERROR")
                continue
            self._sys_log(f"[{name}] 연결 시도 중...", "INFO")
            if hasattr(s, "run_integrity_check"):
                if s.run_integrity_check(log_callback=self._sys_log):
                    s.start(log_callback=self._sys_log)
            elif hasattr(s, "start"):
                s.start(log_callback=self._sys_log)
            time.sleep(0.3)
        self._init_done = True
        self._sys_log("=== 통합 초기화 시퀀스 완료 ===", "SYSTEM")


if __name__ == "__main__":
    root = tk.Tk()
    app  = SensorManagerGUI(root)
    root.mainloop()