# `tests/` — 테스트 스위트

> **31종. 전체가 1초 안에 끝난다.**
> **코드를 고쳤으면 이걸 먼저 돌릴 것. 특히 `tipover_monitor.py` 를 건드렸다면 필수.**

---

## 실행

```bash
python tests/run_all.py       # pytest 없이도 동작
python tests/run_all.py -v    # 전체 스택 트레이스
pytest tests/                 # pytest가 있으면 그대로 동작
```

## 왜 pytest 없이도 돌아가야 하는가

8인 팀에서 각자 환경이 다르다. **의존성 없이 돌아가는 경로**가 있어야
"내 환경에서는 안 돌아가서 안 돌렸다"는 상황이 안 생긴다.

`run_all.py` 는 `test_*` 로 시작하는 모듈 수준 함수를 찾아 실행하는 최소 러너다.

---

## `tests/test_tipover_fsm.py` — 전도 판정 FSM (12종)

**가상 시계를 주입**해 실시간을 기다리지 않는다. 20초짜리 시나리오가 수 ms에 끝난다.

```python
class Rig:
    def feed(self, seconds, accel, roll, pitch, gyro, valid, hz=100)
    def impact(self, g=4.0)
```

| 테스트 | 무엇을 지키는가 |
| :--- | :--- |
| `test_normal_walking_never_triggers` | 정상 보행에서 아무 일도 없다 |
| **`test_impact_while_upright_is_released`** | **기울기 관문** — 없으면 횡단보도에서 신고가 간다 |
| `test_fall_confirmed_when_motionless` | 충격 + 쓰러짐 + 무응답 → 확정 |
| `test_user_cancel_during_asking` | 응답 대기 중 취소 |
| **`test_user_cancel_before_popup_is_not_lost`** | **명령 유실 회귀** — 상태 전이와 같은 틱에 도착해도 유실 안 됨 |
| **`test_movement_releases_but_needs_time_separation`** | **노이즈 2샘플로 전도가 취소되지 않는다** |
| `test_posture_recovery_releases` | 스스로 일어나면 해제 |
| **`test_rearm_cooldown_prevents_repeat_alerts`** | **반복 통보 회귀** |
| `test_sos_bypasses_fsm` | SOS는 판정을 건너뛴다 |
| `test_dead_imu_does_not_advance_fsm` | 죽은 센서로 확정이 나가지 않는다 |
| `test_reset_after_report` | 신고 후 리셋 |
| `test_confirm_sends_exactly_once` | 같은 사고로 두 번 신고하지 않는다 |

**굵게 표시된 4개는 실제로 발생했던 버그의 회귀 테스트다.** 이 테스트가 깨지면
과거 버그가 되살아난 것이므로 반드시 원인을 찾을 것.

---

## `tests/test_components.py` — 구성요소 (19종)

| 영역 | 테스트 |
| :--- | :--- |
| UDP 링크 | 상태 왕복, 명령 3연발 중복 제거, seq 역전 폐기 + 재시작 수용, 링크 끊김 시 값 은닉 |
| NMEA | 체크섬, RTK 품질 파싱, 체크섬 없는 문장 거부, fix 상실 시 좌표 보존 |
| LiDAR | `u16le`/`u12` 언패킹, 체크섬 3종 |
| 경보 | 등급 우선순위, 히스테리시스, 정지 중 무음 |
| 알림 | **플레이스홀더 URL 거부(회귀)**, 디스크 스풀 |
| 배터리 | 전압 곡선 단조성, **측정 불가 시 None 반환(회귀)** |
| 시뮬레이터 | 전 시나리오 출력 범위 검사 |
| 스키마 | 왕복 보존, `tilt_deg` 계산 |

### 타이밍에 흔들리지 않게

```python
def wait_for(predicate, timeout=3.0, interval=0.02)
```

**고정 `sleep` 은 CI에서 반드시 깨진다.** 실제로 한 번 깨져서 이 헬퍼를 도입했다.
새 비동기 테스트를 쓸 때 `time.sleep()` 대신 이것을 쓸 것.

---

## 테스트를 추가할 때

- ⚠ **회귀 테스트에는 "무엇이 깨졌었는지"를 docstring에 남길 것.**
  숫자만 있는 테스트는 반년 뒤에 아무도 왜 있는지 모른다.
- ⚠ 포트를 쓰는 테스트는 **실제 포트와 다른 번호**를 쓸 것 (19100번대).
- ⚠ `config` 값을 바꿨으면 테스트 끝에 되돌릴 것. 모듈 전역이라 다음 테스트에 샌다.
- 새 테스트 모듈을 만들면 `run_all.py` 의 `MODULES` 리스트에 추가.
