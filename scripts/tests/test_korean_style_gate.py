#!/usr/bin/env python3
"""korean-style-gate.sh (+ korean_style_check.py) 회귀 테스트.

실행: python3 ~/.claude/scripts/tests/test_korean_style_gate.py → 실패 0 이면 exit 0

■ 파악한 계약 (소스 대조 — 추측 아님)
  · 입력: PreToolUse 훅이 stdin 으로 JSON 을 받는다. 훅은 `.tool_name` 을 읽어
    `*updateConfluencePage` / `*createConfluencePage` 로 끝나는 도구만 검사하고
    (settings.json matcher: `mcp__claude_ai_Atlassian__(update|create)ConfluencePage`),
    그 외 도구는 즉시 exit 0(무출력). 본문은 `.tool_input.body` 필드에서 꺼낸다.
    본문이 비어 있으면 역시 exit 0(무출력).
  · 훅 프로세스는 항상 exit 0 이다. Claude Code PreToolUse 훅 프로토콜은 차단 여부를
    exit code 가 아니라 stdout JSON 의 `hookSpecificOutput.permissionDecision` 필드로
    전달한다. 그래서 이 테스트는 exit code 대신 그 필드로 통과/차단을 판정한다.
  · 차단 시 stdout: `{"hookSpecificOutput":{"hookEventName":"PreToolUse",
    "permissionDecision":"deny","permissionDecisionReason":"..."}}` (jq -nc 로 생성,
    REASON 은 "★한국어 문체 3규칙 위반 — 게시 중단." 으로 시작). 통과 시 stdout 은 빈 문자열.
  · korean_style_check.py 의 실제 판정(check() 함수, 스크립트 자체 12행 주석에도 명시):
    ① 산문 문장 안 삽입 대시(—, &mdash;) → 차단(blocked)
    ② 제목(h1~h6) 안 대시 → 차단
    ③ 쉼표 2개 이상인 문장 → 경고(warned)만, 차단 아님
    ④ 영문·숫자 뒤 조사 → 경고만, 차단 아님
    report() 는 blocked 가 1건이라도 있어야 exit 1(→ 훅이 deny)이고, warned 만 있으면
    exit 0(→ 훅이 통과)이다. 즉 이 훅이 실제로 막는 건 삽입 대시뿐이고 쉼표 위반은
    막지 않는다(아래 케이스 2 참조 — CLAUDE.md 문체 3규칙엔 쉼표도 위반으로 적혀 있지만,
    이 게이트 구현은 경고로만 처리한다. 스크립트 자체 주석에 명시된 설계다).
  · 제외 대상(코드가 실제로 지우는 것, `_strip_cells`): `<td>/<th>` 표 셀, `<ac:link>` 안
    페이지 제목, `<code>` 내용. 이 안의 대시는 검사 대상에서 아예 사라진다(케이스 5).

■ 케이스 요약
  1. 산문 <p> 안 삽입 대시 → 차단
  2. 쉼표 2개 이상(대시 없음) → 경고만, 차단 아님(실제 계약 — 위 설명 참조)
  3. 위반 없는 정상 본문 → 통과(무출력)
  4. 제목의 콜론 형식(대시 없음) → 통과(오탐 방지)
  5. <code> 블록 안의 대시 → 통과(제외 대상 실측 확인)
  6. 제목(h1) 안 삽입 대시 → 차단(제목 전용 분기)
  7. Confluence 편집 도구가 아닌 tool_name → 훅이 본문을 보지 않고 즉시 통과
"""
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path.home() / ".claude/scripts/korean-style-gate.sh"
CONFLUENCE_TOOL = "mcp__claude_ai_Atlassian__updateConfluencePage"


def run(tool_name: str, body: str, fmt: str | None = "html"):
    """fmt: tool_input.contentFormat 값(2026-10-01 감사: 훅이 형식에 따라 html/markdown 모드를 고른다). None 이면 필드 없음."""
    tool_input = {"body": body} if fmt is None else {"body": body, "contentFormat": fmt}
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    r = subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def denied(stdout: str):
    """stdout 이 deny JSON 이면 (True, reason), 아니면 (False, None) 을 준다."""
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
    rc_ok = rc == 0   # 훅은 항상 exit 0 이어야 한다(차단도 exit 0 + deny JSON)
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

# REASON 문구 계약 고정(차단 케이스 하나로 재확인)
rc, out, _ = run(CONFLUENCE_TOOL, "<p>이 문장은 — 중간에 대시가 있다.</p>")
is_denied, reason = denied(out)
reason_ok = is_denied and reason.startswith("★한국어 문체 3규칙 위반 — 게시 중단.")
print(f"{'OK ' if reason_ok else 'FAIL'} REASON 문구 계약(★한국어 문체 3규칙 위반으로 시작): {reason[:40]!r}")
fail += 0 if reason_ok else 1

# ── 2026-10-01 감사: 본문 형식(contentFormat)별 판정. 수정 전에는 항상 HTML 로 읽어 markdown·ADF 위반이 «0건» 으로 통과했다 ──
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
