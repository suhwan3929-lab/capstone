"""
로그 재생 + 임계값 스윕 — 이 프로젝트에서 가장 중요한 분석 도구

해결하는 문제
    `IMPACT_THRESHOLD_G = 2.8`, `TIPOVER_TILT_DEG = 60` 이라는 숫자에 근거가 없다.
    심사에서 "왜 2.8입니까?"를 반드시 묻는다.

    임계값을 바꿀 때마다 실험을 다시 하는 것은 불가능하다.
    그래서 **기록해 둔 CSV를 실제 판정 코드에 다시 통과시킨다.**
    실시간이 아니라 가상 시계로 돌리므로 20초짜리 로그가 수십 ms에 끝나고,
    수백 개 임계값 조합을 한 번에 훑을 수 있다.

    ★ 재생과 실주행이 **완전히 같은 tipover_monitor 코드**를 쓴다.
      별도의 오프라인 구현을 만들면 "재생에서는 되는데 실기에서 안 되는" 문제가 생긴다.

사용법
    # 한 파일이 어떻게 판정되는지 보기
    python tools/replay.py logs/tipover_front_20260821_143335.csv -v

    # logs/ 전체를 현재 임계값으로 채점
    python tools/replay.py logs/

    # 임계값 조합을 전수 탐색해서 최적점을 찾는다  ← 보고서용
    python tools/replay.py logs/ --sweep

파일명 규칙 (양성/음성 자동 분류)
    양성: tipover_*     (tipover_front, tipover_side, tipover_rear)
    음성: 그 외 전부    (normal_walk, curb, sudden_stop, place_down, car_load, ...)
    단 `*_recover` 가 들어가면 '해제되어야 하는' 케이스로 음성 취급한다.
    (용어 변경 이전의 fall_* 로그도 양성으로 인식한다 — 하위 호환)
"""
import argparse
import csv
import glob
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import console  # noqa: E402

console.setup()
import notifier  # noqa: E402
from schema import GpsFix, ImuSample  # noqa: E402
from states import TIPOVER_CONFIRMED, TIPOVER_REPORTED  # noqa: E402

# 재생 중에는 실제 알림을 보내지 않는다
notifier.send_preliminary = lambda *a, **k: None
notifier.send_confirmed = lambda *a, **k: None
notifier.send_cancelled = lambda *a, **k: None
notifier.start = lambda *a, **k: None

from tipover_monitor import TipoverMonitor  # noqa: E402


class _VirtualClock:
    """CSV의 타임스탬프를 시간 소스로 쓴다. 실시간을 기다리지 않는다."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


#: 양성(전도) 샘플로 취급할 파일명 접두사.
#  "tipover" 가 현재 규약이고, "fall" 은 용어 변경 이전에 수집한 로그 호환용이다.
POSITIVE_PREFIXES = ("tipover", "fall")


def is_positive(name: str) -> bool:
    """
    파일명으로 양성/음성을 가른다.
      양성: tipover_front / tipover_side / tipover_rear
      음성: 그 외 전부. 단 *_recover 는 '해제되어야 하는' 케이스이므로 음성.
    """
    base = os.path.basename(name).lower()
    if "_recover" in base:
        return False
    return base.startswith(POSITIVE_PREFIXES)


def scenario_of(path) -> str:
    base = os.path.basename(path)
    parts = base.rsplit(".", 1)[0].split("_")
    # 뒤쪽의 날짜/시각 토큰을 떼어낸다
    while parts and parts[-1].isdigit():
        parts.pop()
    return "_".join(parts) or base


def replay_file(path, verbose=False):
    """
    한 CSV를 재생한다.
    반환: (사고확정 여부, 확정까지 걸린 시간(초) 또는 None, 샘플 수, 최대 g, 최대 기울기)
    """
    clock = _VirtualClock()
    logs = []
    mon = TipoverMonitor(
        log_callback=(lambda m, l="INFO": logs.append((clock.t, l, m))),
        clock=clock)

    gps = GpsFix(valid=True, lat=35.0, lon=127.0, fix_quality=4, satellites=18)
    fired_at = None
    t0 = None
    n = 0
    peak_g = 0.0
    peak_tilt = 0.0

    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                t = float(row["t"])
                imu = ImuSample(
                    t_capture=t,
                    roll_deg=float(row["roll_deg"]),
                    pitch_deg=float(row["pitch_deg"]),
                    accel_g=float(row["accel_g"]),
                    gyro_dps=float(row.get("gyro_dps") or 0.0),
                    valid=True)
            except (KeyError, ValueError, TypeError):
                continue

            if t0 is None:
                t0 = t
            clock.t = t
            gps.t_capture = t
            n += 1
            peak_g = max(peak_g, imu.accel_g)
            peak_tilt = max(peak_tilt, imu.tilt_deg)

            mon.step(imu, gps)
            if fired_at is None and mon.state in (TIPOVER_CONFIRMED, TIPOVER_REPORTED):
                fired_at = t - t0

    if verbose:
        for t, lvl, msg in logs:
            print(f"    +{t - (t0 or t):6.2f}s [{lvl:5}] {msg}")
    return fired_at is not None, fired_at, n, peak_g, peak_tilt


def collect(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "*.csv")))
        else:
            files.append(p)
    return [f for f in files if os.path.getsize(f) > 64]


# ══════════════════════════════════════════════════════════
# 단일 채점
# ══════════════════════════════════════════════════════════
def cmd_score(files, verbose):
    print(f"\n현재 임계값:  충격 {config.IMPACT_THRESHOLD_G} g  |  "
          f"기울기 {config.TIPOVER_TILT_DEG}°  |  "
          f"안정화 {config.STABILIZE_TIME}s  |  관찰 {config.CHECK_TIME}s\n")
    print(f"{'파일':<34}{'구분':<6}{'판정':<10}{'확정까지':>9}"
          f"{'최대g':>8}{'최대기울기':>11}")
    print("-" * 80)

    tp = fp = tn = fn = 0
    for path in files:
        pos = is_positive(path)
        fired, at, n, pg, pt = replay_file(path, verbose)
        if pos and fired:
            tp += 1
            verdict, mark = "탐지", "OK"
        elif pos and not fired:
            fn += 1
            verdict, mark = "미탐 ✗", "MISS"
        elif not pos and fired:
            fp += 1
            verdict, mark = "오탐 ✗", "FALSE"
        else:
            tn += 1
            verdict, mark = "정상", "OK"
        name = os.path.basename(path)[:33]
        at_s = f"{at:6.1f}s" if at is not None else "     -"
        print(f"{name:<34}{'양성' if pos else '음성':<6}{verdict:<10}"
              f"{at_s:>9}{pg:>8.2f}{pt:>10.0f}°")
        if verbose:
            print()

    print("-" * 80)
    _print_metrics(tp, fp, tn, fn)


def _print_metrics(tp, fp, tn, fn):
    total = tp + fp + tn + fn
    if not total:
        print("데이터가 없습니다.")
        return
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    print(f"\n  탐지(TP) {tp}   미탐(FN) {fn}   오탐(FP) {fp}   정상(TN) {tn}")
    print(f"  재현율(놓치지 않음) {recall:.2f}   정밀도(헛울리지 않음) {prec:.2f}")
    if fn:
        print("\n  ⚠ 미탐이 있습니다. 전도를 놓치는 것이 헛울리는 것보다 위험합니다.")
        print("    → 충격 임계값 또는 기울기 임계값을 낮춰보세요.")
    if fp:
        print("\n  ⚠ 오탐이 있습니다. 오경보 한 번에 보호자의 신뢰가 무너집니다.")
        print("    → 기울기 임계값을 높이거나 관찰 시간을 늘려보세요.")
    if not fn and not fp and total >= 4:
        print("\n  ✅ 이 데이터셋에서는 완전 분리됩니다. 보고서에 근거로 쓸 수 있습니다.")


# ══════════════════════════════════════════════════════════
# 임계값 스윕
# ══════════════════════════════════════════════════════════
def cmd_sweep(files, args):
    g_vals = _frange(args.g_min, args.g_max, args.g_step)
    t_vals = _frange(args.tilt_min, args.tilt_max, args.tilt_step)

    pos_files = [f for f in files if is_positive(f)]
    neg_files = [f for f in files if not is_positive(f)]
    if not pos_files or not neg_files:
        print("⚠ 양성(tipover_*)과 음성 로그가 모두 있어야 스윕이 의미가 있습니다.")
        print(f"   현재 양성 {len(pos_files)}개 / 음성 {len(neg_files)}개")
        if not pos_files:
            print("   → 더미/매트를 이용해 tipover_front / tipover_side / tipover_rear "
                  "를 수집하세요.")
        return

    print(f"\n임계값 스윕: 충격 {len(g_vals)}종 × 기울기 {len(t_vals)}종 "
          f"= {len(g_vals) * len(t_vals)}조합 × {len(files)}파일\n")

    orig = (config.IMPACT_THRESHOLD_G, config.TIPOVER_TILT_DEG)
    results = []
    for g in g_vals:
        for t in t_vals:
            config.IMPACT_THRESHOLD_G = g
            config.TIPOVER_TILT_DEG = t
            tp = sum(1 for f in pos_files if replay_file(f)[0])
            fp = sum(1 for f in neg_files if replay_file(f)[0])
            fn = len(pos_files) - tp
            tn = len(neg_files) - fp
            # 미탐(전도를 놓침)에 오탐의 3배 벌점을 준다.
            # 안전 시스템에서 두 오류의 무게는 같지 않다.
            cost = fn * 3 + fp
            results.append((cost, -tp, g, t, tp, fn, fp, tn))
    config.IMPACT_THRESHOLD_G, config.TIPOVER_TILT_DEG = orig

    results.sort()
    print(f"{'순위':>4}{'충격(g)':>9}{'기울기(°)':>11}"
           f"{'탐지':>6}{'미탐':>6}{'오탐':>6}{'정상':>6}{'벌점':>7}")
    print("-" * 56)
    for i, (cost, _, g, t, tp, fn, fp, tn) in enumerate(results[:15], 1):
        print(f"{i:>4}{g:>9.2f}{t:>11.0f}{tp:>6}{fn:>6}{fp:>6}{tn:>6}{cost:>7}")

    best = results[0]
    cost, _, g, t, tp, fn, fp, tn = best
    print("\n" + "=" * 62)
    print("최적 조합 — config_local.py 에 다음을 추가하세요:")
    print(f"\n    IMPACT_THRESHOLD_G = {g:.2f}")
    print(f"    TIPOVER_TILT_DEG = {t:.0f}\n")
    print(f"  이 조합에서: 탐지 {tp}/{tp + fn}, 오탐 {fp}/{fp + tn}")
    if cost == 0:
        # 완전 분리되는 구간의 중앙을 고르면 여유(margin)가 최대가 된다
        zero = [(gg, tt) for c, _, gg, tt, *_ in results if c == 0]
        gs = sorted({z[0] for z in zero})
        ts = sorted({z[1] for z in zero})
        print(f"\n  ✅ 완전 분리 구간: 충격 {gs[0]:.2f}~{gs[-1]:.2f} g, "
              f"기울기 {ts[0]:.0f}~{ts[-1]:.0f}°")
        print(f"     여유를 최대로 하려면 구간 중앙값을 쓰세요: "
              f"충격 {(gs[0] + gs[-1]) / 2:.2f} g, 기울기 {(ts[0] + ts[-1]) / 2:.0f}°")
        print("\n  ※ 이 표와 구간이 보고서의 임계값 근거 자료가 됩니다.")
    else:
        print("\n  ⚠ 완전 분리되는 조합이 없습니다.")
        print("     가속도·기울기만으로는 부족하다는 뜻입니다. 개선 방향:")
        print("       · 관찰 시간(CHECK_TIME)을 늘린다")
        print("       · 충격 후 자이로 정지 지속시간을 추가 조건으로 넣는다")
        print("       · 데이터를 더 모은다 (시나리오당 최소 5회 반복 권장)")
    print("=" * 62)


def _frange(a, b, step):
    out, x = [], a
    while x <= b + 1e-9:
        out.append(round(x, 3))
        x += step
    return out


def main():
    ap = argparse.ArgumentParser(description="전도 로그 재생 및 임계값 탐색")
    ap.add_argument("paths", nargs="*", default=[config.LOG_DIR])
    ap.add_argument("-v", "--verbose", action="store_true", help="판정 과정 출력")
    ap.add_argument("--sweep", action="store_true", help="임계값 전수 탐색")
    ap.add_argument("--g-min", type=float, default=1.8)
    ap.add_argument("--g-max", type=float, default=5.0)
    ap.add_argument("--g-step", type=float, default=0.2)
    ap.add_argument("--tilt-min", type=float, default=30.0)
    ap.add_argument("--tilt-max", type=float, default=80.0)
    ap.add_argument("--tilt-step", type=float, default=5.0)
    args = ap.parse_args()

    files = collect(args.paths or [config.LOG_DIR])
    if not files:
        print(f"CSV가 없습니다. 먼저 데이터를 수집하세요:\n"
              f"  python safety_monitor.py --tag tipover_front\n"
              f"  python safety_monitor.py --tag curb\n"
              f"(하드웨어가 없으면 --sim --scenario 로 모의 데이터 생성 가능)")
        return 1

    if args.sweep:
        cmd_sweep(files, args)
    else:
        cmd_score(files, args.verbose)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
