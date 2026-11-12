#!/bin/bash
# git-guardrails.sh — 파괴적 git 명령 PreToolUse 차단 게이트
#
# 판단 근거 (2026-08-06 사용자 승인 — mattpocock/skills `git-guardrails-claude-code`(MIT)
# 패턴 흡수, 자체 구현): "git push/pull은 항상 사용자 직접"(agent-routing.md)과 작업트리
# 파괴 방지는 종전까지 룰 문서로만 존재 — bash-write-check.sh는 git 토큰을 의도적으로
# 중화하므로(commit 등 정상 git 쓰기는 commit 규칙 소관) 물리적 강제 장치가 없었다.
# 이 훅이 그 구멍을 메운다: 파괴적 git 명령만 좁게 차단, commit·add·diff 등은 불간섭.
#
# 차단 대상: push / pull / reset --hard / clean -f / branch -D / checkout·restore로
#   작업트리 전체(.) 폐기. 경로 지정 복구(git checkout <ref> -- <path>)는 통과.
#   + stash (2026-09-14 추가): 인자 없는 stash·push·drop·clear·pop·apply. 조회(list·show)는 통과.
#   + 훅 전면 우회 3종 (2026-09-06 추가): commit --no-verify·commit -n / -c core.hooksPath=… /
#   git config 로 core.hooksPath 설정. 셋 다 pre-commit·commit-msg 게이트를 통째로 건너뛰므로
#   감사 원장에 흔적이 남지 않는다. 즉 «지켰는지 나중에 확인할 방법»까지 함께 사라진다는 점에서
#   파괴적 명령과 같은 급이다. 특히 git config 는 한 번 실행되면 그 뒤 모든 커밋에서 훅이 죽는다.
#   -n 은 다른 하위 명령에서 뜻이 다르므로(예: git tag -n) commit 하위 명령일 때만 잡는다.
#   변형 3종 (2026-10-17 외부 검토 반례): 키 대소문자(`core.hookspath`)·`-c` 붙여쓰기(`-cCore.hooksPath=`) /
#   `--config-env=core.hooksPath=ENV` / 환경변수 경유(GIT_CONFIG_PARAMETERS·GIT_CONFIG_COUNT·GIT_CONFIG_KEY_n 에 hookspath) — 뒤 둘은 값을 검증할 수 없어 무조건 차단.
#   예외: 하네스 자신의 훅 경로(~/.claude/.git/hooks)를 가리키는 -c 지정은 통과시킨다.
#   **절대 경로(또는 `~/`)로 쓴 것만 허용한다. `$HOME`·`${HOME}` 표기는 -c 키/값의 변수 확장 규칙(검증 불가)에 걸려 막힌다**(2026-10-17 문서 정정).
#   훅을 «켜려는» 지정까지 막을 이유가 없기 때문이다. config 의 읽기·해제 형태
#   (--get·--list·--unset 등)도 통과시킨다.
#   간접 우회 (2026-10-17 검수팀 보안): `git config include.path`·`includeIf.*.path`·`-c include.path=` / 환경변수 GIT_CONFIG_GLOBAL·GIT_CONFIG_SYSTEM·GIT_DIR·GIT_COMMON_DIR
#   (명령 어디든) — 둘 다 다른 파일의 core.hooksPath 를 끌어들이므로 허용 예외 없이 막는다. 커밋 훅 건너뛰기는 `--no-v…` 접두 전부와 `-n` 묶음 어디든,
#   브랜치 강제 삭제는 -D 와 삭제·강제의 조합 전부, push 우회는 `git config alias.*` 설정·`send-pack`·`http-push`·`remote/subtree … push`·`submodule foreach …push…` 를 막는다.
#   + 확장 검사 (2026-11-09 5단계 — scripts/git_guard_ext.py 로 넘김, 맨 끝에서 호출): 1) `git -c` 허용 목록(출력 형식·신원·프로토콜 키만, 나머지는 프로그램 실행·설정 끌어오기 가능이라 차단)
#   2) 같은 효과의 환경 변수(GIT_CONFIG_*·GIT_EXTERNAL_DIFF·GIT_SSH*·GIT_ASKPASS·pager/editor 류) 3) filter-repo·filter-branch·update-ref -d·gc --prune·prune·reflog expire/delete·rebase(--abort 제외)
#   4) restore·checkout 경로 복구는 «커밋 안 된 변경이 있는 경로»만 차단(실제 git diff 로 확인, 확인 호출은 fsmonitor 등 저장소 설정 코드 실행을 끄고 환경을 정리해 부른다)
#   5) 셸 -c·eval 페이로드 재귀. 판정 불가(따옴표 실패·cd 동반·git 이 명령 자리에 없음·확인 호출 실패)는 전부 차단(fail-closed). 한계: 저장소 config alias 로 감싼 하위명령·`repack -a -d` 류·셸 함수(R11 범위 밖의 것)·목록 밖 래퍼.
#   검수 지적 보강 (2026-11-09 R1~R11, r5 H·C): 셸 확장·줄 이음 차단, heredoc 은 폐기된 판정(R2/R2b)을 버리고 «git 이 든 명령에 따옴표 밖 << 가 있으면 전부 차단»(커밋 메시지는 git commit -F <파일>),
#   래퍼 확대(env -S·su·flock·script·watch·tmux 전 하위명령·here-string·따옴표 속 $()·따옴표 없는 백틱), 환경 변수 확대(HOME·PATH·GIT_DIR·GIT_*_PATHSPECS·GIT_ALLOW_PROTOCOL 류, `+=`),
#   assume-unchanged·skip-worktree 로 숨긴 변경·checkout-index·read-tree -u·apply -R, 긴 옵션 약어, `2>&1` 숫자, git config 쓰기에도 -c 허용 목록, 저장소 filter.* 설정 시 경로 복구 차단,
#   R11 셸 별칭·hash·함수·명령 자리 변수로 git 을 감싼 명령 차단.
#   넓은 범위 (r5 C, 사용자 결정 «데이터 손실·ref 삭제·프로그램 실행 계열은 막는다»): 커밋 안 된 작업·색인을 버리거나(reset --hard/--merge/--keep·clean·rm -f·mv -f·worktree remove --force·checkout/restore --ours/--theirs·update-index --remove 류),
#   ref·객체·reflog·설정을 되돌리기 어렵게 지우거나(tag -d/-f·branch -f/-D/-M/-C·remote remove·update-ref 비후손 이동·notes remove·replace·repack -d·config --unset 의 global/system/file 범위·worktree add -B),
#   git 이 지정한 프로그램을 돌리는(clone -c·ext::·--upload-pack·difftool·bisect run·submodule foreach·send-email·instaweb·--output 덮어쓰기 포함) 형태를 막는다. 목록과 근거 표는 git_guard_ext.py docstring 규칙 11.
#   sec4 (2026-11-09): 따옴표·백슬래시로 쪼갠 이름(`g"i"t`·`g\it`)도 git 으로 본다 — 아래 단락과 check_git 이 같은 사본으로 판정한다.
#   r5fix (2026-11-09 stage5_fix_r5.md): zsh `=git` 도 git 낱말(GITB 경계에 `=`), 이 파일의 push·pull·stash·commit 훅 건너뛰기·checkout -f·전체 폐기 규칙은 git_guard_ext.py 에도 같은 판정으로 있다
#   (`git-<하위명령>` 실행 파일 경로·`=bash -c` 페이로드는 이 파일의 정규식이 못 보기 때문). 그 밖의 r5fix 항목(apply·fetch --prune·merge-file·GIT_TRACE 값·glob 연산자 등)은 확장 파일 docstring 참조.
#   r6fix (2026-11-09 stage5_fix_r6.md): 따옴표·백슬래시로 감싼 구두점(`';'`·`\|`)은 연산자가 아니라 인자 — strip_quoted 가 본문이 구두점뿐인 따옴표와 `\`+구두점을 자리표시자 낱말(QQ)로 바꾼다
#   (되살리면 세그먼트 분리자가 돼 뒤 인자를 못 본다). SHC_RE 에 rbash. 그 밖의 r6fix 항목(source·`.` here-string, 변수 대입 자리, 값 받는 옵션, --skip 등)은 확장 파일 docstring 참조.
# 우회: 첫 줄 "# APPROVED" (bash-write-check와 동일 규약 — 사용자 승인 후 재실행).
#   `# APPROVED` 가 실제 사용자 승인 발화를 인용했는지 검사하는 일은 같은 PreToolUse 체인에서
#   먼저 도는 bash-write-check.sh 가 한다(순서: bash-write-check → git-guardrails). 여기서 반복하지 않는다.
# 판정 단위 (2026-09-14 재감사 B3·B4): 명령 문자열을 `;`·`&&`·`||`·`|`·개행으로 갈라 **세그먼트마다
#   독립 판정**한다. 전체 문자열 매칭이던 종전에는 앞 조각의 허용 예외(stash list·config --get)가
#   뒤 조각의 파괴 동작(stash drop·config core.hooksPath 설정)까지 덮어 통과시켰다. 아래 check_git 참조.
# 한계: 평문 명령과 셸 `-c` 페이로드만 검사한다. $()·백틱·변수 간접 실행은 bash-write-check가
#   별도로 차단한다 (~95% 커버 철학 동일).
#   셸 페이로드 재검사 (2026-09-08 security 재현): `bash --noprofile --norc -c 'git push'` 는
#   따옴표 제거 전처리 때문에 페이로드가 통째로 사라져 통과했다. bash-write-check.sh 의 2단계
#   재검사 방식을 이식해 셸 `-c` 뒤 인용 페이로드를 꺼내 한 번 더 검사한다. 따옴표 제거를 아예
#   없애지 않는 이유는 `git commit -m 'docs: git push 규칙 보강'` 이 오탐되기 때문이다.
# 막지 못하는 것: 이미 core.hooksPath 가 설정돼 있는 저장소에서의 커밋(설정 시점을 이미 놓쳤다),
#   셸 별칭·함수로 감싼 git, 이 저장소 밖에서(다른 셸·편집기·전역 설정 파일 직접 수정으로)
#   만들어 둔 설정.
#   Write 로 ~/.gitconfig 를 만들어 전역 훅 경로를 심는 길은 scope-gate 범위 밖이다(어느 저장소에도 속하지 않는 경로라 경계 개념이 없다) — 알려진 한계.

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$CMD" ] && exit 0

# 사용자 승인 마커 (정확 매칭 — '# APPROVED_X' 오승인 방지, bash-write-check와 동일)
echo "$CMD" | head -1 | grep -qE '^# APPROVED([[:space:]]|$)' && exit 0

# git 토큰 자체가 없으면 즉시 통과 (저비용 단락). 따옴표·백슬래시로 쪼갠 이름(`g"i"t`·`g'i't`·`g\it`)은 셸이 벗긴 뒤 git 이 되므로,
#   따옴표·백슬래시를 뗀 사본에서도 찾는다 (2026-11-09 5단계 sec4: 단락이 쪼갠 이름을 통과시켜 뒤 규칙 전체가 안 돌았다).
echo "$CMD" | grep -q 'git' || printf '%s' "$CMD" | tr -d '"\047\134' | grep -q 'git' || exit 0

deny() {
    jq -cn --arg r "[git 차단] $1 — 사용자 직접 실행 원칙. 목적을 설명하고 승인받은 뒤 첫 줄 '# APPROVED'로 재실행하세요 (code-execution.md § Hook 차단 시 처리)." \
        '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
    exit 0
}

# 따옴표 문자열 제거 — 커밋 메시지·echo 인용문 오탐 방지 (bash-write-check와 동일 전처리)
# 2026-10-01 감사 보강 ① 공백 없는 인용(`'push'`·`"stash"`·`"."`·`"--no-verify"`·`pu"s"h`)은 셸이 따옴표를 벗긴 뒤 실행하므로
#   지우지 말고 따옴표만 벗긴다 — 통째로 지우던 전처리는 하위명령·경로를 따옴표로 감싸기만 해도 모든 규칙을 비껴갔다.
#   공백이 든 인용(커밋 메시지·echo 문장)만 종전대로 지운다. 한계: `echo "git" "push"` 처럼 낱말 둘을 따로 인용하면 오탐한다(드묾).
# ② 개행은 `;` 로 접고 나서 지운다(bash-write-check.sh 332행 방식) — sed 는 줄 단위라 여러 줄 커밋 메시지의 인용 쌍을 못 접어
#   본문 줄의 «git push» 글자가 오차단됐다. 접는 글자를 공백이 아닌 `;` 로 한 이유는 이 훅이 개행을 세그먼트 구분자로 쓰기 때문이다(`git stash list⏎git stash drop`).
# ③ 2026-10-01 P6 검수: 공백 든 인용 지우기는 왼쪽부터 짝짓는다 — 작은따옴표를 먼저 지우던 sed 는 `"it's a" && git push && echo "don't"` 의
#   아포스트로피 둘을 한 쌍으로 읽어 사이의 `git push` 까지 지웠다(큰따옴표 먼저도 대칭 구멍). 닫히지 않은 인용은 남긴다(종전 sed 와 같다).
# ④ 2026-10-01 P6 보안 재검수 H: ①의 «공백 없는 인용 벗기기» sed 가 짝짓기보다 먼저 돌아 `echo '"' ; git push ; echo '"'` 의 `'"'` 를 `"` 로 바꿔
#   남은 큰따옴표 둘이 push 를 지우는 구멍을 다시 열었다. 벗기기와 지우기를 **한 번의 왼쪽→오른쪽 주사**로 합친다: 큰따옴표 안의 `'`·작은따옴표 안의 `"` 는 문자,
#   큰따옴표 안 `\"` 는 이스케이프, 인용 밖 `\"`·`\'`(백슬래시+문자)는 따옴표가 아닌 문자, 인용 밖 낱말 머리 `#` 부터 줄 끝까지는 주석(셸이 실행하지 않는다).
#   개행은 주사 전 \001 로 바꿔 두었다가 `;` 로 접는다(주석 끝 판정에 개행이 필요하고 접힌 `;` 와 구분되어야 한다). 닫히지 않은 인용은 남긴다(종전과 같다).
# ⑤ 2026-10-02 보안 재검수 I: 주석으로 보이는 구간은 **지우지 않고 그대로 남긴다**(따옴표 해석만 끈다 — 줄 끝에서 구간 종료). 주석 판정이 틀린 경우
#   (`echo a\ #b; git push`·`${x:- #}; git push` 처럼 주석이 아닌 `#`)에도 뒤의 명령이 지워지지 않게 하려는 닫힘 방향 설계다. 그 대가로
#   `git status # git push 는 사용자 직접` 처럼 주석 속 «git push» 글자는 차단된다(오탐 허용). 주석 속 아포스트로피는 짝짓기에서 빠져 다음 줄을 삼키지 않는다.
#   `$'…'` 는 안의 `\'` 가 따옴표를 닫지 않는 ANSI-C 인용이라 별도로 읽는다(작은따옴표로 읽으면 `echo $'it\'s' ; git push ; echo $'x\''` 의 push 가 지워진다).
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
S=$(printf '%s' "$CMD" | strip_quoted)

# 명령 이름 앞 옵션 구간. 옵션과 값이 별개 토큰인 형태(`-c protocol.version=2`)까지 넘긴다.
# (2026-09-08 security 재현: `git -c protocol.version=2 push origin main` 이 통과했다)
# 값 토큰은 `-` 로 시작하지 않는 것 한 개만 허용한다. 그래서 하위 명령이 먼저 오는
# `git commit -m push` 형태는 여전히 안 잡힌다(메시지 인자 오탐 방지).
G='git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?([[:space:]]+-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+'

# 훅 경로 허용값: 하네스 자신의 훅을 가리키는 값만 허용한다.
HP_REAL="$(readlink -f "${HOME}/.claude/.git/hooks" 2>/dev/null)"
HP_OK="(${HOME}/\.claude/\.git/hooks|${HP_REAL:-${HOME}/\.claude/\.git/hooks}|~/\.claude/\.git/hooks|\\\$[{]?HOME[}]?/\.claude/\.git/hooks)/?"

# 훅 경로 키(대소문자 무시)·git 앞 경계(서브셸 `(`·경로 접두 `/usr/bin/git`) — 아래 두 함수가 함께 쓴다.
HPK='[Cc][Oo][Rr][Ee]\.[Hh][Oo][Oo][Kk][Ss][Pp][Aa][Tt][Hh]'
GITB='(^|[[:space:];|&(=])([^[:space:]]*/)?git'   # `=` : zsh `=git` (경로 펼침) 도 git 명령 낱말 (2026-11-09 r5fix 1)
# 같은 명령이 HOME 을 다시 대입하면(`export HOME=…`·`HOME=… git …`) 허용값 HP_OK 의 `~`·`$HOME` 표기가 가리키는 곳이 바뀐다 → 예외 불인정 (2026-10-17 security 3차).
HOME_REASSIGNED=""
printf '%s' "$CMD" | grep -qE '(^|[[:space:];&|(])(export[[:space:]]+)?HOME=' && HOME_REASSIGNED=1

# 커밋의 훅 건너뛰기 옵션 (2026-10-17 검수팀 보안).
#   --no-verify: git 은 모호하지 않은 접두를 받는다. 실측(git 2.34.1, 임시 저장소 + 실패하는 pre-commit): `--no-veri`·`--no-verif`·`--no-verify` 만 훅을 건너뛰고
#   `--no-ver` 이하는 `--no-verbose` 와 모호해 오류로 끝난다. 버전마다 옵션 목록이 달라질 수 있으므로 `--no-v` 이상 접두를 전부 막는다(`--no-verbose` 오탐은 감수).
#   -n: 짧은 옵션 묶음 어디에 n 이 있어도 막는다(`-nm x`·`-an`·`-nS`). 값을 받는 옵션 글자(m F C c t S u)가 먼저 나오면 그 뒤는 값이라 제외한다(`-mn` 은 메시지 «n»).
#   앞에 올 수 있는 값 없는 글자는 `git commit -h`(2.34.1)의 짧은 옵션 전체에서 값을 받는 c C F m t S u 를 뺀 a e i n o p q s v z 다(2026-10-17 대조: 이전 목록은 p 가 빠져 `-pn` 이 통과했다).
check_commit_opts() {
    local V="$1" CTX="$2"
    echo "$V" | grep -qE "${G}commit([[:space:]][^;|&]*)?[[:space:]]--no-v[a-z-]*([[:space:])=]|$)" \
        && deny "git commit --no-verify(약어 --no-v… 포함) (pre-commit·commit-msg 게이트 전면 우회 — 감사 원장에 남지 않는다)${CTX}"
    echo "$V" | grep -qE "${G}commit([[:space:]][^;|&]*)?[[:space:]]-[aeinopqsvz]*n[a-zA-Z0-9]*([[:space:])]|$)" \
        && deny "git commit -n (묶음 어디든 --no-verify 축약 — 게이트 전면 우회)${CTX}"
    return 0
}

# 브랜치 강제 삭제: -D, 그리고 삭제(-d·--delete·약어)와 강제(-f·--force·약어)의 조합을 순서·묶음과 무관하게 막는다 (-fd·-df·-d -f·--force -d·--delete --force).
# 강제 없는 -d 와 삭제 없는 -f(브랜치 강제 이동)는 통과한다.
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

# 훅·설정을 간접으로 바꾸거나 push 를 우회하는 명령 (2026-10-17 검수팀 보안). S 와 따옴표·백슬래시 제거본 양쪽에서 쓴다.
#   · `git config include.path`·`includeIf.*.path`·`-c include.path=`: 다른 파일의 core.hooksPath 를 끌어들이는 2단계 우회. 읽기·해제 형태는 통과, HP_OK 예외 없음.
#   · `git config alias.*` 설정: 셸 alias(`!…`) 로 push 를 감출 수 있다. 값이 따옴표 속이라 전처리에서 지워지므로 종류를 가리지 않고 설정 자체를 막는다(`-c alias.` 와 같은 기준).
#   · push 계열 우회: `git send-pack`·`http-push`, `git remote … push`·`git subtree … push`, `git submodule foreach …push…`.
check_extra() {
    local V="$1" CTX="$2" RD
    RD="${G}config[^;|&]*[[:space:]]--(get|get-all|get-regexp|get-urlmatch|list|unset|unset-all)([[:space:]]|$)"
    if echo "$V" | grep -qiE "${G}config([[:space:]][^;|&]*)?[[:space:]]include(if\.[^[:space:]]*)?\.path([[:space:]=]|$)"; then
        echo "$V" | grep -qE "$RD" || deny "git config include.path/includeIf (다른 파일로 core.hooksPath 를 끌어들이는 우회 — 허용 예외 없음)${CTX}"
    fi
    echo "$V" | grep -qiE "${GITB}[^;|&]*[[:space:]]-c[[:space:]]*include(if\.[^[:space:]]*)?\.path=|--config-env[[:space:]=]+include(if\.[^[:space:]]*)?\.path=" \
        && deny "git -c include.path= (다른 파일로 core.hooksPath 를 끌어들이는 우회 — 허용 예외 없음)${CTX}"
    if echo "$V" | grep -qiE "${G}config([[:space:]][^;|&]*)?[[:space:]]alias\.[^[:space:]]+"; then
        echo "$V" | grep -qE "$RD" || deny "git config alias.* (셸 alias 로 push 등 규칙 우회 — 설정 자체를 막는다. push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    fi
    echo "$V" | grep -qE "${G}(send-pack|http-push)([[:space:]]|$)" \
        && deny "git send-pack/http-push (push 우회 — push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    echo "$V" | grep -qE "${G}(remote|subtree)[[:space:]]([^;|&]*[[:space:]])?push([[:space:]]|$)" \
        && deny "git remote/subtree … push (push 우회 — push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    echo "$V" | grep -qE "${G}submodule[[:space:]]+([^;|&]*[[:space:]])?foreach[[:space:]]([^;|&]*[[:space:]])?[^[:space:]]*push" \
        && deny "git submodule foreach … push (push 우회 — push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    return 0
}

# 따옴표 «문자만» 뗀 사본·백슬래시를 뗀 사본(공백 든 따옴표 값이 전처리에서 통째로 지워지는 우회, `core.hooks\Path` 쪼개기)에서
# -c·--config-env 검사(hooksPath·alias·변수 키)를 한 번 더 한다 (2026-10-17 security 3차). 오탐을 줄이려고 `-c` 가 하위명령 앞 전역 옵션 자리에 있을 때만 본다
# (`git commit -m "fix: -c alias.x"` 는 옵션 목록이 commit 에서 끊겨 걸리지 않는다).
check_cfg_opts() {
    local V="$1" CTX="$2" GOPT
    GOPT="${GITB}([[:space:]]+-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+"
    echo "$V" | grep -qiE "${GOPT}-c[[:space:]]*alias\." \
        && deny "git -c alias.* (인라인 별칭으로 하위명령 규칙 우회)${CTX}"
    # 훅 경로 `-c` 는 정규화본에서 하위명령 위치와 무관하게 세그먼트 안 어디든 본다(8차, 과차단 허용 — 위 config 와 같은 기준).
    if echo "$V" | grep -qiE "${GITB}[^;|&]*[[:space:]]-c[[:space:]]*core\.hookspath="; then
        [ -n "$HOME_REASSIGNED" ] && deny "git -c core.hooksPath= — HOME 재대입 뒤 훅 경로 예외 불인정${CTX}"
        echo "$V" | sed -E "s#[[:space:]]-c[[:space:]]*${HPK}=${HP_OK}([[:space:]]|\$)# #g" \
            | grep -qiE "[[:space:]]-c[[:space:]]*core\.hookspath=" \
            && deny "git -c core.hooksPath= (훅 경로 바꿔치기 — 게이트 전면 우회)${CTX}"
    fi
    echo "$V" | grep -qiE -e "${GOPT}--config-env[[:space:]=]+[^[:space:]]*core\.hookspath=" \
        && deny "core.hooksPath 변형 지정(--config-env) — 값을 검증할 수 없어 차단${CTX}"
    echo "$V" | grep -qE "${GOPT}-c[[:space:]]*[^[:space:]]*\\$" \
        && deny "git -c 키에 변수 확장 — 검증 불가 (core.hooksPath 우회 가능)${CTX}"
    # 영구 설정 `git config core.hooksPath` 도 같은 사본에서 본다(6차 Codex: `core.hooks\Path` 가 통과).
    #   8차(Codex): 실행 접두(`env -u FOO`·`sudo -u x env -i` 처럼 값을 받는 래퍼 옵션)를 일일이 파싱하면 깨지므로 접두 판정을 버리고,
    #   정규화본에서는 세그먼트 안 «어디든» `git` 뒤에 `config … core.hookspath`(읽기·해제 형태가 아닌 것)가 오면 막는다.
    #   과차단 허용: 커밋 메시지에 그 글자가 들어 있어도 막힌다(사유 문구에 «정규화본 전체 기준»).
    if echo "$V" | grep -qiE "${G}config([[:space:]][^;|&]*)?[[:space:]]core\.hooksPath([[:space:]=]|$)"; then
        echo "$V" | grep -qE "${G}config[^;|&]*[[:space:]]--(get|get-all|get-regexp|get-urlmatch|list|unset|unset-all)([[:space:]]|$)" \
            || deny "git config core.hooksPath (훅 경로 영구 변경. 이후 모든 커밋에서 게이트 전면 우회 — 정규화본 전체 기준)${CTX}"
    fi
    check_extra "$V" "$CTX"
    return 0
}

# 세그먼트 하나를 모든 규칙으로 검사한다. CTX 는 셸 페이로드 재검사임을 알리는 꼬리표다.
check_git_segment() {
    local S="$1" CTX="$2"
    # 하위명령 낱말 경계에 `)` 포함(2026-10-02): `(git push)`·`$(git push)` 는 `push)` 라 공백·줄끝 경계에 안 걸렸다.
    echo "$S" | grep -qE "${G}push([[:space:])]|$)" \
        && deny "git push (push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    echo "$S" | grep -qE "${G}pull([[:space:])]|$)" \
        && deny "git pull (push/pull은 항상 사용자 직접 — agent-routing.md)${CTX}"
    echo "$S" | grep -qE "${G}reset[[:space:]][^;|&]*--hard" \
        && deny "git reset --hard (작업트리·이력 파괴)${CTX}"
    echo "$S" | grep -qE "${G}clean[[:space:]][^;|&]*-[a-zA-Z]*f" \
        && deny "git clean -f (미추적 파일 영구 삭제)${CTX}"
    # stash 는 2026-09-14 감사에서 «훅 밖이던 유일한 git 파괴 동작» 으로 지목됐다(_audit/loop-audit-20260914.md §3).
    # 인자 없는 stash 는 push 와 같고 작업트리 변경을 통째로 치운다. drop·clear 는 그 치운 것을 영구 삭제하고,
    # pop·apply 는 반대로 현재 작업트리를 덮어쓴다. 어느 쪽이든 되돌리려면 reflog 를 뒤져야 한다.
    # 조회(list·show)만 연다 — 작업트리를 건드리지 않기 때문이며, config 규칙에서 읽기 형태를 연 것과 같은 기준이다.
    if echo "$S" | grep -qE "${G}stash([[:space:])]|$)"; then
        echo "$S" | grep -qE "${G}stash[[:space:]]+(list|show)([[:space:])]|$)" \
            || deny "git stash (작업트리 변경을 치우거나 덮어씀 — push·drop·clear·pop·apply 포함. 조회는 list·show)${CTX}"
    fi
    check_branch_force "$S" "$CTX"
    echo "$S" | grep -qE "${G}(checkout|restore)[[:space:]][^;|&]*(--[[:space:]]+)?\.([[:space:])]|$)" \
        && deny "git checkout/restore . (작업트리 전체 폐기 — 경로 지정 복구는 허용)${CTX}"
    # 2026-10-01 감사: 위 규칙은 `.` 만 봐 같은 «전체 폐기»의 다른 표기를 놓쳤다. ① 저장소 루트 표기 `./`·`:/`
    #   ② 강제 전환(checkout -f·switch -f·--force·--discard-changes — 로컬 수정을 버리고 옮겨 간다)
    #   ③ 인라인 별칭(`-c alias.x=checkout x .` — 하위명령 자리가 별칭이라 위 규칙들이 못 본다. 별칭 정의 자체를 막는다. 쓸 일이 없다).
    echo "$S" | grep -qE "${G}(checkout|restore)[[:space:]]([^;|&]*[[:space:]])?(\./|:/)([[:space:])]|$)" \
        && deny "git checkout/restore ./ · :/ (작업트리 전체 폐기 — 경로 지정 복구는 허용)${CTX}"
    echo "$S" | grep -qE "${G}(checkout|switch)[[:space:]]([^;|&]*[[:space:]])?(-[a-zA-Z]*f[a-zA-Z]*|--force|--discard-changes)([[:space:])]|$)" \
        && deny "git checkout/switch -f · --force · --discard-changes (로컬 수정 폐기 강제 전환)${CTX}"
    echo "$S" | grep -qiE "(^|[[:space:];|&(])([^[:space:]]*/)?git[^;|&]*[[:space:]]-c[[:space:]]*alias\." \
        && deny "git -c alias.* (인라인 별칭으로 하위명령 규칙 우회)${CTX}"
    check_commit_opts "$S" "$CTX"
    check_extra "$S" "$CTX"

    # 훅 경로 지정: 허용값을 지운 뒤 남은 지정이 있으면 차단.
    # 지워서 판정하는 이유는 -c 를 여러 번 쓴 명령에서 나쁜 지정 하나만 섞인 경우를 놓치지 않기 위해서다.
    # 값 끝을 공백·줄끝으로 못박아 `…/hooks/../evil` 같은 접두 일치 통과를 막는다.
    # 2026-10-17 외부 검토 반례: 키 대소문자(`core.hookspath`)와 `-c` 붙여쓰기(`-cCore.hooksPath=`)가 통과했다 → 키는 대소문자 무시, `-c` 뒤 공백 0개 이상.
    #   허용값 HP_OK 는 파일시스템 경로라 대소문자를 구분해야 하므로 sed 의 I 플래그 대신 키만 문자 클래스로 푼다.
    # 앞 경계에 `(`(서브셸 `(git -c …)`)와 경로 접두(`/usr/bin/git`)를 더했다 (2026-10-17 security 재검수). HPK·GITB 는 위에서 정의한다.
    if echo "$S" | grep -qiE "${GITB}[^;|&]*[[:space:]]-c[[:space:]]*core\.hookspath="; then
        [ -n "$HOME_REASSIGNED" ] && deny "git -c core.hooksPath= — HOME 재대입 뒤 훅 경로 예외 불인정${CTX}"
        echo "$S" | sed -E "s#[[:space:]]-c[[:space:]]*${HPK}=${HP_OK}([[:space:]]|\$)# #g" \
            | grep -qiE "[[:space:]]-c[[:space:]]*core\.hookspath=" \
            && deny "git -c core.hooksPath= (훅 경로 바꿔치기 — 게이트 전면 우회)${CTX}"
    fi
    # 전역 옵션 자리의 `-c` 키/값에 변수 확장(`h=core.hooksPath; git -c $h=X commit`)이 있으면 실행 때 무엇이 될지 알 수 없다 → 차단.
    #   옵션 목록 `(-옵션 [값])*` 바로 뒤의 `-c` 만 본다: `git commit -c $SHA`(커밋 재사용 옵션)는 하위명령 뒤라 걸리지 않는다.
    if echo "$S" | grep -qE "${GITB}([[:space:]]+-[^[:space:]]+([[:space:]]+[^-[:space:]][^[:space:]]*)?)*[[:space:]]+-c[[:space:]]*[^[:space:]]*\\$" \
        || echo "$S" | grep -qiE -e "--config-env[[:space:]=]+[^[:space:]=]*\\$"; then
        deny "git -c 키에 변수 확장 — 검증 불가 (core.hooksPath 우회 가능)${CTX}"
    fi
    # 2026-10-17: 같은 우회의 변형 — `--config-env=core.hooksPath=ENV` 와 환경변수 경유(GIT_CONFIG_PARAMETERS·COUNT·KEY_n)는 값이 명령 문자열에 없어 허용값 검증이 불가능하다 → 허용 예외 없이 차단.
    if echo "$S" | grep -qiE -e "--config-env[[:space:]=]+[^[:space:]]*core\.hookspath=" \
        || { echo "$S" | grep -qiE -e "(^|[^A-Za-z0-9_])(GIT_CONFIG_PARAMETERS|GIT_CONFIG_COUNT|GIT_CONFIG_KEY_[0-9]+)=" \
            && echo "$S" | grep -qi -e "hookspath"; }; then
        deny "core.hooksPath 변형 지정(--config-env·GIT_CONFIG_*) — 값을 검증할 수 없어 차단${CTX}"
    fi

    # git config 로 훅 경로를 영구 변경하면 이후 모든 커밋에서 게이트가 죽는다 (읽기·해제 형태는 통과)
    if echo "$S" | grep -qiE "${G}config([[:space:]][^;|&]*)?[[:space:]]core\.hooksPath([[:space:]=]|$)"; then   # 키는 대소문자 무시 (2026-10-17 planner 검수)
        echo "$S" | grep -qE "${G}config[^;|&]*[[:space:]]--(get|get-all|get-regexp|get-urlmatch|list|unset|unset-all)([[:space:]]|$)" \
            || deny "git config core.hooksPath (훅 경로 영구 변경. 이후 모든 커밋에서 게이트 전면 우회)${CTX}"
    fi
    return 0
}

# 세그먼트 평가 (2026-09-14 재감사 B3·B4). 종전엔 명령 문자열 **전체**를 한 덩어리로 봐서
# 허용 예외가 다른 세그먼트의 파괴 동작까지 덮었다: `git stash list && git stash drop stash@{0}` 는
# `stash list` 매칭 하나로 통과했고(drop 단독은 차단), `git config --get core.hooksPath ; git config
# core.hooksPath /tmp/evil` 도 `--get` 하나로 통과해 이후 모든 커밋에서 훅이 죽었다.
# 그래서 `;`·`&&`·`||`·`|`·`&`·개행으로 갈라 **조각마다 독립 판정**한다 — 허용 예외는 그 조각 안에서만 산다.
# 규칙 전부를 이 경로로 옮긴다(일부만 세그먼트화하면 같은 구멍이 남는다).
# 따옴표는 이미 지운 뒤라 인용문 속 구분자는 여기 오지 않는다(`git commit -m 'a; b'` 오탐 없음).
# 백슬래시 쪼갠 이름(`g\it push`)은 strip_quoted 가 `\i` 를 그대로 둬 규칙에 안 걸리므로, 백슬래시를 뗀 사본도 같이 판정한다(sec4).
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

check_git "$S" ""

# 환경변수 경유 hooksPath 지정은 따옴표 제거 «전» 원문 세그먼트에서 본다 (2026-10-17 Codex 2차).
#   전처리(strip_quoted)가 공백 든 따옴표 문자열을 지우므로 `GIT_CONFIG_PARAMETERS="'core.hooksPath'='/dev/null' 'user.name'='x'" git commit`
#   은 값이 통째로 사라져 위 check_git 의 같은 검사를 비껴간다. 값이 무엇이든 hookspath 가 보이면 검증 불가라 차단한다.
#   세그먼트로 자르지 않고 원문 «전체 문자열»에서 본다 (Codex 3차): 따옴표 값 안의 `;`(`'user.name'='x;y' 'core.hooksPath'=…`)에서 잘려 통과했다.
#   `GIT_CONFIG_*=` 뒤 어디든 hookspath 가 있으면 막는다(과차단 허용).
check_env_raw() {
    #   4차(Codex): 따옴표 접합(`'core.hooks""Path'`)은 원문에서 낱말이 갈라져 보이므로 따옴표 문자를 뗀 전체 문자열에서도 본다.
    local v t="$1"
    #   5차(Codex): 백슬래시로 쪼갠 키(`core.hooks\Path`)는 원문·따옴표 제거본에서 낱말이 달라 보이므로 백슬래시 제거본에서도 본다(세 본 중 하나라도 걸리면 차단).
    for v in "$t" "$(printf '%s' "$t" | tr -d "\"'")" "$(printf '%s' "$t" | tr -d "\"'" | tr -d '\134')"; do
        if printf '%s' "$v" | tr '\n' ' ' | grep -qiE '(^|[^A-Za-z0-9_])(GIT_CONFIG_PARAMETERS|GIT_CONFIG_COUNT|GIT_CONFIG_KEY_[0-9]+)=.*hookspath'; then
            deny "core.hooksPath 변형 지정(GIT_CONFIG_*) — 환경 변수 값은 쪼개 검사할 수 없어 원문·따옴표 제거본 전체 기준으로 차단${2:-}"
        fi
        # 2026-10-17 검수팀 보안: 설정 파일·저장소 위치를 바꾸는 환경변수(전역·시스템 설정 파일 교체, 다른 .git 지정)는 그 안의 core.hooksPath 를 검사할 수 없다.
        # 명령 어디든(`env` 경유·앞선 export 포함) 있으면 막는다. 허용 예외(HP_OK) 없음, 과차단 허용.
        # 17차: 옵션형(`--git-dir=`·`--work-tree=`, 값이 따로 오는 형태 포함)도 같은 효과라 같이 막는다.
        if printf '%s' "$v" | grep -qE '(^|[^A-Za-z0-9_])(GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM|GIT_DIR|GIT_COMMON_DIR)=|(^|[[:space:]])--(git-dir|work-tree)([=[:space:]]|$)'; then
            deny "git 설정 파일·저장소 위치 지정(환경변수 GIT_CONFIG_GLOBAL·GIT_CONFIG_SYSTEM·GIT_DIR·GIT_COMMON_DIR, 옵션 --git-dir·--work-tree) — 그 안의 core.hooksPath 를 검사할 수 없어 차단${2:-}"
        fi
    done
}

# ANSI-C 인용 `$'…'` 은 키·값을 이스케이프(`$'core.hooks\x50ath'`)로 감출 수 있고 이 훅은 해석하지 않는다 → git 이 든 세그먼트에 있으면 차단 (2026-10-17 Codex 6차).
# 세그먼트 단위로 보는 이유는 무관한 명령의 `$'` 까지 막지 않으려는 것이다. 커밋 메시지 인자의 `$'a'` 도 걸리지만 사유 문구로 알린다(과차단 허용).
check_ansi_c() {
    local seg
    while IFS= read -r seg; do
        if grep -qF "\$'" <<< "$seg" && grep -qiE '(^|[^A-Za-z0-9_])git([^A-Za-z0-9_]|$)|GIT_CONFIG_' <<< "$seg"; then
            deny "ANSI-C 인용(\$'…')은 해석하지 않아 차단 — git 명령 세그먼트에서는 \$'…' 를 쓰지 않는다${2:-}"
        fi
    done <<< "$(printf '%s' "$1" | sed -E 's/[;&|]/\n/g')"
}

# 원문 텍스트 하나에 대한 «원문 기준» 검사 묶음: GIT_CONFIG_* 세 본, ANSI-C 인용, 그리고 따옴표 문자만 뗀 사본·백슬래시도 뗀 사본에서의
# -c·--config-env·영구 설정 검사(check_cfg_opts). 셸 `-c` 페이로드에도 같은 묶음을 한 단계 적용한다 (8차 Codex).
check_raw_all() {
    local uq bs v seg
    check_env_raw "$1" "$2"
    check_ansi_c "$1" "$2"
    uq=$(printf '%s' "$1" | tr '\n' ';' | tr -d "\"'")
    bs=$(printf '%s' "$uq" | tr -d '\134')   # 8진수 134 = 백슬래시
    for v in "$uq" "$bs"; do
        while IFS= read -r seg; do
            [ -n "${seg//[[:space:]]/}" ] || continue
            check_cfg_opts "$seg" "${2:- — 따옴표·백슬래시 제거본}"
            # 커밋 옵션(--no-verify 약어·-n 묶음)은 백슬래시로 쪼갠 경우(`--no-ver\ify`)만 정규화본에서 본다. 따옴표만 뗀 사본에서 보면 커밋 메시지 속 «--no-verify» 글자까지 막힌다.
            [ "$v" = "$bs" ] && [ "$bs" != "$uq" ] && check_commit_opts "$seg" "${2:- — 백슬래시 제거본}"
        done <<< "$(printf '%s' "$v" | sed -E 's/[;&|]/\n/g')"
    done
}
check_raw_all "$CMD" ""

# 셸 `-c` 페이로드 재검사 (bash-write-check.sh 의 2단계 재검사 이식).
# 인용 페이로드만 꺼내 겉따옴표를 벗기고 같은 전처리를 다시 돌린다. 그래서 페이로드 안의
# 커밋 메시지(`bash -c 'git commit -m "docs: git push"'`)는 여전히 지워져 오탐이 나지 않는다.
# 파이프 대신 here-string 을 쓰는 이유는 while 이 서브셸로 떨어지면 deny 의 종료가 본체에 안 닿기 때문이다.
SHC_RE="(^|[[:space:];&|(])([^[:space:]]*/)?(r?ba|z|da|k)?sh([[:space:]]+-[^[:space:]]+)*[[:space:]]+-c[[:space:]]+('[^']*'|\"[^\"]*\")"
PAYLOADS=$(printf '%s\n' "$CMD" | grep -oE "$SHC_RE" | sed -E "s/^[^'\"]*//")
while IFS= read -r payload; do
    [ -n "$payload" ] || continue
    P=$(printf '%s' "$payload" | sed -E "s/^(['\"])(.*)\1\$/\2/" | strip_quoted)
    check_git "$P" " — 셸 -c 페이로드 안"
    check_raw_all "$(printf '%s' "$payload" | sed -E "s/^(['\"])(.*)\1\$/\2/")" " — 셸 -c 페이로드 안(원문 기준)"
done <<< "$PAYLOADS"

# 확장 검사 (2026-11-09 5단계): 기존 검사를 모두 통과한 명령만 넘긴다. 실행 실패는 막는 방향이다.
EXT_OUT=$(printf '%s' "$INPUT" | python3 -I "$(dirname "$(readlink -f "$0")")/git_guard_ext.py"); EXT_RC=$?
[ -n "$EXT_OUT" ] && { printf '%s\n' "$EXT_OUT"; exit 0; }
[ "$EXT_RC" -ne 0 ] && deny "확장 검사(git_guard_ext.py) 실행 실패 — 판정할 수 없어 차단"

exit 0
