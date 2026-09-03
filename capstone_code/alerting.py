"""
경고 출력 — 부저 / LED / 손잡이 진동

이 모듈이 없으면 시스템의 경고가 **사용자에게 도달하지 않는다.**
지금까지 경고는 노트북 화면 깜박임뿐이었는데, 보행기를 미는 고령자는
1280×720 화면을 보고 있지 않다. GUI는 개발자용 모니터링 도구이고,
실제 사용자 경고 경로는 이쪽이다.

설계 근거 (계획서 리뷰 §2.7 / 코드_리뷰 §3.7)
  * **노인성 난청은 고주파부터 손실된다.** 흔히 쓰는 4 kHz 부저는
    정작 대상 사용자에게 들리지 않을 수 있다 → 1~3 kHz 대역을 쓴다.
  * 청각에만 의존하지 않는다 → **손잡이 진동을 병행**한다.
  * 거리 3단계로 음 간격을 바꾼다 → 주차센서와 같은 멘탈 모델.
  * **경보 피로 방지**: 히스테리시스로 등급이 떨리지 않게 하고,
    같은 등급을 계속 재고지하지 않는다.
  * **센서가 죽은 것을 조용히 넘기지 않는다** → 별도 패턴으로 주기 고지.

우선순위 (높은 것이 낮은 것을 덮어쓴다)
    사고 확정 > 응답 대기 > 충격 감지 > 장애물 위험 > 장애물 경고
    > 센서 이상 > 무음

백엔드
    gpio      : Raspberry Pi (gpiozero). 실기 구성.
    winsound  : 윈도우 개발 PC. 소리로 패턴을 확인할 수 있다.
    null      : 출력 없음(로그만). CI/헤드리스.
"""
import threading
import time

import config

# ── 경보 등급 (숫자가 클수록 우선) ────────────────────────
SILENT = 0
SENSOR_FAULT = 1
OBSTACLE_WARN = 2
OBSTACLE_DANGER = 3
TIPOVER_IMPACT = 4
TIPOVER_ASK = 5
TIPOVER_CONFIRMED = 6

LEVEL_NAME = {
    SILENT: "무음", SENSOR_FAULT: "센서 이상",
    OBSTACLE_WARN: "장애물 경고", OBSTACLE_DANGER: "장애물 위험",
    TIPOVER_IMPACT: "충격 감지", TIPOVER_ASK: "응답 대기", TIPOVER_CONFIRMED: "사고 확정",
}


# ══════════════════════════════════════════════════════════
# 백엔드
# ══════════════════════════════════════════════════════════
class _NullBackend:
    name = "null"

    def tone(self, freq, ms):
        time.sleep(ms / 1000.0)

    def led(self, warn, danger):
        pass

    def vibrate(self, on):
        pass

    def close(self):
        pass


class _WinsoundBackend(_NullBackend):
    """윈도우 개발 PC용. 실제 소리로 패턴을 검증할 수 있다."""
    name = "winsound"

    def __init__(self):
        import winsound
        self._ws = winsound

    def tone(self, freq, ms):
        try:
            # winsound.Beep은 37~32767 Hz만 받는다
            self._ws.Beep(max(37, min(32767, int(freq))), max(1, int(ms)))
        except Exception:
            time.sleep(ms / 1000.0)


class _GpioBackend(_NullBackend):
    """Raspberry Pi. 부저는 PWM으로 주파수를 만든다."""
    name = "gpio"

    def __init__(self):
        from gpiozero import PWMOutputDevice, TonalBuzzer  # noqa: F401
        from gpiozero import DigitalOutputDevice
        self._buzzer = PWMOutputDevice(config.BUZZER_PIN, frequency=1000)
        self._vib = DigitalOutputDevice(config.VIBRATOR_PIN)
        self._led_w = DigitalOutputDevice(config.LED_WARN_PIN)
        self._led_d = DigitalOutputDevice(config.LED_DANGER_PIN)
        self._led_state = (None, None)

    def tone(self, freq, ms):
        self._buzzer.frequency = max(50, int(freq))
        self._buzzer.value = config.BUZZER_DUTY
        time.sleep(ms / 1000.0)
        self._buzzer.value = 0.0

    def led(self, warn, danger):
        # 매 프레임 GPIO를 두드리지 않는다 — 값이 바뀔 때만 쓴다
        if (warn, danger) == self._led_state:
            return
        self._led_state = (warn, danger)
        self._led_w.value = bool(warn)
        self._led_d.value = bool(danger)

    def vibrate(self, on):
        self._vib.value = bool(on)

    def close(self):
        try:
            self._buzzer.value = 0.0
            self._vib.off()
            self._led_w.off()
            self._led_d.off()
            for d in (self._buzzer, self._vib, self._led_w, self._led_d):
                d.close()
        except Exception:
            pass


def _make_backend(log):
    want = config.ALERT_BACKEND
    order = [want] if want != "auto" else ["gpio", "winsound", "null"]
    for name in order:
        try:
            if name == "gpio":
                b = _GpioBackend()
            elif name == "winsound":
                b = _WinsoundBackend()
            elif name == "null":
                b = _NullBackend()
            else:
                continue
            log(f"[경고] 출력 백엔드: {b.name}", "SYSTEM")
            return b
        except Exception as e:
            if want != "auto":
                log(f"[경고] 백엔드 '{name}' 사용 불가: {type(e).__name__}", "WARN")
    return _NullBackend()


# ══════════════════════════════════════════════════════════
# 경보기
# ══════════════════════════════════════════════════════════
class Alerter:
    def __init__(self, log_callback=None):
        self._log = log_callback or (lambda *a, **k: None)
        self._lock = threading.Lock()
        self._level = SILENT
        self._detail = ""
        self._running = False
        self._backend = None
        self._last_announced = (SILENT, 0.0)
        self._last_fault_beep = 0.0
        # 히스테리시스 상태 — 등급을 올릴 때는 즉시, 내릴 때는 여유를 요구한다
        self._obstacle_level = SILENT

    # ────────────────────────────────────────── 수명주기
    def start(self):
        if not config.ALERT_ENABLED:
            self._log("[경고] 출력 비활성화 (config.ALERT_ENABLED=False)", "WARN")
            return
        self._backend = _make_backend(self._log)
        self._running = True
        threading.Thread(target=self._loop, daemon=True, name="Alerter").start()

    def stop(self):
        self._running = False
        time.sleep(0.15)
        if self._backend:
            self._backend.close()

    @property
    def backend_name(self):
        return self._backend.name if self._backend else "미시작"

    # ────────────────────────────────────────── 입력
    def update(self, obstacle_m, tipover_level, sensor_fault: bool, moving=True):
        """
        safety_monitor가 매 주기 호출한다.
          obstacle_m   : 최근접 장애물 거리 (None = 없음/사용 불가)
          tipover_level   : SILENT / TIPOVER_IMPACT / TIPOVER_ASK / TIPOVER_CONFIRMED
          sensor_fault : 센서 하나라도 죽어 있는가
          moving       : 보행기가 움직이는가 (정지 중엔 장애물 경고를 죽인다)
        """
        obs = self._obstacle_grade(obstacle_m, moving)
        level = max(tipover_level, obs, SENSOR_FAULT if sensor_fault else SILENT)

        detail = ""
        if level in (OBSTACLE_WARN, OBSTACLE_DANGER) and obstacle_m is not None:
            detail = f"{obstacle_m:.2f} m"

        with self._lock:
            changed = level != self._level
            self._level, self._detail = level, detail

        if changed:
            self._announce(level, detail)

    def _obstacle_grade(self, d, moving):
        """
        히스테리시스: 올릴 때는 즉시, 내릴 때는 여유(DIST_HYSTERESIS_M)를 요구한다.
        이게 없으면 임계값 근처에서 경보가 딸꾹질하듯 떨려 경보 피로를 만든다.
        """
        if d is None:
            self._obstacle_level = SILENT
            return SILENT
        # 정지 상태에서는 장애물 경고를 울리지 않는다 (경보 피로 방지)
        if not moving:
            self._obstacle_level = SILENT
            return SILENT

        h = config.DIST_HYSTERESIS_M
        cur = self._obstacle_level
        if d <= config.DIST_DANGER_M:
            new = OBSTACLE_DANGER
        elif d <= config.DIST_WARN_M:
            new = OBSTACLE_WARN
        else:
            new = SILENT

        if new < cur:      # 등급을 낮추려면 여유만큼 더 멀어져야 한다
            if cur == OBSTACLE_DANGER and d < config.DIST_DANGER_M + h:
                new = OBSTACLE_DANGER
            elif cur == OBSTACLE_WARN and d < config.DIST_WARN_M + h:
                new = OBSTACLE_WARN
        self._obstacle_level = new
        return new

    def _announce(self, level, detail):
        prev, t = self._last_announced
        now = time.time()
        # 같은 등급을 짧은 간격으로 반복 고지하지 않는다
        if level == prev and (now - t) < config.ALERT_MIN_REPEAT_SEC:
            return
        self._last_announced = (level, now)
        if level == SILENT:
            return
        sev = "ERROR" if level >= OBSTACLE_DANGER else "WARN"
        txt = LEVEL_NAME.get(level, str(level))
        self._log(f"[경고] {txt}{(' — ' + detail) if detail else ''}", sev)

    # ────────────────────────────────────────── 출력 루프
    def _loop(self):
        while self._running:
            with self._lock:
                level = self._level
            try:
                self._render(level)
            except Exception as e:
                self._log(f"[경고] 출력 예외: {type(e).__name__}: {e}", "ERROR")
                time.sleep(0.5)

    def _render(self, level):
        b = self._backend
        if level == SILENT:
            b.led(False, False)
            b.vibrate(False)
            time.sleep(0.1)
            return

        if level == SENSOR_FAULT:
            # 조용히 죽지 않는다. 다만 계속 울리면 무시당하므로 주기적으로만.
            now = time.time()
            if now - self._last_fault_beep < config.SENSOR_FAULT_REPEAT_SEC:
                b.led(True, False)
                time.sleep(0.2)
                return
            self._last_fault_beep = now
            on, off = config.PATTERN_SENSOR_FAULT
            for _ in range(2):
                b.tone(config.BUZZER_FREQ_WARN, on)
                time.sleep(off / 1000.0)
            return

        if level == OBSTACLE_WARN:
            b.led(True, False)
            on, off = config.PATTERN_WARN
            b.tone(config.BUZZER_FREQ_WARN, on)
            self._sleep_ms(off)
            return

        if level == OBSTACLE_DANGER:
            b.led(True, True)
            b.vibrate(True)
            on, off = config.PATTERN_DANGER
            b.tone(config.BUZZER_FREQ_DANGER, on)
            b.vibrate(False)
            self._sleep_ms(off)
            return

        if level == TIPOVER_IMPACT:
            b.led(True, True)
            b.vibrate(True)
            b.tone(config.BUZZER_FREQ_FALL, 300)
            b.vibrate(False)
            self._sleep_ms(400)
            return

        if level == TIPOVER_ASK:
            # 다급한 교대음 — 사용자가 취소 버튼을 눌러야 하는 구간
            b.led(True, True)
            on, off = config.PATTERN_TIPOVER_ASK
            b.vibrate(True)
            b.tone(config.BUZZER_FREQ_FALL, on)
            b.tone(config.BUZZER_FREQ_DANGER, on)
            b.vibrate(False)
            self._sleep_ms(off)
            return

        if level == TIPOVER_CONFIRMED:
            # 인터넷이 끊겨 보호자 알림이 실패해도 이 소리는 울려야 한다.
            # 주변 사람의 도움을 유도하는 것이 마지막 방어선이다.
            b.led(True, True)
            b.vibrate(True)
            for f in (config.BUZZER_FREQ_FALL, config.BUZZER_FREQ_DANGER):
                b.tone(f, 250)
            b.vibrate(False)
            self._sleep_ms(150)
            return

        time.sleep(0.1)

    def _sleep_ms(self, ms):
        """중간에 등급이 바뀌면 즉시 빠져나온다 (반응 지연 방지)."""
        end = time.time() + ms / 1000.0
        cur = self._level
        while self._running and time.time() < end:
            if self._level != cur:
                return
            time.sleep(0.02)


def tipover_state_to_level(tipover_state: str) -> int:
    """states.TIPOVER_* → 경보 등급"""
    from states import (TIPOVER_ASKING, TIPOVER_CHECKING, TIPOVER_CONFIRMED as S_CONF,
                        TIPOVER_REPORTED, TIPOVER_STABILIZING)
    return {
        TIPOVER_STABILIZING: TIPOVER_IMPACT,
        TIPOVER_CHECKING: TIPOVER_IMPACT,
        TIPOVER_ASKING: TIPOVER_ASK,
        S_CONF: TIPOVER_CONFIRMED,
        TIPOVER_REPORTED: TIPOVER_CONFIRMED,
    }.get(tipover_state, SILENT)
