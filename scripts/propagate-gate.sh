#!/usr/bin/env bash
# propagate-gate.sh — Stop 훅: 이 세션이 만든 하네스 커밋이 다른 로컬 세션에 전달됐는지 확인하고, 아니면 턴 종료를 한 번 막는다
# 설계: intent/2026-10-21-harness-change-propagation-gate.md 개정 1.
# 흐름: stdin = Stop 훅 입력 JSON. scripts/toolcall-text-guard.sh 가 맨 앞에서 같은 입력으로 부른다.
#   1) Stop 이 아니거나(SubagentStop 등) stop_hook_active=true 면 통과.
#   2) pending.jsonl 에서 author 가 이 세션이고 6시간 안의 줄만 본다. 없으면 통과.
#   3) 살아 있는 다른 로컬 세션 = `claude agents --json`(시험은 $PROPAGATE_AGENTS_JSON 파일)에서 자기 자신을 뺀 목록. pid 가 있으면 살아 있는 것만 센다.
#   4) 세션마다 ack/<세션 id> 에 그 해시가 있으면 받음. 최대 $PROPAGATE_WAIT 초(기본 6) 2초 간격으로 다시 본다.
#      asleep/<세션 id> 첫 칸이 asleep 이고 시각이 120초 안인 세션은 대기 대상에서 뺀다.
#   5) 끝까지 못 받은 세션이 있으면 decision:block 으로 이름·해시와 할 일(SendMessage 직접 알림 → ack manual 기록)을 준다.
#      막은 해시는 blocked/<이 세션 id> 에 적고 다음 Stop 부터는 다시 막지 않는다.
# 실패는 통과(fail-open): jq·claude 가 없거나 파일을 못 읽으면 exit 0. 세션 목록을 못 읽으면 stderr 에 한 줄 남긴다.
# REF: knowledge/harness/code-history/scripts__propagate-gate.sh.md
set -uo pipefail

DIR="${PROPAGATE_DIR:-$HOME/.claude/_usage/propagate}"
PENDING="$DIR/pending.jsonl"
# WHY: 기본 6초. settings.json 이 이 Stop 훅(toolcall-text-guard.sh)에 15초 제한을 두고, 그 스크립트의 영어 문장 판정이 최대 8초를 쓴다.
WAIT="${PROPAGATE_WAIT:-6}"
MAX_AGE=21600

INPUT=$(cat 2>/dev/null) || exit 0
command -v jq >/dev/null 2>&1 || exit 0
EVENT=$(printf '%s' "$INPUT" | jq -r '.hook_event_name // "Stop"' 2>/dev/null)
[ "$EVENT" = "Stop" ] || exit 0
[ "$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)" = "true" ] && exit 0
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
[ -n "$SID" ] && [ -f "$PENDING" ] || exit 0

NOW=$(date +%s)
# NEVER: 차단 사유에 커밋 제목을 싣지 않는다. 모델이 읽는 지시문이라 git am·cherry-pick 으로 들어온 외부 제목이 지시로 읽힌다(security 검수 2026-10-21).
# 해시는 16진 형식만 받는다(grep 옵션·정규식으로 해석될 값 차단).
MINE=$(jq -r --arg s "$SID" --argjson now "$NOW" --argjson age "$MAX_AGE" \
    'select(.author == $s and ($now - .ts) <= $age and ((.hash // "") | test("^[0-9a-f]{7,40}$"))) | .hash' "$PENDING" 2>/dev/null) || exit 0
BLOCKED="$DIR/blocked/$SID"
if [ -n "$MINE" ] && [ -f "$BLOCKED" ]; then
    MINE=$(printf '%s\n' "$MINE" | grep -vxF -f "$BLOCKED")
fi
[ -n "$MINE" ] || exit 0

if [ -n "${PROPAGATE_AGENTS_JSON:-}" ]; then
    AGENTS=$(cat "$PROPAGATE_AGENTS_JSON" 2>/dev/null) || exit 0
else
    AGENTS=$(timeout 4 claude agents --json 2>/dev/null) || { echo "⚠ propagate-gate: 세션 목록을 읽지 못해 전파 확인을 건너뜀" >&2; exit 0; }
fi
ALL=$(printf '%s' "$AGENTS" | jq -r --arg s "$SID" '.[] | select(.sessionId != $s) | "\(.sessionId)\t\(.name // .id)\t\(.pid // "")"' 2>/dev/null) || exit 0
PEERS=""
while IFS=$'\t' read -r psid pname ppid; do
    [ -n "$psid" ] || continue
    if [[ "$ppid" =~ ^[0-9]+$ ]] && ! kill -0 "$ppid" 2>/dev/null; then continue; fi
    # WHY: 첫 지시 전 세션은 mod 가 알림을 미루므로 ack 가 없는 게 정상이고, 여기서 직접 SendMessage 하라고 시키면 빈 세션이 깨어난다
    # (intent/2026-11-02-no-work-in-spare-sessions.md).
    if [[ "$psid" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] && [ -f "$DIR/asleep/$psid" ]; then
        IFS=$'\t' read -r akind ats < "$DIR/asleep/$psid" || true
        if [ "${akind:-}" = "asleep" ] && [[ "${ats:-}" =~ ^[0-9]+$ ]] && [ $((NOW - 10#$ats)) -le 120 ] && [ $((NOW - 10#$ats)) -ge -120 ]; then continue; fi
    fi
    PEERS+="$psid"$'\t'"$pname"$'\n'
done <<< "$ALL"
[ -n "$PEERS" ] || exit 0

missing() {
    local out="" h psid pname
    while IFS= read -r h; do
        [ -n "$h" ] || continue
        while IFS=$'\t' read -r psid pname; do
            [[ "$psid" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || continue
            if ! { [ -f "$DIR/ack/$psid" ] && cut -f1 "$DIR/ack/$psid" | grep -qxF -- "$h"; }; then
                out+="${pname:0:60}"$'\t'"$psid"$'\t'"$h"$'\n'
            fi
        done <<< "$PEERS"
    done <<< "$MINE"
    printf '%s' "$out"
}

LEFT=$(missing)
waited=0
while [ -n "$LEFT" ] && [ "$waited" -lt "$WAIT" ]; do
    sleep 2
    waited=$((waited + 2))
    LEFT=$(missing)
done
[ -n "$LEFT" ] || exit 0

LIST=$(printf '%s' "$LEFT" | awk -F'\t' '{printf "- %s (%s): %s\n", $1, $2, $3}')
# WHY: 막은 해시를 적어 다음 Stop 부터 통과시킨다. mod 가 안 올라간 세션이 하나만 있어도 매 턴 6초 대기 뒤 차단이 되풀이됐다(qa 2026-10-21).
( umask 077; mkdir -p "$DIR/blocked" && printf '%s' "$LEFT" | cut -f3 | sort -u >> "$BLOCKED" ) 2>/dev/null || true
REASON="하네스 변경 전파가 확인되지 않았습니다(${WAIT}초 동안 받음 기록 없음). 아래 세션마다 SendMessage 로 «[하네스 변경 알림 · 회신 불요] <해시> <요약>» 을 직접 보낸 뒤, 세션마다 \`bash ~/.claude/scripts/propagate-queue.sh ack <세션 id> <해시> manual\` 로 기록하십시오. 그 세션에 띠 mod 가 안 올라가 있을 수 있습니다.
$LIST"
jq -n --arg r "$REASON" '{decision: "block", reason: $r}'
exit 0
