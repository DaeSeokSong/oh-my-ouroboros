#!/usr/bin/env bash
# public-mirror-status.sh — 공개 미러 최신성 한 줄(2026-10-23, intent/2026-10-23-public-mirror-refresh.md).
#
# 출력 예: 마지막 동기화 2026-07-29(86일 전) / 공개본 agents 10 · skills 25 · hooks 18 (발행 예정 13 · 32 · 29) / 게이트 통과
# 공개 저장소를 임시 폴더에 얕게 복제해(읽기 전용, 끝나면 지움) 최신 커밋 날짜와 개수를 세고, public-export.sh --stage-out 으로
# 임시 정제본을 만들어 게이트 결과와 «발행 예정» 개수를 붙인다. 발행 · push 는 하지 않는다.
#   agents = agents/*.md, skills = skills/*/SKILL.md, hooks = settings.json 이 이벤트별로 부르는 scripts/ 스크립트(중복 제외) 수.
# 종료 코드: 0 = 30일 이내이고 agents·skills·hooks 개수가 발행 예정본과 같고 게이트 통과, 1 = 갱신·조치 필요(30일 초과 · 개수 차이 · 게이트 차단), 2 = 조회 실패.
set -uo pipefail

URL="${PUBLIC_MIRROR_URL:-https://github.com/DaeSeokSong/oh-my-ouroboros.git}"
HARNESS="$HOME/.claude"
STALE_DAYS="${PUBLIC_MIRROR_STALE_DAYS:-30}"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/pubmirror.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

count_hooks() {
  jq -r '[.hooks // {} | to_entries[] | .key as $e | .value[]? | .hooks[]? | .command // ""
          | scan("scripts/([A-Za-z0-9_.-]+\\.(?:sh|py))") | $e + ":" + .[0]] | unique | length' "$1" 2>/dev/null || echo "?"
}
count_agents() { find "$1/agents" -maxdepth 1 -name '*.md' -type f 2>/dev/null | wc -l; }
count_skills() { find "$1/skills" -mindepth 2 -maxdepth 2 -name SKILL.md -type f 2>/dev/null | wc -l; }

case "$URL" in
  https://*) ;;
  *) echo "마지막 동기화 조회 실패(공개 저장소 주소는 https:// 만 받습니다) / 공개본 개수 알 수 없음 / 게이트 미실행"; exit 2 ;;
esac
if ! git clone -q --depth 1 -- "$URL" "$TMP/m" 2>/dev/null; then   # -- : 주소가 옵션으로 읽히지 않게(security 2026-10-23)
  echo "마지막 동기화 조회 실패(공개 저장소 복제 불가: $URL) / 공개본 개수 알 수 없음 / 게이트 미실행"
  exit 2
fi
last=$(git -C "$TMP/m" log -1 --format=%cs)
days=$(( ( $(date +%s) - $(git -C "$TMP/m" log -1 --format=%ct) ) / 86400 ))
pa=$(count_agents "$TMP/m"); ps=$(count_skills "$TMP/m"); ph=$(count_hooks "$TMP/m/settings.json")

# 비교 기준은 비공개 원본이 아니라 «지금 내보내면 공개될 정제본» 이다. 2026-10-23 범용화로 내부 전용 파일(골격 게이트 훅 등)을
# 일부러 빼므로, 원본 개수와 비교하면 매번 «개수 차이» 로 잘못 경보한다. 정제본은 게이트가 막아도 남는다(--stage-out).
gate_out=$(bash "$HARNESS/scripts/public-export.sh" --stage-out "$TMP/s" 2>&1); rc=$?
case $rc in
  0) gate="게이트 통과" ;;
  3) gate="게이트 차단(위반 규칙 $(printf '%s\n' "$gate_out" | grep -c '^⛔'))" ;;
  *) gate="게이트 실행 오류(종료 코드 $rc)" ;;
esac
ha=$(count_agents "$TMP/s"); hs=$(count_skills "$TMP/s"); hh=$(count_hooks "$TMP/s/settings.json")

echo "마지막 동기화 ${last}(${days}일 전) / 공개본 agents ${pa} · skills ${ps} · hooks ${ph} (발행 예정 ${ha} · ${hs} · ${hh}) / ${gate}"
if [ "$rc" -ne 0 ] || [ "$days" -gt "$STALE_DAYS" ] || [ "$pa" != "$ha" ] || [ "$ps" != "$hs" ] || [ "$ph" != "$hh" ]; then   # 게이트가 막혀도 갱신 필요(qa 2026-10-23)
  exit 1
fi
exit 0
