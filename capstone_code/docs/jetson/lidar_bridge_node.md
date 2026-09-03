# `jetson/lidar_bridge_node.py`

> **한 줄:** Jetson의 ROS 2 노드. 벤더 드라이버 토픽을 구독해 거리·단차만 뽑아 Pi로 UDP 전송.
> **계층:** Jetson 측 (ROS 2) | **의존:** `rclpy`, `sensor_msgs`, `numpy`

---

## 왜 이렇게 하는가

1. **프레임 파싱은 벤더 드라이버에게 맡긴다.** 직접 파싱하면 payload 오프셋·비트폭을
   추측하게 되고, 틀려도 '그럴듯한 숫자'가 나와 틀린 줄 모른다.
2. **Pi로 넘기는 데이터는 float 2~3개뿐**이므로 DDS를 Pi까지 끌고 갈 이유가 없다.
3. **이 노드가 죽어도 Pi의 전도 감지는 계속 동작한다.**

## 실행

```bash
ros2 launch walker_lidar walker_lidar.launch.py
# 또는 브리지만 단독으로
python3 lidar_bridge_node.py --ros-args -p pi_host:=192.168.10.2
```

## 파라미터

| 이름 | 기본값 | 설명 |
| :--- | :--- | :--- |
| `pi_host` / `pi_port` | 192.168.10.2 / 9100 | UDP 수신처 |
| `send_hz` | 20.0 | 송신 주기 |
| `left_topic` / `right_topic` | `/cygbot_*/scan` | **`ros2 topic list` 로 확인 후 수정** |
| `msg_type` | `LaserScan` | `LaserScan` \| `PointCloud2` |
| `roi_fov_deg` | 80.0 | 정면 ±40° |
| `roi_z_min` / `roi_z_max` | −0.30 / 1.20 | 바닥·머리 위 제거 |
| `min_valid_m` / `max_valid_m` | 0.10 / 8.00 | 유효 범위 |
| `percentile` | 5.0 | 최솟값 대신 하위 N퍼센타일 |
| `curb_drop_m` / `curb_rise_m` / `curb_warn_m` | 0.05 / 0.04 / 1.20 | 단차 감지 |

## 단차(턱) 감지

기획 배경의 **"턱 걸림"** 에 대응한다.
전방을 수평으로 보는 LiDAR는 바닥 단차를 볼 수 없다.

```
센서를 아래로 10~20° 틸트
  → 가까운 구간(< 0.6 m)의 바닥 높이를 기준 평면으로 삼고
  → 먼 구간이 그 평면에서 얼마나 벗어나는지를 본다

평면보다 낮다 → 내려가는 턱 (drop) — 가장 위험
평면보다 높다 → 올라가는 턱 (rise) — 걸려 넘어진다
```

**제약:**
- 센서가 아래로 틸트되어 있고 바닥이 화각에 충분히 들어와야 동작한다
- **2D `LaserScan` 에는 높이(z) 정보가 없어 단차를 판별할 수 없다.** 3D 모드 필수
- 지면이 젖어 있거나 검은 아스팔트면 ToF 반사가 약해 점이 사라진다.
  **'점이 없는 것'과 '낭떠러지'를 구분하지 못한다** — 한계로 명시할 것

## UDP 패킷

```json
{"v": 1, "seq": 1234, "t": 1755766000.123,
 "left": {"d": 1.42, "ok": true}, "right": {"d": null, "ok": true},
 "curb_m": 0.9, "curb_type": "drop"}
```

**데이터가 없어도 매 주기 보낸다** — 패킷 자체가 하트비트다.

## 고칠 때 주의

- ⚠ **토픽 이름과 메시지 타입은 벤더 드라이버 버전에 따라 다르다.**
  `ros2 topic info <topic>` 으로 확인해 파라미터로 넘길 것.
- ⚠ QoS는 `BEST_EFFORT` / `depth=1` 이다. 점군은 최신 프레임만 의미가 있다.
  드라이버가 `RELIABLE` 로 발행해도 매칭된다.
- ⚠ `sendto()` 의 `OSError` 를 삼킨다. 네트워크 일시 장애로 노드가 죽으면 안 된다.
- 패킷에 필드를 추가할 때는 수신 측(`sensors/lidar_udp.py`)이 `.get()` 으로 읽는지 확인할 것.
  그래야 버전이 섞여도 동작한다.

## 관련

- 설치·udev·네트워크: [`../../jetson/README.md`](../../jetson/README.md)
- launch 파일: `jetson/launch/walker_lidar.launch.py` (벤더 드라이버 2개 + 브리지, `respawn=True`)
