#!/usr/bin/env bash
# t41-mask.sh — T41 신호 가림 함수 `mask_cut` 의 정본. 동기 경로(agent-spawn-log.sh)와 비동기 경로(t41-subagent-stop.sh)가 함께 쓴다.
# 사용: `. scripts/t41-mask.sh; printf '%s' "$문장" | mask_cut <최대 코드포인트 수>`
# 마스킹 종류는 scripts/claude-notify.sh 의 MASK_SED 와 같다(고칠 땐 함께). 절단 전에 가려야 반으로 잘린 토큰이 새지 않는다.
# 부수효과 없음: 옵션을 바꾸지 않고 파일을 쓰지 않는다. jq 가 없으면 빈 문자열을 낸다(호출부가 빈 값을 처리한다).
# REF: knowledge/harness/code-history/scripts__t41-mask.sh.md
mask_cut() {
    tr '\t\n\r' '   ' | sed -E \
    -e 's/(^|[^A-Za-z0-9])(sk|tvly)-[A-Za-z0-9_-]{8,}/\1<masked>/g' \
    -e 's/(^|[^A-Za-z0-9])m0-[A-Za-z0-9]{16,}/\1<masked>/g' \
    -e 's/AKIA[A-Z0-9]{12,}/<masked>/g' \
    -e 's/AIza[0-9A-Za-z_-]{30,}/<masked>/g' \
    -e 's/gh[pousr]_[A-Za-z0-9]{20,}/<masked>/g' \
    -e 's/github_pat_[A-Za-z0-9_]{16,}/<masked>/g' \
    -e 's/xox[abprs]-[A-Za-z0-9-]{8,}/<masked>/g' \
    -e 's/AT(ATT|BB|CTT)[A-Za-z0-9_=-]{16,}/<masked>/g' \
    -e 's/Bearer [A-Za-z0-9._-]{16,}/<masked>/g' \
    -e 's/[0-9a-fA-F]{32,}/<masked>/g' \
    -e 's/[0-9]+(\.[0-9]+){5,}/<masked>/g' \
    | jq -Rr --argjson n "$1" '.[0:$n]' 2>/dev/null
}
