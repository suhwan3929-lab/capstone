"""
프로젝트 전역 설정 — 모든 튜닝값은 여기 한 곳에만 둔다.

개인/보드별로 다른 값(COM 포트 등)은 이 파일을 고치지 말고
같은 폴더에 `config_local.py`를 만들어 덮어쓴다. (git 제외 대상)

    # config_local.py
    IMU_PORT = "COM11"
    GPS_PORT = "COM12"

ROS 2 이행 시: 이 파일의 값들이 노드 파라미터(YAML)가 된다.
"""
import os

# ══════════════════════════════════════════════════════════
# 실행 구성
# ══════════════════════════════════════════════════════════
#: 시뮬레이터 모드. 하드웨어 없이 전체 시스템을 돌린다.
#: 8인 팀에서 하드웨어는 한 세트뿐이므로, 나머지 인원은 이 모드로 개발한다.
#:   python safety_monitor.py --sim --scenario tipover_front
SIM_MODE = os.environ.get("WALKER_SIM", "0") == "1"
SIM_SCENARIO = os.environ.get("WALKER_SIM_SCENARIO", "normal_walk")

# LiDAR 데이터를 어디서 받을 것인가
#   "serial" : 이 기기에 LiDAR를 직결 (PC 개발용)
#   "udp"    : Jetson의 ROS 2 브리지 노드에서 수신 (실기 구성)
#   "none"   : LiDAR 사용 안 함
LIDAR_SOURCE = os.environ.get("WALKER_LIDAR_SOURCE", "serial")

# ══════════════════════════════════════════════════════════
# 시리얼 포트
# ══════════════════════════════════════════════════════════
# 실기(Pi/Jetson) 이행 시에는 udev 규칙으로 고정 심볼릭 링크를 만들고
# "/dev/walker_imu" 같은 이름을 쓸 것. /dev/ttyUSB0 번호는 부팅마다 바뀐다.

#: IMU = E2BOX **EBIMU24GV52** (2.4 GHz 무선 AHRS)
#:   ⚠ 제품명의 "24G"는 **2.4 GHz 무선**이지 24 g가 아니다.
#:     실제 가속도 측정범위는 **2 g ~ 16 g 설정 가능** → 반드시 ±16 g로 설정할 것.
#:     ±2 g / ±4 g면 IMPACT_THRESHOLD_G(2.8 g)에 도달하지 못한다.
#:   ⚠ 여기 적는 포트는 센서가 아니라 **무선 수신기(리시버)** 의 포트다.
#:   ⚠ 센서에 자체 리튬폴리머 배터리가 있다. battery.py 는 이것을 보지 못한다.
#:     시연 전 충전 체크리스트에 반드시 포함할 것.
#:   내부 갱신 1000 Hz — 임계값 실험 때는 100 Hz보다 높여서 로깅할 수 있다.
IMU_PORT = "COM6"
IMU_BAUD = 115200

#: GPS = **UB-ZED03** (u-blox ZED-F9P 탑재 보드로 추정)
#:   ⚠ 확인 필요: ① USB/UART ② 기본 통신속도 ③ RTCM 입력 경로
#:                ④ **안테나가 멀티밴드(L1+L2)인가** — 단주파면 RTK가 동작하지 않는다
#:   보드에 CP210x/CH340 변환칩이 있으면 u-blox VID(0x1546) 매칭이 안 되므로
#:   GPS_PORT 를 None 으로 두지 말고 명시할 것.
GPS_PORT = "COM5"          # None 이면 VID/PID로 자동 탐색
GPS_BAUD = 115200

#: LiDAR = **시그봇 CygLiDAR D2** (2D/3D Dual Solid-State ToF) — 계획서 원안과 동일
#:   2D: 0.2 ~ 7.0 m, 120° H, 1° 분해능
#:   3D: 0.05 ~ 2.0 m, 120° H × 65° V, 160×60 = 9,600점
#:   15 Hz · 정확도 ±1% · USB 또는 3.3 V UART · 37×37×24 mm, 28 g
LIDAR_PORT_LEFT = "COM3"
LIDAR_PORT_RIGHT = "COM10"
LIDAR_BAUD = 3_000_000

#: 운용 모드. "3d" | "2d"
#:   3d — 근거리 장애물 경고 + **단차(턱) 감지**. z가 있어야 지면 평면 추정이 가능.
#:        유효 2 m 이므로 경고 거리(1.0~1.5 m)와 단차 경고(1.2 m)를 모두 포함한다.
#:   2d — 원거리(7 m) 접근 인지. z가 없어 단차는 판별할 수 없다.
#:   ⚠ 실외 직사광에서 3D 유효거리가 줄면 경고 거리와 겹칠 수 있다.
#:      실외 실측은 반드시 두 모드를 각각 측정할 것.
LIDAR_MODE = "3d"

# ══════════════════════════════════════════════════════════
# 센서 무응답 판정 (§1.3 워치독)
#   마지막 유효 수신 이후 이 시간이 지나면 "값 없음 + 센서 이상"으로 강등한다.
#   화면에 낡은 값을 살아 있는 값처럼 표시하지 않기 위한 안전장치.
# ══════════════════════════════════════════════════════════
STALE_IMU_SEC = 0.5        # 100 Hz 센서 → 0.5초면 50샘플 결손
STALE_GPS_SEC = 3.0        # 1~10 Hz
STALE_LIDAR_SEC = 0.5      # 15~20 Hz

# ══════════════════════════════════════════════════════════
# IMU / 전도 판정
#
#   각 값의 근거 등급과 출처는 ../설계값_근거.md 참조.
#     A = 문헌·표준에 명시  |  B = 1차 원리 유도  |  C = 근거 없음(실측 필요)
#
#   ⚠ 문헌 임계값은 전부 **신체 착용형** 센서 기준이다.
#      우리는 보행기 프레임에 붙이므로 충격 전달 특성이 다르다.
#      금속 프레임이 지면에 직접 부딪히므로 피크가 더 클 가능성이 높다.
#   ⚠ 그 전에 가속도계 측정범위(FSR)를 확인할 것.
#      EBIMU24GV52는 **2 g ~ 16 g 설정 가능**이므로 반드시 ±16 g로 올려야 한다.
#      (제품명의 "24G"는 2.4 GHz 무선이지 24 g가 아니다)
#      ±2 g / ±4 g로 설정돼 있으면 아래 임계값에 영원히 도달하지 못한다.
#      자이로도 2000 dps로 — 전도 순간 각속도는 수백 dps를 쉽게 넘는다.
#   ⚠ 최종 확정은 실측 데이터 + tools/replay.py --sweep 으로. (계획서 §6.2)
# ══════════════════════════════════════════════════════════

#: [A] Bourke et al. 알고리즘("Bourke3")의 상한 임계값(UFT).
#:     Bagalà et al. (2012) PLOS ONE 7(5):e37062 이 13개 알고리즘을 실제 고령자
#:     낙상 데이터로 평가한 결과 최고 성능(민감도 82.8%, 특이도 96.7%,
#:     오경보 5회/24h)을 기록한 알고리즘이다.
#:     같은 논문의 Bourke1(UFT 1.79g)은 오경보가 22~85회/24h로 폭증했다.
IMPACT_THRESHOLD_G = 2.8

#: [A] 같은 Bourke3의 자세 판정 각도. 충격 후 1~3초 구간에서 ≥60°를 75% 이상 유지.
#:     Kangas et al.(2008)이 "누운 자세"를 수직가속도 ≤0.5g로 판정하는 것과도
#:     일치한다 (cos 60° = 0.5). 서로 다른 두 계열이 같은 값에 도달했다.
TIPOVER_TILT_DEG = 60.0

#: [C] 근거 없음. 문헌(Bourke3)은 충격 후 **1~3초 구간**을 연속 관찰한다.
#:     현재 구현은 5초를 기다린 뒤 한 시점만 본다 → 구간 관찰로 바꾸는 것이 문헌 정합.
STABILIZE_TIME = 5.0

#: [C] 근거 없음. 참고: Apple Watch는 **약 60초** 부동을 요구한다.
#:     우리는 그 1/12이다. 골든타임 우선 판단이지만 실측으로 검증할 것.
CHECK_TIME = 5.0

#: [B] Apple Watch의 자동 신고 카운트다운은 **30초**.
#:     Apple은 119 자동 호출이라 보수적이고, 우리는 보호자 메신저 통보 +
#:     물리 취소 버튼이 있으므로 1/3로 단축했다. 의도적 차이이며 근거를 댈 수 있다.
ASK_TIMEOUT = 10.0

# 판정이 '사고 아님'으로 해제된 뒤 충격 감지를 다시 켜기까지의 시간(초).
#   해제 직후에도 보행기가 여전히 기울어 있는 경우가 있는데(바닥에 눕혀둔 상태 등),
#   이때 작은 충격 하나만 있어도 곧바로 다시 사고로 확정되어
#   같은 상황을 보호자에게 반복 통보하게 된다.
#   ⚠ 이 시간 동안 발생한 '진짜 두 번째 전도'은 놓친다. 실측으로 조정할 것.
REARM_COOLDOWN = 5.0

# 움직임(= 의식 있음) 판정
#   ⚠ 아래 5개는 전부 [C] — 근거 없음. 실측으로 확정해야 한다.
#     방법: 쓰러진 상태에서 '의도적으로 움직인 구간'과 '정지 구간'의
#           가속도/각속도 분포를 비교해 겹치지 않는 지점을 고른다.
MOVE_ACCEL_TOL_G = 1.2     # [C] 기준 대비 가속도 변화
MOVE_ANGLE_TOL_DEG = 25.0  # [C] 기준 대비 자세 변화.
                           #     참고: Chen et al. 은 방향 변화 ≥20°를 낙상 지표로 쓴다
MOVE_GYRO_TOL_DPS = 80.0   # [C] 각속도
MOVE_MIN_INTERVAL = 0.5    # 움직임 이벤트 사이 최소 간격(초).
                           # 이게 없으면 연속된 노이즈 2샘플로 전도 판정이 취소된다.
REQUIRED_MOVE_COUNT = 2    # 이만큼 움직이면 "의식 있음"으로 보고 취소
BASELINE_AVG_SEC = 0.5     # 기준점을 한 샘플이 아니라 이 구간 평균으로 잡는다

# IMU 장착각 보정 — 보행기에 기울여 달았다면 여기에 정지 상태 값을 넣는다.
#   `python safety_monitor.py --calibrate` 로 측정값을 얻을 수 있다.
MOUNT_ROLL_OFFSET_DEG = 0.0
MOUNT_PITCH_OFFSET_DEG = 0.0

# ══════════════════════════════════════════════════════════
# LiDAR 장애물 경고
# ══════════════════════════════════════════════════════════
#: [A] 정지 거리에서 유도. 보행속도는 **국내 법정 설계값**을 쓴다.
#:
#:   경찰청 「교통신호기 설치·운영」 보행신호시간 산정 기준
#:       일반 보행자                        1.0 m/s  ("1 m당 1초")
#:       **보행약자(어린이·어르신·장애인)   0.8 m/s** ("0.8 m당 1초")  ← 채택
#:   해외 rollator 사용자 실측은 약 0.6 m/s로 더 느리다.
#:   **빠른 쪽이 보수적**이므로(반응 시간이 짧아짐) 0.8 m/s를 설계값으로 쓴다.
#:
#:       경고음 인지 + 반응 개시        ≈ 0.25 s
#:       정지 동작 완료                 ≈ 0.60 s   (고령자 급정지 530~590 ms 실측)
#:       ────────────────────────────────────────
#:       정지 거리 = 0.8 × 0.85 = **0.68 m**
#:
#: ⚠ 이전 값 DIST_DANGER_M = 0.5 는 **정지거리(0.68 m)보다 짧았다.**
#:   그 시점에 경고를 들으면 사용자는 물리적으로 멈출 수 없다. 계산으로 증명되는 결함.
#:
#: 현재 값의 근거 (자세한 유도는 ../감지거리_타당성.md):
#:   DIST_WARN_M  = 1.5 → 0.8 m/s에서 1.88 s 여유 = 정지거리의 2.2배.
#:                        3D 유효 2.0 m 안에 0.5 m(25%) 여유를 남겨,
#:                        실외에서 유효거리가 25% 줄어도 유지된다.
#:   DIST_DANGER_M = 0.8 → 정지거리 0.68 m 바로 위. **마지막 정지 가능 지점.**
#:
#: → 팀에서 보행속도를 실측했다면 위 식으로 다시 계산할 것. 식은 그대로 쓴다.
DIST_DANGER_M = 0.8
DIST_WARN_M = 1.5
DIST_HYSTERESIS_M = 0.15   # [C] 임계값 근처 거리 측정 표준편차 σ의 2배 이상으로
                           #     잡아야 한다. σ를 실측할 것.
                           #     없으면 임계값 근처에서 경보가 딸꾹질하듯 떨린다.

#: [A] CygLiDAR D2 데이터시트의 모드별 유효 거리.
#:     ⚠ 이전 값(0.10 / 8.00)은 **두 모드 어느 쪽과도 맞지 않았다.**
#:       2D 최소는 0.2 m인데 0.1 m를 유효로 받았고,
#:       3D 최대는 2.0 m인데 8.0 m까지 유효로 받았다.
#:       범위 밖 값은 센서 포화·난반사 쓰레기값이므로 반드시 걸러야 한다.
LIDAR_RANGE = {
    "3d": (0.05, 2.00),
    "2d": (0.20, 7.00),
}
LIDAR_MIN_VALID_M, LIDAR_MAX_VALID_M = LIDAR_RANGE.get(LIDAR_MODE, (0.05, 2.00))

LIDAR_PERCENTILE = 5       # [C] 균일 평면 100프레임 측정 → 이상치 비율보다 큰 값 선택
LIDAR_CONFIRM_FRAMES = 2   # [C] 단발 이상치가 연속 N프레임 지속될 확률을 측정해 결정

# ── 프레임 포맷 (⚠ 데이터시트 또는 tools/lidar_probe.py 로 확정할 것) ──
#   기본값은 '추정'이다. 확정 전까지 lidar_serial의 거리값을 신뢰하지 말 것.
#   실기에서는 Jetson의 벤더 ROS 2 드라이버가 이 파싱을 대체한다.
LIDAR_PAYLOAD_OFFSET = 5       # 페이로드에서 거리 배열이 시작되는 위치
LIDAR_PACKING = "u16le"        # "u16le" | "u16be" | "u12"(2점=3바이트)
LIDAR_CHECKSUM = "none"        # "none" | "xor" | "sum8"
LIDAR_SCALE_MM = 1.0           # 원시값 → mm 배율

# 단차(턱) 감지 — Jetson 브리지 노드에서 지면 평면 기준으로 계산
#
#: [A] 「교통약자의 이동편의 증진법 시행규칙」 [별표 2]
#:       · 보도-차도 경계 구간 높이 차 : **2 cm 이하**
#:       · 연석 높이                   : **25 cm 이하**
CURB_DROP_M = 0.05         # [A] 연석 상한 25 cm 대비 보수적으로 5 cm
CURB_RISE_M = 0.04         # [A⚠] **법정 턱낮추기 기준은 2 cm다.**
                           #   4 cm면 규정을 지킨 횡단보도 진입부 턱을 놓친다.
                           #   → 0.02 로 낮추는 것이 규정 정합.
                           #   단 ToF의 1 m 깊이 노이즈가 ±1~3 cm이므로
                           #   2 cm는 검출 한계에 걸린다. σ를 실측해
                           #   검출 가능 최소 단차(≈3σ)를 먼저 확인할 것.
#: [B] 단차는 정지 또는 앞바퀴 들어올림이 필요해 장애물보다 여유가 더 필요하다.
#:     → DIST_WARN_M 과 같은 1.5 m.
#:     기하 검증: 센서 높이 0.6 m, 아래로 15~25° 틸트 시 지면은 약 0.5 m부터
#:     화각에 들어오고, 원거리 한계는 화각이 아니라 3D 유효거리(2.0 m)가 결정한다.
#:     즉 화각 부족은 문제가 되지 않는다. (../감지거리_타당성.md §5)
CURB_WARN_M = 1.50

# ══════════════════════════════════════════════════════════
# 경고 출력 (부저 / LED / 진동)
#   ⚠ 대상이 고령자다. 노인성 난청은 고주파부터 손실되므로
#     흔히 쓰는 4 kHz 부저는 정작 사용자에게 들리지 않을 수 있다.
#     1~3 kHz 대역을 쓰고, 손잡이 진동을 병행한다.
# ══════════════════════════════════════════════════════════
ALERT_ENABLED = True
ALERT_BACKEND = "auto"     # "auto" | "gpio" | "winsound" | "null"

BUZZER_PIN = 18            # PWM 가능 핀 (BCM)
VIBRATOR_PIN = 12          # 손잡이 진동모터
LED_WARN_PIN = 27
LED_DANGER_PIN = 22

#: [A] ISO 24500:2010 / ISO 24501:2010 (Accessible design — auditory signals)
#:     "청각 신호의 **기본 주파수는 2500 Hz를 넘지 않아야 한다**"
#:     — 연령 관련 난청(presbycusis)을 가진 65세 이상을 명시적 대상으로 한 표준.
#:     흔히 쓰는 4 kHz 부저는 이 상한을 초과해 대상 사용자에게 안 들릴 수 있다.
BUZZER_FREQ_WARN = 1500    # Hz
BUZZER_FREQ_DANGER = 2200  # Hz  (모두 2500 Hz 이하)
BUZZER_FREQ_FALL = 2000    # Hz
BUZZER_DUTY = 0.5

#: (울림 ms, 쉼 ms) 패턴. 주차센서와 같은 멘탈 모델 — 가까울수록 촘촘하다.
PATTERN_WARN = (120, 700)
PATTERN_DANGER = (100, 160)
PATTERN_TIPOVER_ASK = (200, 200)      # 응답 대기: 다급하게
PATTERN_SENSOR_FAULT = (60, 60)    # 센서 이상: 짧은 2연타 후 긴 침묵

SENSOR_FAULT_REPEAT_SEC = 20.0     # 센서 이상 고지 반복 주기
ALERT_MIN_REPEAT_SEC = 2.0         # 같은 등급 경보 재고지 최소 간격 (경보 피로 방지)

# ══════════════════════════════════════════════════════════
# 물리 버튼
#   취소 버튼이 없으면 오경보가 그대로 보호자에게 간다.
#   고령자가 화면 팝업을 조작할 것이라고 가정해서는 안 된다.
# ══════════════════════════════════════════════════════════
BUTTONS_ENABLED = True
BUTTON_BACKEND = "auto"    # "auto" | "gpio" | "keyboard" | "null"
BUTTON_CANCEL_PIN = 5      # 짧게 누름 = 취소 / 확인
BUTTON_SOS_PIN = 6         # 길게 누름(2초) = 수동 긴급 호출
BUTTON_BOUNCE_SEC = 0.08
BUTTON_SOS_HOLD_SEC = 2.0

# ══════════════════════════════════════════════════════════
# RTK / NTRIP
#   ⚠ 로버에 상시 인터넷 회선(LTE)이 있어야 동작한다. BOM 확인 필요.
#   국토지리정보원 VRS 등 NTRIP 캐스터 계정이 필요하다.
#   계정은 환경변수로만 받는다 (소스에 적지 말 것).
# ══════════════════════════════════════════════════════════
NTRIP_ENABLED = os.environ.get("WALKER_NTRIP", "0") == "1"
NTRIP_HOST = os.environ.get("NTRIP_HOST", "")
NTRIP_PORT = int(os.environ.get("NTRIP_PORT", "2101"))
NTRIP_MOUNTPOINT = os.environ.get("NTRIP_MOUNTPOINT", "")
NTRIP_USER = os.environ.get("NTRIP_USER", "")
NTRIP_PASS = os.environ.get("NTRIP_PASS", "")
NTRIP_GGA_INTERVAL = 10.0     # VRS는 로버 위치를 주기적으로 올려줘야 한다
NTRIP_TIMEOUT = 15.0
NTRIP_MAX_BACKOFF = 60.0

# ══════════════════════════════════════════════════════════
# 배터리
#   ⚠ Raspberry Pi 5에는 BAT0 sysfs가 없다. 별도 연료 게이지가 필요하다.
#     붙이기 전까지 화면에는 "측정 안 됨"이 표시된다 (100%로 거짓 표시하지 않는다).
# ══════════════════════════════════════════════════════════
BATTERY_BACKEND = "auto"   # "auto" | "ina219" | "max17043" | "sysfs" | "null"
BATTERY_I2C_BUS = 1
BATTERY_INA219_ADDR = 0x40
BATTERY_MAX17043_ADDR = 0x36
BATTERY_CELLS = 4          # 3S 또는 4S
BATTERY_SHUNT_OHM = 0.1

BATTERY_WARN_PCT = 20.0
BATTERY_CRITICAL_PCT = 10.0
BATTERY_SHUTDOWN_PCT = 5.0
BATTERY_SHUTDOWN_ENABLED = False   # 실기에서 True. 전원 차단 전 안전 종료.
BATTERY_POLL_SEC = 10.0

# ══════════════════════════════════════════════════════════
# 네트워크 (UDP)
#   Jetson(ROS 2) → Pi : 장애물 거리
#   safety_monitor  → ui : 시스템 상태
#   ui → safety_monitor  : 사용자 응답(취소/확인)
# ══════════════════════════════════════════════════════════
UDP_LIDAR_PORT = 9100      # Pi가 수신
UDP_STATUS_PORT = 9101     # ui가 수신
UDP_COMMAND_PORT = 9102    # safety_monitor가 수신

UDP_STATUS_ADDR = ("127.0.0.1", UDP_STATUS_PORT)
UDP_COMMAND_ADDR = ("127.0.0.1", UDP_COMMAND_PORT)

STATUS_HZ = 10             # safety_monitor → ui 갱신 주기
SCHEMA_VERSION = 1         # 패킷 스키마 버전 (schema.py와 함께 올릴 것)

# ══════════════════════════════════════════════════════════
# 알림 (Discord Webhook)
#   ⚠ URL을 여기 적지 말 것. 환경변수로만 받는다.
#       Windows : setx WALKER_WEBHOOK_URL "https://discord.com/api/webhooks/..."
#       Linux   : /etc/walker/secrets.env  (systemd EnvironmentFile, 권한 600)
# ══════════════════════════════════════════════════════════
WEBHOOK_URL = os.environ.get("WALKER_WEBHOOK_URL", "").strip()
WEBHOOK_TIMEOUT = 5.0
WEBHOOK_MAX_RETRY = 6      # 지수 백오프: 1,2,4,8,16,32초
MAP_FETCH_TIMEOUT = 8.0

#: 전송하지 못한 알림을 디스크에 남긴다.
#: 프로세스가 죽거나 재부팅돼도 사고 알림이 사라지지 않도록 하기 위함.
NOTIFY_SPOOL = "logs/pending_alerts.jsonl"
NOTIFY_SPOOL_MAX = 200

# ══════════════════════════════════════════════════════════
# 로깅
# ══════════════════════════════════════════════════════════
LOG_DIR = "logs"
CSV_ENABLED = True         # 임계값 실험 데이터 수집. 항상 켜둘 것.
CSV_FLUSH_EVERY = 200      # 2초마다 디스크 반영 (전원 차단 대비)

# ── 개인 설정 덮어쓰기 (반드시 파일 맨 끝) ──────────────
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
