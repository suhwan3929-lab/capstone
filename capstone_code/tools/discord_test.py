"""설정된 Discord 채널에 명시적인 시험 메시지 한 건 전송. 스풀은 읽지 않는다."""
import argparse
import getpass
import pathlib
import sys
import warnings

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import console
import config
import notifier


def prompt_bot_settings():
    """채널과 토큰을 이번 실행에서만 사용한다. 파일에는 저장하지 않는다."""
    channel = input("시험용 텍스트 채널 ID: ").strip()
    if not (channel.isascii() and channel.isdigit() and int(channel) > 0):
        print("채널 ID는 양의 정수여야 합니다. 서버 ID가 아닌 채널 ID를 복사하세요.")
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            token = getpass.getpass("봇 토큰 (화면에 표시되지 않음): ").strip()
    except getpass.GetPassWarning:
        print("숨김 입력을 사용할 수 없습니다. PuTTY 터미널에서 직접 실행하세요.")
        return False
    if not token or any(c.isspace() for c in token):
        print("봇 토큰이 비었거나 공백이 있습니다. 'Bot ' 접두사 없이 입력하세요.")
        return False
    config.NOTIFY_BACKEND = "bot"
    config.DISCORD_CHANNEL_ID = channel
    config.DISCORD_BOT_TOKEN = token
    print(f"시험 대상 채널 ID: {channel}. 실제 사고가 아닌 연결 시험 메시지를 보냅니다.")
    return True


def main():
    console.setup()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--send", action="store_true", help="테스트 채널로 메시지 전송")
    ap.add_argument("--prompt", action="store_true", help="채널 ID와 봇 토큰을 이번 실행에만 입력")
    args = ap.parse_args()
    if not args.send:
        ap.error("전송하려면 --send를 지정하세요")
    if args.prompt:
        if not notifier.REQUESTS_AVAILABLE:
            print("requests가 설치된 Python으로 실행하세요. 아직 입력하거나 전송하지 않았습니다.")
            return 1
        try:
            if not prompt_bot_settings():
                return 1
        except (EOFError, KeyboardInterrupt):
            print("\n시험을 취소했습니다. 메시지를 전송하지 않았습니다.")
            return 1
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
