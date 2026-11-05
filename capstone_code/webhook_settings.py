"""systemd용 웹훅 설정을 비밀값 출력 없이 저장하고 읽는다."""
import os
from pathlib import Path
import re
import shlex
import stat
import tempfile
import time
from urllib.parse import urlsplit

DEFAULT_PATH = Path("/etc/walker/secrets.env")
_KEYS = {"WALKER_NOTIFY_BACKEND", "WALKER_WEBHOOK_URL"}


def validate_url(url):
    if not url or not url.isascii() or any(c.isspace() for c in url):
        raise ValueError("웹훅 URL 형식을 확인하세요")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc != "discord.com" or parts.fragment
            or not re.fullmatch(r"/api/webhooks/[0-9]+/[A-Za-z0-9_.-]+/?", parts.path)):
        raise ValueError("Discord의 웹훅 URL 복사 기능으로 가져온 주소가 필요합니다")
    return url


def save_webhook(path, url):
    url = validate_url(url)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("설정 경로는 심볼릭 링크를 사용할 수 없습니다")
    previous = path.read_bytes() if path.exists() else b""
    kept = []
    for line in previous.decode("utf-8").splitlines():
        key = line.split("=", 1)[0].strip().removeprefix("export ").strip()
        if key not in _KEYS:
            kept.append(line)
    kept += ["WALKER_NOTIFY_BACKEND=webhook", "WALKER_WEBHOOK_URL=" + url]
    if previous:
        backup = path.with_name(path.name + ".before-webhook-" + str(time.time_ns()))
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(previous)
    fd, temporary = tempfile.mkstemp(prefix=".webhook-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(kept) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_webhook(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("설정 파일은 심볼릭 링크를 사용할 수 없습니다")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("설정 파일 권한은 600이어야 합니다")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, raw = line.partition("=")
        key = key.strip()
        if sep and key in _KEYS:
            tokens = shlex.split(raw, comments=True)
            if len(tokens) != 1:
                raise ValueError("웹훅 설정 파일 형식을 확인하세요")
            values[key] = tokens[0]
    if values.get("WALKER_NOTIFY_BACKEND") != "webhook":
        raise ValueError("저장된 알림 방식이 webhook이 아닙니다")
    return validate_url(values.get("WALKER_WEBHOOK_URL", ""))
