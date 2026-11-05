"""Check raw-depth comparison statistics without opening serial ports."""
import numpy as np

from tools.diagnose_usb_lidar_3d import summarize


def test_diagnostic_empty_and_single_frame_do_not_invent_temporal_motion():
    assert summarize([]) == {"frames": 0}
    report = summarize([np.full(9600, 1000, dtype=np.uint16)])
    assert report["frames"] == 1 and report["valid_pixels_median"] == 9600
    for region in ("all", "center"):
        values = report[region]
        assert values["valid_percent"] == 100
        assert values["depth_p05_median_p95_mm"] == [1000, 1000, 1000]
        assert values["paired_delta_median_p95_mm"] is None
        assert values["validity_toggle_percent"] is None


def test_diagnostic_known_motion_preserves_millimetres_and_percentiles():
    frames = [np.full(9600, value, dtype=np.uint16) for value in (1000, 1010, 1020)]
    report = summarize(frames)
    for region, pixels in (("all", 9600), ("center", 200)):
        values = report[region]
        assert values["stable_pixels"] == pixels
        assert values["depth_p05_median_p95_mm"] == [1000, 1010, 1020]
        assert values["paired_delta_median_p95_mm"] == [10, 10]
        assert values["paired_jumps_over_50mm_percent"] == 0
        assert values["temporal_mad_median_mm"] == 10


def test_diagnostic_invalid_returns_do_not_count_as_large_distance_jumps():
    frames = [np.full((60, 160), value, dtype=np.uint16) for value in (1000, 1010)]
    frames[1][25, 70], frames[1][25, 71] = 0, 2001
    report = summarize(frames)
    assert report["below_50_percent"] > 0 and report["above_2000_percent"] > 0
    assert report["center"]["valid_percent"] == 99.5
    assert report["center"]["stable_pixels"] == 198
    for region in ("all", "center"):
        assert report[region]["paired_delta_median_p95_mm"] == [10, 10]
        assert report[region]["paired_jumps_over_50mm_percent"] == 0
