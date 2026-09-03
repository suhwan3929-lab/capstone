"""
safety_monitor — 안전 필수 프로세스 (Pi 5)

이 프로세스만 살아 있으면 전도 감지·경고음·보호자 신고가 동작한다.
GUI(ui.py)도, Jetson의 LiDAR도 없어도 된다.
    → 계획서의 "Jetson이 죽어도 Pi 단독으로 전도 알림은 살아 있어야 한다" 요구사항이
      코드 구조로 강제된다.

담당
    센서 수집 → 전도 판정(tipover_monitor) → 경고 출력(alerting)
    물리 버튼(buttons) · RTK 보정(ntrip_client) · 배터리 감시(battery)
    상태 송신(status_link) · 실험 데이터 기록(csv_logger)

실행
    python safety_monitor.py                        # 일반
    python safety_monitor.py --sim                  # 하드웨어 없이 (시뮬레이터)
    python safety_monitor.py --sim --scenario tipover_front
    python safety_monitor.py --tag curb             # 실험 데이터 수집
    python safety_monitor.py --calibrate            # IMU 장착각 측정
    python safety_monitor.py --no-ui-link           # 상태 송신 없이 헤드리스

systemd: systemd/walker-safety.service
"""
import argparse
import sys
import threading
import time

# ── 인자를 먼저 읽어 config를 확정한다 ────────────────────
#   시뮬레이터/LiDAR 소스 결정이 모듈 import보다 앞서야 한다.
def _parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="session", help="CSV 로그 태그(시나리오명)")
    ap.add_argument("--sim", action="store_true", help="하드웨어 없이 시뮬레이션")
    ap.add_argument("--scenario", default=None, help="시뮬레이션 시나리오")
    ap.add_argument("--calibrate", action="store_true", help="IMU 장착각 측정 후 종료")
    ap.add_argument("--no-ui-link", action="store_true", help="상태 UDP 송신 안 함")
    ap.add_argument("--no-alert", action="store_true", help="부저/LED 출력 끄기")
    ap.add_argument("--list-scenarios", action="store_true")
    return ap.parse_args()


ARGS = _parse_args()

import config  # noqa: E402

if ARGS.sim:
    config.SIM_MODE = True
if ARGS.scenario:
    config.SIM_SCENARIO = ARGS.scenario
    config.SIM_MODE = True
if ARGS.no_alert:
    config.ALERT_ENABLED = False

import alerting  # noqa: E402
import console  # noqa: E402
import battery  # noqa: E402
import notifier  # noqa: E402
import ntrip_client  # noqa: E402
from tipover_monitor import TipoverMonitor  # noqa: E402
from alerting import Alerter, tipover_state_to_level  # noqa: E402
from buttons import ButtonHub  # noqa: E402
from csv_logger import SampleLogger  # noqa: E402
from schema import HealthReport, SystemStatus  # noqa: E402
from sensors import gps_source, imu_source, lidar_source  # noqa: E402
from states import CONN_ERROR, CONN_OK, CONN_STALE  # noqa: E402
from status_link import CommandListener, StatusPublisher  # noqa: E402

_notice = [None]        # UI로 넘길 최근 한 줄

console.setup()   # cp949 콘솔에서 이모지 한 글자로 죽지 않게 (console.py 참조)


def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    mark = {"ERROR": "!!", "WARN": " *", "SYSTEM": "==", "INFO": "  "}.get(level, "  ")
    try:
        print(f"[{ts}]{mark} {msg}", flush=True)   # -u 와 함께 systemd 로그로 간다
    except Exception:
        pass                                       # 로그 실패로 죽지 않는다
    if level in ("WARN", "ERROR", "SYSTEM"):
        _notice[0] = msg


# ══════════════════════════════════════════════════════════
# 초기화
# ══════════════════════════════════════════════════════════
def init_sensors():
    log("=== 시스템 부팅 ===", "SYSTEM")
    if config.SIM_MODE:
        from sensors import sim
        log("⚠ 시뮬레이션 모드 — 실제 센서를 읽지 않습니다", "SYSTEM")
        sim.start(config.SIM_SCENARIO, log)
        log("=== 초기화 완료 ===", "SYSTEM")
        return

    log(f"LiDAR 소스: {lidar_source.source_name()}", "SYSTEM")
    for mod, name in ((gps_source, "GPS"), (imu_source, "IMU"),
                      (lidar_source, "LiDAR")):
        if mod is lidar_source and config.LIDAR_SOURCE == "none":
            log("[LiDAR] 사용 안 함 (config.LIDAR_SOURCE='none')", "WARN")
            continue
        try:
            ok = mod.run_integrity_check(log)
            if not ok:
                # 점검에 실패해도 감시 스레드는 띄운다. 나중에 연결되면 자동 복구된다.
                log(f"[{name}] 초기 점검 실패 — 백그라운드 재연결 계속", "WARN")
            mod.start(log)
        except Exception as e:
            log(f"[{name}] 초기화 예외: {type(e).__name__}: {e}", "ERROR")

    log("=== 초기화 완료 ===", "SYSTEM")


def conn_status(valid, status):
    if status == CONN_STALE:
        return CONN_STALE
    return CONN_OK if valid else (status or CONN_ERROR)


def _sensors_faulty(imu, gps, obs) -> bool:
    """
    사용자에게 소리로 알려야 할 만큼 심각한 센서 이상인가.
    IMU가 죽으면 전도 감지 자체가 불가능하므로 반드시 고지해야 한다.
    """
    if not imu.valid:
        return True
    if config.LIDAR_SOURCE != "none" and not config.SIM_MODE and not obs.link_ok:
        return True
    return False


def _is_moving(gps, imu) -> bool:
    """
    정지 중에는 장애물 경고를 울리지 않는다 (경보 피로 방지).
    속도 정보가 없으면 자이로 활동량으로 대신 판단한다.
    """
    if gps.valid and gps.speed_kmh is not None:
        return gps.speed_kmh > 0.5
    return imu.valid and imu.gyro_dps > 5.0


# ══════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════
def main():
    args = ARGS

    if args.list_scenarios:
        from sensors import sim
        print("사용 가능한 시뮬레이션 시나리오:")
        for k in sim.SCENARIOS:
            print(f"  {k}")
        return 0

    init_sensors()

    # ── 장착각 캘리브레이션 모드 ──────────────────────
    if args.calibrate:
        log("수평 정지 상태를 유지하세요. 3초 후 2초간 측정합니다.", "SYSTEM")
        time.sleep(3)
        res = imu_source.capture_mount_offset(2.0)
        if res is None:
            log("IMU 데이터를 받지 못했습니다.", "ERROR")
            return 1
        r, p = res
        log("측정 완료. config_local.py 에 아래 두 줄을 넣으세요:", "SYSTEM")
        print(f"\nMOUNT_ROLL_OFFSET_DEG  = {r:.2f}"
              f"\nMOUNT_PITCH_OFFSET_DEG = {p:.2f}\n")
        return 0

    if not notifier.is_configured():
        log("⚠ 웹훅 미설정 — 판정과 현장 경고는 동작하지만 "
            "보호자 알림은 나가지 않습니다.", "ERROR")

    # ── 구성요소 기동 ─────────────────────────────────
    monitor = TipoverMonitor(log_callback=log)
    monitor.start()

    alerter = Alerter(log_callback=log)
    alerter.start()

    buttons = ButtonHub(monitor.submit, log_callback=log)
    buttons.start()

    cmd_rx = CommandListener(monitor.submit)
    cmd_rx.start()

    battery.start(log)
    if not config.SIM_MODE:
        ntrip_client.start(log)

    pub = None if args.no_ui_link else StatusPublisher()
    tag = args.tag if args.tag != "session" or not config.SIM_MODE \
        else f"sim_{config.SIM_SCENARIO}"
    csv = SampleLogger(tag)
    log(f"CSV 로그: {getattr(csv, 'path', '비활성')}", "SYSTEM")

    stop_evt = threading.Event()
    _install_signals(stop_evt)
    log("가동 중. Ctrl+C 로 종료합니다.", "SYSTEM")

    # ★ 주 루프는 센서 속도(100 Hz)로 돈다.
    #   CSV를 상태 송신 주기(10 Hz)로 기록하면 **충격 피크를 통째로 놓친다.**
    #   강체 충돌의 가속도 전이는 수십 ms 안에 끝나므로,
    #   임계값 실험 데이터는 반드시 센서 원속도로 남겨야 한다. (코드_리뷰 §3.3)
    LOOP_HZ = 100
    period = 1.0 / LOOP_HZ
    publish_every = max(1, LOOP_HZ // config.STATUS_HZ)
    tick = 0
    last_logged_t = 0.0
    next_t = time.monotonic()
    last_ntrip_note = 0.0
    try:
        while not stop_evt.is_set():
            tick += 1
            imu = imu_source.snapshot()
            gps = gps_source.snapshot()
            obs = lidar_source.snapshot()
            state, deadline, sent = monitor.snapshot()

            imu.status = conn_status(imu.valid, imu.status)
            gps.status = conn_status(gps.valid, gps.status)

            # ── 사용자에게 실제로 도달하는 경고 출력 ────
            #   단차(턱)는 장애물보다 위험하므로 더 가까운 것으로 취급한다.
            #   내려가는 턱은 발이 헛디뎌지는 순간 바로 전복으로 이어진다.
            warn_m = obs.nearest_m
            if obs.curb_m is not None:
                bias = 0.25 if obs.curb_type == "drop" else 0.10
                effective = max(0.05, obs.curb_m - bias)
                warn_m = effective if warn_m is None else min(warn_m, effective)

            alerter.update(obstacle_m=warn_m,
                           tipover_level=tipover_state_to_level(state),
                           sensor_fault=_sensors_faulty(imu, gps, obs),
                           moving=_is_moving(gps, imu))

            # 같은 샘플을 두 번 기록하지 않는다 (센서가 루프보다 느릴 때)
            if imu.valid and imu.t_capture > last_logged_t:
                last_logged_t = imu.t_capture
                csv.write(imu, obs, gps, state)

            # ── RTK 상태를 가끔 로그로 남긴다 ───────────
            now = time.time()
            if ntrip_client.is_configured() and now - last_ntrip_note > 60:
                last_ntrip_note = now
                st = ntrip_client.stats()
                log(f"[NTRIP] 연결={st['connected']} 수신={st['bytes']:,}B "
                    f"재접속={st['reconnects']}회 "
                    f"보정지연={'-' if st['rtcm_age'] is None else f'{st['rtcm_age']:.0f}s'}",
                    "INFO")

            if pub and tick % publish_every == 0:
                b = battery.snapshot()
                nt = ntrip_client.stats()
                pub.publish(SystemStatus(
                    tipover_state=state, ask_deadline=deadline, alert_sent=sent,
                    imu=imu, gps=gps, obstacle=obs,
                    health=HealthReport(
                        battery_pct=b["percent"], battery_volts=b["volts"],
                        charging=b["charging"], battery_backend=b["backend"],
                        ntrip_connected=nt["connected"],
                        ntrip_healthy=nt["healthy"], ntrip_bytes=nt["bytes"],
                        alerts_pending=notifier.pending(),
                        alert_backend=alerter.backend_name),
                    notice=_notice[0]))
                _notice[0] = None

            next_t += period
            time.sleep(max(0.0, next_t - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        log("종료 중...", "SYSTEM")
        monitor.stop()
        cmd_rx.stop()
        buttons.stop()
        alerter.stop()
        battery.stop()
        ntrip_client.stop()
        if config.SIM_MODE:
            from sensors import sim
            sim.stop()
        for m in (imu_source, gps_source, lidar_source):
            try:
                m.stop()
            except Exception:
                pass
        csv.close()
        if pub:
            pub.close()
        time.sleep(0.3)
        log("종료 완료", "SYSTEM")
    return 0


def _install_signals(stop_evt):
    import signal
    for sig in ("SIGTERM", "SIGINT"):
        s = getattr(signal, sig, None)
        if s is not None:
            try:
                signal.signal(s, lambda *_: stop_evt.set())
            except (ValueError, OSError):
                pass      # 윈도우/비메인스레드에서는 실패할 수 있다


if __name__ == "__main__":
    sys.exit(main())
