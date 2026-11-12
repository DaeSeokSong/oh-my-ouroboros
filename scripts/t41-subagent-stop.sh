#!/usr/bin/env bash
# t41-subagent-stop.sh — SubagentStop 훅: 서브에이전트의 **진짜 마지막 답**에서 실패 신호를 잡아 T41 기록 (2026-09-14 신설)
#
# ■ 왜 별도 경로인가 (판단 근거 이식)
#   PostToolUse(Agent) 의 tool_response 는 **비동기 소집에서 결과가 아니다**. 소집 직후 돌아오는
#   «Async agent launched …» 안내(보낸 프롬프트 원문 포함)일 뿐이라, 거기서 실패 신호를 읽으면
#   자기 프롬프트를 결과로 오판한다(2026-09-14 실사고 — 검수 의뢰문의 «RESULT: FAIL» 지시가 기록됨).
#   그래서 agent-spawn-log.sh 는 비동기 응답을 건너뛰고, 그 소집의 결과 판정은 이 훅이 맡는다.
#   SubagentStop 은 서브에이전트가 실제로 끝난 뒤에만 발화하므로 마지막 assistant 메시지가 곧 결과다.
#
# ■ 판정
#   agent-spawn-log.sh 와 **같은 강형 정규식**(행 앞 고정)만 신호로 본다. 느슨한 한국어 단어
#   («실패»·«반려»)는 «실패 스위트: 0» 같은 성공 문장에도 맞아 쓰지 않는다.
#   ※ 두 파일에 같은 정규식이 있다 — 고칠 땐 함께 고친다.
#
# ■ 중복
#   동기 소집은 PostToolUse 와 이 훅이 모두 본다. 종전에는 history.md 에 같은 신호가 두 줄 남아
#   T41_REPEAT 의 3회 문턱이 부풀었다(09-14 재감사 §3-b) — 이제 t41-append.sh 가 같은
#   role/dim/신호를 10분 안에 다시 받으면 건너뛴다. 후보 대장은 요약 기준으로 원래 한 행만 남는다.
#
# ■ 안전
#   훅이 세션을 막으면 안 된다 — 파싱·기록 실패를 포함해 **항상 exit 0**.
#
# ■ 정본
#   쓰는 쪽 정본: agents/*.md 보고 형식(마지막 text 블록 안 행두 `RESULT: <값>` 한 줄, target=<역할> 선택).
set -uo pipefail

INPUT=$(cat 2>/dev/null) || exit 0
command -v jq >/dev/null 2>&1 || exit 0

# payload 의 트랜스크립트 키는 구현마다 다르다 — 서브에이전트 전용 경로를 먼저, 없으면 세션 경로를 쓴다.
TP=$(printf '%s' "$INPUT" | jq -r '.agent_transcript_path // empty' 2>/dev/null)
[ -n "$TP" ] && [ -f "$TP" ] || TP=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
[ -n "$TP" ] && [ -f "$TP" ] || exit 0

ROLE=$(printf '%s' "$INPUT" \
    | jq -r '.subagent_type // .agent_type // .agent_name // .tool_input.subagent_type // .name // "general-purpose"' 2>/dev/null \
    | tr '\t\n\r' '   ' | sed 's/[[:space:]]*$//' | cut -c1-40)
[ -n "$ROLE" ] || ROLE="general-purpose"

# 역할 별칭(sec-g1→security 등)은 정본 scripts/role-alias.sh 의 normalize_role 한 곳에서 처리한다(2026-10-17: t41-append.sh 가 source 해 직접 호출 경로와 표를 공유한다).

# 마지막 assistant 메시지의 text 블록만 모은다. 손상된 줄 하나가 전체를 중단시키지 않게 fromjson? 로 관용 파싱한다
# (pattern-detect.sh 와 같은 방식). 마지막 메시지는 파일 끝이므로 꼬리 400줄이면 충분하다.
TEXT=$(tail -n 400 "$TP" 2>/dev/null \
    | jq -R 'fromjson? // empty' 2>/dev/null \
    | jq -rs '[.[] | select(.type == "assistant") | .message.content[]? | select(.type == "text") | .text] | last // empty' 2>/dev/null)
[ -n "$TEXT" ] || exit 0

T41_RX='^[[:space:]]*(RESULT|STATUS|status|판정)[[:space:]]*[:=][[:space:]]*(FAIL|BLOCKED|NEEDS_CONTEXT|REJECT)\b|^[[:space:]]*(FAIL|BLOCKED|NEEDS_CONTEXT)\b'
# 계약(마지막 보고의 `RESULT:` 줄)을 먼저 본다: 마지막 RESULT 줄이 DONE·PASS 면 본문에 행두 «FAIL»류가 있어도 신호가 아니다.
# RESULT 줄이 없는 보고만 위 강형 정규식으로 보되, «FAIL 0건»·«FAIL: 없음» 같은 0건 보고는 신호에서 뺀다(2026-10-01 감사 D).
RESULT_LINE=$(printf '%s\n' "$TEXT" | LC_ALL=C.utf8 grep -E '^[[:space:]]*RESULT[[:space:]]*[:=]' | tail -1)
if [ -n "$RESULT_LINE" ]; then
    SIGNAL=$(printf '%s\n' "$RESULT_LINE" | LC_ALL=C.utf8 grep -E "$T41_RX" | head -1)
else
    SIGNAL=$(printf '%s\n' "$TEXT" | LC_ALL=C.utf8 grep -E "$T41_RX" \
        | LC_ALL=C.utf8 grep -v -E '(FAIL|BLOCKED|NEEDS_CONTEXT|REJECT)[[:space:]]*[:=]?[[:space:]]*(0|없음|none|zero)([^0-9A-Za-z]|$)' | head -1)
fi
[ -n "$SIGNAL" ] || exit 0
# 추적 파일(history.md)로 가는 자유 문장: 토큰·UID 형태를 가리고 N 코드포인트로 절단한다.
# 가림 함수 mask_cut 의 정본은 scripts/t41-mask.sh 한 곳이다(동기 경로 agent-spawn-log.sh 와 공용, 2026-11-12).
# shellcheck source=/dev/null
. "$HOME/.claude/scripts/t41-mask.sh" 2>/dev/null || exit 0
SIGNAL=$(printf '%s' "$SIGNAL" | mask_cut 80)
[ -n "$SIGNAL" ] || exit 0

# 판정할 정보 (2026-11-12): agent-spawn-log.sh 와 같은 `<소집 설명 앞 40자> | from=<원 역할> | <RESULT 줄>` 꼴로 넘긴다.
#   SubagentStop 입력에는 소집 설명이 없다. 서브에이전트 기록 옆의 `<agent-…>.meta.json` 의 description 을 읽고
#   (2026-11-12 실측: agentType · description · toolUseId 키), 없으면 `from=<역할> | <RESULT 줄>` 만 넘긴다.
#   세션 기록(transcript_path 폴백)이면 meta 가 없어 설명이 빈다.
DESC40=""
META="${TP%.jsonl}.meta.json"
[ "$META" != "$TP" ] && [ -f "$META" ] \
    && DESC40=$(jq -r '.description // ""' "$META" 2>/dev/null | mask_cut 40 | sed 's/[[:space:]]*$//')

# --from 자동 모드 — 약점 주체·차원 매핑은 t41-append.sh 한 곳(두 훅 공용). stderr 는 막지 않는다.
bash "$HOME/.claude/scripts/t41-append.sh" --from "$ROLE" --signal "${DESC40:+$DESC40 | }from=$ROLE | $SIGNAL" >/dev/null
exit 0
