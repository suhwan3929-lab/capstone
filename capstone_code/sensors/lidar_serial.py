"""
LiDAR 드라이버 — 직결 시리얼 (PC 개발용)

실기 구성에서는 이 모듈 대신 sensors/lidar_udp.py 를 쓴다.
(Jetson의 ROS 2 벤더 드라이버가 파싱을 담당 → UDP로 거리만 전달)
두 모듈은 같은 인터페이스(snapshot() -> ObstacleReport)를 제공하므로
config.LIDAR_SOURCE 만 바꾸면 상위 코드는 손댈 필요가 없다.

이전 버전 대비 수정:
  [C2] 런타임 재연결
  [C3] last_rx 기록
  [H3] 프레임 전체 최솟값 → 하위 퍼센타일 + 최소거리 하한 + 연속 프레임 확인
  [§4.0] 1바이트씩 2048회 읽기 → 블록 읽기 + 롤링 버퍼 재동기화
  [성능] 포인트 루프 → numpy 벡터 연산

╔══════════════════════════════════════════════════════════════════════╗
║ ⚠ 미검증 항목 — 데이터시트 확인 전까지 이 모듈의 거리값을 신뢰하지 말 것  ║
║   PAYLOAD_DIST_OFFSET(5)과 '2바이트 리틀엔디안' 가정에 근거가 없다.      ║
║   CygLiDAR 3D 모드는 12비트 패킹(2점=3바이트)일 가능성이 있고,           ║
║   그 경우 아래 파싱은 '그럴듯하지만 완전히 틀린' 값을 만든다.            ║
║                                                                      ║
║   검증 방법 (10분):                                                   ║
║     줄자로 0.5 / 1.0 / 2.0 m 지점에 판을 세우고 출력값과 비교.          ║
║   확정 방법:                                                          ║
║     Cygbot 공식 ROS 2 드라이버 소스에서 오프셋·비트폭을 그대로 가져올 것.║
╚══════════════════════════════════════════════════════════════════════╝
"""
import threading
import time

import numpy as np

import config
from schema import ObstacleReport
from states import CONN_ERROR, CONN_OK, CONN_STALE, CONN_WAITING

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# ── 프로토콜 상수 ─────────────────────────────────────────
#   오프셋/패킹/체크섬은 config에서 온다. 추측하지 말고
#   `python tools/lidar_probe.py` 로 측정해서 config_local.py 에 적을 것.
HEADER = b"\x5A\x77\xFF"
MAX_PAYLOAD = 4096
START_3D_CMD = bytes([0x5A, 0x77, 0xFF, 0x02, 0x00, 0x01, 0x00, 0x03])

_bad_checksum = [0]
_checksum_warned = [False]


def _unpack(buf: bytes) -> "np.ndarray":
    """설정된 패킹 방식으로 원시 거리값(mm)을 뽑는다."""
    mode = config.LIDAR_PACKING
    if mode == "u16le":
        n = len(buf) // 2
        return np.frombuffer(buf[:n * 2], dtype="<u2").astype(np.float32)
    if mode == "u16be":
        n = len(buf) // 2
        return np.frombuffer(buf[:n * 2], dtype=">u2").astype(np.float32)
    if mode in ("u12", "u12alt"):
        # 2점 = 3바이트. ToF 센서에서 흔한 형식.
        n = len(buf) // 3
        if n == 0:
            return np.empty(0, dtype=np.float32)
        b = np.frombuffer(buf[:n * 3], dtype=np.uint8).reshape(n, 3).astype(np.uint16)
        if mode == "u12":
            a = ((b[:, 1] & 0x0F) << 8) | b[:, 0]
            c = (b[:, 2] << 4) | (b[:, 1] >> 4)
        else:
            a = (b[:, 0] << 4) | (b[:, 1] >> 4)
            c = ((b[:, 1] & 0x0F) << 8) | b[:, 2]
        return np.column_stack([a, c]).ravel().astype(np.float32)
    raise ValueError(f"알 수 없는 LIDAR_PACKING: {mode}")


def _checksum_ok(payload: bytes, cs: int) -> bool:
    mode = config.LIDAR_CHECKSUM
    if mode == "none":
        return True
    if mode == "xor":
        x = 0
        for b in payload:
            x ^= b
        return x == cs
    if mode == "sum8":
        return (sum(payload) & 0xFF) == cs
    return True

_lock = threading.Lock()
_state = {
    "left": {"dist": None, "ok": False, "t": 0.0, "status": CONN_WAITING, "hits": 0},
    "right": {"dist": None, "ok": False, "t": 0.0, "status": CONN_WAITING, "hits": 0},
}
_running = False
_log = None


def _emit(msg, level="INFO"):
    if _log:
        _log(f"[LiDAR] {msg}", level)


# ══════════════════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════════════════
def snapshot() -> ObstacleReport:
    now = time.time()
    with _lock:
        side = {k: dict(v) for k, v in _state.items()}

    def val(s):
        # [C3] 오래된 값은 내보내지 않는다
        if not s["ok"] or (now - s["t"]) > config.STALE_LIDAR_SEC:
            return None, False
        return s["dist"], True

    l_d, l_ok = val(side["left"])
    r_d, r_ok = val(side["right"])
    return ObstacleReport(t_capture=now, left_m=l_d, right_m=r_d,
                          left_ok=l_ok, right_ok=r_ok, link_ok=True)


def status(side: str) -> str:
    with _lock:
        s = dict(_state[side])
    if s["ok"] and (time.time() - s["t"]) > config.STALE_LIDAR_SEC:
        return CONN_STALE
    return s["status"]


def start(log_callback=None) -> bool:
    global _running, _log
    _log = log_callback
    if not SERIAL_AVAILABLE:
        return False
    _running = True
    for port, side in ((config.LIDAR_PORT_LEFT, "left"),
                       (config.LIDAR_PORT_RIGHT, "right")):
        threading.Thread(target=_supervisor, args=(port, side),
                         daemon=True, name=f"LiDAR-{side}").start()
    return True


def stop():
    global _running
    _running = False


# ══════════════════════════════════════════════════════════
# 내부
# ══════════════════════════════════════════════════════════
def _set(side, **kw):
    with _lock:
        _state[side].update(kw)


def _supervisor(port, side):
    """[C2] 끊기면 지수 백오프로 재연결."""
    backoff = 1.0
    while _running:
        if port is None:
            _set(side, status=CONN_ERROR, ok=False)
            return
        ser = None
        try:
            _set(side, status=CONN_WAITING, ok=False)
            _emit(f"{side.upper()} 포트({port}) 연결 시도...")
            ser = serial.Serial(port, config.LIDAR_BAUD, timeout=1)
            ser.reset_input_buffer()
            ser.write(START_3D_CMD)
            _emit(f"✅ {side.upper()} 연결 성공", "INFO")
            backoff = 1.0
            _read_loop(ser, side)
        except Exception as e:
            _emit(f"{side.upper()} 끊김: {type(e).__name__}: {e}", "ERROR")
        finally:
            _set(side, status=CONN_ERROR, ok=False, dist=None)
            try:
                if ser:
                    ser.close()
            except Exception:
                pass
        if not _running:
            break
        end = time.time() + backoff
        while _running and time.time() < end:
            time.sleep(0.1)
        backoff = min(backoff * 2, 30.0)


def _read_loop(ser, side):
    """
    블록 단위로 읽어 버퍼에 쌓고, 버퍼에서 헤더를 찾는다.
    예전처럼 1바이트씩 읽으면 3 Mbps를 따라가지 못하고,
    페이로드 안의 0x5A에서 동기가 어긋나면 복구하지 못했다.
    """
    buf = bytearray()
    while _running:
        chunk = ser.read(max(1, min(ser.in_waiting, 8192)))
        if not chunk:
            continue
        buf.extend(chunk)
        if len(buf) > 1 << 20:              # 폭주 방지
            del buf[:-(1 << 16)]

        while True:
            i = buf.find(HEADER)
            if i < 0:
                # 헤더 일부가 걸쳐 있을 수 있으니 꼬리 2바이트는 남긴다
                if len(buf) > 2:
                    del buf[:-2]
                break
            if len(buf) < i + len(HEADER) + 2:
                del buf[:i]
                break
            plen = buf[i + 3] | (buf[i + 4] << 8)
            if plen == 0 or plen > MAX_PAYLOAD:
                del buf[:i + 1]             # 가짜 헤더 → 1바이트만 버리고 재탐색
                continue
            frame_end = i + 5 + plen + 1    # +1 = 체크섬
            if len(buf) < frame_end:
                del buf[:i]
                break
            payload = bytes(buf[i + 5:i + 5 + plen])
            cs = buf[i + 5 + plen]
            del buf[:frame_end]

            # 깨진 프레임이 그대로 거리값이 되면 허위 위험 경보가 된다.
            if not _checksum_ok(payload, cs):
                _bad_checksum[0] += 1
                if _bad_checksum[0] in (20, 200) and not _checksum_warned[0]:
                    _emit(f"체크섬 불일치 {_bad_checksum[0]}회 — "
                          f"LIDAR_CHECKSUM 설정을 확인하세요 "
                          f"(tools/lidar_probe.py analyze)", "WARN")
                    _checksum_warned[0] = True
                continue
            _handle_payload(payload, side)


def _handle_payload(payload: bytes, side: str):
    data = payload[config.LIDAR_PAYLOAD_OFFSET:]
    if len(data) < 4:
        return

    # 성능: 파이썬 루프 대신 numpy. 초당 20~30만 점을 1% 미만 CPU로 처리한다.
    try:
        d_mm = _unpack(data) * config.LIDAR_SCALE_MM
    except ValueError as e:
        _emit(str(e), "ERROR")
        return
    if d_mm.size == 0:
        return
    d_m = d_mm / 1000.0

    # [H3] 유효 범위 밖 제거. 특히 최소거리 미만은 센서 포화/난반사 쓰레기값이다.
    valid = d_m[(d_m >= config.LIDAR_MIN_VALID_M) & (d_m <= config.LIDAR_MAX_VALID_M)]

    if valid.size == 0:
        _set(side, dist=None, ok=True, t=time.time(), status=CONN_OK, hits=0)
        return

    # [H3] 최솟값 1개는 노이즈 픽셀 하나에 그대로 휘둘린다 → 하위 퍼센타일 사용
    dist = float(np.percentile(valid, config.LIDAR_PERCENTILE))

    # [H3] 연속 N프레임 위험일 때만 위험으로 인정 (단발 노이즈 제거)
    with _lock:
        hits = _state[side]["hits"]
        hits = hits + 1 if dist <= config.DIST_DANGER_M else 0
        if dist <= config.DIST_DANGER_M and hits < config.LIDAR_CONFIRM_FRAMES:
            dist = config.DIST_DANGER_M + 0.01      # 확정 전까지는 '경고' 등급으로 보류
        _state[side].update(dist=dist, ok=True, t=time.time(),
                            status=CONN_OK, hits=hits)
