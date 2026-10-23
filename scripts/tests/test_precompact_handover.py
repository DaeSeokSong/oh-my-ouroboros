#!/usr/bin/env python3
"""precompact-handover-check.sh 회귀 테스트 (자체 완결 — 임시 저장소를 만들어 mtime 만 바꾼다).

실행: python3 ~/.claude/scripts/tests/test_precompact_handover.py → 실패 0 이면 exit 0
케이스: 파일 없음 → 침묵 / 방금 갱신 → 침묵 / 59분 전 → 침묵(경계) / 61분 전 → 경고 / 하루 전 → 경고(분 수 표기) /
        git 저장소가 아니어도 cwd 기준으로 동작 / 어떤 경우에도 exit 0(compact 를 막지 않는다).
경계(60분)를 양쪽에서 확인하는 이유: 경보가 너무 자주 뜨면 배경 소음이 되고, 너무 늦게 뜨면 의미가 없다.
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
    """Claude Code 프로젝트 폴더 이름 규칙: 영숫자 외 문자는 '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def run(root: str, age_min: float | None, git_init: bool = True, sub: str | None = None, legacy: bool = False):
    """root 의 프로젝트 memory(가짜 HOME 아래 projects/<이름>/memory/short-term)에 handover.md 를 age_min 분 전으로 만들어
    훅을 돌린다(2026-10-01 감사: 실제 규칙 경로). age_min=None 이면 파일을 만들지 않는다. sub 는 세션 cwd 를 하위 폴더로
    주어 git 뿌리 폴백을 확인한다. legacy=True 면 종전의 존재하지 않는 경로 `<저장소>/short-term/handover.md` 에 만든다."""
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
                       env=dict(os.environ, HOME=str(home)))
    return r.returncode, r.stdout.strip()


# (이름, 경과 분, git 저장소 여부, 경고 기대)
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

# 경고 문구에 경과 분이 실제로 들어가는지 («N분 전» 이 비면 사용자가 판단할 수 없다)
with tempfile.TemporaryDirectory() as root:
    rc, out = run(root, 125, True)
ok = "125분 전" in out and rc == 0
fail += 0 if ok else 1
print(f"{'OK ' if ok else 'FAIL'} 경과 분 표기 (125분): {out[:120]!r}")

# 2026-10-01 감사: 경고는 PreCompact 가 지원하는 systemMessage JSON 으로 나가야 한다(평문 stdout 은 안 닿는다)
with tempfile.TemporaryDirectory() as root:
    rc, out = run(root, 90, True)
try:
    ok = rc == 0 and "HANDOVER_STALE" in json.loads(out)["systemMessage"]
except Exception:
    ok = False
fail += 0 if ok else 1
print(f"{'OK ' if ok else 'FAIL'} 경고는 systemMessage JSON: {out[:120]!r}")

# 세션 cwd 가 저장소 하위 폴더여도 git 뿌리의 프로젝트 memory 를 본다
with tempfile.TemporaryDirectory() as root:
    rc, out = run(root, 120, True, sub="pkg/inner")
ok = "HANDOVER_STALE" in out and rc == 0
fail += 0 if ok else 1
print(f"{'OK ' if ok else 'FAIL'} cwd 가 하위 폴더 → git 뿌리 memory 폴백: {out[:80]!r}")

# 종전 경로(저장소/short-term/handover.md)는 규칙의 위치가 아니므로 보지 않는다 — 수정 전에는 이 경로만 봤다
with tempfile.TemporaryDirectory() as root:
    rc, out = run(root, 120, True, legacy=True)
ok = "HANDOVER_STALE" not in out and rc == 0
fail += 0 if ok else 1
print(f"{'OK ' if ok else 'FAIL'} 종전 경로는 더 이상 보지 않음: {out[:80]!r}")

total = len(CASES) + 4
print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({total} cases)")
sys.exit(1 if fail else 0)
