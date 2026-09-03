# `sensors/imu_source.py` · `gps_source.py` · `lidar_source.py`

> **한 줄:** 실제 센서와 시뮬레이터 중 하나를 고르는 얇은 선택 계층.
> **계층:** 추상화 | **의존:** `config`, 각 구현 모듈

---

## 왜 존재하는가

상위 코드(`tipover_monitor`, `safety_monitor`, `ui`)는 데이터가
**실제 센서에서 오는지 시뮬레이터에서 오는지 알 필요가 없다.**

이 계층이 그것을 숨긴다. 덕분에:

- 하드웨어 없이 전체 시스템 개발이 가능하다 (`--sim`)
- PC 개발(LiDAR 직결) → 실기(Jetson UDP) 전환이 설정 한 줄이다

## 선택 규칙

| 모듈 | 분기 기준 | 선택지 |
| :--- | :--- | :--- |
| `imu_source` | `config.SIM_MODE` | `sim` / `imu_sensor` |
| `gps_source` | `config.SIM_MODE` | `sim` / `gps_sensor` |
| `lidar_source` | `config.SIM_MODE`, `config.LIDAR_SOURCE` | `sim` / `lidar_serial` / `lidar_udp` / 없음 |

```python
# config_local.py 한 줄로 실기 전환
LIDAR_SOURCE = "udp"
```

## 공통 인터페이스

```python
snapshot()                      # → ImuSample / GpsFix / ObstacleReport
start(log_callback) -> bool
stop()
run_integrity_check(log_callback) -> bool
```

추가로 `imu_source.capture_mount_offset()`, `gps_source.position_age()`,
`lidar_source.status(side)` / `source_name()`.

## 고칠 때 주의

- ⚠ **`lidar_source` 는 import 시점에 구현을 고른다.**
  ```python
  if config.LIDAR_SOURCE == "serial":
      from sensors import lidar_serial as _impl
  ```
  따라서 **`config.LIDAR_SOURCE` 를 바꾸는 코드는 이 모듈 import보다 먼저 실행되어야 한다.**
  `safety_monitor.py` 가 인자 파싱을 import보다 앞에 두는 이유다.
  (반면 `SIM_MODE` 는 호출 시점에 확인하므로 순서에 자유롭다.)
- ⚠ **이 계층에 로직을 넣지 말 것.** 순수한 위임만 한다.
  로직이 들어가면 실센서와 시뮬레이터의 동작이 갈린다.
- 새 소스를 추가하면 세 파일의 인터페이스를 동일하게 유지할 것.

## ROS 2 이행 시

이 계층은 **삭제된다.** 노드 구성이 그 역할을 대신한다.
