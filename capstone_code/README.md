# 보행기 안전 소프트웨어

Pi 안전 프로세스와 UI, Jetson LiDAR 브리지로 구성됩니다. 안전 프로세스는 UI와 Jetson 없이도 전도 감지·현장 경보·보호자 알림을 계속 수행합니다.

## Windows 실행

```powershell
cd "D:\nas\유수환\26-2 capstone\capstone_code"
.\.venv\Scripts\python.exe .\tests\run_all.py
.\.venv\Scripts\python.exe .\run_dev.py --sim --scenario tipover_front
```

현재 테스트: 안전·구성요소 35개, Jetson 패키지 구조 3개.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\jetson\test -p "test_*.py" -v
```

## Pi 실행

```bash
python safety_monitor.py --sim --scenario normal_walk
python run_dev.py --sim --scenario tipover_front
python safety_monitor.py --calibrate
python safety_monitor.py --tag normal_walk
```

실기에서는 `config_local.py.example`을 `config_local.py`로 복사하고 포트·GPIO·IMU 보정값·LiDAR 소스를 지정합니다. 비밀값은 커밋하지 않습니다.

## 주요 파일

| 파일 | 역할 |
| --- | --- |
| `safety_monitor.py` | 센서·전도 FSM·경보·알림·기록 통합 |
| `tipover_monitor.py` | 전도 상태 머신 |
| `ui.py` | 터치 UI; 안전 로직과 분리 |
| `config.py` | 기본 설정 |
| `config_local.py` | 장치별 설정; Git 제외 |
| `sensors/` | IMU·GPS·LiDAR·시뮬레이터 |
| `jetson/` | ROS 2 LiDAR→UDP 패키지 |
| `systemd/` | Pi 자동 실행 서비스 |
| `tests/` | 의존성 없는 회귀 테스트 |
| `tools/` | 로그 분석·재생·LiDAR 포맷 확인 |

## 전도 상태 흐름

```text
정상 → 충격 감지
     → 1~3초 자세창에서 60° 이상 비율 75% 확인
     → 움직임 5초 관찰
     → 사용자 응답 10초 대기
     → 사고 확정·알림
```

취소, 자세 회복, 의미 있는 움직임이 있으면 정상으로 복귀합니다. SOS는 자동 판정을 건너뜁니다.

## 실기 전 확인

- IMU FSR ±16 g와 출력 필드
- Jetson 벤더 드라이버 토픽·좌표계
- LiDAR 지면 제거와 단차 임계값
- GPIO·배터리·LTE·터치 UI
- systemd 재부팅 복구와 Pi↔Jetson UDP

상세 배포는 저장소 루트의 `작업_목록.md`, 남은 검증은 `할일_목록.md`를 봅니다.
