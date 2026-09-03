"""
전도 임계값 분석 — rosbag + rqt 대체

계획서 §6.2 "전도 감지 임계값 실험 데이터 수집"의 분석 도구.
현재 IMPACT_THRESHOLD_G = 2.8 이라는 숫자에는 아무 근거가 없다.
이 스크립트가 만드는 그래프가 그 숫자의 근거이자 보고서의 핵심 그림이 된다.

사용법
    python tools/analyze_logs.py                # logs/ 전체
    python tools/analyze_logs.py --dir logs
    python tools/analyze_logs.py --no-plot      # 표만

파일명 규칙: <시나리오>_<날짜>_<시각>.csv
    양성(전도): tipover_front, tipover_side, tipover_rear
    음성(일상): normal_walk, curb, sudden_stop, place_down, car_load, elevator

⚠ 실제 고령자를 대상으로 전도를 재현하지 말 것.
  더미(모래주머니/마네킹) 또는 매트 위 젊은 피험자로 대체한다.
⚠ 이 분석 전에 가속도계 측정범위(FSR)를 먼저 확인할 것.
  ±2 g로 설정돼 있으면 그래프가 2 g에서 잘려 나온다.
"""
import argparse
import glob
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import console  # noqa: E402

console.setup()

POSITIVE_PREFIXES = ("fall",)


def scenario_of(path):
    base = os.path.basename(path)
    return base.split("_2")[0] if "_2" in base else base.rsplit(".", 1)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="logs")
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()

    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("pandas가 필요합니다:  pip install pandas matplotlib")

    files = sorted(glob.glob(os.path.join(args.dir, "*.csv")))
    if not files:
        raise SystemExit(f"{args.dir}/ 에 CSV가 없습니다. "
                         f"먼저 `python safety_monitor.py --tag <시나리오>` 로 수집하세요.")

    rows, pos_peaks, neg_peaks = [], [], []
    plots = []

    for path in files:
        df = pd.read_csv(path)
        if df.empty:
            continue
        scen = scenario_of(path)
        is_pos = scen.startswith(POSITIVE_PREFIXES)
        peak = float(df.accel_g.max())
        tilt = float(df.tilt_deg.abs().max())
        # 충격 이후 자세가 유지되는지 (전도의 핵심 특징)
        after = df[df.accel_g > df.accel_g.max() * 0.8]
        tilt_after = float(after.tilt_deg.abs().mean()) if not after.empty else 0.0

        rows.append((scen, "양성" if is_pos else "음성",
                     peak, tilt, tilt_after, len(df)))
        (pos_peaks if is_pos else neg_peaks).append(peak)
        plots.append((scen, is_pos, df))

    print(f"\n{'시나리오':<16}{'구분':<6}{'최대 g':>8}{'최대 기울기':>12}"
          f"{'충격후 기울기':>14}{'샘플':>8}")
    print("-" * 66)
    for scen, kind, peak, tilt, ta, n in sorted(rows, key=lambda r: -r[2]):
        print(f"{scen:<16}{kind:<6}{peak:>8.2f}{tilt:>11.0f}°{ta:>13.0f}°{n:>8}")

    print("\n" + "=" * 66)
    if pos_peaks and neg_peaks:
        lo, hi = max(neg_peaks), min(pos_peaks)
        print(f"음성 최대: {lo:.2f} g   /   양성 최소: {hi:.2f} g")
        if hi > lo:
            print(f"✅ 분리 가능. 권장 IMPACT_THRESHOLD_G = {(lo + hi) / 2:.2f}")
            print(f"   (여유 구간 {lo:.2f} ~ {hi:.2f} g)")
        else:
            print("⚠ 두 분포가 겹칩니다. 가속도 임계값만으로는 분리할 수 없습니다.")
            print("  → TIPOVER_TILT_DEG(자세 조건)를 함께 써야 합니다. "
                  "위 표의 '충격후 기울기' 열을 비교하세요.")
    else:
        print("⚠ 양성/음성 시나리오가 모두 있어야 임계값을 결정할 수 있습니다.")
        print("  양성: tipover_front, tipover_side / 음성: curb, place_down, sudden_stop ...")
    print("=" * 66 + "\n")

    if args.no_plot:
        return
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib 미설치 — 그래프 생략:  pip install matplotlib)")
        return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    for scen, is_pos, df in plots:
        t = df.t - df.t.iloc[0]
        style = dict(lw=1.8, alpha=0.9) if is_pos else dict(lw=1.0, alpha=0.5)
        ax1.plot(t, df.accel_g, label=f"{scen}{' (전도)' if is_pos else ''}", **style)
        ax2.plot(t, df.tilt_deg.abs(), **style)

    ax1.axhline(2.8, ls="--", c="r", lw=1, label="현재 임계값 2.8 g")
    ax1.set_ylabel("가속도 벡터합 (g)")
    ax1.legend(fontsize=8, ncol=2)
    ax1.grid(alpha=0.3)

    ax2.axhline(60, ls="--", c="r", lw=1, label="TIPOVER_TILT_DEG = 60°")
    ax2.set_ylabel("기울기 (deg)")
    ax2.set_xlabel("시간 (s)")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3)

    fig.suptitle("시나리오별 충격량 · 자세 — 임계값 결정 근거")
    fig.tight_layout()
    out = os.path.join(args.dir, "threshold_analysis.png")
    fig.savefig(out, dpi=140)
    print(f"그래프 저장: {out}")
    plt.show()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
