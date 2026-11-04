# 좌우 LiDAR 3D 표시

<!-- project-status:2026-10-12:start -->
> 갱신: 2026-10-12 · [진행 현황·확인 범위](progress_2026-10-12.md)
> 기본 실행과 배포 상태를 연결했다. 가상 값·표시 데이터·알림 큐 상태를 실제 센서 성능이나 보호자 수신 완료로 판정하지 않는다.
<!-- project-status:2026-10-12:end -->

3D 측정점은 표시 전용이다. 기존 2D 장애물 거리·경고·전도 감시·SOS·단차 판정은 변경하지 않는다.
좌우 센서 좌표를 각각 표시하며, 두 센서를 보행기 좌표로 합치지 않는다.

## 화면

각 LiDAR 카드의 기본 화면은 정면 3D로 센서에서 전방을 본다.
현재 대시보드에서는 시점·2D/3D 선택 줄과 하단 거리 판정 행을 숨겨 점군 표시를 넓혔다.
`화면 확대`에서 1cm·5cm·10cm를 선택한다. 단위는 한 칸의 실제 거리이며 기본값은 10cm다.
한 칸의 화면 길이를 유지하고 선택에 맞게 측정점의 배율도 바꾼다. 데이터와 거리 색상표는 유지한다.
독립 카드 미리보기에는 기존 2D/3D 및 시점·거리 표시를 유지한다.
네 시점 모두 센서에서 측정점까지의 3차원 거리 색이다. 10cm 파랑, 20cm 청록,
35cm 초록, 60cm 노랑, 1m 주황, 2m 분홍으로 고정 보간한다. 색은 위험 등급이 아니다.
점 지름은 2px이며 3축 화살표와 센서 모형은 표시하지 않는다.
고정된 센서 공간 범위로 투영하므로 점군 변화로 배율·중심·10cm 눈금이 변하지 않는다.
창 크기나 시점을 직접 바꾸면 배율은 다시 계산한다.
좌표는 센서의 전방·좌측·상방이며, 보행기 자세나 중력 기준으로 보정하지 않았다.
따라서 센서의 실제 움직임이나 측정 잡음을 제거한 지도 고정 화면은 아니다.
가상의 바닥면은 그리지 않는다. 바닥은 실제 측정점이 있는 곳만 표시한다.
얇은 격자는 화면 평면의 10cm 투영 눈금이며 측정된 바닥이나 면이 아니다.
PC USB 및 Jetson→Pi는 최대 9,600 유효 점을 사용하며 기본은 10cm 확대다. 시점·점군 선택 버튼 줄은 숨겼다.
그림 위의 `화면 N/M점`은 화면 안에 그린 점 수와 선택된 점 수이며 점이 겹쳐 보일 수 있다.

기본 수신 주소는 로컬 시험용 `127.0.0.1`이다. 실기에서는 `config_local.py`의
`UDP_PREVIEW_BIND` 또는 `WALKER_PREVIEW_BIND`에 Pi의 현재 유선 IPv4를 지정한다.
전체 인터페이스 `0.0.0.0`은 거절한다. OS 고정 IP를 변경하는 설정은 아니다.

센서별 새 프레임이 0.5초 이상 없으면 이전 점을 지우고 `3D 수신 중단`을 표시한다.
한 번도 수신하지 않았으면 `3D 데이터 없음`, 정상적인 빈 프레임은 `유효 측정점 없음`이다.
3D 수신 포트 충돌은 해당 그림만 비활성화하며 대시보드의 나머지 기능을 유지한다.

## 데이터와 좌표 근거

```text
D2 /scan    -> 기존 lidar_bridge_node -> UDP 9100 -> safety_monitor -> UI 상태
D2 /scan_3D -> 새 lidar_preview_node  -> UDP 9103 -----------------> UI 3D 표시
```

새 노드는 별도 ROS 프로세스이며 BEST_EFFORT, KEEP_LAST depth 1로 최신 점군만 받는다.
센서별 최대 10Hz로 전송하며, 입력 중단 시 오래된 프레임을 재전송하지 않는다.
기본 토픽은 `/cygbot_left/scan_3D`, `/cygbot_right/scan_3D`이고 타입은 PointCloud2다.
런치 인자로 토픽 이름·전송 대상·포트·좌표 프로필을 변경할 수 있다.

제조사 `d2_node.cpp`에서 `scan_3D`가 PointCloud2임을 확인했다.
`mapping_point_cloud.cpp`와 `distortion_table.cpp`는 픽셀 좌표를 반전하고
광축을 X로 배치하며 MM2M을 적용한다. 기본 `cyglidar_d2` 프로필은 이미
X=전방, Y=좌측, Z=상방, 단위 m인 입력을 그대로 사용한다.
다른 드라이버의 광학 좌표에는 명시적으로 `ros_optical`을 선택할 수 있으며,
이 경우 `(전방, 좌측, 상방)=(원본 Z, -원본 X, -원본 Y)`로 변환한다.

확인한 제조사 소스(main, 2026-10-07):

- https://github.com/CygLiDAR-ROS/cyglidar_d2/blob/main/d2_ros2/src/d2_node.cpp
- https://github.com/CygLiDAR-ROS/cyglidar_d2/blob/main/sdk/src/mapping_point_cloud.cpp
- https://github.com/CygLiDAR-ROS/cyglidar_d2/blob/main/sdk/src/distortion_table.cpp

실기에서는 실제 드라이버 버전·토픽·좌표 방향을 다시 확인해야 한다.
장착 높이와 기울기를 추측해 넣지 않는다.

## 전용 UDP 형식 (v2, 9,600점)

안전 상태와 분리된 UDP 9103을 사용한다. GUI 환경변수 `WALKER_PREVIEW_PORT`와
Jetson `preview_port`는 같은 값이어야 한다. 기존 안전 거리 UDP 9100은 유지한다.

- 새 송신기는 프레임당 최대 9,600 유효점을 보내며 각도 구간 축약을 하지 않는다.
- 실제 3차원 거리 0.05~2.0m, X>0인 유한값만 남긴다. 바닥 높이 필터는 없다.
  오류·범위 밖 측정값 때문에 실제 점 수는 9,600보다 적을 수 있다.
  ROS float32 좌표의 경계 반올림 오차에는 0.000001m 여유만 둔다.
- 헤더는 little-endian `<4sBBBBQIQHHHHI`, 40바이트다.
  순서는 magic=`W3DP`, version=2, side(0=left/1=right), flags, reserved=0,
  session(uint64), sequence(uint32), capture_ns(uint64), chunk_points(uint16),
  chunk_index(uint16), chunk_count(uint16), total_points(uint16), payload_crc32(uint32)다.
- flags bit 0=빈 프레임, bit 1=모의 데이터이며 나머지는 0이다.
- 점은 little-endian `<hhh`, 센서 기준 XYZ의 signed int16 밀리미터다.
  1mm 저장 간격은 센서 정확도를 뜻하지 않는다. 수신 범위 검증은 반올림 여유 1mm를 허용한다.
- 패킷당 최대 192점, 최대 1,192바이트다. 9,600점은 50개 패킷으로 나뉜다.
  수신 패킷 제한은 1,200바이트다. 빈 프레임도 1개 패킷으로 보낸다.
- 좌우 각각 조립 중 프레임 1개만 유지한다. 순서가 바뀐 패킷은 조립하며,
  더 최신 프레임이 오면 이전 미완성 프레임을 버린다. 첫 패킷부터 0.25초가 지나면 폐기한다.
  중복 패킷은 이 시간을 늘리지 않는다.
- 전체 패킷과 일치하는 메타데이터 및 전체 XYZ 페이로드 CRC32가 확인돼야 표시 프레임을 갱신한다.
  누락·손상·상충 패킷은 부분 점군으로 표시하지 않는다. 최근 폐기 프레임 ID 64개를 기억한다.
- 완성 프레임 수신 후 0.5초가 지나면 이전 점군을 지운다. 미완성 패킷은 신선도를 갱신하지 않는다.
  중복·역순 프레임과 최근 종료 세션 64개의 지연 패킷도 신선도를 갱신하지 않는다.

수신 monotonic clock으로 신선도를 판단한다. ROS header stamp는 진단 값이며 두 장치의
시계 동기화는 전제가 아니다. 각 센서 최대 10Hz로 최신 프레임만 보내므로 모든 시간 프레임을
저장하거나 재생하는 기능은 아니다. 좌우 모두 9,600점·10Hz이면 UDP 페이로드 약 1.19MB/s
(약 9.54Mbps, 네트워크 헤더 제외)다. 실제 표시 속도는 Pi 부하와 네트워크 상태에 따라 달라진다.

구형 v1 수신도 유지한다. v1 헤더는 `<4sBBBBQIQH` 30바이트, 최대 192점·1,182바이트다.
구형 송신기의 16×12 각도 구간 축약은 v1에만 해당한다. **Pi 수신기를 먼저 업데이트한 뒤
Jetson 송신기를 업데이트한다.** 구형 Pi 수신기는 v2를 표시하지 못한다.

## PC 미리보기와 검증

`capstone_code` 폴더에서 실행한다. tkinter·numpy와 고밀도 표시용 Pillow를 사용한다.
아래 미리보기는 센서·네트워크·알림·명령 전송을 시작하지 않는다.

```powershell
python tools/preview_lidar_3d.py
python tools/preview_lidar_3d.py --dashboard --size 1024x600
python tools/preview_lidar_3d.py --dashboard --size 1024x600 --reported
```

카드 미리보기 버튼으로 평평한 바닥, 올라가는 턱, 내려가는 단차, 벽,
빈 프레임, 오른쪽 중단, 3D 없음 상태를 볼 수 있다. 모의 턱은 20cm다.
전체 대시보드 기본 예시는 왼쪽 올라가는 턱, 오른쪽 내려가는 단차다.

```powershell
python tests/run_all.py
python tools/preview_lidar_3d.py --dashboard --size 1024x600 --check-layout
python tools/preview_lidar_3d.py --dashboard --size 1024x600 --reported --check-layout
python tools/preview_lidar_3d.py --dashboard --size 1280x720 --check-layout
```

레이아웃 검사는 거리·시점·전환 버튼·SOS·IMU 값·GPS 좌표와 사고 후 감시 재개 버튼이
부모 영역에 완전히 들어오는지 확인하고 창을 닫는다. 실제 터치 검사를 대신하지 않는다.

## Pi / Jetson 적용

장치별 적용 순서와 롤백은 [GUI·채널·9,600점 배포](deploy_gui_channels.md)를 먼저 따른다.

Pi에는 `ui.py`, `config.py`, `lidar_preview.py`, `lidar_preview_view.py`와
`jetson/walker_preview/` 전체가 필요하다. 기존 `config_local.py`는 유지한다.
GUI만 재시작하면 되며, 이번 3D 표시 추가 때문에 안전 감시 프로세스를 재시작할 필요는 없다.
포트를 변경하면 Pi 설정과 Jetson의 `preview_port`를 맞춘다.

Jetson의 ROS 작업공간에는 새 노드·`walker_preview/`·갱신된 setup.py·런치 파일을 반영한다.
기존 거리 브리지는 변경하지 않는다.

```bash
cd ~/walker_bridge_ws
colcon build --symlink-install --packages-select walker_lidar
source install/setup.bash
ros2 pkg executables walker_lidar
ros2 topic info /cygbot_left/scan_3D
ros2 topic info /cygbot_right/scan_3D
```

출력에서 `lidar_preview_node` 실행 파일과 두 토픽의 PointCloud2 타입을 확인한다.
기존 드라이버·거리 브리지가 실행 중이면 아래 새 노드만 추가한다.
`<Pi_IP>`는 Pi의 실제 주소로 바꿔야 한다.

```bash
ros2 run walker_lidar lidar_preview_node --ros-args -p pi_host:=<Pi_IP>
```

전체 런치를 새로 시작하는 경우 `enable_3d_preview:=true`가 기본이다.
이미 전체 런치가 실행 중이면 두 번째 전체 런치를 띄우지 않는다.
표시 노드만 중단하거나 `enable_3d_preview:=false`로 기존 화면 경로를 유지할 수 있다.

## 실제 센서 확인 순서

1. RViz 원본과 GUI의 전방·좌측·상방 방향을 비교한다.
2. 실제 바닥이 센서 시야에 들어오는지 확인한다. 2m는 센서로부터의 3D 거리다.
3. 평평한 바닥과 높이를 알고 있는 턱을 정지 상태에서 비교한다.
4. 한쪽 센서 중단, 표시 노드 중단·재시작, 네트워크 단절·복구를 확인한다.
5. Pi에서 1024×600 터치 조작과 30분 연속 실행을 확인하고,
   표시를 켜거나 꺼도 기존 장애물 경고·전도 감시가 유지되는지 기록한다.

확대 화면에서는 화면 경계 밖 점이 잘리며 같은 픽셀의 점은 겹친다. 점이 없는 곳은 미측정 영역이다.
바닥 보정이나 단차 자동 판정 개선은 이번 범위에 포함하지 않는다.
단차가 화면에 보이지 않는 것을 통행이 안전하다는 근거로 사용하면 안 된다.
PC 검증과 실제 Pi / Jetson 센서·터치·30분 검증은 별도로 기록한다.

## 이번 게시본 PC 검증 (2026-11-04)

- 게시본 기능 테스트 146개와 Jetson 패키지 구조·설치 검사 4개 통과.
- 좌우 각각 9,600점 UDP 루프백 왕복, 순서 변경·누락·중복·손상·시간초과·세션 재시작 검사 통과.
- ROS float32의 5cm·2m 경계에서 각각 9,600점이 유지되는지 확인.
- 1024×600 정상·사고 후 조치 화면, 1280×720 정상 화면 배치 검사 통과.
- 실제 Pi/Jetson 배포·터치·장시간 성능은 미확인이다.

## PC 검증 기록 (2026-10-07)

- 기능 테스트 99개 통과: 기존 안전 기능과 3D 패킷·샘플링·수신·화면 제거 검사 포함.
- Jetson 패키지 검사 4개 통과: 새 실행 파일·공유 모듈 설치와 독립 런치 경로 확인.
- 실제 Tk 창의 1024×600 정상·사고 확정 화면과 1280×720 정상 화면 배치 검사 통과.
- 실제 창에서 좌우 3D 예시와 사고 후 감시 재개 버튼을 확인했다.
- 실제 Pi / Jetson 배포, 센서 방향·바닥 측정, 터치, 30분 운용은 아직 확인하지 않았다.
