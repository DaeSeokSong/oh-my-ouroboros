"""graphify-autoindex.sh 보고 채널 회귀 테스트 (2026-10-01 감사: 평문 stdout 은 모델에 안 닿는다 → additionalContext JSON).

실행: python3 ~/.claude/scripts/tests/test_graphify_autoindex.py → 실패 0 이면 exit 0
계약: 직전 재인덱싱이 남긴 .autoindex-updated / .autoindex-failed 마커가 있으면 PostToolUse additionalContext JSON 한 개로
      보고하고 마커를 지운다(한 호출에 JSON 은 하나). 마커가 없으면 무출력. 항상 exit 0.
격리: 임시 프로젝트·가짜 HOME, PATH 는 /usr/bin:/bin 만 줘 graphify 를 실제로 부르지 않는다(백그라운드 재인덱싱 방지).
REF: knowledge/harness/code-history/scripts__tests__test_graphify_autoindex.py.md
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path.home() / ".claude/scripts/graphify-autoindex.sh"
SAFE_PATH = "/usr/bin:/bin"
fail = 0
n = 0


def check(name, ok, detail=""):
    global fail, n
    n += 1
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}" + ("" if ok else f": {detail}"))


if shutil.which("graphify", path=SAFE_PATH):
    print("SKIP: /usr/bin:/bin 에 graphify 가 있어 격리할 수 없다")
    sys.exit(0)

with tempfile.TemporaryDirectory() as td:
    home = Path(td) / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), PATH=SAFE_PATH)

    def run(proj: Path):
        payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(proj / "a.py")}})
        return subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True, env=env, check=False)

    def project(name, updated=None, failed=None):
        p = Path(td) / name
        (p / "graphify-out").mkdir(parents=True)
        (p / "a.py").write_text("x = 1\n", encoding="utf-8")
        if updated:
            (p / "graphify-out/.autoindex-updated").write_text(updated, encoding="utf-8")
        if failed:
            (p / "graphify-out/.autoindex-failed").write_text(failed, encoding="utf-8")
        return p

    p1 = project("p1", updated="10-01 12:00 p1")
    r = run(p1)
    try:
        out = json.loads(r.stdout)["hookSpecificOutput"]
        ok = out["hookEventName"] == "PostToolUse" and "자동 갱신 완료" in out["additionalContext"]
    except Exception:  # noqa: BLE001
        ok = False
    check("완료 마커 → additionalContext JSON 으로 보고", ok and r.returncode == 0, f"rc={r.returncode} stdout={r.stdout[:200]!r}")
    check("완료 마커는 보고 뒤 삭제", not (p1 / "graphify-out/.autoindex-updated").exists())

    p2 = project("p2", updated="10-01 12:00 p2", failed="10-01 12:01 p2 FAIL")
    r = run(p2)
    try:
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        ok = "자동 갱신 완료" in ctx and "자동 갱신 실패" in ctx
    except Exception:  # noqa: BLE001
        ok = False
    check("완료·실패 마커 동시 → JSON 하나에 두 줄", ok, f"stdout={r.stdout[:300]!r}")

    p3 = project("p3")
    r = run(p3)
    check("마커 없음 → 무출력·exit 0", r.returncode == 0 and r.stdout.strip() == "", f"rc={r.returncode} stdout={r.stdout[:100]!r}")

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({n} cases)")
sys.exit(1 if fail else 0)
