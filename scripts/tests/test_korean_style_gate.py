"""korean-style-gate.sh (+ korean_style_check.py) 회귀 테스트.

실행: python3 ~/.claude/scripts/tests/test_korean_style_gate.py → 실패 0 이면 exit 0
REF: knowledge/harness/code-history/scripts__tests__test_korean_style_gate.py.md
"""
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path.home() / ".claude/scripts/korean-style-gate.sh"
CONFLUENCE_TOOL = "mcp__claude_ai_Atlassian__updateConfluencePage"


def run(tool_name: str, body: str, fmt: str | None = "html"):
    tool_input = {"body": body} if fmt is None else {"body": body, "contentFormat": fmt}
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    r = subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True, check=False)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def denied(stdout: str):
    if not stdout:
        return False, None
    try:
        obj = json.loads(stdout)
    except json.JSONDecodeError:
        return False, None
    hso = obj.get("hookSpecificOutput", {})
    if hso.get("permissionDecision") == "deny":
        return True, hso.get("permissionDecisionReason", "")
    return False, None


CASES = [
    ("① 산문 삽입 대시 → 차단", CONFLUENCE_TOOL,
     "<p>이 문장은 — 중간에 대시가 있다.</p>", True),
    ("② 쉼표 2개 이상(대시 없음) → 경고만, 차단 아님(실제 계약)", CONFLUENCE_TOOL,
     "<p>이것은 값, 저것도 값, 그것도 값이다.</p>", False),
    ("③ 위반 없는 정상 본문 → 통과", CONFLUENCE_TOOL,
     "<p>이 문서는 정상적으로 작성됐다.</p>", False),
    ("④ 제목 콜론 형식(대시 없음) → 통과(오탐 방지)", CONFLUENCE_TOOL,
     "<h1>실험 결과: 요약</h1><p>본문 내용이다.</p>", False),
    ("⑤ code 블록 안 대시 → 통과(제외 대상)", CONFLUENCE_TOOL,
     "<p>실행 명령은 <code>a — b</code> 형태다.</p>", False),
    ("⑥ 제목(h1) 안 삽입 대시 → 차단", CONFLUENCE_TOOL,
     "<h1>실험 결과 — 요약</h1>", True),
    ("⑦ Confluence 편집 도구가 아니면 위반 본문도 통과", "Read",
     "<p>이 문장은 — 위반이지만 도구가 다르다.</p>", False),
]

fail = 0
for name, tool_name, body, want_denied in CASES:
    rc, out, err = run(tool_name, body)
    is_denied, reason = denied(out)
    rc_ok = rc == 0
    verdict_ok = is_denied == want_denied
    ok = rc_ok and verdict_ok
    fail += 0 if ok else 1
    tag = "OK " if ok else "FAIL"
    detail = ""
    if not ok:
        detail = f"\n     rc={rc} denied={is_denied}(기대 {want_denied}) stdout={out[:200]!r} stderr={err[:200]!r}"
    elif is_denied:
        detail = f"\n     reason 앞부분: {reason[:60]!r}"
    print(f"{tag} {name}:{detail}")

rc, out, _ = run(CONFLUENCE_TOOL, "<p>이 문장은 — 중간에 대시가 있다.</p>")
is_denied, reason = denied(out)
reason_ok = is_denied and reason.startswith("★한국어 문체 3규칙 위반 — 게시 중단.")
print(f"{'OK ' if reason_ok else 'FAIL'} REASON 문구 계약(★한국어 문체 3규칙 위반으로 시작): {reason[:40]!r}")
fail += 0 if reason_ok else 1

MD_BAD = "# 제목\n\n이 문장은 — 중간에 대시가 있다.\n"
MD_OK = "# 제목\n\n이 문서는 정상적으로 작성됐다.\n"
FMT_CASES = [
    ("⑧ markdown 본문의 삽입 대시 → 차단", MD_BAD, "markdown", True),
    ("⑨ adf 본문의 삽입 대시 → 차단", '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"이 문장은 — 중간에 대시가 있다."}]}]}', "adf", True),
    ("⑩ 형식 필드 없음 → markdown 취급, 삽입 대시 차단", MD_BAD, None, True),
    ("⑪ storage 본문의 삽입 대시 → 차단(HTML 모드 유지)", "<p>이 문장은 — 중간에 대시가 있다.</p>", "storage", True),
    ("⑫ markdown 정상 본문 → 통과", MD_OK, "markdown", False),
]
for name, body, fmt, want_denied in FMT_CASES:
    rc, out, err = run(CONFLUENCE_TOOL, body, fmt)
    is_denied, _ = denied(out)
    ok = rc == 0 and is_denied == want_denied
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}{'' if ok else f' (rc={rc} denied={is_denied} out={out[:150]!r})'}")

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(CASES) + 1 + len(FMT_CASES)} cases)")
sys.exit(1 if fail else 0)
