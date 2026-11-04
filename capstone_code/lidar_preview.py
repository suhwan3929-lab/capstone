"""GUI-only UDP receiver. No safety status, commands, or sensor decisions pass here."""
from collections import deque
from dataclasses import dataclass
import ipaddress
import socket
import threading
import time
import zlib

from jetson.walker_preview.protocol import (PORT, MAX_PACKET, STALE_SEC, ASSEMBLY_SEC,
    CHUNK_VERSION, PreviewFrame, decode_chunk, decode_frame)


@dataclass(frozen=True)
class PreviewSnapshot:
    points: tuple = ()
    status: str = "missing"
    simulated: bool = False
    capture_ns: int = 0


class PreviewReceiver:
    def __init__(self, port=PORT, clock=time.monotonic, bind_host="127.0.0.1"):
        self.port, self.clock = port, clock
        self.bind_host = bind_host
        self._lock = threading.Lock()
        self._latest = {}
        self._retired = {side: deque(maxlen=64) for side in ("left", "right")}
        self._pending = {}
        self._dropped = {side: deque(maxlen=64) for side in ("left", "right")}
        self._socket = None
        self._thread = None
        self._stop = threading.Event()
        self.error = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return True
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        except OSError:
            pass  # The OS default remains usable when the buffer hint is denied.
        try:
            address = ipaddress.IPv4Address(self.bind_host)
            if address.is_unspecified or address.is_multicast or int(address) == 0xffffffff:
                raise ValueError("3D preview requires one local IPv4 address, not a wildcard")
            sock.bind((str(address), int(self.port)))
            sock.settimeout(0.1)
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            sock.close()
            self.error = str(exc)
            return False
        self.error = None
        self.port = sock.getsockname()[1]
        self._socket = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(sock,), daemon=True,
                                        name="Preview3D-RX")
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        if self._socket:
            self._socket.close()
        if self._thread:
            self._thread.join(timeout=0.3)

    def ingest(self, data):
        try:
            chunked = len(data) > 4 and data[4] == CHUNK_VERSION
            frame = decode_chunk(data) if chunked else decode_frame(data)
        except (ValueError, TypeError):
            return False
        with self._lock:
            self._expire_locked()
            if not self._acceptable_locked(frame):
                return False
            if not chunked:
                self._drop_locked(frame.side)
                return self._publish_locked(frame)
            side = frame.side
            key = (frame.session, frame.sequence)
            if key in self._dropped[side]:
                return False
            pending = self._pending.get(side)
            if pending and key != pending["key"]:
                old_session, old_sequence = pending["key"]
                if frame.session == old_session:
                    if not self._newer(frame.sequence, old_sequence):
                        return False
                elif (side in self._latest and frame.session == self._latest[side][0].session):
                    # Late packets from the running session cannot displace its restart.
                    return False
                self._drop_locked(side)
                pending = None
            metadata = (frame.capture_ns, frame.count, frame.total_points, frame.crc32, frame.simulated)
            if pending is None:
                pending = {"key": key, "started": self.clock(), "metadata": metadata, "chunks": {}}
                self._pending[side] = pending
            if metadata != pending["metadata"]:
                self._drop_locked(side)
                return False
            chunks = pending["chunks"]
            if frame.index in chunks:
                if chunks[frame.index].payload != frame.payload:
                    self._drop_locked(side)
                return False
            chunks[frame.index] = frame
            if len(chunks) != frame.count:
                return False
            payload = b"".join(chunks[index].payload for index in range(frame.count))
            if zlib.crc32(payload) != frame.crc32:
                self._drop_locked(side)
                return False
            points = tuple(point for index in range(frame.count) for point in chunks[index].points_mm)
            del self._pending[side]
            return self._publish_locked(PreviewFrame(side, frame.session, frame.sequence,
                                        frame.capture_ns, points, frame.simulated))

    @staticmethod
    def _newer(sequence, previous):
        return 0 < ((sequence - previous) & 0xffffffff) < 0x80000000

    def _acceptable_locked(self, frame):
        if frame.session in self._retired[frame.side]:
            return False
        previous = self._latest.get(frame.side)
        return (not previous or frame.session != previous[0].session
                or self._newer(frame.sequence, previous[0].sequence))

    def _drop_locked(self, side):
        pending = self._pending.pop(side, None)
        if pending:
            self._dropped[side].append(pending["key"])

    def _expire_locked(self):
        for side, pending in tuple(self._pending.items()):
            if self.clock() - pending["started"] >= ASSEMBLY_SEC:
                self._drop_locked(side)

    def _publish_locked(self, frame):
        previous = self._latest.get(frame.side)
        if previous and previous[0].session != frame.session:
            self._retired[frame.side].append(previous[0].session)
        points = tuple(tuple(value / 1000.0 for value in point) for point in frame.points_mm)
        self._latest[frame.side] = (frame, self.clock(), points)
        return True

    def snapshot(self, side):
        if self.error:
            return PreviewSnapshot(status="unavailable")
        with self._lock:
            self._expire_locked()
            latest = self._latest.get(side)
        if latest is None:
            return PreviewSnapshot()
        frame, arrived, points = latest
        if self.clock() - arrived >= STALE_SEC:
            return PreviewSnapshot(status="stale")
        return PreviewSnapshot(points, "live" if points else "empty", frame.simulated, frame.capture_ns)

    def _loop(self, sock):
        while not self._stop.is_set():
            try:
                data, _ = sock.recvfrom(MAX_PACKET + 1)
                self.ingest(data)
            except socket.timeout:
                continue
            except OSError as exc:
                if not self._stop.is_set():
                    self.error = str(exc)
                return
