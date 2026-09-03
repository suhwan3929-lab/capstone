"""
물리 버튼 — 취소 / SOS

왜 필요한가
  오경보가 났을 때 고령자가 **1280×720 화면의 팝업 버튼을 찾아 누를 것**이라고
  가정해서는 안 된다. 손잡이에 붙은 큼직한 물리 버튼이 있어야 취소가 실제로 된다.
  취소 수단이 없으면 오경보 한 번으로 보호자의 신뢰가 무너지고,
  그 시점부터 이 시스템은 무시당한다.

버튼 2개
  취소 버튼 : 짧게 누름 → 판정 취소 / 팝업 응답 "아니오"
  SOS  버튼 : 2초 이상 길게 누름 → 사용자가 직접 긴급 호출
              (짧게 누르면 무시 — 주머니 눌림으로 신고가 나가면 안 된다)

배선 (BCM)
  버튼 한쪽 → GPIO 핀, 반대쪽 → GND. 내부 풀업 사용(pull_up=True).
  기계식 스위치는 채터링이 있으므로 bounce_time으로 걸러낸다.

백엔드
  gpio     : Raspberry Pi (gpiozero)
  keyboard : 개발 PC — 터미널에 n/s 입력으로 버튼을 흉내낸다
  null     : 없음
"""
import sys
import threading
import time

import config
from states import CMD_RESET, CMD_USER_NO, CMD_USER_YES

#: SOS는 별도 명령으로 다룬다 (states.CMD_* 와 같은 네임스페이스)
CMD_SOS = "sos"


class ButtonHub:
    def __init__(self, on_command, log_callback=None):
        self._cb = on_command
        self._log = log_callback or (lambda *a, **k: None)
        self._running = False
        self._backend = None

    def start(self):
        if not config.BUTTONS_ENABLED:
            return
        want = config.BUTTON_BACKEND
        order = [want] if want != "auto" else ["gpio", "keyboard", "null"]
        for name in order:
            try:
                if name == "gpio":
                    self._start_gpio()
                elif name == "keyboard":
                    self._start_keyboard()
                else:
                    self._backend = "null"
                self._backend = self._backend or name
                self._log(f"[버튼] 백엔드: {self._backend}", "SYSTEM")
                self._running = True
                return
            except Exception as e:
                if want != "auto":
                    self._log(f"[버튼] '{name}' 사용 불가: {type(e).__name__}", "WARN")
        self._backend = "null"

    def stop(self):
        self._running = False
        for d in getattr(self, "_devs", []):
            try:
                d.close()
            except Exception:
                pass

    # ────────────────────────────────────── GPIO
    def _start_gpio(self):
        from gpiozero import Button

        cancel = Button(config.BUTTON_CANCEL_PIN, pull_up=True,
                        bounce_time=config.BUTTON_BOUNCE_SEC)
        sos = Button(config.BUTTON_SOS_PIN, pull_up=True,
                     bounce_time=config.BUTTON_BOUNCE_SEC,
                     hold_time=config.BUTTON_SOS_HOLD_SEC)

        cancel.when_pressed = lambda: self._emit(CMD_USER_NO, "취소 버튼")
        # ★ when_held 만 연결한다. when_pressed를 쓰면 주머니 눌림으로 신고가 나간다.
        sos.when_held = lambda: self._emit(CMD_SOS, "SOS 버튼(길게 누름)")

        self._devs = [cancel, sos]
        self._backend = "gpio"

    # ────────────────────────────────────── 키보드 (개발용)
    def _start_keyboard(self):
        if not sys.stdin or not sys.stdin.isatty():
            raise RuntimeError("대화형 터미널이 아님")
        threading.Thread(target=self._kbd_loop, daemon=True, name="Buttons").start()
        self._backend = "keyboard"
        self._log("[버튼] 개발용 키 입력: n=취소  y=사고확인  s=SOS  r=리셋", "SYSTEM")

    def _kbd_loop(self):
        mapping = {"n": (CMD_USER_NO, "취소"), "y": (CMD_USER_YES, "사고 확인"),
                   "s": (CMD_SOS, "SOS"), "r": (CMD_RESET, "리셋")}
        while self._running or self._backend == "keyboard":
            try:
                line = sys.stdin.readline()
            except Exception:
                return
            if not line:
                return
            key = line.strip().lower()[:1]
            if key in mapping:
                cmd, name = mapping[key]
                self._emit(cmd, f"키보드 {name}")

    # ────────────────────────────────────── 공통
    def _emit(self, cmd, source):
        self._log(f"[버튼] {source} → {cmd}", "WARN")
        try:
            self._cb(cmd)
        except Exception as e:
            self._log(f"[버튼] 콜백 예외: {type(e).__name__}: {e}", "ERROR")
