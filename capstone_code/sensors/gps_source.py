"""
GPS 소스 선택기 — 실제 센서 vs 시뮬레이터.
imu_source.py 와 같은 패턴.
"""
import time

import config
from schema import GpsFix
from sensors import gps_sensor


def snapshot() -> GpsFix:
    if config.SIM_MODE:
        from sensors import sim
        return sim.gps_snapshot()
    return gps_sensor.snapshot()


def position_age() -> float:
    if config.SIM_MODE:
        from sensors import sim
        f = sim.gps_snapshot()
        return (time.time() - f.t_capture) if f.lat is not None else float("inf")
    return gps_sensor.position_age()


def start(log_callback=None) -> bool:
    if config.SIM_MODE:
        return True
    return gps_sensor.start(log_callback)


def stop():
    if not config.SIM_MODE:
        gps_sensor.stop()


def run_integrity_check(log_callback=None) -> bool:
    if config.SIM_MODE:
        return True
    return gps_sensor.run_integrity_check(log_callback)
