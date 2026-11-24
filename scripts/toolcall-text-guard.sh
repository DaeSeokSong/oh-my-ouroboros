#!/usr/bin/env bash
# toolcall-text-guard.sh — Stop/SubagentStop 훅: "도구 호출이 텍스트로 출력되는" 장문 컨텍스트 실패 자가 복구
#   마지막 assistant 메시지의 text 에 여는 invoke 태그와 parameter 태그가 둘 다 남아 있으면 decision:block 으로 종료를 막고
#   방금 텍스트로 쓴 호출을 실제 도구 호출로 재실행하라고 지시한다. stop_hook_active=true 면 즉시 통과(재시도 1회).
#   실패는 항상 exit 0 침묵 통과(fail-open).
# 단계 순서: 전파 확인(propagate-gate.sh) → 마크업 검사 → 한글 보고 검사(korean_report_check.py) → needs input 팝업 근거 검사(needs_input_popup_check.py)
#   → 세션 작업 현황 검사(handoff_check.py). 앞 단계가 block 을 내면 뒤 단계는 부르지 않는다(한 턴에 block 하나). 뒤 세 단계는 Stop 전용이다.
# REF: knowledge/harness/code-history/scripts__toolcall-text-guard.sh.md
set -uo pipefail

INPUT=$(cat 2>/dev/null) || exit 0

ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)
[ "$ACTIVE" = "true" ] && exit 0

# WHY: 이 Stop 훅이 settings.json 에 이미 연결돼 있어 scripts/propagate-gate.sh 를 여기서 부른다(settings 는 사용자만 고친다).
GATE_OUT=$(printf '%s' "$INPUT" | bash "$(dirname "$(readlink -f "$0")")/propagate-gate.sh" 2>/dev/null) || GATE_OUT=""
if [ -n "$GATE_OUT" ]; then
  printf '%s\n' "$GATE_OUT"
  exit 0
fi

# WHY: 기록 파일 끝은 훅 시점에 최신이 아니다(knowledge/harness/stop-hook-transcript-race.md). SubagentStop 에서 이 필드는 자식 자신의 마지막 메시지다.
LAST_TEXT=$(printf '%s' "$INPUT" | jq -r '.last_assistant_message // empty' 2>/dev/null)

if [ -z "$LAST_TEXT" ]; then
  # WHY: SubagentStop 입력의 transcript_path 는 «부모(main)» 기록이고 자식 기록은 agent_transcript_path 다(2026-10-01 감사).
  TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.agent_transcript_path // .transcript_path // empty' 2>/dev/null)
  [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] || exit 0

  LAST_TEXT=$(tail -n 300 "$TRANSCRIPT" 2>/dev/null | jq -rs '
    [ .[] | select(.type=="assistant") ] | last
    | (.message.content? // [] | if type=="array" then .[] else empty end
         | select(.type=="text") | .text) ' 2>/dev/null)
  # WHY: 종전 `last` 는 마지막 text 블록만 봐 앞 블록의 마크업 유출을 놓쳤다(2026-07-18 Codex).
fi
[ -n "$LAST_TEXT" ] || exit 0

OPEN_PAT='<(antml:)?invoke +name='
PARAM_PAT='<(antml:)?parameter +name='

if printf '%s' "$LAST_TEXT" | grep -qE "$OPEN_PAT" \
   && printf '%s' "$LAST_TEXT" | grep -qE "$PARAM_PAT"; then
  jq -n '{decision: "block",
          reason: "직전 응답에서 도구 호출 마크업이 실제 호출로 실행되지 않고 본문 텍스트로 출력되었습니다 (장문 컨텍스트에서 발생하는 알려진 디코딩 실패). 방금 텍스트로 적은 도구 호출을 지금 실제 도구 호출로 다시 실행하세요. 같은 실패가 반복되면 호출을 더 작은 단위로 나누고, 컨텍스트가 75% 이상이면 먼저 handover 기록 후 compact를 고려하세요."}'
  exit 0
fi

# WHY: settings.json 의 이 훅 제한은 15초라 앞 단계가 쓴 시간만큼 줄여 13초 안에 끝낸다. 4+6+8=18초로 넘으면 훅이 죽어
# 영어 보고 차단이 통째로 빠진다(qa 2026-10-21). 설계: intent/2026-10-16-korean-report-guard.md.
LEFT_SEC=$(( 13 - SECONDS ))
[ "$LEFT_SEC" -gt 8 ] && LEFT_SEC=8
EVENT=$(printf '%s' "$INPUT" | jq -r '.hook_event_name // empty' 2>/dev/null)
if [ "$LEFT_SEC" -ge 2 ] && [ "$EVENT" = "Stop" ]; then
  KO_OUT=$(printf '%s' "$INPUT" | timeout "$LEFT_SEC" uv run -q --no-project python "$(dirname "$0")/korean_report_check.py" 2>/dev/null)
  [ -n "$KO_OUT" ] && printf '%s\n' "$KO_OUT"
fi

# WHY: 선택을 최종 보고의 needs input 줄로만 물으면 block 한다(2026-10-28 사용자 지시, scripts/needs_input_popup_check.py).
NI_OUT=""
LEFT_SEC=$(( 13 - SECONDS ))
[ "$LEFT_SEC" -gt 2 ] && LEFT_SEC=2
if [ "$LEFT_SEC" -ge 1 ] && [ "$EVENT" = "Stop" ] && ! printf '%s' "${KO_OUT:-}" | grep -q '"decision"'; then
  NI_OUT=$(printf '%s' "$INPUT" | timeout "$LEFT_SEC" python3 -I "$(dirname "$0")/needs_input_popup_check.py" 2>/dev/null)
  [ -n "$NI_OUT" ] && printf '%s\n' "$NI_OUT"
fi

# WHY: 일한 턴인데 .scratch/handoff/<세션 앞 8자>.md 가 30분 넘게 묵었으면 block 한다(2026-10-23 사용자 지시, scripts/handoff_check.py).
# settings.json 배선을 늘리지 않으려고 이 Stop 훅 안에서 부른다.
LEFT_SEC=$(( 13 - SECONDS ))
[ "$LEFT_SEC" -gt 3 ] && LEFT_SEC=3
if [ "$LEFT_SEC" -ge 1 ] && [ "$EVENT" = "Stop" ] && ! printf '%s' "${KO_OUT:-}" | grep -q '"decision"' && [ -z "$NI_OUT" ]; then
  printf '%s' "$INPUT" | timeout "$LEFT_SEC" python3 -I "$(dirname "$0")/handoff_check.py" 2>/dev/null
fi

exit 0
