# Jetson ROS 2 LiDAR 브리지

권장 환경은 JetPack 6.2.1(Ubuntu 22.04 기반)과 ROS 2 Humble입니다.

## 빌드

```bash
mkdir -p ~/walker_ws/src
cp -a /path/to/capstone_code/jetson ~/walker_ws/src/walker_lidar
cd ~/walker_ws
rosdep install --from-paths src -y --ignore-src
colcon build --symlink-install
source install/setup.bash
```

`package.xml`, `setup.py`, `setup.cfg`, 리소스 마커와 launch 설치 설정이 포함돼 있습니다.

## 실행 전

벤더 드라이버를 설치하고 토픽을 확인합니다.

```bash
ros2 topic list
ros2 topic info /lidar_left/scan
ros2 topic hz /lidar_left/scan
```

실제 이름과 형식에 맞춰 launch의 좌·우 토픽, `msg_type`(`LaserScan` 또는 `PointCloud2`), Pi IP와 ROI를 수정합니다.

```bash
ros2 launch walker_lidar walker_lidar.launch.py
```

Pi에서는 `LIDAR_SOURCE = "udp"`, 기본 UDP 포트는 9100입니다.

## 실기 검증

- 좌·우 LiDAR USB 포트를 udev로 고정
- 프레임 방향·장착각·거리 단위 확인
- 평지에서 지면 오검출 확인
- 경사·연석·실외 직사광 데이터로 임계값 조정
- Jetson 재부팅과 네트워크 단절 후 Pi 자동 복구 확인

Windows 패키지 구조 테스트는 ROS 2와 실제 LiDAR 호환성을 증명하지 않습니다.
