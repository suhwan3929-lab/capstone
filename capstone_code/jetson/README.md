# Jetson D2 → UDP 브리지

<!-- project-status:2026-10-12:start -->
> 갱신: 2026-10-12 · [진행 현황·확인 범위](../docs/progress_2026-10-12.md)
> 실행·Ubuntu 원격접속·Git 배포의 최신 진행 기록을 연결했다. 기존 날짜별 검토·시험 결과와 아직 미확인인 실기 항목을 구분한다.
<!-- project-status:2026-10-12:end -->

3D 표시 전용 노드 `lidar_preview_node`를 추가했다. 기존 거리 브리지는 2D LaserScan을 유지한다.
프레임당 최대 9,600 유효점을 50개 이하 UDP 패킷으로 보내며 각도 축약을 하지 않는다.
통합 런치는 왼쪽 채널 0, 오른쪽 채널 1을 요청한다.
`start_drivers:=false`는 이미 실행 중인 드라이버 채널을 변경하지 않는다.
배포는 [장치별 업데이트·롤백](../docs/deploy_gui_channels.md)을 따른다.
전용 UDP 9103과 GUI 적용 방법은 [3D 표시 안내](../docs/lidar_3d_preview.md)를 따른다.

Jetson은 ROS 2로 LiDAR 데이터를 처리하고, Pi에는 대표 거리와 축약 윤곽을 UDP 9100으로 보낸다. Pi는 순수 Python으로 수신한다.

## 확인한 구성

- 제조사 저장소: https://github.com/CygLiDAR-ROS/cyglidar_d2
- 제조사 패키지 `cyglidar_d2_ros2`, 실행 파일 `cyglidar_d2_publisher`.
- 제조사 작업 공간 `~/d2_ws`, 우리 브리지 작업 공간 `~/walker_bridge_ws`.
- PL2303 모듈 설치와 두 D2의 RViz 물체 반응은 사용자 확인 완료.
- 시리얼 기반 `/dev/lidar_left`, `/dev/lidar_right` 생성 완료. USB 재연결 후 좌우 유지 검사는 별도 진행한다.

기존 제조사 작업 공간을 유지한다. 브리지 설치 시 제조사 드라이버나 OpenCV를 다시 설치하지 않는다.

## 브리지 설치

PC에서 받은 `walker_lidar_2026-10-05.tar.gz`를 Jetson 홈에 놓은 뒤 실행한다. 아래 경로에 기존 수정본이 있으면 먼저 보관한다.

```bash
source /opt/ros/humble/setup.bash
source ~/d2_ws/install/setup.bash
mkdir -p ~/walker_bridge_ws/src
tar -xzf ~/walker_lidar_2026-10-05.tar.gz -C ~/walker_bridge_ws/src
cd ~/walker_bridge_ws
colcon build --symlink-install --packages-select walker_lidar
source ~/walker_bridge_ws/install/setup.bash
ros2 pkg executables walker_lidar
```

필요한 `numpy`, `rclpy`, `sensor_msgs_py`가 없으면 누락된 패키지부터 확인한다. 추가 설치가 필요할 때는 기존 OpenCV를 변경하지 않는 경로를 사용한다.

```bash
sudo apt-get install --no-upgrade --no-remove -y python3-numpy ros-humble-sensor-msgs-py
```

## Pi 없이 Jetson 내부 전송 시험

현재 두 D2 드라이버를 켜 둔다. **수신 창부터** 시작한다.

```bash
python3 - <<'PY'
import json
import socket

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
    receiver.bind(("127.0.0.1", 9100))
    receiver.settimeout(30)
    for _ in range(10):
        packet = json.loads(receiver.recvfrom(4096)[0])
        parts = []
        for side in ("left", "right"):
            value = packet[side]
            points = value.get("points_xy") or []
            parts.append(f"{side}: ok={value['ok']} distance={value['d']}m points={len(points)}")
        print(f"seq={packet['seq']} " + " | ".join(parts))
PY
```

다른 Jetson 터미널에서 브리지를 시작한다. `start_drivers:=false`는 이미 실행 중인 드라이버를 유지하는 설정이다.

```bash
source /opt/ros/humble/setup.bash
source ~/d2_ws/install/setup.bash
source ~/walker_bridge_ws/install/setup.bash
ros2 launch walker_lidar walker_lidar.launch.py start_drivers:=false pi_host:=127.0.0.1
```

좌우 `ok=True`는 센서 메시지가 최근 0.5초 안에 들어왔다는 뜻이다. `distance=None`이면 정면 ±40°, 0.1~8m 관심영역 안에 유효 거리가 없는 상태다. 각 센서 정면에 물체를 두어 좌우 거리와 표시용 점이 각각 나오는지 확인한다. 패킷 수신만으로 양쪽 센서 건강을 판정하지 않는다.

## Pi 통합

Pi를 켜고 Jetson과 같은 네트워크에 연결한 뒤 `hostname -I`로 Pi의 현재 주소를 확인한다. 공유기를 이용한 개발 시험은 보드 간 Ethernet 직결 전에 진행할 수 있다.

브리지를 중지하고 `pi_host`를 Pi의 실제 주소로 바꿔 다시 실행한다. 아래 `<Pi_IP>`는 치환해야 한다.

```bash
ros2 launch walker_lidar walker_lidar.launch.py start_drivers:=false pi_host:=<Pi_IP>
```

Pi의 `/opt/walker/capstone_code/config_local.py`에서 다음 값을 설정한다.

```python
LIDAR_SOURCE = "udp"
```

Pi 수신은 UDP 9100이다. GUI에서 링크뿐 아니라 좌우 센서 상태·거리·윤곽이 각각 갱신되는지 확인한다. GUI와 별도 UDP 수신기를 같은 포트에 함께 실행하지 않는다.

두 D2 드라이버가 모두 종료된 뒤에는 통합 실행 파일 하나로 드라이버와 브리지를 시작할 수 있다.

```bash
ros2 launch walker_lidar walker_lidar.launch.py pi_host:=<Pi_IP>
```

## 범위와 다음 검증

현재 브리지는 `/cygbot_left/scan`, `/cygbot_right/scan`의 **2D LaserScan**을 사용한다. 제조사 드라이버는 `run_mode=2`로 2D·3D를 함께 발행한다. `baud_rate=0`은 제조사 설정 인덱스로 3,000,000bps를 뜻한다.

3D 점이 RViz에 보이는 것과 단차 판정이 검증된 것은 별개다. 현재 2D 경로에서는 단차 정보가 생성되지 않는다. 3D 경로의 축 방향, 장착 위치·기울기, 바닥 기준과 판정 정확도를 검증한 뒤 전환해야 한다. 현재 실행 파일에는 미확인 장착 변환을 추가하지 않았다.

추가 검증: 알려진 거리에서의 좌우 거리 비교, USB 재연결 좌우 유지, 한 센서 분리 시 해당 측 오류 표시, 브리지·네트워크 단절과 복구, 장시간 수신 및 최종 유선망 시험. 단독 LiDAR 시험과 Pi 통합 시험 결과를 나눠 기록한다.
