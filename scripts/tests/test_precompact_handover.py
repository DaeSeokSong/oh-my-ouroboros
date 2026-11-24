"""precompact-handover-check.sh 회귀 테스트 (자체 완결 — 임시 저장소를 만들어 mtime 만 바꾼다).

실행: python3 ~/.claude/scripts/tests/test_precompact_handover.py → 실패 0 이면 exit 0
케이스: 파일 없음 → 침묵 / 방금 갱신 → 침묵 / 59분 전 → 침묵(경계) / 61분 전 → 경고 / 하루 전 → 경고(분 수 표기) /
        git 저장소가 아니어도 cwd 기준으로 동작 / 어떤 경우에도 exit 0(compact 를 막지 않는다).
REF: knowledge/harness/code-history/scripts__tests__test_precompact_handover.py.md
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOOK = Path.home() / ".claude/scripts/precompact-handover-check.sh"


def enc(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def run(root: str, age_min: float | None, git_init: bool = True, sub: str | None = None, legacy: bool = False):
    if git_init:
        subprocess.run(["git", "init", "-q", root], check=True, capture_output=True)
    home = Path(root) / "fakehome"
    if age_min is not None:
        d = Path(root) / "short-term" if legacy else home / ".claude/projects" / enc(root) / "memory/short-term"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "handover.md"
        f.write_text("# handover\n", encoding="utf-8")
        when = time.time() - age_min * 60
        os.utime(f, (when, when))
    cwd = root
    if sub:
        cwd = str(Path(root) / sub)
        Path(cwd).mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"session_id": "t", "trigger": "auto", "cwd": cwd})
    r = subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True, cwd=cwd,
                       env=dict(os.environ, HOME=str(home)), check=False)
    return r.returncode, r.stdout.strip()


CASES = [
    ("handover.md 없음 → 침묵", None, True, False),
    ("방금 갱신 → 침묵", 0, True, False),
    ("59분 전 → 침묵 (경계 아래)", 59, True, False),
    ("61분 전 → 경고 (경계 위)", 61, True, True),
    ("하루 전 → 경고", 60 * 24, True, True),
    ("git 저장소 아님 + 오래됨 → 경고 (cwd 기준)", 120, False, True),
    ("git 저장소 아님 + 파일 없음 → 침묵", None, False, False),
]

fail = 0
for name, age, git_init, want_warn in CASES:
    with tempfile.TemporaryDirectory() as root:
        rc, out = run(root, age, git_init)
    warned = "HANDOVER_STALE" in out
    ok = warned == want_warn and rc == 0
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}: warn={warned} (기대 {want_warn}) rc={rc}")
    if not ok and out:
        print(f"     출력: {out[:200]}")

with tempfile.TemporaryDirectory() as root:
    rc, out = run(root, 125, True)
ok = "125분 전" in out and rc == 0
fail += 0 if ok else 1
print(f"{'OK ' if ok else 'FAIL'} 경과 분 표기 (125분): {out[:120]!r}")

with tempfile.TemporaryDirectory() as root:
    rc, out = run(root, 90, True)
try:
    ok = rc == 0 and "HANDOVER_STALE" in json.loads(out)["systemMessage"]
except Exception:  # noqa: BLE001
    ok = False
fail += 0 if ok else 1
print(f"{'OK ' if ok else 'FAIL'} 경고는 systemMessage JSON: {out[:120]!r}")

with tempfile.TemporaryDirectory() as root:
    rc, out = run(root, 120, True, sub="pkg/inner")
ok = "HANDOVER_STALE" in out and rc == 0
fail += 0 if ok else 1
print(f"{'OK ' if ok else 'FAIL'} cwd 가 하위 폴더 → git 뿌리 memory 폴백: {out[:80]!r}")

with tempfile.TemporaryDirectory() as root:
    rc, out = run(root, 120, True, legacy=True)
ok = "HANDOVER_STALE" not in out and rc == 0
fail += 0 if ok else 1
print(f"{'OK ' if ok else 'FAIL'} 종전 경로는 더 이상 보지 않음: {out[:80]!r}")

total = len(CASES) + 4
print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({total} cases)")
sys.exit(1 if fail else 0)
