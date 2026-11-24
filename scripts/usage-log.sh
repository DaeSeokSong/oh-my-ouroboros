#!/usr/bin/env bash
# usage-log.sh — 하네스 사용 기록기(intent/2026-11-24-harness-review-six-items.md 개정 2 W14). 정본 설명: rules-lazy/harness-logs.md
# 사용법: settings 의 PostToolUse · PostToolUseFailure · InstructionsLoaded · SubagentStop · SessionStart · SessionEnd · PreCompact ·
#   PostCompact 에 matcher 없이 `bash $HOME/.claude/scripts/usage-log.sh`. 설치 · 되돌리기: scripts/hook_deny_wrap_install.py
#   hook-deny-wrap.sh 로 감싸지 않는다(자기 실행 줄을 스스로 쓴다).
# 종료 코드: 언제나 0. stdout · stderr 에 아무것도 내지 않는다.
# 쓰는 파일: ~/.claude/_usage/<폴더>/YYYY-MM-DD.tsv, 머리 줄 없음, 모드 600(umask 077), 한 줄 = 덧붙이기 한 번, 4KB 미만.
#   tool-use       time · session8 · caller · tool · ok · ms        PostToolUse ok=1, PostToolUseFailure ok=0, ms = 입력의 duration_ms
#   rule-reads     time · session8 · caller · how · path           how = read(PostToolUse 의 Read) | loaded:<load_reason>(InstructionsLoaded)
#                  path = 실제 경로로 푼 뒤 하네스 뿌리(~/.claude 를 푼 경로) 기준 상대 경로. rules · rules-lazy · skills · agents ·
#                  knowledge · doc-formats 아래와 CLAUDE.md 만, 그 밖(하네스 뿌리 밖 포함)은 남기지 않는다.
#   agent-runs     launch: time · session8 · caller · launch · agent_id · subagent_type · model 인자 · effort 인자 · name 인자(1|0)
#                  (PostToolUse 의 Agent · Task, jq 로 읽는다. jq 가 없으면 쓰지 않는다)
#                  stop: usage_log_agent.py 가 쓴다(SubagentStop, 칸은 그 파일 머리).
#   session-events time · session8 · kind · model                  kind = start:<source> | end:<reason> | precompact:<trigger> |
#                                                                   postcompact:<trigger>, model 은 SessionStart 입력에 있을 때만
#   hook-runs      이 기록기 자신의 실행 한 줄(hook-deny-wrap.sh 와 같은 칸, hook = usage-log, rc 0 · pass)
#   caller = 공통 칸 agent_id 앞 8자, 없으면 main. 이름 칸은 [A-Za-z0-9_.:-] 만 남기고 자른다. 빈 칸은 -.
# 싣지 않는 것: tool_input · tool_response 내용(Read 의 file_path 는 위 조건을 통과한 상대 경로만, Agent 는 위 네 칸만), 프롬프트,
#   error, last_assistant_message(usage_log_agent.py 가 정해진 상태 낱말만 꺼낸다), compact_summary, custom_instructions, cwd,
#   transcript_path, 세션 id 전체, 하네스 밖 경로.
# 칸을 찾는 법: 입력 앞 4KB 에서 bash 정규식(통과 경로에 jq · python 없음). session_id · agent_id 는 "hook_event_name" 앞의 공통 칸에서만,
#   나머지는 그 뒤에서 찾는다. duration_ms 는 입력 끝 1KB 에서 «duration_ms 뒤에 mcp_server 만 오고 객체가 닫히는» 꼴만 읽는다.
#   file_path 에 JSON 이스케이프(역슬래시)가 있으면 jq 로 다시 읽고, jq 가 없으면 남기지 않는다.
# 기록 자리가 일반 파일이 아니거나(링크 · FIFO · 폴더) 하드링크 수가 1 이 아니면 쓰지 않는다(확인과 덧붙이기 사이에 바뀌는 경합은 막지 못한다).
# 한계: 1) 실행 전에 거절된 도구 호출(스키마 검증 · 권한 거부)은 PostToolUse · PostToolUseFailure 가 뜨지 않아 tool-use 에 없다.
#   2) 칸 이름은 공식 훅 문서와 이 서버의 Claude Code 2.1.323 실행 파일 문자열에서 확인했다. 판이 바뀌어 칸이 없어지면 그 칸은 - 다.
#   3) 입력 앞 4KB 안에 칸이 없으면(아주 긴 앞쪽 칸) 그 칸은 - 다. hook_event_name 이 앞 4KB 안에 없으면 그 이벤트의 줄
#   (tool-use · rule-reads · agent-runs · session-events)을 쓰지 않고 자기 hook-runs 줄만 event - 로 쓴다.
#   무결성: 같은 사용자가 고칠 수 있는 기록이다(위조 불가 증거 아님).

{ set +euxvfC +o pipefail; shopt -u failglob nullglob nocaseglob nocasematch; } 2>/dev/null

field() {
    local re="\"$1\"[[:space:]]*:[[:space:]]*\"([^\"]*)\""
    REPLY=''
    [[ $2 =~ $re ]] && REPLY=${BASH_REMATCH[1]}
}

clean() {
    REPLY=${1//[^A-Za-z0-9_.:-]/}
    REPLY=${REPLY:0:$2}
}

append() {
    local d="$BASE/$1" f n
    if [ ! -d "$d" ] || [ -L "$d" ]; then
        [ -e "$d" ] || [ -L "$d" ] || mkdir -p -- "$d" || return
        [ -d "$d" ] && [ ! -L "$d" ] || return
    fi
    f="$d/$DAY.tsv"
    if [ -e "$f" ] || [ -L "$f" ]; then
        [ -f "$f" ] && [ ! -L "$f" ] || return
        n=$(stat -c %h -- "$f") && [ "$n" = 1 ] || return
    fi
    printf '%s\n' "${2:0:4000}" >> "$f"
}

rule_line() {
    local p root dir base rel
    field file_path "$REST"
    p=$REPLY
    if [[ $p == *\\* ]]; then
        command -v jq >/dev/null 2>&1 || return
        p=$(printf '%s' "$IN" | jq -r 'if .hook_event_name == "InstructionsLoaded" then .file_path else .tool_input.file_path end
            | strings') || return
    fi
    [[ $p == /* ]] || return
    cd -P -- "$HOME/.claude" 2>/dev/null || return
    root=$PWD
    if [ -L "$p" ]; then
        p=$(readlink -f -- "$p") || return
        [[ $p == /* ]] || return
    fi
    base=${p##*/}
    dir=${p%/*}
    case $base in '' | . | ..) return ;; esac
    cd -P -- "${dir:-/}" 2>/dev/null || return
    rel=${PWD%/}/$base
    rel=${rel#"$root"/}
    case $rel in
        rules/* | rules-lazy/* | skills/* | agents/* | knowledge/* | doc-formats/* | CLAUDE.md) ;;
        *) return ;;
    esac
    rel=${rel//[[:cntrl:]]/}
    append rule-reads "$NOW"$'\t'"$S8"$'\t'"$CALLER"$'\t'"$1"$'\t'"${rel:0:1024}"
}

agent_launch() {
    local j aid st mo ef nm
    command -v jq >/dev/null 2>&1 || return
    j=$(printf '%s' "$IN" | jq -r '[((.tool_response | objects | (.agentId // .agent_id)) // ""),
            ((.tool_input | objects | .subagent_type) // ""), ((.tool_input | objects | .model) // ""),
            ((.tool_input | objects | .effort) // ""),
            (if (.tool_input | type) == "object" and (.tool_input | has("name")) then "1" else "0" end)]
        | map(tostring | gsub("[^A-Za-z0-9_.:-]"; "") | .[0:64] | if . == "" then "-" else . end) | join("\t")') || return
    IFS=$'\t' read -r aid st mo ef nm <<< "$j"
    [ -n "$nm" ] || return
    append agent-runs "$NOW"$'\t'"$S8"$'\t'"$CALLER"$'\tlaunch\t'"$aid"$'\t'"$st"$'\t'"$mo"$'\t'"$ef"$'\t'"$nm"
}

tool_line() {
    local ok=1 tail=$IN re ms=''
    [ "$EV" = PostToolUseFailure ] && ok=0
    field tool_name "$REST"
    clean "$REPLY" 128
    TOOL=$REPLY
    [ "${#IN}" -gt 1024 ] && tail=${IN: -1024}
    re='"duration_ms"[[:space:]]*:[[:space:]]*([0-9]{1,12})[[:space:]]*(,[[:space:]]*"mcp_server"[[:space:]]*:[[:space:]]*"[^"]*"[[:space:]]*)?\}[[:space:]]*$'
    [[ $tail =~ $re ]] && ms=${BASH_REMATCH[1]}
    append tool-use "$NOW"$'\t'"$S8"$'\t'"$CALLER"$'\t'"${TOOL:--}"$'\t'"$ok"$'\t'"${ms:--}"
    [ "$ok" = 1 ] || return
    case $TOOL in
        Read) rule_line read ;;
        Agent | Task) agent_launch ;;
    esac
}

session_line() {
    local kind model=''
    field "$2" "$REST"
    clean "$REPLY" 40
    kind=$REPLY
    if [ "$EV" = SessionStart ]; then
        field model "$REST"
        clean "$REPLY" 128
        model=$REPLY
    fi
    append session-events "$NOW"$'\t'"$S8"$'\t'"$1:${kind:--}"$'\t'"${model:--}"
}

main() {
    local LC_ALL=C T0=${EPOCHREALTIME//[!0-9]/} IN='' HEAD PRE REST BASE DAY NOW S8 CALLER EV TOOL='' SELF ms='' t1
    umask 077
    SELF=${BASH_SOURCE[0]}
    if [[ $SELF == */* ]]; then SELF=${SELF%/*}; else SELF=.; fi
    [[ $SELF == /* ]] || SELF=$PWD/$SELF
    { IN=$(cat); } 2>/dev/null
    HEAD=${IN:0:4096}
    PRE=${HEAD%%\"hook_event_name\"*}
    REST=${HEAD:${#PRE}}
    [[ $HOME == /* ]] && [ -d "$HOME/.claude" ] || return
    BASE="$HOME/.claude/_usage"
    printf -v DAY '%(%Y-%m-%d)T' -1
    printf -v NOW '%(%Y-%m-%dT%H:%M:%S%z)T' -1
    field session_id "$PRE"
    clean "$REPLY" 8
    S8=${REPLY:--}
    field agent_id "$PRE"
    clean "$REPLY" 8
    CALLER=${REPLY:-main}
    field hook_event_name "$REST"
    clean "$REPLY" 40
    EV=$REPLY
    case $EV in
        PostToolUse | PostToolUseFailure) tool_line ;;
        InstructionsLoaded)
            field load_reason "$REST"
            clean "$REPLY" 40
            rule_line "loaded:${REPLY:--}"
            ;;
        SubagentStop)
            command -v python3 >/dev/null 2>&1 \
                && printf '%s' "$IN" | python3 -I "$SELF/usage_log_agent.py" "$S8" "$CALLER"
            ;;
        SessionStart) session_line start source ;;
        SessionEnd) session_line end reason ;;
        PreCompact) session_line precompact trigger ;;
        PostCompact) session_line postcompact trigger ;;
    esac
    # NEVER: an arithmetic expansion error exits a non-interactive bash; check digits before $(( )).
    t1=${EPOCHREALTIME//[!0-9]/}
    [[ $T0 =~ ^[0-9]{1,20}$ && $t1 =~ ^[0-9]{1,20}$ ]] && ms=$(( (10#$t1 - 10#$T0) / 1000 ))
    printf -v NOW '%(%Y-%m-%dT%H:%M:%S%z)T' -1
    append hook-runs "$NOW"$'\t'"$S8"$'\t'"$CALLER"$'\t'"${EV:--}"$'\tusage-log\t'"${TOOL:--}"$'\t0\tpass\t'"${ms:--}"
}

main "$@" > /dev/null 2>&1
exit 0
