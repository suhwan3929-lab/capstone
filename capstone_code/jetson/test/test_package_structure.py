"""Windows-compatible checks for ROS 2 package metadata and install layout."""
from pathlib import Path
import ast
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class TestPackageStructure(unittest.TestCase):
    def test_launch_preserves_scan_bridge_and_adds_optional_display_process(self):
        source = ROOT / "launch" / "walker_lidar.launch.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        ns = dict(LaunchDescription=lambda actions: actions,
                  DeclareLaunchArgument=lambda *args, **kwargs: None,
                  LaunchConfiguration=lambda name: name,
                  IfCondition=lambda value: ("if", value),
                  ParameterValue=lambda value, **kwargs: value,
                  Node=lambda **kwargs: kwargs)
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), ns)
        actions = ns["generate_launch_description"]()
        drivers = [action for action in actions if isinstance(action, dict)
                   and action.get("executable") == "cyglidar_d2_publisher"]
        self.assertEqual(len(drivers), 2)
        channels = {driver["namespace"]: driver["parameters"][0]["frequency_channel"] for driver in drivers}
        self.assertEqual(channels, {"cygbot_left": 0, "cygbot_right": 1})
        nodes = {action["executable"]: action for action in actions if isinstance(action, dict)}
        bridge = nodes["lidar_bridge_node"]
        preview = nodes["lidar_preview_node"]
        self.assertEqual(bridge["parameters"][0]["msg_type"], "LaserScan")
        self.assertEqual(bridge["parameters"][0]["left_topic"], "/cygbot_left/scan")
        self.assertEqual(preview["condition"], ("if", "enable_3d_preview"))
        self.assertEqual(preview["parameters"][0]["preview_hz"], 10.0)
        self.assertNotEqual(bridge["name"], preview["name"])

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
        self.assertIn("lidar_preview_node = lidar_preview_node:main",
                      (ROOT / "setup.py").read_text(encoding="utf-8"))

    def test_package_installs_launch_and_ament_marker(self):
        with tempfile.TemporaryDirectory() as target:
            subprocess.run([sys.executable, "setup.py", "install", f"--prefix={target}"],
                           cwd=ROOT, capture_output=True, text=True, check=True)
            prefix = Path(target)
            self.assertTrue((prefix / "share" / "walker_lidar" / "package.xml").is_file())
            self.assertTrue((prefix / "share" / "walker_lidar" / "launch" /
                             "walker_lidar.launch.py").is_file())
            self.assertTrue(list(prefix.rglob("walker_preview/d2_lens.json")))
            self.assertTrue(list(prefix.rglob("walker_preview/LICENSE.cyglidar_d2")))
            self.assertTrue((prefix / "share" / "ament_index" / "resource_index" /
                             "packages" / "walker_lidar").is_file())
            self.assertTrue(list(prefix.rglob("lidar_preview_node.py")))
            self.assertTrue(list(prefix.rglob("walker_preview/protocol.py")))
            self.assertTrue(list(prefix.rglob("walker_preview/sampling.py")))


if __name__ == "__main__":
    unittest.main()
