#!/usr/bin/env bash
# spawn-tree.sh — Write/Edit 보유 spawn(researcher·qa·docs·tutor)의 쓰기 경계 검사 정본 (paper-read Step 4 / Phase 1.5 / Write 보유 spawn 공통)
#
# 왜 스크립트인가 (2026-08-25 12라운드): Step 4 산문의 트리 생성 명령(`%p\t%s`)과 ⓑ 접두 해시 요구가 어긋났고(Grok),
#   history.md 형식 화이트리스트(`^## \[20`)가 실제 파일(`## 2026-…`·`### 2026-…`)과 달라 실사용 0건 = 정상 감사 기록을 FAIL 로 오판할 상태였으며(렌즈1),
#   ⓒ 형식 검사만으로는 Edit 도구로 얹은 형식 적합 위조 줄을 못 가른다(렌즈2). 세 가지를 한 곳에서 집행하고 산문은 이 파일을 가리키기만 한다.
#
# 면제 범위(2026-10-01 감사): 런타임 면제(RUNTIME_EXEMPT)는 하네스 홈 고정 접두 아래만이다. 임의 깊이의 같은 이름 폴더는 면제되지 않는다(RUNTIME_EXEMPT 정의 위 주석).
#
# 사용:
#   snapshot <tree파일> <root>...
#       main 이 spawn 직전 실행. root 전체를 `path \t size \t prefix_sha` 로 저장(append-only 기대 파일만 `head -c size | sha256sum`, 나머지 `-`).
#       tree 파일 자신이 마커(ctime 기준) — 별도 .spawn-marker 불필요. 출력의 inode·ctime 을 qa spawn prompt 에 실어 보낸다.
#       tree 파일은 spawn 의 허용 경로 **밖**에 두고 spawn 마다 새 이름(`.spawn-tree-{논문명}`) — 이미 있으면 거부.
#   check <tree파일> [--allow <절대경로접두>]... [--main-only <절대경로>]... [--allow-mcp <mcp__접두>]...
#       spawn 종료 직후 검사자가 실행(주체 규칙은 아래). 절대 경로 접두만 받는다(`*/notes/*` 같은 접미 광역 금지). ④ 는 subagent 의 `mcp__*` 호출 중 `--allow-mcp` 접두에
#       맞지 않는 것을 FAIL 로 본다 — 15라운드 Grok: 전면 스위치는 qa·tutor 의 내부 기억(mem0)과 docs 의 외부 발신(Confluence)을 한 스위치로 묶었다. 예: `--allow-mcp mcp__mem0__`.
#       주체 규칙: 검사자 ≠ 피검사자 — researcher 창은 qa 가, qa·docs·tutor 창은 main 이 실행한다(15라운드 렌즈3).
#       ④ 는 창 안의 **모든** subagent transcript 를 본다(검사자 자신 포함) — 검사자 qa 는 check 를 마치기 전에 어떤 MCP 도구도 호출하지 않는다(T05 검색은 check 뒤, 16라운드 Grok).
#       `--allow-mcp` 접두는 서버 단위 `mcp__<서버>__` 만 받는다(`mcp__` 단독 거부).
#       ① 사라진 파일(드롭퍼 자기삭제) — 심볼릭 링크도 파일로 센다(`-type l`, 14라운드 Grok 낮음: 링크 신설로 스캔을 비켜가던 경로)
#       ② append-only 기대 파일: 크기 감소 / 마커 시점 접두 해시 불일치 / 추가 줄이 아래 형식 표 밖
#       ③ tree 보다 ctime 이 새로운 파일 중 허용 접두 밖(gitignored·`.git/` 포함. 제외는 **이번 tree 파일 자신(정확 경로)**·`_usage/*-last`·`.git/index` 뿐 —
#          13라운드 Grok: 이름 glob `.spawn-tree-*` 제외는 드롭퍼가 그 이름으로 파일을 만들면 ①③ 에서 사라지게 했다. 다른 spawn 의 tree 가 같은 창에 있으면 `--allow` 로 그 경로를 준다)
#          여기에 `jobs/*/tmp/*` 하나를 더 뺀다 — 하네스가 지정한 에이전트 스크래치이며 2026-08-30 실측으로 전체 143,262 개 중 118,604 개(45GB)가 이 아래였다.
#          그대로 두면 snapshot 이 2분을 넘고 트리 파일이 20MB 라 도구가 통째로 건너뛰어진다. 대가(정직 표기): 스크래치에 숨긴 파일은 ①③ 이 못 본다.
#          숨긴 파일은 실행돼야 해를 끼치고 그 실행 경로는 bash-write-check 가 막는다는 전제로 감수했다.
#       `--allow` 접두 매칭: 접두가 `/` 로 끝나면 디렉터리 접두, 아니면 그 경로와 정확히 같거나 그 아래(`…/review.md` 가 `review.mdx` 를 허용하지 않도록 — 13라운드 Grok 낮음).
#       ④ 의 timestamp 비교는 transcript 의 `Z`(UTC) ISO 문자열과 tree ctime 을 UTC 로 바꾼 문자열의 사전순 비교 — Claude Code transcript 는 항상 `Z` 표기(오프셋 표기가 섞이면 초 단위가 어긋날 수 있음, 알려진 한계).
#       ④ tree 이후 갱신된 subagent transcript(`projects/*/*/subagents/*.jsonl`) 안, tree ctime 이후 timestamp 의 Write/Edit/MultiEdit/NotebookEdit tool_use 중
#          file_path 가 `--allow` 접두 밖 — 형식 적합 위조 줄·같은 크기 덮어쓰기도 도구 호출 자체가 증거로 남아 잡힌다. 같은 창의 `mcp__*` tool_use 는 격리 spawn 의 외부 발신이라 FAIL.
#          `--main-only` 경로는 ③ 에서는 허용(main 이 라운드 사이에 append — tutor 의 quiz-search.log)하되 ④ 에서는 subagent 가 건드리면 FAIL.
#       출력: `FAIL …` 줄들 + 마지막 줄 `RESULT: PASS` 또는 `RESULT: FAIL n`. exit 0=PASS, 1=FAIL, 2=사용 오류. qa 는 이 출력 원문을 보고에 인용한다(자기선언 무효).
#
# append-only 기대 파일과 줄 형식 (정본 — 룰·스킬 산문은 이 표를 복제하지 않는다. 실제 파일 형식 실측 기준):
#   */_audit/agent-spawn.log        ^[^\t]+\t(pre|post)\t
#   */_audit/approved-commands.log  ^[^\t]+\t[0-9a-f]{64}\t[0-9]+\t
#   */_audit/history.md             ^(#{2,3} 20YY-MM-DD 헤더 | "- " | "  " | "|" | "**" | "T41: " | "> " | 빈 줄)
#   */_evolve/crosscheck.tsv        ^[^\t]+\t[^\t]+\t[0-9]+\t[0-9]+\t
#   */projects/**/*.jsonl           ^\{.*"type":
# 한계(정직 표기): 형식·해시·transcript 는 모두 "쓰기 흔적" 검사다. subagent 의 Bash 경유 쓰기는 bash-write-check 훅이 막고, 훅이 놓친 경로는 ③ 이 잡되
#   같은 크기 덮어쓰기는 ctime 으로만 보인다(내용 비교 없음). ④ 는 Write/Edit/MultiEdit/NotebookEdit tool_use 만 본다 — Bash tool_use 로 파일을 쓰는 경로(훅 우회 시)는
#   ③ 의 ctime·허용 접두로만 잡힌다(13라운드 렌즈2). SPAWN_TREE_HOME 은 자체 테스트용 오버라이드 — 실운용 spawn prompt 에 env 를 넣지 않는다.
set -uf
export LC_ALL=C
# 심볼릭 링크 root 는 반드시 풀어서 쓴다 (2026-08-30 실사고): `~/.claude` 는 `~/workspace/.claude`
# 링크라 `find ~/.claude -type f` 가 링크 자신 1건만 반환하고 트리로 내려가지 않는다. 그대로 두면
# snapshot 이 "1 files" 로 만들어지고 check 가 사실상 아무것도 안 보면서 RESULT: PASS 를 낸다.
# 같은 날 온톨로지 파이프라인에서 확인된 것과 같은 계열의 결함이다.
resolve_root() { readlink -f -- "$1" 2>/dev/null || printf '%s' "$1"; }
HOMEC=$(resolve_root "${SPAWN_TREE_HOME:-$HOME/.claude}")
MODE="${1:-}"; [ $# -gt 0 ] && shift
TREE="${1:-}"; [ $# -gt 0 ] && shift
# TREE 도 절대 경로로 고정한다 — 상대 경로로 받으면 find 출력(절대)과 형태가 달라 자기 제외가 걸리지 않는다
[ -n "$TREE" ] && TREE=$(resolve_root "$TREE")
usage() { echo "usage: spawn-tree.sh snapshot <tree> <root>... | check <tree> [--allow <abs-prefix>]... [--main-only <abs-path>]... [--allow-mcp <mcp__prefix>]..."; exit 2; }
[ -n "$MODE" ] && [ -n "$TREE" ] || usage

ao_kind() {  # append-only 기대 파일 분류 — 빈 문자열이면 일반 파일
    case "$1" in
        */_audit/agent-spawn.log) echo spawnlog ;;
        */_audit/approved-commands.log) echo approved ;;
        */_audit/history.md) echo history ;;
        */_evolve/crosscheck.tsv) echo crosscheck ;;
        */projects/*.jsonl) echo transcript ;;
        *) echo "" ;;
    esac
}
line_ok() {  # $1 kind, $2 line
    case "$1" in
        spawnlog)   printf '%s\n' "$2" | grep -qE $'^[^\t]+\t(pre|post)\t' ;;
        approved)   printf '%s\n' "$2" | grep -qE $'^[^\t]+\t[0-9a-f]{64}\t[0-9]+\t' ;;
        history)    printf '%s\n' "$2" | grep -qE '^(#{2,3} 20[0-9]{2}-[0-9]{2}-[0-9]{2}|- |  |\||\*\*|T41: |> |$)' ;;
        crosscheck) printf '%s\n' "$2" | grep -qE $'^[^\t]+\t[^\t]+\t[0-9]+\t[0-9]+\t' ;;
        transcript) printf '%s\n' "$2" | grep -qE '^\{.*"type":' ;;
        *) return 0 ;;
    esac
}
prefix_sha() { head -c "$2" -- "$1" 2>/dev/null | sha256sum | cut -c1-64; }
# 런타임이 창 안에서 스스로 쓰는 경로 (2026-08-30 실측으로 확정 — 첫 실사용에서 16건이 전부 이것이었다).
# 검사 대상 spawn 이 만지는 파일이 아니라 하네스·git·에이전트 런타임이 항상 건드리는 것들이라 남겨 두면
# 정상 쓰기가 FAIL 로 잡히고, 그러면 스캔 자체를 무시하게 된다(8라운드 Grok 이 지적한 실패 모드).
# `.git` 은 통째로 빼지 않는다 — `hooks/`·`config` 는 지속형 백도어 자리라 계속 본다(6라운드 렌즈2). 내용 주소 저장소와 ref 만 뺀다.
# 2026-10-01 감사: 면제는 «하네스 홈($HOMEC) 고정 접두»다. 맨 앞 `*/` 로 쓰면 어느 깊이에든 그 이름의 폴더만 만들면
# 거기 아래 쓰기가 ①③ 에서 빠졌다(위 «이름 glob 금지» 원칙과 반대였다).
RUNTIME_EXEMPT=(
    -not -path "$HOMEC/_usage/*-last"
    -not -path "$HOMEC/.git/index" -not -path "$HOMEC/.git/objects/*" -not -path "$HOMEC/.git/refs/*"
    -not -path "$HOMEC/.git/logs/*" -not -path "$HOMEC/.git/COMMIT_EDITMSG" -not -path "$HOMEC/.git/ORIG_HEAD"
    -not -path "$HOMEC/jobs/*/tmp/*" -not -path "$HOMEC/jobs/*/state.json" -not -path "$HOMEC/jobs/*/timeline.jsonl"
    -not -path "$HOMEC/_cache/read-once/*"
    -not -path "$HOMEC/projects/*/*.meta.json" -not -path "$HOMEC/projects/*/*/subagents/*.meta.json"
    -not -path "$HOMEC/teams/*"
    -not -path "$HOMEC/tools/mem-guard/mem-watch.log" -not -path "$HOMEC/tools/mem-guard/mem-watch.state"
)
list_files() {  # $@ roots → `path \t size` (정렬). 제외는 이번 tree 파일 자신(정확 경로)과 위 런타임 목록뿐 — 이름 glob 제외 금지(13라운드 Grok)
    find "$@" \( -type f -o -type l \) -not -path "$TREE" "${RUNTIME_EXEMPT[@]}" -printf '%p\t%s\n' 2>/dev/null | sort
}

if [ "$MODE" = snapshot ]; then
    [ $# -ge 1 ] || { echo "snapshot: root 1개 이상 필요"; usage; }
    [ -e "$TREE" ] && { echo "이미 존재: $TREE — spawn 마다 새 이름을 쓴다"; exit 2; }
    # root 는 링크를 푼 형태로 고정해 헤더에 적는다 — check 가 같은 형태로 다시 걷도록(위 resolve_root 주석)
    ROOTS_R=()
    for r in "$@"; do
        [ -d "$r" ] || { echo "root 아님: $r"; exit 2; }
        ROOTS_R+=("$(resolve_root "$r")")
    done
    set -- "${ROOTS_R[@]}"
    {
        printf '# roots:'; for r in "$@"; do printf '\t%s' "$r"; done; printf '\n'
        list_files "$@" | while IFS=$'\t' read -r p s; do
            k=$(ao_kind "$p")
            if [ -n "$k" ]; then printf '%s\t%s\t%s\n' "$p" "$s" "$(prefix_sha "$p" "$s")"; else printf '%s\t%s\t-\n' "$p" "$s"; fi
        done
    } > "$TREE"
    N=$(($(wc -l < "$TREE") - 1))
    echo "snapshot: ${N} files → $TREE  (마커=이 파일: $(stat -c 'inode=%i ctime=%Z' "$TREE"))"
    sleep 1   # ctime 은 정수 초 — 같은 초 안의 쓰기가 "더 새롭지 않다"로 판정되는 경합을 닫는다(15라운드 렌즈2 낮음)
    exit 0
fi

[ "$MODE" = check ] || usage
[ -s "$TREE" ] || { echo "tree 없음/비어 있음: $TREE"; exit 2; }
ALLOW=(); MAINONLY=(); ALLOW_MCP=()
# 허용 접두도 root 와 같은 형태(링크 푼 절대 경로)로 맞춘다 — 형태가 다르면 정상 쓰기가 "허용 밖"으로 잡힌다.
# 끝의 `/`는 디렉터리 접두를 뜻하므로 resolve 뒤에 되붙인다(under 의 판정 규칙).
norm_prefix() {
    local p="$1" tail="" r
    case "$p" in */) tail="/" ;; esac
    r=$(readlink -f -- "$p" 2>/dev/null) || r=""
    [ -n "$r" ] || r="${p%/}"
    printf '%s%s' "$r" "$tail"
}
while [ $# -gt 0 ]; do
    case "$1" in
        --allow)     [ $# -ge 2 ] || usage; case "$2" in /*) ALLOW+=("$(norm_prefix "$2")") ;; *) echo "--allow 는 절대 경로 접두만: $2"; exit 2 ;; esac; shift 2 ;;
        --main-only) [ $# -ge 2 ] || usage; case "$2" in /*) MAINONLY+=("$(norm_prefix "$2")") ;; *) echo "--main-only 는 절대 경로만: $2"; exit 2 ;; esac; shift 2 ;;
        --allow-mcp) [ $# -ge 2 ] || usage
                     # 서버 단위 접두(`mcp__<서버>__`)만 — `mcp__` 단독은 전면 스위치로 되돌아가므로 거부 (16라운드 Grok)
                     if [[ "$2" =~ ^mcp__[A-Za-z0-9_-]+__$ ]]; then ALLOW_MCP+=("$2"); else echo "--allow-mcp 는 서버 접두 mcp__<서버>__ 형식만(예: mcp__mem0__): $2"; exit 2; fi; shift 2 ;;
        *) echo "알 수 없는 인자: $1"; usage ;;
    esac
done
mcp_allowed() { local n="$1" a; for a in ${ALLOW_MCP[@]+"${ALLOW_MCP[@]}"}; do case "$n" in "$a"*) return 0 ;; esac; done; return 1; }
IFS=$'\t' read -r -a HDR < "$TREE"
[ "${HDR[0]}" = "# roots:" ] && [ ${#HDR[@]} -ge 2 ] || { echo "tree 헤더 손상(# roots: 없음): $TREE"; exit 2; }
ROOTS=("${HDR[@]:1}")
FAIL=0
fail() { echo "FAIL $*"; FAIL=$((FAIL + 1)); }
under() {  # $1 path, $2 접두: `/` 로 끝나면 디렉터리 접두, 아니면 정확 일치 또는 그 아래
    case "$2" in
        */) case "$1" in "$2"*) return 0 ;; esac ;;
        *)  [ "$1" = "$2" ] && return 0; case "$1" in "$2"/*) return 0 ;; esac ;;
    esac
    return 1
}
allowed_file() { local p="$1" a; for a in ${ALLOW[@]+"${ALLOW[@]}"} ${MAINONLY[@]+"${MAINONLY[@]}"}; do under "$p" "$a" && return 0; done; return 1; }
allowed_sub()  { local p="$1" a; for a in ${ALLOW[@]+"${ALLOW[@]}"}; do under "$p" "$a" && return 0; done; return 1; }

NOW=$(mktemp); OLDP=$(mktemp); NEWP=$(mktemp)
trap 'rm -f "$NOW" "$OLDP" "$NEWP"' EXIT
list_files "${ROOTS[@]}" > "$NOW"
tail -n +2 "$TREE" | cut -f1 | sort > "$OLDP"
cut -f1 "$NOW" | sort > "$NEWP"

# ① 사라진 파일
while IFS= read -r p; do [ -n "$p" ] && fail "사라진 파일: $p"; done < <(comm -23 "$OLDP" "$NEWP")

# ② append-only 기대 파일: 크기·접두 해시·추가 줄 형식
while IFS=$'\t' read -r p s h; do
    [ "$h" = - ] && continue
    [ -f "$p" ] || continue
    ns=$(stat -c %s -- "$p")
    if [ "$ns" -lt "$s" ]; then fail "append-only 크기 감소: $p ${s}→${ns}"; continue; fi
    nh=$(prefix_sha "$p" "$s")
    [ "$nh" = "$h" ] || fail "append-only 접두 변경: $p (마커 시점 ${s}B 의 sha256 불일치 — 기존 줄이 바뀌었거나 재작성됨)"
    if [ "$ns" -gt "$s" ]; then
        k=$(ao_kind "$p"); n=0; skip=0
        # 접두 마지막 바이트가 개행이 아니면 추가분 첫 조각은 기존 줄의 꼬리 — 형식 판정에서 제외
        [ "$s" -gt 0 ] && [ "$(head -c "$s" -- "$p" | tail -c 1 | od -An -tx1 | tr -d ' \n')" != "0a" ] && skip=1
        while IFS= read -r line; do
            if [ "$skip" -eq 1 ]; then skip=0; continue; fi
            line_ok "$k" "$line" || { n=$((n + 1)); [ "$n" -le 3 ] && fail "append-only 형식 밖 줄: $p: ${line:0:100}"; }
        done < <(tail -c +$((s + 1)) -- "$p")
        [ "$n" -gt 3 ] && echo "  (형식 밖 줄 ${n}건 중 3건만 표시)"
    fi
done < <(tail -n +2 "$TREE")

# ③ 마커 이후 ctime 변경 파일 중 허용 밖 (append-only 파일은 ② 에서 판정, tree 에 없던 새 append-only 파일은 전체 줄 형식 검사)
while IFS= read -r p; do
    [ -n "$p" ] || continue
    k=$(ao_kind "$p")
    if [ -n "$k" ]; then
        if ! grep -qxF -- "$p" "$OLDP"; then
            # 신규 append-only 형식 파일: 형식 검사는 **추가** 조건이지 허용 접두의 대체가 아니다 (13라운드 렌즈2: 형식만 맞춘 `…/z/_audit/history.md` 신설이 통과했다).
            # 예외는 런타임이 스스로 만드는 transcript 의 **실제 깊이**만 — `projects/<proj>/<session>.jsonl`·`projects/<proj>/<session>/subagents/<agent>.jsonl`
            # (14라운드 렌즈2: case 의 `*` 는 `/` 를 넘어가 임의 깊이의 위조 .jsonl 도 면제됐다). 예외 파일도 INFO 로 남겨 창 안 신설을 보이게 한다.
            if [[ "$p" =~ ^"$HOMEC"/projects/[^/]+/[^/]+\.jsonl$ || "$p" =~ ^"$HOMEC"/projects/[^/]+/[^/]+/subagents/[^/]+\.jsonl$ ]]; then
                echo "INFO 런타임 transcript 신설(형식 검사만): $p"
            else
                allowed_file "$p" || fail "허용 밖 신규 append-only 형식 파일: $p"
            fi
            n=0
            while IFS= read -r line; do line_ok "$k" "$line" || { n=$((n + 1)); [ "$n" -le 3 ] && fail "신규 append-only 파일 형식 밖 줄: $p: ${line:0:100}"; }; done < "$p"
        fi
        continue
    fi
    allowed_file "$p" || fail "허용 밖 변경(ctime>마커): $p"
done < <(find "${ROOTS[@]}" \( -type f -o -type l \) -cnewer "$TREE" -not -path "$TREE" "${RUNTIME_EXEMPT[@]}" 2>/dev/null | sort -u)

# ④ subagent transcript 의 Write/Edit tool_use 경로 + MCP 호출 (tree ctime 이후 timestamp 만)
#    MCP: 이 검사가 쓰이는 spawn(paper-read researcher·qa·docs·tutor)은 `rules-lazy/untrusted-quarantine.md` §4 로 외부 발신·MCP 가 금지된 격리 spawn 이다.
#    도구 권한을 spawn 단위로 뗄 수 없으므로 transcript 의 `mcp__*` tool_use 를 FAIL 로 잡는다(14라운드 렌즈2: 파일시스템 감사만으로는 Confluence 생성 같은 발신을 못 봤다). `--allow-mcp` 로만 해제.
if command -v jq >/dev/null 2>&1; then
    D=$(date -u -d "@$(stat -c %Z -- "$TREE")" +%Y-%m-%dT%H:%M:%S)
    while IFS= read -r t; do
        [ -n "$t" ] || continue
        while IFS= read -r fp; do
            [ -n "$fp" ] || continue
            # transcript 의 경로도 허용 접두와 같은 형태로 푼다 — 링크 낀 표기 차이로 정상 쓰기가 FAIL 되던 것을 막는다(2026-08-30)
            fp_r=$(readlink -f -- "$fp" 2>/dev/null) || fp_r=""
            [ -n "$fp_r" ] || fp_r="$fp"
            allowed_sub "$fp_r" || fail "subagent 도구 쓰기 허용 밖: $(basename -- "$t"): $fp"
        done < <(jq -rR --arg d "$D" 'fromjson? | select(.type=="assistant" and ((.timestamp // "") >= $d)) | .message.content[]? | select(.type=="tool_use") | select(.name=="Write" or .name=="Edit" or .name=="MultiEdit" or .name=="NotebookEdit") | (.input.file_path // .input.notebook_path // empty)' -- "$t" 2>/dev/null | sort -u)
        while IFS= read -r mn; do
            [ -n "$mn" ] || continue
            mcp_allowed "$mn" || fail "subagent MCP 호출(격리 spawn 에서 외부 발신 금지, 허용은 --allow-mcp 접두만): $(basename -- "$t"): $mn"
        done < <(jq -rR --arg d "$D" 'fromjson? | select(.type=="assistant" and ((.timestamp // "") >= $d)) | .message.content[]? | select(.type=="tool_use") | select(.name | startswith("mcp__")) | .name' -- "$t" 2>/dev/null | sort -u)
    done < <(find "$HOMEC/projects" -path '*/subagents/*.jsonl' \( -type f -o -type l \) -cnewer "$TREE" 2>/dev/null | sort)
else
    fail "jq 없음 — ④ transcript 검사 불가(fail-closed)"
fi

if [ "$FAIL" -eq 0 ]; then echo "RESULT: PASS"; exit 0; else echo "RESULT: FAIL $FAIL"; exit 1; fi
