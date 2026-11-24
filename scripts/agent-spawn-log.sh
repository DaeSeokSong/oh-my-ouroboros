#!/usr/bin/env bash
# agent-spawn-log.sh — Agent 도구 소집을 1줄씩 기록한다.
#   PreToolUse(Agent)  → `pre`  : 소집 시도 (분모에 넣지 않음 — 실패한 시도도 여기 남는다)
#   PostToolUse(Agent) → `post` : 소집 완료 (agent-eval §1.5 분모의 정본은 이 `post` 줄)
# 형식: TSV — ts \t phase(pre|post) \t subagent_type \t name \t model \t description(80자). 전 필드 탭·개행 살균.
# 쓰는 파일: ~/.claude/_audit/agent-spawn.log(파싱·쓰기 실패는 $LOG.invalid). 차단하지 않는다(exit 0 고정).
#   pre: 지시문 본문을 가려 _audit/agent-prompts/<YYYYMMDD>/<HHMMSS.나노초.PID>-<세션 8자>-<타입>.txt 에 새 파일로 남긴다(폴더 700 · 파일 600,
#     intent/2026-11-24-harness-review-six-items.md W4). 가린 본문이 204,800 바이트를 넘으면 앞부분만 남긴다(바이트 절단이라 마지막 글자가 깨질 수 있다).
#     하루 1회 30일보다 오래된 날짜 폴더를 지운다. 실패는 조용히 무시한다.
#   post: 소집 결과의 실패 신호를 t41-append.sh 로 넘긴다(기록은 후보이고 약점 확정은 사람·모델 몫이다).
# 무결성: 이 로그는 신뢰 경계 밖이다. 분모는 "훅이 남긴 기록"이지 위조 불가 증거가 아니며, 감사 판정은 세션 transcript · git 이력과 교차해 내린다.
# REF: knowledge/harness/code-history/scripts__agent-spawn-log.sh.md
PHASE="${1:-pre}"
LOG="$HOME/.claude/_audit/agent-spawn.log"
INPUT=$(cat)
san() { tr '\t\n\r' '   ' | cut -c1-"$1"; }
TYPE=$(printf '%s' "$INPUT" | jq -r '.tool_input.subagent_type // "general-purpose"' 2>/dev/null | san 40)
NAME=$(printf '%s' "$INPUT" | jq -r '.tool_input.name // "-"' 2>/dev/null | san 40)
MODEL=$(printf '%s' "$INPUT" | jq -r '.tool_input.model // "inherit"' 2>/dev/null | san 20)
DESC=$(printf '%s' "$INPUT" | jq -r '.tool_input.description // ""' 2>/dev/null | san 80)
mkdir -p "$(dirname "$LOG")" 2>/dev/null
if [ -z "$TYPE" ]; then
    printf '%s\t%s\tparse-fail\n' "$(date -Is)" "$PHASE" >> "$LOG.invalid" 2>/dev/null
    exit 0
fi
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -Is)" "$PHASE" "$TYPE" "$NAME" "$MODEL" "$DESC" >> "$LOG" 2>/dev/null \
    || printf '%s\t%s\twrite-fail\n' "$(date -Is)" "$PHASE" >> "$LOG.invalid" 2>/dev/null

# WHY: 지시문은 mask_cut 이 놓치는 흔한 꼴이 많아(키=값 · JWT · URL 자격증명 · PEM 등, 2026-11-24 security 재현) 이 추가 가림을 한 번 더 거친다.
#   stdin 은 줄바꿈이 \036 으로 바뀐 한 줄이다. 가림 규칙 · 과잉 가림 · 놓치는 꼴은 파일 머리 REF 노트에 있다.
# REF: knowledge/harness/code-todo.md CT-002
# WHY: 키 앞뒤와 scheme 반복을 {0,40} · {0,20} 으로 묶었다. 묶지 않으면 긴 영숫자 줄에서 제곱 시간이 되어 훅 시간 제한(5초)을 넘는다.
#   LC_ALL=C 로 바이트 단위로 돈다(한글 바이트는 ASCII 클래스에 안 맞는다).
# NEVER: AWS secret 을 맨 40자 꼴로 잡지 않는다. 파일 경로와 겹친다(키 문맥 aws_secret_access_key=… 으로만 잡는다).
mask_prompt_extra() {
    local R=$'\036' V K SEP
    V="[^[:space:]\"'$R]"
    K="[A-Za-z0-9_]{0,40}(pass(word|wd|phrase)?|pwd|secret|token|api[_ -]?key|access[_-]?key|private[_-]?key|credential|auth|cookie|session(id)?|sid)[A-Za-z0-9_]{0,40}"
    SEP="[\"']?[[:space:]]*[:=][[:space:]]*"
    LC_ALL=C sed -E \
        -e "s#-----BEGIN ([A-Z0-9 ]+)-----[^-]*-----END ([A-Z0-9 ]+)-----#-----BEGIN \1-----<masked>-----END \2-----#g" \
        -e "s#(-----BEGIN [A-Z0-9 ]+-----)[A-Za-z0-9+/=${R}[:space:]]{16,}#\1<masked>#g" \
        -e "s#(Authorization[[:space:]]*:[[:space:]]*)[^$R]+#\1<masked>#Ig" \
        -e "s#(Bearer|Basic)([[:space:]]+)$V+#\1\2<masked>#Ig" \
        -e "s#([A-Za-z][A-Za-z0-9+.-]{0,20}://)[^/@[:space:]\"'$R]+@#\1<masked>@#g" \
        -e "s#eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+#<masked>#g" \
        -e "s#(hooks\.slack\.com/services/)[A-Za-z0-9/_-]+#\1<masked>#g" \
        -e "s#(^|[^A-Za-z0-9])(hf_[A-Za-z0-9]{8,}|glpat-[A-Za-z0-9_-]{8,}|npm_[A-Za-z0-9]{16,}|sk_(live|test)_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9_-]{6,}|xox[abprs]-[A-Za-z0-9-]{8,}|AKIA[A-Z0-9]{12,})#\1<masked>#g" \
        -e "s#(--(token|password|passwd|secret|api-key)[[:space:]]+)$V+#\1<masked>#Ig" \
        -e "s#((^|[[:space:]])(-u|--user)[[:space:]]+)[^[:space:]\"':$R]+:$V+#\1<masked>#g" \
        -e "s#(^|[^A-Za-z0-9_])($K$SEP)\"[^\"$R]*\"#\1\2\"<masked>\"#Ig" \
        -e "s#(^|[^A-Za-z0-9_])($K$SEP)'[^'$R]*'#\1\2'<masked>'#Ig" \
        -e "s#(^|[^A-Za-z0-9_])($K${SEP}[\"']?)$V+#\1\2<masked>#Ig" \
        -e "s#(^|[^A-Za-z0-9_])(pw${SEP}[\"']?)$V+#\1\2<masked>#Ig" \
        -e "s#(^|[^A-Za-z0-9_])(($K|pw)[[:space:]]*:[[:space:]]*${R}[[:space:]]*)$V+#\1\2<masked>#Ig"
}
log_prompt() {
    local root="$HOME/.claude/_audit/agent-prompts" today p sid typ dir f body bytes cutoff d n
    [ -L "$root" ] && return 0
    mkdir -m 700 "$root" 2>/dev/null
    [ -d "$root" ] && [ ! -L "$root" ] || return 0
    # NEVER: 가림 함수를 못 읽으면 본문을 남기지 않는다(가리지 않은 원문은 쓰지 않는다).
    # shellcheck source=/dev/null
    . "$HOME/.claude/scripts/t41-mask.sh" 2>/dev/null && command -v jq >/dev/null 2>&1 || return 0
    today=$(date +%Y%m%d)
    p="$root/.last-prune"
    # NEVER: .last-prune 이 링크이거나 일반 파일이 아니면 읽지 않는다. FIFO 등에서 훅이 멈춘다.
    if [ ! -L "$p" ] && { [ ! -e "$p" ] || [ -f "$p" ]; } && [ "$(head -c 16 "$p" 2>/dev/null)" != "$today" ]; then
        ( umask 077; printf '%s\n' "$today" > "$p" ) 2>/dev/null
        cutoff=$(date -d '30 days ago' +%Y%m%d 2>/dev/null)
        for d in "$root"/*; do
            n=${d##*/}
            [[ "$n" =~ ^[0-9]{8}$ ]] && [ -n "$cutoff" ] && [ ! -L "$d" ] && [ -d "$d" ] && [ "$n" -lt "$cutoff" ] \
                && rm -rf -- "$d" 2>/dev/null
        done
    fi
    sid=$(printf '%s' "$INPUT" | jq -r '.session_id // ""' 2>/dev/null | LC_ALL=C tr -cd 'A-Za-z0-9_.:-' | cut -c1-8)
    typ=$(printf '%s' "$INPUT" | jq -r '.tool_input.subagent_type // "general-purpose"' 2>/dev/null \
        | LC_ALL=C tr -cd 'A-Za-z0-9_.:-' | cut -c1-40)
    dir="$root/$today"
    [ -L "$dir" ] && return 0
    mkdir -m 700 "$dir" 2>/dev/null
    [ -d "$dir" ] && [ ! -L "$dir" ] || return 0
    # WHY: 시각 칸에 PID 를 붙인다. 같은 나노초 · 세션 · 타입의 동시 호출이면 noclobber 가 둘째 기록을 버린다(2026-11-24 security 지적).
    f="$dir/$(date +%H%M%S.%N).$$-${sid:-nosess}-${typ:-unknown}.txt"
    # WHY: mask_cut 은 줄바꿈을 공백으로 바꾸므로 줄바꿈을 \036 으로 감싸 넘기고 되돌린다(scripts/t41-mask.sh).
    # NEVER: 자른 뒤에 가리지 않는다. 먼저 자르면 반쯤 잘린 토큰이 가림을 피한다.
    body=$(printf '%s' "$INPUT" | jq -r '.tool_input.prompt // ""' 2>/dev/null | tr '\n' '\036' | mask_cut 1000000 \
        | mask_prompt_extra | tr '\036' '\n')
    bytes=$(printf '%s' "$body" | LC_ALL=C wc -c)
    if [ "$bytes" -gt 204800 ]; then
        body="$(printf '%s' "$body" | head -c 204800)
[truncated: 가린 본문 ${bytes} 바이트 가운데 앞 204800 바이트만 남김]"
    fi
    ( umask 077; set -C; printf '%s\n' "$body" > "$f" ) 2>/dev/null
    return 0
}
[ "$PHASE" = "pre" ] && log_prompt

# WHY: 실패·재작업 신호 → T41 이 main 의 의무 문장뿐이라 post 652건 동안 T41 0건이었다(09-14 감사 §2-5).
#   신호는 행 앞에 고정된 강형 표기로만 본다. 느슨한 한국어 단어는 «실패 스위트: 0» 같은 성공 문장에도 맞았다(2026-09-14).
# NEVER: 비동기 소집의 즉시 응답을 판정하지 않는다. 보낸 프롬프트 원문이 실려 와 검수 의뢰가 자기 프롬프트를 실패 신호로 기록했다
#   (2026-09-14 검수 실사고). 그 소집의 진짜 결과는 scripts/t41-subagent-stop.sh 가 잡는다.
# NEVER: agentId: 를 비동기 판별에 쓰지 않는다. 동기 완료 결과 끝에도 붙는다(09-26 실측 동기 250건).
# NEVER: 정규식을 이 파일에서만 고치지 않는다. t41-subagent-stop.sh 에 같은 정규식이 있다.
if [ "$PHASE" = "post" ]; then
    # NEVER: 객체 tool_response 를 tostring 으로 펴지 않는다. 개행이 `\n` 리터럴이 되어 행 고정 정규식 매칭이 모두 죽는다.
    RESP=$(printf '%s' "$INPUT" | jq -r '.tool_response | if type == "string" then . else (.. | strings) end' 2>/dev/null)
    ASYNC_RX='Async agent launched|Spawned successfully|The agent is now running'
    T41_RX='^[[:space:]]*(RESULT|STATUS|status|판정)[[:space:]]*[:=][[:space:]]*(FAIL|BLOCKED|NEEDS_CONTEXT|REJECT)\b|^[[:space:]]*(FAIL|BLOCKED|NEEDS_CONTEXT)\b'
    if [ -n "$RESP" ] && ! printf '%s\n' "$RESP" | grep -qE "$ASYNC_RX"; then
        # WHY: t41-subagent-stop.sh 와 같은 판정이다(2026-10-01 P6 검수). 마지막 RESULT 줄이 DONE·PASS 면 본문 행두 «FAIL»은 신호가 아니고,
        # «FAIL 0건»·«FAIL: 없음» 같은 0건 보고는 신호에서 뺀다.
        RESULT_LINE=$(printf '%s\n' "$RESP" | LC_ALL=C.utf8 grep -E '^[[:space:]]*RESULT[[:space:]]*[:=]' | tail -1)
        if [ -n "$RESULT_LINE" ]; then
            SIGNAL=$(printf '%s\n' "$RESULT_LINE" | LC_ALL=C.utf8 grep -E "$T41_RX" | head -1 | san 80)
        else
            SIGNAL=$(printf '%s\n' "$RESP" | LC_ALL=C.utf8 grep -E "$T41_RX" \
                | LC_ALL=C.utf8 grep -v -E '(FAIL|BLOCKED|NEEDS_CONTEXT|REJECT)[[:space:]]*[:=]?[[:space:]]*(0|없음|none|zero)([^0-9A-Za-z]|$)' | head -1 | san 80)
        fi
        # WHY: san() 이 jq 출력의 끝 개행까지 공백으로 바꾸므로 TYPE 은 "coder " 꼴이다. 안 다듬으면
        # scripts/t41-append.sh 의 agents/<role>.md 검증이 전부 실패한다.
        ROLE_T=$(printf '%s' "$TYPE" | sed 's/[[:space:]]*$//')
        # WHY: RESULT 줄 한 줄만으로는 누구의 FAIL 인지 알 수 없어 `<소집 설명 앞 40자> | from=<원 역할> | <RESULT 줄>` 꼴로 넘긴다(2026-11-12).
        #   설명·RESULT 줄은 추적 파일 history.md 로 가므로 scripts/t41-mask.sh 의 mask_cut 을 거친다(2026-11-12 검수).
        # NEVER: stderr 를 막지 않는다. 기록 실패를 삼키면 «T41 0건»의 원인이 또 안 보인다.
        # shellcheck source=/dev/null
        if [ -n "$SIGNAL" ] && [ -n "$ROLE_T" ] && . "$HOME/.claude/scripts/t41-mask.sh" 2>/dev/null; then
            SIGNAL=$(printf '%s' "$SIGNAL" | mask_cut 80)
            DESC40=$(printf '%s' "$INPUT" | jq -r '.tool_input.description // ""' 2>/dev/null | mask_cut 40 | sed 's/[[:space:]]*$//')
            # WHY: 응답의 agentId 와 `<세션>/subagents/agent-<id>.jsonl` 파일 이름이 같다(2026-11-16 실측).
            #   id 는 영숫자만 받아 경로 조립에 `/`·`..` 이 끼지 않게 한다. 접두 · 링크 검사는 t41-ledger.sh 가 한다.
            STP=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
            SID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
            AID=$(printf '%s' "$INPUT" | jq -r '.tool_response | objects | .agentId // empty' 2>/dev/null)
            [ -n "$AID" ] || AID=$(printf '%s\n' "$RESP" | grep -oE 'agentId: [A-Za-z0-9]+' | tail -1 | cut -d' ' -f2)
            RTP=""
            case "$AID" in ''|*[!A-Za-z0-9]*) ;; *) case "$STP" in *.jsonl) RTP="${STP%.jsonl}/subagents/agent-${AID}.jsonl" ;; esac ;; esac
            [ -n "$SIGNAL" ] && T41_REPORTER_TP="$RTP" T41_SESSION_ID="$SID" T41_PATH_KIND=sync \
                bash "$HOME/.claude/scripts/t41-append.sh" --from "$ROLE_T" --signal "${DESC40:+$DESC40 | }from=$ROLE_T | $SIGNAL" >/dev/null
        fi
    fi
fi
exit 0
