#!/usr/bin/env python3
"""ci-gate-edit.sh 회귀 테스트 (2026-10-01 감사: lint 결과가 stderr 가 아니라 additionalContext JSON 으로 닿아야 한다).

실행: python3 ~/.claude/scripts/tests/test_ci_gate_edit.py → 실패 0 이면 exit 0
계약: PostToolUse 입력의 file_path 를 검사해 결과가 있으면 stdout 에
      {"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"…"}} 를 낸다(exit 0, 비차단). 결과가 없으면 무출력.
      markdownlint 가 설치돼 있으면 .md 검사 경로가 달라지므로 그 환경에서는 .md 케이스를 건너뛴다.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path.home() / ".claude/scripts/ci-gate-edit.sh"
FENCE = "`" * 3
fail = 0
n = 0


def run(path: Path):
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(path)}})
    return subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True)


def check(name, ok, detail=""):
    global fail, n
    n += 1
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}" + ("" if ok else f": {detail}"))


with tempfile.TemporaryDirectory() as td:
    if shutil.which("markdownlint"):
        print("SKIP .md 케이스(markdownlint 설치됨)")
    else:
        bad = Path(td) / "bad.md"
        bad.write_text(f"# 제목\n\n{FENCE}\n코드가 안 닫힘\n", encoding="utf-8")
        r = run(bad)
        try:
            out = json.loads(r.stdout)["hookSpecificOutput"]
            ok = out["hookEventName"] == "PostToolUse" and "fence imbalance" in out["additionalContext"] and str(bad) in out["additionalContext"]
        except Exception:
            ok = False
        check("펜스 불균형 .md → PostToolUse additionalContext JSON", ok and r.returncode == 0, f"rc={r.returncode} stdout={r.stdout[:200]!r} stderr={r.stderr[:100]!r}")
        check("결과는 stderr 가 아니라 stdout 으로", r.stderr.strip() == "", r.stderr[:100])
        good = Path(td) / "good.md"
        good.write_text(f"# 제목\n\n{FENCE}\n닫힘\n{FENCE}\n", encoding="utf-8")
        r = run(good)
        check("정상 .md → 무출력·exit 0", r.returncode == 0 and r.stdout.strip() == "", f"rc={r.returncode} stdout={r.stdout[:100]!r}")
    txt = Path(td) / "a.txt"
    txt.write_text("x\n", encoding="utf-8")
    r = run(txt)
    check("검사 대상 확장자가 아니면 무출력·exit 0", r.returncode == 0 and r.stdout.strip() == "", r.stdout[:100])

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({n} cases)")
sys.exit(1 if fail else 0)
