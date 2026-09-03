"""
LiDAR 소스 선택기.

config.LIDAR_SOURCE 값에 따라 직결(serial)과 UDP(Jetson ROS 2) 중 하나를 고른다.
두 구현이 같은 인터페이스를 제공하므로 상위 코드(tipover_monitor, ui)는
어느 쪽인지 알 필요가 없다. 이것이 PC 개발 → 실기 이행을 무비용으로 만든다.
"""
import config
from schema import ObstacleReport
from states import CONN_ERROR

_impl = None

if config.LIDAR_SOURCE == "serial":
    from sensors import lidar_serial as _impl
elif config.LIDAR_SOURCE == "udp":
    from sensors import lidar_udp as _impl


def snapshot() -> ObstacleReport:
    if config.SIM_MODE:
        from sensors import sim
        return sim.obstacle_snapshot()
    if _impl is None:
        return ObstacleReport()
    return _impl.snapshot()


def status(side: str) -> str:
    if config.SIM_MODE:
        from states import CONN_OK
        return CONN_OK
    if _impl is None:
        return CONN_ERROR
    return _impl.status(side)


def start(log_callback=None) -> bool:
    if config.SIM_MODE:
        return True
    if _impl is None:
        if log_callback:
            log_callback("[LiDAR] 사용 안 함 (config.LIDAR_SOURCE='none')", "WARN")
        return False
    return _impl.start(log_callback)


def stop():
    if _impl is not None:
        _impl.stop()


def run_integrity_check(log_callback=None) -> bool:
    if config.SIM_MODE:
        return True
    if _impl is None:
        return False
    if hasattr(_impl, "run_integrity_check"):
        return _impl.run_integrity_check(log_callback)
    return True


def source_name() -> str:
    return "sim" if config.SIM_MODE else config.LIDAR_SOURCE
