#!/bin/bash
# git-guardrails.sh — 파괴적 git 명령 PreToolUse 차단 게이트. 파괴적 git 명령만 좁게 차단하고 commit·add·diff 등은 불간섭.
#
# 입력: 훅 JSON(stdin)의 .tool_input.command · agent_id · agent_type. 출력: 막을 때만 deny JSON 한 줄(stdout). 종료 코드: 늘 0.
# 판정 단위: 명령을 `;`·`&&`·`||`·`|`·`&`·개행으로 갈라 세그먼트마다 독립 판정한다(허용 예외는 그 조각 안에서만 산다).
#   셸 `-c` 뒤 인용 페이로드는 꺼내 한 번 더 검사하고, 줄 이음을 이어 붙인 사본도 같은 검사를 한 번 더 받는다(둘 중 하나라도 막으면 차단).
# 차단 대상:
#   push / pull 과 우회(send-pack·http-push·remote/subtree … push·submodule foreach …push…·lfs push/pre-push/pull·subtree pull·svn dcommit/set-tree/commit-diff/branch/tag/fetch/rebase).
#   reset --hard / clean -f / branch 강제 삭제(-D 와 삭제·강제의 조합 전부) / checkout·restore 로 작업트리 전체(. ./ :/) 폐기 / checkout·switch -f·--force·--discard-changes.
#   경로 지정 복구(git checkout <ref> -- <path>)는 통과. stash(인자 없음·push·drop·clear·pop·apply)는 차단, 조회(list·show)는 통과.
#   훅 우회: commit --no-v… 접두 전부와 commit 의 -n 묶음(다른 하위 명령의 -n 은 대상 아님) / -c core.hooksPath=…(하네스 훅 경로 ~/.claude/.git/hooks 를 절대 경로나 `~/` 로 쓴 것만 허용) /
#     git config core.hooksPath 설정 / --config-env · GIT_CONFIG_* 의 hookspath / include.path·includeIf.*.path·-c include.path= /
#     GIT_CONFIG_GLOBAL·GIT_CONFIG_SYSTEM·GIT_DIR·GIT_COMMON_DIR·--git-dir·--work-tree / -c alias.*·git config alias.* 설정 /
#     -c 키/값의 변수 확장($HOME 표기 포함) / git 이 든 세그먼트의 ANSI-C 인용. config 의 읽기·해제 형태(--get·--list·--unset 등)는 통과.
#   확장 검사(scripts/git_guard_ext.py, 맨 끝에서 호출): -c 허용 목록 · 같은 효과의 환경 변수 · 이력 삭제 하위 명령 · 커밋 안 된 경로의 복구 ·
#     셸 페이로드 재귀 · 데이터 손실 · ref 삭제 · 프로그램 실행 계열. 목록과 근거 표는 git_guard_ext.py docstring 규칙 11. 판정 불가 · 실행 실패는 차단.
# 승인 마커: 첫 줄 "# APPROVED"(정확 매칭, 인용 실재 검사는 같은 체인에서 먼저 도는 bash-write-check.sh). 마커 줄을 떼고 모든 검사를 돌린다.
#   deny 는 마커로 풀린다(하위 명령이 확정됐고 push · pull 이 아닌 차단, 확장 검사의 ok=True). deny_strict 는 안 풀린다(push · pull 과 그 계열,
#   그것을 감출 수 있어 판정을 확정할 수 없는 꼴, 확장 검사의 기본).
# 서브 에이전트: 훅 입력에 agent_id 가 있고 agent_type 이 gitops 가 아니면(비었거나 못 읽어도) commit·commit-tree·cherry-pick·revert·merge·rebase·am·
#   update-ref·fast-import · HEAD 를 옮기는 reset · propagate-queue.sh 실행을 막는다(마커로도 안 풀림). SUBG · SUBR 는 세그먼트 머리의 git 만 보는
#   좁은 정규식이고, 나머지 꼴은 git_guard_ext.py 규칙 12 가 막는다. main(agent_id 없음)·gitops 의 판정은 바꾸지 않는다.
# 한계: 이 파일의 정규식은 평문 명령과 셸 -c 페이로드만 본다($()·백틱·변수 간접 실행은 bash-write-check.sh 가 별도로 차단한다).
#   확장 검사의 한계는 git_guard_ext.py docstring 을 본다. 확장 검사는 git 이 든 명령에 따옴표 밖 << 가 있으면(<<< 제외) 전부 차단한다
#   (커밋 메시지는 git commit -F <파일>). 이미 core.hooksPath 가 설정된 저장소의 커밋, 이 저장소 밖에서 만든 설정(Write 로 심은 ~/.gitconfig 포함), 미리 정의된 git 별칭 · 셸 별칭 ·
#   함수 · 래퍼 스크립트로 감싼 push, 마커로 풀린 훅 경로가 가리키는 훅 프로그램의 push, xargs·find -exec·parallel 에 낱말을 나눠 넘긴 git 은 보지 못한다.
#   오탐 허용: 주석 속 «git push» 글자, 낱말 둘을 따로 인용한 `echo "git" "push"`, 커밋 메시지 인자의 `$'a'`, 커밋 메시지 속 `git config core.hooksPath` 글자.
# REF: mattpocock/skills `git-guardrails-claude-code`(MIT) 패턴 흡수, 자체 구현(2026-08-06 사용자 승인)
# REF: knowledge/harness/code-history/scripts__git-guardrails.sh.md

# WHY: 2026-11-24 사용자 결정 «세 명령도 막음»(00b1d3ed54 뒤 security 잔여 위험): 같은 서브 에이전트에게 fast-import 를 위 목록에 더하고,
#   HEAD 를 옮기는 reset(--soft·--mixed·--hard·--keep·--merge, 또는 `--` 앞 첫 인자가 HEAD 가 아님)과 scripts/propagate-queue.sh 실행도 막는다.
#   reset 은 모드 옵션 꼴만 SUBR 이 보고 인자 꼴과 xargs·parallel 뒤의 reset 은 git_guard_ext.py 가 본다. propagate-queue 가 든 명령은 git 낱말이 없어도
#   아래 단락을 지나 ext pq_allowed 가 «읽기 허용 목록» 으로 판정한다(security 3차 F1~F5 로 차단 목록을 뒤집음). git 이나 propagate-queue 가 든 서브 에이전트 명령은
#   4,000자 · 구분자 36개 · git 낱말 72개를 넘으면 분석 전에 막는다(security 4차 D5, 제한 시간 10초, 6차에서 검수 명령이 12개에 막혀 넓힘).
#   셸 -c 페이로드 하나는 구분자 2개로 세고, git_guard_ext.py 는 서브 에이전트의 analyze() 호출을 200회로 묶는다(security 5차 N1: 치환·페이로드 겹침).
#   받아들이는 한계(이 훅은 실수 방지 관문이지 악의적 서브 에이전트를 막는 경계가 아니다): 다른 언어를 거친 실행(python3 -c·파이프로 넘긴 글·sed 의 e),
#   환경 변수가 가리키는 설정 파일로 옵션 주입(RIPGREP_CONFIG_PATH), 글롭·변수로 숨은 이름, 미리 만든 복사본·링크, git 별칭, ssh,
#   객체를 만드는 저수준 명령(write-tree·hash-object -w·mktree·tag -a·notes add), main 세션 자신의 긴 입력(범위 밖).
#   오탐(서브 에이전트만): 허용 목록 밖의 읽기(less·bat·awk·`timeout 5 cat …`·`bash -n …`·`echo $(wc -l …)`), 전파 스크립트 파이프라인의 큰따옴표 속 `$`·따옴표 밖 글롭.

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$CMD" ] && exit 0
SUBAGENT=$(printf '%s' "$INPUT" | jq -r 'if ((.agent_id // "") | tostring) != "" and .agent_type != "gitops" then 1 else empty end' 2>/dev/null)
# WHY: 2026-11-24 security rounds 3-4 — each segment costs about 0.12 s here (25 `git log;` = 3.06 s, 100 = 12.6 s; at load average 33,
#   40 = 5.0-5.3 s and 48 = 5.8-6.3 s) and the hook limit in settings.json is 10 s, so a subagent command naming git or propagate-queue
#   (also when quotes, backslashes or newlines split the word) is denied before parsing above 4,000 characters, 36 separators (`;` `|`
#   `&` newline, `&&` `||` `|&` count once) or 72 git words. 12 separators blocked a read-only review chain (round 6), 36 keeps the
#   worst case under 6 s on a busy server. A shell `-c` payload counts as two separators: each costs about 0.17 s here
#   (`bash -c 'git status'` x 30 = 5.3 s, x 60 = 10.1 s at load average 35, round 6).
if [ -n "$SUBAGENT" ] && printf '%s' "$CMD" | tr -d '"\047\134\n' | grep -qE 'git|propagate-queue'; then
    SJ=""; SEPS=""
    if [ "${#CMD}" -le 4000 ]; then
        SJ=$(printf '%s' "$CMD" | tr -d '"\047\134\n'); SJG=${SJ//git/}
        SEPS=${CMD//&&/;}; SEPS=${SEPS//||/;}; SEPS=${SEPS//|&/;}; SEPS=${SEPS//[^;|&$'\n']/}
        SEPS+=$(printf '%s' "$CMD" | grep -oE '[a-z]*sh([[:space:]]+-[^[:space:]]+)*[[:space:]]+-c[[:space:]]' | sed 's/.*/;;/' | tr -d '\n')
    fi
    if [ "${#CMD}" -gt 4000 ] || [ "${#SEPS}" -gt 36 ] || [ $(( (${#SJ} - ${#SJG}) / 3 )) -gt 72 ]; then
        jq -cn --arg r "[git 차단] 서브 에이전트는 커밋하지 않습니다. 바꾼 파일 목록과 커밋 메시지 안을 main 에 돌려주십시오(커밋은 main 이나 gitops 가 합니다). 명령이 너무 깁니다(4,000자 · 구분자 36개 · git 낱말 72개 상한, 나눠서 실행하십시오)." \
            '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
        exit 0
    fi
fi

APPR=""
if echo "$CMD" | head -1 | grep -qE '^# APPROVED([[:space:]]|$)'; then
    APPR=1
    CMD=$(printf '%s\n' "$CMD" | tail -n +2)
    INPUT=$(printf '%s' "$INPUT" | jq -c --arg c "$CMD" '.tool_input.command = $c')
fi
# NEVER: 원문 검사를 JOINED 로 바꿔 넘기지 않는다. 이어 붙이기는 따옴표·이스케이프를 보지 않아(`\\⏎` 는 셸에서 줄 이음이 아니다)
#   사본만 보면 원문이 막히던 꼴이 통과할 수 있다(2026-11-12 reviewer).
JOINED=${CMD//$'\\\n'/}

echo "$CMD" | grep -q 'git' || printf '%s' "$CMD" | tr -d '"\047\134' | grep -q 'git' \
    || printf '%s' "$JOINED" | tr -d '"\047\134' | grep -q 'git' \
    || { [ -n "$SUBAGENT" ] && printf '%s' "$JOINED" | tr -d '"\047\134' | grep -q 'propagate-queue'; } || exit 0

emit_deny() {
    jq -cn --arg r "[git 차단] $1" \
        '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
    exit 0
}
deny() {
    [ -n "$APPR" ] && return 0
    emit_deny "$1 — 사용자 직접 실행 원칙. 목적을 설명하고 승인받은 뒤 첫 줄 '# APPROVED'로 재실행하세요 (code-execution.md § Hook 차단 시 처리)."
}
deny_strict() {
    emit_deny "$1 — 승인 표시(# APPROVED)로도 통과하지 않습니다. push·pull 과 그것을 감출 수 있는 형태는 사용자가 터미널에서 직접 실행하세요 (2026-11-12 결정, code-execution.md § Hook 차단 시 처리)."
}

# NEVER: 주석으로 보이는 구간을 지우지 않는다. 주석 판정이 틀린 경우(`echo a\ #b; git push`·`${x:- #}; git push`)에도
#   뒤의 명령이 지워지지 않게 하려는 닫힘 방향 설계다(2026-10-02 보안 재검수 I).
strip_quoted() {
    tr '\n' '\001' | awk -v NL="$(printf '\001')" '{
        n = length($0); out = ""; i = 1
        while (i <= n) { c = substr($0, i, 1)
            if (c == "\\") { if (substr($0, i + 1, 1) ~ /[;&|()<>]/) out = out "QQ"; else out = out substr($0, i, 2); i += 2; continue }
            if (c == "#" && (i == 1 || substr($0, i - 1, 1) == NL || substr($0, i - 1, 1) ~ /[[:space:];&|(]/)) {
                j = index(substr($0, i), NL); if (j == 0) { out = out substr($0, i); break }
                out = out substr($0, i, j - 1); i += j - 1; continue }
            if (c == "$" && substr($0, i + 1, 1) == "\047") { k = i + 2
                while (k <= n) { d = substr($0, k, 1)
                    if (d == "\\") { k += 2; continue }
                    if (d == "\047") break
                    k++ }
                if (k > n) { out = out substr($0, i); break }
                body = substr($0, i + 2, k - i - 2)
                if (body ~ /^[;&|()<>]+$/) out = out "QQ"
                else if (index(body, NL) == 0 && body !~ /[[:space:]]/) out = out body
                i = k + 1; continue }
            if (c == "\"" || c == "\047") { k = i + 1
                while (k <= n) { d = substr($0, k, 1)
                    if (c == "\"" && d == "\\") { k += 2; continue }
                    if (d == c) break
                    k++ }
                if (k > n) { out = out substr($0, i); break }
                body = substr($0, i + 1, k - i - 1)
                if (body ~ /^[;&|()<>]+$/) out = out "QQ"
                else if (index(body, NL) == 0 && body !~ /[[:space:]]/) out = out body
                i = k + 1; continue }
            out = out c; i++ }
        gsub(NL, ";", out); print out }'
}

G='git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?([[:space:]]+-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+'
SUBP='^[[:space:]]*(([$]?[(]|[{`])[[:space:]]*|(!|if|then|do|else|elif|while|until|time|env|command|exec|nohup|nice|sudo|builtin|[A-Za-z_][A-Za-z0-9_]*[+]?=[^[:space:]]*)[[:space:]]+)*([^[:space:]]*/)?=?git(-|([[:space:]]+(-[Cc][[:space:]]+([^[:space:]\\]|\\.)+|-[^[:space:]]+))*[[:space:]]+)'
SUBG="${SUBP}(commit|commit-tree|cherry-pick|revert|merge|rebase|am|update-ref|fast-import)([[:space:])]|\$)"
SUBR="${SUBP}reset([[:space:]][^;|&]*)?[[:space:]]--[smhk][a-z]*([=[:space:])]|\$)"

HP_REAL="$(readlink -f "${HOME}/.claude/.git/hooks" 2>/dev/null)"
HP_OK="(${HOME}/\.claude/\.git/hooks|${HP_REAL:-${HOME}/\.claude/\.git/hooks}|~/\.claude/\.git/hooks|\\\$[{]?HOME[}]?/\.claude/\.git/hooks)/?"

HPK='[Cc][Oo][Rr][Ee]\.[Hh][Oo][Oo][Kk][Ss][Pp][Aa][Tt][Hh]'
GITB='(^|[[:space:];|&(=])([^[:space:]]*/)?git'
HOME_REASSIGNED=""

# WHY: git 2.34.1 실측 — `--no-veri`·`--no-verif`·`--no-verify` 가 훅을 건너뛴다. 버전마다 옵션 목록이 달라질 수 있으므로
#   `--no-v` 이상 접두를 전부 막는다(`--no-verbose` 오탐은 감수).
check_commit_opts() {
    local V="$1" CTX="$2"
    echo "$V" | grep -qE "${G}commit([[:space:]][^;|&]*)?[[:space:]]--no-v[a-z-]*([[:space:])=]|$)" \
        && deny "git commit --no-verify(약어 --no-v… 포함) (pre-commit·commit-msg 게이트 전면 우회 — 감사 원장에 남지 않는다)${CTX}"
    # WHY: -n 앞에 올 수 있는 값 없는 글자는 `git commit -h`(2.34.1)의 짧은 옵션 전체에서 값을 받는 c C F m t S u 를 뺀 a e i n o p q s v z 다
    #   (2026-10-17 대조: 이전 목록은 p 가 빠져 `-pn` 이 통과했다).
    echo "$V" | grep -qE "${G}commit([[:space:]][^;|&]*)?[[:space:]]-[aeinopqsvz]*n[a-zA-Z0-9]*([[:space:])]|$)" \
        && deny "git commit -n (묶음 어디든 --no-verify 축약 — 게이트 전면 우회)${CTX}"
    return 0
}

check_branch_force() {
    local V="$1" CTX="$2" BR DEL FRC E='([[:space:])]|$)'
    BR="${G}branch[[:space:]]([^;|&]*[[:space:]])?"
    DEL='(-[a-zA-Z]*d[a-zA-Z]*|--de[a-z]*)'
    FRC='(-[a-zA-Z]*f[a-zA-Z]*|--forc[a-z]*)'
    if echo "$V" | grep -qE "${BR}-[a-zA-Z]*D[a-zA-Z]*${E}" \
        || echo "$V" | grep -qE "${BR}-[a-zA-Z]*(d[a-zA-Z]*f|f[a-zA-Z]*d)[a-zA-Z]*${E}" \
        || echo "$V" | grep -qE "${BR}${DEL}[[:space:]]([^;|&]*[[:space:]])?${FRC}${E}" \
        || echo "$V" | grep -qE "${BR}${FRC}[[:space:]]([^;|&]*[[:space:]])?${DEL}${E}"; then
        deny "git branch 강제 삭제 (-D·-fd·-d -f·--delete --force 조합)${CTX}"
    fi
    return 0
}

check_extra() {
    local V="$1" CTX="$2" RD
    RD="${G}config[^;|&]*[[:space:]]--(get|get-all|get-regexp|get-urlmatch|list|unset|unset-all)([[:space:]]|$)"
    if echo "$V" | grep -qiE "${G}config([[:space:]][^;|&]*)?[[:space:]]include(if\.[^[:space:]]*)?\.path([[:space:]=]|$)"; then
        echo "$V" | grep -qE "$RD" || deny_strict "git config include.path/includeIf (다른 파일로 core.hooksPath 를 끌어들이는 우회 — 허용 예외 없음)${CTX}"
    fi
    echo "$V" | grep -qiE "${GITB}[^;|&]*[[:space:]]-c[[:space:]]*include(if\.[^[:space:]]*)?\.path=|--config-env[[:space:]=]+include(if\.[^[:space:]]*)?\.path=" \
        && deny_strict "git -c include.path= (다른 파일로 core.hooksPath 를 끌어들이는 우회 — 허용 예외 없음)${CTX}"
    if echo "$V" | grep -qiE "${G}config([[:space:]][^;|&]*)?[[:space:]]alias\.[^[:space:]]+"; then
        echo "$V" | grep -qE "$RD" || deny_strict "git config alias.* (셸 alias 로 push 등 규칙 우회 — 설정 자체를 막는다. push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    fi
    echo "$V" | grep -qE "${G}(send-pack|http-push)([[:space:]]|$)" \
        && deny_strict "git send-pack/http-push (push 우회 — push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    echo "$V" | grep -qE "${G}(remote|subtree)[[:space:]]([^;|&]*[[:space:]])?push([[:space:]]|$)" \
        && deny_strict "git remote/subtree … push (push 우회 — push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    echo "$V" | grep -qE "${G}submodule[[:space:]]+([^;|&]*[[:space:]])?foreach[[:space:]]([^;|&]*[[:space:]])?[^[:space:]]*push" \
        && deny_strict "git submodule foreach … push (push 우회 — push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    return 0
}

check_cfg_opts() {
    local V="$1" CTX="$2" GOPT
    GOPT="${GITB}([[:space:]]+-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+"
    echo "$V" | grep -qiE "${GOPT}-c[[:space:]]*alias\." \
        && deny_strict "git -c alias.* (인라인 별칭으로 하위명령 규칙 우회)${CTX}"
    if echo "$V" | grep -qiE "${GITB}[^;|&]*[[:space:]]-c[[:space:]]*core\.hookspath="; then
        [ -n "$HOME_REASSIGNED" ] && deny "git -c core.hooksPath= — HOME 재대입 뒤 훅 경로 예외 불인정${CTX}"
        echo "$V" | sed -E "s#[[:space:]]-c[[:space:]]*${HPK}=${HP_OK}([[:space:]]|\$)# #g" \
            | grep -qiE "[[:space:]]-c[[:space:]]*core\.hookspath=" \
            && deny "git -c core.hooksPath= (훅 경로 바꿔치기 — 게이트 전면 우회)${CTX}"
    fi
    echo "$V" | grep -qiE -e "${GOPT}--config-env[[:space:]=]+[^[:space:]]*core\.hookspath=" \
        && deny "core.hooksPath 변형 지정(--config-env) — 값을 검증할 수 없어 차단${CTX}"
    echo "$V" | grep -qE "${GOPT}-c[[:space:]]*[^[:space:]]*\\$" \
        && deny_strict "git -c 키에 변수 확장 — 검증 불가 (core.hooksPath 우회 가능)${CTX}"
    if echo "$V" | grep -qiE "${G}config([[:space:]][^;|&]*)?[[:space:]]core\.hooksPath([[:space:]=]|$)"; then
        echo "$V" | grep -qE "${G}config[^;|&]*[[:space:]]--(get|get-all|get-regexp|get-urlmatch|list|unset|unset-all)([[:space:]]|$)" \
            || deny "git config core.hooksPath (훅 경로 영구 변경. 이후 모든 커밋에서 게이트 전면 우회 — 정규화본 전체 기준)${CTX}"
    fi
    check_extra "$V" "$CTX"
    return 0
}

check_git_segment() {
    local S="$1" CTX="$2"
    [ -n "$SUBAGENT" ] && { echo "$S" | grep -qE "$SUBG" || echo "$S" | grep -qE "$SUBR"; } \
        && emit_deny "서브 에이전트는 커밋하지 않습니다. 바꾼 파일 목록과 커밋 메시지 안을 main 에 돌려주십시오(커밋은 main 이나 gitops 가 합니다).${CTX}"
    echo "$S" | grep -qE "${G}push([[:space:])]|$)" \
        && deny_strict "git push (push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    echo "$S" | grep -qE "${G}pull([[:space:])]|$)" \
        && deny_strict "git pull (push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    echo "$S" | grep -qE "${G}(lfs[[:space:]]([^;|&]*[[:space:]])?(push|pre-push|pull)|subtree[[:space:]]([^;|&]*[[:space:]])?pull)([[:space:])]|$)" \
        && deny_strict "git lfs push/pre-push/pull · subtree pull (push/pull 우회 — push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    echo "$S" | grep -qE "${G}svn[[:space:]]([^;|&]*[[:space:]])?(fetch|rebase)([[:space:])]|$)" \
        && deny_strict "git svn fetch/rebase (SVN 서버에서 받아옴 — push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    echo "$S" | grep -qE "${G}svn[[:space:]]([^;|&]*[[:space:]])?(dcommit|set-tree|commit-diff|branch|tag)([[:space:])]|$)" \
        && deny_strict "git svn dcommit/set-tree/commit-diff/branch/tag (SVN 서버로 올려 보냄 — push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    echo "$S" | grep -qE "${G}reset[[:space:]][^;|&]*--hard" \
        && deny "git reset --hard (작업트리·이력 파괴)${CTX}"
    echo "$S" | grep -qE "${G}clean[[:space:]][^;|&]*-[a-zA-Z]*f" \
        && deny "git clean -f (미추적 파일 영구 삭제)${CTX}"
    if echo "$S" | grep -qE "${G}stash([[:space:])]|$)"; then
        echo "$S" | grep -qE "${G}stash[[:space:]]+(list|show)([[:space:])]|$)" \
            || deny "git stash (작업트리 변경을 치우거나 덮어씀 — push·drop·clear·pop·apply 포함. 조회는 list·show)${CTX}"
    fi
    check_branch_force "$S" "$CTX"
    echo "$S" | grep -qE "${G}(checkout|restore)[[:space:]][^;|&]*(--[[:space:]]+)?\.([[:space:])]|$)" \
        && deny "git checkout/restore . (작업트리 전체 폐기 — 경로 지정 복구는 허용)${CTX}"
    echo "$S" | grep -qE "${G}(checkout|restore)[[:space:]]([^;|&]*[[:space:]])?(\./|:/)([[:space:])]|$)" \
        && deny "git checkout/restore ./ · :/ (작업트리 전체 폐기 — 경로 지정 복구는 허용)${CTX}"
    echo "$S" | grep -qE "${G}(checkout|switch)[[:space:]]([^;|&]*[[:space:]])?(-[a-zA-Z]*f[a-zA-Z]*|--force|--discard-changes)([[:space:])]|$)" \
        && deny "git checkout/switch -f · --force · --discard-changes (로컬 수정 폐기 강제 전환)${CTX}"
    echo "$S" | grep -qiE "(^|[[:space:];|&(])([^[:space:]]*/)?git[^;|&]*[[:space:]]-c[[:space:]]*alias\." \
        && deny_strict "git -c alias.* (인라인 별칭으로 하위명령 규칙 우회)${CTX}"
    check_commit_opts "$S" "$CTX"
    check_extra "$S" "$CTX"

    # NEVER: 이 sed 에 I 플래그를 쓰지 않는다. 허용값 HP_OK 는 파일시스템 경로라 대소문자를 구분해야 하므로 키(HPK)만 문자 클래스로 푼다(2026-10-17 외부 검토 반례).
    if echo "$S" | grep -qiE "${GITB}[^;|&]*[[:space:]]-c[[:space:]]*core\.hookspath="; then
        [ -n "$HOME_REASSIGNED" ] && deny "git -c core.hooksPath= — HOME 재대입 뒤 훅 경로 예외 불인정${CTX}"
        echo "$S" | sed -E "s#[[:space:]]-c[[:space:]]*${HPK}=${HP_OK}([[:space:]]|\$)# #g" \
            | grep -qiE "[[:space:]]-c[[:space:]]*core\.hookspath=" \
            && deny "git -c core.hooksPath= (훅 경로 바꿔치기 — 게이트 전면 우회)${CTX}"
    fi
    if echo "$S" | grep -qE "${GITB}([[:space:]]+-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+-c[[:space:]]*[^[:space:]]*\\$" \
        || echo "$S" | grep -qiE -e "--config-env[[:space:]=]+[^[:space:]=]*\\$"; then
        deny_strict "git -c 키에 변수 확장 — 검증 불가 (core.hooksPath 우회 가능)${CTX}"
    fi
    if echo "$S" | grep -qiE -e "--config-env[[:space:]=]+[^[:space:]]*core\.hookspath=" \
        || { echo "$S" | grep -qiE -e "(^|[^A-Za-z0-9_])(GIT_CONFIG_PARAMETERS|GIT_CONFIG_COUNT|GIT_CONFIG_KEY_[0-9]+)=" \
            && echo "$S" | grep -qi -e "hookspath"; }; then
        deny "core.hooksPath 변형 지정(--config-env·GIT_CONFIG_*) — 값을 검증할 수 없어 차단${CTX}"
    fi

    if echo "$S" | grep -qiE "${G}config([[:space:]][^;|&]*)?[[:space:]]core\.hooksPath([[:space:]=]|$)"; then
        echo "$S" | grep -qE "${G}config[^;|&]*[[:space:]]--(get|get-all|get-regexp|get-urlmatch|list|unset|unset-all)([[:space:]]|$)" \
            || deny "git config core.hooksPath (훅 경로 영구 변경. 이후 모든 커밋에서 게이트 전면 우회)${CTX}"
    fi
    return 0
}

# NEVER: 허용 예외가 있는 규칙(stash list·config --get 등)을 세그먼트 밖에서 판정하지 않는다. 앞 조각의 예외가 뒤 조각의 파괴 동작을 덮는다
#   (2026-09-14 재감사 B3·B4: `git stash list && git stash drop stash@{0}` 는 `stash list` 매칭 하나로 통과했다).
check_git() {
    local seg v bs variants
    bs=$(printf '%s' "$1" | tr -d '\134')
    variants=("$1")
    [ "$bs" != "$1" ] && variants+=("$bs")
    for v in "${variants[@]}"; do
        while IFS= read -r seg; do
            [ -n "${seg//[[:space:]]/}" ] || continue
            check_git_segment "$seg" "$2"
        done <<< "$(printf '%s' "$v" | sed -E 's/[;&|]/\n/g')"
    done
    return 0
}

# NEVER: 이 검사를 세그먼트로 잘라 하지 않는다. 따옴표 값 안의 `;`(`'user.name'='x;y' 'core.hooksPath'=…`)에서 잘려 통과했다(2026-10-17 Codex 3차).
check_env_raw() {
    local v t="$1"
    for v in "$t" "$(printf '%s' "$t" | tr -d "\"'")" "$(printf '%s' "$t" | tr -d "\"'" | tr -d '\134')"; do
        if printf '%s' "$v" | tr '\n' ' ' | grep -qiE '(^|[^A-Za-z0-9_])(GIT_CONFIG_PARAMETERS|GIT_CONFIG_COUNT|GIT_CONFIG_KEY_[0-9]+)=.*hookspath'; then
            deny "core.hooksPath 변형 지정(GIT_CONFIG_*) — 환경 변수 값은 쪼개 검사할 수 없어 원문·따옴표 제거본 전체 기준으로 차단${2:-}"
        fi
        printf '%s' "$v" | grep -qE '(^|[[:space:]])--work-tree([=[:space:]]|$)' \
            && deny "git --work-tree 지정 — 확인 호출이 다른 작업 트리를 볼 수 있어 차단${2:-}"
        if printf '%s' "$v" | grep -qE '(^|[^A-Za-z0-9_])(GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM|GIT_DIR|GIT_COMMON_DIR)=|(^|[[:space:]])--git-dir([=[:space:]]|$)'; then
            deny_strict "git 설정 파일·저장소 위치 지정(환경변수 GIT_CONFIG_GLOBAL·GIT_CONFIG_SYSTEM·GIT_DIR·GIT_COMMON_DIR, 옵션 --git-dir) — 그 안의 core.hooksPath 를 검사할 수 없어 차단${2:-}"
        fi
    done
}

check_ansi_c() {
    local seg
    while IFS= read -r seg; do
        if grep -qF "\$'" <<< "$seg" && grep -qiE '(^|[^A-Za-z0-9_])git([^A-Za-z0-9_]|$)|GIT_CONFIG_' <<< "$seg"; then
            deny_strict "ANSI-C 인용(\$'…')은 해석하지 않아 차단 — git 명령 세그먼트에서는 \$'…' 를 쓰지 않는다${2:-}"
        fi
    done <<< "$(printf '%s' "$1" | sed -E 's/[;&|]/\n/g')"
}

check_raw_all() {
    local uq bs v seg
    check_env_raw "$1" "$2"
    check_ansi_c "$1" "$2"
    uq=$(printf '%s' "$1" | tr '\n' ';' | tr -d "\"'")
    bs=$(printf '%s' "$uq" | tr -d '\134')
    for v in "$uq" "$bs"; do
        while IFS= read -r seg; do
            [ -n "${seg//[[:space:]]/}" ] || continue
            check_cfg_opts "$seg" "${2:- — 따옴표·백슬래시 제거본}"
            [ "$v" = "$bs" ] && [ "$bs" != "$uq" ] && check_commit_opts "$seg" "${2:- — 백슬래시 제거본}"
        done <<< "$(printf '%s' "$v" | sed -E 's/[;&|]/\n/g')"
    done
}

# NEVER: 아래 while 루프에 파이프로 먹이지 않는다(here-string 만 쓴다). while 이 서브셸로 떨어지면 deny 의 종료가 본체에 안 닿는다.
SHC_RE="(^|[[:space:];&|(])([^[:space:]]*/)?(r?ba|z|da|k)?sh([[:space:]]+-[^[:space:]]+)*[[:space:]]+-c[[:space:]]+('[^']*'|\"[^\"]*\")"
check_cmd() {
    local payload P PAYLOADS EXT_OUT EXT_RC
    HOME_REASSIGNED=""
    printf '%s' "$1" | grep -qE '(^|[[:space:];&|(])(export[[:space:]]+)?HOME=' && HOME_REASSIGNED=1
    check_git "$(printf '%s' "$1" | strip_quoted)" "$3"
    check_raw_all "$1" "$3"
    PAYLOADS=$(printf '%s\n' "$1" | grep -oE "$SHC_RE" | sed -E "s/^[^'\"]*//")
    while IFS= read -r payload; do
        [ -n "$payload" ] || continue
        P=$(printf '%s' "$payload" | sed -E "s/^(['\"])(.*)\1\$/\2/" | strip_quoted)
        check_git "$P" " — 셸 -c 페이로드 안$3"
        check_raw_all "$(printf '%s' "$payload" | sed -E "s/^(['\"])(.*)\1\$/\2/")" " — 셸 -c 페이로드 안(원문 기준)$3"
    done <<< "$PAYLOADS"
    # 확장 검사 (2026-11-09 5단계): 기존 검사를 모두 통과한 명령만 넘긴다. 실행 실패는 막는 방향이다.
    # WHY: 2026-11-24 — a hook killed at its 10 s limit left the analyzer running at 99% CPU; `timeout` (7 s, 1 s grace) backs up its own 6 s limit (exit 124)
    EXT_OUT=$(printf '%s' "$2" | timeout -k 1 7 python3 -I "$(dirname "$(readlink -f "$0")")/git_guard_ext.py" ${APPR:+--approved}); EXT_RC=$?
    [ -n "$EXT_OUT" ] && { printf '%s\n' "$EXT_OUT"; exit 0; }
    [ "$EXT_RC" -eq 124 ] && [ -n "$SUBAGENT" ] && emit_deny "서브 에이전트 명령의 분석 시간 초과: 명령을 나눠 실행하십시오(확장 검사 6초 한도)$3"
    [ "$EXT_RC" -ne 0 ] && deny_strict "확장 검사(git_guard_ext.py) 실행 실패 — 판정할 수 없어 차단$3"
    return 0
}
check_cmd "$CMD" "$INPUT" ""
[ "$JOINED" != "$CMD" ] \
    && check_cmd "$JOINED" "$(printf '%s' "$INPUT" | jq -c --arg c "$JOINED" '.tool_input.command = $c')" " — 줄 이음을 이어 붙인 사본"

exit 0
