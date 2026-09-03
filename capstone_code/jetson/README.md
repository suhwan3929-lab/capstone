# Jetson 측 설정 (ROS 2)

Jetson만 ROS 2를 쓰고, Pi는 순수 Python이다. 둘 사이는 UDP로 잇는다.
결정 근거는 `../../코드_리뷰.md` §4 참고.

## 1. 벤더 드라이버 설치

```bash
mkdir -p ~/walker_ws/src && cd ~/walker_ws/src
git clone <Cygbot 공식 ROS 2 드라이버 저장소>
cd ~/walker_ws && rosdep install --from-paths src -y --ignore-src
colcon build --symlink-install
```

**프레임을 직접 파싱하지 말 것.** 벤더 드라이버를 쓰는 가장 큰 이유가
payload 오프셋과 비트폭을 추측하지 않기 위해서다. 직접 파싱하면 틀려도
"그럴듯한 숫자"가 나와서 틀린 줄을 모른다. (`코드_리뷰.md` §1.4)

## 2. 포트 고정 (필수)

USB LiDAR 2대는 부팅 순서에 따라 `/dev/ttyUSB0` ↔ `1` 이 뒤바뀐다.
좌우가 바뀌면 점군이 반대로 합쳐져 디버깅에 며칠을 쓴다.

```bash
udevadm info -a -n /dev/ttyUSB0 | grep -m1 ATTRS{serial}
```

`/etc/udev/rules.d/99-walker.rules`:

```
SUBSYSTEM=="tty", ATTRS{serial}=="<왼쪽 시리얼>",   SYMLINK+="lidar_left"
SUBSYSTEM=="tty", ATTRS{serial}=="<오른쪽 시리얼>", SYMLINK+="lidar_right"
```

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## 3. 토픽 확인

```bash
ros2 topic list
ros2 topic info /cygbot_left/scan
ros2 topic hz /cygbot_left/scan
```

확인한 값을 `launch/walker_lidar.launch.py` 의 `left_topic` / `right_topic` /
`msg_type` 파라미터에 반영한다. (`LaserScan`과 `PointCloud2` 둘 다 지원)

## 4. 실행

```bash
ros2 launch walker_lidar walker_lidar.launch.py
```

브리지만 단독 실행:

```bash
python3 lidar_bridge_node.py --ros-args -p pi_host:=192.168.10.2
```

## 5. Pi 쪽 전환

Pi의 `config_local.py` 에 한 줄만 추가하면 된다.

```python
LIDAR_SOURCE = "udp"
```

`python3 safety_monitor.py` 실행 후 "Jetson 링크 연결됨" 로그를 확인한다.

## 6. 네트워크 체크리스트

- Jetson `eth0` = 192.168.10.1 / Pi = 192.168.10.2 고정
  **Pi 5의 이더넷 인터페이스는 `eth0`이 아니라 `end0`이다.**
  같은 설정 파일을 복사하면 Pi 쪽이 동작하지 않는다. (계획서 리뷰 §2.1)
- Jetson이 인터넷(apt/NTP)에 나가려면 Pi에서 IP forwarding + NAT 필요
- 시각 동기화: Pi를 chrony NTP 서버, Jetson을 클라이언트로
  UDP 신선도 판정은 **수신 측 도착 시각** 기준이라 시계가 어긋나도
  오동작하지는 않는다. 다만 로그 대조를 위해 맞춰두는 편이 좋다.
- 방화벽에서 UDP 9100 허용
