"""Pi에 기존 웹훅을 저장한다. 알림 전송이나 서비스 시작은 하지 않는다."""
import getpass
import os
import pathlib
import sys
import warnings

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from webhook_settings import DEFAULT_PATH, save_webhook


def main():
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        print("Pi에서 sudo python3 tools/configure_webhook.py로 실행하세요")
        return 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            url = getpass.getpass("고정할 기존 웹훅 URL (숨김): ").strip()
        save_webhook(DEFAULT_PATH, url)
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print("입력을 취소했거나 숨김 입력을 사용할 수 없습니다. 저장하지 않았습니다.")
        return 1
    except (OSError, ValueError):
        print("저장 실패: 웹훅 주소 형식과 설정 파일 경로/권한을 확인하세요")
        return 1
    print("WEBHOOK_SAVED: /etc/walker/secrets.env (권한 600)")
    print("현재 실행 중인 안전감시 시험과 서비스 시작 설정은 바꾸지 않았습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
