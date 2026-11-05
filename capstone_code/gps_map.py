"""실제 GPS 시험용 지도와 좌표 메시지를 만든다."""
import io
import math
import subprocess
import sys
import time
from datetime import datetime, timezone

from PIL import Image, ImageDraw

import config
from map_tiles import TileClient
from states import fix_quality_name


def validate_fix(fix, max_age=60):
    if (not fix.valid or fix.fix_quality not in (1, 2, 4, 5)
            or fix.lat is None or fix.lon is None
            or not math.isfinite(fix.lat) or not math.isfinite(fix.lon)
            or not -90 <= fix.lat <= 90 or not -180 <= fix.lon <= 180
            or not math.isfinite(fix.t_capture)
            or not 0 <= time.time() - fix.t_capture <= max_age):
        raise ValueError("새로운 GPS 위치를 확인하지 못했습니다. 전송하지 않습니다.")
    return fix


def read_pi_fix(timeout=15):
    if sys.platform.startswith("linux"):
        check = subprocess.run(["pgrep", "-f", "[s]afety_monitor.py"], capture_output=True)
        if check.returncode != 1:
            raise ValueError("GPS 포트 공유 방지를 위해 기존 안전감시 시험을 Ctrl+C로 종료하세요")
    from sensors import gps_sensor
    if not gps_sensor.start():
        raise ValueError("GPS 드라이버를 시작하지 못했습니다")
    try:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            fix = gps_sensor.snapshot()
            try:
                return validate_fix(fix, config.STALE_GPS_SEC)
            except ValueError:
                time.sleep(0.1)
        raise ValueError("GPS 위치 수신 시간 초과. 안테나와 위성 수신 상태를 확인하세요")
    finally:
        gps_sensor.stop()


def render_map(lat, lon, cache_path=None, timeout=25, client=None):
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("지도 좌표 형식 오류")
    zoom, width, height = 16, 480, 320
    latitude = max(-85.05112878, min(85.05112878, lat))
    world = 256 * 2 ** zoom
    cx = (lon + 180) / 360 * world
    cy = (1 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2 * world
    left, top = math.floor(cx - width / 2), math.floor(cy - height / 2)
    canvas = Image.new("RGB", (width, height), "#dce8e4")
    client = client or TileClient(cache_path or config.MAP_CACHE_PATH, config.MAP_TILE_URL)
    deadline = time.monotonic() + timeout
    for y in range(top // 256, (top + height - 1) // 256 + 1):
        if not 0 <= y < 2 ** zoom:
            continue
        for x in range(left // 256, (left + width - 1) // 256 + 1):
            if time.monotonic() >= deadline:
                raise ValueError("지도 수신 시간 초과")
            data = client.get_tile(zoom, x, y)
            if data is None:
                raise ValueError("지도 이미지를 받지 못했습니다. 연결 제한 또는 인터넷 상태를 확인하세요")
            with Image.open(io.BytesIO(data)) as tile:
                canvas.paste(tile.convert("RGB"), (x * 256 - left, y * 256 - top))
    draw = ImageDraw.Draw(canvas)
    px, py = round(cx - left), round(cy - top)
    draw.ellipse((px - 12, py - 12, px + 12, py + 12), fill="#dc3545", outline="white", width=3)
    draw.rectangle((0, height - 20, width, height), fill="white")
    draw.text((7, height - 16), config.MAP_ATTRIBUTION, fill="#333333")
    out = io.BytesIO()
    canvas.save(out, "PNG")
    return out.getvalue()


def test_payload(fix, with_image=False):
    validate_fix(fix)
    age = time.time() - fix.t_capture
    stamp = datetime.fromtimestamp(fix.t_capture, timezone.utc).isoformat(timespec="seconds")
    payload = {"content": "🧪 [GPS 지도 시험] 실제 사고가 아닙니다.",
               "allowed_mentions": {"parse": []}, "embeds": [{
                   "title": "라즈베리 GPS 측정 위치", "color": 3447003,
                   "description": "GPS 측정값입니다. 실제 위치 오차는 별도 검증이 필요합니다.",
                   "fields": [
                       {"name": "위도 / 경도", "value": f"{fix.lat:.7f}, {fix.lon:.7f}"},
                       {"name": "측위 상태", "value": f"{fix_quality_name(fix.fix_quality)} · 위성 {fix.satellites}개 · HDOP {fix.hdop}"},
                       {"name": "장치 수신 시각 (UTC)", "value": stamp},
                       {"name": "GPS 시각 (UTC)", "value": fix.utc or "알 수 없음"},
                       {"name": "측정 후 경과", "value": f"{age:.1f}초"},
                       {"name": "지도", "value": f"https://www.openstreetmap.org/?mlat={fix.lat}&mlon={fix.lon}#map=16/{fix.lat}/{fix.lon}"},
                   ]}]}
    if with_image:
        payload["embeds"][0]["image"] = {"url": "attachment://map.png"}
        payload["embeds"][0]["footer"] = {"text": config.MAP_ATTRIBUTION + " · 빨간 점: GPS 측정 위치"}
        payload["attachments"] = [{"id": 0, "filename": "map.png"}]
    return payload
