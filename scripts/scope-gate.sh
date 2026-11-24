#!/usr/bin/env bash
# scope-gate.sh — PreToolUse hook for Write/Edit
# Checks if target file path is in the registered scope; otherwise block.
#
# 판정 순서 (2026-10-17 하네스 감사 G1 — intent/2026-10-17-harness-audit-fixes.md, 설계 plans/2026-10-17-harness-audit-fixes.md 개정 1·2):
#   0) 경로 정규화: 물리 경로(realpath -m)와 논리 경로(realpath -m -s, 심볼릭 보존)를 둘 다 만들고,
#      하네스 뿌리도 논리($HOME/.claude)·물리(pwd -P)·realpath 세 표기를 대조한다(편측 물리화 금지).
#   1) 항상 차단(예외보다 앞, 매니저도 불가 — 스크립트 전용 파일·위조 방지): sessions/**,
#      scope/ 안에서 훅 session_id 와 다른 파일, _evolve/{candidates.tsv,candidates.lock,crosscheck.tsv,prompts.jsonl,t41-ledger.jsonl,t41-ledger.lock},
#      _usage/**, _audit/publish-approval/**(2026-10-07), projects/*/*.jsonl 세션 기록(2026-10-07).
#      표기 중 하나라도 걸리면 차단한다. 출력은 block_forgery(JSON decision, exit 0).
#   2) 모든 세션 통과: projects/<하나>/memory/?*, knowledge/, doc-formats/, _evolve/quiz/, .scratch/, scope/<자기 session_id>.json.
#      CWD_ROOT 계산 앞에서 판정해 비 git cwd 세션(예: ~/workspace)의 쓰기가 fail-closed 에 걸리지 않는다.
#      물리 경로도 하네스 안일 때만 통과(심볼릭으로 밖을 가리키면 아래 프로젝트 경계 검사로 보낸다).
#   3) 기본값 = 매니저만(2026-10-17 후속): ~/.claude 아래에서 1)·2)·4) 어디에도 속하지 않는 모든 경로
#      (CLAUDE.md·settings*.json·rules/·scripts/·README.md·AGENTS.md·.gitignore·commands/ 등 최상위 파일 전부 포함)는
#      «[Harness] Manager» 세션만 통과한다. 열거 목록이 아니라 기본 거부라 새 폴더도 자동으로 보호된다.
#      cwd 와 무관하다(하네스 저장소가 cwd 여도 다른 이름이면 차단). 비매니저는 여기서 바로 exit 2 로 막아
#      뒤쪽 scope 의 exit 0 에 닿지 않는다. 이 차단은 오류가 아니라 의도된 차단이다.
#   4) 기존 프로젝트 경계 검사로 보내는 fall-through 집합: jobs/·teams/·daemon*·plans/·projects/(memory 밖 경로, 위 1)·2) 제외).
#      plans/ 는 Claude Code 플랜 모드가 ~/.claude/plans 에 쓰는 플랜 파일이라 통제 파일이 아니다(2026-10-17 검수팀. 이 서버엔 아직 폴더가 없다).
#      하네스 밖 경로도 이 검사 → scope 등록 검사로 간다. jq 가 없으면 이 검사를 못 하므로 하네스 안 fall-through 경로는 exit 2 로 닫고
#      (2026-10-17 외부 검토), 하네스 밖 경로만 종전대로 통과한다. scope 폴더가 있을 때 session_id 가 없으면 scope 파일 선택이 불가능해 exit 2 로 닫는다(폴더가 없으면 통과).
#   5) 프로젝트 경계 검사 안의 워크트리 통과(2026-11-21): 다른 뿌리여도 «같은 저장소의 git 워크트리» 면 통과한다. git 명령(--git-common-dir)과
#      git 폴더 안 commondir 파일은 믿지 않는다(위조 가능). 워크트리의 .git 파일과 본 저장소의 worktrees/<이름>/gitdir 가 서로를 가리킬 때만 인정한다(main_git_dir).
#   6) 프로젝트 경계 검사 안의 .git 폴더 안 경로 소속 판정(2026-11-21): .git 폴더 안 경로는 늘 가장 앞의 .git 성분 앞까지를
#      소속 뿌리로 보아 같은 비교를 탄다(종전에는 git 이 뿌리를 못 줘 통과했다. 껍데기 .git 을 HEAD·objects·refs 로 채워 저장소로 만드는 길도 막는다).
#   7) 저장소 뿌리 찾기(2026-11-21 보안 검토): git 을 부르지 않고 폴더를 위로 올라가며 유효한 .git 을 직접 찾는다(find_repo_root).
#      git 은 저장소 설정 core.worktree·환경 변수 GIT_DIR 를 믿어 뿌리를 답하므로, 설정 한 줄을 자기 저장소에 써서 경계를 속일 수 있었다.
#      유효한 .git 은 둘뿐이다: HEAD 파일·objects·refs 가 든 폴더, 또는 첫 줄이 «gitdir: <경로>» 인 일반 파일.
#      표지는 심볼릭 링크를 따라가서 본다(git 이 그렇게 읽기 때문: 뿌리 인식은 넓게, 같은 저장소라는 신뢰 판정 main_git_dir 만 엄격하게.
#      표지를 좁히면 git 이 저장소로 읽는 폴더가 «어느 저장소도 아님» 으로 통과한다. main_git_dir 는 심볼릭 .git 파일을 계속 거부한다).
#      유효하지 않은 .git(빈 껍데기 등)은 건너뛴다. 이 서버의 ~/workspace/.git 은 info/ 만 든 껍데기라 뿌리로 치면
#      workspace 에서 뜬 세션이 모든 프로젝트를 통과시킨다.
#   (1 의 .git/** 도 항상 차단: 훅 설치는 scripts/setup-harness.sh 가 Bash 로 한다.)
#
# 매니저 판정(is_manager): ~/.claude/sessions/*.json 중 sessionId 가 훅 입력 session_id 와 같은 파일을 전부 검사한다.
#   하나라도 실패하면 매니저 아님. 조건: name 이 정확히 «[Harness] Manager» · /proc/<pid> 존재 ·
#   procStart 가 /proc/<pid>/stat 의 22번째 필드(마지막 «)» 뒤 기준)와 같음. uid 조건은 구분력이 없어 두지 않는다.
#   *.key 는 읽지 않는다(*.json 글롭만, 일반 파일만). *.json 은 전부 jq 로 해석해 디코딩된 sessionId 로 비교하고(\u 이스케이프 우회 차단),
#   name·pid·procStart 비교도 jq 안에서 한다(제어문자로 필드 경계를 깨는 길 차단). 64KB 초과·읽기 불가·후보의 파싱 실패는 «판정 불가 → 매니저 아님».
#   실패 사유는 stderr 에 구분해 낸다(세션 파일 없음 / 이름 불일치 / pid 없음 / procStart 불일치).
#   보호 폴더(.git·_evolve·_usage·sessions·scope·_audit/publish-approval·projects)가 심볼릭이면 그 realpath 로 들어오는 경로도 같은 보호를 받는다.
#
# 알려진 한계 (설계에 수용, 문구 규율과 다른 훅이 보완):
#   (1) 세션 이름은 사용자가 정하므로 같은 이름의 다른 세션은 막지 못한다.
#   (2) Bash 로 sessions/*.json 을 위조하는 길은 Write·Edit 만 타는 이 훅이 못 막는다. bash-write-check.sh 의
#       리다이렉션·heredoc 차단이 유일한 방어다.
#   (3) 매니저 세션이 띄운 subagent 는 session_id 를 공유해 전원 통과한다. 외부 원문을 읽은 에이전트의 쓰기를 막는
#       untrusted-quarantine 은 훅이 아니라 문구 규율이다(이 훅은 구분 못 함).
#   (4) 훅이 예기치 않게 죽으면 기존 정책대로 exit 0(fail-open). fail-closed 인 곳: cwd 가 저장소 밖인 분기, 하네스 경로의
#       매니저 판정 실패(파일·pid·procStart·파싱 실패 포함), jq 가 없을 때의 하네스 경로(fall-through 집합 포함, exit 2),
#       scope 폴더가 있는데 훅 입력에 session_id 가 없는 경우(exit 2). jq 가 없을 때 하네스 밖 경로는 저장소 경계 검사를 못 하므로 통과한다(알려진 한계).
#   (5) Bash 경유 쓰기·git checkout/stash, 어느 저장소에도 속하지 않는 일반 파일은 경계 개념이 없어 통과(아래 프로젝트 경계 검사 주석).
#   (6) 매니저는 3)에서 바로 통과하므로 프로젝트 경계 검사와 scope 등록 검사를 건너뛴다.
#   (7) knowledge/ 등 허용 폴더 안의 하드링크, Bash 로 만든 심볼릭은 경로 문자열만 보는 이 훅이 못 막는다.
#   (8) 워크트리 통과(2026-11-21): 꼴을 직접 확인하므로 git 의 commondir 위조는 통하지 않는다. 판정할 수 없으면 전부 «다른 저장소» 로 막는다.
#       훅은 «학습이 도는 워크트리» 를 구분하지 못한다(고치지 않는 것은 규율).
#   (9) .git 폴더 안 경로(2026-11-21): 다른 저장소의 hooks·config·commondir 쓰기를 막기 위해 가장 앞의 .git 성분 앞을 소속 뿌리로 본다. 뿌리 폴더가 없으면 차단한다.
#   (10) 뿌리 찾기(2026-11-21): bare 저장소와 GIT_DIR 로 따로 둔 저장소는 뿌리로 인식하지 않는다(한계). 파일 시스템 경계에서 멈추지 않는다(git 과 다른 점).
#       cwd 쪽을 판정할 수 없으면(폴더를 못 열거나 표지가 없으면) 뿌리 없음 → «cwd 가 저장소 밖» 분기로 막는다.
#   (11) «cwd 가 저장소 밖» 분기는 허용 목록 아래여도 .git 안 경로 쓰기를 막는다(2026-11-21 보안 재검토: 저장소 표지를 만들어 이 분기를 건너뛰는 길 차단).
# REF: knowledge/harness/code-history/scripts__scope-gate.sh.md
set -u

INPUT="$(cat)"
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null)
SESSION=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[ -z "$CWD" ] && CWD=$(pwd)

# WHY: jq 가 없으면 위 값이 전부 비어 «경로 없음 → 통과» 로 조용히 열린다(2026-10-17 security). 하네스 경로만큼은 닫기 위해
# 필요한 세 값을 거칠게 직접 뽑는다(JSON 이스케이프는 풀지 않는다).
NOJQ=""
if ! command -v jq >/dev/null 2>&1; then
  NOJQ=1
  json_field() { [[ "$INPUT" =~ \"$1\"[[:space:]]*:[[:space:]]*\"([^\"]*)\" ]] && printf '%s' "${BASH_REMATCH[1]}"; }
  FILE=$(json_field file_path); [ -n "$FILE" ] || FILE=$(json_field path)
  SESSION=$(json_field session_id)
  CWD=$(json_field cwd); [ -z "$CWD" ] && CWD=$(pwd)
  # WHY: 정규식 추출은 백슬래시 u 와 숫자 넷으로 쓴 유니코드 이스케이프 같은 JSON 이스케이프를 못 푼다. 백슬래시가 든 경로·cwd 와, 키는 있는데 값을 못 뽑은 입력은 닫는다(2026-10-17 외부 검토).
  case "$FILE$CWD" in *\\*) echo "scope-gate: jq 없음 + 경로에 JSON 이스케이프(백슬래시)가 있어 판정할 수 없다(차단)." >&2; exit 2 ;; esac
  if [ -z "$FILE" ]; then
    case "$INPUT" in *file_path*|*'"path"'*) echo "scope-gate: jq 없음 + 입력에서 경로를 뽑지 못했다(차단)." >&2; exit 2 ;; esac
  fi
fi

[ -z "$FILE" ] && exit 0

# WHY: `~/` 로 시작하는 경로는 셸처럼 $HOME 으로 푼다(안 풀면 cwd 아래 «~» 폴더로 오인돼 하네스 판정을 비껴간다, 2026-10-17 security).
# shellcheck disable=SC2088  # 따옴표 친 '~/' 는 리터럴 접두 비교가 목적이다(전개하지 않는다)
case "$FILE" in '~/'*) FILE="$HOME/${FILE#\~/}" ;; esac

# WHY: `~/.claude/../outside`·심볼릭이 비정규 접두 매칭으로 scope를 우회하는 것 방지(2026-07-18 Codex).
# 상대 경로는 훅 프로세스의 cwd 가 아니라 입력 JSON 의 세션 cwd 로 푼다(2026-09-08 security 재현).
# 논리 표기(심볼릭 보존, `..` 만 해소)는 하네스 안 일부가 밖으로 걸린 심볼릭이어도 차단 목록·매니저 전용 판정을 대조하기 위해서다(2026-10-17 G1).
ORIG_FILE="$FILE"
case "$FILE" in
  /*) ;;
  *) FILE="$CWD/$FILE" ;;
esac
LOGICAL=$(realpath -m -s "$FILE" 2>/dev/null); [ -n "$LOGICAL" ] || LOGICAL="$FILE"
CANON=$(realpath -m "$FILE" 2>/dev/null) && [ -n "$CANON" ] && FILE="$CANON"

# WHY: $HOME/.claude 자체가 심링크인 서버에서는 FILE 만 물리 경로가 되어 심링크 문자열 접두와 불일치 → 하네스 예외가
# 무력화된다(2026-08-07). 비교 접두도 물리화해 양측을 맞춘다.
# REF: knowledge/harness/path-guard-symlink-bypass.md
HARNESS=$(cd "$HOME/.claude" 2>/dev/null && pwd -P) || HARNESS="$HOME/.claude"
HARNESS_RP=$(realpath -m "$HOME/.claude" 2>/dev/null) || HARNESS_RP="$HARNESS"

block_forgery() {
  if [ -n "$NOJQ" ]; then echo "$1 (jq 없음: 차단 JSON 대신 exit 2)" >&2; exit 2; fi
  printf '{"decision": "block", "reason": %s}\n' "$(printf '%s' "$1" | jq -R -s .)"
  exit 0
}

RELS=()
REL_PHYS=""
for F in "$FILE" "$LOGICAL"; do
  for B in "$HARNESS" "$HOME/.claude" "$HARNESS_RP"; do
    case "$F" in
      "$B"/?*)
        R="${F#"$B"/}"
        RELS+=("$R")
        [ "$F" = "$FILE" ] && REL_PHYS="$R"
        break ;;
    esac
  done
done

# WHY: 보호 폴더 자체가 심볼릭이면 그 realpath 로 직접 들어오는 경로도 같은 보호를 받도록 RELS 에 더한다(2026-10-17 외부 검토).
PROT=(.git _evolve _usage sessions scope _audit/publish-approval projects)
PROT_RP=()
while IFS= read -r PL; do PROT_RP+=("$PL"); done < <(realpath -m -- "${PROT[@]/#/$HOME/.claude/}" 2>/dev/null)
PI=0
for P in "${PROT[@]}"; do
  PR="${PROT_RP[$PI]:-}"; PI=$((PI + 1))
  [ -n "$PR" ] && [ "$PR" != "$HARNESS/$P" ] || continue
  for F in "$FILE" "$LOGICAL"; do
    case "$F" in "$PR"|"$PR"/*) RELS+=("$P${F#"$PR"}") ;; esac
  done
done

OWN_SCOPE_REL=""
case "$SESSION" in
  ''|.*|*[!A-Za-z0-9._-]*) ;;
  *) OWN_SCOPE_REL="scope/$SESSION.json" ;;
esac

is_always_block_rel() {
  case "$1" in
    .git|.git/*)
      BLOCK_MSG="scope-gate: 하네스 저장소 내부(.git/, 특히 hooks)는 Write·Edit 로 고칠 수 없다. 훅 설치는 scripts/setup-harness.sh 가 한다(2026-10-17 G1)."; return 0 ;;
    sessions|sessions/*)
      BLOCK_MSG="scope-gate: 세션 등록 파일(sessions/)은 Write·Edit 로 만들거나 고칠 수 없다(매니저 판정 위조 방지, 2026-10-17 G1)."; return 0 ;;
    _usage|_usage/*)
      BLOCK_MSG="scope-gate: 사용 장부·마커(_usage/)는 스크립트만 갱신한다. Write·Edit 로 고칠 수 없다(2026-10-17 G1)."; return 0 ;;
    _evolve/candidates.tsv|_evolve/candidates.lock|_evolve/crosscheck.tsv|_evolve/prompts.jsonl|_evolve/t41-ledger.jsonl|_evolve/t41-ledger.lock)
      BLOCK_MSG="scope-gate: 후보 대장·교차검증 판정표·프롬프트 기록·약점 대장(_evolve/)은 스크립트 전용이다. Write·Edit 로 고칠 수 없다(2026-10-17 G1, 약점 대장 2026-11-16)."; return 0 ;;
    _audit/publish-approval|_audit/publish-approval/*)
      BLOCK_MSG="scope-gate: Confluence 게시 승인 사용 장부(_audit/publish-approval/)는 Write·Edit 로 만들거나 고칠 수 없다(승인 위조 방지, 2026-10-07 security 검수)."; return 0 ;;
    scope|scope/*)
      [ -n "$OWN_SCOPE_REL" ] && [ "$1" = "$OWN_SCOPE_REL" ] && return 1
      BLOCK_MSG="scope-gate: scope/ 에서는 이 세션 자신의 파일(scope/<session_id>.json)만 쓸 수 있다. 다른 세션의 범위 등록은 고칠 수 없다(2026-10-17 G1)."; return 0 ;;
    projects/*)
      local prel="${1#projects/}"
      case "${prel#*/}" in memory/?*) [ "$prel" != "${prel#*/}" ] && return 1 ;; esac
      case "$prel" in
        *.jsonl) BLOCK_MSG="scope-gate: 세션 기록(projects/*/*.jsonl)은 Write·Edit 로 만들거나 고칠 수 없다(Confluence 게시 승인 증거 위조 방지, 2026-10-07 security 검수)."; return 0 ;;
      esac ;;
  esac
  return 1
}

# WHY: `case` 의 `*` 는 `/` 까지 삼키므로 projects/ 만 접두를 떼고 «첫 칸 뒤가 memory/» 인지로 한 단계만 허용한다(2026-09-08 security 재현).
is_allow_rel() {
  case "$1" in
    knowledge/?*|doc-formats/?*|_evolve/quiz/?*|.scratch/?*) return 0 ;;
    projects/*)
      local prel="${1#projects/}"
      [ "$prel" = "${prel#*/}" ] && return 1
      case "${prel#*/}" in memory/?*) return 0 ;; esac
      return 1 ;;
  esac
  [ -n "$OWN_SCOPE_REL" ] && [ "$1" = "$OWN_SCOPE_REL" ] && return 0
  return 1
}

is_fallthrough_rel() {
  case "$1" in
    jobs|jobs/*|teams|teams/*|daemon*|projects|projects/*|plans|plans/*) return 0 ;;
  esac
  return 1
}

is_manager() {
  MGR_WHY=""
  if [ -n "$NOJQ" ]; then MGR_WHY="jq 없음(매니저 판정 불가)"; return 1; fi
  if [ -z "$SESSION" ]; then MGR_WHY="세션 파일 없음(훅 입력에 session_id 가 없다)"; return 1; fi
  local sdir="$HOME/.claude/sessions" sf out pid pstart stat after matched=0
  local -a fields=()
  for sf in "$sdir"/*.json; do
    # WHY: FIFO·소켓 같은 특수 파일을 열면 훅이 멈춘다(2026-10-17 security). 일반 파일만 연다.
    [ -f "$sf" ] || continue
    [ -r "$sf" ] || { MGR_WHY="세션 파일 읽기 실패($sf)"; return 1; }
    [ "$(stat -c %s "$sf" 2>/dev/null || echo 999999)" -le 65536 ] || { MGR_WHY="세션 파일이 64KB 를 넘어 판정 불가($sf)"; return 1; }
    # WHY: 원문 부분 문자열로 거르지 않고 *.json 전부를 jq 로 해석해 «디코딩된» sessionId 로 비교한다(\u 이스케이프 우회 차단, 2026-10-17 외부 검토).
    # 값 비교도 jq 안에서 한다: name 의 제어문자·개행이 필드 경계를 깨 통과하는 길을 없앤다.
    out=$(jq -r --arg sid "$SESSION" 'if type != "object" or .sessionId != $sid then "skip"
      elif .name != "[Harness] Manager" then "name"
      elif (.pid | type) != "number" or (.pid | floor) != .pid or .pid < 1 then "pid"
      elif ((.procStart | tostring) | test("\\A[0-9]+\\z")) | not then "pstart"
      else "ok\t\(.pid)\t\(.procStart | tostring)" end' "$sf" 2>/dev/null) || {
      if grep -qF -- "$SESSION" "$sf" 2>/dev/null; then MGR_WHY="세션 파일 JSON 파싱 실패($sf)"; return 1; fi
      continue
    }
    [ "$out" = "skip" ] && continue
    matched=1
    if [ "$out" = "name" ]; then MGR_WHY="이름 불일치(세션 이름이 «[Harness] Manager» 가 아니다)"; return 1; fi
    if [ "$out" = "pid" ] || [ "$out" = "pstart" ]; then MGR_WHY="pid 없음(세션 파일의 pid·procStart 가 숫자가 아니다)"; return 1; fi
    IFS=$'\t' read -r _ pid pstart <<< "$out"
    case "$pid" in ''|*[!0-9]*) MGR_WHY="pid 없음(세션 파일에 pid 가 없거나 숫자가 아니다)"; return 1 ;; esac
    case "$pstart" in ''|*[!0-9]*) MGR_WHY="procStart 불일치(숫자가 아니다)"; return 1 ;; esac
    if [ ! -d "/proc/$pid" ]; then MGR_WHY="pid 없음(/proc/$pid 가 없다. 종료된 세션)"; return 1; fi
    stat=$(cat "/proc/$pid/stat" 2>/dev/null) || { MGR_WHY="pid 없음(/proc/$pid/stat 를 읽지 못했다)"; return 1; }
    after="${stat##*) }"   # WHY: comm 은 공백·괄호를 품을 수 있어 마지막 «) » 뒤부터 센다. 22번째 필드 = 이 뒤 20번째(색인 19)
    read -r -a fields <<< "$after"
    if [ -z "$pstart" ] || [ "${fields[19]:-}" != "$pstart" ]; then MGR_WHY="procStart 불일치(pid 가 재사용됐거나 세션 파일이 낡았다)"; return 1; fi
  done
  if [ "$matched" -ne 1 ]; then MGR_WHY="세션 파일 없음(sessions/ 에 session_id 가 같은 파일이 없다)"; return 1; fi
  return 0
}

IN_HARNESS=""
if [ "${#RELS[@]}" -gt 0 ]; then
  for R in "${RELS[@]}"; do
    if is_always_block_rel "$R"; then block_forgery "$BLOCK_MSG"; fi
  done

  if [ -n "$REL_PHYS" ]; then
    ALL_ALLOWED=1
    for R in "${RELS[@]}"; do is_allow_rel "$R" || ALL_ALLOWED=0; done
    [ "$ALL_ALLOWED" -eq 1 ] && exit 0
  fi

  CORE_REL=""
  for R in "${RELS[@]}"; do is_fallthrough_rel "$R" || CORE_REL="$R"; done
  if [ -n "$CORE_REL" ]; then
    is_manager && exit 0
    echo "scope-gate: 하네스 경로($CORE_REL)는 기본값이 매니저 전용이라 [Harness] Manager 세션만 고친다. 판정: $MGR_WHY. 필요한 변경을 보고에 적어 사용자에게 알리십시오(2026-10-17 G1)." >&2
    exit 2
  fi
  IN_HARNESS=1
fi
if [ -n "$NOJQ" ]; then
  if [ -n "$IN_HARNESS" ]; then
    echo "scope-gate: jq 없음 — 하네스 경로(${RELS[0]}) 경계 판정 불가, 차단" >&2
    exit 2
  fi
  exit 0
fi

# REF: rules/code-execution.md § 프로젝트 경계
find_repo_root() {
  local p line
  p=$(cd -- "$1" 2>/dev/null && pwd -P) || return 1
  [ -n "$p" ] || return 1
  while :; do
    if [ -d "$p/.git" ]; then
      if [ -f "$p/.git/HEAD" ] && [ -d "$p/.git/objects" ] && [ -d "$p/.git/refs" ]; then printf '%s\n' "$p"; return 0; fi
    elif [ -f "$p/.git" ]; then
      line=""
      IFS= read -r line 2>/dev/null < "$p/.git" || [ -n "$line" ] || true
      case "$line" in 'gitdir: '?*) printf '%s\n' "$p"; return 0 ;; esac
    fi
    [ "$p" = "/" ] && return 1
    p=$(dirname -- "$p")
  done
}
CWD_ROOT=$(find_repo_root "$CWD")
DIR=$(dirname "$FILE")
while [ ! -d "$DIR" ] && [ "$DIR" != "/" ]; do DIR=$(dirname "$DIR"); done

if [ -z "$CWD_ROOT" ]; then
  # WHY: 허용 목록 아래에서 D/.git(파일 한 줄 또는 HEAD·objects·refs 폴더)을 쓰면 다음 호출부터 D 가 뿌리로 잡혀
  # 이 분기를 건너뛰고, 어느 저장소에도 속하지 않는 경로(허용 목록 밖)가 통과해 버린다(2026-11-21 보안 재검토).
  case "$FILE" in
    */.git/*|*/.git)
      REASON="프로젝트 경계: 세션 cwd 가 git 저장소 밖이라 \`.git\` 안 경로($FILE)에는 쓸 수 없다(허용 목록 아래여도 같다). 저장소 표지를 만들면 쓰기 범위 판정이 바뀐다(rules/code-execution.md § 프로젝트 경계)"
      printf '{"decision": "block", "reason": %s}\n' "$(printf '%s' "$REASON" | jq -R -s .)"
      exit 0 ;;
  esac
  # WHY: cwd 가 git 저장소 밖인 세션은 «쓰기 범위가 정의되지 않은 세션» 이라 이 분기는 fail-closed 다(2026-09-08 사용자 결정).
  ALLOW_FILE="${SCOPE_ALLOW_FILE:-$HOME/.claude/config/scope-allow.txt}"
  ALLOW_LOCAL_FILE="${SCOPE_ALLOW_LOCAL_FILE:-$HOME/.claude/config/scope-allow.local.txt}"
  REAL=$(cd "$DIR" 2>/dev/null && pwd -P) || REAL="$DIR"
  ALLOWED=0
  for AF in "$ALLOW_FILE" "$ALLOW_LOCAL_FILE"; do
    [ "$ALLOWED" -eq 1 ] && break
    [ -f "$AF" ] || continue
    while IFS= read -r LINE || [ -n "$LINE" ]; do
      case "$LINE" in ''|'#'*) continue ;; esac
      ALLOW="${LINE%"${LINE##*[![:space:]]}"}"
      case "$ALLOW" in '~'*) ALLOW="$HOME${ALLOW#\~}" ;; esac
      ALLOW="${ALLOW%/}"
      [ -z "$ALLOW" ] && continue
      case "$REAL" in "$ALLOW"|"$ALLOW"/*) ALLOWED=1; break ;; esac
    done < "$AF"
  done
  if [ "$ALLOWED" -ne 1 ]; then
    REASON="프로젝트 경계: 세션 cwd 가 git 저장소 밖이라 쓰기 범위가 없다. 허용할 경로를 사용자가 \`config/scope-allow.txt\`(모든 서버 공통) 또는 \`config/scope-allow.local.txt\`(이 서버 전용, gitignore)에 적어야 한다(rules/code-execution.md § 프로젝트 경계)"
    printf '{"decision": "block", "reason": %s}\n' "$(printf '%s' "$REASON" | jq -R -s .)"
    exit 0
  fi
fi

# WHY: 같은 저장소인지는 git 명령이 아니라 꼴을 직접 확인해 판정한다. git 은 git 폴더 안의 commondir 파일을 읽어 공용 폴더를 정하는데,
# 그 파일은 Write 로 쓸 수 있어 위조된다(2026-11-21 보안 검토).
main_git_dir() {
  local root line g gd wt
  root=$(cd -- "$1" 2>/dev/null && pwd -P) || return 1
  [ -n "$root" ] || return 1
  if [ -d "$root/.git" ]; then
    (cd -- "$root/.git" 2>/dev/null && pwd -P)
    return
  fi
  [ -f "$root/.git" ] && [ ! -L "$root/.git" ] || return 1
  line=""
  IFS= read -r line < "$root/.git" || [ -n "$line" ] || return 1
  case "$line" in 'gitdir: '?*) g="${line#gitdir: }" ;; *) return 1 ;; esac
  case "$g" in /*) ;; *) g="$root/$g" ;; esac
  gd=$(cd -- "$g" 2>/dev/null && pwd -P) || return 1
  [ "$(basename -- "$(dirname -- "$gd")")" = "worktrees" ] || return 1
  [ -f "$gd/gitdir" ] || return 1
  line=""
  IFS= read -r line < "$gd/gitdir" || [ -n "$line" ] || return 1
  case "$line" in /*) ;; *) line="$gd/$line" ;; esac
  [ "$(basename -- "$line")" = ".git" ] || return 1
  wt=$(cd -- "$(dirname -- "$line")" 2>/dev/null && pwd -P) || return 1
  [ "$wt" = "$root" ] || return 1
  (cd -- "$(dirname -- "$(dirname -- "$gd")")" 2>/dev/null && pwd -P)
}
same_repo_worktree() {
  local a b
  a=$(main_git_dir "$1") || return 1
  b=$(main_git_dir "$2") || return 1
  [ -n "$a" ] && [ "$a" = "$b" ]
}

if [ -n "$CWD_ROOT" ]; then
  FILE_ROOT=$(find_repo_root "$DIR")
  # WHY: .git 폴더 안 경로는 가장 앞의 .git 성분 앞까지를 소속 뿌리로 삼는다. 다른 저장소의 .git/hooks·config·commondir 쓰기,
  # 껍데기 .git 을 채워 저장소로 만들기를 막는다(2026-11-21 보안 검토).
  case "$FILE" in
    */.git/*|*/.git)
      GIT_ROOT_RAW="${FILE%%/.git/*}"; GIT_ROOT_RAW="${GIT_ROOT_RAW%/.git}"
      FILE_ROOT=$(cd -- "${GIT_ROOT_RAW:-/}" 2>/dev/null && pwd -P) || {
        REASON="프로젝트 경계: .git 폴더 안 경로($FILE)의 소속 저장소 뿌리를 열 수 없어 판정할 수 없다(차단). 다른 저장소의 .git 안은 쓸 수 없다(rules/code-execution.md § 프로젝트 경계)."
        printf '{"decision": "block", "reason": %s}\n' "$(printf '%s' "$REASON" | jq -R -s .)"
        exit 0
      } ;;
  esac
  if [ -n "$FILE_ROOT" ]; then
    CWD_ROOT=$(cd "$CWD_ROOT" 2>/dev/null && pwd -P)
    FILE_ROOT=$(cd "$FILE_ROOT" 2>/dev/null && pwd -P)
    case "$FILE_ROOT" in
      "$CWD_ROOT"|"$CWD_ROOT"/*) ;;
      *)
        if ! same_repo_worktree "$CWD_ROOT" "$FILE_ROOT"; then
          REASON="프로젝트 경계: $FILE_ROOT 는 현재 세션 저장소($CWD_ROOT) 밖의 다른 저장소다. 다른 저장소는 읽기만 허용한다(rules/code-execution.md § 프로젝트 경계). 그 프로젝트를 cwd 로 열어 지시할 때 수정한다."
          printf '{"decision": "block", "reason": %s}\n' "$(printf '%s' "$REASON" | jq -R -s .)"
          exit 0
        fi ;;
    esac
  fi
fi

# WHY: 세션별 scope 파일 우선. 과거의 전역 최신 파일 사용 → 병렬 세션 간 교차 오작동(2026-07-06 Codex 교차검증 F11).
# REF: rules-lazy/scope-gate.md
SCOPE_DIR="$HOME/.claude/scope"
[ ! -d "$SCOPE_DIR" ] && exit 0

if [ -n "$SESSION" ]; then
  LATEST="$SCOPE_DIR/$SESSION.json"
  [ ! -f "$LATEST" ] && exit 0
else
  # WHY: «최신 scope 파일» 로 폴백하면 다른 세션이 등록한 범위를 이 세션이 타고 통과·차단 판정을 받는다(2026-10-17 Grok 반례).
  echo "scope-gate: 훅 입력에 session_id 가 없어 scope 파일을 고를 수 없다(차단). 다른 세션의 등록 범위로 판정하지 않는다." >&2
  exit 2
fi

IN_SCOPE=$(jq -r --arg f "$FILE" --arg g "$ORIG_FILE" '.scope[] | select(.path == $f or .path == $g) | .path' "$LATEST" 2>/dev/null)
if [ -z "$IN_SCOPE" ]; then
  REASON="scope-gate: $FILE is not in the registered scope ($LATEST). 사전 합의된 범위 외 파일 수정·삭제는 사용자 승인이 필요합니다."
  printf '{"decision": "block", "reason": %s}\n' "$(printf '%s' "$REASON" | jq -R -s .)"
fi

exit 0
