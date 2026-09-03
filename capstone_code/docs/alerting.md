# `alerting.py`

> **한 줄:** 부저 · LED · 손잡이 진동. **경고가 사용자에게 실제로 도달하는 유일한 경로.**
> **계층:** 출력 (안전 필수) | **의존:** `config`, `states`

---

## 왜 존재하는가

이 모듈이 없으면 시스템의 경고가 **사용자에게 도달하지 않는다.**
리팩터링 전 경고는 노트북 화면 깜박임뿐이었는데, **보행기를 미는 고령자는
1280×720 화면을 보고 있지 않다.** GUI는 개발자용 모니터링 도구이고,
실제 사용자 경고 경로는 이쪽이다.

## 경보 등급 (숫자가 클수록 우선)

| 값 | 상수 | 상황 |
| ---: | :--- | :--- |
| 0 | `SILENT` | 무음 |
| 1 | `SENSOR_FAULT` | 센서 이상 — 주기적 2연타 |
| 2 | `OBSTACLE_WARN` | 장애물 경고 (~1.0 m) |
| 3 | `OBSTACLE_DANGER` | 장애물 위험 (~0.5 m) + 진동 |
| 4 | `TIPOVER_IMPACT` | 충격 감지 |
| 5 | `TIPOVER_ASK` | 응답 대기 — 다급한 교대음 |
| 6 | `TIPOVER_CONFIRMED` | 사고 확정 |

높은 등급이 낮은 등급을 덮어쓴다.

## 설계 근거

- **부저 주파수 1500~2200 Hz** — ISO 24500/24501은 청각 신호의 기본 주파수를
  **2500 Hz 이하**로 권고한다. 연령 관련 난청(presbycusis)을 가진 65세 이상이
  명시적 대상인 표준이다. 흔히 쓰는 4 kHz 부저는 정작 사용자에게 안 들릴 수 있다.
- **손잡이 진동 병행** — 청각에만 의존하지 않는다.
- **거리 3단계로 음 간격 변화** — 주차센서와 같은 멘탈 모델.
- **히스테리시스** — 등급을 올릴 때는 즉시, 내릴 때는 `DIST_HYSTERESIS_M` 만큼
  더 멀어져야 한다. 없으면 임계값 근처에서 경보가 딸꾹질하듯 떨린다.
- **정지 중 경고 중단** — 경보 피로 방지.
- **센서 이상을 조용히 넘기지 않는다** — 다만 계속 울리면 무시당하므로
  `SENSOR_FAULT_REPEAT_SEC` 주기로만 고지.
- **사고 확정음은 인터넷과 무관하게 울린다** — 보호자 알림이 실패해도
  주변 사람의 도움을 유도하는 것이 마지막 방어선이다.

## 공개 인터페이스

```python
class Alerter:
    def start(self); def stop(self)
    def update(self, obstacle_m, tipover_level, sensor_fault, moving=True)
    @property backend_name

tipover_state_to_level(tipover_state) -> int   # states.TIPOVER_* → 경보 등급
```

`safety_monitor.py` 가 100 Hz 주 루프에서 `update()` 를 호출한다.

## 백엔드

| 이름 | 환경 | 비고 |
| :--- | :--- | :--- |
| `gpio` | Raspberry Pi | `gpiozero` PWM 부저 + 진동모터 + LED 2개 |
| `winsound` | 윈도우 개발 PC | 실제 소리로 패턴을 검증할 수 있다 |
| `null` | 헤드리스 / CI | 출력 없음 |

`ALERT_BACKEND = "auto"` 면 gpio → winsound → null 순으로 시도한다.

## 고칠 때 주의

- ⚠ **`update()` 는 상태만 기록하고 즉시 반환한다.** 실제 소리 출력은
  별도 스레드(`_loop`)가 한다. `update()` 에서 `time.sleep()` 을 부르면
  100 Hz 주 루프가 멈춘다.
- ⚠ **`_sleep_ms()` 는 등급이 바뀌면 즉시 빠져나온다.** 이게 없으면
  긴 쉼표 구간 중에 사고가 나도 반응이 최대 700 ms 늦는다.
- GPIO 백엔드의 `led()` 는 값이 바뀔 때만 쓴다. 매 프레임 GPIO를 두드리지 않기 위함.
- 등급을 추가하면 `_render()` 와 `LEVEL_NAME` 양쪽에 추가할 것.

## 미해결 (하드웨어 필요)

- **음압(dB) 값이 아직 근거 없음.** ISO 24501은 고정 dB가 아니라
  주변 소음 대비 산출 방법을 규정한다. 실외 보행 소음을 측정한 뒤 산출해야 한다.
- GPIO 핀 번호(`BUZZER_PIN` 등)는 실제 결선 후 확인 필요.
