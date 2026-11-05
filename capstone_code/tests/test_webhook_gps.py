"""보호된 웹훅 저장과 실제 GPS 지도 시험의 실패/성공 경로를 검증한다."""
import contextlib
import io
import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

import config
import gps_map
from schema import GpsFix
from test_discord_cli import tool, settings
from test_map_tiles import png
from webhook_settings import load_webhook, save_webhook, validate_url

URL = "https://discord.com/api/webhooks/123456789012345678/unit-test-only-secret"


def fix(**changes):
    values = dict(valid=True, lat=37.5, lon=127.0, fix_quality=2, satellites=9,
                  hdop=2.1, t_capture=time.time())
    values.update(changes)
    return GpsFix(**values)


def test_webhook_save_preserves_other_settings_and_protects_backup():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "secrets.env"
        old = b"# device settings\nOTHER_SETTING=keep\nWALKER_NOTIFY_BACKEND=bot\n"
        path.write_bytes(old)
        save_webhook(path, URL)
        assert load_webhook(path) == URL
        assert "OTHER_SETTING=keep" in path.read_text()
        assert path.read_text().count("WALKER_NOTIFY_BACKEND=") == 1
        backup = next(path.parent.glob("secrets.env.before-webhook-*"))
        assert backup.read_bytes() == old
        if os.name != "nt":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_webhook_invalid_url_cannot_modify_saved_settings():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "secrets.env"
        path.write_text("OTHER_SETTING=keep\n")
        for invalid in ("", URL + "\nINJECT=1", "http://discord.com/api/webhooks/1/test",
                        "https://example.org/api/webhooks/1/test", URL + "#fragment"):
            try:
                save_webhook(path, invalid)
            except ValueError:
                pass
            else:
                raise AssertionError("잘못된 웹훅 URL 저장")
            assert path.read_text() == "OTHER_SETTING=keep\n"


def test_webhook_configuration_command_does_not_print_saved_url():
    path = Path(__file__).resolve().parents[1] / "tools/configure_webhook.py"
    spec = importlib.util.spec_from_file_location("configure_webhook_test", path)
    configure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(configure)
    with tempfile.TemporaryDirectory() as directory, \
            patch.object(configure.os, "geteuid", return_value=0, create=True), \
            patch.object(configure, "DEFAULT_PATH", Path(directory)/"secrets.env"), \
            patch.object(configure.getpass, "getpass", return_value=URL), \
            contextlib.redirect_stdout(io.StringIO()) as output:
        assert configure.main() == 0
        assert load_webhook(Path(directory)/"secrets.env") == URL
    assert URL not in output.getvalue()


def test_gps_test_rejects_invalid_stale_or_missing_position():
    for sample in (fix(valid=False), fix(fix_quality=0), fix(lat=None), fix(lon=float("nan")),
                   fix(lat=91), fix(t_capture=time.time()-61), fix(t_capture=time.time()+20)):
        try:
            gps_map.validate_fix(sample)
        except ValueError:
            pass
        else:
            raise AssertionError("유효하지 않은 GPS 위치를 시험 전송에 사용")


def test_pi_gps_reader_stops_after_real_driver_sample():
    from sensors import gps_sensor
    sample = fix()
    with patch.object(gps_map.sys, "platform", "win32"), \
            patch.object(gps_sensor, "start", return_value=True), \
            patch.object(gps_sensor, "snapshot", return_value=sample), \
            patch.object(gps_sensor, "stop") as stop:
        assert gps_map.read_pi_fix() is sample
        stop.assert_called_once()


def test_pi_gps_reader_rejects_another_safety_process_before_opening_serial():
    from sensors import gps_sensor
    with patch.object(gps_map.sys, "platform", "linux"), \
            patch.object(gps_map.subprocess, "run", return_value=SimpleNamespace(returncode=0)), \
            patch.object(gps_sensor, "start") as start:
        try:
            gps_map.read_pi_fix()
        except ValueError:
            pass
        else:
            raise AssertionError("안전감시와 GPS 포트를 동시에 사용")
        start.assert_not_called()


def test_gps_map_image_marks_the_measurement_and_fetches_only_visible_tiles():
    client = Mock()
    client.get_tile.return_value = png()
    data = gps_map.render_map(37.5, 127.0, client=client)
    image = Image.open(io.BytesIO(data))
    assert image.size == (480, 320)
    red, green, blue = image.getpixel((240, 160))
    assert red > 200 and green < 100
    assert 1 <= client.get_tile.call_count <= 9
    calls = [call.args for call in client.get_tile.call_args_list]
    assert len(calls) == len(set(calls))


def test_gps_map_block_cannot_be_sent_as_a_map_image():
    client = Mock()
    client.get_tile.return_value = None
    try:
        gps_map.render_map(37.5, 127.0, client=client)
    except ValueError:
        pass
    else:
        raise AssertionError("지도 차단 이미지를 시험 지도처럼 사용")


def test_gps_payload_is_nonincident_timestamped_and_has_attachment_reference():
    payload = gps_map.test_payload(fix(), with_image=True)
    assert "실제 사고가 아닙니다" in payload["content"]
    assert payload["allowed_mentions"] == {"parse": []}
    embed = payload["embeds"][0]
    assert embed["image"]["url"] == "attachment://map.png"
    assert "OpenStreetMap" in embed["footer"]["text"]
    assert "실제 위치 오차" in embed["description"]
    assert any("openstreetmap.org" in field["value"] for field in embed["fields"])
    assert any("UTC" in field["name"] for field in embed["fields"])


def test_gps_cli_loads_saved_webhook_and_sends_map_without_spool():
    t = tool()
    with settings(), tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "secrets.env"
        save_webhook(path, URL)
        with patch.object(sys, "argv", ["discord_test.py", "--send", "--secrets-file", str(path),
                                        "--gps-location", "--map-image"]), \
                patch.object(t.notifier, "REQUESTS_AVAILABLE", True), \
                patch.object(gps_map, "read_pi_fix", return_value=fix()), \
                patch.object(gps_map, "render_map", return_value=png()), \
                patch.object(t.notifier, "_post_with_retry", return_value=True) as send, \
                patch.object(t.notifier, "start") as start, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            assert t.main() == 0
            assert config.NOTIFY_BACKEND == "webhook" and config.WEBHOOK_URL == URL
            send.assert_called_once()
            assert send.call_args.kwargs["image_bytes"].startswith(b"\x89PNG")
            start.assert_not_called()
        assert URL not in output.getvalue()


def test_gps_cli_missing_fix_or_map_failure_never_sends():
    for missing_fix in (False, True):
        t = tool()
        with settings(), patch.object(config, "WEBHOOK_URL", URL), \
                patch.object(sys, "argv", ["discord_test.py", "--send", "--gps-location", "--map-image"]), \
                patch.object(t.notifier, "REQUESTS_AVAILABLE", True), \
                patch.object(gps_map, "read_pi_fix", side_effect=ValueError() if missing_fix else None,
                             return_value=fix()), \
                patch.object(gps_map, "render_map", side_effect=ValueError()), \
                patch.object(t.notifier, "_post_with_retry") as send, \
                contextlib.redirect_stdout(io.StringIO()):
            assert t.main() == 1
            send.assert_not_called()


def test_confirmed_alarm_map_uses_the_same_renderer_as_the_test():
    import notifier
    with patch.object(gps_map, "render_map", return_value=png()) as render:
        assert notifier._fetch_static_map(37.5, 127.0) == png()
        render.assert_called_once_with(37.5, 127.0, timeout=config.MAP_FETCH_TIMEOUT)
