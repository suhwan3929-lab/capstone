"""
LiDAR 프레임 포맷 판별 도구

해결하는 문제
    `sensors/lidar_serial.py`의 payload 오프셋(5)과 '2바이트 리틀엔디안' 가정에는
    근거가 없다. CygLiDAR 3D 모드는 12비트 패킹(2점=3바이트)일 가능성이 있고,
    그 경우 파싱 결과는 '그럴듯하지만 완전히 틀린' 값이 된다.
    숫자가 그럴듯해서 틀린 줄을 모르는 것이 이 버그의 가장 위험한 점이다.

이 도구는 추측 대신 **측정**한다.

사용법
    # 1) 원시 프레임을 파일로 덤프 (하드웨어 필요)
    python tools/lidar_probe.py dump --port COM3 --seconds 5

    # 2) 덤프에서 후보 레이아웃을 전수 탐색해 순위를 매긴다
    python tools/lidar_probe.py analyze logs/lidar_raw_COM3.bin

    # 3) 줄자로 잰 실제 거리를 주면 정답을 확정할 수 있다 (가장 확실)
    python tools/lidar_probe.py analyze logs/lidar_raw_COM3.bin --truth 1.00

권장 절차 (10분)
    평평한 판을 정면 1.0 m에 세우고 dump → analyze --truth 1.00
    1순위로 나온 (offset, packing)을 config_local.py 에 적는다.
        LIDAR_PAYLOAD_OFFSET = <값>
        LIDAR_PACKING = "<값>"
"""
import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import console  # noqa: E402

console.setup()

HEADER = b"\x5A\x77\xFF"
MAX_PAYLOAD = 4096


# ══════════════════════════════════════════════════════════
# 디코더 후보
# ══════════════════════════════════════════════════════════
def decode_u16le(buf):
    return [buf[i] | (buf[i + 1] << 8) for i in range(0, len(buf) - 1, 2)]


def decode_u16be(buf):
    return [(buf[i] << 8) | buf[i + 1] for i in range(0, len(buf) - 1, 2)]


def decode_u12(buf):
    """2점 = 3바이트 패킹. ToF 센서에서 흔한 형식."""
    out = []
    for i in range(0, len(buf) - 2, 3):
        b0, b1, b2 = buf[i], buf[i + 1], buf[i + 2]
        out.append(((b1 & 0x0F) << 8) | b0)
        out.append((b2 << 4) | (b1 >> 4))
    return out


def decode_u12_alt(buf):
    """12비트 패킹의 반대 니블 배치."""
    out = []
    for i in range(0, len(buf) - 2, 3):
        b0, b1, b2 = buf[i], buf[i + 1], buf[i + 2]
        out.append((b0 << 4) | (b1 >> 4))
        out.append(((b1 & 0x0F) << 8) | b2)
    return out


DECODERS = {
    "u16le": decode_u16le,
    "u16be": decode_u16be,
    "u12": decode_u12,
    "u12alt": decode_u12_alt,
}


# ══════════════════════════════════════════════════════════
# 프레임 추출
# ══════════════════════════════════════════════════════════
def iter_frames(data: bytes):
    """롤링 버퍼 방식으로 프레임을 잘라낸다 (헤더 오탐 시 1바이트만 전진)."""
    i = 0
    n = len(data)
    while True:
        i = data.find(HEADER, i)
        if i < 0 or i + 6 > n:
            return
        plen = data[i + 3] | (data[i + 4] << 8)
        if plen == 0 or plen > MAX_PAYLOAD or i + 5 + plen + 1 > n:
            i += 1
            continue
        yield data[i + 5:i + 5 + plen], data[i + 5 + plen]
        i += 5 + plen + 1


# ══════════════════════════════════════════════════════════
# dump
# ══════════════════════════════════════════════════════════
def cmd_dump(args):
    import serial

    out = pathlib.Path(config.LOG_DIR)
    out.mkdir(parents=True, exist_ok=True)
    safe = args.port.replace("/", "_").replace("\\", "_").replace(":", "")
    path = out / f"lidar_raw_{safe}.bin"

    print(f"포트 {args.port} @ {args.baud} 로 {args.seconds}초 수집합니다...")
    if args.truth:
        print(f"※ 정면 {args.truth} m 에 판이 세워져 있는지 확인하세요.")

    import time
    total = 0
    with serial.Serial(args.port, args.baud, timeout=1) as ser, \
            open(path, "wb") as f:
        ser.reset_input_buffer()
        if args.start_cmd:
            ser.write(bytes.fromhex(args.start_cmd.replace(" ", "")))
            print(f"시작 명령 전송: {args.start_cmd}")
        end = time.time() + args.seconds
        while time.time() < end:
            chunk = ser.read(max(1, min(ser.in_waiting, 16384)))
            if chunk:
                f.write(chunk)
                total += len(chunk)

    print(f"\n{total:,} 바이트 저장 → {path}")
    if total == 0:
        print("⚠ 한 바이트도 받지 못했습니다. 통신속도 또는 시작 명령을 확인하세요.")
        return 1
    frames = list(iter_frames(path.read_bytes()))
    print(f"프레임 {len(frames)}개 인식 "
          f"(페이로드 길이: {sorted({len(p) for p, _ in frames})})")
    if not frames:
        print("⚠ 헤더 5A 77 FF 를 찾지 못했습니다. 프로토콜이 다를 수 있습니다.")
        return 1
    print(f"\n다음 명령으로 분석하세요:\n"
          f"  python tools/lidar_probe.py analyze {path}"
          f"{' --truth ' + str(args.truth) if args.truth else ''}")
    return 0


# ══════════════════════════════════════════════════════════
# analyze
# ══════════════════════════════════════════════════════════
def score_layout(values_mm, truth_m=None):
    """
    후보 레이아웃의 그럴듯함을 점수화한다.
      * 유효 거리 범위 안에 들어오는 값의 비율 (높을수록 좋음)
      * 이웃 점 간 급변 비율 (낮을수록 좋음 — 실제 장면은 연속적이다)
      * 정답 거리를 알면 그 값 근처에 몰려 있는 비율 (결정적)
    """
    if len(values_mm) < 16:
        return 0.0, {}

    lo = config.LIDAR_MIN_VALID_M * 1000
    hi = config.LIDAR_MAX_VALID_M * 1000
    in_range = [v for v in values_mm if lo <= v <= hi]
    frac_valid = len(in_range) / len(values_mm)

    # 연속성: 이웃한 두 점이 1 m 이상 튀는 비율
    jumps = sum(1 for a, b in zip(values_mm, values_mm[1:]) if abs(a - b) > 1000)
    smooth = 1.0 - jumps / max(1, len(values_mm) - 1)

    detail = {"유효비율": frac_valid, "연속성": smooth,
              "중앙값m": (sorted(in_range)[len(in_range) // 2] / 1000.0)
                        if in_range else 0.0}

    score = frac_valid * 0.45 + smooth * 0.25

    if truth_m is not None:
        tol = max(80.0, truth_m * 1000 * 0.12)     # ±12% 또는 최소 8 cm
        near = sum(1 for v in values_mm if abs(v - truth_m * 1000) <= tol)
        frac_near = near / len(values_mm)
        detail["정답근접"] = frac_near
        score = score * 0.4 + frac_near * 0.6      # 정답이 있으면 그쪽이 지배적
    return score, detail


def cmd_analyze(args):
    data = pathlib.Path(args.path).read_bytes()
    frames = [p for p, _cs in iter_frames(data)]
    if not frames:
        print("프레임을 찾지 못했습니다.")
        return 1

    print(f"프레임 {len(frames)}개, 페이로드 길이 "
          f"{sorted({len(p) for p in frames})}\n")

    # 체크섬 알고리즘 판별
    _report_checksum(data)

    sample = frames[len(frames) // 2:len(frames) // 2 + 8] or frames[:8]
    results = []
    for offset in range(0, args.max_offset + 1):
        for name, dec in DECODERS.items():
            vals = []
            for p in sample:
                if len(p) <= offset + 3:
                    continue
                vals.extend(dec(p[offset:]))
            if not vals:
                continue
            sc, detail = score_layout(vals, args.truth)
            results.append((sc, offset, name, detail, len(vals) // len(sample)))

    results.sort(reverse=True, key=lambda r: r[0])
    print(f"{'점수':>6}  {'오프셋':>6}  {'패킹':<8}{'점/프레임':>10}"
          f"{'유효비율':>10}{'연속성':>8}{'중앙값(m)':>11}"
          f"{'  정답근접' if args.truth else ''}")
    print("-" * (76 + (10 if args.truth else 0)))
    for sc, off, name, d, npts in results[:15]:
        row = (f"{sc:>6.3f}  {off:>6}  {name:<8}{npts:>10}"
               f"{d['유효비율']:>10.2f}{d['연속성']:>8.2f}{d['중앙값m']:>11.2f}")
        if args.truth:
            row += f"{d.get('정답근접', 0):>10.2f}"
        print(row)

    if results:
        sc, off, name, d, _ = results[0]
        print("\n" + "=" * 66)
        if args.truth and d.get("정답근접", 0) < 0.15:
            print("⚠ 정답 거리 근처에 몰리는 레이아웃이 없습니다.")
            print("  프로토콜이 예상과 다르거나, 판이 화각 밖일 수 있습니다.")
            print("  → Cygbot 공식 ROS 2 드라이버 소스에서 파싱 규칙을 확인하세요.")
        else:
            print("1순위 후보 — config_local.py 에 다음을 추가하세요:")
            print(f"\n    LIDAR_PAYLOAD_OFFSET = {off}")
            print(f'    LIDAR_PACKING = "{name}"\n')
            print(f"  (중앙값 {d['중앙값m']:.2f} m — 실제와 맞는지 눈으로 확인할 것)")
        print("=" * 66)
    return 0


def _report_checksum(data):
    frames = list(iter_frames(data))[:60]
    if not frames:
        return
    hits = {"xor": 0, "sum8": 0}
    for payload, cs in frames:
        x = 0
        for b in payload:
            x ^= b
        if x == cs:
            hits["xor"] += 1
        if (sum(payload) & 0xFF) == cs:
            hits["sum8"] += 1
    n = len(frames)
    print("체크섬 판별 (프레임 %d개):" % n)
    for k, v in hits.items():
        mark = "  ← 일치" if v == n else ""
        print(f"    {k:<6} {v}/{n}{mark}")
    best = [k for k, v in hits.items() if v == n]
    if best:
        print(f'    → config_local.py 에  LIDAR_CHECKSUM = "{best[0]}"  를 추가하세요.\n')
    else:
        print("    → 두 방식 모두 불일치. 체크섬 범위가 헤더/길이를 포함할 수 있습니다.\n")


def main():
    ap = argparse.ArgumentParser(description="CygLiDAR 프레임 포맷 판별")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dump", help="원시 바이트 수집")
    d.add_argument("--port", default=config.LIDAR_PORT_LEFT)
    d.add_argument("--baud", type=int, default=config.LIDAR_BAUD)
    d.add_argument("--seconds", type=float, default=5.0)
    d.add_argument("--truth", type=float, default=None,
                   help="정면에 세워둔 판까지의 실제 거리(m)")
    d.add_argument("--start-cmd", default="5A77FF0200010003",
                   help="측정 시작 명령 (hex)")
    d.set_defaults(func=cmd_dump)

    a = sub.add_parser("analyze", help="후보 레이아웃 전수 탐색")
    a.add_argument("path")
    a.add_argument("--truth", type=float, default=None,
                   help="줄자로 잰 실제 거리(m). 주면 판별 정확도가 크게 올라간다")
    a.add_argument("--max-offset", type=int, default=16)
    a.set_defaults(func=cmd_analyze)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
