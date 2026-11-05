"""봇 입력과 단발 시험 전송은 실제 Discord 연결 없이 검증한다."""
import contextlib
import importlib.util
import io
import pathlib
import sys
import warnings
from unittest.mock import Mock, patch

import config


def tool():
    path = pathlib.Path(__file__).resolve().parents[1] / "tools" / "discord_test.py"
    spec = importlib.util.spec_from_file_location("discord_cli_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def settings():
    with patch.multiple(config, NOTIFY_BACKEND="webhook", WEBHOOK_URL="", DISCORD_CHANNEL_ID="", DISCORD_BOT_TOKEN=""):
        yield


def test_discord_prompt_uses_hidden_token_and_does_not_print_it():
    t = tool()
    output = io.StringIO()
    with settings(), patch("builtins.input", return_value="123456789012345678"), \
            patch.object(t.getpass, "getpass", return_value="test-private-token"), \
            contextlib.redirect_stdout(output):
        assert t.prompt_bot_settings()
        assert config.NOTIFY_BACKEND == "bot"
        assert config.DISCORD_CHANNEL_ID == "123456789012345678"
        assert config.DISCORD_BOT_TOKEN == "test-private-token"
    assert "test-private-token" not in output.getvalue()


def test_discord_invalid_channel_or_token_never_reaches_send():
    for channel, token in (("0", "test"), ("abc", "test"), ("１２３", "test"),
                           ("123", ""), ("123", "Bot private-token")):
        t = tool()
        with settings(), patch("builtins.input", return_value=channel), \
                patch.object(t.getpass, "getpass", return_value=token), \
                contextlib.redirect_stdout(io.StringIO()):
            assert not t.prompt_bot_settings()
            assert config.DISCORD_BOT_TOKEN == ""


def test_discord_prompt_fails_closed_if_hidden_input_is_unavailable():
    t = tool()
    def warn(*args):
        warnings.warn("hidden input unavailable", t.getpass.GetPassWarning)
    with settings(), patch("builtins.input", return_value="123"), \
            patch.object(t.getpass, "getpass", side_effect=warn), \
            contextlib.redirect_stdout(io.StringIO()):
        assert not t.prompt_bot_settings()
        assert config.DISCORD_BOT_TOKEN == ""


def test_discord_cli_sends_only_test_payload_without_worker_or_spool():
    t = tool()
    with settings(), patch.object(sys, "argv", ["discord_test.py", "--send", "--prompt"]), \
            patch("builtins.input", return_value="123456789012345678"), \
            patch.object(t.getpass, "getpass", return_value="test-private-token"), \
            patch.object(t.notifier, "REQUESTS_AVAILABLE", True), \
            patch.object(t.notifier, "_post_with_retry", return_value=True) as send, \
            patch.object(t.notifier, "start") as start, \
            patch.object(t.notifier, "_restore_spool") as restore, \
            patch.object(t.notifier, "_spool_add") as spool, \
            contextlib.redirect_stdout(io.StringIO()):
        assert t.main() == 0
        payload = send.call_args.args[0]
        assert "실제 사고가 아닙니다" in payload["content"]
        assert payload["allowed_mentions"] == {"parse": []}
        send.assert_called_once()
        start.assert_not_called()
        restore.assert_not_called()
        spool.assert_not_called()


def test_discord_cancelled_prompt_never_sends():
    t = tool()
    with patch.object(sys, "argv", ["discord_test.py", "--send", "--prompt"]), \
            patch.object(t.notifier, "REQUESTS_AVAILABLE", True), \
            patch("builtins.input", side_effect=KeyboardInterrupt), \
            patch.object(t.notifier, "_post_with_retry") as send, \
            contextlib.redirect_stdout(io.StringIO()):
        assert t.main() == 1
        send.assert_not_called()
