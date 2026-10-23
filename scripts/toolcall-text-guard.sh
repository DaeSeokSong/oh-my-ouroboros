#!/usr/bin/env bash
# toolcall-text-guard.sh — Stop/SubagentStop 훅: "도구 호출이 텍스트로 출력되는" 장문 컨텍스트 실패 자가 복구
#
# 배경 (2026-07-14 사용자 보고): 컨텍스트가 길어지면 모델이 Bash 등 도구 호출을
# 실제 호출 채널이 아닌 본문 텍스트(함수 호출 XML 마크업 원문)로 출력하는 실패가 빈발.
# 하네스는 이를 실행하지 않으므로 작업이 조용히 누락된 채 턴이 끝난다.
#
# 원리: Stop 시점에 transcript 마지막 assistant 메시지의 text 파트를 검사 —
#   여는 invoke 태그 + parameter 태그가 "둘 다" 텍스트로 남아 있으면 decision:block으로
#   종료를 막고 "방금 텍스트로 쓴 호출을 실제 도구 호출로 재실행하라"는 지시를 주입한다.
#
# 오탐/루프 가드 (설계 근거 — 판단 근거 이식):
#   ① 두 태그 동시 존재 요구: 문서·설명에서 태그 하나를 인용하는 정상 응답은 통과.
#   ② stop_hook_active=true면 즉시 통과: 재시도는 1회로 한정 — 무한 루프 방지.
#      (정상 응답이 오탐돼도 비용은 "추가 1턴" 한 번뿐)
#   ③ 실패는 항상 exit 0 침묵 통과: 훅 자체 오류로 세션 종료를 막는 일이 없도록 fail-open.
set -uo pipefail

INPUT=$(cat 2>/dev/null) || exit 0

ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)
[ "$ACTIVE" = "true" ] && exit 0

# 하네스 변경 전파 확인(2026-10-21, scripts/propagate-gate.sh). 이 세션이 만든 하네스 커밋을 다른 로컬 세션이 받지 못했으면
# 그 차단 JSON 을 그대로 내고 끝낸다. 이 Stop 훅이 settings.json 에 이미 연결돼 있어 여기서 부른다(settings 는 사용자만 고친다).
GATE_OUT=$(printf '%s' "$INPUT" | bash "$(dirname "$(readlink -f "$0")")/propagate-gate.sh" 2>/dev/null) || GATE_OUT=""
if [ -n "$GATE_OUT" ]; then
  printf '%s\n' "$GATE_OUT"
  exit 0
fi

# 마지막 응답은 입력의 last_assistant_message 를 먼저 쓴다(기록 파일 끝은 훅 시점에 최신이 아니다 — knowledge/harness/stop-hook-transcript-race.md).
# SubagentStop 에서 이 필드는 자식 자신의 마지막 메시지다.
LAST_TEXT=$(printf '%s' "$INPUT" | jq -r '.last_assistant_message // empty' 2>/dev/null)

if [ -z "$LAST_TEXT" ]; then
  # 필드가 없을 때만 기록 파일로 폴백. SubagentStop 입력의 transcript_path 는 «부모(main)» 기록이고 자식 기록은 agent_transcript_path 다(2026-10-01 감사).
  # 자식 종료 때 부모의 마지막 메시지를 검사하면 엉뚱한 메시지를 막거나 자식의 유출을 놓친다. Stop 에는 이 필드가 없어 전과 같다.
  TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.agent_transcript_path // .transcript_path // empty' 2>/dev/null)
  [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] || exit 0

  # 마지막 assistant 메시지의 text 콘텐츠만 추출 (tail로 최근 구간 한정 — 대형 transcript 성능 보호)
  LAST_TEXT=$(tail -n 300 "$TRANSCRIPT" 2>/dev/null | jq -rs '
    [ .[] | select(.type=="assistant") ] | last
    | (.message.content? // [] | if type=="array" then .[] else empty end
         | select(.type=="text") | .text) ' 2>/dev/null)
  # 마지막 assistant 메시지의 **모든** text 블록 검사 (2026-07-18 Codex): 종전 `last`는 마지막
  # 블록만 봐 앞 블록의 마크업 유출을 놓쳤다. 위 jq는 마지막 메시지의 전 text 블록을 이어 반환.
fi
[ -n "$LAST_TEXT" ] || exit 0

# 네임스페이스 접두사 유무 양쪽 매칭 (harness 렌더링에 따라 둘 다 관측됨)
OPEN_PAT='<(antml:)?invoke +name='
PARAM_PAT='<(antml:)?parameter +name='

if printf '%s' "$LAST_TEXT" | grep -qE "$OPEN_PAT" \
   && printf '%s' "$LAST_TEXT" | grep -qE "$PARAM_PAT"; then
  jq -n '{decision: "block",
          reason: "직전 응답에서 도구 호출 마크업이 실제 호출로 실행되지 않고 본문 텍스트로 출력되었습니다 (장문 컨텍스트에서 발생하는 알려진 디코딩 실패). 방금 텍스트로 적은 도구 호출을 지금 실제 도구 호출로 다시 실행하세요. 같은 실패가 반복되면 호출을 더 작은 단위로 나누고, 컨텍스트가 75% 이상이면 먼저 handover 기록 후 compact를 고려하세요."}'
  exit 0
fi

# 한글 보고 검사 (Stop 전용, 마크업 검사가 통과한 뒤에만): intent/2026-10-16-korean-report-guard.md.
# 영어 문장이 있으면 판정기가 block JSON 을 출력한다. uv 관리 파이썬, 프로젝트 환경은 건드리지 않고(--no-project) 8초 상한, 실패는 침묵 통과.
# settings.json 의 이 훅 제한은 15초다. 위 전파 확인이 쓴 시간만큼 줄여 13초 안에 끝낸다(qa 2026-10-21: 4+6+8=18초로 넘으면
# 훅이 죽어 영어 보고 차단이 통째로 빠진다). 남은 시간이 2초 미만이면 이번 턴은 판정을 건너뛴다.
LEFT_SEC=$(( 13 - SECONDS ))
[ "$LEFT_SEC" -gt 8 ] && LEFT_SEC=8
if [ "$LEFT_SEC" -ge 2 ] && [ "$(printf '%s' "$INPUT" | jq -r '.hook_event_name // empty' 2>/dev/null)" = "Stop" ]; then
  printf '%s' "$INPUT" | timeout "$LEFT_SEC" uv run -q --no-project python "$(dirname "$0")/korean_report_check.py" 2>/dev/null
fi

exit 0
