#!/usr/bin/env bash
# agent-spawn-log.sh — Agent 도구 소집을 1줄씩 기록한다. (2026-08-25 신설, v2)
#   PreToolUse(Agent)  → `pre`  : 소집 시도 (분모에 넣지 않음 — 실패한 시도도 여기 남는다)
#   PostToolUse(Agent) → `post` : 소집 완료 (agent-eval §1.5 분모의 정본은 이 `post` 줄)
#
# 왜: agent-eval "동일 약점 N회"의 분모(에이전트별 소집 횟수)를 셀 소스가 없었다
#     (_audit/history.md는 서술형, _evolve/prompts.jsonl은 사용자 프롬프트만 — 2라운드 검수 실측).
#     3라운드 검수: PreToolUse 만 세면 실패한 시도까지 분모에 들어가고 teammate 의 name 이 빠진다 → post 결합·name 기록.
# 형식: TSV — ts \t phase(pre|post) \t subagent_type \t name \t model \t description(80자). 전 필드 탭·개행 살균.
# 무결성 (정직 표기 — 4라운드 검수로 재기술): 이 로그는 **신뢰 경계 밖**이다. bash-write-check.sh 는 `>`·`>>`·인라인
#   인터프리터 쓰기·이 스크립트의 직접 호출을 차단해 문턱을 올릴 뿐, 인터프리터는 무한하고 훅은 Bash 도구 호출만 본다.
#   따라서 분모(agent-eval §1.5)는 "훅이 남긴 기록"이지 위조 불가 증거가 아니며, 감사 판정은 이 로그 단독이 아니라
#   세션 transcript(`~/.claude/projects/*/*.jsonl` — jobs/*/timeline.jsonl 은 상태 로그라 대상 아님)·git 이력과 교차해 내린다. 파싱·쓰기 실패는 $LOG.invalid 에 남긴다(조용히 삼키지 않음). 차단하지 않는다(exit 0 고정).
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

# T41 자동 기록 (2026-09-14 신설) — 왜: agent-eval 의 "실패·재작업 신호 → T41" 이 main 의 의무
#   문장뿐이라 post 652건 동안 T41 0건이었다(09-14 감사 §2-5). 실패 신호는 소집 결과 문자열에
#   이미 들어 있으므로 같은 훅에서 t41-append.sh(유일 쓰기 경로)로 넘긴다. 성공 소집엔 아무것도 하지 않는다.
#   판정은 표면형 매칭이라 오탐이 있을 수 있다 — 기록은 후보이고 약점 확정은 여전히 사람·모델 몫이다.
#
# ★오탐 2건 교정 (2026-09-14 당일, 검수 실사고):
#   ① **비동기 소집의 즉시 응답을 결과로 오판**. 비동기 Agent 소집의 PostToolUse tool_response 는
#      «Async agent launched …» 류 안내이고 여기에 **보낸 프롬프트 원문이 그대로 실려 온다**. 그래서
#      «RESULT: FAIL 이면 …» 같은 지시문이 들어간 검수 의뢰가 자기 프롬프트를 실패 신호로 기록했다
#      (검수용 qa 소집이 자기 프롬프트로 T41 을 낳음). 비동기 응답이면 판정 자체를 건너뛴다 —
#      그 소집의 진짜 결과는 SubagentStop 훅(scripts/t41-subagent-stop.sh)이 잡는다.
#   ② **느슨한 한국어 단어**. 종전의 `실패|재작업|반려`·`FAIL\b` 는 «실패 스위트: 0»·«반려 없음»
#      같은 성공 문장에도 맞았다. 신호를 **행 앞에 고정된 강형 표기**로만 좁힌다(아래 T41_RX).
#   ③ **동기 완료 결과의 agentId 오판** (2026-09-26). 비동기 판별은 세 문구만 본다 — 동기 완료
#      결과 끝에도 «agentId: … (use SendMessage …)» 메타가 붙으므로(09-26 실측 동기 250건) agentId:
#      는 판별에 쓰지 않는다.
#   ※ 같은 정규식이 t41-subagent-stop.sh 에도 있다(동기·비동기 두 경로). 고칠 땐 두 곳을 함께 고친다.
if [ "$PHASE" = "post" ]; then
    # tool_response 는 문자열일 수도 객체일 수도 있다(에이전트 반환 형식이 고정 아님).
    # 객체는 tostring(한 줄 JSON) 대신 **내부 문자열만 한 줄씩** 뽑는다 — 행 고정 정규식이 성립하려면
    # 줄바꿈이 살아 있어야 하는데 tostring 은 개행을 `\n` 리터럴로 만들어 모든 매칭을 죽인다.
    RESP=$(printf '%s' "$INPUT" | jq -r '.tool_response | if type == "string" then . else (.. | strings) end' 2>/dev/null)
    ASYNC_RX='Async agent launched|Spawned successfully|The agent is now running'
    T41_RX='^[[:space:]]*(RESULT|STATUS|status|판정)[[:space:]]*[:=][[:space:]]*(FAIL|BLOCKED|NEEDS_CONTEXT|REJECT)\b|^[[:space:]]*(FAIL|BLOCKED|NEEDS_CONTEXT)\b'
    if [ -n "$RESP" ] && ! printf '%s\n' "$RESP" | grep -qE "$ASYNC_RX"; then
        # t41-subagent-stop.sh 와 같은 판정(2026-10-01 P6 검수): 마지막 `RESULT:` 줄이 있으면 그 줄만 본다(DONE·PASS 면 본문 행두 «FAIL»은 신호 아님).
        # RESULT 줄이 없는 응답만 전체를 보되 «FAIL 0건»·«FAIL: 없음» 같은 0건 보고는 신호에서 뺀다.
        RESULT_LINE=$(printf '%s\n' "$RESP" | LC_ALL=C.utf8 grep -E '^[[:space:]]*RESULT[[:space:]]*[:=]' | tail -1)
        if [ -n "$RESULT_LINE" ]; then
            SIGNAL=$(printf '%s\n' "$RESULT_LINE" | LC_ALL=C.utf8 grep -E "$T41_RX" | head -1 | san 80)
        else
            SIGNAL=$(printf '%s\n' "$RESP" | LC_ALL=C.utf8 grep -E "$T41_RX" \
                | LC_ALL=C.utf8 grep -v -E '(FAIL|BLOCKED|NEEDS_CONTEXT|REJECT)[[:space:]]*[:=]?[[:space:]]*(0|없음|none|zero)([^0-9A-Za-z]|$)' | head -1 | san 80)
        fi
        # san() 이 jq 출력의 끝 개행까지 공백으로 바꾸므로 TYPE 은 "coder " 꼴이다. 로그 형식은 그대로 두고
        # 역할 이름만 다듬어 넘긴다 — 안 다듬으면 t41-append 의 agents/<role>.md 검증이 전부 실패한다.
        ROLE_T=$(printf '%s' "$TYPE" | sed 's/[[:space:]]*$//')
        # 판정할 정보 (2026-11-12): RESULT 줄 한 줄만으로는 무엇을 하던 소집이 누구의 FAIL 인지 알 수 없어 판정이 불가했다.
        #   신호를 `<소집 설명 앞 40자> | from=<원 역할> | <RESULT 줄>` 꼴로 넘긴다(설명이 비면 앞 칸 생략). 40자는 jq 문자 단위 절단이다.
        #   t41-append.sh 는 «from=… | » 뒤만 귀속·10분 중복 키에 쓰고, 설명은 history·후보 요약에만 남긴다.
        # --from 자동 모드 — 약점 주체·차원 매핑은 t41-append.sh 한 곳에만 둔다(두 훅 공용).
        # stderr 는 막지 않는다: 기록 실패를 삼키면 «T41 0건»의 원인이 또 안 보인다.
        # 설명·RESULT 줄은 추적 파일 history.md 로 가므로 비동기 경로와 같은 가림(scripts/t41-mask.sh 의 mask_cut)을 거친다(2026-11-12 검수).
        # shellcheck source=/dev/null
        if [ -n "$SIGNAL" ] && [ -n "$ROLE_T" ] && . "$HOME/.claude/scripts/t41-mask.sh" 2>/dev/null; then
            SIGNAL=$(printf '%s' "$SIGNAL" | mask_cut 80)
            DESC40=$(printf '%s' "$INPUT" | jq -r '.tool_input.description // ""' 2>/dev/null | mask_cut 40 | sed 's/[[:space:]]*$//')
            [ -n "$SIGNAL" ] && bash "$HOME/.claude/scripts/t41-append.sh" --from "$ROLE_T" --signal "${DESC40:+$DESC40 | }from=$ROLE_T | $SIGNAL" >/dev/null
        fi
    fi
fi
exit 0
