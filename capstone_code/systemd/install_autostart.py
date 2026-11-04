"""Install boot services without duplicating the current manual sensor run."""
import argparse
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid


def render(role, user, home, project, pi_host=None, alerts=False):
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", user):
        raise ValueError("Invalid service user")
    home, project = PurePosixPath(home), PurePosixPath(project)
    if not home.is_absolute() or not project.is_absolute():
        raise ValueError("Use absolute Linux paths")
    if any(not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(path)) for path in (home, project)):
        raise ValueError("Paths must not contain whitespace or shell special characters")
    helper = PurePosixPath("/usr/local/libexec/walker")
    if role == "pi":
        extra = "" if alerts else " --no-alert"
        service = f"""[Unit]
Description=Walker safety monitor
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User={user}
WorkingDirectory={project}
Environment=WALKER_SIM=0
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/etc/walker/secrets.env
ExecStart=/opt/walker/venv/bin/python -u {project}/safety_monitor.py --tag boot{extra}
Restart=always
RestartSec=3
TimeoutStopSec=20
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
        # The desktop supplies its own display/authentication environment.
        launcher = f"""#!/bin/bash
set -e
export WALKER_SIM=0
cd {shlex.quote(str(project))}
state="${{XDG_STATE_HOME:-$HOME/.local/state}}/walker"
mkdir -p "$state"
exec 9>"${{XDG_RUNTIME_DIR:-$state}}/walker-ui.lock"
flock -n 9 || exit 0
child=""
cleanup() {{
    if [ -n "$child" ]; then
        kill "$child" 2>/dev/null || true
        wait "$child" 2>/dev/null || true
    fi
}}
trap cleanup EXIT
trap 'exit 0' INT TERM
while true; do
    /opt/walker/venv/bin/python -u ui.py >>"$state/ui.log" 2>&1 &
    child=$!
    wait "$child" || true
    child=""
    sleep 5
done
"""
        desktop = """[Desktop Entry]
Type=Application
Name=Walker Dashboard
Exec=/usr/local/libexec/walker/start-pi-ui.sh
Terminal=false
X-GNOME-Autostart-enabled=true
"""
        return {
            PurePosixPath("/etc/systemd/system/walker-safety.service"): service,
            helper / "start-pi-ui.sh": launcher,
            home / ".config/autostart/walker-ui.desktop": desktop,
        }
    if role != "jetson":
        raise ValueError("Unknown role")
    if not pi_host or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", pi_host):
        raise ValueError("Supply Pi IPv4 address or hostname with --pi-host")
    launcher = f"""#!/bin/bash
set -e
source /opt/ros/humble/setup.bash
source {shlex.quote(str(home / 'd2_ws/install/setup.bash'))}
source {shlex.quote(str(project / 'install/setup.bash'))}
preview=false
if ros2 pkg executables walker_lidar | grep -q '^walker_lidar lidar_preview_node$'; then
    preview=true
fi
exec ros2 launch walker_lidar walker_lidar.launch.py start_drivers:=true \\
    pi_host:={shlex.quote(pi_host)} enable_3d_preview:="$preview"
"""
    wait_devices = """import os
from pathlib import Path
import sys
import time

ports = [Path('/dev/lidar_left'), Path('/dev/lidar_right')]
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    if all(port.exists() and os.access(port, os.R_OK | os.W_OK) for port in ports):
        sys.exit(0)
    time.sleep(0.5)
print('LiDAR aliases missing or not accessible; retrying boot startup.', file=sys.stderr)
sys.exit(1)
"""
    service = f"""[Unit]
Description=Walker dual D2 drivers and UDP bridge
After=network-online.target systemd-modules-load.service
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User={user}
WorkingDirectory={home}
Environment=PYTHONUNBUFFERED=1
ExecStartPre=/usr/bin/python3 /usr/local/libexec/walker/wait-lidar.py
ExecStart=/bin/bash /usr/local/libexec/walker/start-jetson.sh
Restart=always
RestartSec=3
TimeoutStartSec=45
TimeoutStopSec=20
KillMode=control-group
KillSignal=SIGINT
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    return {
        PurePosixPath("/etc/systemd/system/walker-lidar.service"): service,
        helper / "start-jetson.sh": launcher,
        helper / "wait-lidar.py": wait_devices,
        PurePosixPath("/etc/modules-load.d/walker-lidar.conf"): "pl2303\n",
    }


def preflight(role, user, project, home):
    """Check the board before writing configuration, without starting sensors."""
    import pwd
    import grp
    account = pwd.getpwnam(user)
    if Path(account.pw_dir) != home:
        raise ValueError("Account home does not match")
    if grp.getgrnam("dialout").gr_gid not in os.getgrouplist(user, account.pw_gid):
        raise ValueError("Service user must belong to dialout for serial sensor access")
    if role == "pi":
        for name in ("safety_monitor.py", "ui.py", "config.py"):
            if not (project / name).is_file():
                raise FileNotFoundError(str(project / name))
        python = "/opt/walker/venv/bin/python"
        check = ("import sys; sys.path.insert(0, sys.argv[1]); import config; "
                 "sys.exit(0 if not config.SIM_MODE and config.LIDAR_SOURCE == 'udp' else 2)")
        subprocess.run(["runuser", "-u", user, "--", python, "-c", check, str(project)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["runuser", "-u", user, "--", python, "-c",
                        "import tkinter, serial, requests"], check=True)
        subprocess.run(["flock", "--version"], check=True, stdout=subprocess.DEVNULL)
    else:
        for setup in (Path("/opt/ros/humble/setup.bash"),
                      home / "d2_ws/install/setup.bash", project / "install/setup.bash"):
            if not setup.is_file():
                raise FileNotFoundError(str(setup))
        subprocess.run(["modinfo", "pl2303"], check=True, stdout=subprocess.DEVNULL)
    return account


def install_files(files, home, account):
    files = {Path(str(path)): content for path, content in files.items()}
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    backup = Path("/var/backups/walker-autostart") / stamp
    for path in files:
        if path.exists():
            saved = backup / path.relative_to("/")
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
    for path, content in files.items():
        parent_existed = path.parent.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        path.chmod(0o755 if path.suffix == ".sh" else 0o644)
        if path.is_relative_to(home):
            os.chown(path, account.pw_uid, account.pw_gid)
            if not parent_existed:
                for parent in (home / ".config", path.parent):
                    os.chown(parent, account.pw_uid, account.pw_gid)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("pi", "jetson"))
    parser.add_argument("--user")
    parser.add_argument("--project-dir")
    parser.add_argument("--pi-host")
    parser.add_argument("--enable-alerts", action="store_true",
                        help="Pi only: enable buzzer/LED instead of --no-alert trial mode")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    user = args.user or ("yu" if args.role == "pi" else "walker")
    home = PurePosixPath("/home") / user
    project = PurePosixPath(args.project_dir or ("/opt/walker/capstone_code" if args.role == "pi"
                                                else str(home / "walker_bridge_ws")))
    files = render(args.role, user, home, project, args.pi_host, args.enable_alerts)
    if args.dry_run:
        for path, content in files.items():
            print(f"\n{path}\n{content}")
        return 0
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("Run with sudo on Ubuntu, or use --dry-run")
    home, project = Path(str(home)), Path(str(project))
    account = preflight(args.role, user, project, home)
    if args.role == "pi":
        logs = project / "logs"
        logs.mkdir(exist_ok=True)
        os.chown(logs, account.pw_uid, account.pw_gid)
    backup = install_files(files, home, account)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    service = "walker-safety.service" if args.role == "pi" else "walker-lidar.service"
    subprocess.run(["systemd-analyze", "verify", "/etc/systemd/system/" + service], check=True)
    if args.role == "pi":
        old = subprocess.run(["systemctl", "list-unit-files", "walker-ui.service", "--no-legend"],
                             capture_output=True, text=True, check=True)
        if old.stdout.strip():
            subprocess.run(["systemctl", "disable", "walker-ui.service"], check=True)
    subprocess.run(["systemctl", "enable", service], check=True)
    subprocess.run(["systemctl", "is-enabled", service], check=True)
    print("Installed and enabled for next boot: " + service)
    print("Existing running programs were not started or stopped.")
    print("Previous configuration backup: " + str(backup))
    if args.role == "pi":
        print("GUI starts on desktop login. Enable Ubuntu Automatic Login for power-on GUI.")
        print("Buzzer/LED: " + ("enabled by config" if args.enable_alerts else "disabled (--no-alert)"))
        print("Discord still requires valid /etc/walker/secrets.env and verified delivery.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("Install stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
