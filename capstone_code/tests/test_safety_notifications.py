"""실제 네트워크/하드웨어 없이 고장 경보와 Discord 전송 경로를 검증한다."""
import importlib
import importlib.util
import json
import pathlib
import sys
import tempfile
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config
from schema import GpsFix, ImuSample, ObstacleReport


@contextmanager
def transport(backend="bot"):
    # 기존 FSM 테스트가 전역 notifier 함수를 대체하므로 독립 모듈을 사용한다.
    spec = importlib.util.spec_from_file_location("notifier_transport_test", ROOT / "notifier.py")
    n = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(n)
    response = SimpleNamespace(status_code=200, headers={}, json=lambda: {"id": "123"})
    http = SimpleNamespace(post=Mock(return_value=response))
    with tempfile.TemporaryDirectory() as d, patch.multiple(
        config, NOTIFY_BACKEND=backend, DISCORD_BOT_TOKEN="unit-test-token",
        DISCORD_CHANNEL_ID="123456789012345678",
        WEBHOOK_URL="https://discord.com/api/webhooks/123456789012345678/unit-test-only",
        NOTIFY_SPOOL=str(pathlib.Path(d) / "pending.jsonl"), WEBHOOK_MAX_RETRY=3,
    ), patch.object(n, "REQUESTS_AVAILABLE", True), patch.object(n, "requests", http, create=True):
        yield n, http


def test_lidar_sensor_faults_with_live_bridge():
    with patch.object(sys, "argv", ["safety_monitor.py"]):
        safety = importlib.import_module("safety_monitor")
    from alerting import Alerter, SENSOR_FAULT, SILENT
    with patch.multiple(config, SIM_MODE=False, LIDAR_SOURCE="udp"):
        for left, right in ((False, True), (True, False), (False, False), (True, True)):
            obs = ObstacleReport(link_ok=True, left_ok=left, right_ok=right)
            fault = safety._sensors_faulty(ImuSample(valid=True), GpsFix(), obs)
            assert fault == (not (left and right)), (left, right)
            a = Alerter()
            a.update(None, SILENT, fault, moving=False)
            assert a._level == (SENSOR_FAULT if fault else SILENT)
        assert safety._sensors_faulty(ImuSample(valid=True), GpsFix(), ObstacleReport())


def test_disabled_lidar_does_not_mask_imu_fault():
    with patch.object(sys, "argv", ["safety_monitor.py"]):
        safety = importlib.import_module("safety_monitor")
    with patch.multiple(config, SIM_MODE=False, LIDAR_SOURCE="none"):
        assert not safety._sensors_faulty(ImuSample(valid=True), GpsFix(), ObstacleReport())
        assert safety._sensors_faulty(ImuSample(valid=False), GpsFix(), ObstacleReport())
    with patch.multiple(config, SIM_MODE=True, LIDAR_SOURCE="udp"):
        assert not safety._sensors_faulty(ImuSample(valid=True), GpsFix(), ObstacleReport())


def test_bot_configuration_validation():
    with transport() as (n, http):
        assert n.is_configured()
        for channel in ("", "CHANNEL_ID", "0", "123/path", "１２３"):
            with patch.object(config, "DISCORD_CHANNEL_ID", channel):
                assert not n.is_configured()
        for token in ("", "bad token"):
            with patch.object(config, "DISCORD_BOT_TOKEN", token):
                assert not n.is_configured()
        with patch.object(config, "NOTIFY_BACKEND", "typo"):
            assert not n.is_configured()
        with patch.object(n, "REQUESTS_AVAILABLE", False):
            assert not n.is_configured()
        http.post.assert_not_called()


def test_bot_message_and_image_use_same_channel_auth():
    with transport() as (n, http):
        assert n._post_with_retry({"content": "test"})
        n._post_image(b"test-image", {})
        assert http.post.call_count == 2
        for call in http.post.call_args_list:
            assert call.args[0] == "https://discord.com/api/v10/channels/123456789012345678/messages"
            assert call.kwargs["headers"]["Authorization"] == "Bot unit-test-token"
            assert call.kwargs["allow_redirects"] is False
        assert "files[0]" in http.post.call_args.kwargs["files"]


def test_webhook_keeps_compatible_payload_and_waits_for_discord():
    with transport("webhook") as (n, http):
        assert n.is_configured()
        assert n._post_with_retry({"content": "test"})
        call = http.post.call_args
        assert call.args[0] == config.WEBHOOK_URL
        assert call.kwargs["params"] == {"wait": "true"}
        assert "headers" not in call.kwargs


def test_discord_rate_limit_retries_after_server_delay():
    with transport() as (n, http), patch.object(n.time, "sleep") as sleep:
        http.post.side_effect = [
            SimpleNamespace(status_code=429, headers={}, json=lambda: {"retry_after": 0.25}),
            SimpleNamespace(status_code=200),
        ]
        assert n._post_with_retry({"content": "test"})
        sleep.assert_called_once_with(0.25)
        assert http.post.call_count == 2


def test_discord_auth_failure_keeps_confirmed_spool():
    with transport() as (n, http):
        http.post.return_value.status_code = 401
        n.send_confirmed(ImuSample(valid=False), GpsFix(), None, 0.0)
        item = n._q.get_nowait()
        n._deliver(item)
        assert item["id"] in pathlib.Path(config.NOTIFY_SPOOL).read_text(encoding="utf-8")
        assert http.post.call_count == 1


def test_sos_without_imu_reaches_discord_transport_once():
    import tipover_monitor
    from buttons import CMD_SOS
    from states import TIPOVER_REPORTED
    with transport() as (n, http), patch.object(tipover_monitor, "notifier", n):
        m = tipover_monitor.TipoverMonitor()
        m.submit(CMD_SOS)
        # 고장 전 값이 남아 있어도 현재 측정값으로 보내지 않는다.
        imu = ImuSample(valid=False, roll_deg=80.0, accel_g=9.0)
        for _ in range(10):
            m.step(imu, GpsFix())
        assert m.state == TIPOVER_REPORTED
        assert n._q.qsize() == 1
        item = n._q.get_nowait()
        assert item["peak_g"] is None and item["tilt_deg"] is None
        assert item["imu_valid"] is False
        n._deliver(item)
        assert http.post.call_count == 1
        payload = http.post.call_args.kwargs["json"]
        assert any(f["name"] == "IMU 상태" for f in payload["embeds"][0]["fields"])
        assert payload["allowed_mentions"] == {"parse": []}
        assert pathlib.Path(config.NOTIFY_SPOOL).read_text(encoding="utf-8").strip() == ""


def test_transport_error_log_does_not_expose_credentials():
    with transport() as (n, http), patch.object(n.time, "sleep"):
        http.post.side_effect = RuntimeError("unit-test-token secret webhook URL")
        logs = []
        n._log = lambda msg, level="INFO": logs.append(msg)
        assert not n._post_with_retry({"content": "test"})
        assert "unit-test-token" not in " ".join(logs)
        assert "secret webhook" not in " ".join(logs)


def test_confirmed_delivery_status_tracks_queue_http_and_server_acceptance():
    with transport() as (n, http):
        n.send_confirmed(ImuSample(), GpsFix(), None, 0.0)
        item = n._q.get_nowait()
        assert n.delivery_status() == {"id": item["id"], "state": "queued"}
        response = http.post.return_value

        def post(*args, **kwargs):
            assert n.delivery_status()["state"] == "sending"
            return response

        http.post.side_effect = post
        n._deliver(item)
        assert n.delivery_status() == {"id": item["id"], "state": "accepted"}
        http.post.side_effect = None
        n.send_cancelled("test")
        n._deliver(n._q.get_nowait())
        assert n.delivery_status()["id"] == item["id"]


def test_failed_or_unconfigured_delivery_does_not_become_success_when_queue_empties():
    for configured in (False, True):
        with transport() as (n, http):
            http.post.return_value.status_code = 401
            n.send_confirmed(ImuSample(), GpsFix(), None, 0.0)
            item = n._q.get_nowait()
            with patch.object(n, "is_configured", return_value=configured):
                n._deliver(item)
            assert n.pending() == 0
            assert n.delivery_status()["state"] == ("failed" if configured else "unconfigured")
            assert item["id"] in pathlib.Path(config.NOTIFY_SPOOL).read_text(encoding="utf-8")


def test_older_incident_result_cannot_overwrite_new_incident_delivery_status():
    with transport() as (n, http):
        n.send_confirmed(ImuSample(), GpsFix(), None, 0.0)
        old = n._q.get_nowait()
        n.send_confirmed(ImuSample(), GpsFix(), None, 0.0)
        latest = n._q.get_nowait()
        assert old["id"] != latest["id"]
        n._deliver(old)
        assert n.delivery_status() == {"id": latest["id"], "state": "queued"}


def test_restored_spool_is_queued_and_map_failure_cannot_undo_text_acceptance():
    with transport() as (n, http):
        n.send_confirmed(ImuSample(), GpsFix(), None, 0.0)
        item = n._q.get_nowait()
        n._delivery.update(id="", state="")
        n._restore_spool()
        assert n.delivery_status() == {"id": item["id"], "state": "queued"}
        item = n._q.get_nowait()
        item["lat"], item["lon"] = 37.0, 127.0
        with patch.object(n, "_fetch_static_map", side_effect=RuntimeError("mock map failure")):
            try:
                n._deliver(item)
            except RuntimeError:
                n._track_delivery(item, "failed")  # worker exception path
        assert n.delivery_status()["state"] == "accepted"


def test_redirect_is_not_delivery_success():
    with transport() as (n, http), patch.object(n.time, "sleep"):
        http.post.return_value.status_code = 302
        assert not n._post_with_retry({"content": "test"})


def test_map_attachment_keeps_bot_and_webhook_auth_and_retries():
    for backend in ("bot", "webhook"):
        with transport(backend) as (n, http), patch.object(n.time, "sleep"):
            http.post.side_effect = [SimpleNamespace(status_code=500), SimpleNamespace(status_code=200)]
            payload = {"content": "test", "embeds": [{"image": {"url": "attachment://map.png"}}]}
            assert n._post_with_retry(payload, image_bytes=b"test-image")
            assert http.post.call_count == 2
            for call in http.post.call_args_list:
                assert "json" not in call.kwargs
                assert call.kwargs["files"]["files[0]"] == ("map.png", b"test-image", "image/png")
                assert json.loads(call.kwargs["files"]["payload_json"][1]) == payload
                assert call.kwargs["allow_redirects"] is False
                if backend == "bot":
                    assert call.kwargs["headers"]["Authorization"] == "Bot unit-test-token"
                else:
                    assert call.kwargs["params"] == {"wait": "true"}
