# `sensors/sim.py`

> **한 줄:** 하드웨어 없이 전체 시스템을 돌리는 센서 시뮬레이터.
> **계층:** 개발 지원 | **의존:** `config`, `schema`, `states`

---

## 왜 존재하는가

**8인 팀에 하드웨어는 한 세트뿐이다.** 나머지 7명이 센서를 기다리며
아무것도 못 하는 상황을 없애기 위한 것이다.

전도 판정·알림·UI·UDP 링크·경고 출력은 전부 이 모드에서 개발하고 검증할 수 있다.

```bash
python safety_monitor.py --sim --scenario tipover_front
python run_dev.py --sim --scenario curb
```

## 시나리오

| 이름 | 내용 | 기대 결과 |
| :--- | :--- | :--- |
| `normal_walk` | 정상 보행 (1.8 Hz 미세 진동) | 아무 일 없음 |
| `curb` | 보도블록 턱 넘기 + 단차 감지 | 충격 후 **해제** |
| `sudden_stop` | 급정지 | 충격 후 **해제** |
| `place_down` | 보행기를 눕혀두고 자리를 뜸 | **오탐** (아래 참조) |
| `tipover_front` | 전방 전도 (pitch +82°) | 확정 → 신고 |
| `tipover_side` | 측방 전도 (roll +86°) | 확정 → 신고 |
| `tipover_rear` | 후방 전도 (pitch −78°) | 확정 → 신고 |
| `tipover_recover` | 넘어졌다 스스로 일어남 | 움직임 감지 → **해제** |
| `obstacle` | 장애물이 0.35 m/s로 접근 | 경고 → 위험 |
| `sensor_drop` | 10초 후 IMU 사망 | 워치독이 잡아 부저 고지 |

## `place_down` 이 오탐인 것은 정상이다

보행기를 바닥에 눕혀두고 자리를 뜨면 IMU가 보는 신호는 **실제 전도와 원리적으로
구분되지 않는다.** 충격이 있었고, 기울어졌고, 움직이지 않는다.

이건 알고리즘으로 풀 문제가 아니라 **사용자가 취소 버튼을 누르는 것**으로 푸는 문제다.
`tools/replay.py` 가 이 케이스를 오탐으로 잡아내는 것이 정상이며,
**이 한계를 보고서에 정직하게 쓰는 편이 심사에서 낫다.**

## 공개 인터페이스

```python
SCENARIOS: dict[str, callable]
start(scenario=None, log_callback=None)
stop(); elapsed()
imu_snapshot(); gps_snapshot(); obstacle_snapshot()
```

시나리오 함수 시그니처: `t(초) -> (accel_g, roll, pitch, gyro, obstacle_m, imu_alive)`

## 고칠 때 주의

- ⚠ **이 모듈이 만드는 값은 '그럴듯한 모형'이지 실측이 아니다.**
  **임계값 확정에 이 데이터를 쓰면 순환 논리가 된다.**
  (실제로 한 번 그런 일이 있었다 — `설계값_근거.md` §0 참조)
  임계값은 반드시 실제 IMU 데이터로 정해야 한다.
- 시나리오를 추가하면 `SCENARIOS` 딕셔너리에 등록할 것.
  `tests/test_components.py::test_all_sim_scenarios_run` 이 모든 시나리오의
  출력 범위를 검사하므로, 비현실적인 값을 넣으면 테스트가 잡는다.
- `sensor_drop` 은 `t_capture` 를 갱신하지 않아 워치독이 잡도록 만들어져 있다.
