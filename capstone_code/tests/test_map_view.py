"""실제 네트워크나 화면 없이 지도 위젯의 요청 경로를 검사한다."""
import importlib.util
import pathlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_map_tiles import png


def view_module():
    spec = importlib.util.spec_from_file_location(
        "map_view_test", pathlib.Path(__file__).resolve().parents[1] / "map_view.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"tkintermapview": SimpleNamespace(TkinterMapView=type("Base", (), {}))}):
        spec.loader.exec_module(module)
    return module


def widget(module):
    view = module.WalkerMapView.__new__(module.WalkerMapView)
    view.running = view.tiles_enabled = view._map_visible = True
    view.zoom = 3
    view.upper_left_tile_pos = (2.2, 3.3)
    view.lower_right_tile_pos = (3.1, 4.1)
    view.empty_tile_image = object()
    view.tile_image_cache = {}
    view.tile_client = Mock()
    view.tile_client.tile_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    return view


def test_map_view_never_prefetches_and_skips_hidden_unlocated_or_old_tiles():
    module = view_module()
    view = widget(module)
    view.pre_cache()
    for attribute in ("tiles_enabled", "_map_visible", "running"):
        setattr(view, attribute, False)
        assert view.request_image(3, 2, 3) is view.empty_tile_image
        setattr(view, attribute, True)
    assert view.request_image(2, 2, 3) is view.empty_tile_image
    assert view.request_image(3, 0, 0) is view.empty_tile_image
    view.tile_client.get_tile.assert_not_called()


def test_map_view_routes_visible_tiles_to_policy_client_and_handles_block():
    module = view_module()
    view = widget(module)
    view.tile_client.get_tile.return_value = png()
    with patch.object(module.ImageTk, "PhotoImage", return_value="tile"):
        assert view.request_image(3, 2, 3) == "tile"
    view.tile_client.get_tile.assert_called_once_with(3, 2, 3)
    assert view.tile_image_cache["323"] == "tile"
    view.tile_client.get_tile.return_value = None
    assert view.request_image(3, 3, 4) is view.empty_tile_image
    assert "334" not in view.tile_image_cache


def test_map_view_sets_actual_position_before_enabling_requests():
    module = view_module()
    view = widget(module)
    view.tiles_enabled = False
    events = []
    view.set_position = lambda lat, lon: events.append(("position", view.tiles_enabled))
    view.set_tile_server = lambda url: events.append(("server", view.tiles_enabled))
    view.set_gps_position(37, 127)
    assert events == [("position", False), ("server", True)]


def test_map_view_pauses_network_until_a_valid_position_returns():
    module = view_module()
    view = widget(module)
    view.pause()
    assert view.request_image(3, 2, 3) is view.empty_tile_image
    view.tile_client.get_tile.assert_not_called()


def test_map_view_refreshes_on_show_and_only_retries_visible_tiles():
    module = view_module()
    view = widget(module)
    view.set_tile_server = Mock()
    view._status_callback = Mock()
    view.after = Mock()
    view.winfo_ismapped = Mock(return_value=False)
    view._hidden()
    assert not view._map_visible
    view._shown()
    assert view._map_visible
    view.set_tile_server.assert_called_once()
    view.tile_client.retry_due.return_value = True
    view._poll_status()
    view.tile_client.retry_due.assert_not_called()
    view.winfo_ismapped.return_value = True
    view._poll_status()
    assert view.set_tile_server.call_count == 2
