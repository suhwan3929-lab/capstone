"""Bounded display packets. XYZ millimetres are units, not accuracy claims."""
from dataclasses import dataclass
import math
import struct
import zlib

MAGIC = b"W3DP"
VERSION = 1
CHUNK_VERSION = 2
PORT = 9103
MAX_POINTS = 192
MAX_PACKET = 1200
MAX_FRAME_POINTS = 9600
ASSEMBLY_SEC = 0.25
STALE_SEC = 0.5
EMPTY = 1
SIMULATED = 2
SIDES = ("left", "right")
# magic, version, side, flags, reserved, session, sequence, capture_ns, count
HEADER = struct.Struct("<4sBBBBQIQH")
POINT = struct.Struct("<hhh")
# Legacy fields, chunk index/count, total points, and complete-payload CRC32.
CHUNK_HEADER = struct.Struct("<4sBBBBQIQHHHHI")


@dataclass(frozen=True)
class PreviewFrame:
    side: str
    session: int
    sequence: int
    capture_ns: int
    points_mm: tuple
    simulated: bool = False


@dataclass(frozen=True)
class PreviewChunk:
    side: str
    session: int
    sequence: int
    capture_ns: int
    index: int
    count: int
    total_points: int
    crc32: int
    points_mm: tuple
    payload: bytes
    simulated: bool = False


def encode_frame(side, session, sequence, capture_ns, points_mm, simulated=False):
    if side not in SIDES or len(points_mm) > MAX_POINTS:
        raise ValueError("Invalid sensor or point count")
    flags = (EMPTY if not points_mm else 0) | (SIMULATED if simulated else 0)
    payload = bytearray(HEADER.pack(MAGIC, VERSION, SIDES.index(side), flags, 0,
                                    session, sequence, capture_ns, len(points_mm)))
    for point in points_mm:
        if len(point) != 3 or any(type(v) is not int for v in point):
            raise ValueError("Coordinates must be integer XYZ millimetres")
        if point[0] < 0 or not 49 <= math.sqrt(sum(v * v for v in point)) <= 2001:
            raise ValueError("Point outside the 3D sensor range")
        payload.extend(POINT.pack(*point))
    if len(payload) > MAX_PACKET:
        raise ValueError("Oversized preview packet")
    return bytes(payload)


def decode_frame(data):
    if not HEADER.size <= len(data) <= MAX_PACKET:
        raise ValueError("Invalid preview packet length")
    magic, version, side, flags, reserved, session, seq, capture, count = HEADER.unpack_from(data)
    if (magic != MAGIC or version != VERSION or side >= len(SIDES) or reserved
            or flags & ~(EMPTY | SIMULATED) or count > MAX_POINTS
            or bool(flags & EMPTY) != (count == 0)
            or len(data) != HEADER.size + count * POINT.size):
        raise ValueError("Invalid preview header")
    points = tuple(POINT.iter_unpack(data[HEADER.size:]))
    # Allow only the 1 mm rounding margin of the encoder.
    if any(p[0] < 0 or not 49 <= math.sqrt(sum(v * v for v in p)) <= 2001 for p in points):
        raise ValueError("Invalid preview coordinate")
    return PreviewFrame(SIDES[side], session, seq, capture, points, bool(flags & SIMULATED))


def encode_frame_chunks(side, session, sequence, capture_ns, points_mm, simulated=False):
    if side not in SIDES or len(points_mm) > MAX_FRAME_POINTS:
        raise ValueError("Invalid sensor or full-frame point count")
    payload = bytearray()
    for point in points_mm:
        if len(point) != 3 or any(type(value) is not int for value in point):
            raise ValueError("Coordinates must be integer XYZ millimetres")
        if point[0] < 0 or not 49 <= math.sqrt(sum(value * value for value in point)) <= 2001:
            raise ValueError("Point outside the 3D sensor range")
        payload.extend(POINT.pack(*point))
    total = len(points_mm)
    count = max(1, (total + MAX_POINTS - 1) // MAX_POINTS)
    crc = zlib.crc32(payload)
    flags = (EMPTY if not total else 0) | (SIMULATED if simulated else 0)
    packets = []
    for index in range(count):
        chunk_points = min(MAX_POINTS, total - index * MAX_POINTS)
        header = CHUNK_HEADER.pack(MAGIC, CHUNK_VERSION, SIDES.index(side), flags, 0,
                                   session, sequence, capture_ns, chunk_points,
                                   index, count, total, crc)
        start = index * MAX_POINTS * POINT.size
        packets.append(header + payload[start:start + chunk_points * POINT.size])
    return tuple(packets)


def decode_chunk(data):
    if not CHUNK_HEADER.size <= len(data) <= MAX_PACKET:
        raise ValueError("Invalid full-preview packet length")
    magic, version, side, flags, reserved, session, seq, capture, size, index, count, total, crc = CHUNK_HEADER.unpack_from(data)
    expected_count = max(1, (total + MAX_POINTS - 1) // MAX_POINTS)
    if (magic != MAGIC or version != CHUNK_VERSION or side >= len(SIDES) or reserved
            or flags & ~(EMPTY | SIMULATED) or total > MAX_FRAME_POINTS
            or bool(flags & EMPTY) != (total == 0)
            or count != expected_count or index >= count
            or size != min(MAX_POINTS, total - index * MAX_POINTS)
            or len(data) != CHUNK_HEADER.size + size * POINT.size):
        raise ValueError("Invalid full-preview header")
    payload = bytes(data[CHUNK_HEADER.size:])
    points = tuple(POINT.iter_unpack(payload))
    if any(point[0] < 0 or not 49 <= math.sqrt(sum(value * value for value in point)) <= 2001 for point in points):
        raise ValueError("Invalid full-preview coordinate")
    return PreviewChunk(SIDES[side], session, seq, capture, index, count, total,
                        crc, points, payload, bool(flags & SIMULATED))
