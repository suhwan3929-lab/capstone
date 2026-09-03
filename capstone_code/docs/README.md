# 코드 문서 색인

> `capstone_code/` 의 모든 `.py` 파일에 대한 설명서.
> 각 문서는 **무엇을 하는가 / 왜 존재하는가 / 고칠 때 주의**를 담고 있다.

---

## 처음 보는 사람이 읽는 순서

1. [`../README.md`](../README.md) — 시스템 전체 구조와 실행법
2. [`../../용어_정의.md`](../../용어_정의.md) — **"낙상"이 아니라 "전도"인 이유** (필독)
3. [`tipover_monitor.md`](tipover_monitor.md) — 시스템의 심장
4. [`safety_monitor.md`](safety_monitor.md) — 모든 것이 조립되는 곳
5. [`../../설계값_근거.md`](../../설계값_근거.md) — 임계값이 왜 그 숫자인가

## AI에게 이 코드를 물어볼 때

이 문서들과 함께 다음을 같이 주면 맥락이 정확해진다.

- `docs/README.md` (이 파일) + 고치려는 파일의 `docs/<이름>.md`
- `states.py` 최상단 용어집
- `../../코드_리뷰.md` — 과거에 어떤 버그가 있었는지

**각 문서의 "고칠 때 주의" 절이 가장 중요하다.** 과거 버그의 재발 방지 조건이 적혀 있다.

---

## 기반 계층

| 문서 | 파일 | 한 줄 |
| :--- | :--- | :--- |
| [config.md](config.md) | `config.py` | 모든 튜닝값의 단일 장소 |
| [states.md](states.md) | `states.py` | 상태 문자열 단일 정의처 |
| [schema.md](schema.md) | `schema.py` | 모듈 간 데이터 형태 (미래의 `.msg`) |
| [console.md](console.md) | `console.py` | cp949 콘솔 크래시 방지 |

## 판정 · 출력 (안전 필수)

| 문서 | 파일 | 한 줄 |
| :--- | :--- | :--- |
| [tipover_monitor.md](tipover_monitor.md) | `tipover_monitor.py` | **전도 판정 FSM — 시스템의 심장** |
| [notifier.md](notifier.md) | `notifier.py` | 보호자 알림 (2단 전송 · 디스크 스풀) |
| [alerting.md](alerting.md) | `alerting.py` | 부저 · LED · 진동 (사용자에게 닿는 유일한 경로) |
| [buttons.md](buttons.md) | `buttons.py` | 취소 · SOS 물리 버튼 |

## 센서

| 문서 | 파일 | 한 줄 |
| :--- | :--- | :--- |
| [sensors/imu_sensor.md](sensors/imu_sensor.md) | `sensors/imu_sensor.py` | EBIMU 드라이버 (판정 로직 없음) |
| [sensors/gps_sensor.md](sensors/gps_sensor.md) | `sensors/gps_sensor.py` | ZED-F9P NMEA + RTCM 통로 |
| [sensors/lidar_serial.md](sensors/lidar_serial.md) | `sensors/lidar_serial.py` | LiDAR 직결 (**포맷 미검증**) |
| [sensors/lidar_udp.md](sensors/lidar_udp.md) | `sensors/lidar_udp.py` | Jetson에서 UDP 수신 |
| [sensors/sim.md](sensors/sim.md) | `sensors/sim.py` | 하드웨어 없는 시뮬레이터 |
| [sensors/sources.md](sensors/sources.md) | `sensors/*_source.py` | 실센서 / 시뮬레이터 선택 계층 |

## 부가

| 문서 | 파일 | 한 줄 |
| :--- | :--- | :--- |
| [ntrip_client.md](ntrip_client.md) | `ntrip_client.py` | RTK 보정정보 수신 |
| [battery.md](battery.md) | `battery.py` | 잔량 측정 + 저전압 안전 종료 |
| [status_link.md](status_link.md) | `status_link.py` | 프로세스 간 UDP |
| [csv_logger.md](csv_logger.md) | `csv_logger.py` | 실험 데이터 100 Hz 기록 |

## 진입점

| 문서 | 파일 | 한 줄 |
| :--- | :--- | :--- |
| [safety_monitor.md](safety_monitor.md) | `safety_monitor.py` | **안전 필수 프로세스** |
| [ui.md](ui.md) | `ui.py` | 읽기 전용 대시보드 |
| [run_dev.md](run_dev.md) | `run_dev.py` | 개발용 동시 실행기 |

## 도구 · 테스트 · Jetson

| 문서 | 파일 | 한 줄 |
| :--- | :--- | :--- |
| [tools/replay.md](tools/replay.md) | `tools/replay.py` | **로그 재생 + 임계값 스윕** |
| [tools/lidar_probe.md](tools/lidar_probe.md) | `tools/lidar_probe.py` | LiDAR 포맷 판별 |
| [tools/analyze_logs.md](tools/analyze_logs.md) | `tools/analyze_logs.py` | 분포 통계 · 그래프 |
| [tests/README.md](tests/README.md) | `tests/*.py` | 테스트 31종 |
| [jetson/lidar_bridge_node.md](jetson/lidar_bridge_node.md) | `jetson/lidar_bridge_node.py` | ROS 2 브리지 + 단차 감지 |

---

## 문서화하지 않은 파일

| 파일 | 이유 |
| :--- | :--- |
| `sensors/__init__.py` | 버전 문자열만 있음 |
| `config_local.py` | 개인 설정 (git 제외). 예시는 `config_local.py.example` |
| `jetson/launch/walker_lidar.launch.py` | [jetson/lidar_bridge_node.md](jetson/lidar_bridge_node.md) 에서 함께 설명 |
| `legacy/*.py` | **이전 단일 프로세스 버전.** 역사적 참고용이며 수정하지 않는다. 어떤 결함이 있었는지는 [`../../코드_리뷰.md`](../../코드_리뷰.md) 참조 |

---

## 전체를 관통하는 설계 규칙 5가지

1. **GUI는 읽기 전용.** 판정 로직 0줄. `ui.py` 를 죽여도 안전 기능이 계속 동작해야 한다.
2. **모듈 하나 = 미래의 ROS 2 노드 하나.** 센서 모듈끼리 서로 import 하지 않는다.
3. **즉석 dict 금지.** 모듈 사이 데이터는 `schema.py` 의 dataclass로만 오간다.
4. **단위를 변수명에 박는다.** `accel_g`, `left_m`, `roll_deg`. 모든 샘플에 `t_capture`.
5. **블로킹 I/O는 전용 스레드로.** 웹훅 전송이 판정 루프를 멈추게 하지 않는다.

## 반복되는 안전 원칙 3가지

- **조용히 죽지 않는다.** 센서가 멈추면 값을 무효화하고 사용자에게 소리로 알린다.
  낡은 값을 살아 있는 값처럼 표시하지 않는다.
- **틀린 계기판은 없는 계기판보다 나쁘다.** 측정 못 하면 "측정 안 됨"이라고 쓴다.
- **미탐 > 오탐.** 전도를 놓치는 것이 헛울리는 것보다 위험하다. 단, 오경보 한 번에
  보호자 신뢰가 무너지므로 **취소 수단**으로 균형을 잡는다.
