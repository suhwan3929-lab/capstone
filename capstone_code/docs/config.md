# `config.py`

> **한 줄:** 프로젝트의 모든 튜닝값·포트·임계값이 모여 있는 단 하나의 장소.
> **계층:** 기반 | **의존:** 없음 (`config_local.py`만 선택적으로 흡수)

---

## 무엇을 하는가

시리얼 포트, 판정 임계값, 경고 거리, 부저 주파수, 네트워크 포트, 로그 설정 등
**동작을 바꾸는 모든 숫자**를 모듈 수준 상수로 보관한다. 다른 모듈은 전부 `import config`
후 `config.X` 로 읽는다.

파일 맨 끝에서 `from config_local import *` 를 시도한다. `config_local.py` 는
`.gitignore` 대상이므로, 각자 자기 COM 포트를 여기에 적으면 공용 파일을 건드리지 않는다.

## 왜 존재하는가

리팩터링 전에는 COM 포트가 4개 파일에, 임계값이 2개 파일에 흩어져 있었다.
8인 팀에서 각자 포트 번호가 다르므로 **전원이 소스를 고치게 되고, 그 상태로 파일을 주고받으면
충돌과 되돌림이 반복된다.** 설정을 한곳에 모으고 개인 설정을 분리한 이유다.

ROS 2로 이행하면 이 파일이 노드 파라미터 YAML이 된다.

## 주요 상수 그룹

| 그룹 | 대표 상수 | 비고 |
| :--- | :--- | :--- |
| 실행 구성 | `SIM_MODE`, `SIM_SCENARIO`, `LIDAR_SOURCE` | 환경변수로도 설정 가능 |
| 시리얼 포트 | `IMU_PORT`, `GPS_PORT`, `LIDAR_PORT_LEFT/RIGHT` | 실기에서는 udev 고정 링크 사용 |
| 워치독 | `STALE_IMU_SEC`, `STALE_GPS_SEC`, `STALE_LIDAR_SEC` | 이 시간 넘으면 값을 무효화 |
| 전도 판정 | `IMPACT_THRESHOLD_G`, `TIPOVER_TILT_DEG`, `STABILIZE_TIME`, `CHECK_TIME`, `ASK_TIMEOUT`, `REARM_COOLDOWN` | 근거 등급이 주석에 표시됨 |
| 움직임 판정 | `MOVE_*`, `REQUIRED_MOVE_COUNT`, `BASELINE_AVG_SEC` | 전부 등급 C (근거 없음) |
| 장애물 경고 | `DIST_WARN_M`, `DIST_DANGER_M`, `DIST_HYSTERESIS_M` | 정지거리에서 유도 |
| LiDAR 파싱 | `LIDAR_PAYLOAD_OFFSET`, `LIDAR_PACKING`, `LIDAR_CHECKSUM` | **추정값** — `tools/lidar_probe.py` 로 확정 |
| 단차 | `CURB_DROP_M`, `CURB_RISE_M`, `CURB_WARN_M` | 교통약자법 기준 |
| 경고 출력 | `BUZZER_FREQ_*`, `PATTERN_*`, `ALERT_BACKEND` | ISO 24500 기준 |
| 버튼 | `BUTTON_CANCEL_PIN`, `BUTTON_SOS_PIN`, `BUTTON_SOS_HOLD_SEC` | |
| RTK | `NTRIP_*` | 계정은 전부 환경변수 |
| 배터리 | `BATTERY_*` | |
| 네트워크 | `UDP_LIDAR_PORT`(9100), `UDP_STATUS_PORT`(9101), `UDP_COMMAND_PORT`(9102), `SCHEMA_VERSION` | |
| 알림 | `WEBHOOK_URL`, `NOTIFY_SPOOL` | URL은 환경변수에서만 |

## 고칠 때 주의

- **비밀값을 이 파일에 적지 말 것.** `WEBHOOK_URL`, `NTRIP_USER/PASS` 는
  `os.environ.get()` 으로만 읽는다. 여기에 실제 값을 적고 커밋하면
  제3자가 고령자의 실시간 위치를 수신할 수 있다.
- **`from config_local import *` 는 반드시 파일 맨 끝에 있어야 한다.**
  중간에 있으면 그 아래 정의가 개인 설정을 덮어써 버린다.
- **각 상수 위의 근거 주석(`[A]` / `[B]` / `[C]`)을 지우지 말 것.**
  숫자만 남으면 반년 뒤에 아무도 왜 그 값인지 모른다.
  등급 정의는 [`../../설계값_근거.md`](../../설계값_근거.md).
- 상수를 추가하면 `config_local.py.example` 에도 예시를 넣어 주는 편이 친절하다.

## 알려진 문제

- `DIST_DANGER_M = 0.5` 는 유도된 정지거리(약 0.51 m)와 같아 **반응 여유가 0**이다.
  보행속도를 실측한 뒤 재계산이 필요하다.
- `CURB_RISE_M = 0.04` 는 법정 턱낮추기 기준(2 cm)보다 커서
  규정을 지킨 횡단보도 진입부 턱을 놓친다.

## 관련 문서

- [`../../설계값_근거.md`](../../설계값_근거.md) — 모든 임계값의 근거와 등급
