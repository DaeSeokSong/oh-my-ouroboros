#!/usr/bin/env bash
# correction-detect.sh — 사용자 교정 발화(T12) 를 후보 대장에 기계로 적는다. (2026-09-14 신설)
#
# 왜 훅인가: T12 는 "사용자 교정 감지 → 저장 → 3회+ 면 룰 후보" 인데, 감지와 저장이 모두 모델
#   의무 문장이라 `_evolve/candidates.tsv` 에 T12 행이 0건이었다 (09-14 감사 §2-1·§2-3).
#   프롬프트 원문은 이미 `_evolve/prompts.jsonl` 에 쌓이므로, 저장만 결정론적으로 떼어내
#   SessionStart 에서 훑는다. 판정·룰화 제안은 여전히 모델·사용자 몫이고 여기서는 후보만 남긴다.
#
# 매칭 키워드(2026-10-17): 후보의 note 열에 `kw=<키워드>` 로 남긴다. 요약 열은 그대로 두어 중복 판정 키를 보존한다.
#
# 사용: bash correction-detect.sh   (인자 없음. 어떤 실패에서도 exit 0 — 세션 시작을 막지 않는다)
# 출력: 새로 추가한 건수 1줄 (0건이면 무출력 — T03 주입 비용을 상수로 두기 위함)
set -uo pipefail

CLAUDE_DIR="$HOME/.claude"
EVOLVE_DIR="$CLAUDE_DIR/_evolve"
LOG="$EVOLVE_DIR/prompts.jsonl"
SCAN_LINES=400  # 최근 400줄 — 세션 시작마다 전량(3,500줄+) 재스캔은 낭비고, 중복 차단이 있어 누락도 없다.

[ -f "$LOG" ] || exit 0
command -v jq >/dev/null 2>&1 || exit 0

# 교정 발화 정규식 (2026-09-14 확정, 같은 날 재감사로 4종 추가). 프롬프트 로그 실측에서 뽑은
# 표면형이며, 의미 판정이 아니라 후보 표시가 목적이라 재현율을 우선하고 오탐은 모델 판정에 맡긴다.
# `매번|항상|다시는|앞으로도` 는 learner.md:11 의 룰 업데이트 표지와 같은 목록이다 — 정본이 표지로
# 쓰는 말을 감지기가 안 보면 그 행의 트리거가 영영 기계로 잡히지 않는다.
PATTERNS_CORE='하지 ?마|앞으로는|앞으로도|매번|항상|다시는|왜 .{0,20}(했|하고|하지)|잘못|말라고'
# «다시 … 해» 는 교정일 수도 단순 재요청일 수도 있다. 재요청형(«다시 출력해»·«다시 보고해»)을
# 빼지 않으면 일상 지시가 교정 후보로 쌓여 7일 경보가 소음이 된다. grep -E 에 부정 예견이 없어
# 두 단계로 가른다: 핵심 표지가 있으면 바로 채택, 없고 «다시 …해» 뿐이면 재요청형만 걸러낸다.
RETRY_RX='다시 .{0,10}해'
RETRY_EXCL='다시 ?(출력|보고|확인|알려|보여|정리|설명|검토)'
# 사용자 본인 실수형(2026-11-12): 핵심 표지가 «잘못» 하나뿐이고 이 식에 맞으면 교정이 아니다
# («프롬프트 잘못 입력했어» T12-20261112-09). «잘못 만들었어» 같은 교정은 이 식에 안 맞아 그대로 잡힌다.
# 주어가 사용자 자신인 꼴만 넘긴다: «내가·제가 잘못 …» 과 입력 행위(«잘못 입력했·눌렀·붙여»). «잘못 이해했·알려·말했·표현» 은
# 주어가 없거나 «너·네가» 이면 어시스턴트 교정이라 잡는다(«너 잘못 이해했어»·«잘못 알려 줬잖아»).
SELF_RX='(내가|제가) ?잘못|잘못 ?(입력했|눌렀|붙여)'

# herestring 으로 먹인다 — `printf | grep -q` 는 grep 이 첫 매치에서 즉시 끝나 printf 가 SIGPIPE(141)로
# 죽고, `set -o pipefail` 이 그 141 을 파이프라인 결과로 삼아 **매치인데 불일치로 읽힌다**. 문자열 앞쪽에서
# 맞는 표지(«항상 …»)일수록 자주 터지는 경합이었다 (2026-09-14 테스트에서 재현).
is_correction() {  # 0=교정 발화로 본다
  if LC_ALL=C.utf8 grep -qE "$PATTERNS_CORE" <<< "$1"; then
    [ "$(LC_ALL=C.utf8 grep -oE "$PATTERNS_CORE" <<< "$1" | sort -u)" = "잘못" ] \
      && LC_ALL=C.utf8 grep -qE "$SELF_RX" <<< "$1" || return 0
  fi
  LC_ALL=C.utf8 grep -qE "$RETRY_RX" <<< "$1" || return 1
  LC_ALL=C.utf8 grep -qE "$RETRY_EXCL" <<< "$1" && return 1
  return 0
}

# 프롬프트 안의 개행·탭은 TSV 를 깨뜨리므로 추출 단계에서 공백으로 바꾼다.
# fromjson? — 손상된 한 줄이 전체 파싱을 중단시키지 않게 (pattern-detect.sh 와 같은 이유).
# 사람이 쓴 말만 본다(2026-11-12, 미판정 128건 중 103건이 잡음이던 실측): prompt-log.sh 는 훅·예약 메시지도 그대로
#   적으므로 여기서 거른다. 로그 자체는 APPROVED 인용 대조에 쓰여 고치지 않는다.
#   1) 접두 `[하네스 변경 알림`(본문 끝 «보고하지 마십시오» 가 78건 오탐) · `[예약 점검` · `<system-reminder` 는 통째로 뺀다.
#   2) `<pasted_content` 뒤(붙여 넣은 터미널 출력)는 잘라 내고 앞의 사용자 문장만 본다.
#   3) `[결정 팝업 확인]` 은 선택지 문구(«잘못된 막힘» 같은 기능 이름)를 빼고 «직접 입력)» 뒤 구간만 남긴다.
#      직접 입력에는 진짜 교정이 들어온다(T12-20261110-27 «앞으로는 각 모델당 effort …» 가 실제 규칙이 됨).
#      구간 끝은 다음 항목 머리 « - E2 » 꼴이다.
PROMPTS=$(tail -n "$SCAN_LINES" "$LOG" 2>/dev/null \
  | jq -rR 'fromjson? | .prompt // empty
      | select(test("^\\s*(\\[하네스 변경 알림|\\[예약 점검|<system-reminder)") | not)
      | gsub("[\n\r\t]"; " ")
      | sub("<pasted_content.*$"; "")
      | if startswith("[결정 팝업 확인]") then ([scan("직접 입력\\)\\s*(.*?)(?=\\s-\\s[A-Z][A-Za-z]*[0-9]+\\s|$)") | .[0]] | join(" ")) else . end
      | select(test("\\S"))' 2>/dev/null)
[ -n "$PROMPTS" ] || exit 0

# 매칭은 python3 re 로 한 번에 건다 (2026-10-01 감사 P6): grep 3.7 은 `.` 가 U+D558 이상 글자(«확»·«한»
# 등 ㅎ 계열)를 못 맞혀 «왜 확인 안 했어»·«다시 한번 제대로 해» 같은 교정을 놓쳤다. 패턴은 위 정본 그대로
# 넘기고, python3 가 없거나 실패하면 종전 grep 판정으로 폴백한다.
# 출력은 «매칭 키워드<TAB>발화» (2026-10-17 G2): 키워드는 후보 대장 note 열에 `kw=` 로 남긴다. 요약 열에 섞으면
# 중복 판정 키가 바뀌어 같은 발화가 새 후보가 된다. 발화 안의 탭은 위 gsub 가 이미 공백으로 바꿨다.
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
  # 앞 60자(문자 단위). 절단을 python3 로 되돌린다 (2026-09-14): 이 서버의 grep 3.7 은 로케일과
  # 무관하게 `.` 가 U+D558 이상(«하»·«한»·«항»·«해» 등 ㅎ 계열) 을 못 맞혀, `grep -oE '^.{1,60}'`
  # 가 그 글자로 시작하는 발화에서 **빈 문자열**을 냈다 — «항상 …» 교정이 통째로 버려졌다.
  # prompt-log.sh 와 같은 폴백 구조(python3 문자 절단 → 부재 시 cut 바이트 절단)를 쓴다.
  SUMMARY=$(printf '%s' "$line" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//' \
    | { python3 -c 'import sys; sys.stdout.write(sys.stdin.read()[:60])' 2>/dev/null || cut -c1-60; })
  [ -n "$SUMMARY" ] || continue
  # 쓰기·중복 차단·id 연번은 candidates-append.sh 잠금 안에서만 — 직접 cp→mv 하던 판은
  # 세션 동시 시작에서 서로를 덮어썼다(09-14 재감사 B1). stdout 만 버리고 stderr 는 흘린다.
  # 키워드는 --note "kw=…" 로만 넘긴다(요약=중복 키 불변, 정제는 candidates-append.sh 가 한다).
  NOTE_ARGS=(); [ -n "$KW" ] && [ "$KW" != "-" ] && NOTE_ARGS=(--note "kw=$KW")
  if bash "$CLAUDE_DIR/scripts/candidates-append.sh" T12 "$SUMMARY" ${NOTE_ARGS[@]+"${NOTE_ARGS[@]}"} >/dev/null; then
    ADDED=$((ADDED + 1))
  fi
done <<EOF
$MATCHED
EOF

[ "$ADDED" -gt 0 ] && echo "T12 교정 후보 ${ADDED}건 추가 (_evolve/candidates.tsv)"
exit 0
