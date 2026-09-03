# `sensors/lidar_serial.py`

> **한 줄:** CygLiDAR 직결 드라이버 (PC 개발용). **⚠ 프레임 포맷 미검증.**
> **계층:** 센서 드라이버 | **의존:** `config`, `schema`, `states`, `numpy`, `pyserial`(선택)

---

## 위치

실기 구성에서는 **이 모듈을 쓰지 않는다.** Jetson의 벤더 ROS 2 드라이버가
파싱을 담당하고 `sensors/lidar_udp.py` 가 결과만 받는다.
이 모듈은 PC에서 LiDAR를 직접 꽂아 볼 때 쓴다.

두 모듈은 같은 인터페이스(`snapshot() -> ObstacleReport`)를 제공하므로
`config.LIDAR_SOURCE` 만 바꾸면 상위 코드는 손댈 필요가 없다.

## ⚠ 가장 중요한 경고

```
PAYLOAD_OFFSET(5)과 '2바이트 리틀엔디안' 가정에 근거가 없다.
CygLiDAR 3D 모드는 12비트 패킹(2점=3바이트)일 가능성이 있고,
그 경우 파싱 결과는 '그럴듯하지만 완전히 틀린' 값이 된다.
```

**숫자가 그럴듯해서 틀린 줄을 모르는 것**이 이 문제의 위험한 점이다.

→ **`tools/lidar_probe.py` 로 10분이면 확정할 수 있다.** 추측하지 말 것.

## 공개 인터페이스

```python
snapshot() -> ObstacleReport
status(side) -> str          # "left" | "right"
start(log_callback); stop()
```

## 설계 포인트

### 롤링 버퍼 재동기화

블록 단위로 읽어 버퍼에 쌓고 `buf.find(HEADER)` 로 헤더를 찾는다.

리팩터링 전에는 `ser.read(1)` 을 최대 2048회 반복했는데,
3 Mbps에서 처리량을 따라가지 못했고, 페이로드 안의 `0x5A` 에서
**동기가 어긋나면 복구하지 못했다**(1바이트만 전진하는 로직이 없었다).

### 체크섬 검증

`config.LIDAR_CHECKSUM` 이 `"xor"` / `"sum8"` 이면 검증한다.
리팩터링 전에는 체크섬 바이트를 읽고 **버렸다.**
깨진 프레임이 그대로 거리값이 되어 허위 위험 경보를 만들 수 있었다.

### 최솟값 대신 퍼센타일

```python
dist = np.percentile(valid, config.LIDAR_PERCENTILE)
```

ToF는 반사·난반사·태양광으로 **튀는 픽셀이 반드시 생긴다.**
프레임 전체 최솟값을 쓰면 나쁜 픽셀 하나가 `0.03 m` 를 내고 즉시 위험 경보가 된다.
**시연 중 오경보 1순위 원인이다.**

추가로 `LIDAR_CONFIRM_FRAMES` 만큼 연속 위험이어야 확정한다.

### numpy 벡터 연산

초당 20~30만 점을 파이썬 루프로 처리하면 0.1~0.3 코어를 먹는다.
`np.frombuffer` 한 줄로 1% 미만이 된다. GIL도 풀린다.

## 고칠 때 주의

- ⚠ **파싱 상수를 코드에 하드코딩하지 말 것.** `config.LIDAR_*` 를 읽는다.
  `tools/lidar_probe.py` 결과를 `config_local.py` 에 적으면 코드를 안 고쳐도 된다.
- ⚠ **최소 거리 하한(`LIDAR_MIN_VALID_M`)을 없애지 말 것.**
  ToF는 최소 측정거리 미만에서 쓰레기값을 낸다.
- USB 2대를 꽂으면 부팅 순서에 따라 `/dev/ttyUSB0` ↔ `1` 이 뒤바뀐다.
  **udev 규칙으로 고정 심볼릭 링크를 만들 것.** 좌우가 바뀌면 점군이 반대로 합쳐진다.

## 테스트

`tests/test_components.py::test_lidar_unpack_u16le`, `test_lidar_unpack_u12`,
`test_lidar_checksum_modes`
