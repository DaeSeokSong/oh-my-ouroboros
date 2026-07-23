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

TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
[ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] || exit 0

# 마지막 assistant 메시지의 text 콘텐츠만 추출 (tail로 최근 구간 한정 — 대형 transcript 성능 보호)
LAST_TEXT=$(tail -n 300 "$TRANSCRIPT" 2>/dev/null | jq -rs '
  [ .[] | select(.type=="assistant") ] | last
  | (.message.content? // [] | if type=="array" then .[] else empty end
       | select(.type=="text") | .text) ' 2>/dev/null)
# 마지막 assistant 메시지의 **모든** text 블록 검사 (2026-07-18 Codex): 종전 `last`는 마지막
# 블록만 봐 앞 블록의 마크업 유출을 놓쳤다. 위 jq는 마지막 메시지의 전 text 블록을 이어 반환.
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

exit 0
