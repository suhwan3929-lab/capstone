# `safety_monitor.py`

> **한 줄:** 안전 필수 프로세스의 진입점. **이것만 살아 있으면 시스템이 동작한다.**
> **계층:** 진입점 | **실행:** `python safety_monitor.py`

---

## 무엇을 하는가

모든 구성요소를 조립하고 100 Hz 주 루프를 돌린다.

```
센서 수집(imu/gps/lidar_source)
   → 전도 판정(tipover_monitor)
   → 경고 출력(alerting)
   → CSV 기록(csv_logger)
   → 상태 송신(status_link)
동시에: 물리 버튼(buttons) · RTK(ntrip_client) · 배터리(battery)
```

GUI(`ui.py`)도, Jetson의 LiDAR도 없어도 된다.
→ 계획서의 **"Jetson이 죽어도 Pi 단독으로 알림은 살아 있어야 한다"** 요구사항이
코드 구조로 강제된다.

## 실행 옵션

```bash
python safety_monitor.py                          # 일반
python safety_monitor.py --sim                    # 하드웨어 없이
python safety_monitor.py --sim --scenario tipover_front
python safety_monitor.py --tag curb               # 실험 데이터 수집
python safety_monitor.py --calibrate              # IMU 장착각 측정 후 종료
python safety_monitor.py --no-ui-link             # 상태 송신 없이 헤드리스
python safety_monitor.py --no-alert               # 부저/LED 끄기
python safety_monitor.py --list-scenarios
```

## 설계 포인트

### 인자를 import보다 먼저 읽는다

```python
ARGS = _parse_args()
import config
if ARGS.sim: config.SIM_MODE = True
import alerting, battery, ...      # noqa: E402
```

`sensors/lidar_source.py` 가 **import 시점에** `config.LIDAR_SOURCE` 를 보고
구현을 고르기 때문에, 설정 확정이 import보다 앞서야 한다.
`# noqa: E402` 주석은 이 의도적 순서를 린터에 알리는 것이다.

### 주 루프는 100 Hz, 상태 송신은 10 Hz

```python
LOOP_HZ = 100
publish_every = LOOP_HZ // config.STATUS_HZ    # 10틱마다 송신
```

CSV를 10 Hz로 기록하면 충격 피크를 놓친다(→ `csv_logger.md` 참조).
반면 UI는 10 Hz면 충분하므로 나눴다.

### 단차를 장애물보다 위험하게 취급

```python
bias = 0.25 if curb_type == "drop" else 0.10
effective = max(0.05, curb_m - bias)
warn_m = min(obstacle_m, effective)
```

내려가는 턱은 발이 헛디뎌지는 순간 바로 전도로 이어지므로 더 가까운 것처럼 다룬다.

### 초기 점검에 실패해도 감시 스레드는 띄운다

센서가 나중에 연결되면 자동 복구된다. 부팅 시점에 없다고 포기하지 않는다.

## 고칠 때 주의

- ⚠ **주 루프 안에서 블로킹 I/O를 하지 말 것.** 100 Hz다.
- ⚠ **`log()` 는 예외를 삼킨다.** 로그 한 줄 때문에 안전 필수 프로세스가 죽으면 안 된다.
  `console.setup()` 과 함께 cp949 크래시를 막는 2중 방어다.
- ⚠ 종료 시 `finally` 블록에서 모든 구성요소를 `stop()` 한다.
  구성요소를 추가하면 여기도 추가할 것. 안 하면 시리얼 포트가 안 닫힌다.
- `--calibrate` 는 측정 후 즉시 종료한다. 일반 실행 경로와 섞지 말 것.

## 관련 파일

- systemd 유닛: `systemd/walker-safety.service`
- 개발용 동시 실행: `run_dev.py`
