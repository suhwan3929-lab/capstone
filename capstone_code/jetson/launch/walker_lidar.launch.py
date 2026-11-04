"""
Jetson 실행 런치 파일.

검증한 CygLiDAR D2 드라이버 2대와 UDP 브리지를 함께 띄운다.
기존 드라이버를 유지할 때는 start_drivers:=false로 브리지만 실행한다.
pi_host는 Pi의 현재 주소로 지정한다. 기본값은 최종 유선망 계획 주소다.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    common = dict(package="cyglidar_d2_ros2", executable="cyglidar_d2_publisher",
                  condition=IfCondition(LaunchConfiguration("start_drivers")),
                  respawn=True, respawn_delay=2.0, output="screen")

    return LaunchDescription([
        DeclareLaunchArgument("pi_host", default_value="192.168.10.2",
                              description="Pi UDP receiver address"),
        DeclareLaunchArgument("start_drivers", default_value="true",
                              description="Set false when D2 publishers already run"),
        DeclareLaunchArgument("enable_3d_preview", default_value="true",
                              description="Independent display-only 3D process"),
        DeclareLaunchArgument("preview_port", default_value="9103"),
        DeclareLaunchArgument("left_cloud_topic", default_value="/cygbot_left/scan_3D"),
        DeclareLaunchArgument("right_cloud_topic", default_value="/cygbot_right/scan_3D"),
        DeclareLaunchArgument("coordinate_profile", default_value="cyglidar_d2"),
        # Separate modulation channels reduce interference between the two D2 emitters.
        Node(**common, name="cygbot_left", namespace="cygbot_left",
             parameters=[{
                 "port_number": "/dev/lidar_left",
                 "baud_rate": 0,  # D2 index 0 = 3,000,000 bps
                 "run_mode": 2,
                 "frame_id": "laser_left",
                 "frequency_channel": 0,
                 "enable_kalmanfilter": True,
             }]),
        Node(**common, name="cygbot_right", namespace="cygbot_right",
             parameters=[{
                 "port_number": "/dev/lidar_right",
                 "baud_rate": 0,
                 "run_mode": 2,
                 "frame_id": "laser_right",
                 "frequency_channel": 1,
                 "enable_kalmanfilter": True,
             }]),
        Node(
            package="walker_lidar", executable="lidar_bridge_node",
            name="lidar_bridge", output="screen",
            respawn=True, respawn_delay=2.0,
            parameters=[{
                "pi_host": ParameterValue(LaunchConfiguration("pi_host"), value_type=str),
                "pi_port": 9100,
                "send_hz": 20.0,
                "left_topic": "/cygbot_left/scan",
                "right_topic": "/cygbot_right/scan",
                "msg_type": "LaserScan",
                "roi_fov_deg": 80.0,
            }],
        ),
        Node(
            package="walker_lidar", executable="lidar_preview_node",
            name="lidar_preview_3d", output="screen",
            condition=IfCondition(LaunchConfiguration("enable_3d_preview")),
            respawn=True, respawn_delay=2.0,
            parameters=[{
                "pi_host": ParameterValue(LaunchConfiguration("pi_host"), value_type=str),
                "preview_port": ParameterValue(LaunchConfiguration("preview_port"), value_type=int),
                "left_cloud_topic": LaunchConfiguration("left_cloud_topic"),
                "right_cloud_topic": LaunchConfiguration("right_cloud_topic"),
                "coordinate_profile": LaunchConfiguration("coordinate_profile"),
                "preview_hz": 10.0,
            }],
        ),
    ])
