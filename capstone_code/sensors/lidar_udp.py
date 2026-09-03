"""
LiDAR 수신기 — Jetson의 ROS 2 브리지 노드에서 UDP로 받는다. (실기 구성)

설계 원칙 3가지:
  1) 비신뢰 UDP가 정답이다. 장애물 거리는 "최신값만 의미 있음" 성격이므로
     재전송이 오히려 해롭다. (계획서 §3.3에서 BEST_EFFORT로 정한 것과 같은 판단)
  2) 데이터가 없어도 매 주기 보낸다. 패킷 자체가 하트비트다.
     → "감지된 물체 없음"과 "링크 끊김"을 수신 측이 구분할 수 있다.
  3) 신선도는 **수신 측 도착 시각**으로 판정한다. 송신 타임스탬프는 진단용.
     → 두 보드의 시계 동기화(chrony)에 의존하지 않는다.

ROS 2 전면 이행 시: 이 모듈이 그대로 서브스크라이버 콜백이 된다.
"""
import json
import socket
import threading
import time

import config
from schema import ObstacleReport

_lock = threading.Lock()
_state = {"left": None, "right": None, "left_ok": False, "right_ok": False,
          "curb_m": None, "curb_type": "",
          "seq": 0, "arrived": 0.0, "latency": None}
_running = False
_log = None


def _emit(msg, level="INFO"):
    if _log:
        _log(f"[LiDAR-UDP] {msg}", level)


def snapshot() -> ObstacleReport:
    with _lock:
        s = dict(_state)
    link_ok = bool(s["arrived"]) and \
        (time.monotonic() - s["arrived"]) < config.STALE_LIDAR_SEC
    if not link_ok:
        # 링크가 끊겼으면 낡은 거리값을 절대 내보내지 않는다.
        return ObstacleReport(t_capture=time.time(), link_ok=False)
    return ObstacleReport(t_capture=time.time(),
                          left_m=s["left"], right_m=s["right"],
                          left_ok=s["left_ok"], right_ok=s["right_ok"],
                          curb_m=s["curb_m"], curb_type=s["curb_type"],
                          link_ok=True, latency_s=s["latency"])


def status(side: str) -> str:
    from states import CONN_ERROR, CONN_OK
    r = snapshot()
    if not r.link_ok:
        return CONN_ERROR
    return CONN_OK if (r.left_ok if side == "left" else r.right_ok) else CONN_ERROR


def start(log_callback=None) -> bool:
    global _running, _log
    _log = log_callback
    _running = True
    threading.Thread(target=_rx_loop, daemon=True, name="LiDAR-RX").start()
    _emit(f"UDP {config.UDP_LIDAR_PORT} 수신 대기")
    return True


def stop():
    global _running
    _running = False


def run_integrity_check(log_callback=None) -> bool:
    """3초 안에 Jetson 패킷이 한 번이라도 오는지 확인."""
    global _log
    _log = log_callback
    start(log_callback)
    t_end = time.time() + 3.0
    while time.time() < t_end:
        if snapshot().link_ok:
            _emit("✅ Jetson 링크 확인", "INFO")
            return True
        time.sleep(0.1)
    _emit("Jetson으로부터 패킷 없음 — 네트워크/노드 상태를 확인하세요", "ERROR")
    return False


def _rx_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", config.UDP_LIDAR_PORT))
    sock.settimeout(0.2)
    was_linked = False

    while _running:
        try:
            data, _addr = sock.recvfrom(4096)
            pkt = json.loads(data)
            if pkt.get("v") != config.SCHEMA_VERSION:
                continue
            with _lock:
                prev = _state["seq"]
                new = int(pkt["seq"])
                # 순서 역전 패킷은 버린다. 단 seq가 크게 뒤로 가면
                # Jetson이 재시작한 것이므로 새 세션으로 받아들인다.
                # (이 예외가 없으면 Jetson 재부팅 후 모든 패킷을 영구히 거부한다)
                if new <= prev and (prev - new) < 1000:
                    continue
                _state.update(
                    seq=new,
                    left=pkt["left"]["d"] if pkt["left"]["ok"] else None,
                    right=pkt["right"]["d"] if pkt["right"]["ok"] else None,
                    left_ok=bool(pkt["left"]["ok"]),
                    right_ok=bool(pkt["right"]["ok"]),
                    # 구버전 브리지와도 호환되도록 .get()으로 읽는다
                    curb_m=pkt.get("curb_m"),
                    curb_type=pkt.get("curb_type", "") or "",
                    arrived=time.monotonic(),
                    latency=time.time() - float(pkt["t"]),
                )
            if not was_linked:
                was_linked = True
                _emit("Jetson 링크 연결됨", "INFO")
        except socket.timeout:
            if was_linked and not snapshot().link_ok:
                was_linked = False
                _emit("⚠ Jetson 링크 끊김 — 장애물 경고 사용 불가 "
                      "(전도 감지는 계속 동작)", "ERROR")
        except Exception:
            continue        # 깨진 패킷 하나로 수신 스레드가 죽지 않는다

    sock.close()
