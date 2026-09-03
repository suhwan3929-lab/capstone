"""
센서 시뮬레이터 — 하드웨어 없이 전체 시스템을 돌린다.

왜 필요한가
    8인 팀에 하드웨어는 한 세트뿐이다. 나머지 7명이 센서를 기다리며
    아무것도 못 하는 상황을 없애기 위한 것이다.
    전도 판정·알림·UI·UDP 링크는 전부 이 모드에서 개발하고 검증할 수 있다.

사용법
    python safety_monitor.py --sim --scenario tipover_front
    python run_dev.py --sim --scenario curb

시나리오
    normal_walk  정상 보행 — 미세 진동, 기울기 거의 0
    curb         보도블록 턱 넘기 — 짧고 큰 충격, 자세는 유지  (음성 샘플)
    sudden_stop  급정지                                        (음성 샘플)
    place_down     보행기를 바닥에 눕혀둠 — 충격 + 기울기 유지   (오탐 유발 케이스)
    tipover_front 전방 전도 — 충격 후 쓰러진 자세 유지          (양성 샘플)
    tipover_side  측방 전도 (roll 축)                          (양성 샘플)
    tipover_rear  후방 전도 (pitch 음수)                        (양성 샘플)
    tipover_recover 넘어졌다가 스스로 일어남                      (해제되어야 함)
    obstacle     전방 장애물이 서서히 접근 (LiDAR 경고 확인용)
    sensor_drop  10초 후 IMU가 죽는다 (워치독 확인용)

⚠ 이 모듈이 만드는 값은 '그럴듯한 모형'이지 실측이 아니다.
  임계값 확정은 반드시 실제 데이터(tools/replay.py)로 해야 한다.
"""
import math
import random
import threading
import time

import config
from schema import GpsFix, ImuSample, ObstacleReport
from states import CONN_ERROR, CONN_OK, CONN_WAITING

_start_t = 0.0
_scenario = "normal_walk"
_running = False
_log = None
_lock = threading.Lock()
_imu = ImuSample()
_gps = GpsFix()
_obs = ObstacleReport()

#: 광주 조선대 부근 — 시연 시연장 좌표로 바꿔 쓸 것
_BASE_LAT, _BASE_LON = 35.1595, 126.8526


def _emit(msg, level="INFO"):
    if _log:
        _log(f"[시뮬] {msg}", level)


# ══════════════════════════════════════════════════════════
# 시나리오 정의
#   t (초) → (accel_g, roll_deg, pitch_deg, gyro_dps, obstacle_m, imu_alive)
# ══════════════════════════════════════════════════════════
def _noise(scale=0.02):
    return random.gauss(0, scale)


def _scn_normal_walk(t):
    # 보행 리듬 ~1.8 Hz의 미세 진동
    a = 1.0 + 0.08 * math.sin(t * 11.3) + _noise(0.03)
    return a, _noise(1.5), 2.0 + _noise(1.5), abs(_noise(8)), None, True


def _scn_curb(t):
    a, r, p, g, o, alive = _scn_normal_walk(t)
    if 6.0 <= t < 6.12:                 # 턱을 넘는 순간
        a, g = 3.4, 140
        p = 12.0
    if 5.0 <= t < 7.0:                  # 턱이 앞에 보인다
        o = max(0.25, 1.6 - (t - 5.0) * 0.7)
    return a, r, p, g, o, alive


def _scn_sudden_stop(t):
    a, r, p, g, o, alive = _scn_normal_walk(t)
    if 6.0 <= t < 6.25:
        a, p, g = 3.1, 18.0, 90
    return a, r, p, g, o, alive


def _scn_place_down(t):
    """보행기를 바닥에 눕혀두고 자리를 뜬다 — 사고로 오판하기 쉬운 케이스."""
    if t < 5.0:
        return _scn_normal_walk(t)
    if t < 5.2:
        return 3.6, 40.0, 20.0, 250, None, True
    # 눕혀진 채 정지 → 기울기 조건만으로는 실제 전도와 구분되지 않는다.
    # 실제 구분은 '사용자가 취소 버튼을 누르는가'로 이뤄진다.
    return 1.0 + _noise(0.01), 88.0 + _noise(0.5), 5.0 + _noise(0.5), \
        abs(_noise(1)), None, True


def _scn_tipover_front(t):
    if t < 6.0:
        return _scn_normal_walk(t)
    if t < 6.15:                        # 충격
        return 4.6, 20.0, 55.0, 380, 0.4, True
    # 쓰러진 자세로 정지
    return 1.0 + _noise(0.02), 12.0 + _noise(1), 82.0 + _noise(1), \
        abs(_noise(2)), None, True


def _scn_tipover_side(t):
    """측방 전도 — roll 축으로 넘어진다."""
    if t < 6.0:
        return _scn_normal_walk(t)
    if t < 6.15:
        return 5.1, 62.0, 15.0, 420, 0.4, True
    return 1.0 + _noise(0.02), 86.0 + _noise(1), 8.0 + _noise(1),         abs(_noise(2)), None, True


def _scn_tipover_rear(t):
    """후방 전도 — 뒤로 넘어간다. pitch 부호가 전방과 반대."""
    if t < 6.0:
        return _scn_normal_walk(t)
    if t < 6.15:
        return 4.2, 18.0, -50.0, 350, None, True
    return 1.0 + _noise(0.02), 10.0 + _noise(1), -78.0 + _noise(1),         abs(_noise(2)), None, True


def _scn_tipover_recover(t):
    a, r, p, g, o, alive = _scn_tipover_front(t)
    if t >= 12.0:                       # 스스로 일어난다
        phase = min(1.0, (t - 12.0) / 3.0)
        p = 82.0 * (1 - phase)
        r = 12.0 * (1 - phase)
        g = 120 if (t * 3) % 1 < 0.3 else 20
        a = 1.0 + (1.6 if (t * 2) % 1 < 0.2 else 0.0)
    return a, r, p, g, o, alive


def _scn_obstacle(t):
    a, r, p, g, _o, alive = _scn_normal_walk(t)
    # 3 m 앞 장애물로 0.35 m/s 속도로 접근 → 12초 뒤 위험 구간
    d = max(0.18, 3.0 - t * 0.35)
    return a, r, p, g, d, alive


def _scn_sensor_drop(t):
    a, r, p, g, o, _alive = _scn_normal_walk(t)
    return a, r, p, g, o, t < 10.0      # 10초 후 IMU 사망


SCENARIOS = {
    "normal_walk": _scn_normal_walk,
    "curb": _scn_curb,
    "sudden_stop": _scn_sudden_stop,
    "place_down": _scn_place_down,
    "tipover_front": _scn_tipover_front,
    "tipover_side": _scn_tipover_side,
    "tipover_rear": _scn_tipover_rear,
    "tipover_recover": _scn_tipover_recover,
    "obstacle": _scn_obstacle,
    "sensor_drop": _scn_sensor_drop,
}


# ══════════════════════════════════════════════════════════
# 구동
# ══════════════════════════════════════════════════════════
def start(scenario=None, log_callback=None) -> bool:
    global _running, _start_t, _scenario, _log
    _log = log_callback
    _scenario = scenario or config.SIM_SCENARIO
    if _scenario not in SCENARIOS:
        _emit(f"알 수 없는 시나리오 '{_scenario}' — "
              f"사용 가능: {', '.join(SCENARIOS)}", "ERROR")
        _scenario = "normal_walk"
    _start_t = time.time()
    _running = True
    _emit(f"시뮬레이션 시작: {_scenario} (하드웨어 없음)", "SYSTEM")
    threading.Thread(target=_loop, daemon=True, name="Sim").start()
    return True


def stop():
    global _running
    _running = False


def elapsed() -> float:
    return time.time() - _start_t if _start_t else 0.0


def imu_snapshot() -> ImuSample:
    with _lock:
        return ImuSample(**vars(_imu))


def gps_snapshot() -> GpsFix:
    with _lock:
        return GpsFix(**vars(_gps))


def obstacle_snapshot() -> ObstacleReport:
    with _lock:
        return ObstacleReport(**vars(_obs))


def _loop():
    fn = SCENARIOS[_scenario]
    period = 0.01                       # 100 Hz (실제 IMU와 같은 속도)
    next_t = time.monotonic()
    announced_end = False

    while _running:
        t = elapsed()
        a, r, p, g, obs_m, alive = fn(t)
        now = time.time()

        with _lock:
            if alive:
                _imu.__dict__.update(
                    t_capture=now, roll_deg=r, pitch_deg=p, yaw_deg=0.0,
                    accel_g=a, gyro_dps=g, status=CONN_OK, valid=True)
            else:
                _imu.status = CONN_ERROR
                _imu.valid = False      # t_capture를 갱신하지 않아 워치독이 잡는다

            # GPS: 기준점 주변을 천천히 이동. 8초 뒤 RTK FIX를 얻는 것으로 모사.
            _gps.__dict__.update(
                t_capture=now,
                lat=_BASE_LAT + t * 2.5e-6,
                lon=_BASE_LON + t * 1.5e-6,
                alt_m=72.0, speed_kmh=2.6,
                fix_quality=4 if t > 8 else (1 if t > 2 else 0),
                satellites=int(min(22, 6 + t)),
                hdop=max(0.6, 2.4 - t * 0.1),
                utc=time.strftime("%H:%M:%S", time.gmtime()),
                status=CONN_OK if t > 2 else CONN_WAITING,
                valid=t > 2)

            # curb 시나리오에서만 단차를 모사한다
            curb_m, curb_type = None, ""
            if _scenario == "curb" and 4.0 <= t < 6.2:
                curb_m, curb_type = max(0.1, 1.15 - (t - 4.0) * 0.5), "rise"

            _obs.__dict__.update(
                t_capture=now,
                left_m=obs_m,
                right_m=None if obs_m is None else obs_m + 0.35,
                curb_m=curb_m, curb_type=curb_type,
                left_ok=True, right_ok=True, link_ok=True, latency_s=0.01)

        if not alive and not announced_end:
            announced_end = True
            _emit("시나리오: IMU 사망 — 워치독이 잡아야 합니다", "WARN")

        next_t += period
        time.sleep(max(0.0, next_t - time.monotonic()))
