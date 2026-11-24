#!/usr/bin/env bash
# t41-subagent-stop.sh — SubagentStop 훅: 서브에이전트의 진짜 마지막 답에서 실패 신호를 잡아 T41 기록
#   비동기 소집의 결과 판정은 이 훅이 맡는다(agent-spawn-log.sh 는 비동기 응답을 건너뛴다).
# 판정: 마지막 `RESULT:` 줄을 먼저 보고, 없으면 agent-spawn-log.sh 와 같은 강형 정규식(행 앞 고정)만 신호로 본다.
# NEVER: 정규식을 이 파일에서만 고치지 않는다. agent-spawn-log.sh 에 같은 정규식이 있다.
# 기록: t41-append.sh --from 으로 넘긴다. 파싱·기록 실패를 포함해 항상 exit 0.
# 쓰는 쪽 정본: agents/*.md 보고 형식(마지막 text 블록 안 행두 `RESULT: <값>` 한 줄, target=<역할> 선택).
# REF: knowledge/harness/code-history/scripts__t41-subagent-stop.sh.md
set -uo pipefail

INPUT=$(cat 2>/dev/null) || exit 0
command -v jq >/dev/null 2>&1 || exit 0

TP=$(printf '%s' "$INPUT" | jq -r '.agent_transcript_path // empty' 2>/dev/null)
[ -n "$TP" ] && [ -f "$TP" ] || TP=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
[ -n "$TP" ] && [ -f "$TP" ] || exit 0

ROLE=$(printf '%s' "$INPUT" \
    | jq -r '.subagent_type // .agent_type // .agent_name // .tool_input.subagent_type // .name // "general-purpose"' 2>/dev/null \
    | tr '\t\n\r' '   ' | sed 's/[[:space:]]*$//' | cut -c1-40)
[ -n "$ROLE" ] || ROLE="general-purpose"

# WHY: 손상된 줄 하나가 전체를 중단시키지 않게 fromjson? 로 관용 파싱한다(scripts/pattern-detect.sh 와 같은 방식).
# 마지막 메시지는 파일 끝이므로 꼬리 400줄만 본다.
TEXT=$(tail -n 400 "$TP" 2>/dev/null \
    | jq -R 'fromjson? // empty' 2>/dev/null \
    | jq -rs '[.[] | select(.type == "assistant") | .message.content[]? | select(.type == "text") | .text] | last // empty' 2>/dev/null)
[ -n "$TEXT" ] || exit 0

T41_RX='^[[:space:]]*(RESULT|STATUS|status|판정)[[:space:]]*[:=][[:space:]]*(FAIL|BLOCKED|NEEDS_CONTEXT|REJECT)\b|^[[:space:]]*(FAIL|BLOCKED|NEEDS_CONTEXT)\b'
# WHY: 마지막 RESULT 줄이 DONE·PASS 면 본문에 행두 «FAIL»류가 있어도 신호가 아니다.
# «FAIL 0건»·«FAIL: 없음» 같은 0건 보고는 신호에서 뺀다(2026-10-01 감사 D).
RESULT_LINE=$(printf '%s\n' "$TEXT" | LC_ALL=C.utf8 grep -E '^[[:space:]]*RESULT[[:space:]]*[:=]' | tail -1)
if [ -n "$RESULT_LINE" ]; then
    SIGNAL=$(printf '%s\n' "$RESULT_LINE" | LC_ALL=C.utf8 grep -E "$T41_RX" | head -1)
else
    SIGNAL=$(printf '%s\n' "$TEXT" | LC_ALL=C.utf8 grep -E "$T41_RX" \
        | LC_ALL=C.utf8 grep -v -E '(FAIL|BLOCKED|NEEDS_CONTEXT|REJECT)[[:space:]]*[:=]?[[:space:]]*(0|없음|none|zero)([^0-9A-Za-z]|$)' | head -1)
fi
[ -n "$SIGNAL" ] || exit 0
# WHY: 추적 파일(history.md)로 가는 자유 문장이라 토큰·UID 형태를 가린다. mask_cut 의 정본은 scripts/t41-mask.sh 다.
# shellcheck source=/dev/null
. "$HOME/.claude/scripts/t41-mask.sh" 2>/dev/null || exit 0
SIGNAL=$(printf '%s' "$SIGNAL" | mask_cut 80)
[ -n "$SIGNAL" ] || exit 0

# WHY: SubagentStop 입력에는 소집 설명이 없어 서브에이전트 기록 옆 `<agent-…>.meta.json` 의 description 을 읽는다
# (2026-11-12 실측: agentType · description · toolUseId 키).
DESC40=""
META="${TP%.jsonl}.meta.json"
[ "$META" != "$TP" ] && [ -f "$META" ] \
    && DESC40=$(jq -r '.description // ""' "$META" 2>/dev/null | mask_cut 40 | sed 's/[[:space:]]*$//')

# NEVER: transcript_path 폴백을 보고 에이전트 transcript 로 넘기지 않는다. 부모(main) 기록이라 틀린 행위자가 된다(2026-11-16).
RTP=$(printf '%s' "$INPUT" | jq -r '.agent_transcript_path // empty' 2>/dev/null)
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

# NEVER: t41-append.sh 의 stderr 를 막지 않는다.
T41_REPORTER_TP="$RTP" T41_SESSION_ID="$SID" T41_PATH_KIND=async \
    bash "$HOME/.claude/scripts/t41-append.sh" --from "$ROLE" --signal "${DESC40:+$DESC40 | }from=$ROLE | $SIGNAL" >/dev/null
exit 0
