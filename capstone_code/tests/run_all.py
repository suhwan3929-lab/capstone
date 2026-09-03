"""
테스트 실행기 — pytest 없이도 돌아간다.

    python tests/run_all.py
    python tests/run_all.py -v

pytest가 설치되어 있으면 `pytest tests/` 도 그대로 동작한다.
8인 팀에서 각자 환경이 다르므로 의존성 없이 돌아가는 경로를 준비해 둔다.

코드를 고칠 때마다 이걸 먼저 돌릴 것.
특히 tipover_monitor.py 를 건드렸다면 반드시.
"""
import importlib
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import console  # noqa: E402

console.setup()

MODULES = ["test_tipover_fsm", "test_components"]


def run():
    verbose = "-v" in sys.argv
    passed, failed = [], []

    for modname in MODULES:
        mod = importlib.import_module(modname)
        tests = [(n, getattr(mod, n)) for n in sorted(dir(mod))
                 if n.startswith("test_") and callable(getattr(mod, n))]
        print(f"\n── {modname}  ({len(tests)}개) " + "─" * (44 - len(modname)))
        for name, fn in tests:
            try:
                fn()
                passed.append(name)
                print(f"  PASS  {name}")
            except Exception as e:
                failed.append((modname, name, e, traceback.format_exc()))
                print(f"  FAIL  {name}  →  {type(e).__name__}: {e}")

    print("\n" + "=" * 62)
    print(f"  통과 {len(passed)}  /  실패 {len(failed)}")
    print("=" * 62)

    if failed:
        for modname, name, e, tb in failed:
            print(f"\n── 실패 상세: {modname}.{name} " + "─" * 20)
            print(tb if verbose else f"{type(e).__name__}: {e}")
        if not verbose:
            print("\n(-v 로 실행하면 전체 스택 트레이스를 볼 수 있습니다)")
        return 1

    print("\n  전체 통과. 안심하고 커밋하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
