"""
프로세스 간 상태/명령 채널 (safety_monitor ↔ ui)

    safety_monitor ──상태 10 Hz──> ui        (UDP 9101)
    ui ──사용자 응답(예/아니오)──> safety_monitor  (UDP 9102)

이 채널이 존재하는 이유는 성능이 아니라 **격리**다.
GUI가 멈추거나 죽어도 전도 감지가 영향을 받지 않아야 한다.
(예전에는 한 프로세스여서 tkinter가 멈추면 안전 기능도 같이 멈췄다)

ROS 2 이행 시:
    StatusPublisher  → /walker/status 퍼블리셔
    CommandListener  → /walker/user_response 서브스크라이버
"""
import json
import socket
import threading
import time

import config
from schema import SystemStatus


class StatusPublisher:
    """safety_monitor 측. 상태를 주기적으로 UI로 쏜다."""

    def __init__(self, addr=None):
        self.addr = addr or config.UDP_STATUS_ADDR
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._seq = 0

    def publish(self, status: SystemStatus):
        self._seq += 1
        status.seq = self._seq
        status.t = time.time()
        d = status.to_dict()
        d["v"] = config.SCHEMA_VERSION
        try:
            self._sock.sendto(json.dumps(d).encode("utf-8"), self.addr)
        except OSError:
            pass          # UI가 없어도 safety_monitor는 계속 동작해야 한다

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


class StatusSubscriber:
    """ui 측. 최신 상태를 보관한다."""

    def __init__(self, port=None):
        self.port = port or config.UDP_STATUS_PORT
        self._lock = threading.Lock()
        self._latest = None
        self._arrived = 0.0
        self._seq = 0
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True, name="StatusRX").start()

    def stop(self):
        self._running = False

    def latest(self):
        """(SystemStatus | None, 링크 정상 여부)"""
        with self._lock:
            s, t = self._latest, self._arrived
        alive = bool(t) and (time.monotonic() - t) < 2.0
        return s, alive

    def _loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", self.port))
        sock.settimeout(0.3)
        while self._running:
            try:
                data, _ = sock.recvfrom(8192)
                d = json.loads(data)
                if d.get("v") != config.SCHEMA_VERSION:
                    continue
                seq = d.get("seq", 0)
                with self._lock:
                    if seq <= self._seq and (self._seq - seq) < 1000:
                        continue      # 순서 역전 폐기 (재시작은 수용)
                    self._seq = seq
                    self._latest = SystemStatus.from_dict(d)
                    self._arrived = time.monotonic()
            except socket.timeout:
                continue
            except Exception:
                continue
        sock.close()


class CommandSender:
    """ui 측. 사용자 응답을 safety_monitor로 보낸다."""

    def __init__(self, addr=None):
        self.addr = addr or config.UDP_COMMAND_ADDR
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, cmd: str):
        payload = json.dumps({"v": config.SCHEMA_VERSION, "cmd": cmd}).encode()
        # 사용자 취소는 놓치면 안 되는 명령이므로 3번 보낸다 (UDP 손실 대비)
        for _ in range(3):
            try:
                self._sock.sendto(payload, self.addr)
            except OSError:
                pass
            time.sleep(0.02)


class CommandListener:
    """safety_monitor 측."""

    def __init__(self, on_command, port=None):
        self.port = port or config.UDP_COMMAND_PORT
        self._cb = on_command
        self._running = False
        self._seen = 0.0

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True, name="CmdRX").start()

    def stop(self):
        self._running = False

    def _loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", self.port))
        sock.settimeout(0.3)
        last = None
        while self._running:
            try:
                data, _ = sock.recvfrom(1024)
                d = json.loads(data)
                if d.get("v") != config.SCHEMA_VERSION:
                    continue
                cmd = d.get("cmd")
                now = time.monotonic()
                # 3연발로 오므로 0.5초 내 중복은 무시
                if cmd == last and (now - self._seen) < 0.5:
                    continue
                last, self._seen = cmd, now
                self._cb(cmd)
            except socket.timeout:
                continue
            except Exception:
                continue
        sock.close()
