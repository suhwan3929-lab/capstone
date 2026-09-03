"""
Jetson 실행 런치 파일.

벤더 드라이버 2대 + 브리지 노드를 함께 띄운다.
`respawn=True` 가 systemd의 `Restart=always` 와 같은 역할을 한다.

⚠ 아래 package/executable 이름은 설치한 Cygbot ROS 2 패키지에 맞게 수정할 것.
   `ros2 pkg executables | grep -i cyg` 로 확인할 수 있다.
"""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    common = dict(package="cygbot_ros2", executable="cygbot_node",
                  respawn=True, respawn_delay=2.0, output="screen")

    return LaunchDescription([
        Node(**common, name="cygbot_left", namespace="cygbot_left",
             parameters=[{"port": "/dev/lidar_left", "baudrate": 3000000}]),
        Node(**common, name="cygbot_right", namespace="cygbot_right",
             parameters=[{"port": "/dev/lidar_right", "baudrate": 3000000}]),
        Node(
            package="walker_lidar", executable="lidar_bridge_node",
            name="lidar_bridge", output="screen",
            respawn=True, respawn_delay=2.0,
            parameters=[{
                "pi_host": "192.168.10.2",
                "pi_port": 9100,
                "send_hz": 20.0,
                "left_topic": "/cygbot_left/scan",
                "right_topic": "/cygbot_right/scan",
                "msg_type": "LaserScan",
                "roi_fov_deg": 80.0,
            }],
        ),
    ])
