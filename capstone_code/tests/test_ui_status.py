"""센서/Discord 없이 표시의 신선도와 SOS 처리 상태를 확인한다."""
from unittest.mock import Mock, patch

import config
import ui
from buttons import CMD_SOS
from schema import GpsFix, ImuSample, ObstacleReport, SystemStatus
from states import CONN_OK, TIPOVER_CONFIRMED, TIPOVER_NORMAL, TIPOVER_REPORTED
from lidar_preview import PreviewSnapshot


def status():
    return SystemStatus(
        tipover_state=TIPOVER_NORMAL,
        imu=ImuSample(valid=True, status=CONN_OK),
        obstacle=ObstacleReport(link_ok=True, left_ok=True, right_ok=True,
                                left_m=3.0, right_m=3.0))


def dashboard(st=None, alive=True):
    d = ui.Dashboard.__new__(ui.Dashboard)
    for name in ("root", "sub", "cmd", "term", "recovery_panel", "recovery_label",
                 "recovery_button", "sos_button", "sos_status", "lidar_l", "lidar_r",
                 "imu_card", "gps_card", "curb_lbl", "overall", "clock", "batt", "health_lbl", "flash",
                 "summary_imu", "summary_gps"):
        setattr(d, name, Mock())
    d.sub.latest.return_value = (st or status(), alive)
    d.preview_sub = None
    d._popup = None
    d._flashing = False
    d._link_warned = False
    d._last_notice = None
    d._reset_requested_at = None
    d._sos_requested_at = None
    d._sos_unconfirmed = False
    return d


def test_header_never_claims_normal_with_missing_lidar():
    for left, right, link in ((False, True, True), (True, False, True), (False, False, False)):
        st = status()
        st.obstacle = ObstacleReport(left_ok=left, right_ok=right, link_ok=link)
        d = dashboard(st)
        with patch.multiple(config, SIM_MODE=False, LIDAR_SOURCE="udp"):
            d._refresh()
        text = d.overall.config.call_args.kwargs["text"]
        assert "LiDAR" in text and "감시 일부 불가" in text
        assert "OK" not in text and "정상" not in text


def test_header_preserves_danger_and_reports_other_failed_sensor():
    st = status()
    st.obstacle.left_m = 0.1
    st.obstacle.right_ok = False
    d = dashboard(st)
    with patch.multiple(config, SIM_MODE=False, LIDAR_SOURCE="udp"):
        d._refresh()
    assert "위험" in d.overall.config.call_args.kwargs["text"]
    assert "LiDAR" in d.overall.config.call_args.kwargs["text"]


def test_threeD_loss_is_explicit_while_distance_monitoring_stays_healthy():
    d = dashboard()
    d.preview_sub = Mock()
    d.preview_sub.snapshot.side_effect = lambda side: PreviewSnapshot(status="live" if side == "left" else "stale")
    with patch.multiple(config, SIM_MODE=False, LIDAR_SOURCE="udp"):
        d._refresh()
    text = d.overall.config.call_args.kwargs["text"]
    assert "감시 정상" in text and "3D 오른쪽 중단" in text
    assert d.overall.config.call_args.kwargs["fg"] == ui.C_YELLOW
    d.lidar_r.update_card.assert_called_once_with(3.0, True, True, None, False)


def test_threeD_health_does_not_mask_distance_danger_or_sensor_failure():
    st = status()
    st.obstacle.left_m = .1
    d = dashboard(st)
    d.preview_sub = Mock()
    d.preview_sub.snapshot.return_value = PreviewSnapshot(status="unavailable")
    with patch.multiple(config, SIM_MODE=False, LIDAR_SOURCE="udp"):
        d._refresh()
    assert "위험" in d.overall.config.call_args.kwargs["text"]
    assert "3D" in d.overall.config.call_args.kwargs["text"]
    assert d.overall.config.call_args.kwargs["fg"] == ui.C_RED
    st.obstacle.left_m, st.obstacle.left_ok = None, False
    d.preview_sub.snapshot.return_value = PreviewSnapshot(status="live")
    with patch.multiple(config, SIM_MODE=False, LIDAR_SOURCE="udp"):
        d._refresh()
    assert "감시 일부 불가" in d.overall.config.call_args.kwargs["text"]


def test_threeD_badge_and_distance_badge_are_updated_independently():
    card = ui.LidarCard.__new__(ui.LidarCard)
    for name in ("preview_3d", "preview_status", "preview", "badge", "dist", "config"):
        setattr(card, name, Mock())
    card.update_card(3, True, True)
    assert "거리" in card.badge.config.call_args.kwargs["text"]
    distance_calls = list(card.badge.config.call_args_list)
    card.update_3d(PreviewSnapshot(status="stale"))
    assert card.preview_status.config.call_args.kwargs["text"] == "3D 수신 중단"
    assert card.badge.config.call_args_list == distance_calls
    card.update_3d(PreviewSnapshot(status="empty"))
    assert card.preview_status.config.call_args.kwargs["text"] == "3D 유효점 없음"


def test_invalid_lidar_distance_cannot_trigger_display_danger():
    st = status()
    st.obstacle.left_m, st.obstacle.left_ok = 0.1, False
    d = dashboard(st)
    with patch.multiple(config, SIM_MODE=False, LIDAR_SOURCE="udp"):
        d._refresh()
    assert "위험" not in d.overall.config.call_args.kwargs["text"]
    d.flash.start.assert_not_called()


def test_disabled_lidar_is_explicit_and_does_not_hide_imu_fault():
    st = status()
    st.obstacle = ObstacleReport()
    d = dashboard(st)
    with patch.multiple(config, SIM_MODE=False, LIDAR_SOURCE="none"):
        d._refresh()
        assert "LiDAR 미사용" in d.overall.config.call_args.kwargs["text"]
        st.imu.valid = False
        d._refresh()
    assert "IMU" in d.overall.config.call_args.kwargs["text"]


def test_monitor_loss_invalidates_cards_and_closes_old_question():
    d = dashboard(alive=False)
    popup = d._popup = Mock()
    d._refresh()
    d.imu_card.set_unavailable.assert_called_once_with("감시 연결 끊김")
    d.gps_card.set_unavailable.assert_called_once_with("감시 연결 끊김")
    popup.destroy.assert_called_once()
    assert d.sos_button.config.call_args.kwargs["state"] == ui.tk.DISABLED
    assert "마지막 수신" in d.health_lbl.config.call_args.kwargs["text"]
    assert "확인 불가" in d.summary_imu.config.call_args.kwargs["text"]
    assert "확인 불가" in d.summary_gps.config.call_args.kwargs["text"]


def test_camera_controls_keep_both_sensor_views_in_sync_and_select_3d():
    d = dashboard()
    d.display_mode_buttons = {"3D": Mock(), "2D": Mock()}
    d.view_buttons = {key: Mock() for key in ("front", "oblique", "top", "side")}
    d._set_display_mode("2D")
    assert d.display_mode == "2D"
    d._set_view("side")
    assert d.display_mode == "3D" and d.current_view == "side"
    for card in (d.lidar_l, d.lidar_r):
        card.set_mode.assert_called_with("3D")
        card.preview_3d.set_view.assert_called_once_with("side")


def test_grid_size_selection_updates_both_previews_without_sensor_commands():
    d = dashboard()
    d.grid_size_buttons = {value: Mock() for value in (1, 5, 10)}
    d.preview_sub = Mock()
    for centimeters in (1, 5, 10):
        d._set_grid_size_cm(centimeters)
        assert d.grid_size_cm == centimeters
        d.lidar_l.preview_3d.set_grid_size_cm.assert_called_with(centimeters)
        d.lidar_r.preview_3d.set_grid_size_cm.assert_called_with(centimeters)
        assert d.grid_size_buttons[centimeters].config.call_args.kwargs["relief"] == ui.tk.SUNKEN
    d.cmd.send.assert_not_called()
    assert d.preview_sub.mock_calls == []


def test_details_toggle_preserves_emergency_controls():
    d = dashboard()
    d._details_visible = False
    d.main_panel, d.details_panel, d.details_button = Mock(), Mock(), Mock()
    d._toggle_details()
    d.main_panel.grid_remove.assert_called_once()
    d.details_panel.grid.assert_called_once()
    assert d.details_button.config.call_args.kwargs["text"] == "기본 화면"
    d._toggle_details()
    d.main_panel.grid.assert_called_once()
    d.details_panel.grid_remove.assert_called_once()
    d.sos_button.grid_remove.assert_not_called()
    d.recovery_panel.pack_forget.assert_not_called()


def test_warning_pulse_never_creates_a_window_over_sos():
    root, banner = Mock(), Mock()
    with patch.object(ui.tk, "Toplevel") as window:
        pulse = ui.FlashOverlay(root, banner)
        pulse.start()
        assert pulse.active
        banner.config.assert_called_with(highlightbackground=ui.C_RED)
        pulse.stop()
    window.assert_not_called()
    assert not pulse.active


def gps_card():
    card = ui.GPSCard.__new__(ui.GPSCard)
    for name in ("badge", "detail", "coord", "marker", "config"):
        setattr(card, name, Mock())
    card._last_pos = (37.0, 127.0)
    card._last_map_t = 1.0
    return card


def test_invalid_gps_clears_coordinates_and_current_marker():
    card = gps_card()
    marker = card.marker
    card.update_card(GpsFix(valid=False, lat=37.0, lon=127.0))
    marker.delete.assert_called_once()
    assert card.marker is None and card._last_pos is None
    assert "확인 불가" in card.coord.config.call_args.kwargs["text"]


def test_incomplete_or_no_fix_gps_is_not_presented_as_current_location():
    for gps in (GpsFix(valid=True, lat=37.0, fix_quality=4),
                GpsFix(valid=True, lat=37.0, lon=127.0, fix_quality=0)):
        card = gps_card()
        card.update_card(gps)
        assert card.marker is None
        assert "확인 불가" in card.coord.config.call_args.kwargs["text"]


def test_gps_recovery_restores_coordinate_color():
    card = gps_card()
    card._clear_position()
    with patch.object(ui, "MAP_AVAILABLE", False):
        card.update_card(GpsFix(valid=True, lat=37.0, lon=127.0, fix_quality=4))
    assert card.coord.config.call_args.kwargs["fg"] == ui.C_WHITE


def test_sos_waits_for_monitor_and_blocks_duplicate_requests():
    d = dashboard()
    with patch.object(ui.time, "monotonic", return_value=10.0):
        d._sos()
        d._sos()
    d.cmd.send.assert_called_once_with(CMD_SOS)
    assert "확인 중" in d.sos_status.config.call_args.kwargs["text"]
    assert d.sos_button.config.call_args.kwargs["state"] == ui.tk.DISABLED
    assert "즉시 보호자" not in d.term.append.call_args.args[0]


def test_sos_is_not_sent_without_monitor_or_during_existing_incident():
    for st, alive in ((status(), False), (SystemStatus(tipover_state=TIPOVER_REPORTED), True)):
        d = dashboard(st, alive)
        d._sos()
        d.cmd.send.assert_not_called()


def test_sos_timeout_allows_retry_without_claiming_acceptance():
    d = dashboard()
    d._sos_requested_at = 10.0
    with patch.object(ui.time, "monotonic", return_value=12.1):
        d._update_sos(status(), True)
    assert "응답 확인 못함" in d.sos_status.config.call_args.kwargs["text"]
    assert d.sos_button.config.call_args.kwargs["state"] == ui.tk.NORMAL


def test_sos_send_error_cannot_claim_request_success():
    d = dashboard()
    d.cmd.send.return_value = False
    d._sos()
    assert "송신 실패" in d.sos_status.config.call_args.kwargs["text"]
    assert d._sos_requested_at is None


def test_notification_results_are_distinct_and_do_not_claim_guardian_read():
    d = dashboard()
    for state, expected in (("queued", "전송 대기"), ("sending", "전송 중"),
                            ("accepted", "서버 접수 확인"), ("failed", "전송 실패"),
                            ("unconfigured", "전송되지 않음"), ("", "결과 확인 불가")):
        d._update_sos(SystemStatus(tipover_state=TIPOVER_REPORTED,
                                  notification_state=state), True)
        text = d.sos_status.config.call_args.kwargs["text"]
        assert expected in text
        if state == "accepted":
            assert "열람 여부는 확인 불가" in text
    d._update_sos(SystemStatus(tipover_state=TIPOVER_CONFIRMED,
                              notification_state="accepted"), True)
    assert "서버 접수 확인" not in d.sos_status.config.call_args.kwargs["text"]


def test_schema_supports_old_monitor_and_new_delivery_fields():
    assert SystemStatus.from_dict({}).notification_state == ""
    st = SystemStatus(notification_id="event", notification_state="accepted")
    restored = SystemStatus.from_dict(st.to_dict())
    assert restored.notification_id == "event" and restored.notification_state == "accepted"
