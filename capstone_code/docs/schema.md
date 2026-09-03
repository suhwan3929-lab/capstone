# `schema.py`

> **한 줄:** 모듈 사이를 오가는 모든 데이터의 형태를 dataclass로 못박은 파일.
> **계층:** 기반 | **의존:** `states`

---

## 무엇을 하는가

| dataclass | 내용 | 주요 파생 속성 |
| :--- | :--- | :--- |
| `ImuSample` | roll/pitch/yaw(deg), `accel_g`, `gyro_dps`, `t_capture`, `valid` | `.tilt_deg` = max(&#124;roll&#124;, &#124;pitch&#124;) |
| `GpsFix` | lat/lon, `fix_quality`, `satellites`, `hdop`, `utc`, `valid` | `.has_position` |
| `ObstacleReport` | `left_m`, `right_m`, `curb_m`, `curb_type`, `link_ok`, `latency_s` | `.nearest_m` |
| `HealthReport` | 배터리·NTRIP·알림 대기열 상태 | — |
| `SystemStatus` | 위 전부를 묶은 UI 전송용 패킷 | `.to_dict()` / `.from_dict()` |

## 왜 존재하는가

**즉석 dict를 주고받으면 ROS 2로 옮길 수 없다.** 여기 정의된 dataclass가
그대로 `msg/` 디렉터리가 된다.

| 지금 | ROS 2 이행 후 |
| :--- | :--- |
| `ImuSample` | `sensor_msgs/Imu` (`accel_g` × 9.80665 → m/s²) |
| `GpsFix` | `sensor_msgs/NavSatFix` + 품질 별도 토픽 |
| `ObstacleReport` | 커스텀 `.msg` |
| `SystemStatus` | 커스텀 `.msg` |
| `t_capture` | `header.stamp` |
| `valid` 플래그 | 토픽 미발행으로 대체 |

## 규약 — 지켜야 하는 것

1. **모듈 사이 데이터는 반드시 이 dataclass로만 오간다.** 즉석 dict 금지.
2. **변수명에 단위를 박는다.** `accel_g`, `left_m`, `roll_deg`.
   단위 없는 이름(`accel`, `dist`)은 리뷰에서 지적된 실제 버그의 원인이었다
   (ROS 표준 m/s² 와 g 혼동).
3. **모든 샘플은 `t_capture` 를 갖는다.** 워치독과 ROS 이행 양쪽에 필요하다.
4. 좌표계는 REP-103: x=전방, y=좌측, z=상방. 각도는 deg.

## 고칠 때 주의

- **필드를 추가할 때는 반드시 기본값을 준다.** `SystemStatus.from_dict()` 가
  `.get()` 으로 읽으므로, 기본값이 있으면 구버전 송신자와도 호환된다.
- `to_dict()` 는 `dataclasses.asdict()` 를 쓰므로 **JSON 직렬화 가능한 타입만** 넣을 것.
  `datetime`, `numpy` 배열 등을 넣으면 UDP 전송에서 터진다.
- `from_dict()` 는 중첩 dataclass를 손으로 복원한다. **중첩 필드를 추가하면
  `from_dict()` 도 같이 고쳐야 한다.** 안 고치면 조용히 기본값이 들어간다.
- `tilt_deg` 가 `max(|roll|, |pitch|)` 인 것은 판정의 핵심이다.
  yaw는 전도 판정과 무관하므로 포함하지 않는다.

## 테스트

- `tests/test_components.py::test_schema_roundtrip_preserves_everything`
- `tests/test_components.py::test_imu_tilt_uses_max_of_roll_pitch`
