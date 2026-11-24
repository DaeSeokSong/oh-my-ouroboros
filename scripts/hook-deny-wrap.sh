#!/usr/bin/env bash
# hook-deny-wrap.sh — PreToolUse 차단 훅을 감싸 차단을 기록하고, 같은 훅에 연속 3회 막히면 거부 사유에 [반복 차단] 문구를 붙인다.
#   intent/2026-11-24-harness-review-six-items.md 개정 1 W9. 설치 · 되돌리기: scripts/hook_deny_wrap_install.py
# 사용법: hook-deny-wrap.sh <훅 이름> -- <명령> [인자…]
#         hook-deny-wrap.sh --ping   → «hook-deny-wrap ok» 한 줄, exit 0, stdin 은 읽지 않는다(settings 가드용).
#         hook-deny-wrap.sh --log-only <훅 이름> -- <명령> [인자…]   (개정 2 W14, 차단 훅이 아닌 나머지 command 훅)
#           stdin 만 메모리로 받아 파이프로 넘기고 stdout · stderr 는 잡지 않고 그대로 물려준다(백그라운드 자식을 남기는 훅이 있어
#           기다리지 않는다). 종료 코드를 그대로 낸다. 출력을 고치지 않고 [반복 차단] 문구 · hook-deny.tsv · 계수를 쓰지 않는다.
# 실행 기록(W14, 두 방식 모두): ~/.claude/_usage/hook-runs/YYYY-MM-DD.tsv 에 실행마다 한 줄, 머리 줄 없음, 모드 600(umask 077).
#   칸: time · session8 · caller · event · hook · tool · rc · verdict · ms. verdict = pass | deny | error | killed.
#   기존 방식은 위 거부 판정(종료 코드 2 · JSON 꼴)이면 deny, rc 0 이면 pass, 그 밖은 error. --log-only 는 종료 코드만 본다
#   (0 pass · 2 deny · 그 밖 error). 이름 칸은 [A-Za-z0-9_.:-] 만 남기고 자른다. session_id · agent_id 는 입력 앞 4KB 에서
#   "hook_event_name" 앞쪽(공통 칸)에서만 찾는다(도구 입력 속 agent_id 를 호출 주체로 잡지 않게). 시각은 bash 의 printf %()T 와
#   EPOCHREALTIME 이라 기록 경로에 새 프로세스가 없다(폴더가 없을 때의 mkdir 한 번만). 기록 실패는 건너뛴다.
#   감싸는 쪽이 TERM · INT · HUP 을 받으면 verdict killed · rc 128+n 으로 한 줄 남기고 같은 신호로 스스로 끝난다.
#   settings 에는 설치 도구가 «이 파일에 --ping 을 물어 정해진 글이 돌아오면 감싸고, 아니면 원래 명령을 그대로» 꼴로 넣는다
#   (3차 B1: bash -n 은 빈 파일 · 셔뱅만 · 끝줄이 잘린 파일을 통과시켜 원래 훅이 0회 돌았다).
#   본문은 main(){ … }; main "$@"; exit 꼴이다: bash 가 함수 전체를 먼저 읽으므로 실행 중 제자리 수정에 덜 흔들리고,
#   끝줄이 없으면 --ping 도 답하지 못한다.
#
# ★불변식: 감싼 훅의 판정을 절대 바꾸지 않는다. 통과를 거부로, 거부를 통과로 바꾸는 경로가 없다.
#   감싸는 쪽의 어떤 실패(jq 없음 · 기록 폴더 쓰기 실패 · 임시 파일 실패 · 디스크 가득 · 잠금 대기 초과 · HOME 없음)에서도
#   감싼 훅의 stdout · stderr · 종료 코드를 그대로 낸다.
#   stdin · stdout · stderr 는 임시 파일에 두지 않고 메모리(bash 변수)로 받는다(2차 F1 · F3: 디스크가 가득 차거나 임시 폴더가
#   지워져도 감싼 훅은 온전한 입력을 받고, 그 판정 출력이 잘리지 않는다). stdin 은 파이프로 넘긴다. 임시 파일을 쓰는 곳은
#   판정 뒤의 기록 · 계수뿐이다(실패하면 건너뛴다).
#   후처리는 stdout · stderr 를 /dev/null 로 돌린 함수(post) 안에서만 돌고 아무것도 내보내지 않는다. 내보내기는 맨 끝 한 곳이다.
#   문구 덧붙이기는 «거부이고 계수가 3 이상이고 덧붙이기가 성공할 때» 만 한다(실패하면 원래 출력).
#   감싼 명령보다 먼저는 환경을 바꾸지 않는다(umask · LC_ALL 은 명령이 끝난 뒤 post 안에서만).
# 거부 판정 세 꼴(공식 훅 문서 2026-11-24): 1) 종료 코드 2(사유 = stderr) 2) stdout 이 JSON 객체 하나이고
#   hookSpecificOutput.permissionDecision == "deny" 3) 옛 꼴 최상위 decision == "block"(사유 = reason).
#   JSON 꼴은 종료 코드와 무관하게 센다. 공식 문서 «Exit code output» 표(https://code.claude.com/docs/en/hooks, 2026-11-24
#   조회): 유효한 JSON 은 종료 코드 0 이면 칸이 적용되고, 2 면 차단이되 칸도 읽으며, 그 밖이면 종료 코드를 무시하고 칸만으로
#   판정한다. 무효 JSON 은 0 · 그 밖에서 비차단 오류이고 2 에서는 stderr 가 사유다.
#   종료 코드 2 와 차단 JSON 이 함께면 stderr 와 JSON 사유 양쪽에 붙인다(어느 쪽이 사유로 쓰이든 보이게).
#   stdout 앞 64KB 에 deny · block 낱말이 없으면 jq 를 띄우지 않는다(통과 경로를 가볍게).
#   JSON 꼴은 jq 판정 뒤 python3 의 표준 JSON 검사(NaN · Infinity 거부)도 통과해야 센다(3차 N4: jq 1.6 은 NaN 을 받아 주므로
#   Claude Code 가 무효로 볼 출력을 거부로 세고 다시 쓸 수 있었다). python3 이 없으면 JSON 꼴은 세지 않는다.
# 기록: ~/.claude/_audit/hook-deny.tsv — time · session(8자) · caller · hook · tool · streak. tool_input 내용은 싣지 않는다
#   (명령 · 경로에 시크릿이 있을 수 있다). 모드 600, 2MB 를 넘으면 뒤쪽 절반만(_audit/.hook-deny.* 임시 → mv).
#   잠금 hook-deny.tsv.lock 은 flock -w 0.5 이고, 못 잡으면 기록 · 계수를 건너뛴다(flock 이 없으면 잠금 없이).
#   계수: ~/.claude/_cache/hook-deny/<세션 8자>.<호출 주체>.<훅 이름>. 호출 주체 = agent_id 앞 8자, 없으면 main.
#   계수 파일은 같은 폴더의 .tmp.* 에 쓴 뒤 mv 한다. 이름은 [A-Za-z0-9_.-] 만 남긴다. 세션이나 훅 이름이 비면 기록만 하고
#   세지 않는다(streak 0). 잠금 · 기록 자리가 일반 파일이 아니면(링크 · FIFO · 폴더 · 소켓 · 장치) 기록 · 계수를 건너뛴다.
#   기록 · 계수 · .pruned 파일의 하드링크 수가 1 이 아니면 그 파일에 쓰지 않는다(계수 파일이면 세지 않는다).
#   계수 · .pruned · 새 기록 파일은 같은 폴더의 mktemp(모드 600) 뒤 mv 로 쓴다. 기록 덧붙이기 직전에 다시 확인한다.
#   계수 폴더는 하루 1회 7일 지난 일반 파일을 지운다.
# 세션 id 는 입력 앞 4KB 에서 "session_id" 의 첫 일치를 bash 정규식으로 뽑는다(통과 경로에서 jq 를 안 띄우려고). 두 경로가
#   같은 방법을 써야 계수 파일 이름이 맞는다. caller · tool 은 jq 로 최상위 칸을 읽고, jq 가 없으면 앞 4KB 정규식으로 대신한다.
# 왜 통과하면 계수를 되돌리나: «연속» 차단만 헛도는 재시도의 신호다. 그 훅을 통과한 호출이 사이에 있으면 모델이 다른
#   일을 하고 있거나 고쳐 쓴 호출이 통과한 것이라 처음부터 다시 센다(의뢰서 개정 1 전제). 되돌리기 = 계수 파일 삭제.
# 한계: 1) 관계없는 통과 호출(같은 훅을 통과한 다른 일)이 사이에 끼면 계수가 되돌아가 문구가 늦게 붙거나 안 붙는다.
#   2) 같은 이벤트의 훅은 병렬로 돌아 서로의 결정을 모른다. 다른 훅의 거부는 이 훅의 계수에 들어가지 않고, 다른 훅이
#   거부한 호출을 이 훅이 통과시켰으면 이 훅의 계수는 되돌아간다.
#   3) bash 변수는 NUL 바이트를 못 담는다. 입력에 NUL 이 있으면 감싼 훅이 받는 stdin 이 달라지고, 감싼 훅의 stdout · stderr 에
#   NUL 이 있으면 NUL 이 빠진 채 나간다(실제 훅 입력은 JSON 이고, 감싸는 11개 훅의 stdout 은 JSON 이거나 비어 있고 stderr 는
#   사유 글이라 NUL 이 없다). bash 의 «ignored null byte» 경고는 stderr 로 새지 않게 버린다.
#   4) session_id 는 앞 4KB 의 첫 일치라, Claude Code 가 session_id 를 맨 앞에 두지 않고 그 앞의 칸에 같은 글자가 있으면
#   다른 값을 세션으로 잡는다(계수 이름만 틀리고 판정은 그대로다). 4KB 안에 없으면 세지 않는다.
#   5) 감싼 훅의 stdin · stdout · stderr 는 Claude Code 와 이어진 파이프가 아니라 이 스크립트의 파이프다(내용은 같다).
#   감싼 훅이 끝난 뒤에도 그 자식이 stderr 에 쓰면 꼬리(길이 · 종료 코드)를 못 읽어 비차단 오류(1)로 끝난다(판정이 바뀔 수
#   있다. 감싸는 11개 훅은 자식을 남기지 않는다).
#   6) 잠금 · 기록 자리 확인과 덧붙이기(>>) 사이, 또는 기록 회전 확인과 tail 사이에 그 자리가 FIFO 로 바뀌면 그 열기가 막힐 수
#   있다(같은 사용자의 경합만 가능). 계수 · .pruned 읽기는 <> 열기와 read -t 로 막히지 않는다.
#   7) 신호로 죽은 훅은 감싸면 종료 코드 128+n 으로 나오고 셸이 찍는 «Terminated» 류 한 줄이 빠진다(어느 쪽이든 0 도 2 도 아니다).
#   --log-only 에서는 출력을 잡지 않으므로 감싸는 bash 가 찍는 «Terminated» 류 한 줄이 stderr 로 나간다.
#   8) 상속된 셸 옵션(SHELLOPTS · BASHOPTS 를 export 한 errexit · nounset · pipefail · xtrace · failglob 등)은 이 스크립트 안에서
#   끈다. 감싼 훅에는 원래 값을 env 로 넘긴다(첫 인자에 '=' 가 있거나 env 가 없으면 넘기지 못한다). verbose 는 끄기 전에 읽은
#   줄이 stderr 로 새는 것을 막지 못한다.
#   9) --log-only 는 출력을 잡지 않으므로 JSON 꼴 판정(permissionDecision · decision)을 보지 못한다. verdict 는 종료 코드만이다.
#   10) killed 는 신호를 받았다는 뜻일 뿐 시간 초과와 사용자 취소를 가르지 못한다. KILL 로 죽으면 기록이 없다. 신호가 감싸는
#   쪽에만 오고 감싼 훅에는 안 오면 bash 가 훅이 끝날 때까지 trap 을 미루므로 그때 남는다. 기존 방식에서 killed 이면 감싼 훅의
#   출력은 내보내지 않는다(신호로 죽은 훅과 같이 판정 없음).
#   11) hook-runs 기록 자리는 링크 · FIFO · 폴더이면 쓰지 않지만 하드링크 수는 보지 않는다(stat 프로세스를 통과 경로에 두지 않으려고).
#   usage-log.sh 는 하드링크 수까지 본다.
#   무결성: agent-spawn-log.sh 와 같이 신뢰 경계 밖의 기록이다(위조 불가 증거 아님).
# REF: knowledge/harness/code-history/scripts__hook-deny-wrap.sh.md

# WHY: 상속된 셸 옵션이 판정을 바꾸지 않게 맨 먼저 끈다(errexit 이면 post 의 실패가 exit 2 를 rc 1 로 바꿨다). xtrace 출력이
# stderr 에 섞이지 않게 묶음 전체를 /dev/null 로 돌린다. main 이 아니라 여기서 하는 까닭: 아래 대입부터 xtrace 에 찍힌다.
{
    HDW_SO='' HDW_BO=''
    [[ ${SHELLOPTS@a} == *x* ]] && HDW_SO=$SHELLOPTS
    [[ ${BASHOPTS@a} == *x* ]] && HDW_BO=$BASHOPTS
    set +euxvfC +o pipefail
    shopt -u failglob nullglob nocaseglob nocasematch
} 2>/dev/null

MAX=2097152
HEADER=$'time\tsession\tcaller\thook\ttool\tstreak'

ident() {
    local a='' t='' j re
    if command -v jq >/dev/null 2>&1; then
        j=$(printf '%s' "$IN" | jq -r '[(.agent_id, .tool_name) | (. // "" | tostring | gsub("[^A-Za-z0-9_.-]"; ""))] | join("\t")') \
            || j=$'\t'
        a=${j%%$'\t'*}
        t=${j#*$'\t'}
    else
        re='"agent_id"[[:space:]]*:[[:space:]]*"([^"]*)"'
        [[ $HEAD =~ $re ]] && a=${BASH_REMATCH[1]}
        re='"tool_name"[[:space:]]*:[[:space:]]*"([^"]*)"'
        [[ $HEAD =~ $re ]] && t=${BASH_REMATCH[1]}
    fi
    a=${a//[^A-Za-z0-9_.-]/}
    t=${t//[^A-Za-z0-9_.-]/}
    CALLER=${a:0:8}
    TOOL=${t:0:80}
    : "${CALLER:=main}" "${TOOL:=-}"
}

one_link() {
    [ ! -e "$1" ] && [ ! -L "$1" ] && return 0
    [ -f "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %h -- "$1")" = 1 ]
}

regular_or_absent() {
    if [ -e "$1" ] || [ -L "$1" ]; then [ -f "$1" ] && [ ! -L "$1" ]; fi
}

# WHY: standard JSON only (rejects NaN · Infinity that jq 1.6 accepts), so a deny that Claude Code would reject as
# invalid JSON is never counted or rewritten.
STRICT='import json, sys
def r(c): raise ValueError(c)
json.loads(sys.stdin.buffer.read().decode("utf-8"), parse_constant=r)'

post() {
    local LC_ALL=C
    local hook s8='' re ohead deny=0 json=0 f any='' cdir audit log cf n streak=0 now tmp last='' mark today msg x
    [ -n "$NOCOUNT" ] && return
    hook=${HOOK_RAW//[^A-Za-z0-9_.-]/}
    hook=${hook:0:64}
    HEAD=${IN:0:4096}
    re='"session_id"[[:space:]]*:[[:space:]]*"([^"]*)"'
    if [[ $HEAD =~ $re ]]; then
        s8=${BASH_REMATCH[1]//[^A-Za-z0-9_.-]/}
        s8=${s8:0:8}
    fi
    [ "$RC" -eq 2 ] && deny=1
    ohead=${OUT:0:65536}
    if [[ $ohead == *deny* || $ohead == *block* ]] && command -v jq >/dev/null 2>&1 \
        && printf '%s' "$OUT" | jq -e -s 'length == 1 and (.[0] | type == "object" and
             ([.hookSpecificOutput | objects | .permissionDecision] == ["deny"] or .decision == "block"))' >/dev/null \
        && printf '%s' "$OUT" | python3 -I -c "$STRICT"; then
        deny=1
        json=1
    fi
    DENY=$deny
    [[ $HOME == /* ]] && [ -d "$HOME/.claude" ] || return
    cdir="$HOME/.claude/_cache/hook-deny"

    if [ "$deny" -eq 0 ]; then
        [ -n "$s8" ] && [ -n "$hook" ] || return
        for f in "$cdir/$s8".*."$hook"; do [ -e "$f" ] && { any=1; break; }; done
        [ -n "$any" ] || return
        ident
        cf="$cdir/$s8.$CALLER.$hook"
        [ -f "$cf" ] && [ ! -L "$cf" ] && rm -f -- "$cf"
        return
    fi

    ident
    umask 077
    audit="$HOME/.claude/_audit"
    log="$audit/hook-deny.tsv"
    [ -d "$audit" ] || mkdir -p -- "$audit" || return
    [ -d "$audit" ] && [ ! -L "$audit" ] || return
    # NEVER: 잠금 · 기록 자리에 FIFO · 폴더 · 소켓 · 장치 · 링크가 있으면 열지 않는다(FIFO 열기는 끝없이 막힌다). 잠금은 <> 로 연다:
    # 확인 뒤 FIFO 로 바뀌어도 읽기 · 쓰기 열기는 막히지 않는다.
    regular_or_absent "$log.lock" && regular_or_absent "$log" || return
    {
        if command -v flock >/dev/null 2>&1; then flock -w 0.5 9 || return; fi
        if [ -n "$s8" ] && [ -n "$hook" ]; then
            [ -d "$cdir" ] || mkdir -p -- "$cdir"
            if [ -d "$cdir" ] && [ ! -L "$cdir" ]; then
                cf="$cdir/$s8.$CALLER.$hook"
                if one_link "$cf"; then
                    n=0
                    [ -f "$cf" ] && IFS= read -t 0.2 -r n <> "$cf"
                    [[ $n =~ ^[0-9]{1,6}$ ]] || n=0
                    n=$((10#$n + 1))
                    tmp=$(mktemp "$cdir/.tmp.XXXXXX")
                    if [ -n "$tmp" ]; then
                        if printf '%s\n' "$n" > "$tmp" && mv -f -- "$tmp" "$cf"; then streak=$n; else rm -f -- "$tmp"; fi
                    fi
                fi
                mark="$cdir/.pruned"
                printf -v today '%(%Y-%m-%d)T' -1
                if one_link "$mark"; then
                    [ -f "$mark" ] && IFS= read -t 0.2 -r last <> "$mark"
                    if [ "$last" != "$today" ]; then
                        find "$cdir" -mindepth 1 -maxdepth 1 -type f -mmin +10080 ! -name .pruned -delete
                        tmp=$(mktemp "$cdir/.tmp.XXXXXX")
                        if [ -n "$tmp" ]; then
                            if printf '%s\n' "$today" > "$tmp" && mv -f -- "$tmp" "$mark"; then :; else rm -f -- "$tmp"; fi
                        fi
                    fi
                fi
            fi
        fi
        if one_link "$log"; then
            if [ ! -e "$log" ]; then
                tmp=$(mktemp "$audit/.hook-deny.XXXXXX")
                if [ -n "$tmp" ]; then
                    printf '%s\n' "$HEADER" > "$tmp" && mv -n -- "$tmp" "$log"
                    rm -f -- "$tmp"
                fi
            elif [ "$(stat -c %s -- "$log")" -gt "$MAX" ]; then
                tmp=$(mktemp "$audit/.hook-deny.XXXXXX")
                if [ -n "$tmp" ] && [ -f "$log" ] && [ ! -L "$log" ]; then
                    { printf '%s\n' "$HEADER"; tail -c "$((MAX / 2))" -- "$log" | tail -n +2; } > "$tmp"
                    # NEVER: 머리줄만 든 임시 파일(읽기 오류 등)로 원본을 덮지 않는다.
                    if [ "$(stat -c %s -- "$tmp")" -gt "$((${#HEADER} + 1))" ]; then mv -f -- "$tmp" "$log"; else rm -f -- "$tmp"; fi
                elif [ -n "$tmp" ]; then
                    rm -f -- "$tmp"
                fi
            fi
            if [ -f "$log" ] && one_link "$log"; then
                printf -v now '%(%Y-%m-%dT%H:%M:%S%z)T' -1
                printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$now" "${s8:--}" "$CALLER" "${hook:--}" "$TOOL" "$streak" >> "$log"
            fi
        fi
    } 9<> "$log.lock"

    [ "$streak" -ge 3 ] || return
    msg="[반복 차단] 같은 훅(${hook})에 연속 ${streak}회 막혔습니다. 다른 방법으로 돌아가려 하지 말고 무엇을 하려 했는지와 차단 문구를 사용자에게 그대로 보고하십시오(rules-lazy/error-handling.md 도구 차단)."
    if [ "$json" -eq 1 ]; then
        if x=$(printf '%s' "$OUT" | jq -c -s --arg m "$msg" '
                def app: if type == "string" then . + "\n" + $m elif type == "null" then $m else . end;
                .[0]
                | if (.hookSpecificOutput | type) == "object" and .hookSpecificOutput.permissionDecision == "deny"
                  then .hookSpecificOutput.permissionDecisionReason |= app else . end
                | if .decision == "block" then .reason |= app else . end') && [ -n "$x" ]; then
            NEWOUT="$x"$'\n'
        fi
    fi
    if [ "$RC" -eq 2 ]; then
        if [ -n "$ERR" ] && [ "${ERR: -1}" != $'\n' ]; then ERR_SUFFIX=$'\n'"$msg"$'\n'; else ERR_SUFFIX="$msg"$'\n'; fi
    fi
}

runlog() {
    local LC_ALL=C re head pre s8='' caller='' ev='' tool='' hook verdict ms='' t1 d f day now line
    LOGGED=1
    head=${IN:0:4096}
    pre=${head%%\"hook_event_name\"*}
    re='"session_id"[[:space:]]*:[[:space:]]*"([^"]*)"'
    [[ $pre =~ $re ]] && s8=${BASH_REMATCH[1]//[^A-Za-z0-9_.:-]/}
    re='"agent_id"[[:space:]]*:[[:space:]]*"([^"]*)"'
    [[ $pre =~ $re ]] && caller=${BASH_REMATCH[1]//[^A-Za-z0-9_.:-]/}
    re='"hook_event_name"[[:space:]]*:[[:space:]]*"([^"]*)"'
    [[ $head =~ $re ]] && ev=${BASH_REMATCH[1]//[^A-Za-z0-9_.:-]/}
    re='"tool_name"[[:space:]]*:[[:space:]]*"([^"]*)"'
    [[ ${head:${#pre}} =~ $re ]] && tool=${BASH_REMATCH[1]//[^A-Za-z0-9_.:-]/}
    hook=${HOOK_RAW//[^A-Za-z0-9_.:-]/}
    if [ -n "$VERDICT" ]; then verdict=$VERDICT
    elif [ "$DENY" = 1 ] || [ "$RC" = 2 ]; then verdict=deny
    elif [ "$RC" = 0 ]; then verdict=pass
    else verdict=error; fi
    # NEVER: an arithmetic expansion error exits a non-interactive bash, which would drop the hook's output; check digits first.
    t1=${EPOCHREALTIME//[!0-9]/}
    [[ $T0 =~ ^[0-9]{1,20}$ && $t1 =~ ^[0-9]{1,20}$ ]] && ms=$(( (10#$t1 - 10#$T0) / 1000 ))
    [[ $HOME == /* ]] && [ -d "$HOME/.claude" ] || return
    umask 077
    d="$HOME/.claude/_usage/hook-runs"
    if [ ! -d "$d" ] || [ -L "$d" ]; then
        [ -e "$d" ] || [ -L "$d" ] || mkdir -p -- "$d" || return
        [ -d "$d" ] && [ ! -L "$d" ] || return
    fi
    printf -v day '%(%Y-%m-%d)T' -1
    f="$d/$day.tsv"
    if [ -e "$f" ] || [ -L "$f" ]; then [ -f "$f" ] && [ ! -L "$f" ] || return; fi
    printf -v now '%(%Y-%m-%dT%H:%M:%S%z)T' -1
    s8=${s8:0:8} caller=${caller:0:8} ev=${ev:0:40} hook=${hook:0:64} tool=${tool:0:128}
    printf -v line '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s' "$now" "${s8:--}" "${caller:-main}" "${ev:--}" "${hook:--}" \
        "${tool:--}" "$RC" "$verdict" "${ms:--}"
    printf '%s\n' "$line" >> "$f"
}

# shellcheck disable=SC2329
on_sig() {
    [ -n "$LOGGED" ] || { RC=$((128 + $2)); VERDICT=killed; runlog > /dev/null 2>&1; }
    trap - HUP INT TERM
    kill -s "$1" "$$"
    exit "$((128 + $2))"
}

# WHY: LC_ALL=C is local so the hook started later keeps the caller's locale (L3: UTF-8 made 18MB take 2 s).
read_in() {
    local LC_ALL=C
    { IN=$(cat && printf y || printf n); } 2>/dev/null
    [ "${IN: -1}" = y ] || NOCOUNT=1
    IN=${IN%?}
}

main() {
    local HOOK_RAW i a IN='' ALL OUT ERR RC=1 TRAIL OUTLEN NOCOUNT='' NEWOUT='' ERR_SUFFIX='' HEAD='' CALLER='' TOOL='' PRE=()
    local T0=${EPOCHREALTIME//[!0-9]/} LOGONLY='' DENY=0 VERDICT='' LOGGED=''
    if [ "$#" -eq 1 ] && [ "$1" = "--ping" ]; then
        printf 'hook-deny-wrap ok\n'
        return 0
    fi
    if [ "$#" -ge 4 ] && [ "$1" = "--log-only" ] && [ "$3" = "--" ]; then
        LOGONLY=1
        HOOK_RAW=$2
        shift 3
    elif [ "$#" -ge 3 ] && [ "$2" = "--" ]; then
        HOOK_RAW=$1
        shift 2
    else
        # NEVER: 사용 오류로 감싼 명령을 막지 않는다. '--' 뒤에 명령이 있으면 감싸지 않고 그대로 실행한다(판정 보존 우선).
        i=0
        for a in "$@"; do
            i=$((i + 1))
            if [ "$a" = "--" ]; then
                shift "$i"
                [ "$#" -ge 1 ] && exec "$@"
                break
            fi
        done
        echo "hook-deny-wrap: 사용법: hook-deny-wrap.sh <훅 이름> -- <명령> [인자…] (감싸지 않고 통과)" >&2
        return 0
    fi
    command -v cat >/dev/null 2>&1 || exec "$@"
    trap 'on_sig HUP 1' HUP
    trap 'on_sig INT 2' INT
    trap 'on_sig TERM 15' TERM

    # NEVER: 앞쪽 패턴 제거(${x#*…} · ${x##*…})를 쓰지 않는다. 길이의 제곱으로 느려진다.
    # stdin 끝에 y · n 한 글자를 붙였다 떼어 끝 개행을 보존하고 읽기 실패를 안다.
    read_in
    if [ -n "$HDW_SO$HDW_BO" ] && [[ $1 != *=* ]] && command -v env >/dev/null 2>&1; then
        PRE=(env)
        [ -n "$HDW_SO" ] && PRE+=("SHELLOPTS=$HDW_SO")
        [ -n "$HDW_BO" ] && PRE+=("BASHOPTS=$HDW_BO")
    fi

    if [ -n "$LOGONLY" ]; then
        # WHY: graphify-commit-refresh.sh · graphify-autoindex.sh · claude-notify.sh leave background children holding
        # stdout · stderr (W14 scout 2026-11-24); capturing them would block until those children exit (limit 5 above).
        printf '%s' "$IN" 2>/dev/null | "${PRE[@]}" "$@"
        RC=${PIPESTATUS[1]}
        runlog > /dev/null 2> /dev/null
        return "$RC"
    fi

    # WHY: 임시 파일 없이 바깥 명령 치환이 «stderr 바이트 + stdout 바이트 + stdout 길이 10자리 + 종료 코드 3자리» 를 받는다. 안쪽 치환이 stdout 을
    #   받는 동안 훅의 stderr 는 fd 4(= 바깥 치환 파이프)로 바로 흐르고, 훅이 끝난 뒤에야 stdout 과 꼬리를 쓰므로 섞이지 않는다.
    #   가르는 자리는 꼬리의 길이로 구한다(3차 B2: 위치 찾기 없이 선형). 길이 · 자르기는 LC_ALL=C 의 바이트 단위다.
    #   안쪽 서브셸이 종료 코드를 쓰기 전에 죽으면 꼬리를 일부러 무효로 써서 아래 대체 경로(rc 1)로 보낸다(L2: 000 → rc 0 이었다).
    { ALL=$( { OUT=$(printf '%s' "$IN" 2>/dev/null | "${PRE[@]}" "$@" 2>&4 4>&-; printf ' %s' "${PIPESTATUS[1]}"); } 4>&1
             LC_ALL=C
             RC=$OUT
             OUT=${OUT% *}
             RC=${RC:${#OUT}+1}
             if [[ $RC =~ ^[0-9]{1,3}$ ]]; then printf '%s%010d%03d' "$OUT" "${#OUT}" "$RC"
             else printf '%s?????????????' "$OUT"; fi ); } 2>/dev/null
    local LC_ALL=C
    TRAIL=${ALL: -13}
    ALL=${ALL%?????????????}
    if [[ $TRAIL =~ ^[0-9]{13}$ ]] && OUTLEN=$((10#${TRAIL:0:10})) && [ "$OUTLEN" -le "${#ALL}" ]; then
        RC=$((10#${TRAIL:10:3}))
        OUT=${ALL:$((${#ALL} - OUTLEN))}
        ERR=${ALL:0:$((${#ALL} - OUTLEN))}
    else
        # WHY: 꼬리를 못 읽으면(서브셸을 못 띄움 등) 판정을 알 수 없어 받은 것을 stderr 로 내고 비차단 오류(1)로 끝낸다.
        RC=1 OUT='' ERR=$ALL NOCOUNT=1
    fi

    { post; runlog; } > /dev/null 2> /dev/null

    # NEVER: 감싸는 모드에서는 여기 밖에서 출력하지 않는다(유일한 출력 지점). 감싼 훅의 stdout · stderr 그대로, 덧붙일 때만 바뀐 사본 · 꼬리 한 줄.
    if [ -n "$NEWOUT" ]; then printf '%s' "$NEWOUT"; else printf '%s' "$OUT"; fi
    printf '%s%s' "$ERR" "$ERR_SUFFIX" >&2
    return "$RC"
}

main "$@"; exit
