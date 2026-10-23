#!/bin/bash
# korean-style-gate.sh — Confluence MCP 쓰기 직전 한국어 문체 3규칙 게이트
#
# ■ 왜 hook 인가 (판단 근거 이식 — 2026-08-10)
# 룰은 2026-08-05 제정 · 08-07 상시 승격됐는데도 08-10 Confluence 4개 페이지에서
# **한 건도 반영되지 않았다**(사용자 지적, 차단 위반 83건). 원인은 룰의 부재가 아니라
# "매번 기억해서 지킨다"는 방식 자체다. 그래서 판정을 기억에서 **게이트**로 옮긴다.
#   · 스크립트 경로(confluence_patch_page.py) → 그 안의 게이트가 막는다
#   · MCP 경로(updateConfluencePage / createConfluencePage) → 이 hook 이 막는다
# 두 경로를 다 막아야 "무조건 확인"이 성립한다 — 실제로 뚫린 쪽이 MCP 경로였다.
#
# 판정: 차단 위반(삽입 대시·제목 대시)이 있으면 deny. 경고(쉼표·조사)는 통과시킨다.
# 우회: 의도적으로 넘겨야 하면 body 안 어디에도 손대지 말고 사용자에게 확인받을 것.
# 정본 룰: ~/.claude/rules-lazy/answer-detail.md § 한국어 문체

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)

case "$TOOL" in
  *updateConfluencePage|*createConfluencePage) ;;
  *) exit 0 ;;
esac

BODY=$(echo "$INPUT" | jq -r '.tool_input.body // empty' 2>/dev/null)
[ -z "$BODY" ] && exit 0

# 본문 형식(contentFormat: html·storage·markdown·adf — 2026-10-01 실제 호출 기록에서 확인)에 맞춰 판정한다.
# 항상 HTML 로 판정하면 markdown·ADF 본문은 <p>·<li>·<h*> 블록이 0개라 «위반 0건» 으로 통과했다(감사).
# html·storage 가 아니면(필드 없음 포함) markdown 모드(.md)로 돌린다 — 판정기가 확장자로 모드를 정한다.
FMT=$(echo "$INPUT" | jq -r '.tool_input.contentFormat // empty' 2>/dev/null | tr 'A-Z' 'a-z')
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
