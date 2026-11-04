"""Check boot isolation and the deployed Pi/Jetson configuration, without hardware."""
import ast
from configparser import ConfigParser
from pathlib import Path, PurePosixPath
import runpy
import subprocess
import sys

INSTALLER = Path(__file__).resolve().parents[1] / "systemd/install_autostart.py"
render = runpy.run_path(str(INSTALLER))["render"]


def unit(content):
    parser = ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(content)
    return parser


def test_pi_safety_starts_without_gui_or_missing_discord_secrets():
    files = render("pi", "yu", "/home/yu", "/opt/walker/capstone_code")
    service = unit(files[PurePosixPath("/etc/systemd/system/walker-safety.service")])
    assert service["Service"]["User"] == "yu"
    assert service["Service"]["WorkingDirectory"] == "/opt/walker/capstone_code"
    assert "/opt/walker/venv/bin/python" in service["Service"]["ExecStart"]
    assert "safety_monitor.py --tag boot --no-alert" in service["Service"]["ExecStart"]
    assert service["Service"]["EnvironmentFile"] == "-/etc/walker/secrets.env"
    assert service["Install"]["WantedBy"] == "multi-user.target"
    assert service["Service"]["Restart"] == "always"
    assert "Requires" not in service["Unit"] and "BindsTo" not in service["Unit"]
    assert "graphical" not in service["Unit"]["After"]


def test_pi_alarm_option_does_not_enable_simulation_or_change_sensors():
    files = render("pi", "yu", "/home/yu", "/opt/walker/capstone_code", alerts=True)
    service = files[PurePosixPath("/etc/systemd/system/walker-safety.service")]
    assert "--no-alert" not in service and "--sim" not in service
    assert "Environment=WALKER_SIM=0" in service


def test_gui_uses_desktop_environment_and_single_instance_lock():
    files = render("pi", "yu", "/home/yu", "/opt/walker/capstone_code")
    desktop = files[PurePosixPath("/home/yu/.config/autostart/walker-ui.desktop")]
    launcher = files[PurePosixPath("/usr/local/libexec/walker/start-pi-ui.sh")]
    assert "Exec=/usr/local/libexec/walker/start-pi-ui.sh" in desktop
    assert "DISPLAY=:0" not in launcher and "XAUTHORITY=" not in launcher
    assert "flock -n 9 || exit 0" in launcher
    assert "python -u ui.py" in launcher and "run_dev.py" not in launcher
    assert "trap cleanup EXIT" in launcher and "sleep 5" in launcher


def test_jetson_waits_for_serial_ports_and_starts_both_drivers():
    files = render("jetson", "walker", "/home/walker", "/home/walker/walker_bridge_ws",
                   pi_host="192.168.0.173")
    service = unit(files[PurePosixPath("/etc/systemd/system/walker-lidar.service")])
    launcher = files[PurePosixPath("/usr/local/libexec/walker/start-jetson.sh")]
    wait = files[PurePosixPath("/usr/local/libexec/walker/wait-lidar.py")]
    assert service["Service"]["User"] == "walker"
    assert service["Service"]["KillMode"] == "control-group"
    assert service["Service"]["TimeoutStopSec"] == "20"
    assert "start_drivers:=true" in launcher and "pi_host:=192.168.0.173" in launcher
    assert "source /opt/ros/humble/setup.bash" in launcher
    assert "d2_ws/install/setup.bash" in launcher and "walker_bridge_ws/install/setup.bash" in launcher
    assert "set -u" not in launcher
    assert "lidar_preview_node" in launcher and 'preview=false' in launcher
    assert "'/dev/lidar_left'" in wait and "'/dev/lidar_right'" in wait
    ast.parse(wait)
    assert files[PurePosixPath("/etc/modules-load.d/walker-lidar.conf")] == "pl2303\n"


def test_rejects_missing_host_and_unsafe_paths_before_rendering():
    for kwargs in ({}, {"pi_host": "host;reboot"}, {"pi_host": "a\nUser=root"}):
        try:
            render("jetson", "walker", "/home/walker", "/home/walker/walker_bridge_ws", **kwargs)
        except ValueError:
            continue
        raise AssertionError("Unsafe or missing host accepted")
    try:
        render("pi", "yu", "/home/yu", "/opt/walker\nExecStart=bad")
    except ValueError:
        return
    raise AssertionError("Unsafe project path accepted")


def test_dry_run_never_writes_linux_configuration():
    result = subprocess.run([sys.executable, str(INSTALLER), "pi", "--dry-run"],
                            capture_output=True, text=True, check=True)
    assert "walker-safety.service" in result.stdout
    assert "Installed and enabled" not in result.stdout
    result = subprocess.run([sys.executable, str(INSTALLER), "jetson", "--pi-host",
                             "192.168.0.173", "--dry-run"], capture_output=True, text=True, check=True)
    assert "start_drivers:=true" in result.stdout
