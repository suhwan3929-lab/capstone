# 고령자 보행기 안전 보조 시스템 — 소프트웨어

**구성: Jetson = ROS 2 (벤더 드라이버), Pi = 순수 Python, 둘 사이는 UDP.**
결정 근거와 이행 계획은 [`../코드_리뷰.md`](../코드_리뷰.md) §4 참고.

```
                    ┌──────────────── Jetson Orin Nano ────────────────┐
                    │  cygbot_ros2 드라이버 ×2  (벤더 제공)             │
                    │        ↓ /cygbot_*/scan                          │
                    │  lidar_bridge_node  ROI 필터 · 퍼센타일 · 단차감지 │
                    └────────────────────┬─────────────────────────────┘
                                         │ UDP 9100 (거리 + 단차, 20 Hz)
                    ┌────────────────────▼──── Raspberry Pi 5 ─────────┐
                    │  safety_monitor.py     ★ 안전 필수 · 단독 생존      │
                    │   IMU · GPS · 전도판정 · 부저/진동 · 물리버튼     │
                    │   NTRIP(RTK) · 배터리 · 보호자 신고               │
                    └────────────────────┬─────────────────────────────┘
                          UDP 9101 ↓     │ ↑ UDP 9102 (사용자 응답)
                    ┌────────────────────▼─────────────────────────────┐
                    │  ui.py               읽기 전용 대시보드            │
                    │  ※ 죽어도 안전 기능은 계속 동작한다               │
                    └──────────────────────────────────────────────────┘
```

---

## 빠른 시작

```bash
pip install -r requirements.txt
cp config_local.py.example config_local.py
```

**하드웨어가 없어도 전체 시스템이 돌아간다.** 8인 팀에 센서는 한 세트뿐이므로
나머지 인원은 시뮬레이터로 개발한다.

```bash
python run_dev.py --sim --scenario tipover_front
```

하드웨어가 있으면 `config_local.py`에서 포트만 맞추고:

```bash
python run_dev.py
```

웹훅 URL은 **소스에 적지 말고** 환경변수로 넘긴다.

```bash
setx WALKER_WEBHOOK_URL "https://discord.com/api/webhooks/..."
```

### 코드를 고쳤다면 반드시

```bash
python tests/run_all.py
```

31개 테스트가 1초 안에 끝난다. `tipover_monitor.py`를 건드렸다면 특히 필수다.

---

## 시뮬레이터 시나리오

| 시나리오 | 내용 | 기대 동작 |
| :--- | :--- | :--- |
| `normal_walk` | 정상 보행 | 아무 일 없음 |
| `curb` | 보도블록 턱 넘기 + 단차 감지 | 충격 감지 후 **해제** |
| `sudden_stop` | 급정지 | 충격 감지 후 **해제** |
| `place_down` | 보행기를 눕혀두고 자리를 뜸 | **오탐 유발 케이스** (아래 참고) |
| `tipover_front` | 전방 전복 | 사고 확정 → 신고 |
| `tipover_recover` | 넘어졌다 스스로 일어남 | 움직임 감지 후 **해제** |
| `obstacle` | 장애물 접근 | 경고 → 위험 3단계 |
| `sensor_drop` | 10초 후 IMU 사망 | 워치독이 잡아 부저로 고지 |

```bash
python safety_monitor.py --list-scenarios
```

> **`place_down`에 대하여 —** 보행기를 바닥에 눕혀두고 자리를 뜨면 IMU가 보는 신호는
> 실제 전도와 **원리적으로 구분되지 않는다.** 충격이 있었고, 기울어졌고, 움직이지 않는다.
> 이건 알고리즘으로 풀 문제가 아니라 **사용자가 취소 버튼을 누르는 것**으로 푸는 문제다.
> `tools/replay.py`가 이 케이스를 오탐으로 잡아내는 것이 정상이며,
> 이 한계를 보고서에 정직하게 쓰는 편이 심사에서 낫다.

---

## 파일 구조

| 파일 | 역할 | ROS 2 이행 시 |
| :--- | :--- | :--- |
| `config.py` | 모든 튜닝값 · 포트 · 임계값 | 노드 파라미터 YAML |
| `schema.py` | 메시지 스키마 (dataclass) | `msg/` 디렉터리 |
| `states.py` | 상태 문자열 단일 정의처 | 메시지 enum |
| `console.py` | cp949 콘솔에서 죽지 않게 하는 안전장치 | 그대로 |
| **판정 · 알림** | | |
| `tipover_monitor.py` | **전도 판정 FSM** (시계 주입 가능) | `tipover_detector_node` |
| `notifier.py` | 보호자 알림 · 2단 전송 · 디스크 스풀 | `notifier_node` |
| `alerting.py` | **부저 · LED · 손잡이 진동** | `alert_node` |
| `buttons.py` | 취소 / SOS 물리 버튼 | `button_node` |
| **센서** | | |
| `sensors/imu_sensor.py` | IMU 드라이버 (판정 로직 없음) | `imu_node` |
| `sensors/gps_sensor.py` | GPS 드라이버 + RTCM 전달 | `gps_node` |
| `sensors/lidar_serial.py` | LiDAR 직결 (PC 개발용) | 벤더 드라이버로 대체 |
| `sensors/lidar_udp.py` | Jetson에서 UDP 수신 | 서브스크라이버 |
| `sensors/*_source.py` | 실센서 / 시뮬레이터 선택 | 삭제 |
| `sensors/sim.py` | **시뮬레이터** | 삭제 또는 테스트용 유지 |
| **부가** | | |
| `ntrip_client.py` | RTK 보정정보(RTCM3) 수신 | `ntrip_client` 패키지 |
| `battery.py` | 연료 게이지 + 저전압 안전 종료 | `battery_node` |
| `status_link.py` | 프로세스 간 UDP | 토픽 |
| `csv_logger.py` | 실험 데이터 기록 (100 Hz) | rosbag |
| **진입점** | | |
| `safety_monitor.py` | 안전 필수 프로세스 | launch |
| `ui.py` | 대시보드 (읽기 전용) | 유지 또는 Foxglove |
| `run_dev.py` | 개발용 동시 실행기 | launch |
| **도구** | | |
| `tools/replay.py` | **로그 재생 + 임계값 스윕** | rqt / PlotJuggler |
| `tools/lidar_probe.py` | **LiDAR 프레임 포맷 판별** | 불필요 |
| `tools/analyze_logs.py` | 시나리오별 통계 · 그래프 | rqt |
| `tests/` | 테스트 31종 | 유지 |
| `jetson/` | ROS 2 브리지 노드 · launch | — |
| `systemd/` | 프로세스 감시 유닛 | launch `respawn` |
| `legacy/` | 이전 단일 프로세스 버전 (참고용) | — |

---

## 설계 규칙 (지키면 ROS 2 이행이 껍데기 교체로 끝난다)

1. **GUI는 읽기 전용.** 판정 로직 0줄. `ui.py`를 죽여도 안전 기능이 계속 동작해야 한다.
2. **모듈 하나 = 미래의 노드 하나.** 센서 모듈끼리 서로 import 하지 않는다.
3. **즉석 dict 금지.** 모듈 사이 데이터는 `schema.py`의 dataclass로만 오간다.
4. **단위를 변수명에 박는다.** `accel_g`, `left_m`, `roll_deg`. 모든 샘플에 `t_capture`.
5. **블로킹 I/O는 전용 스레드로.** 웹훅 전송이 판정 루프를 멈추게 하지 않는다.

---

## 임계값을 근거 있게 정하기 (계획서 §6.2)

`IMPACT_THRESHOLD_G = 2.8`, `TIPOVER_TILT_DEG = 60` 의 근거는 ../설계값_근거.md 를 참조한다.
심사에서 "왜 2.8입니까?"를 반드시 묻는다. 아래로 근거를 만든다.

### 1) 데이터 수집

```bash
python safety_monitor.py --tag normal_walk
python safety_monitor.py --tag curb            # 보도블록 턱 넘기
python safety_monitor.py --tag sudden_stop
python safety_monitor.py --tag place_down        # 보행기 내려놓기
python safety_monitor.py --tag car_load        # 차량 적재
python safety_monitor.py --tag tipover_front    # ← 더미/매트 사용
python safety_monitor.py --tag tipover_side
```

CSV는 **센서 원속도(100 Hz)** 로 기록된다. 상태 표시 주기(10 Hz)로 남기면
충격 피크를 통째로 놓친다 — 강체 충돌의 가속도 전이는 수십 ms에 끝난다.

**실제 고령자를 대상으로 전도를 재현하지 말 것.**
더미(모래주머니·마네킹) 또는 매트 위 젊은 피험자로 대체한다.

### 2) 재생해서 채점

```bash
python tools/replay.py logs/
```

기록된 로그를 **실제 판정 코드에 그대로 다시 통과시킨다.** 가상 시계를 쓰므로
20초짜리 로그가 수십 ms에 끝난다. 별도의 오프라인 구현을 만들지 않기 때문에
"재생에서는 되는데 실기에서 안 되는" 문제가 생기지 않는다.

### 3) 임계값 전수 탐색 ← 보고서용

```bash
python tools/replay.py logs/ --sweep
```

수백 개 조합을 훑어 **완전 분리 구간**과 그 중앙값을 알려준다.
미탐(전도를 놓침)에 오탐의 3배 벌점을 준다 — 안전 시스템에서 두 오류의 무게는 같지 않다.
출력되는 표와 구간이 그대로 보고서의 임계값 근거가 된다.

```bash
python tools/analyze_logs.py     # 시나리오별 통계 + 그래프 PNG
```

> **선행 조건:** 가속도계 측정범위(FSR)가 ±16 g 이상인지 먼저 확인할 것.
> ±2 g / ±4 g로 설정돼 있으면 2.8 g 임계값에 원리적으로 도달하지 못한다.
> `safety_monitor.py` 시작 시 자동 진단이 돌아가며, 정지 상태에서 1 g가 아니면 경고한다.

---

## LiDAR 프레임 포맷 확정

`sensors/lidar_serial.py`의 payload 오프셋과 비트 폭은 **추정값**이다.
틀려도 '그럴듯한 숫자'가 나와서 틀린 줄을 모르는 것이 이 문제의 위험한 점이다.
추측 대신 측정한다.

```bash
# 정면 1.0 m에 판을 세우고
python tools/lidar_probe.py dump --port COM3 --seconds 5 --truth 1.00
python tools/lidar_probe.py analyze logs/lidar_raw_COM3.bin --truth 1.00
```

오프셋 0~16 × 패킹 4종을 전수 탐색해 순위를 매기고, 체크섬 알고리즘도 판별한다.
결과를 `config_local.py`에 적으면 코드를 고칠 필요가 없다.

```python
LIDAR_PAYLOAD_OFFSET = 5
LIDAR_PACKING = "u12"
LIDAR_CHECKSUM = "xor"
```

**실기에서는 Jetson의 벤더 ROS 2 드라이버가 이 파싱을 대체한다** — 그쪽이 정답이다.

---

## RTK (cm급 측위)

`ntrip_client.py`가 없으면 F9P는 RTK로 동작하지 않고, 계획서가 내세운
"cm 단위 정밀 위치"는 성립하지 않는다. 측위 품질은 단독측위(수 m)에 머문다.

```bash
set WALKER_NTRIP=1
set NTRIP_HOST=<캐스터 주소>
set NTRIP_MOUNTPOINT=<마운트포인트>
set NTRIP_USER=...
set NTRIP_PASS=...
```

마운트포인트를 모르면:

```bash
python -c "import ntrip_client as n; n.print_sourcetable()"
```

측위 품질(단독/DGPS/**RTK 고정**/RTK 부동)은 대시보드와 **보호자 알림 메시지에
항상 함께 전송된다.** 보호자에게 "오차 ±2 cm"와 "오차 ±5 m"는 완전히 다른 정보다.

> ⚠ **로버에 상시 인터넷 회선(LTE)이 필요하다.** 현재 BOM에 모뎀이 없다.
> ⚠ VRS는 사용자 위치를 캐스터로 전송한다. 개인정보 처리 항목에 명시할 것.

---

## IMU 장착각 보정

보행기에 기울여 달았다면 반드시 필요하다. 안 하면 기울기 판정이 그만큼 어긋난다.

```bash
python safety_monitor.py --calibrate      # 수평 정지 상태에서 실행
```

출력된 두 줄을 `config_local.py` 에 붙여 넣는다.

---

## 실기 배포 (Raspberry Pi 5)

프로세스 격리와 자동 재시작은 [`systemd/README.md`](systemd/README.md) 참고.
Jetson 설정은 [`jetson/README.md`](jetson/README.md) 참고.

**배포 후 반드시 검증할 것:**

```bash
sudo systemctl stop walker-ui        # UI를 죽인다
journalctl -u walker-safety -f         # fall은 아무 일 없이 계속 도는가?
```

---

## 남은 과제

| 항목 | 상태 |
| :--- | :--- |
| **가속도계 FSR 확인** | ⚠ **최우선.** 코드로 해결 불가. 자동 진단 경고는 넣어두었다 |
| **LTE 모뎀 / 데이터 SIM** | ❌ BOM 누락. NTRIP·웹훅 둘 다 인터넷이 필요하다 |
| **LiDAR 프레임 포맷** | ⚠ `tools/lidar_probe.py` 로 10분이면 확정 가능. 하드웨어 필요 |
| **부저 · 진동 · LED 실배선** | ⚠ 코드는 완성. GPIO 핀 번호 확인 후 결선만 하면 된다 |
| **취소 / SOS 물리 버튼** | ⚠ 코드는 완성. BOM에 버튼 2개 추가 필요 |
| **연료 게이지 (INA219 등)** | ⚠ 코드는 완성. I2C 모듈 조달 필요 |
| **단차 감지 실측 검증** | ⚠ 3D PointCloud2 모드 + 아래로 틸트 장착이 전제 |
| **듀얼 LiDAR 외부 캘리브레이션** | ❌ 미착수 (P2) |
| **의료기기 아님 면책 · 위치정보 동의 절차** | ❌ 문서 작업 (계획서 리뷰 §4.3) |
| **무게중심 · 전도각 검토** | ❌ 기구 설계 (계획서 리뷰 §5.6) |
