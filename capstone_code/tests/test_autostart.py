"""Check boot isolation and the deployed Pi/Jetson configuration, without hardware."""
import ast
from contextlib import redirect_stdout
from configparser import ConfigParser
import io
import os
from pathlib import Path, PurePosixPath
import runpy
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

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


def test_gui_only_render_has_no_safety_service():
    files = render("pi", "yu", "/home/yu", "/home/yu/capstone/capstone_code", gui_only=True)
    assert set(files) == {PurePosixPath("/usr/local/libexec/walker/start-pi-ui.sh"),
                          PurePosixPath("/home/yu/.config/autostart/walker-ui.desktop")}
    assert "cd /home/yu/capstone/capstone_code" in "\n".join(files.values())
    assert "safety_monitor.py" not in "\n".join(files.values())


def test_gui_only_cli_preview_and_invalid_role_combinations():
    result = subprocess.run([sys.executable, str(INSTALLER), "pi", "--gui-only", "--dry-run"],
                            capture_output=True, text=True, check=True)
    assert "walker-ui.desktop" in result.stdout and "walker-safety.service" not in result.stdout
    for args in (["jetson", "--gui-only", "--pi-host", "192.168.10.2"],
                 ["pi", "--gui-only", "--enable-alerts"]):
        result = subprocess.run([sys.executable, str(INSTALLER), *args, "--dry-run"],
                                capture_output=True, text=True)
        assert result.returncode == 2 and "--gui-only" in result.stderr


def test_gui_only_preflight_does_not_require_serial_group_or_udp_distance_source():
    preflight = runpy.run_path(str(INSTALLER))["preflight"]
    account = SimpleNamespace(pw_dir="/home/yu", pw_uid=1000, pw_gid=1000)
    group = Mock(side_effect=AssertionError("GUI must not require serial access"))
    with patch.dict(sys.modules, {"pwd": SimpleNamespace(getpwnam=lambda name: account),
                                  "grp": SimpleNamespace(getgrnam=group)}), \
            patch.object(Path, "is_file", return_value=True), \
            patch.object(subprocess, "run") as run:
        assert preflight("pi", "yu", Path("/home/yu/capstone/capstone_code"),
                         Path("/home/yu"), gui_only=True) is account
        group.assert_not_called()
        probe = run.call_args_list[0].args[0]
        assert "not config.SIM_MODE" in probe[6] and "LIDAR_SOURCE" not in probe[6]


def test_gui_only_install_never_enables_or_writes_safety_service():
    main = runpy.run_path(str(INSTALLER))["main"]
    installed = Mock(return_value=Path("/var/backups/walker-autostart/test"))
    args = [str(INSTALLER), "pi", "--gui-only", "--project-dir", "/home/yu/capstone/capstone_code"]
    with patch.dict(main.__globals__, preflight=Mock(return_value=object()),
                    install_files=installed), patch.object(sys, "argv", args), \
            patch.object(sys, "platform", "linux"), \
            patch.object(os, "geteuid", return_value=0, create=True), \
            patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="")) as run, \
            redirect_stdout(io.StringIO()):
        assert main() == 0
    files = installed.call_args.args[0]
    assert len(files) == 2 and all(path.suffix in (".sh", ".desktop") for path in files)
    assert [call.args[0] for call in run.call_args_list] == [
        ["systemctl", "list-unit-files", "--no-legend"]]


def test_gui_install_handles_a_missing_or_existing_legacy_service():
    for present in (False, True):
        main = runpy.run_path(str(INSTALLER))["main"]
        commands = []

        def systemctl(command, **kwargs):
            commands.append(command)
            # Some systemd releases return 1 for a pattern with no matches.
            if command == ["systemctl", "list-unit-files", "walker-ui.service", "--no-legend"]:
                raise subprocess.CalledProcessError(1, command, output="", stderr="")
            rows = "ssh.service enabled enabled\n"
            if present:
                rows += "walker-ui.service enabled enabled\n"
            return subprocess.CompletedProcess(command, 0, stdout=rows, stderr="")

        args = [str(INSTALLER), "pi", "--gui-only"]
        installed = Mock(return_value=Path("/var/backups/walker-autostart/test"))
        with patch.dict(main.__globals__, preflight=Mock(return_value=object()),
                        install_files=installed), patch.object(sys, "argv", args), \
                patch.object(sys, "platform", "linux"), \
                patch.object(os, "geteuid", return_value=0, create=True), \
                patch.object(subprocess, "run", side_effect=systemctl), \
                redirect_stdout(io.StringIO()):
            assert main() == 0
        assert (["systemctl", "disable", "walker-ui.service"] in commands) == present
        assert not any(command[:2] == ["systemctl", "enable"] for command in commands)


def test_gui_install_keeps_systemctl_failures_visible():
    main = runpy.run_path(str(INSTALLER))["main"]
    error = subprocess.CalledProcessError(1, ["systemctl"], stderr="Failed to connect to bus")
    args = [str(INSTALLER), "pi", "--gui-only"]
    with patch.dict(main.__globals__, preflight=Mock(return_value=object()),
                    install_files=Mock(return_value=Path("/backup"))), \
            patch.object(sys, "argv", args), patch.object(sys, "platform", "linux"), \
            patch.object(os, "geteuid", return_value=0, create=True), \
            patch.object(subprocess, "run", side_effect=error):
        try:
            main()
        except subprocess.CalledProcessError as caught:
            assert caught is error
        else:
            raise AssertionError("A real systemctl failure was ignored")
