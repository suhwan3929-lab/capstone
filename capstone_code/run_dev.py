"""
개발 편의용 실행기 — safety_monitor 와 ui 를 함께 띄운다.

실기(Pi)에서는 systemd가 이 역할을 한다. 개발 PC에서 터미널 2개를 띄우는
번거로움만 없애주는 물건이며, 두 프로세스가 분리되어 있다는 사실은 그대로다.

    python run_dev.py
    python run_dev.py --tag curb        # CSV 태그를 safety_monitor로 전달
    python run_dev.py --no-ui           # 모니터만
"""
import argparse
import subprocess
import sys
import threading
import time

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import console

console.setup()

PY = sys.executable


def _pump(proc, prefix):
    for line in iter(proc.stdout.readline, ""):
        if line:
            print(f"{prefix} {line.rstrip()}", flush=True)


def _spawn(script, extra, prefix):
    p = subprocess.Popen([PY, "-u", script] + extra,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    threading.Thread(target=_pump, args=(p, prefix), daemon=True).start()
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="session")
    ap.add_argument("--no-ui", action="store_true")
    ap.add_argument("--sim", action="store_true", help="하드웨어 없이 시뮬레이션")
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--no-alert", action="store_true")
    args = ap.parse_args()

    extra = ["--tag", args.tag]
    if args.sim:
        extra.append("--sim")
    if args.scenario:
        extra += ["--scenario", args.scenario]
    if args.no_alert:
        extra.append("--no-alert")

    procs = []
    print("=" * 60)
    print(" safety_monitor 시작 (안전 필수 프로세스)")
    print("=" * 60)
    procs.append(("monitor", _spawn("safety_monitor.py", extra, "[모니터]")))

    if not args.no_ui:
        time.sleep(1.5)          # 모니터가 UDP 수신 준비를 마칠 여유
        print("=" * 60)
        print(" ui 시작 (대시보드 — 죽어도 안전 기능은 계속됩니다)")
        print("=" * 60)
        procs.append(("ui", _spawn("ui.py", [], "[  UI  ]")))

    try:
        while True:
            for name, p in procs:
                if p.poll() is not None:
                    print(f"\n[run_dev] {name} 프로세스가 종료되었습니다 "
                          f"(코드 {p.returncode})")
                    if name == "monitor":
                        raise KeyboardInterrupt
                    procs = [(n, q) for n, q in procs if n != name]
            if not procs:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[run_dev] 종료 중...")
    finally:
        for _, p in procs:
            if p.poll() is None:
                p.terminate()
        time.sleep(0.5)
        for _, p in procs:
            if p.poll() is None:
                p.kill()


if __name__ == "__main__":
    main()
