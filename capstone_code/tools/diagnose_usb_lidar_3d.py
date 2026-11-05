"""Bounded dual/single/dual raw-depth comparison. No stored sensor settings change."""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jetson.walker_preview.d2_usb import (
    DEPTH, AMPLITUDE, decode_depth, unit_rays)
from tools.usb_lidar_3d import UsbReceiver


class CaptureReceiver(UsbReceiver):
    """Use the GUI's independent port threads so an idle port cannot delay another."""
    def __init__(self, ports, capture_after):
        super().__init__(ports)
        self.capture_after = capture_after
        self.frames = {side: [] for side in ports}

    def ingest(self, side, payload):
        if not payload or payload[0] not in (DEPTH, AMPLITUDE):
            return False
        try:
            depth = decode_depth(payload)
        except ValueError:
            with self._lock:
                self._stats[side]["bad_frame"] += 1
            return False
        with self._lock:
            self._stats[side]["received"] += 1
            if time.monotonic() >= self.capture_after:
                self.frames[side].append(depth.copy())
        return True


def summarize(frames):
    if not frames:
        return {"frames": 0}
    depth = np.stack(frames).reshape(-1, 60, 160).astype(float)
    valid = (depth >= 50) & (depth <= 2000)
    result = {"frames": len(frames),
              "valid_pixels_median": float(np.median(valid.sum(axis=(1, 2)))),
              "below_50_percent": float(np.mean(depth < 50) * 100),
              "above_2000_percent": float(np.mean(depth > 2000) * 100)}
    for label, region in (("all", (slice(None), slice(None))),
                          ("center", (slice(25, 35), slice(70, 90)))):
        data = depth[:, region[0], region[1]]
        keep = valid[:, region[0], region[1]]
        usable = data[keep]
        paired = keep[1:] & keep[:-1]
        differences = np.abs(np.diff(data, axis=0))[paired]
        stable = keep.mean(axis=0) >= .8
        deviations = []
        for row, column in zip(*np.where(stable)):
            samples = data[:, row, column][keep[:, row, column]]
            deviations.append(float(np.median(np.abs(samples - np.median(samples)))))
        result[label] = {
            "valid_percent": float(keep.mean() * 100),
            "depth_p05_median_p95_mm": np.percentile(usable, (5, 50, 95)).tolist() if usable.size else None,
            "paired_delta_median_p95_mm": np.percentile(differences, (50, 95)).tolist() if differences.size else None,
            "paired_jumps_over_50mm_percent": float(np.mean(differences > 50) * 100) if differences.size else None,
            "validity_toggle_percent": float(np.mean(keep[1:] != keep[:-1]) * 100) if len(keep) > 1 else None,
            "stable_pixels": int(stable.sum()),
            "temporal_mad_median_mm": float(np.median(deviations)) if deviations else None}
    sampled = depth[:, ::2, ::2].reshape(len(depth), -1)
    sampled_valid = valid[:, ::2, ::2].reshape(len(depth), -1)
    rays = unit_rays().reshape(60, 160, 3)[::2, ::2].reshape(-1, 3)
    centroids = [np.mean(rays[ok, 1:] * distances[ok, None], axis=0)
                 for distances, ok in zip(sampled, sampled_valid) if ok.any()]
    result["display_centroid_yz_std_mm"] = np.std(centroids, axis=0).tolist() if centroids else None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", required=True)
    parser.add_argument("--right", required=True)
    parser.add_argument("--seconds", type=float, default=8)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw, report = {}, {}
    for phase, right_on in (("dual_before", True), ("usb1_only", False), ("dual_after", True)):
        ports = {"left": args.left}
        if right_on:
            ports["right"] = args.right
        receiver = CaptureReceiver(ports, time.monotonic() + 5.2)
        print("PHASE", phase, flush=True)
        try:
            receiver.start()
            time.sleep(5.2 + args.seconds)
        finally:
            receiver.stop()
        frames = receiver.frames
        report[phase] = {side: summarize(frames.get(side, [])) for side in ("left", "right")}
        report[phase]["transport"] = {side: receiver.stats(side) for side in ports}
        report[phase]["usable"] = (
            len(frames["left"]) >= 30 and
            all(not receiver.stats(side)[key] for side in ports
                for key in ("bad_checksum", "bad_frame", "error")) and
            (not right_on or len(frames.get("right", [])) >= 30))
        for side in ("left", "right"):
            values = frames.get(side, [])
            raw[phase + "_" + side] = np.stack(values) if values else np.empty((0, 9600), dtype=np.uint16)
        print(json.dumps({phase: report[phase]}, ensure_ascii=False), flush=True)
    report["comparison_usable"] = all(report[phase]["usable"]
                                      for phase in ("dual_before", "usb1_only", "dual_after"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    np.savez_compressed(args.output.with_suffix(".npz"), **raw)
    print("SAVED", str(args.output), flush=True)
    return 0 if report["comparison_usable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
