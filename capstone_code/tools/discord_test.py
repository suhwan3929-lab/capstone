"""설정된 Discord 채널에 명시적인 시험 메시지 한 건 전송. 스풀은 읽지 않는다."""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import console
import notifier


def main():
    console.setup()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--send", action="store_true", help="테스트 채널로 메시지 전송")
    args = ap.parse_args()
    if not args.send:
        ap.error("전송하려면 --send를 지정하세요")
    if not notifier.is_configured():
        print("Discord 설정 또는 requests 설치를 확인하세요. 비밀값은 출력하지 않습니다.")
        return 1
    notifier._log = lambda msg, level="INFO": print(level, msg, flush=True)
    ok = notifier._post_with_retry({
        "content": "🧪 [연결 시험] 보행기 Discord 신고 연결 확인 — 실제 사고가 아닙니다.",
        "allowed_mentions": {"parse": []},
    })
    print("Discord 전송 성공 — 채널에서 시험 메시지를 확인하세요." if ok else "Discord 전송 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
