#!/usr/bin/env bash
# t41-ledger.sh — T41 짧은 id 대장(`_evolve/t41-ledger.jsonl`)의 유일한 쓰기 경로이자 transcript 경로 검사의 정본 (2026-11-16 신설)
#
# 왜: `_audit/history.md`(git 추적)의 T41 줄은 역할 · 차원 · 신호만 남겨, 뒤에서 «그 약점을 낸 소집이 실제로 무엇을 했나»
#   (C3 · C4 궤적 재판정)를 찾을 길이 없었다. 그렇다고 transcript 경로 · 세션 id 를 history 에 적으면 추적 파일에 세션이 드러난다.
#   그래서 history 에는 무작위 짧은 id 만 남기고, id → 세션 · 보고 에이전트 · 행위자 · 행위자 transcript 는 추적 제외 대장에 둔다.
#   (계획 docs/superpowers/plans/2026-11-16-paper-concepts-eval-loop.md 2절 · 의뢰서 intent/2026-11-16-paper-concepts-eval-loop.md P0)
#
# 하위 명령:
#   add <session> <reporter> <actor> <actor_tp> <role> <dim> <path> <gap_s> <n_cand>
#       새 id 를 만들어 대장에 한 줄 JSON 을 덧붙이고 stdout 에 id(16진 8자)를 낸다. 실패면 exit 1(stderr 한 줄, stdout 빈 값).
#       호출자는 t41-append.sh 의 `_usage/t41.lock` 임계구역 안이다. 여기서 대장 자체 잠금(flock -w 2)을 겹친다(잠금 순서 t41 → ledger).
#       `_evolve` 자체가 링크이거나 대장이 링크 · 일반 파일 아님 · 권한 600 아님이면 거부한다(호출자는 id 없이 기록).
#   get <id>            대장 한 줄을 그대로 낸다. 없거나 id 꼴이 아니면 exit 2.
#   transcript <id>     행위자 transcript 실제 경로를 낸다. 종료 코드가 «재판정 제외 · 판정 보류» 경계다:
#                         0 경로 출력 · 2 id 없음 또는 행위자 빈 칸(제외) · 3 파일 없음(제외) · 4 링크 · 일반 파일 아님 · 접두 밖 · 이름 · 읽기 불가(판정 보류)
#   find-actor <reporter_tp> <role>     (환경변수 T41_SELF=1 이면 자기 귀속)
#       행위자 찾기. stdout 네 줄(행위자 id · 행위자 transcript · gap_s · n_cand), 못 찾으면 행위자 칸이 빈 줄. 호출자가 `timeout 2` 로 감싼다.
#   stats [--since YYYY-MM-DD]
#       history 의 새 T41 수 · 짧은 id 수 · 행위자 찾은 수와 두 비율, 찾은 건의 단일 · 모호(n_cand) · gap_s 구간,
#       유효 보존일 · 실측 최고령(일)을 낸다(읽기 전용).
#       분모는 history 의 T41 줄이고 대장 행은 그 줄의 id 로만 조인한다. add 뒤 history 기록 전에 끊기면(시간 초과 · 디스크 오류)
#       짝 없는 대장 행이 남을 수 있다. 바깥 t41.lock 대기 방식을 바꿔 막는 대신(그러면 T41 기록 자체를 잃는 경우가 생겨 더 나쁘다)
#       집계에서 대장을 기준으로 세지 않아 그런 행이 수치에 들어가지 않게 한다(2026-11-16 검수 반송 6).
#
# 대장 칸: id · ts · session · reporter · actor · actor_tp · role · dim · path(sync|async|manual|auto) · gap_s · n_cand
#   n_cand: 역할 · 시각 조건을 만족한 후보 수(0 · 1 · 2+). 자기 귀속 · main · 탐색 불가는 빈 칸이다. 2 이상이면 «가장 최근» 선택이 모호한 건이다.
#   버린 안: TSV(경로에 탭 · 개행이 들어가면 깨짐, 이스케이프 규칙을 따로 둬야 함) · candidates.tsv 열 추가(7열 계약이 바뀜).
# 안전: 대장은 umask 077 로 만들고 쓸 때마다 «링크 아님 · 일반 파일 · 권한 600» 을 확인한다. 하나라도 어긋나면 쓰지 않는다
#   (누가 대장을 링크로 바꿔 다른 파일에 덧붙이게 하거나, 권한을 넓혀 경로 · 세션 id 를 노출하는 길을 닫는다).
set -euo pipefail
# REF: knowledge/harness/code-history/scripts__t41-ledger.sh.md

CLAUDE_DIR="${HOME}/.claude"
LEDGER="${CLAUDE_DIR}/_evolve/t41-ledger.jsonl"
LEDGER_LOCK="${CLAUDE_DIR}/_evolve/t41-ledger.lock"
HISTORY="${CLAUDE_DIR}/_audit/history.md"
PROJ_ROOT="${CLAUDE_DIR}/projects"

die() { echo "t41-ledger: $*" >&2; exit 1; }
valid_id() { [[ "$1" =~ ^[0-9a-f]{8}$ ]]; }

# WHY: od 는 정확히 4바이트만 읽고 끝나므로 `tr </dev/urandom | head` 꼴처럼 pipefail 아래 SIGPIPE(141)로 죽지 않는다.
new_id() { od -An -N4 -tx1 /dev/urandom | tr -d ' \n'; }

ledger_ok() {
  [[ -L "${LEDGER}" ]] && { echo "t41-ledger: 대장이 링크라 거부 (${LEDGER})" >&2; return 1; }
  [[ -e "${LEDGER}" ]] || return 0
  [[ -f "${LEDGER}" ]] || { echo "t41-ledger: 대장이 일반 파일이 아니라 거부 (${LEDGER})" >&2; return 1; }
  [[ "$(stat -c %a "${LEDGER}")" == "600" ]] || { echo "t41-ledger: 대장 권한이 600 이 아니라 거부 (${LEDGER})" >&2; return 1; }
}

# NEVER: 존재 검사를 링크 검사보다 먼저 하지 않는다. `-e` 는 링크를 따라가 끊긴 링크를 «없음(3)» 으로 보는데, 끊긴 링크는 누가 경로를 바꾼 흔적이라 보류(4)다.
# NEVER: 접두 판정에서 대상과 접두 가운데 한쪽만 실제 경로로 풀지 않는다. 한쪽만 풀면 HOME 이 링크일 때 정상 경로가 접두 밖으로 보이고,
#   대상만 문자열로 보면 `projects/../x` · 중간 링크로 접두 밖 파일을 열 수 있다.
check_path() {
  local p="$1" real root
  [[ -n "${p}" && "${p}" != *$'\n'* ]] || return 4
  [[ "${p}" == *.jsonl ]] || return 4
  [[ -L "${p}" ]] && return 4
  [[ -e "${p}" ]] || return 3
  [[ -f "${p}" ]] || return 4
  real="$(readlink -f -- "${p}" 2>/dev/null)" || return 4
  root="$(readlink -f -- "${PROJ_ROOT}" 2>/dev/null)" || return 4
  [[ -n "${root}" && "${real}" == "${root}"/* ]] || return 4
  [[ -r "${real}" ]] || return 4
  printf '%s' "${real}"
}

# NEVER: 대장 조회를 문자열 grep 으로 하지 않는다. jq 로 id 칸을 비교한다(칸 사이 공백 · 칸 순서가 달라도 같은 행을 찾고, 다른 칸 값 속 글자에 맞지 않게).
#   손상된 줄 하나가 전체를 멈추지 않게 fromjson? 로 관용 파싱한다.
ledger_line() {
  [[ -f "${LEDGER}" && ! -L "${LEDGER}" ]] || return 0
  jq -Rcn --arg id "$1" '[inputs | fromjson? | select(type == "object" and .id == $id)] | last // empty' "${LEDGER}" 2>/dev/null || true
}

cmd_add() {
  [[ $# -eq 9 ]] || die "사용법: add <session> <reporter> <actor> <actor_tp> <role> <dim> <path> <gap_s> <n_cand>"
  command -v jq >/dev/null 2>&1 || die "jq 없음 — 대장 기록 생략"
  command -v flock >/dev/null 2>&1 || die "flock 없음 — 잠금 없이 대장을 쓰지 않는다"
  # NEVER: 폴더 링크 검사를 빼지 않는다. `_evolve` 가 링크면 대장 · 잠금 파일이 링크 대상 폴더(추적 폴더일 수 있음)에 생기고, 파일 단위 링크 검사로는 못 막는다.
  [[ -L "${CLAUDE_DIR}/_evolve" ]] && die "_evolve 가 링크라 거부 (${CLAUDE_DIR}/_evolve)"
  mkdir -p "${CLAUDE_DIR}/_evolve" 2>/dev/null || true
  umask 077
  exec 8>"${LEDGER_LOCK}" || die "잠금 파일 열기 실패 (${LEDGER_LOCK})"
  flock -w 2 8 || die "대장 잠금 2초 초과"
  ledger_ok || exit 1
  [[ -e "${LEDGER}" ]] || : >> "${LEDGER}" || die "대장 생성 실패"
  ledger_ok || exit 1
  local id="" row
  for _ in 1 2 3 4 5; do
    id="$(new_id)"
    valid_id "${id}" || { id=""; continue; }
    [[ -n "$(ledger_line "${id}")" ]] || break
    id=""
  done
  [[ -n "${id}" ]] || die "id 충돌 5회 — id 없이 기록"
  row="$(jq -nc --arg id "${id}" --arg ts "$(date -Is)" --arg session "$1" --arg reporter "$2" --arg actor "$3" \
      --arg actor_tp "$4" --arg role "$5" --arg dim "$6" --arg path "$7" --arg gap_s "$8" --arg n_cand "$9" \
      '{id:$id, ts:$ts, session:$session, reporter:$reporter, actor:$actor, actor_tp:$actor_tp, role:$role, dim:$dim, path:$path, gap_s:$gap_s, n_cand:$n_cand}')" \
      || die "JSON 생성 실패"
  printf '%s\n' "${row}" >> "${LEDGER}" || die "대장 쓰기 실패"
  printf '%s\n' "${id}"
}

cmd_get() {
  valid_id "${1:-}" || exit 2
  command -v jq >/dev/null 2>&1 || exit 2
  local line; line="$(ledger_line "$1")"
  [[ -n "${line}" ]] || exit 2
  printf '%s\n' "${line}"
}

cmd_transcript() {
  valid_id "${1:-}" || exit 2
  command -v jq >/dev/null 2>&1 || exit 4
  local line tp real rc=0
  line="$(ledger_line "$1")"
  [[ -n "${line}" ]] || exit 2
  tp="$(jq -r '.actor_tp // ""' <<< "${line}" 2>/dev/null)" || exit 4
  [[ -n "${tp}" ]] || exit 2
  real="$(check_path "${tp}")" || rc=$?
  [[ "${rc}" -eq 0 ]] || exit "${rc}"
  printf '%s\n' "${real}"
}

# WHY: 행위자의 끝난 시각으로 `agent-*.jsonl` 수정 시각을 쓴다. meta.json 에는 종료 시각 칸이 없다(2026-11-16 실측 키: agentType · customAgentType · description · name ·
#   toolUseId · finished(불리언) · spawnDepth 등). 마지막 기록 시각 ≈ 끝난 시각이라 대용으로 쓰고, 어긋날 수 있으니 gap_s
#   (보고 시작 − 행위자 수정 시각, 초)를 함께 남겨 뒤에서 의심 건을 거른다. teammate 는 늦게 바뀔 수 있다(계획 5절).
# NEVER: 자기 귀속 여부를 귀속 역할과 보고 역할 문자열 비교로 정하지 않는다. t41-append.sh 의 귀속 분기가 정한 표지(환경변수 T41_SELF=1)로만 판단한다.
#   문자열을 다시 비교하면 표 밖 역할(foo → general-purpose)은 자기 귀속인데 남을 찾고, `target=<같은 역할>` 은 남을 가리키는데
#   자신으로 적혔다(2026-11-16 검수 반송 3).
# NEVER: 가장 최근 후보가 경로 검사에서 통과하지 못하면(링크 등) 더 오래된 후보로 넘어가지 않고 빈 칸으로 둔다(반송 5):
#   넘어가면 «누가 최근 기록을 링크로 바꿔 둔» 경우에 엉뚱한 옛 소집이 행위자로 적힌다. 판정 보류가 맞다.
cmd_find_actor() {
  local rtp="${1:-}" role="${2:-}" rreal dir rid start ts mt f meta t n pick="" pick_mt=0 ncand=0
  emit() { printf '%s\n%s\n%s\n%s\n' "$1" "$2" "$3" "$4"; exit 0; }
  [[ -n "${role}" && "${role}" != "main" ]] || emit "" "" "" ""
  rreal="$(check_path "${rtp}")" || emit "" "" "" ""
  rid="${rreal##*/}"; rid="${rid%.jsonl}"
  [[ "${rid}" == agent-* ]] || emit "" "" "" ""
  [[ "${T41_SELF:-0}" == 1 ]] && emit "${rid}" "${rreal}" "" ""
  command -v jq >/dev/null 2>&1 || emit "" "" "" ""
  # shellcheck source=/dev/null
  . "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/role-alias.sh"
  dir="${rreal%/*}"
  ts="$(head -n 50 "${rreal}" | jq -rR 'fromjson? | .timestamp // empty' 2>/dev/null | head -1 || true)"
  [[ -n "${ts}" ]] || emit "" "" "" ""
  start="$(date -d "${ts}" +%s 2>/dev/null)" || emit "" "" "" ""
  # WHY: meta 를 파일마다 jq 로 열면 한 세션 수백~천 개에서 훅 제한(5초)을 넘는다. awk 한 번으로 «파일 이름<TAB>내용» 한 줄씩 만들고
  #   jq 한 번이 줄마다 fromjson? 으로 푼다. 그냥 JSON 으로 읽으면 깨진 meta 하나에서 jq 가 멈춰 그 뒤 파일이 모두 빠졌다(반송 4, 실측 rc=4).
  #   `jq -R` 로 여러 파일을 바로 읽지 않는 이유: meta 는 끝 개행이 없어(2026-11-16 실측) 앞 파일 끝과 다음 파일 첫 줄이 한 줄로 붙는다.
  #   awk 는 파일마다 레코드를 끊으므로 깨진 파일만 건너뛴다(여러 줄로 쓴 meta 도 한 줄로 합쳐 푼다).
  declare -A TYPE=() NORM=()
  while IFS=$'\t' read -r f t; do
    [[ -n "${f}" ]] && TYPE["${f}"]="${t}"
  done < <(awk 'FNR == 1 { if (f != "") print f "\t" b; f = FILENAME; b = "" } { b = b $0 } END { if (f != "") print f "\t" b }' \
          "${dir}"/agent-*.meta.json 2>/dev/null \
      | jq -Rr 'index("\t") as $i | select($i != null) | (.[$i + 1:] | fromjson? // null) as $m | select($m | type == "object")
          | [.[:$i], ($m.customAgentType // $m.agentType // "" | tostring)] | @tsv' 2>/dev/null || true)
  while IFS=$'\t' read -r mt f; do
    [[ -n "${f}" && "${f}" != "${rreal}" ]] || continue
    (( mt <= start )) || continue
    meta="${f%.jsonl}.meta.json"
    t="${TYPE["${meta}"]:-}"
    [[ -n "${t}" ]] || continue
    if [[ -z "${NORM["${t}"]+x}" ]]; then
      n="$(normalize_role "${t}")"; NORM["${t}"]="${n:-${t}}"
    fi
    [[ "${NORM["${t}"]}" == "${role}" ]] || continue
    ncand=$(( ncand + 1 ))
    [[ "${ncand}" -eq 1 ]] && { pick="${f}"; pick_mt="${mt}"; }
  done < <(stat -c $'%Y\t%n' -- "${dir}"/agent-*.jsonl 2>/dev/null | sort -t $'\t' -k1,1nr || true)
  [[ -n "${pick}" ]] || emit "" "" "" "${ncand}"
  check_path "${pick}" >/dev/null || emit "" "" "" "${ncand}"
  n="${pick##*/}"
  emit "${n%.jsonl}" "$(readlink -f -- "${pick}")" "$(( start - pick_mt ))" "${ncand}"
}

cmd_stats() {
  local since=""
  if [[ "${1:-}" == "--since" ]]; then since="${2:-}"; fi
  [[ -z "${since}" || "${since}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || die "사용법: stats [--since YYYY-MM-DD]"
  local lines n_t41 n_id ids rows="" keep src oldest
  lines="$(grep -E '^- [0-9]{4}-[0-9]{2}-[0-9]{2} T41: ' "${HISTORY}" 2>/dev/null \
      | awk -v c="${since}" '{ if (c == "" || $2 >= c) print }' || true)"
  n_t41="$(grep -c . <<< "${lines}" || true)"
  ids="$(grep -oE ' — \[t41id:[0-9a-f]{8}\] ' <<< "${lines}" | grep -oE '[0-9a-f]{8}' || true)"
  n_id="$(grep -c . <<< "${ids}" || true)"
  if [[ -n "${ids}" && -f "${LEDGER}" && ! -L "${LEDGER}" ]] && command -v jq >/dev/null 2>&1; then
    rows="$(jq -rR 'fromjson? | select(type == "object") | [(.id // ""), (.actor // ""), (.n_cand // ""), (.gap_s // "")] | map(tostring) | @tsv' \
        "${LEDGER}" 2>/dev/null || true)"
  fi
  if [[ "${n_t41}" -eq 0 ]]; then
    echo "새 T41 0건${since:+ (since ${since})}"
  elif [[ "${n_id}" -eq 0 ]]; then
    echo "짧은 id 0건 (새 T41 ${n_t41}건${since:+, since ${since}})"
  else
    awk -F'\t' -v t="${n_t41}" -v s="${since}" '
      FNR == NR { if ($1 != "") ids[++ni] = $1; next }
      { act[$1] = $2; nc[$1] = $3; gap[$1] = $4 }
      END {
        for (k = 1; k <= ni; k++) {
          id = ids[k]; if (!(id in act) || act[id] == "") continue
          a++
          if (nc[id] == "") self++; else if (nc[id] + 0 >= 2) amb++; else one++
          g = gap[id]
          if (g == "") gb++; else if (g + 0 <= 600) g1++; else if (g + 0 <= 3600) g2++; else g3++
        }
        printf "새 T41 %d건 · 짧은 id %d건(%.1f%%) · 행위자 찾음 %d건(짧은 id 중 %.1f%%)%s\n", t, ni, 100*ni/t, a, 100*a/ni, (s == "" ? "" : " (since " s ")")
        printf "행위자 찾음 %d건 내역: 단일(n_cand=1) %d · 모호(n_cand≥2) %d · 자기 귀속 %d\n", a, one, amb, self
        printf "행위자 찾음 gap_s: 10분 이하 %d · 1시간 이하 %d · 1시간 초과 %d · 빈 칸 %d\n", g1, g2, g3, gb
      }' <(printf '%s\n' "${ids}") <(printf '%s\n' "${rows}")
  fi
  # WHY: 유효 보존일은 settings.json 의 cleanupPeriodDays, 없으면 Claude Code 설정 스키마 표기 기본값 30(계획 5절).
  keep="$(jq -r '.cleanupPeriodDays // empty' "${CLAUDE_DIR}/settings.json" 2>/dev/null || true)"
  src="settings.json cleanupPeriodDays"
  [[ "${keep}" =~ ^[0-9]+$ ]] || { keep=30; src="설정 없음 · 기본값(Claude Code 설정 스키마 표기)"; }
  oldest="$(find "${PROJ_ROOT}" -name '*.jsonl' -type f -printf '%T@\n' 2>/dev/null | sort -n | head -1 || true)"
  if [[ -n "${oldest}" ]]; then
    oldest="$(( ( $(date +%s) - ${oldest%.*} ) / 86400 ))일"
  else
    oldest="측정 불가(transcript 없음)"
  fi
  echo "유효 보존일 ${keep}일(${src}) · 실측 최고령 ${oldest}"
  [[ "${keep}" -ge 30 ]] || echo "보존 설정 검토 필요: 유효 보존일 ${keep}일 < T41_REPEAT 창 30일"
}

sub="${1:-}"; shift || true
case "${sub}" in
  add) cmd_add "$@" ;;
  get) cmd_get "$@" ;;
  transcript) cmd_transcript "$@" ;;
  find-actor) cmd_find_actor "$@" ;;
  stats) cmd_stats "$@" ;;
  *) echo "사용법: t41-ledger.sh add|get|transcript|find-actor|stats …" >&2; exit 2 ;;
esac
