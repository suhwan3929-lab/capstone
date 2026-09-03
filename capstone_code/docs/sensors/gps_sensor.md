# `sensors/gps_sensor.py`

> **한 줄:** ZED-F9P NMEA 드라이버 + RTCM 보정정보 전달 통로.
> **계층:** 센서 드라이버 | **의존:** `config`, `schema`, `states`, `pyserial`(선택)

---

## 공개 인터페이스

```python
snapshot() -> GpsFix
position_age() -> float      # 마지막 유효 좌표로부터 경과 초. 없으면 inf
write_rtcm(data: bytes)      # NTRIP → F9P (큐 경유)
last_gga() -> str | None     # VRS 업로드용 원시 GGA
start(log_callback); stop()
find_gps_port()              # VID 우선 자동 탐색
run_integrity_check(log_callback)
```

## 리팩터링에서 고친 것

| 결함 | 조치 |
| :--- | :--- |
| 재연결 없음 | 지수 백오프 감시 루프 |
| 신호가 끊겨도 "정상" | `t_capture` + 신선도 강등 |
| **fix 상실 시 마지막 좌표를 현재 위치처럼 유지** | `quality > 0` 일 때만 좌표 갱신 + `position_age()` 제공 |
| 체크섬 없는 문장을 유효로 처리 | `_checksum_ok()` 가 `*` 없으면 False |
| **아무 COM 포트나 GPS로 열었다** | u-blox VID(`0x1546`) 우선 매칭 |

### fix 상실 처리 — 미묘한 부분

fix를 잃으면 GGA의 위경도 필드가 **비어서** 온다.
좌표는 **보존하되 갱신하지 않는다.** 사고 신고에 "몇 초 전 좌표"로 쓸 수 있어야 하기 때문이다.
대신 `position_age()` 로 신선도를 반드시 함께 보고한다.

### 자동 탐색이 왜 위험했나

리팩터링 전 윈도우 폴백은 `for p in ports: return p.device` 였다.
**LiDAR(COM3)나 IMU(COM6)를 GPS로 열어버릴 수 있었다.**
그러면 그 센서의 포트를 빼앗기고 NMEA 파서는 쓰레기를 읽는다.

## RTCM 통로 (RTK)

`ntrip_client` 가 `write_rtcm()` 으로 넣으면, **수신 스레드가** 큐를 비워 포트에 쓴다.
시리얼 포트를 여러 스레드가 동시에 만지지 않게 하려는 구조다.
한 번에 최대 8개만 쓴다 — 몰아쓰면 NMEA 수신이 밀린다.

## 고칠 때 주의

- ⚠ **포트에 쓰는 것은 수신 스레드뿐이다.** 다른 곳에서 `ser.write()` 하지 말 것.
- ⚠ **GGA는 받은 원문을 그대로 보관한다.** VRS 업로드에 재조립하면 체크섬이 틀어진다.
- ⚠ `find_gps_port()` 는 못 찾으면 `None` 을 반환한다. **아무 포트나 집어오지 않는다.**
- `run_integrity_check()` 는 유효 NMEA 수신을 조건으로 한다. 실패 시 통신속도
  (38400/9600) 확인을 안내한다.

## 테스트

`tests/test_components.py::test_nmea_checksum_and_fix_quality`,
`test_nmea_rejects_missing_checksum`, `test_gps_keeps_position_when_fix_lost`
