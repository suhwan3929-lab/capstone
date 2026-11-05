# Jetson을 끈 상태에서 실제 IMU·GPS와 GUI 연결 시험

2026-11-06 Pi 현재 확인값: SIM_MODE=False, IMU=/dev/walker_imu/921600/wireless,
설정 명령 사용=False, GPS=/dev/walker_gps/115200, 외부 알림 설정 없음,
walker-safety.service=inactive. 기존 LIDAR_SOURCE는 serial이다.
IMU는 책상 위 시험 상태이며 최종 장착각 보정은 하지 않았다.

## 이번 시험의 범위

실제 센서를 읽고 안전 판정 및 GUI 상태 전송을 실행한다. Jetson/LiDAR 입력은 이번 실행에서만 제외한다.
실내 GPS는 통신이 정상이더라도 위치가 잡히지 않을 수 있다.
시뮬레이션 데이터를 사용하거나 안전감시 자동 시작을 등록하는 단계가 아니다.

`--no-alert`는 부저/LED만 끈다. 외부 전송 차단에는 반드시 `--no-notify`를 함께 사용한다.
`--no-notify`는 알림 워커와 기존 대기 기록 복원을 시작하지 않으며 새 시험 알림을 큐나 디스크에 남기지 않는다.
기존 사고 알림 파일은 지우거나 변경하지 않는다. 현재 시험 프로세스가 종료되면 이 옵션도 종료된다.

## Pi PuTTY

다른 IMU/GPS 읽기 스크립트가 끝났는지 확인한다. GUI는 켜 둔다.

```bash
git -C "$HOME/capstone" pull --ff-only origin main
cd "$HOME/capstone/capstone_code"
/opt/walker/venv/bin/python safety_monitor.py --no-notify --no-alert --lidar-source none --tag bench_imu_gps
```

시작 로그에서 시험용 외부 알림 차단, LiDAR 사용 안 함, IMU 유효 데이터 수신 및 초기화 완료를 확인한다.
GUI의 안전감시 연결 끊김 표시가 해소되는지, 센서 상세에서 실제 IMU 자세가 바뀌는지 확인한다.
GPS 좌표는 fix를 얻기 전까지 확인 불가로 표시되어야 한다.
이 과정은 실제 기기 수신과 GUI 연동 시험이며 사고 감지 성능이나 보호자 수신을 검증한 것이 아니다.

SOS 시험은 위 명령으로 실행한 프로세스에서만 진행한다. GUI는 `시험 모드 · 외부 알림 전송 안 함`을 표시한다.
판정 상태 초기화를 위해 종료 후 같은 명령으로 다시 시작할 수 있다.
종료는 PuTTY에서 Ctrl+C다. 종료 뒤 GUI의 안전감시 연결 끊김 표시가 돌아오는 것은 정상이다.

## 남은 작업

최종 보행기 장착과 수평 보정, GPS 실제 위치 fix, Jetson 포함 거리/점군 통합,
승인한 시험 채널에서 실제 알림 수신, 전체 안전서비스 부팅 등록과 재부팅 확인을 별도로 진행한다.
최종 Jetson 연결에서는 `--lidar-source udp`를 사용하거나 config_local.py에 LIDAR_SOURCE="udp"를 저장한다.
이번 `none` 옵션은 config_local.py나 systemd 설정을 바꾸지 않는다.
