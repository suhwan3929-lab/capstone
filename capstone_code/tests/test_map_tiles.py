"""실제 네트워크 없이 식별정보, HTTP 오류와 지도 캐시를 검증한다."""
import io
import pathlib
import tempfile
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import requests
from PIL import Image

from map_tiles import DEFAULT_TTL, TILE_URL, USER_AGENT, TileClient


def png():
    out = io.BytesIO()
    Image.new("RGB", (256, 256), "#dce8e4").save(out, "PNG")
    return out.getvalue()


def response(status=200, data=None, **headers):
    return SimpleNamespace(status_code=status, content=png() if data is None else data,
                           headers=headers, close=Mock())


@contextmanager
def client(*responses):
    with tempfile.TemporaryDirectory() as folder:
        clock = [1000.0]
        http = SimpleNamespace(get=Mock(side_effect=list(responses)))
        tile = TileClient(pathlib.Path(folder) / "tiles.sqlite3", http=http, clock=lambda: clock[0])
        yield tile, http, clock


def test_map_requests_identify_app_and_use_canonical_https_without_redirects():
    with client(response()) as (tile, http, clock):
        assert tile.get_tile(0, 0, 0) == png()
        call = http.get.call_args
        assert call.args[0] == "https://tile.openstreetmap.org/0/0/0.png"
        assert call.kwargs["headers"]["User-Agent"] == USER_AGENT
        assert "github.com/suhwan3929-lab/capstone" in USER_AGENT
        assert not call.kwargs["allow_redirects"]
        assert call.kwargs["timeout"] == (3, 6)
        assert "Cache-Control" not in call.kwargs["headers"]


def test_map_normal_tiles_are_reused_on_disk_across_client_restarts():
    with client(response()) as (tile, http, clock):
        data = tile.get_tile(0, 0, 0)
        clock[0] += DEFAULT_TTL - 1
        other = TileClient(tile.cache_path, http=http, clock=lambda: clock[0])
        assert other.get_tile(0, 0, 0) == data
        assert http.get.call_count == 1


def test_map_expired_tiles_revalidate_with_etag_and_last_modified():
    with client(response(**{"Cache-Control": "max-age=60", "Age": "10", "ETag": "v1",
                            "Last-Modified": "Wed, 04 Nov 2026 00:00:00 GMT"}),
                response(304, data=b"", **{"Cache-Control": "max-age=90"})) as (tile, http, clock):
        original = tile.get_tile(0, 0, 0)
        clock[0] += 49
        assert tile.get_tile(0, 0, 0) == original and http.get.call_count == 1
        clock[0] += 2
        assert tile.get_tile(0, 0, 0) == original
        headers = http.get.call_args.kwargs["headers"]
        assert headers["If-None-Match"] == "v1"
        assert "If-Modified-Since" in headers
        assert tile.status() == "ready"


def test_map_blocked_png_is_never_displayed_or_cached_and_requests_back_off():
    for status in (403, 429):
        with client(response(status, **{"Retry-After": "120"}), response()) as (tile, http, clock):
            assert tile.get_tile(1, 0, 0) is None
            assert tile.status() == "blocked"
            assert tile.get_tile(1, 1, 0) is None
            assert not tile.cache_path.exists() and http.get.call_count == 1
            clock[0] += 121
            assert tile.retry_due()
            assert tile.get_tile(1, 0, 0) == png()
            assert tile.status() == "ready"


def test_map_network_failure_can_reuse_previously_viewed_expired_tile():
    with client(response(**{"Cache-Control": "max-age=1"}),
                requests.ConnectionError("offline")) as (tile, http, clock):
        data = tile.get_tile(0, 0, 0)
        clock[0] += 2
        assert tile.get_tile(0, 0, 0) == data
        assert tile.status() == "offline"
        assert tile.retry_at == clock[0] + 30


def test_map_redirect_html_or_invalid_image_is_not_cached():
    for reply in (response(302), response(200, b"<html>blocked</html>"), response(500)):
        with client(reply) as (tile, http, clock):
            assert tile.get_tile(0, 0, 0) is None
            assert not tile.cache_path.exists()
            assert tile.status() == "offline"
            reply.close.assert_called_once()


def test_map_no_store_is_not_written_to_memory_or_disk():
    with client(response(**{"Cache-Control": "no-store"}), response()) as (tile, http, clock):
        assert tile.get_tile(0, 0, 0) == png()
        assert not tile._memory and not tile.cache_path.exists()
        tile.get_tile(0, 0, 0)
        assert http.get.call_count == 2


def test_map_invalid_coordinates_do_not_request_and_longitude_wraps():
    with client(response()) as (tile, http, clock):
        assert tile.get_tile(20, 0, 0) is None
        assert tile.get_tile(0, 0, 1) is None
        http.get.assert_not_called()
        tile.get_tile(1, 3, 1)
        assert http.get.call_args.args[0].endswith("/1/1/1.png")


def test_map_provider_change_uses_a_separate_cache_key():
    with client(response(), response()) as (tile, http, clock):
        tile.get_tile(0, 0, 0)
        other = TileClient(tile.cache_path, tile_url="https://example.org/{z}/{x}/{y}.png",
                           http=http, clock=lambda: clock[0])
        other.get_tile(0, 0, 0)
        assert http.get.call_count == 2


def test_map_gui_status_does_not_wait_for_http_lock():
    import threading
    with client() as (tile, http, clock):
        acquired, release = threading.Event(), threading.Event()
        def hold():
            with tile._lock:
                acquired.set()
                release.wait(3)
        worker = threading.Thread(target=hold)
        worker.start()
        assert acquired.wait(1)
        try:
            assert tile.status() == "waiting"
            assert tile.retry_due() is False
        finally:
            release.set()
            worker.join(2)
