"""
IMU 소스 선택기 — 실제 센서 vs 시뮬레이터.

config.SIM_MODE 하나로 갈린다. 상위 코드(tipover_monitor, safety_monitor)는
어느 쪽인지 알 필요가 없다 — 이것이 하드웨어 없이 개발을 가능하게 만든다.
lidar_source.py 와 같은 패턴이다.
"""
import config
from schema import ImuSample
from sensors import imu_sensor


def snapshot() -> ImuSample:
    if config.SIM_MODE:
        from sensors import sim
        return sim.imu_snapshot()
    return imu_sensor.snapshot()


def start(log_callback=None) -> bool:
    if config.SIM_MODE:
        return True         # 시뮬레이터는 safety_monitor가 한 번만 띄운다
    return imu_sensor.start(log_callback)


def stop():
    if not config.SIM_MODE:
        imu_sensor.stop()


def run_integrity_check(log_callback=None) -> bool:
    if config.SIM_MODE:
        return True
    return imu_sensor.run_integrity_check(log_callback)


def capture_mount_offset(duration=2.0):
    if config.SIM_MODE:
        return (0.0, 0.0)
    return imu_sensor.capture_mount_offset(duration)
