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
import time
import tkinter as tk
from tkinter import scrolledtext

import config
import console
from states import (CMD_RESET, CMD_USER_NO, CMD_USER_YES, CONN_ERROR,
                    CONN_STALE, TIPOVER_ASKING, TIPOVER_DISPLAY, TIPOVER_NORMAL,
                    TIPOVER_REPORTED, LEVEL_DANGER, LEVEL_OK, LEVEL_WARN,
                    fix_quality_name)
from buttons import CMD_SOS
from status_link import CommandSender, StatusSubscriber

console.setup()

try:
    import tkintermapview
    MAP_AVAILABLE = True
except ImportError:
    MAP_AVAILABLE = False

C_BG, C_CARD, C_TERM_BG, C_BORDER = "#0d0d0d", "#1a1a1a", "#050505", "#2a2a2a"
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
    """위험 거리에서 화면 전체를 깜박이는 오버레이."""
    FLASH_MS = 300
    ALPHA = 0.35

    def __init__(self, root):
        self.root = root
        self._active = False
        self._visible = False
        self._after = None
        self.overlay = tk.Toplevel(root)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-alpha", self.ALPHA)
        self.overlay.configure(bg=C_FLASH_ON)
        self.overlay.withdraw()
        self.canvas = tk.Canvas(self.overlay, bg=C_FLASH_ON, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self._sync()
        # [M1 관련] 자식 위젯의 Configure까지 올라오므로 루트 것만 처리한다
        root.bind("<Configure>", self._on_cfg)

    def _sync(self):
        r = self.root
        w, h = r.winfo_width(), r.winfo_height()
        self.overlay.geometry(f"{w}x{h}+{r.winfo_x()}+{r.winfo_y()}")
        self.canvas.delete("all")
        self.canvas.create_text(w // 2, h // 2, text="⚠  위험 거리 감지  ⚠",
                                fill="white", font=("Segoe UI", 36, "bold"))
        self.canvas.create_rectangle(8, 8, w - 8, h - 8, outline="white", width=8)

    def _on_cfg(self, e):
        if self._active and e.widget is self.root:
            self._sync()

    def _tick(self):
        if not self._active:
            return
        if self._visible:
            self.overlay.withdraw()
        else:
            self._sync()
            self.overlay.deiconify()
        self._visible = not self._visible
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
        self.overlay.withdraw()
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


class LidarCard(tk.Frame):
    def __init__(self, parent, title, **kw):
        super().__init__(parent, bg=C_CARD, bd=0, highlightthickness=2,
                         highlightbackground=C_BORDER, **kw)
        tk.Label(self, text=title, bg=C_CARD, fg=C_BLUE,
                 font=("Segoe UI", 11, "bold")).pack(pady=(14, 4))
        self.badge = tk.Label(self, text=" 연결 대기중 ", bg=C_GRAY, fg=C_WHITE,
                              font=("Segoe UI", 10, "bold"), padx=10, pady=3)
        self.badge.pack(pady=(0, 10))
        self.dist = tk.Label(self, text="-", bg=C_CARD, fg=C_GRAY,
                             font=("Segoe UI", 28, "bold"))
        self.dist.pack(pady=(0, 6))
        tk.Label(self, text="최근접 거리 (m)", bg=C_CARD, fg=C_DIMWHITE,
                 font=("Segoe UI", 9)).pack(pady=(0, 14))

    def update_card(self, d, ok, link_ok):
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
                 font=("Segoe UI", 11, "bold")).pack(pady=(14, 6))
        self.badge = tk.Label(self, text=" 연결 대기중 ", bg=C_GRAY, fg=C_WHITE,
                              font=("Segoe UI", 13, "bold"), padx=12, pady=4)
        self.badge.pack(pady=(0, 8))
        self.state_lbl = tk.Label(self, text="-", bg=C_CARD, fg=C_GRAY,
                                  font=("Segoe UI", 22, "bold"))
        self.state_lbl.pack(pady=(0, 4))
        tk.Label(self, text="사고 상태", bg=C_CARD, fg=C_DIMWHITE,
                 font=("Segoe UI", 9)).pack(pady=(0, 6))
        info = tk.Frame(self, bg=C_CARD)
        info.pack(pady=(0, 14))
        self.vals = {}
        for i, key in enumerate(("Roll", "Pitch", "충격")):
            tk.Label(info, text=f"{key}:", bg=C_CARD, fg=C_DIMWHITE,
                     font=("Segoe UI", 8)).grid(row=0, column=i * 2, padx=3)
            v = tk.Label(info, text="-", bg=C_CARD, fg=C_WHITE,
                         font=("Segoe UI", 8, "bold"))
            v.grid(row=0, column=i * 2 + 1, padx=3)
            self.vals[key] = v

    def update_card(self, imu, tipover_state):
        if imu.status in (CONN_ERROR, CONN_STALE) or not imu.valid:
            txt = "응답 없음" if imu.status == CONN_STALE else "연결 안됨"
            self.badge.config(text=f"  {txt}  ", bg=C_RED, fg=C_WHITE)
            self.state_lbl.config(text=txt, fg=C_RED)
            self.config(highlightbackground=C_RED)
            for v in self.vals.values():
                v.config(text="-")
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
        if MAP_AVAILABLE:
            self.map = tkintermapview.TkinterMapView(self, corner_radius=0)
            self.map.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
            self.map.set_zoom(15)
            self.map.set_position(35.1595, 126.8526)
            self.marker = None
        else:
            c = tk.Canvas(self, bg="#111", bd=0, highlightthickness=1,
                          highlightbackground="#333")
            c.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
            c.create_text(150, 80, text="지도: pip install tkintermapview",
                          fill=C_RED, font=("Segoe UI", 10, "bold"))

    def update_card(self, gps):
        if not gps.valid:
            txt = "응답 없음" if gps.status == CONN_STALE else "연결 안됨"
            self.badge.config(text=f"  {txt}  ", bg=C_RED, fg=C_WHITE)
            self.config(highlightbackground=C_RED)
            self.detail.config(text="-")
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

        if gps.lat is None:
            self.coord.config(text="Lat: -   Lon: -")
            return
        self.coord.config(text=f"Lat: {gps.lat:.6f}   Lon: {gps.lon:.6f}")

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
                                             state=tk.DISABLED, bd=0)
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

    def __init__(self, root):
        self.root = root
        root.title("노약자 보행 보조 시스템 — 대시보드")
        root.configure(bg=C_BG)
        root.geometry("1280x720")
        root.minsize(1024, 600)          # [M8] 소형 터치스크린 대비

        self.sub = StatusSubscriber()
        self.sub.start()
        self.cmd = CommandSender()

        self._popup = None
        self._flashing = False
        self._last_notice = None
        self._link_warned = False

        self._build()
        root.update_idletasks()
        self.flash = FlashOverlay(root)
        root.protocol("WM_DELETE_WINDOW", self._on_close)   # [M9]

        self.term.append("대시보드 시작 — safety_monitor 연결 대기", "SYSTEM")
        self._refresh()

    def _build(self):
        hdr = tk.Frame(self.root, bg=C_HEADER_BG, height=52)
        hdr.pack(fill=tk.X, side=tk.TOP)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="노약자 보행 보조 시스템", bg=C_HEADER_BG, fg=C_BLUE,
                 font=("Segoe UI", 15, "bold")).pack(side=tk.LEFT, padx=20, pady=10)
        self.overall = tk.Label(hdr, text="●  연결 대기", bg=C_HEADER_BG, fg=C_GRAY,
                                font=("Segoe UI", 10, "bold"))
        self.overall.pack(side=tk.RIGHT, padx=20)
        self.clock = tk.Label(hdr, text="", bg=C_HEADER_BG, fg=C_DIMWHITE,
                              font=("Segoe UI", 9))
        self.clock.pack(side=tk.RIGHT, padx=10)
        self.batt = BatteryWidget(hdr)
        self.batt.pack(side=tk.RIGHT, padx=15, pady=12)
        self.health_lbl = tk.Label(hdr, text="", bg=C_HEADER_BG, fg=C_DIMWHITE,
                                   font=("Segoe UI", 8))
        self.health_lbl.pack(side=tk.RIGHT, padx=8)

        body = tk.Frame(self.root, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(8, 14))

        top = tk.Frame(body, bg=C_BG)
        top.pack(fill=tk.X, pady=(0, 10))
        top.columnconfigure(0, weight=1, uniform="t")
        top.columnconfigure(1, weight=1, uniform="t")
        top.rowconfigure(0, minsize=190)
        self.lidar_l = LidarCard(top, "Left LiDAR")
        self.lidar_l.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.lidar_r = LidarCard(top, "Right LiDAR")
        self.lidar_r.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.curb_lbl = tk.Label(body, text="", bg=C_BG, fg=C_DIMWHITE,
                                 font=("Segoe UI", 10, "bold"))
        self.curb_lbl.pack(fill=tk.X, pady=(0, 6))

        bot = tk.Frame(body, bg=C_BG)
        bot.pack(fill=tk.BOTH, expand=True)
        for i, w in ((0, 1), (1, 1), (2, 2)):
            bot.columnconfigure(i, weight=w)
        bot.rowconfigure(0, weight=1)
        self.imu_card = IMUCard(bot)
        self.imu_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.gps_card = GPSCard(bot)
        self.gps_card.grid(row=0, column=1, sticky="nsew", padx=(6, 6))
        right = tk.Frame(bot, bg=C_BG)
        right.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        self.term = TerminalCard(right)
        self.term.pack(fill=tk.BOTH, expand=True)
        # 화면에서도 SOS를 부를 수 있어야 한다.
        # (실기에서는 손잡이의 물리 SOS 버튼이 주 경로다 — buttons.py)
        tk.Button(right, text="🆘  긴급 호출 (SOS)", bg="#8b0000", fg="white",
                  font=("Segoe UI", 11, "bold"), height=2,
                  command=self._sos).pack(fill=tk.X, pady=(6, 0))

    # ────────────────────────────────────────── 갱신
    def _refresh(self):
        self.clock.config(text=time.strftime("%Y-%m-%d  %H:%M:%S"))
        st, alive = self.sub.latest()
        if not alive:
            if not self._link_warned:
                self.term.append("⚠ safety_monitor 연결 없음 — "
                                 "python safety_monitor.py 를 실행하세요", "ERROR")
                self._link_warned = True
            self.overall.config(text="●  모니터 연결 끊김", fg=C_RED)
            self.batt.update_battery(None, False)
            self.health_lbl.config(text="")
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
            bits.append(f"미전송 {h.alerts_pending}건")
        if h.battery_volts:
            bits.append(f"{h.battery_volts:.1f}V")
        self.health_lbl.config(
            text="  ·  ".join(bits),
            fg=C_YELLOW if (h.alerts_pending or
                            (h.ntrip_connected and not h.ntrip_healthy))
            else C_DIMWHITE)

        obs = st.obstacle
        self.lidar_l.update_card(obs.left_m, obs.left_ok, obs.link_ok)
        self.lidar_r.update_card(obs.right_m, obs.right_ok, obs.link_ok)
        # 단차(턱) — 기획 배경의 "턱 걸림"
        if obs.curb_m is not None:
            kind = "내려가는 턱" if obs.curb_type == "drop" else "올라가는 턱"
            self.curb_lbl.config(
                text=f"⚠  전방 {obs.curb_m:.2f} m  {kind} 감지",
                fg=C_RED if obs.curb_type == "drop" else C_YELLOW)
        else:
            self.curb_lbl.config(text="")

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
            d is not None and d <= config.DIST_DANGER_M
            for d in (obs.left_m, obs.right_m))
        self._set_flash(danger and self._popup is None)

        # 헤더 종합 상태
        if st.tipover_state not in (TIPOVER_NORMAL,):
            self.overall.config(text=f"●  {st.tipover_state}", fg=C_RED)
        elif not st.imu.valid:
            self.overall.config(text="●  IMU 이상", fg=C_RED)
        else:
            lv = max(dist_to_level(obs.left_m), dist_to_level(obs.right_m))
            self.overall.config(text=f"●  {level_text(lv)}", fg=level_color(lv))

        self.root.after(self.REFRESH_MS, self._refresh)

    def _set_flash(self, on):
        if on and not self._flashing:
            self.flash.start()
            self._flashing = True
            self.term.append("🚨 위험 거리 감지 — 화면 경고 활성화", "ERROR")
        elif not on and self._flashing:
            self.flash.stop()
            self._flashing = False

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
        self.cmd.send(CMD_SOS)
        self.term.append("🆘 SOS 전송 — 즉시 보호자에게 신고합니다", "ERROR")

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
