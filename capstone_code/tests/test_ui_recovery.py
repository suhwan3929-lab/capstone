"""실제 Tk 창 없이 조치 완료 UI → 명령 → 사고 FSM 복귀 경로를 확인한다."""
from unittest.mock import Mock, patch

import config
import ui
from schema import SystemStatus
from states import (CMD_RESET, TIPOVER_ASKING, TIPOVER_CONFIRMED,
                    TIPOVER_NORMAL, TIPOVER_REPORTED)
from buttons import CMD_SOS
from test_tipover_fsm import Rig, SENT


def dashboard(state=TIPOVER_REPORTED, alive=True):
    d = ui.Dashboard.__new__(ui.Dashboard)
    d.root = Mock()
    d.sub = Mock()
    d.sub.latest.return_value = (SystemStatus(tipover_state=state), alive)
    d.cmd = Mock()
    d.term = Mock()
    d.recovery_panel = Mock()
    d.recovery_label = Mock()
    d.recovery_button = Mock()
    d.sos_button = Mock()
    d._reset_requested_at = None
    return d


def test_recovery_control_is_available_only_after_report():
    d = dashboard()
    for state in (TIPOVER_NORMAL, TIPOVER_ASKING):
        d._update_recovery(SystemStatus(tipover_state=state), True)
        d.recovery_panel.pack_forget.assert_called()
        d.recovery_panel.pack.assert_not_called()
    d._update_recovery(SystemStatus(tipover_state=TIPOVER_REPORTED), True)
    d.recovery_panel.pack.assert_called()
    assert d.recovery_button.config.call_args.kwargs["state"] == ui.tk.NORMAL


def test_recovery_is_disabled_until_confirmed_alert_is_queued():
    d = dashboard(TIPOVER_CONFIRMED)
    d._update_recovery(SystemStatus(tipover_state=TIPOVER_CONFIRMED), True)
    assert d.recovery_button.config.call_args.kwargs["state"] == ui.tk.DISABLED
    with patch.object(ui.messagebox, "askyesno") as ask:
        d._request_reset()
    ask.assert_not_called()
    d.cmd.send.assert_not_called()


def test_disconnected_monitor_cannot_be_reset():
    d = dashboard(alive=False)
    d._update_recovery(SystemStatus(tipover_state=TIPOVER_REPORTED), False)
    assert d.recovery_button.config.call_args.kwargs["state"] == ui.tk.DISABLED
    with patch.object(ui.messagebox, "askyesno") as ask:
        d._request_reset()
    ask.assert_not_called()
    d.cmd.send.assert_not_called()


def test_declining_resolution_keeps_confirmed_event():
    d = dashboard()
    with patch.object(ui.messagebox, "askyesno", return_value=False):
        d._request_reset()
    d.cmd.send.assert_not_called()
    assert d._reset_requested_at is None


def test_link_loss_during_confirmation_prevents_reset():
    d = dashboard()
    d.sub.latest.side_effect = [(SystemStatus(tipover_state=TIPOVER_REPORTED), True),
                                (None, False)]
    with patch.object(ui.messagebox, "askyesno", return_value=True):
        d._request_reset()
    d.cmd.send.assert_not_called()


def test_changed_state_during_confirmation_prevents_reset():
    d = dashboard()
    d.sub.latest.side_effect = [(SystemStatus(tipover_state=TIPOVER_REPORTED), True),
                                (SystemStatus(tipover_state=TIPOVER_NORMAL), True)]
    with patch.object(ui.messagebox, "askyesno", return_value=True):
        d._request_reset()
    d.cmd.send.assert_not_called()


def test_resolution_request_waits_for_monitor_ack_and_blocks_double_click():
    d = dashboard()
    with patch.object(ui.messagebox, "askyesno", return_value=True) as ask, \
            patch.object(ui.time, "monotonic", return_value=10.0):
        d._request_reset()
        d._request_reset()
    ask.assert_called_once()
    d.cmd.send.assert_called_once_with(CMD_RESET)
    assert d.recovery_button.config.call_args.kwargs["state"] == ui.tk.DISABLED
    assert d.sub.latest.return_value[0].tipover_state == TIPOVER_REPORTED


def test_unacknowledged_request_can_be_retried():
    d = dashboard()
    d._reset_requested_at = 10.0
    with patch.object(ui.time, "monotonic", return_value=12.1):
        d._update_recovery(SystemStatus(tipover_state=TIPOVER_REPORTED), True)
    assert d._reset_requested_at is None
    assert d.recovery_button.config.call_args.kwargs["state"] == ui.tk.NORMAL
    d.cmd.send.assert_not_called()


def test_monitor_normal_ack_hides_recovery_control():
    d = dashboard()
    d._reset_requested_at = 10.0
    d._update_recovery(SystemStatus(tipover_state=TIPOVER_NORMAL), True)
    assert d._reset_requested_at is None
    d.recovery_panel.pack_forget.assert_called_once()


def test_resolution_ui_resumes_fsm_without_cancelling_existing_report():
    r = Rig()
    r.mon.submit(CMD_SOS)
    r.feed(0.2)
    assert r.state == TIPOVER_REPORTED
    previous_alerts = SENT.copy()
    d = dashboard()
    d.sub.latest.side_effect = lambda: (SystemStatus(tipover_state=r.state), True)
    d.cmd.send.side_effect = r.mon.submit

    with patch.object(ui.messagebox, "askyesno", return_value=True):
        d._request_reset()
    r.feed(0.2)
    assert r.state == TIPOVER_NORMAL
    assert SENT == previous_alerts
    assert not r.mon.alert_sent and r.mon.ask_deadline is None
    d._update_recovery(SystemStatus(tipover_state=r.state), True)
    d.recovery_panel.pack_forget.assert_called()

    r.impact()
    assert r.state == TIPOVER_NORMAL, "감시 재개 직후 쿨다운이 사라짐"
    r.feed(config.REARM_COOLDOWN + 0.1)
    r.impact()
    assert r.state != TIPOVER_NORMAL, "쿨다운 후 새 충격을 감지하지 못함"


def test_reported_ui_does_not_claim_guardian_delivery():
    display = ui.TIPOVER_DISPLAY[TIPOVER_REPORTED]
    assert "보호자 통보됨" not in display
    assert "조치 확인 대기" in display
