# Pi·Jetson GUI / 채널 / 9,600점 업데이트

2026-11-04. 대상 저장소는 `suhwan3929-lab/capstone`, 브랜치는 `main`이다.
이 문서는 적용 절차이며 실제 두 보드에서 실행·검증한 기록은 아니다.

## 변경 내용과 적용 순서

Pi의 1024×600 가로 GUI에 정면 3D, 작은 점, 고정 중심, 확대 눈금 1/5/10cm와 큰 시계를 적용한다.
Jetson은 좌 채널 0·우 채널 1로 시작하며, 프레임당 최대 9,600 유효점을 보낸다.
원본 160×60에서 0.05~2.0m의 유효점만 사용하므로 실제 표시 점 수는 더 적을 수 있다.
전송은 센서별 최대 10Hz의 최신 프레임이다. 확대 화면 밖 점은 잘릴 수 있고 점이 겹칠 수 있다.

**Pi 수신기 먼저, Jetson 송신기 다음** 순서다. 새 Pi는 구형 192점 v1도 받지만 구형 Pi는 새 v2를 받지 못한다.
안전 거리 UDP 9100과 3D UDP 9103은 분리돼 있다. 고정 IP·Netplan·NetworkManager·로컬 센서 설정은 변경하지 않는다.
일반 pull 뒤 랜선 고정 연결을 다시 설정할 필요는 없다. 기존 자동 실행 설치기를 재설치할 필요도 없다.
단, 실제 실행 폴더가 Git 폴더와 다르면 pull만으로 실행 코드가 바뀌지 않으므로 아래 경로 확인이 필요하다.

보행기를 사용하지 않는 점검 시간에 진행한다. Pi 안전 감시나 Jetson 런치 재시작 동안 해당 감시 입력이 일시 중단된다.

## 1. 두 보드에서 경로와 이전 버전 확인

Pi에서:

```bash
systemctl show walker-safety.service -p WorkingDirectory -p ExecStart
systemctl cat walker-safety.service
```

Jetson에서:

```bash
systemctl cat walker-lidar.service
sed -n '1,180p' /usr/local/libexec/walker/start-jetson.sh
readlink -f ~/walker_bridge_ws/src/walker_lidar
```

서비스가 없다면 현재 수동 실행 명령과 코드 폴더를 확인한다. 실제 서비스/런처가 사용하는 경로를 기준으로 진행한다.
Pi GUI는 바탕화면 자동 실행 또는 기존 `walker-ui.service` 중 현재 사용 중인 방식을 유지한다.
두 방식을 중복 실행하지 않는다. `config_local.py`나 비밀 설정을 화면에 출력하지 않는다.

각 보드의 실제 Git 저장소 루트에서 아래를 실행한다. 경로는 장치마다 다르다.

```bash
git rev-parse --show-toplevel
git remote get-url origin
git status --short
git branch -vv
git rev-parse HEAD > ~/walker-before-gui-update.txt
```

예상 원격은 `https://github.com/suhwan3929-lab/capstone.git`이다.
변경 파일이 있으면 먼저 별도 보관·비교하고 업데이트를 멈춘다. `reset --hard`나 `clean`으로 지우지 않는다.
기존 `config_local.py`, 서비스 시작 스크립트와 현재 `pi_host`도 개인 백업 위치에 보관한다.
ZIP/파일 복사 설치는 Git pull 대상이 아니므로 새 저장소의 파일을 실제 실행 경로에 별도 반영해야 한다.

## 2. Pi 코드와 GUI 먼저 적용

실제 Git 저장소 루트에서:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git rev-parse HEAD
```

fast-forward가 거절되면 이력 차이를 확인하고 중단한다. 강제 초기화하지 않는다.
실제 배포 경로가 저장소 밖이면 같은 버전의 `capstone_code` 변경 파일을 반영하고 로컬 설정은 보존한다.
GUI는 `ui.py`, `lidar_preview.py`, `lidar_preview_view.py`, `jetson/walker_preview/`가 함께 필요하다.
이번 게시본의 상태 표시 변경까지 적용하려면 `schema.py`, `states.py`, `status_link.py`,
`notifier.py`, `safety_monitor.py`, `sensors/lidar_udp.py` 등도 같은 버전으로 맞춘다.

현재 GUI가 쓰는 Python 환경에서 Pillow를 확인한다. 아래 경로는 기존 설치 예시이며 실제 ExecStart의 Python을 사용한다.

```bash
/opt/walker/venv/bin/python -c "import numpy, PIL, serial, requests; print('GUI dependencies OK')"
# PIL만 없을 때 같은 환경에 설치:
/opt/walker/venv/bin/python -m pip install 'pillow>=9.2'
```

다른 센서 패키지와 Python 환경을 통째로 다시 설치하지 않는다.
안전 감시 관련 파일도 갱신했다면 다음을 실행한다.

```bash
sudo systemctl restart walker-safety.service
systemctl status walker-safety.service --no-pager
```

GUI를 실제 사용 중인 방식으로 한 번만 재시작한다. 바탕화면 자동 실행 방식은 창을 닫고 런처의 재시작을 기다린다.
기존 `walker-ui.service`를 쓰는 경우에만 그 서비스를 재시작한다. 수동 실행 구성은 기존 명령으로 다시 실행한다.
Jetson을 업데이트하기 전까지는 구형 최대 192점 수신 화면이 나올 수 있다.

## 3. Jetson 소스 반영·재빌드

Jetson도 실제 Git 루트에서 2절의 fetch/switch/pull을 수행한다.
`~/walker_bridge_ws/src/walker_lidar`가 저장소 `capstone_code/jetson`을 직접 가리키는지 확인한다.
기존 별도 복사본이면 이를 먼저 백업하고 최신 패키지 내용을 반영한다. 아래 `repo`는 실제 Git 루트에서 설정한다.

```bash
repo="$(git rev-parse --show-toplevel)"
pkg="$HOME/walker_bridge_ws/src/walker_lidar"
readlink -f "$pkg"
# 별도 복사본일 때만, 기존 폴더를 보관한 다음 반영:
cp -a "$pkg" "$HOME/walker_lidar-before-gui-$(date +%Y%m%d-%H%M%S)"
cp -a "$repo/capstone_code/jetson/." "$pkg/"
```

위 복사는 패키지 폴더가 실제로 존재하는 경우다. 이미 최신 저장소를 직접 가리키면 복사를 생략한다.
현재 수동 ROS launch를 Ctrl+C로 종료하거나, 서비스 구성은 `sudo systemctl stop walker-lidar.service`로 중지한다.
다른 터미널에서 같은 USB 센서를 읽는 드라이버를 남기지 않는다. 제조사 드라이버·OpenCV 재설치는 필요 없다.

```bash
source /opt/ros/humble/setup.bash
source ~/d2_ws/install/setup.bash
cd ~/walker_bridge_ws
colcon build --symlink-install --packages-select walker_lidar
source install/setup.bash
ros2 pkg executables walker_lidar
```

출력에 `lidar_bridge_node`, `lidar_preview_node`가 있어야 한다. 빌드가 실패하면 재시작하지 말고 오류를 확인한다.
서비스 구성은 기존 Pi 주소를 유지한 시작 스크립트인지 확인하고 재시작한다.

```bash
sudo systemctl restart walker-lidar.service
systemctl status walker-lidar.service --no-pager
journalctl -u walker-lidar.service -n 100 --no-pager
```

수동 구성은 `PI_IP`를 현재 Pi 유선 주소로 바꾸고 기존 드라이버 종료 후 다음 하나만 실행한다.

```bash
ros2 launch walker_lidar walker_lidar.launch.py start_drivers:=true pi_host:=PI_IP
```

`enable_3d_preview:=true`가 기본이다. **`start_drivers:=false`는 실행 중인 드라이버의 채널을 바꾸지 않는다.**
채널 0/1을 적용하려면 새 런치로 두 드라이버를 다시 시작해야 한다. 채널 파라미터가 런타임 변경을 지원한다고 추측하지 않는다.
서비스가 다른 제조사 런치를 쓰면 그 실제 실행 경로에도 동일한 채널을 반영해야 한다.

## 4. 현장 확인과 예상 결과

1. Jetson에서 두 PointCloud2 토픽을 확인한다.
   `ros2 topic info /cygbot_left/scan_3D`, `ros2 topic info /cygbot_right/scan_3D`.
2. `ros2 param get /cygbot_left/cygbot_left frequency_channel`은 0,
   `/cygbot_right/cygbot_right`는 1이어야 한다. 실제 노드명이 다르면 `ros2 node list`로 확인한다.
   제조사 시작 로그의 `FREQUENCY CH.`도 좌우 0/1인지 확인한다.
   이는 요청 설정 확인이며 광학 주파수 계측이나 장치 채널 읽기 응답은 아니다.
3. Pi에 좌우 `3D 수신 중`, 확대 1/5/10cm와 큰 시계가 나타나는지 확인한다.
   그림의 `화면 N/M점`에서 M은 수신 프레임의 유효점 수로 최대 9,600이다.
   항상 9,600이 나오는 것은 아니다. 화면 밖 점·같은 픽셀에 겹친 점 때문에 N과 모양도 달라진다.
4. 한쪽 센서 중단은 해당 그림만, 3D 노드 중단은 양쪽 그림을 0.5초 뒤 지워야 한다.
   복구 시 새 완성 프레임으로 다시 표시해야 한다. UDP 누락 시 부분 프레임을 그리지 않아 일시 정지가 보일 수 있다.
5. 기존 거리 경고·전도 상태, 상세 화면을 확인한다. SOS는 합의된 신고 시험 절차에서만 별도로 시험한다.
   1024×600 터치와 30분 연속 구동, GUI 부하와 네트워크 손실도 실제 Pi에서 확인한다.

로컬 Windows 시험은 좌우 9,600점 UDP 왕복, 손상·누락·순서·세션·시간초과를 확인했다.
사용자는 USB 채널 0/1 적용 후 간섭 감소를 확인했다고 보고했다.
실제 Pi/Jetson 적용, 현장 성능·정확도·장시간 동작은 이 문서 작성 시 확인하지 않았다.

## 5. 실패 시 롤백

먼저 해당 GUI/ROS 런치를 중지하고 적용 전 커밋과 백업 패키지 경로를 확인한다.
실제 Git 루트가 깨끗한 상태에서만 다음처럼 이전 버전을 별도 체크아웃한다.

```bash
old_revision="$(cat ~/walker-before-gui-update.txt)"
git switch --detach "$old_revision"
```

Pi는 같은 이전 버전의 실행 파일을 복원하고 GUI와 필요한 감시 서비스를 재시작한다.
Jetson은 저장소를 직접 참조하면 이전 코드로 다시 빌드하고, 별도 복사본이면 보관한 패키지 전체를 복원한 뒤
3절처럼 재빌드·재시작한다. 새 파일이 섞이지 않도록 현재 패키지를 다른 이름으로 보관하고 백업을 원래 위치에 복원한다.
기존 IP·장치 설정·비밀 설정은 바꾸지 않는다. 양쪽을 이전 호환 버전으로 돌린 뒤 수신·경고 상태를 다시 확인한다.
