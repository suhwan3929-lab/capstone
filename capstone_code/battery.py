"""
배터리 잔량 측정 + 저전압 안전 종료

왜 필요한가
  이전 코드는 `/sys/class/power_supply/BAT0` 를 읽었는데
  **Raspberry Pi 5에는 BAT0가 없다.** 그래서 항상 100%를 반환했고,
  화면에는 언제나 초록색 만충 표시가 떴다.
  틀린 계기판은 없는 계기판보다 나쁘다 — 실제로 5% 남았는데 100%로 보이면
  시연 도중 전원이 나가도 원인을 못 찾는다.

  또한 Jetson/Pi를 전원 차단으로 그냥 끄면 파일시스템이 깨진다.
  잔량이 바닥나기 전에 **정상 종료**시키는 것이 SSD/SD 카드를 지키는 유일한 방법이다.

백엔드
  ina219   : 전류/전압 모니터 (I2C). 전압 + 소비전류까지 볼 수 있어 권장.
  max17043 : LiPo 연료 게이지 (I2C). 1셀 기준이라 분압 필요.
  sysfs    : 노트북 등 BAT0가 실제로 있는 환경
  null     : 측정 수단 없음 → percent=None ("측정 안 됨"으로 표시된다)

⚠ 자작 리튬팩에는 BMS(과충전/과방전/과전류/셀 밸런싱)와 인라인 퓨즈가 필수다.
  고령자가 체중을 싣는 기구에 들어가는 배터리다. (계획서 리뷰 §5.4)
"""
import os
import subprocess
import threading
import time

import config

#: 리튬이온 1셀 개방전압 → 잔량(%) 근사 곡선.
#: 부하 시 전압 강하 때문에 실제보다 낮게 나온다 — 대략치로만 쓸 것.
#: 정확한 잔량이 필요하면 쿨롱 카운팅(MAX17043 등)을 써야 한다.
_LI_CURVE = [
    (4.20, 100), (4.10, 92), (4.00, 85), (3.90, 74), (3.80, 62),
    (3.70, 50), (3.60, 34), (3.50, 20), (3.40, 10), (3.30, 5), (3.00, 0),
]

_lock = threading.Lock()
_state = {"percent": None, "volts": None, "current_a": None,
          "charging": False, "backend": "미시작", "t": 0.0}
_running = False
_log = None
_warned = set()


def _emit(msg, level="INFO"):
    if _log:
        _log(f"[배터리] {msg}", level)


# ══════════════════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════════════════
def snapshot() -> dict:
    with _lock:
        return dict(_state)


def percent():
    with _lock:
        return _state["percent"]


def start(log_callback=None) -> bool:
    global _running, _log
    _log = log_callback
    backend = _make_backend()
    with _lock:
        _state["backend"] = backend.name
    if backend.name == "null":
        _emit("측정 수단 없음 — 잔량은 '측정 안 됨'으로 표시됩니다. "
              "실기에는 연료 게이지(INA219/MAX17043)를 반드시 달 것.", "WARN")
    else:
        _emit(f"백엔드: {backend.name}", "SYSTEM")
    _running = True
    threading.Thread(target=_loop, args=(backend,), daemon=True,
                     name="Battery").start()
    return backend.name != "null"


def stop():
    global _running
    _running = False


def volts_to_percent(v_pack, cells=None) -> float:
    cells = cells or config.BATTERY_CELLS
    vc = v_pack / max(1, cells)
    if vc >= _LI_CURVE[0][0]:
        return 100.0
    if vc <= _LI_CURVE[-1][0]:
        return 0.0
    for (v_hi, p_hi), (v_lo, p_lo) in zip(_LI_CURVE, _LI_CURVE[1:]):
        if v_lo <= vc <= v_hi:
            r = (vc - v_lo) / (v_hi - v_lo)
            return round(p_lo + r * (p_hi - p_lo), 1)
    return 0.0


# ══════════════════════════════════════════════════════════
# 백엔드
# ══════════════════════════════════════════════════════════
class _NullBackend:
    name = "null"

    def read(self):
        return None, None, None, False


class _SysfsBackend(_NullBackend):
    name = "sysfs"
    BASE = "/sys/class/power_supply/BAT0"

    def __init__(self):
        if not os.path.exists(f"{self.BASE}/capacity"):
            raise FileNotFoundError(self.BASE)

    def read(self):
        with open(f"{self.BASE}/capacity") as f:
            pct = float(f.read().strip())
        charging = False
        try:
            with open(f"{self.BASE}/status") as f:
                charging = f.read().strip().lower() in ("charging", "full")
        except OSError:
            pass
        volts = None
        try:
            with open(f"{self.BASE}/voltage_now") as f:
                volts = int(f.read().strip()) / 1e6
        except OSError:
            pass
        return pct, volts, None, charging


class _Ina219Backend(_NullBackend):
    """전압 + 전류. 전류 부호로 충전/방전을 구분한다."""
    name = "ina219"
    REG_BUSVOLT, REG_CURRENT, REG_CONFIG, REG_CALIB = 0x02, 0x04, 0x00, 0x05

    def __init__(self):
        from smbus2 import SMBus
        self._bus = SMBus(config.BATTERY_I2C_BUS)
        self._addr = config.BATTERY_INA219_ADDR
        # 32V / 최대 3.2A 레인지, 12bit 연속 측정
        self._write(self.REG_CONFIG, 0x399F)
        self._write(self.REG_CALIB, 4096)
        self.read()      # 통신 확인 (실패하면 여기서 예외)

    def _write(self, reg, val):
        self._bus.write_i2c_block_data(self._addr, reg,
                                       [(val >> 8) & 0xFF, val & 0xFF])

    def _read16(self, reg):
        hi, lo = self._bus.read_i2c_block_data(self._addr, reg, 2)
        return (hi << 8) | lo

    def read(self):
        raw = self._read16(self.REG_BUSVOLT)
        volts = (raw >> 3) * 0.004          # LSB = 4 mV
        cur = self._read16(self.REG_CURRENT)
        if cur > 32767:
            cur -= 65536
        amps = cur / 10000.0                # 캘리브레이션에 따른 배율
        return volts_to_percent(volts), volts, amps, amps < -0.02


class _Max17043Backend(_NullBackend):
    """쿨롱 카운팅 기반 1셀 연료 게이지."""
    name = "max17043"

    def __init__(self):
        from smbus2 import SMBus
        self._bus = SMBus(config.BATTERY_I2C_BUS)
        self._addr = config.BATTERY_MAX17043_ADDR
        self.read()

    def read(self):
        vh, vl = self._bus.read_i2c_block_data(self._addr, 0x02, 2)
        sh, sl = self._bus.read_i2c_block_data(self._addr, 0x04, 2)
        volts = ((vh << 4) | (vl >> 4)) * 0.00125
        pct = sh + sl / 256.0
        return round(pct, 1), volts, None, False


def _make_backend():
    want = config.BATTERY_BACKEND
    order = [want] if want != "auto" else ["ina219", "max17043", "sysfs", "null"]
    for name in order:
        try:
            if name == "ina219":
                return _Ina219Backend()
            if name == "max17043":
                return _Max17043Backend()
            if name == "sysfs":
                return _SysfsBackend()
            return _NullBackend()
        except Exception:
            continue
    return _NullBackend()


# ══════════════════════════════════════════════════════════
# 감시 루프
# ══════════════════════════════════════════════════════════
def _loop(backend):
    while _running:
        try:
            pct, volts, amps, charging = backend.read()
            with _lock:
                _state.update(percent=pct, volts=volts, current_a=amps,
                              charging=charging, t=time.time())
            if pct is not None and not charging:
                _check_thresholds(pct)
            elif charging:
                _warned.clear()
        except Exception as e:
            _emit(f"측정 실패: {type(e).__name__}: {e}", "WARN")
            with _lock:
                _state.update(percent=None, t=time.time())
        end = time.time() + config.BATTERY_POLL_SEC
        while _running and time.time() < end:
            time.sleep(0.2)


def _check_thresholds(pct):
    if pct <= config.BATTERY_SHUTDOWN_PCT:
        if "shutdown" not in _warned:
            _warned.add("shutdown")
            _emit(f"잔량 {pct:.0f}% — 안전 종료를 시작합니다", "ERROR")
            _safe_shutdown()
    elif pct <= config.BATTERY_CRITICAL_PCT:
        if "critical" not in _warned:
            _warned.add("critical")
            _emit(f"⚠ 잔량 {pct:.0f}% — 곧 자동 종료됩니다", "ERROR")
    elif pct <= config.BATTERY_WARN_PCT:
        if "warn" not in _warned:
            _warned.add("warn")
            _emit(f"잔량 {pct:.0f}% — 충전이 필요합니다", "WARN")
    else:
        _warned.clear()


def _safe_shutdown():
    """
    전원이 끊기기 전에 OS를 정상 종료시킨다.
    ⚠ 전원 스위치로 그냥 끊으면 파일시스템이 깨진다.
      학기 말에 SSD가 부팅 불가가 되는 사고가 실제로 자주 발생한다.
    """
    if not config.BATTERY_SHUTDOWN_ENABLED:
        _emit("(자동 종료 비활성 — config.BATTERY_SHUTDOWN_ENABLED=False)", "WARN")
        return
    try:
        subprocess.Popen(["sudo", "shutdown", "-h", "+1",
                          "walker: battery critical"])
        _emit("1분 후 시스템이 종료됩니다", "ERROR")
    except Exception as e:
        _emit(f"종료 명령 실패: {type(e).__name__}: {e}", "ERROR")
