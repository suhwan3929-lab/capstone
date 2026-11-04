"""Sample measured XYZ rays without removing floor returns or adding a ground plane."""
import numpy as np

from .protocol import MAX_POINTS, MAX_FRAME_POINTS


def normalize_xyz(points, profile="cyglidar_d2"):
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    # CygLiDAR SDK mapping_point_cloud.cpp already publishes forward/left/up in metres.
    if profile == "cyglidar_d2":
        return points
    if profile == "ros_optical":
        return points[:, [2, 0, 1]] * [1, -1, -1]
    raise ValueError("Unknown coordinate profile")


def full_xyz(points, profile="cyglidar_d2"):
    """Retain every valid D2 pixel, with a bounded 9600-point frame."""
    points = normalize_xyz(points, profile)
    radius = np.linalg.norm(points, axis=1)
    # ROS float32 XYZ can put a valid 50/2000 mm ray just across the boundary.
    keep = (np.isfinite(points).all(axis=1) & (points[:, 0] > 0)
            & (radius >= .05 - 1e-6) & (radius <= 2.0 + 1e-6))
    selected = points[keep][:MAX_FRAME_POINTS]
    return np.rint(selected * 1000).astype(np.int16).tolist()


def sample_xyz(points, profile="cyglidar_d2"):
    points = normalize_xyz(points, profile)
    radius = np.linalg.norm(points, axis=1)
    keep = np.isfinite(points).all(axis=1) & (points[:, 0] > 0) & (radius >= 0.05) & (radius <= 2.0)
    points, radius = points[keep], radius[keep]
    if not len(points):
        return []
    # Keep one nearest measured ray in each horizontal AND vertical cell (16 x 12).
    azimuth = np.arctan2(points[:, 1], points[:, 0])
    elevation = np.arctan2(points[:, 2], np.hypot(points[:, 0], points[:, 1]))
    horizontal = np.clip(((azimuth + np.deg2rad(60)) / np.deg2rad(120) * 16).astype(int), 0, 15)
    vertical = np.clip(((elevation + np.deg2rad(32.5)) / np.deg2rad(65) * 12).astype(int), 0, 11)
    bins = vertical * 16 + horizontal
    order = np.lexsort((radius, bins))
    _, first = np.unique(bins[order], return_index=True)
    selected = points[order[first]][:MAX_POINTS]
    return np.rint(selected * 1000).astype(np.int16).tolist()
