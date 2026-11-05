# 고령자 보행기 안전 보조 시스템

Jetson은 ROS 2 LiDAR 처리, Raspberry Pi는 Python 안전 감시와 1024×600 가로 대시보드를 담당한다.
게시 기준 브랜치는 **main**이다. GitHub 코드 반영과 실제 장치 적용은 각각 확인한다.

## 2026-11-06 현재 점검 상태

**GPS·IMU 개별 수신과 기존 웹훅의 문자·실제 GPS 지도 수신을 확인했다. Pi 안전서비스는 재부팅 뒤에도 active였다.**

화면은 **같은 전원에서 USB 장치를 제거하고 켠 뒤 복구**됐다. **전원 문제 해결은 사용자 요청으로 보류**하며, 전체 장치 연결 상태의 반복 기동·실제 GUI SOS 전달·최종 장착각·장시간 운용은 미완료다. [최신 진행 현황](capstone_code/docs/progress_2026-11-06.md)과 [후속 트러블슈팅 18개 사례](capstone_code/docs/troubleshooting_history_20261106.md)에 확인 경계를 기록했다.

## 2026-11-04 GUI·LiDAR 변경

- 정면 3D 기본 화면, 2px 점, 고정 투영, 확대 눈금 1/5/10cm, 큰 시계.
- Jetson 왼쪽 채널 0·오른쪽 채널 1. Windows USB 시험도 기본 0/1.
- Jetson→Pi 표시 전용 UDP 9103은 프레임당 최대 9,600 유효점, 센서별 최대 10Hz.
  0.05~2.0m 유효점만 보내며 누락·손상 프레임은 표시하지 않는다. 기존 안전 거리 UDP 9100은 유지한다.
- **Pi 수신기를 먼저 업데이트하고 Jetson 패키지를 재빌드·재시작한다.**
  기존 고정 IP를 유지하며 `config_local.py`에 `UDP_PREVIEW_BIND`를 Pi의 현재 유선 IPv4로 한 번 지정한다. pull만으로 실제 실행 폴더/ROS 설치본이 갱신되는지 확인해야 한다.

[장치별 적용·예상 결과·롤백](capstone_code/docs/deploy_gui_channels.md)을 따른다.
사용자는 USB 채널 0/1 분리 후 간섭 감소를 확인했다고 보고했다.
이 게시본의 PC 테스트는 실제 Pi·Jetson 배포나 센서 정확도 검증을 뜻하지 않는다.

## 실행과 기록

- [최신 진행 현황: 2026-11-06](capstone_code/docs/progress_2026-11-06.md)
- [후속 트러블슈팅 18개 사례: 2026-11-06](capstone_code/docs/troubleshooting_history_20261106.md)
- [후속 트러블슈팅 HTML](capstone_code/docs/troubleshooting_history_20261106.html)
- [이전 트러블슈팅 26개 사례: 2026-11-05](capstone_code/docs/troubleshooting_history_20261105.md)
- [소프트웨어 구조·기본 실행](capstone_code/README.md)
- [3D 점군·전송 형식](capstone_code/docs/lidar_3d_preview.md)
- [Windows 두 USB 센서 시험](capstone_code/docs/usb_3d_pc_test.md)
- [재시작 복구·3D 수신 상태](capstone_code/docs/recovery_and_3d_status.md)
- [GUI 상태·SOS 표시](capstone_code/docs/gui_status_update.md)
- [사고 후 감시 재개](capstone_code/docs/incident_recovery.md)
- [Ubuntu SSH·APT 잠금 해결](capstone_code/docs/remote_access.md)
- [Git 업데이트와 코드 버전 확인](capstone_code/docs/git_update.md)
- [이전 진행 기록: 2026-10-18](capstone_code/docs/progress_2026-10-18.md)
- [단계별 최종 시험](최종%20테스트.md)

개인 설정·로그·원본 센서 캡처·Python 환경은 게시하지 않는다. main의 무선 IMU·지도·웹훅 후속 변경과 실기 결과는 최신 진행 문서에서 확인한다. 작업 원본의 독립 변경 전체가 게시됐다고 가정하지 않는다.
