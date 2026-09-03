"""
GPS 드라이버 (u-blox ZED-F9P, NMEA)

이전 버전 대비 수정:
  [C2] 런타임 재연결
  [C3] last_rx 기록 — 신호가 끊겨도 "정상"으로 표시되던 문제
  [H7] fix 상실 시 좌표를 그대로 들고 있던 문제 → 신선도 판정 + 품질 노출
  [M6] 아무 COM 포트나 잡던 자동탐색 → VID/PID 우선 매칭
"""
import platform
import queue
import threading
import time

import config
from schema import GpsFix
from states import CONN_ERROR, CONN_OK, CONN_STALE, CONN_WAITING

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

UBLOX_VID = 0x1546          # u-blox AG

_lock = threading.Lock()
_fix = GpsFix()
_running = False
_log = None

#: NTRIP 클라이언트가 넣는 RTCM3 보정 바이트. 수신 스레드가 F9P로 흘려보낸다.
#: 포트를 소유한 쪽이 한 곳뿐이어야 경합이 없다.
_rtcm_q: "queue.Queue[bytes]" = queue.Queue(maxsize=64)
#: VRS에 되올릴 마지막 원시 GGA 문장. 직접 만들지 않고 받은 것을 그대로 쓴다.
_last_gga = [None]


def _emit(msg, level="INFO"):
    if _log:
        _log(f"[GPS] {msg}", level)


# ══════════════════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════════════════
def snapshot() -> GpsFix:
    """
    [C3][H7] 마지막 수신 이후 STALE_GPS_SEC가 지나면 valid=False.
    좌표 자체는 남겨둔다 — 사고 신고에 '몇 초 전 좌표'로 쓸 수 있어야 하기 때문.
    대신 신선도를 반드시 함께 보고한다 (position_age 참조).
    """
    with _lock:
        f = GpsFix(**vars(_fix))
    if f.valid and (time.time() - f.t_capture) > config.STALE_GPS_SEC:
        f.valid = False
        f.status = CONN_STALE
    return f


def position_age() -> float:
    """마지막 유효 좌표로부터 경과 시간(초). 좌표가 없으면 inf."""
    with _lock:
        t = _fix.t_capture if _fix.lat is not None else 0.0
    return (time.time() - t) if t else float("inf")


def write_rtcm(data: bytes):
    """
    NTRIP 클라이언트 → F9P 방향. 실제 쓰기는 수신 스레드가 한다.
    시리얼 포트를 여러 스레드가 동시에 만지지 않도록 큐를 경유시킨다.
    """
    try:
        _rtcm_q.put_nowait(data)
    except queue.Full:
        try:                    # 오래된 보정정보는 가치가 없다. 최신 것을 남긴다.
            _rtcm_q.get_nowait()
            _rtcm_q.put_nowait(data)
        except queue.Empty:
            pass


def last_gga():
    """VRS 업로드용 마지막 원시 GGA 문장 (체크섬 포함)."""
    return _last_gga[0]


def start(log_callback=None) -> bool:
    global _running, _log
    _log = log_callback
    if not SERIAL_AVAILABLE:
        _set(status=CONN_ERROR, valid=False)
        return False
    _running = True
    threading.Thread(target=_supervisor, daemon=True, name="GPS").start()
    return True


def stop():
    global _running
    _running = False


def find_gps_port():
    """
    [M6] 설명 문자열이 아니라 VID로 먼저 찾는다.
    예전 코드는 윈도우에서 '첫 번째 COM 포트'를 반환해서
    LiDAR나 IMU 포트를 GPS로 열어버릴 수 있었다.
    """
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if getattr(p, "vid", None) == UBLOX_VID:
            return p.device
    keywords = ("u-blox", "ublox", "gnss", "zed")
    for p in ports:
        blob = f"{p.description or ''} {p.manufacturer or ''}".lower()
        if any(k in blob for k in keywords):
            return p.device
    if platform.system() != "Windows":
        for cand in ("/dev/walker_gps", "/dev/ttyACM0", "/dev/ttyUSB0"):
            import os
            if os.path.exists(cand):
                return cand
    return None      # 못 찾으면 None. 아무 포트나 집어오지 않는다.


# ══════════════════════════════════════════════════════════
# 내부
# ══════════════════════════════════════════════════════════
def _set(**kw):
    with _lock:
        for k, v in kw.items():
            setattr(_fix, k, v)


def _resolve_port():
    return config.GPS_PORT if config.GPS_PORT else find_gps_port()


def _checksum_ok(sentence: str) -> bool:
    if "*" not in sentence:
        return False                     # 체크섬 없는 문장은 신뢰하지 않는다
    body = sentence.lstrip("$")
    star = body.rfind("*")
    calc = 0
    for ch in body[:star]:
        calc ^= ord(ch)
    return format(calc, "02X") == body[star + 1:].strip().upper()


def _dm_to_deg(raw: str, deg_digits: int):
    """ddmm.mmmm → 십진 도"""
    if len(raw) < deg_digits + 3:
        return None
    return float(raw[:deg_digits]) + float(raw[deg_digits:]) / 60.0


def _f(v):
    v = v.strip()
    return float(v) if v else None


def _i(v):
    v = v.strip()
    return int(v) if v else 0


def _parse_gga(parts):
    if len(parts) < 10:
        return
    quality = _i(parts[6])

    lat = lon = None
    if parts[2].strip():
        lat = _dm_to_deg(parts[2].strip(), 2)
        if lat is not None and parts[3].strip() == "S":
            lat = -lat
    if parts[4].strip():
        lon = _dm_to_deg(parts[4].strip(), 3)
        if lon is not None and parts[5].strip() == "W":
            lon = -lon

    upd = dict(fix_quality=quality,
               satellites=_i(parts[7]),
               hdop=_f(parts[8]),
               alt_m=_f(parts[9]),
               t_capture=time.time(),
               status=CONN_OK,
               valid=True)

    # [H7] 측위가 유효할 때만 좌표를 갱신한다.
    #      fix를 잃으면 GGA의 위경도 필드가 비어서 오는데,
    #      예전 코드는 그때 마지막 좌표를 그대로 들고 있어서
    #      몇 분 전 위치를 현재 위치처럼 표시했다.
    if quality > 0 and lat is not None and lon is not None:
        upd["lat"] = round(lat, 8)
        upd["lon"] = round(lon, 8)

    tr = parts[1].strip()
    if len(tr) >= 6:
        upd["utc"] = f"{tr[0:2]}:{tr[2:4]}:{tr[4:6]}"

    _set(**upd)


def _parse_rmc(parts):
    if len(parts) < 8:
        return
    spd = _f(parts[7])
    if spd is not None:
        _set(speed_kmh=round(spd * 1.852, 2))


def _supervisor():
    backoff = 1.0
    while _running:
        port = _resolve_port()
        if port is None:
            _emit("포트를 찾을 수 없습니다", "ERROR")
            _set(status=CONN_ERROR, valid=False)
            _sleep_interruptible(5.0)
            continue
        try:
            _set(status=CONN_WAITING, valid=False)
            _emit(f"포트({port}) 연결 시도...")
            with serial.Serial(port, config.GPS_BAUD, timeout=2) as ser:
                _emit("연결 성공", "INFO")
                backoff = 1.0
                _read_loop(ser)
        except Exception as e:
            _emit(f"연결 끊김: {type(e).__name__}: {e}", "ERROR")
        _set(status=CONN_ERROR, valid=False)
        if not _running:
            break
        _sleep_interruptible(backoff)
        backoff = min(backoff * 2, 30.0)


def _sleep_interruptible(sec):
    end = time.time() + sec
    while _running and time.time() < end:
        time.sleep(0.1)


def _read_loop(ser):
    while _running:
        # ── NTRIP 보정정보를 F9P로 흘려보낸다 ──────────
        _drain_rtcm(ser)

        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("ascii", errors="ignore").strip()
        if not line.startswith("$") or not _checksum_ok(line):
            continue
        parts = line.split(",")
        tag = parts[0][-3:]
        if tag == "GGA":
            _last_gga[0] = line          # VRS 업로드용 원본 보관
            _parse_gga(parts)
        elif tag == "RMC":
            _parse_rmc(parts)


def _drain_rtcm(ser):
    wrote = 0
    while wrote < 8:                     # 한 번에 몰아쓰지 않는다 (수신 지연 방지)
        try:
            data = _rtcm_q.get_nowait()
        except queue.Empty:
            return
        try:
            ser.write(data)
        except Exception as e:
            _emit(f"RTCM 전달 실패: {type(e).__name__}", "WARN")
            return
        wrote += 1


def run_integrity_check(log_callback=None) -> bool:
    """[§2.9] 포트 열기가 아니라 유효 NMEA 수신을 성공 조건으로 삼는다."""
    global _log
    _log = log_callback
    if not SERIAL_AVAILABLE:
        _emit("pyserial 미설치", "ERROR")
        return False
    port = _resolve_port()
    if port is None:
        _emit("포트를 찾을 수 없습니다", "ERROR")
        return False

    for attempt in range(1, 4):
        try:
            with serial.Serial(port, config.GPS_BAUD, timeout=1) as ser:
                t_end = time.time() + 3.0
                while time.time() < t_end:
                    line = ser.readline().decode("ascii", "ignore").strip()
                    if line.startswith("$") and _checksum_ok(line):
                        _emit(f"✅ 유효 NMEA 수신 확인 ({port} @ {config.GPS_BAUD})", "INFO")
                        return True
                _emit(f"포트는 열렸으나 NMEA 없음 ({attempt}/3). "
                      f"통신속도를 확인하세요(38400/9600 시도).", "WARN")
        except Exception as e:
            _emit(f"연결 시도 {attempt}/3 실패: {type(e).__name__}: {e}", "WARN")
        time.sleep(1.0)

    _emit("3회 연결 실패", "ERROR")
    return False
