#!/usr/bin/env bash
# correction-detect.sh — 사용자 교정 발화(T12) 를 후보 대장에 기계로 적는다.
#   SessionStart 에서 `_evolve/prompts.jsonl` 을 훑어 candidates-append.sh 로 T12 후보만 남긴다. 판정·룰화 제안은 모델·사용자 몫이다.
#   매칭 키워드는 후보의 note 열에 `kw=<키워드>` 로 남긴다. 요약 열은 그대로 두어 중복 판정 키를 보존한다.
#
# 사용: bash correction-detect.sh   (인자 없음. 어떤 실패에서도 exit 0 — 세션 시작을 막지 않는다)
# 출력: 새로 추가한 건수 1줄 (0건이면 무출력 — T03 주입 비용을 상수로 두기 위함)
# REF: knowledge/harness/code-history/scripts__correction-detect.sh.md
set -uo pipefail

CLAUDE_DIR="$HOME/.claude"
EVOLVE_DIR="$CLAUDE_DIR/_evolve"
LOG="$EVOLVE_DIR/prompts.jsonl"
SCAN_LINES=400  # WHY: 세션 시작마다 전량(3,500줄+) 재스캔은 낭비고, 중복 차단이 있어 누락도 없다.

[ -f "$LOG" ] || exit 0
command -v jq >/dev/null 2>&1 || exit 0

# WHY: 프롬프트 로그 실측에서 뽑은 표면형이고(2026-09-14 확정) 후보 표시가 목적이라 재현율을 우선하고 오탐은 모델 판정에 맡긴다.
# `매번|항상|다시는|앞으로도` 는 rules-lazy/learner.md 의 룰 업데이트 표지와 같은 목록이다.
PATTERNS_CORE='하지 ?마|앞으로는|앞으로도|매번|항상|다시는|왜 .{0,20}(했|하고|하지)|잘못|말라고'
# WHY: 재요청형(«다시 출력해»·«다시 보고해»)을 빼지 않으면 일상 지시가 교정 후보로 쌓여 7일 경보가 소음이 된다.
# grep -E 에 부정 예견이 없어 두 단계로 가른다.
RETRY_RX='다시 .{0,10}해'
RETRY_EXCL='다시 ?(출력|보고|확인|알려|보여|정리|설명|검토)'
# WHY: 핵심 표지가 «잘못» 하나뿐이고 이 식에 맞으면 사용자 본인 실수라 교정이 아니다(«프롬프트 잘못 입력했어» T12-20261112-09).
# 주어가 사용자 자신인 꼴(«내가·제가 잘못 …»)과 입력 행위(«잘못 입력했·눌렀·붙여»)만 넘긴다.
SELF_RX='(내가|제가) ?잘못|잘못 ?(입력했|눌렀|붙여)'

# NEVER: `printf | grep -q` 로 먹이지 않는다. grep 이 첫 매치에서 끝나 printf 가 SIGPIPE(141)로 죽고
# pipefail 이 그 141 을 결과로 삼아 매치인데 불일치로 읽힌다(2026-09-14 테스트에서 재현).
is_correction() {
  if LC_ALL=C.utf8 grep -qE "$PATTERNS_CORE" <<< "$1"; then
    [ "$(LC_ALL=C.utf8 grep -oE "$PATTERNS_CORE" <<< "$1" | sort -u)" = "잘못" ] \
      && LC_ALL=C.utf8 grep -qE "$SELF_RX" <<< "$1" || return 0
  fi
  LC_ALL=C.utf8 grep -qE "$RETRY_RX" <<< "$1" || return 1
  LC_ALL=C.utf8 grep -qE "$RETRY_EXCL" <<< "$1" && return 1
  return 0
}

# WHY: prompt-log.sh 는 훅·예약 메시지도 그대로 적어 미판정 128건 중 103건이 잡음이었다(2026-11-12 실측). 로그 자체는 APPROVED 인용 대조에 쓰여 고치지 않는다.
# `[결정 팝업 확인]` 은 선택지 문구를 빼고 «직접 입력)» 뒤 구간만 남긴다. 직접 입력에는 진짜 교정이 들어온다(T12-20261110-27).
PROMPTS=$(tail -n "$SCAN_LINES" "$LOG" 2>/dev/null \
  | jq -rR 'fromjson? | .prompt // empty
      | select(test("^\\s*(\\[하네스 변경 알림|\\[예약 점검|<system-reminder)") | not)
      | gsub("[\n\r\t]"; " ")
      | sub("<pasted_content.*$"; "")
      | if startswith("[결정 팝업 확인]") then ([scan("직접 입력\\)\\s*(.*?)(?=\\s-\\s[A-Z][A-Za-z]*[0-9]+\\s|$)") | .[0]] | join(" ")) else . end
      | select(test("\\S"))' 2>/dev/null)
[ -n "$PROMPTS" ] || exit 0

# WHY: grep 3.7 은 `.` 가 U+D558 이상 글자(«확»·«한» 등)를 못 맞혀 «왜 확인 안 했어» 같은 교정을 놓쳤다(2026-10-01 감사 P6).
# python3 가 없거나 실패하면 grep 판정으로 폴백한다.
# NEVER: 매칭 키워드를 요약 열에 섞지 않는다. 중복 판정 키가 바뀌어 같은 발화가 새 후보가 된다(2026-10-17 G2).
MATCHED=$(printf '%s\n' "$PROMPTS" | python3 -c '
import re, sys
core, retry, excl, selfm = (re.compile(p) for p in sys.argv[1:5])
for l in sys.stdin:
    l = l.rstrip("\n")
    m = core.search(l)
    if m and {x.group(0) for x in core.finditer(l)} == {"잘못"} and selfm.search(l):
        m = None
    if not m and not excl.search(l):
        m = retry.search(l)
    if m:
        print(m.group(0).replace("\t", " ") + "\t" + l)
' "$PATTERNS_CORE" "$RETRY_RX" "$RETRY_EXCL" "$SELF_RX" 2>/dev/null) \
  || MATCHED=$(while IFS= read -r l; do
       is_correction "$l" || continue
       kw=$(LC_ALL=C.utf8 grep -oE "$PATTERNS_CORE" <<< "$l" | head -1); [ -n "$kw" ] || kw=$(LC_ALL=C.utf8 grep -oE "$RETRY_RX" <<< "$l" | head -1)
       printf '%s\t%s\n' "${kw:--}" "$l"
     done <<< "$PROMPTS")
[ -n "$MATCHED" ] || exit 0

ADDED=0

while IFS=$'\t' read -r KW line; do
  [ -n "$line" ] || continue
  # NEVER: `grep -oE '^.{1,60}'` 로 자르지 않는다. grep 3.7 은 `.` 가 U+D558 이상을 못 맞혀 «항상 …» 교정이 통째로 버려졌다(2026-09-14).
  SUMMARY=$(printf '%s' "$line" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//' \
    | { python3 -c 'import sys; sys.stdout.write(sys.stdin.read()[:60])' 2>/dev/null || cut -c1-60; })
  [ -n "$SUMMARY" ] || continue
  # NEVER: 대장을 직접 cp→mv 하지 않는다. 세션 동시 시작에서 서로를 덮어썼다(09-14 재감사 B1).
  # 쓰기·중복 차단·id 연번은 candidates-append.sh 잠금 안에서만 하고 stdout 만 버린다.
  NOTE_ARGS=(); [ -n "$KW" ] && [ "$KW" != "-" ] && NOTE_ARGS=(--note "kw=$KW")
  if bash "$CLAUDE_DIR/scripts/candidates-append.sh" T12 "$SUMMARY" ${NOTE_ARGS[@]+"${NOTE_ARGS[@]}"} >/dev/null; then
    ADDED=$((ADDED + 1))
  fi
done <<EOF
$MATCHED
EOF

[ "$ADDED" -gt 0 ] && echo "T12 교정 후보 ${ADDED}건 추가 (_evolve/candidates.tsv)"
exit 0
