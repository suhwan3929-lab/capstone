# 코드 문서 색인

먼저 [`../README.md`](../README.md)를 읽고, 수정할 모듈의 문서와 테스트를 함께 확인합니다.

## 안전 경로

| 문서 | 역할 |
| --- | --- |
| [safety_monitor.md](safety_monitor.md) | Pi 안전 프로세스 |
| [tipover_monitor.md](tipover_monitor.md) | 전도 FSM |
| [alerting.md](alerting.md) | 부저·진동·LED |
| [notifier.md](notifier.md) | 보호자 알림과 스풀 |
| [buttons.md](buttons.md) | 취소·SOS 버튼 |

## 센서·통신

| 문서 | 역할 |
| --- | --- |
| [sensors/imu_sensor.md](sensors/imu_sensor.md) | IMU 직렬 수신 |
| [sensors/gps_sensor.md](sensors/gps_sensor.md) | GNSS·RTCM |
| [sensors/lidar_udp.md](sensors/lidar_udp.md) | Jetson UDP 수신 |
| [sensors/lidar_serial.md](sensors/lidar_serial.md) | 잠정 직렬 파서 |
| [sensors/sources.md](sensors/sources.md) | 실센서·시뮬레이터 선택 |
| [status_link.md](status_link.md) | 안전 프로세스↔UI UDP |

## 설정·기록·UI

| 문서 | 역할 |
| --- | --- |
| [config.md](config.md) | 기본·로컬 설정 |
| [schema.md](schema.md) / [states.md](states.md) | 데이터·상태 규약 |
| [csv_logger.md](csv_logger.md) | 실험 CSV |
| [ntrip_client.md](ntrip_client.md) | RTK 보정 |
| [battery.md](battery.md) | 배터리 상태 |
| [ui.md](ui.md) / [run_dev.md](run_dev.md) | 화면·개발 실행 |

## 검증·Jetson

- [tests/README.md](tests/README.md): 안전·구성요소 35개, 패키지 구조 3개
- [jetson/lidar_bridge_node.md](jetson/lidar_bridge_node.md): ROS 2 LiDAR 브리지
- [tools/replay.md](tools/replay.md): 로그 재생·임계값 탐색
- [tools/lidar_probe.md](tools/lidar_probe.md): 직접 직렬 포맷 확인
- [tools/analyze_logs.md](tools/analyze_logs.md): 분포·그래프

공통 원칙: UI와 Jetson 장애가 전도 감지를 중단하면 안 되며, 오래된 센서값을 정상값으로 표시하지 않습니다.
