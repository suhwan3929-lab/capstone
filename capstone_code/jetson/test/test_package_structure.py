"""Windows-compatible checks for ROS 2 package metadata and install layout."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class TestPackageStructure(unittest.TestCase):
    def test_package_xml_declares_expected_ros_dependencies(self):
        root = ET.parse(ROOT / "package.xml").getroot()
        self.assertEqual(root.findtext("name"), "walker_lidar")
        deps = {node.text for node in root.findall("exec_depend")}
        self.assertTrue({"rclpy", "sensor_msgs", "sensor_msgs_py", "launch", "launch_ros"} <= deps)
        self.assertEqual(root.findtext("export/build_type"), "ament_python")

    def test_setup_exposes_ros_console_entry_point(self):
        result = subprocess.run([sys.executable, "setup.py", "--name"], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "walker_lidar")
        self.assertIn("lidar_bridge_node = lidar_bridge_node:main",
                      (ROOT / "setup.py").read_text(encoding="utf-8"))

    def test_package_installs_launch_and_ament_marker(self):
        with tempfile.TemporaryDirectory() as target:
            subprocess.run([sys.executable, "setup.py", "install", f"--prefix={target}"],
                           cwd=ROOT, capture_output=True, text=True, check=True)
            prefix = Path(target)
            self.assertTrue((prefix / "share" / "walker_lidar" / "package.xml").is_file())
            self.assertTrue((prefix / "share" / "walker_lidar" / "launch" /
                             "walker_lidar.launch.py").is_file())
            self.assertTrue((prefix / "share" / "ament_index" / "resource_index" /
                             "packages" / "walker_lidar").is_file())


if __name__ == "__main__":
    unittest.main()
