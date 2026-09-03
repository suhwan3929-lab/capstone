"""
IMU 드라이버 (EBIMU-9DOFV6)

이 모듈은 **순수 드라이버**다. 전도 판정 로직은 여기 없다 (→ tipover_monitor.py).
  * 시리얼에서 읽어 파싱한다
  * 장착각 오프셋을 보정한다
  * 최신 샘플을 ImuSample로 제공한다
그게 전부다. ROS 2 이행 시 이 모듈이 imu_node가 되고, 판정은 별도 노드가 된다.

이전 버전 대비 수정:
  [C2] 런타임 재연결 — 예외 1회로 스레드가 죽던 문제
  [C3] last_rx 기록 — 데이터가 끊겨도 "정상"으로 표시되던 문제
  [C6] 필드 수 엄격 검사 + 정지 시 1g 자체 진단 — 인덱스가 조용히 밀리던 문제
  [M4] 장착각 오프셋 보정
"""
import math
import threading
import time

import config
from schema import ImuSample
from states import CONN_ERROR, CONN_OK, CONN_STALE, CONN_WAITING

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

#: EBIMU 출력 설정. <sof1>=오일러각, <sog1>=자이로, <soa1>=가속도(중력포함, g)
#: 나머지는 전부 끈다 — 켜져 있으면 필드 개수가 늘어 인덱스가 밀린다. [C6]
SETUP_COMMANDS = ["<sof1>", "<sog1>", "<soa1>",
                  "<som0>", "<sod0>", "<sot0>", "<sots0>"]
EXPECTED_FIELDS = 9          # roll,pitch,yaw, gx,gy,gz, ax,ay,az

_lock = threading.Lock()
_sample = ImuSample()
_running = False
_log = None
_selfcheck_done = False
_selfcheck_buf = []


def _emit(msg, level="INFO"):
    if _log:
        _log(f"[IMU] {msg}", level)


# ══════════════════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════════════════
def snapshot() -> ImuSample:
    """최신 샘플. 수신이 끊겼으면 valid=False로 강등해서 돌려준다. [C3]"""
    with _lock:
        s = ImuSample(**vars(_sample))
    if s.valid and (time.time() - s.t_capture) > config.STALE_IMU_SEC:
        s.valid = False
        s.status = CONN_STALE
    return s


def start(log_callback=None) -> bool:
    global _running, _log
    _log = log_callback
    if not SERIAL_AVAILABLE:
        _set(status=CONN_ERROR, valid=False)
        _emit("pyserial 미설치", "ERROR")
        return False
    _running = True
    threading.Thread(target=_supervisor, daemon=True, name="IMU").start()
    return True


def stop():
    global _running
    _running = False


def capture_mount_offset(duration=2.0):
    """
    수평 정지 상태에서 호출하면 장착각 오프셋을 측정해 돌려준다.
    출력값을 config_local.py 의 MOUNT_*_OFFSET_DEG 에 적어 넣을 것.
    """
    rolls, pitches = [], []
    t_end = time.time() + duration
    while time.time() < t_end:
        s = snapshot()
        if s.valid:
            # 보정 전 원값으로 되돌려서 평균낸다
            rolls.append(s.roll_deg + config.MOUNT_ROLL_OFFSET_DEG)
            pitches.append(s.pitch_deg + config.MOUNT_PITCH_OFFSET_DEG)
        time.sleep(0.02)
    if not rolls:
        return None
    return (sum(rolls) / len(rolls), sum(pitches) / len(pitches))


# ══════════════════════════════════════════════════════════
# 내부
# ══════════════════════════════════════════════════════════
def _set(**kw):
    with _lock:
        for k, v in kw.items():
            setattr(_sample, k, v)


def _parse(line: str):
    """
    EBIMU ASCII 한 줄 → float 리스트.
    한 필드라도 숫자가 아니면 그 줄 전체를 버린다(부분 파싱은 인덱스를 밀리게 한다).
    """
    line = line.strip().lstrip("*")
    if not line:
        return []
    out = []
    for tok in line.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(float(tok))
        except ValueError:
            return []
    return out


def _setup_sensor(ser):
    for c in SETUP_COMMANDS:
        ser.write(c.encode("ascii"))
        time.sleep(0.05)
        ser.reset_input_buffer()
    time.sleep(0.1)


def _self_check(accel_g):
    """
    [C6] 정지 상태에서 가속도 벡터합은 1 g여야 한다.
    아니라면 셋 중 하나다: 필드 순서 오인 / 단위 오인 / 가속도계 측정범위(FSR) 설정 오류.
    조용히 틀린 값을 쓰는 것보다 시끄럽게 경고하는 편이 낫다.
    """
    global _selfcheck_done
    if _selfcheck_done:
        return
    _selfcheck_buf.append(accel_g)
    if len(_selfcheck_buf) < 50:
        return
    avg = sum(_selfcheck_buf) / len(_selfcheck_buf)
    _selfcheck_done = True
    if abs(avg - 1.0) > 0.15:
        _emit(f"⚠ 정지 상태 가속도가 {avg:.2f}g (기대값 1.00g). "
              f"필드 순서 / 단위 / 가속도계 측정범위(FSR) 설정을 확인하세요. "
              f"FSR이 ±2g면 임계값 {config.IMPACT_THRESHOLD_G}g에 도달할 수 없습니다.", "ERROR")
    else:
        _emit(f"✅ 자체 진단 통과 (정지 시 {avg:.2f}g)", "INFO")


def _supervisor():
    """[C2] 끊기면 지수 백오프로 재연결한다. 프로그램이 사는 동안 계속."""
    backoff = 1.0
    while _running:
        ser = None
        try:
            _set(status=CONN_WAITING, valid=False)
            _emit(f"포트({config.IMU_PORT}) 연결 시도...")
            ser = serial.Serial(config.IMU_PORT, config.IMU_BAUD,
                                timeout=1, dsrdtr=False)
            _setup_sensor(ser)
            _emit("연결 성공", "INFO")
            backoff = 1.0
            _read_loop(ser)
        except Exception as e:
            _emit(f"연결 끊김: {type(e).__name__}: {e}", "ERROR")
        finally:
            _set(status=CONN_ERROR, valid=False)
            try:
                if ser:
                    ser.close()
            except Exception:
                pass
        if not _running:
            break
        _emit(f"{backoff:.0f}초 후 재연결", "WARN")
        _sleep_interruptible(backoff)
        backoff = min(backoff * 2, 30.0)


def _sleep_interruptible(sec):
    end = time.time() + sec
    while _running and time.time() < end:
        time.sleep(0.1)


def _read_loop(ser):
    bad_lines = 0
    while _running:
        raw = ser.readline()
        if not raw:
            continue                       # 타임아웃. status는 snapshot()이 강등한다
        parsed = _parse(raw.decode("utf-8", errors="ignore"))

        # [C6] '이하 배제'가 아니라 '정확히 9개'. 필드가 늘면 인덱스가 밀린다.
        if len(parsed) != EXPECTED_FIELDS:
            bad_lines += 1
            if bad_lines in (50, 500):
                _emit(f"⚠ 필드 개수 불일치 {bad_lines}회 "
                      f"(기대 {EXPECTED_FIELDS}개, 실제 {len(parsed)}개). "
                      f"출력 설정을 확인하세요.", "WARN")
            continue

        roll, pitch, yaw = parsed[0:3]
        gx, gy, gz = parsed[3:6]
        ax, ay, az = parsed[6:9]

        accel_g = math.sqrt(ax * ax + ay * ay + az * az)
        gyro_dps = math.sqrt(gx * gx + gy * gy + gz * gz)
        _self_check(accel_g)

        _set(t_capture=time.time(),
             roll_deg=roll - config.MOUNT_ROLL_OFFSET_DEG,      # [M4]
             pitch_deg=pitch - config.MOUNT_PITCH_OFFSET_DEG,
             yaw_deg=yaw,
             accel_g=accel_g,
             gyro_dps=gyro_dps,
             status=CONN_OK,
             valid=True)


def run_integrity_check(log_callback=None) -> bool:
    """
    시작 전 점검. [§2.9] '포트가 열린다'로 만족하지 않고
    실제로 유효 샘플이 들어오는지까지 확인한다.
    """
    global _log
    _log = log_callback
    if not SERIAL_AVAILABLE:
        _emit("pyserial 미설치", "ERROR")
        return False

    for attempt in range(1, 4):
        try:
            with serial.Serial(config.IMU_PORT, config.IMU_BAUD,
                               timeout=1, dsrdtr=False) as ser:
                _setup_sensor(ser)
                t_end = time.time() + 2.0
                while time.time() < t_end:
                    if len(_parse(ser.readline().decode("utf-8", "ignore"))) == EXPECTED_FIELDS:
                        _emit(f"✅ 유효 데이터 수신 확인 ({config.IMU_PORT})", "INFO")
                        return True
                _emit(f"포트는 열렸으나 유효 데이터 없음 ({attempt}/3)", "WARN")
        except Exception as e:
            _emit(f"연결 시도 {attempt}/3 실패: {type(e).__name__}: {e}", "WARN")
        time.sleep(1.0)

    _emit("3회 연결 실패", "ERROR")
    return False
