from glob import glob
from os.path import join

from setuptools import setup

package_name = "walker_lidar"

setup(
    name=package_name,
    version="0.1.0",
    py_modules=["lidar_bridge_node"],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/walker_lidar"]),
        (join("share", package_name), ["package.xml"]),
        (join("share", package_name, "launch"), glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools", "numpy"],
    zip_safe=True,
    maintainer="유수환",
    maintainer_email="suhwan3929@naver.com",
    description="Dual LiDAR ROS 2 to UDP bridge for the Walker safety system.",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={"console_scripts": ["lidar_bridge_node = lidar_bridge_node:main"]},
)
