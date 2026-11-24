#!/bin/bash
# korean-style-gate.sh — Confluence MCP 쓰기 직전 한국어 문체 3규칙 게이트
#   MCP 경로(updateConfluencePage / createConfluencePage)를 이 hook 이 막는다. 스크립트 경로(confluence_patch_page.py)는 그 안의 게이트가 막는다.
# 판정: 차단 위반(삽입 대시·제목 대시)이 있으면 deny. 경고(쉼표·조사)는 통과시킨다.
# 우회: 의도적으로 넘겨야 하면 body 안 어디에도 손대지 말고 사용자에게 확인받을 것.
# 정본 룰: ~/.claude/rules-lazy/answer-detail.md § 한국어 문체
# REF: knowledge/harness/code-history/scripts__korean-style-gate.sh.md

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)

case "$TOOL" in
  *updateConfluencePage|*createConfluencePage) ;;
  *) exit 0 ;;
esac

BODY=$(echo "$INPUT" | jq -r '.tool_input.body // empty' 2>/dev/null)
[ -z "$BODY" ] && exit 0

# WHY: 항상 HTML 로 판정하면 markdown·ADF 본문은 <p>·<li>·<h*> 블록이 0개라 «위반 0건» 으로 통과했다(감사).
# 판정기(scripts/korean_style_check.py)가 확장자로 모드를 정한다.
FMT=$(echo "$INPUT" | jq -r '.tool_input.contentFormat // empty' 2>/dev/null | tr '[:upper:]' '[:lower:]')
case "$FMT" in
  html|storage) EXT=html ;;
  *) EXT=md ;;
esac
TMP=$(mktemp "/tmp/kstyle.XXXXXX.$EXT")
printf '%s' "$BODY" > "$TMP"
OUT=$(python3 "$HOME/.claude/scripts/korean_style_check.py" "$TMP" 2>&1)
RC=$?
rm -f "$TMP"

[ "$RC" -eq 0 ] && exit 0

REASON="★한국어 문체 3규칙 위반 — 게시 중단.

$OUT

고치는 방법: 콤마로 기계 치환 금지. 문장을 다시 쓴다.
  · 산문 삽입 대시 → 마침표로 문장 분리 (왼쪽이 서술 종결이면 그대로 끊는다)
  · 제목·캡션·범례 대시 → 콜론
  · 한 문장 쉼표 2개 이상 → 분할, 나열은 가운뎃점(·)
정본: ~/.claude/rules-lazy/answer-detail.md § 한국어 문체
대량 수정이면 MCP 대신 ~/.claude/scripts/confluence_patch_page.py (리터럴 치환 + 같은 게이트)."

jq -nc --arg r "$REASON" \
  '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
exit 0
