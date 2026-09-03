"""
콘솔 출력 안전장치.

윈도우 콘솔의 기본 인코딩은 cp949다. ✅ ⚠ ✗ 🆘 같은 문자를 출력하지 못하고
`UnicodeEncodeError`로 **프로세스를 죽인다.**
안전 필수 프로세스가 로그 한 줄 때문에 죽는 것은 용납할 수 없고,
분석 도구가 표 하나 그리다 죽는 것도 곤란하다.

모든 진입점(safety_monitor, ui, tools/*)에서 맨 위에 한 번 호출한다.

    import console; console.setup()
"""
import sys


def setup():
    for stream in ("stdout", "stderr"):
        s = getattr(sys, stream, None)
        if s is None:
            continue
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def safe_print(*args, **kwargs):
    """어떤 경우에도 예외를 밖으로 내보내지 않는 print."""
    try:
        print(*args, **kwargs)
    except Exception:
        try:
            text = " ".join(str(a) for a in args)
            sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")
        except Exception:
            pass
