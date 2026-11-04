"""Display-only CygLiDAR D2 USB decoding, ported from the BSD vendor SDK.

See third_party/cyglidar_d2/NOTICE.md and LICENSE. Never use this test
adapter as an obstacle or tip-over decision source.
"""
from functools import lru_cache
from functools import reduce
import json
import operator
from pathlib import Path

import numpy as np

WIDTH, HEIGHT = 160, 60
PIXELS = WIDTH * HEIGHT
DEPTH, AMPLITUDE = 0x08, 0x88
MAX_PAYLOAD = 24005


def command(code, argument=0):
    payload = bytes((code, argument))
    data = b"\x5a\x77\xff" + len(payload).to_bytes(2, "little") + payload
    return data + bytes((reduce(operator.xor, data[3:], 0),))


START_3D = command(DEPTH)
STOP = command(0x02)
DEVICE_INFO = command(0x10)
DEPTH_ONLY = command(0x15)


def frequency_channel_command(channel):
    if type(channel) is not int or not 0 <= channel <= 15:
        raise ValueError("Frequency channel must be an integer from 0 to 15")
    return command(0x0F, channel)


class StreamParser:
    """Bounded rolling parser. Length bytes participate in the SDK XOR."""
    def __init__(self):
        self.buffer = bytearray()
        self.bad_checksum = 0
        self.bad_length = 0

    def feed(self, chunk):
        self.buffer.extend(chunk)
        if len(self.buffer) > MAX_PAYLOAD * 4:
            del self.buffer[:-MAX_PAYLOAD * 2]
        frames = []
        while True:
            start = self.buffer.find(b"\x5a\x77")
            if start < 0:
                self.buffer[:] = self.buffer[-1:]
                break
            if start:
                del self.buffer[:start]
            if len(self.buffer) < 5:
                break
            size = int.from_bytes(self.buffer[3:5], "little")
            if not 1 <= size <= MAX_PAYLOAD:
                self.bad_length += 1
                del self.buffer[0]
                continue
            end = size + 6
            if len(self.buffer) < end:
                break
            expected = reduce(operator.xor, self.buffer[3:end-1], 0)
            if expected != self.buffer[end-1]:
                self.bad_checksum += 1
                del self.buffer[0]
                continue
            frames.append(bytes(self.buffer[5:end-1]))
            del self.buffer[:end]
        return frames


def decode_depth(payload):
    """One type byte, four timestamp/temperature bytes, then packed pixels."""
    if not payload or payload[0] not in (DEPTH, AMPLITUDE):
        raise ValueError("Not a D2 3D frame")
    stride = 3 if payload[0] == DEPTH else 5
    expected = 5 + (PIXELS // 2) * stride
    if len(payload) != expected:
        raise ValueError("Unexpected D2 3D frame length")
    packed = np.frombuffer(payload, dtype=np.uint8, offset=5).reshape(-1, stride).astype(np.uint16)
    depth = np.empty(PIXELS, dtype=np.uint16)
    depth[0::2] = (packed[:, 0] << 4) | (packed[:, 1] >> 4)
    depth[1::2] = ((packed[:, 1] & 15) << 8) | packed[:, 2]
    return depth


@lru_cache(maxsize=1)
def unit_rays():
    """SDK pixel order, lens interpolation and X-forward/Y-left/Z-up axes."""
    table = json.loads(Path(__file__).with_name("d2_lens.json").read_text(encoding="utf-8"))
    column, row = np.meshgrid(np.arange(WIDTH, dtype=np.float32) - 79.5,
                              np.arange(HEIGHT, dtype=np.float32) - 29.5)
    radius_pixels = np.hypot(column, row)
    radius_mm = np.float32(.02) * radius_pixels
    angle = np.interp(radius_mm, table["real_image_height"], table["lens_angle"])
    angle = angle.astype(np.float32) * np.float32(3.14159265 / 180)
    sine = np.sin(angle) / radius_pixels
    rays = np.stack((np.cos(angle), -column * sine, -row * sine), axis=-1).reshape(-1, 3)
    rays.setflags(write=False)
    return rays


def depth_to_xyz(depth):
    depth = np.asarray(depth)
    if depth.shape != (PIXELS,):
        raise ValueError("Expected 160 x 60 D2 depth pixels")
    valid = (depth > 0) & (depth < 4000)
    return unit_rays()[valid] * (depth[valid, None].astype(np.float32) * np.float32(.001))


def display_depth_xyz(depth, full_resolution=False):
    """Local USB points, using either every pixel or a fixed 80 x 30 grid."""
    depth = np.asarray(depth)
    if depth.shape != (PIXELS,):
        raise ValueError("Expected 160 x 60 D2 depth pixels")
    step = 1 if full_resolution else 2
    sampled = depth.reshape(HEIGHT, WIDTH)[::step, ::step].reshape(-1)
    rays = unit_rays().reshape(HEIGHT, WIDTH, 3)[::step, ::step].reshape(-1, 3)
    valid = (sampled >= 50) & (sampled <= 2000)
    return rays[valid] * (sampled[valid, None].astype(np.float32) * np.float32(.001))
