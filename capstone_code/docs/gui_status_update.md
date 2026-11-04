# GUI 상태 표시 수정과 장치 적용

작성일: 2026-11-04. 로컬 소스와 모의 시험 기준이며, 실제 Pi·Jetson 적용 기록은 아니다.

최신 장치 업데이트 순서는 [GUI·채널·9,600점 배포](deploy_gui_channels.md)를 따른다.

## 후속 3D 레이아웃 적용

현재 작업 원본의 `ui.py`는 1024×600 기본 3D 화면, 상세 보기, 고정 위치 SOS,
배너 테두리 경고로 갱신했다. `lidar_preview_view.py`의 점 크기와 축 안내도 조정했다.
같은 최신 기반 코드를 사용 중인 Pi라면 이 두 GUI 파일을 갱신하고 GUI만 재시작하면 된다.
아래의 상태 전송/SOS 결과 표시 변경까지 처음 적용한다면 관련 모니터 파일 갱신과 재시작도 필요하다.

구버전 GitHub 코드에는 3D 수신 파일 등이 없을 수 있으므로 두 파일만 무조건 덮어쓰지 않는다.
`lidar_preview.py`, `jetson/walker_preview/protocol.py`, 현재 `schema.py`/`states.py`/`status_link.py`
호환 여부를 함께 확인한다. 기존 `config_local.py`, 고정 IP, 설치된 서비스/시작 스크립트는 유지한다.
작업 원본 수정은 아직 GitHub 게시 또는 실제 Pi 적용을 의미하지 않는다.

이 PC에서는 실제 COM4·COM5의 USB 표시 시험까지 수행했다.
PC USB 시험은 모니터·신고 경로와 분리되어 있으며 [별도 실행 안내](usb_3d_pc_test.md)를 따른다.

## Git pull 뒤 고정 IP를 다시 설정해야 하는가

기존에 영구 저장한 NetworkManager/Netplan의 유선 IP 설정은 일반 `git pull`로 바뀌지 않는다.
3D 수신 주소만 기존 `config_local.py`의 `UDP_PREVIEW_BIND`에 현재 Pi 유선 IP로 한 번 지정한다.
OS 네트워크 설정 명령은 실행하지 않으며 거리/3D UDP 9100·9103과
Pi 내부 상태/명령 UDP 9101·9102도 바꾸지 않는다.

| 설정 | 이번 업데이트의 영향 |
| --- | --- |
| 보드 OS의 유선 고정 IP·Wi-Fi 프로필 | 변경 없음 |
| Git에서 제외된 `config_local.py`, `/etc/walker/secrets.env` | 일반 pull로 덮어쓰지 않음 |
| 설치된 `/usr/local/libexec/walker/start-jetson.sh`의 `pi_host` | pull만으로 변경되지 않음 |
| 저장소에서 직접 수정한 추적 대상 실행 파일 | pull 충돌 또는 배포 버전 차이 확인 필요 |

기존 직결 계획은 Jetson `192.168.10.1/24`, Pi `192.168.10.2/24`다.
이는 문서상 계획이며 현재 보드의 실제 주소를 확인한 결과가 아니다.
이미 다른 대역으로 정상 운용 중이면 이번 GUI 업데이트 때문에 바꾸지 않는다.
자동 실행 설치기를 다시 실행하거나 생성된 시작 스크립트를 덮어쓰면 실행 대상 IP가
달라질 수 있다. 이번 수정 적용을 위해 네트워크 설정 또는 자동 실행 설치를 다시 할 필요는 없다.
수동 ROS launch를 새 터미널에서 실행한다면 기존처럼 현재 Pi 유선 IP를 `pi_host`에 전달한다.

## 적용 대상과 범위

이번 기능 변경은 Pi의 `ui.py`, `schema.py`, `status_link.py`, `notifier.py`,
`safety_monitor.py`와 3D 수신/그리기 모듈에 있다. 전도 판정 FSM은 유지한다.
이번 게시본에는 Jetson 채널 0/1 런치와 최대 9,600점 분할 전송도 포함하므로
Pi 업데이트에 이어 Jetson `walker_lidar` 재빌드와 기존 런치 재시작이 필요하다.

상위 작업 폴더 `capstone_code`와 `.publish-capstone/capstone_code`는 별도 스냅샷이다.
상위 폴더 수정은 자동으로 GitHub에 올라가지 않는다. **수정본을 게시하고 장치가 사용하는
브랜치에 반영한 다음에야 장치의 pull로 받을 수 있다.** 현재 장치의 브랜치/경로는 미확인이다.

## Pi에서 적용하는 순서

1. 실제 서비스가 사용하는 경로를 확인한다. 아래 명령은 설정을 바꾸지 않는다.

   ```bash
   systemctl show walker-safety.service -p WorkingDirectory -p ExecStart
   systemctl cat walker-lidar.service  # Jetson에서만, 전송 목적지를 확인할 때
   ```

   서비스가 없는 구성은 현재 실행 명령과 폴더를 먼저 확인한다.

2. Pi의 실제 Git 저장소 루트에서 브랜치와 변경 파일을 확인한다.

   ```bash
   git rev-parse --show-toplevel
   git branch -vv
   git status --short
   ```

   서비스 코드 경로가 Git 저장소와 다르면 pull만으로 서비스는 갱신되지 않는다.
   ZIP/파일 복사 설치라면 기존 배포 경로로 수정 파일을 별도 적용해야 한다.
   코드와 `config_local.py`를 백업하고 적용 전 커밋을 기록한다.
   추적 파일에 장치 전용 수정이 있거나 이력이 갈라졌다면 먼저 비교한다.
   `git reset --hard`, `git clean` 또는 설정 파일 덮어쓰기로 해결하지 않는다.

3. 수정본이 게시·반영된 동일한 배포 브랜치를 받는다.

   ```bash
   git pull --ff-only
   ```

   다른 브랜치로 자동 전환하지 않는다. 전체 `capstone_code` 폴더를 복사해 덮어쓰기보다
   같은 배포 버전의 변경 파일을 적용하고 장치 전용 설정을 보존한다.

4. 보행기를 사용하지 않는 점검 시간에 Pi 모니터와 GUI를 재시작한다.

   ```bash
   sudo systemctl restart walker-safety.service
   systemctl status walker-safety.service --no-pager
   ```

   모니터 재시작 동안 감시가 일시 중단된다. GUI는 실제 실행 방식에 맞춰 닫았다가 다시 연다.
   GUI가 데스크톱 자동 실행이면 앱을 다시 열고, `walker-ui.service` 방식으로 실제 실행 중이면
   해당 서비스를 재시작한다. 두 방식으로 중복 실행하지 않는다. 새 Discord 알림 시험은
   이 업데이트에 포함되지 않으며, 모의 시험 결과를 실제 보호자 수신 증거로 사용하지 않는다.

5. 장애물 수신과 연결 끊김/복구 표시를 확인한다. 현장 확인 전 SOS 버튼을 시험 삼아 누르면
   실제 사고 알림이 전송될 수 있다. 별도로 합의한 시험 채널·절차에서 확인한다.

## 문제 발생 시

미리 기록한 코드 버전/백업으로 이번 변경 파일을 복구하고 Pi 모니터·GUI만 재시작한다.
네트워크 프로필, 비밀 설정, `config_local.py`는 되돌릴 대상이 아니다.
기존 유선 통신도 안 된다면 [유선 LAN 매뉴얼](../../라즈베리파이_젯슨_유선랜_전환_매뉴얼.md)의
주소·경로·9100/9103 수신 점검 순서를 따른다.
