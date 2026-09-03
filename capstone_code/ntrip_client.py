"""
NTRIP 클라이언트 — RTK 보정정보(RTCM3) 수신

계획서 §6.2에 "국토지리정보원 VRS NTRIP 연동"이 적혀 있었으나 미구현 상태였다.
**이것 없이는 ZED-F9P가 RTK로 동작하지 않고, 계획서가 내세운 'cm 단위 정밀 위치'는
성립하지 않는다.** 측위 품질은 단독측위(수 m)에 머문다.

동작
    1) 캐스터에 접속 → 마운트포인트 스트림 요청 (NTRIP v1/v2)
    2) 받은 RTCM3 바이트를 그대로 F9P 시리얼 포트로 흘려보낸다
    3) VRS(가상기준점) 방식은 **로버의 현재 위치를 주기적으로 되올려야** 한다
       → gps_sensor가 보관 중인 마지막 GGA 문장을 그대로 업로드한다
    4) 끊기면 지수 백오프로 재접속

⚠ 로버(보행기)에 상시 인터넷 회선이 필요하다. 현재 BOM에 LTE 모뎀이 없다.
  Wi-Fi만으로는 실외 보행 중 보정정보를 받을 수 없다.

⚠ VRS는 사용자의 위치를 캐스터 서버로 전송한다. 개인정보 항목에 명시할 것.

계정 정보는 환경변수로만 받는다:
    NTRIP_HOST / NTRIP_PORT / NTRIP_MOUNTPOINT / NTRIP_USER / NTRIP_PASS
    WALKER_NTRIP=1
"""
import base64
import socket
import threading
import time

import config

_running = False
_log = None
_stats = {
    "connected": False,
    "bytes": 0,
    "last_rtcm": 0.0,
    "last_gga": 0.0,
    "reconnects": 0,
    "error": None,
}
_lock = threading.Lock()


def _emit(msg, level="INFO"):
    if _log:
        _log(f"[NTRIP] {msg}", level)


# ══════════════════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════════════════
def is_configured() -> bool:
    return bool(config.NTRIP_ENABLED and config.NTRIP_HOST
                and config.NTRIP_MOUNTPOINT)


def stats() -> dict:
    with _lock:
        s = dict(_stats)
    s["rtcm_age"] = (time.time() - s["last_rtcm"]) if s["last_rtcm"] else None
    #: 보정정보가 30초 이상 끊기면 RTK FIX는 사실상 풀린 것으로 봐야 한다
    s["healthy"] = bool(s["connected"] and s["rtcm_age"] is not None
                        and s["rtcm_age"] < 30.0)
    return s


def start(log_callback=None) -> bool:
    global _running, _log
    _log = log_callback
    if not is_configured():
        if config.NTRIP_ENABLED:
            _emit("설정이 불완전합니다 (NTRIP_HOST / NTRIP_MOUNTPOINT 확인)", "ERROR")
        else:
            _emit("비활성 — RTK 보정 없이 동작합니다 "
                  "(측위 품질은 단독측위 수준)", "WARN")
        return False
    _running = True
    threading.Thread(target=_supervisor, daemon=True, name="NTRIP").start()
    return True


def stop():
    global _running
    _running = False


# ══════════════════════════════════════════════════════════
# 내부
# ══════════════════════════════════════════════════════════
def _set(**kw):
    with _lock:
        _stats.update(kw)


def _build_request() -> bytes:
    auth = base64.b64encode(
        f"{config.NTRIP_USER}:{config.NTRIP_PASS}".encode()).decode()
    return (
        f"GET /{config.NTRIP_MOUNTPOINT} HTTP/1.1\r\n"
        f"Host: {config.NTRIP_HOST}:{config.NTRIP_PORT}\r\n"
        f"Ntrip-Version: Ntrip/2.0\r\n"
        f"User-Agent: NTRIP WalkerSafety/1.0\r\n"
        f"Authorization: Basic {auth}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode("ascii")


def _read_header(sock) -> bytes:
    """헤더 끝(\\r\\n\\r\\n)까지 읽고, 헤더 뒤에 붙어 온 본문 조각을 돌려준다."""
    buf = b""
    deadline = time.time() + config.NTRIP_TIMEOUT
    while time.time() < deadline:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("헤더 수신 중 연결 종료")
        buf += chunk
        # NTRIP v1 캐스터는 HTTP 헤더 없이 "ICY 200 OK"만 보내기도 한다
        if b"\r\n\r\n" in buf:
            head, _, rest = buf.partition(b"\r\n\r\n")
            _check_status(head)
            return rest
        if buf.startswith(b"ICY 200 OK"):
            head, _, rest = buf.partition(b"\r\n")
            return rest
        if len(buf) > 65536:
            raise ConnectionError("헤더가 비정상적으로 큼")
    raise TimeoutError("헤더 수신 타임아웃")


def _check_status(head: bytes):
    first = head.split(b"\r\n", 1)[0].decode("ascii", "replace")
    if "200" in first or "ICY" in first:
        return
    if "401" in first:
        raise PermissionError("인증 실패 — NTRIP_USER / NTRIP_PASS 확인")
    if "404" in first:
        raise LookupError("마운트포인트 없음 — NTRIP_MOUNTPOINT 확인 "
                          "(소스테이블은 마운트포인트를 비우고 조회)")
    raise ConnectionError(f"캐스터 응답: {first}")


def _supervisor():
    backoff = 2.0
    while _running:
        sock = None
        try:
            _emit(f"접속 시도 {config.NTRIP_HOST}:{config.NTRIP_PORT}"
                  f"/{config.NTRIP_MOUNTPOINT}")
            sock = socket.create_connection(
                (config.NTRIP_HOST, config.NTRIP_PORT), config.NTRIP_TIMEOUT)
            sock.settimeout(config.NTRIP_TIMEOUT)
            sock.sendall(_build_request())
            leftover = _read_header(sock)

            _set(connected=True, error=None)
            _emit("✅ 보정정보 스트림 연결됨", "INFO")
            backoff = 2.0
            if leftover:
                _forward(leftover)
            _stream(sock)

        except Exception as e:
            _set(connected=False, error=f"{type(e).__name__}: {e}")
            _emit(f"연결 실패/끊김: {type(e).__name__}: {e}", "ERROR")
        finally:
            _set(connected=False)
            try:
                if sock:
                    sock.close()
            except Exception:
                pass

        if not _running:
            break
        with _lock:
            _stats["reconnects"] += 1
        _emit(f"{backoff:.0f}초 후 재접속", "WARN")
        end = time.time() + backoff
        while _running and time.time() < end:
            time.sleep(0.2)
        backoff = min(backoff * 2, config.NTRIP_MAX_BACKOFF)


def _stream(sock):
    last_gga = 0.0
    while _running:
        # ── VRS: 로버 위치를 주기적으로 올린다 ──────────
        now = time.time()
        if now - last_gga >= config.NTRIP_GGA_INTERVAL:
            last_gga = now
            gga = _latest_gga()
            if gga:
                try:
                    sock.sendall(gga.encode("ascii") + b"\r\n")
                    _set(last_gga=now)
                except Exception as e:
                    raise ConnectionError(f"GGA 업로드 실패: {e}")

        try:
            data = sock.recv(8192)
        except socket.timeout:
            # 보정정보가 한동안 없을 수 있다. 연결 자체는 유지한다.
            continue
        if not data:
            raise ConnectionError("스트림 종료")
        _forward(data)


def _forward(data: bytes):
    """받은 RTCM을 F9P로 흘려보낸다."""
    from sensors import gps_sensor
    gps_sensor.write_rtcm(data)
    with _lock:
        _stats["bytes"] += len(data)
        _stats["last_rtcm"] = time.time()


def _latest_gga():
    from sensors import gps_sensor
    return gps_sensor.last_gga()


# ══════════════════════════════════════════════════════════
# 진단 도구 — 마운트포인트 목록 조회
# ══════════════════════════════════════════════════════════
def fetch_sourcetable(host=None, port=None, timeout=10.0):
    """
    캐스터의 소스테이블(사용 가능한 마운트포인트 목록)을 가져온다.
    어떤 마운트포인트를 써야 할지 모를 때 이걸로 확인한다.

        python -c "import ntrip_client as n; n.print_sourcetable()"
    """
    host = host or config.NTRIP_HOST
    port = port or config.NTRIP_PORT
    if not host:
        raise ValueError("NTRIP_HOST가 설정되지 않았습니다")
    req = (f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\n"
           f"Ntrip-Version: Ntrip/2.0\r\n"
           f"User-Agent: NTRIP WalkerSafety/1.0\r\n\r\n").encode()
    with socket.create_connection((host, port), timeout) as s:
        s.settimeout(timeout)
        s.sendall(req)
        buf = b""
        while True:
            try:
                chunk = s.recv(8192)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            if b"ENDSOURCETABLE" in buf:
                break
    return buf.decode("ascii", "replace")


def print_sourcetable():
    text = fetch_sourcetable()
    print(f"{'마운트포인트':<18}{'형식':<10}{'위도':>9}{'경도':>10}  식별자")
    print("-" * 74)
    for line in text.splitlines():
        if not line.startswith("STR;"):
            continue
        f = line.split(";")
        if len(f) > 10:
            print(f"{f[1]:<18}{f[3]:<10}{f[9]:>9}{f[10]:>10}  {f[2]}")
