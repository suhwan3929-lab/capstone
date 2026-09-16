# `jetson/lidar_bridge_node.py`

벤더 ROS 2 토픽에서 좌·우 장애물과 단차 후보를 추려 Pi UDP 9100으로 보냅니다. `LaserScan`과 `PointCloud2`를 지원하며 QoS는 최신 프레임 우선 `BEST_EFFORT`, depth 1입니다.

```bash
ros2 launch walker_lidar walker_lidar.launch.py
```

주요 파라미터는 Pi 주소, 좌·우 토픽, 메시지 형식, FOV, 거리·z ROI, 단차 임계값입니다. 실제 토픽은 `ros2 topic list/info/hz`로 확인합니다.

패킷 예:

```json
{"v":1,"session":"boot-id","seq":123,"t":1755766000.1,
 "left":{"d":1.42,"ok":true},"right":{"d":null,"ok":false},
 "curb_m":0.9,"curb_type":"drop"}
```

`session`은 노드 시작마다 바뀌며 Pi가 재시작과 이전 세션 지연 패킷을 구분합니다. 데이터가 없어도 하트비트 패킷을 보냅니다.

주의:

- 2D `LaserScan`에는 높이가 없어 단차 검출을 할 수 없습니다.
- 현재 PointCloud2 장애물 필터는 절대 z 범위, 단차는 가까운 점의 중앙값을 사용합니다.
- 장착 기울기와 경사면에서는 지면을 잘못 분류할 수 있으므로 실제 rosbag으로 지면 평면 모델을 검증해야 합니다.
- 검은색·젖은 노면과 직사광에서 점 소실 여부를 측정해야 합니다.

설치와 빌드는 [`../../jetson/README.md`](../../jetson/README.md)를 봅니다.
