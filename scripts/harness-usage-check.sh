#!/usr/bin/env bash
# harness-usage-check.sh — "구축됐지만 사용 안 되는" 인프라 감지 (T03 세션 시작 시 1회 호출)
#
# 설계 근거: cadence(주기)-구동 인프라는 신선도 마커 필수, event-구동 인프라는 트리거 배선만.
#   이 스크립트는 cadence-구동 항목의 신선도만 검사한다 — event-구동(citation-log, rollback,
#   killswitch 등)은 이벤트가 없으면 미사용이 정상이므로 검사하지 않는다.
#
# 토큰 설계: 검사는 전부 bash(토큰 0), 모델에게는 **이상 항목만** 1줄씩 노출.
#   전부 정상이면 "USAGE OK" 한 줄 — T03에서 모델이 읽는 비용을 상수로 고정한다.
#
# 사용 마커 규약: 각 도구는 실행 시 ~/.claude/_usage/<이름>-last 를 touch 한다 (gitignore).
#   마커가 없으면 "한 번도 실행 안 됨"으로 판정 가능 — 부재 자체가 신호다.
# REF: knowledge/harness/code-history/scripts__harness-usage-check.sh.md

# NEVER: 판정(accepted/rejected)을 새로 내리지는 않는다(learner 불변식 «자동 적용 없음», 2026-10-17 G2·G5-1). 상태는 두 경우에만 바뀐다:
#   만료(pending→expired)와 재시도 큐 배수(post-commit 이 못 한 `set accepted` 를 다시 시도)이고, 효과 기록은 note 만 쓴다.

set -uo pipefail
CLAUDE_DIR="$HOME/.claude"
USAGE_DIR="$CLAUDE_DIR/_usage"
mkdir -p "$USAGE_DIR" 2>/dev/null
ISSUES=0
MAINT_LOG="$USAGE_DIR/maintenance.log"
if [ -f "$MAINT_LOG" ] && [ "$(wc -l < "$MAINT_LOG" 2>/dev/null || echo 0)" -gt 1000 ]; then
    if ! { tail -n 500 "$MAINT_LOG" > "$MAINT_LOG.tmp.$$" 2>/dev/null && mv "$MAINT_LOG.tmp.$$" "$MAINT_LOG" 2>/dev/null; }; then rm -f "$MAINT_LOG.tmp.$$" 2>/dev/null; fi
fi
TODAY=$(date +%Y-%m-%d)
ADDED_NS=0
# WHY: 하루 1회 일은 `_usage/<이름>-<날짜>.d` 디렉터리를 mkdir 로 선점한 세션만 한다. 마커 파일을 «읽고 판단하고 쓰기» 하면 병렬 세션이 둘 다 통과한다(2026-10-17 외부 검토).
claim_daily() { mkdir "$USAGE_DIR/$1-$TODAY.d" 2>/dev/null; }
release_daily() { rmdir "$USAGE_DIR/$1-$TODAY.d" 2>/dev/null; return 0; }
# WHY: T41 효과 기록 선점 디렉터리가 done 없이 mtime 10분을 넘으면 뒤 세션이 승계하고 EFF_TAKEOVER=1 을 둔다(2026-10-17 Grok 4차).
# 그러지 않으면 기록이 계속 실패할 때 만료(T12·T40 포함)가 영영 멈춘다. 승계 경합은 set-note-batch 가 멱등이라 무해하다.
EFF_TAKEOVER=0; EFF_DONE_FAIL=0; EFF_NO_CUT=0
mark_effect_done() {
    local dir="$USAGE_DIR/t41-effect-$TODAY.d"
    if { : > "$dir/done"; } 2>/dev/null; then return 0; fi
    EFF_DONE_FAIL=1
    { printf 'done 생성 실패\n' > "$dir/failed"; } 2>/dev/null
    return 1
}
effect_claim() {
    local dir="$USAGE_DIR/t41-effect-$TODAY.d"
    if mkdir "$dir" 2>/dev/null; then return 0; fi
    if [ -d "$dir" ] && [ ! -e "$dir/done" ] && [ -n "$(find "$dir" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
        touch "$dir" 2>/dev/null; rm -f "$dir/failed" 2>/dev/null
        EFF_TAKEOVER=1
        return 0
    fi
    return 1
}
norm_axis() {
    local role n
    case "$1" in */*) ;; *) printf '%s' "$1"; return ;; esac
    role="${1%%/*}"; n=$(normalize_role "$role"); [ -n "$n" ] || n="$role"
    printf '%s/%s' "$n" "${1#*/}"
}
find "$USAGE_DIR" -mindepth 2 -maxdepth 2 -type f \( -name 'done' -o -name 'failed' \) -path '*/t41-effect-*.d/*' ! -path "*-$TODAY.d/*" -delete 2>/dev/null
find "$USAGE_DIR" -maxdepth 1 -type d \( -name 'candidates-digest-*.d' -o -name 't41-effect-*.d' \) ! -name "*-$TODAY.d" -exec rmdir {} + 2>/dev/null
HAVE_TIMEOUT=0
command -v timeout >/dev/null 2>&1 && HAVE_TIMEOUT=1
if [ -f "$CLAUDE_DIR/scripts/role-alias.sh" ]; then
    # shellcheck source=/dev/null
    . "$CLAUDE_DIR/scripts/role-alias.sh"
else
    normalize_role() { printf '%s' "$1"; }
fi
now_ns() {
    local t; t=$(date +%s%N 2>/dev/null); [[ "$t" =~ ^[0-9]+$ ]] && echo "$t" || echo 0
}

# NEVER: 이 점검에서 git 색인을 바꾸지 않는다(`git add` 없음, 2026-10-01 감사 P6). 세션마다 색인을 바꾸면 사용자가 스테이징한 상태와 섞인다.

warn() { echo "⚠ $1"; ISSUES=$((ISSUES + 1)); }

age_days() {
    if [ -e "$1" ]; then
        local m
        m=$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0)
        echo $(( ($(date +%s) - m) / 86400 ))
    else
        echo -1
    fi
}
age_min() {
    if [ -e "$1" ]; then
        local m
        m=$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0)
        echo $(( ($(date +%s) - m) / 60 ))
    else
        echo -1
    fi
}

A=$(age_days "$CLAUDE_DIR/_audit/last-run")
# WHY: last-run은 머신 로컬(gitignore) — 감사는 repo 단위이므로 git 추적되는 history.md의
# 최신 일자와 함께 보고 더 새로운 쪽을 쓴다 (2026-07-13 _audit 추적 전환과 한 쌍).
# 제목에 감사·점검 계열 낱말이 있는 절만 감사로 친다: 전부 세면 규칙을 고친 날마다 감사 시계가 리셋된다(2026-09-14 교정 3).
HD=$(grep -oE '^#{2,3} [0-9]{4}-[0-9]{2}-[0-9]{2}.*' "$CLAUDE_DIR/_audit/history.md" 2>/dev/null \
    | grep -iE '감사|점검|audit' | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | sort | tail -1)
if [ -n "$HD" ]; then
    HS=$(date -d "$HD" +%s 2>/dev/null || date -jf %Y-%m-%d "$HD" +%s 2>/dev/null || echo "")
    if [ -n "$HS" ]; then
        HA=$(( ($(date +%s) - HS) / 86400 ))
        { [ "$A" -lt 0 ] || [ "$HA" -lt "$A" ]; } && A="$HA"
    fi
fi
if [ "$A" -lt 0 ]; then
    warn "AUDIT_NEVER: 감사 기록 없음 → /harness-audit 제안"
elif [ "$A" -gt 30 ]; then
    warn "AUDIT_STALE(${A}d): /harness-audit 제안 (30일 초과)"
fi

if command -v systemctl >/dev/null 2>&1; then
    if ! systemctl --user is-enabled claude-ontology-refresh.timer >/dev/null 2>&1; then
        warn "TIMER_UNSET: 온톨로지 타이머 미활성 → mem0 결정 확인 후 3택 게이트 (code-graph.md §8)"
    else
        # WHY: "성공 존재 여부"가 아니라 "마지막 성공의
        # 시점"으로 판정 — 존재 여부로 통과시키면 과거 성공 1회가 이후 연속 실패를 영구히
        # 가린다 (Codex 교차검증 P2 반영, 2026-07-09). 일간 타이머 + 여유 1일 = 2일 임계 (2026-07-13 주간→일간 전환).
        L="$CLAUDE_DIR/ontology-refresh.log"
        if [ -f "$L" ]; then
            # WHY: "finalize 완료"는 pipeline finalize 성공 종점에서 무조건 찍히는 유일 마커.
            # "변경 없음"은 detect 단계의 "시맨틱 변경 없음"과도 매칭돼 실패를 성공으로 오인시킴 (qa 정독 P1)
            LAST_OK_LINE=$(grep -E "finalize 완료" "$L" 2>/dev/null | tail -1)
            # WHY: 미push 백로그로 인한 정상 skip은 침묵 사망이 아니다 — 마지막 이벤트가 skip이면
            # TIMER_SILENT를 억제 (push 대기는 PUSH_NEEDED 경보가 담당). 일간 전환으로 push보다
            # 빌드가 잦아져 skip이 정상 상태가 됨 (2026-07-13 주간→일간과 한 쌍).
            LAST_EVENT=$(grep -E "finalize 완료|이번 주기 skip" "$L" 2>/dev/null | tail -1)
            if [ -n "$LAST_EVENT" ] && [ "$LAST_EVENT" != "$LAST_OK_LINE" ]; then
                :
            elif [ -n "$LAST_OK_LINE" ]; then
                LAST_OK_TS=$(printf '%s' "$LAST_OK_LINE" | sed -E 's/^\[([^]]+)\].*/\1/')
                # WHY: GNU date -d → BSD date -j 순서 폴백. 둘 다 실패하면 경고 — 감지기의 파싱 실패가
                # 조용한 통과가 되면 감지기 자신이 침묵 사망한다 (Codex 2라운드 P2: fail-visible 원칙).
                # BSD %z는 +0900 형식(콜론 없음)만 받으므로 ISO의 +09:00 콜론을 제거해 전달 (3라운드 P2)
                LAST_OK_TS_BSD=$(printf '%s' "$LAST_OK_TS" | sed -E 's/([+-][0-9]{2}):([0-9]{2})$/\1\2/')
                LAST_OK_EPOCH=$(date -d "$LAST_OK_TS" +%s 2>/dev/null \
                    || date -j -f "%Y-%m-%dT%H:%M:%S%z" "$LAST_OK_TS_BSD" +%s 2>/dev/null \
                    || echo 0)
                if [ "$LAST_OK_EPOCH" -gt 0 ]; then
                    OK_AGE=$(( ($(date +%s) - LAST_OK_EPOCH) / 86400 ))
                    [ "$OK_AGE" -gt 2 ] && warn "TIMER_SILENT(마지막 성공 ${OK_AGE}d 전): 이후 실행 실패 반복 의심 → ontology-refresh.log 확인"
                else
                    warn "TIMER_PARSE: 성공 로그 타임스탬프 파싱 실패(${LAST_OK_TS}) → ontology-refresh.log 수동 확인"
                fi
            else
                # WHY: 성공 기록 없음 + 로그 존재 = 실행됐으나 전부 실패. 로그 mtime(LA)은 실패로도 갱신돼
                # 마스킹되므로(2026-07-18 Codex) 실행 횟수로 판정: '갱신 시작' ≥2회면 반복 실패 확정
                # (1회는 첫 실행 진행 중일 수 있어 유예).
                RUN_COUNT=$(grep -c '갱신 시작' "$L" 2>/dev/null); RUN_COUNT=${RUN_COUNT:-0}
                [ "$RUN_COUNT" -ge 2 ] && warn "TIMER_SILENT: 타이머 ${RUN_COUNT}회 실행했으나 성공 기록 0 → ontology-refresh.log 확인"
            fi
        else
            warn "TIMER_SILENT(로그 부재): 온톨로지 타이머 활성이나 ontology-refresh.log 없음 → 타이머 동작·로그 경로 점검"
        fi
    fi
fi

# WHY: 온톨로지뿐 아니라 하네스 자체 변경도 1커밋이라도 원격 미반영이면 알린다(2026-07-10 사용자 확정, vault 포함 여부는 병기).
if git -C "$CLAUDE_DIR" rev-parse --abbrev-ref '@{upstream}' >/dev/null 2>&1; then
    N=$(git -C "$CLAUDE_DIR" rev-list --count '@{upstream}'..HEAD 2>/dev/null || echo 0)
    if [ "$N" -ge 1 ]; then
        VN=$(git -C "$CLAUDE_DIR" rev-list --count '@{upstream}'..HEAD -- graphify-out/ 2>/dev/null || echo 0)
        if [ "$VN" -ge 1 ]; then
            warn "PUSH_NEEDED(${N}건, vault ${VN}건 포함): 미push 하네스 변경 → git push 권장 (타서버 전파·타이머 가드 해소)"
        else
            warn "PUSH_NEEDED(${N}건): 미push 하네스 변경 → git push 권장 (타서버 전파)"
        fi
    fi
fi

# WHY: 나이틀리는 스테이징+메시지 준비까지만 한다(2026-08-05 자동 커밋 폐지).
if [ -f "$CLAUDE_DIR/graphify-out/.commit-msg" ] && ! git -C "$CLAUDE_DIR" diff --quiet HEAD -- graphify-out/ 2>/dev/null; then
    warn "ONTOLOGY_COMMIT_PENDING: 나이틀리 산출물 커밋 대기 → git pull 확인 후 git commit -F graphify-out/.commit-msg -- graphify-out/ && git push"
fi

# WHY: 원격 실비교 우선(2026-07-10 사용자 제안). fetch 는 비대화형·5초 제한(세션 시작 지연 방지)이고,
#     자격증명 캐시가 없는 서버에선 fetch가 조용히 실패 → 로컬 휴리스틱으로 강등. 권장 채널은 세션 응답만 — ntfy 미사용 (사용자 결정).
if git -C "$CLAUDE_DIR" rev-parse --abbrev-ref '@{upstream}' >/dev/null 2>&1; then
    if GIT_TERMINAL_PROMPT=0 timeout 5 git -C "$CLAUDE_DIR" fetch --quiet 2>/dev/null; then
        BEHIND=$(git -C "$CLAUDE_DIR" rev-list --count HEAD..'@{upstream}' 2>/dev/null || echo 0)
        if [ "$BEHIND" -ge 1 ]; then
            VN=$(git -C "$CLAUDE_DIR" rev-list --count HEAD..'@{upstream}' -- graphify-out/ 2>/dev/null || echo 0)
            if [ "$VN" -ge 1 ]; then
                warn "PULL_NEEDED(${BEHIND}건, vault ${VN}건 포함): 원격에 새 커밋 → git pull 권장"
            else
                warn "PULL_NEEDED(${BEHIND}건): 원격에 새 커밋 → git pull 권장"
            fi
        fi
    elif command -v systemctl >/dev/null 2>&1 && ! systemctl --user is-enabled claude-ontology-refresh.timer >/dev/null 2>&1; then
        LAST_VAULT_TS=$(git -C "$CLAUDE_DIR" log -1 --format=%ct -- graphify-out/ 2>/dev/null || echo 0)
        if [ "$LAST_VAULT_TS" -gt 0 ]; then
            VAGE=$(( ($(date +%s) - LAST_VAULT_TS) / 86400 ))
            [ "$VAGE" -gt 3 ] && warn "ONTOLOGY_PULL(추정 ${VAGE}d, fetch 불가 환경): 로컬 vault가 일간 주기 대비 오래됨 → git pull 권장"
        fi
    fi
fi

PD=$(age_days "$USAGE_DIR/pattern-detect-last")
EVOLVE_LINES=$(cat "$CLAUDE_DIR"/_evolve/*.jsonl 2>/dev/null | wc -l)
if [ "$EVOLVE_LINES" -gt 50 ] && { [ "$PD" -lt 0 ] || [ "$PD" -gt 7 ]; }; then
    warn "PATTERNS_UNMINED(${EVOLVE_LINES}줄/${PD}d): pattern-detect 실행 제안 (T40 자가진화 루프 정지 상태)"
fi
# WHY: 위 PATTERNS_UNMINED 는 SessionStart 의 pattern-detect 가 매번 pattern-detect-last 를 찍어 사실상 도달 불가
# (훅이 죽었을 때만 울린다, 2026-10-01 P6 검수). «후보를 안 본다» 경보는 아래 CANDIDATES_PENDING 하나가 맡는다.

if [ -d "$CLAUDE_DIR/knowledge" ]; then
    # WHY: -maxdepth 제거 (2026-07-14): 프로젝트별 하위 폴더(harness/ 등) 재귀 검사 — maxdepth 1 유지 시 오경보
    KN=$(find "$CLAUDE_DIR/knowledge" -name '*.md' ! -name 'README.md' -newermt '-14 days' 2>/dev/null | head -1)
    if [ -z "$KN" ]; then
        warn "KNOWLEDGE_SILENT: 최근 14일 지식 노트 0건 → 대화 지식 캡처 루프 점검 (rules-lazy/knowledge-capture.md)"
    fi
fi

# WHY: 문구가 아니라 사실로 판정한다(2026-09-14 재정의): 마지막 bench 이후 규칙 계열 파일이
#    바뀐 커밋이 있고, 그 첫 커밋으로부터 14일이 지났으면 측정이 밀린 것이다. 첫 커밋 기준이라야 계속 고치는 동안 경보가 뒤로 밀리지 않는다.
B=$(age_days "$USAGE_DIR/bench-last")
BENCH_TS=$(stat -c %Y "$USAGE_DIR/bench-last" 2>/dev/null || stat -f %m "$USAGE_DIR/bench-last" 2>/dev/null || echo 0)
if git -C "$CLAUDE_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    FIRST_RULE_TS=$(git -C "$CLAUDE_DIR" log --since="@$BENCH_TS" --format=%ct --reverse \
        -- rules rules-lazy agents CLAUDE.md 2>/dev/null | head -1)
    if [ -n "$FIRST_RULE_TS" ]; then
        RULE_AGE=$(( ($(date +%s) - FIRST_RULE_TS) / 86400 ))
        if [ "$RULE_AGE" -gt 14 ]; then
            if [ "$B" -lt 0 ]; then
                warn "BENCH_PENDING(규칙 변경 후 ${RULE_AGE}d): harness-bench 실행 이력 없음 → /harness-bench 제안"
            else
                warn "BENCH_PENDING(bench ${B}d 전, 이후 규칙 변경 첫 커밋 ${RULE_AGE}d): 수정→측정 복귀 지연 → /harness-bench 제안"
            fi
        fi
    fi
fi

# WHY: cron이 등록돼 있는데 로그가 30분+ 침묵이면 감시기의 침묵 사망이다(fail-visible 원칙, 2026-08-19 검수 발견).
if crontab -l 2>/dev/null | grep -q mem-watch.sh; then
    MW_LOG="$CLAUDE_DIR/tools/mem-guard/mem-watch.log"
    MW_AGE=$(age_min "$MW_LOG" 2>/dev/null || echo -1)
    if [ "$MW_AGE" -lt 0 ] 2>/dev/null; then
        warn "MEMWATCH_SILENT: cron 등록됐는데 mem-watch.log 부재 → cron 동작 점검"
    elif [ "$MW_AGE" -gt 30 ] 2>/dev/null; then
        warn "MEMWATCH_SILENT(${MW_AGE}m): mem-watch cron이 30분+ 침묵 → cron 동작 점검"
    fi
fi

# WHY: agent-crosscheck.sh 는 T41 약점 루프의 유일한 기록점인데 훅·타이머 배선이 없다(2026-09-06 검수 발견). 2026-10-17 G2 부터 자동 실행한다.
#    동기로 돌리면 transcript 전수 grep 이 SessionStart 를 막으므로 전용 잠금이 비어 있을 때만 분리해 띄운다.
#    신선도 판정은 파일 mtime 이 아니라 `agent-crosscheck.sh latest` 를 쓴다 — mtime 은 손으로 파일을 만지거나 다른 줄을 붙여도
#    갱신돼 «오래된 판정» 을 가린다(2026-10-17 외부 검토).
#    재시도 폭주 방지: 시도 마커(30분)는 여기서 찍고, 성공 마커(6시간)는 agent-crosscheck.sh --auto 가 행을 append 한 직후에만 찍는다.
CC_TSV="$CLAUDE_DIR/_evolve/crosscheck.tsv"
CC_STALE=0
bash "$CLAUDE_DIR/scripts/agent-crosscheck.sh" latest >/dev/null 2>&1 || CC_STALE=1
if [ "$CC_STALE" = 1 ]; then
    CC_LABEL="기록 없음"; CC_AGE=-1
    if [ -s "$CC_TSV" ]; then
        CC_E=$(date -d "$(tail -n 1 "$CC_TSV" | cut -f1)" +%s 2>/dev/null)
        if [ -n "$CC_E" ]; then CC_AGE=$(( ($(date +%s) - CC_E) / 86400 )); CC_LABEL="${CC_AGE}d"; else CC_AGE=0; CC_LABEL="ts 해석 불가"; fi
    fi
    if [ -f "$CLAUDE_DIR/scripts/agent-crosscheck.sh" ] && command -v flock >/dev/null 2>&1 && command -v setsid >/dev/null 2>&1 \
        && [ -z "$(find "$USAGE_DIR/crosscheck-auto-last" -mmin -360 2>/dev/null)" ] \
        && [ -z "$(find "$USAGE_DIR/crosscheck-auto-attempt" -mmin -30 2>/dev/null)" ] \
        && ( flock -n 8 ) 8>"$USAGE_DIR/crosscheck.lock" 2>/dev/null; then
        touch "$USAGE_DIR/crosscheck-auto-attempt" 2>/dev/null
        # WHY: 15분 상한·최저 CPU/IO 우선순위(2026-10-17 검수): transcript 전수 grep 이 작업 중인 학습·세션과 디스크를 다투지 않게 한다.
        # 각 도구는 있을 때만 감싼다(ionice 는 실제로 돌아가는지 한 번 확인 — 컨테이너에서 거부되면 감싼 명령 자체가 안 돈다).
        CC_WRAP=()
        command -v timeout >/dev/null 2>&1 && CC_WRAP+=(timeout 900)
        command -v nice >/dev/null 2>&1 && CC_WRAP+=(nice -n 19)
        command -v ionice >/dev/null 2>&1 && ionice -c3 true >/dev/null 2>&1 && CC_WRAP+=(ionice -c3)
        setsid nohup ${CC_WRAP[@]+"${CC_WRAP[@]}"} bash "$CLAUDE_DIR/scripts/agent-crosscheck.sh" --auto >> "$USAGE_DIR/crosscheck-auto.log" 2>&1 < /dev/null &
        echo "ℹ CROSSCHECK_AUTO(${CC_LABEL}): 최신 판정이 신선하지 않아(7일 초과 또는 일치 아님) agent-crosscheck.sh --auto 를 백그라운드로 시작함 (결과: _usage/crosscheck-auto.log, 새 행은 _evolve/crosscheck.tsv)"
    elif [ "$CC_AGE" -lt 0 ]; then
        warn "CROSSCHECK_STALE(기록 없음): bash scripts/agent-crosscheck.sh 실행 (T41 에이전트 약점 루프 기록 0건)"
    else
        warn "CROSSCHECK_STALE(${CC_LABEL}): bash scripts/agent-crosscheck.sh 실행 (최신 판정이 7일 초과이거나 일치가 아님 — T41 약점 루프 정지 의심)"
    fi
fi

CAND_FILE="$CLAUDE_DIR/_evolve/candidates.tsv"
SPAWN_LOG="$CLAUDE_DIR/_audit/agent-spawn.log"
T41_HIST="$CLAUDE_DIR/_audit/history.md"
# WHY: 순서는 «재시도 큐 배수 → T41 효과 기록 → 7일 만료» 다(2026-10-17 Grok 2차·Codex 3차). 큐에 남은 id 는 7일 만료에서 제외한다(만료가 큐를 앞지르지 않게).
#     세션당 최대 2줄만 처리한다(바깥 훅 15초 안에 들게: 줄당 timeout 2초 × 2 + 효과 기록 ≤10초 = 14초).
RETRY_F="$USAGE_DIR/candidates-attach-retry.tsv"
RETRY_LOCK="$USAGE_DIR/candidates-attach-retry.lock"
retry_locked() {
    if command -v flock >/dev/null 2>&1; then ( flock -w 2 8 || exit 1; "$@" ) 8>"$RETRY_LOCK"
    else
        printf '%s attach-retry: 잠금 불가(flock 없음) — 큐를 읽거나 쓰지 않음\n' "$(date -Is)" >> "$MAINT_LOG" 2>/dev/null
        return 1
    fi
}
# shellcheck disable=SC2329  # 아래 세 함수는 retry_locked "$@" 로 간접 호출된다
retry_snapshot() { cat "$RETRY_F" 2>/dev/null; }
# shellcheck disable=SC2329
retry_ids() { awk -F'\t' 'NF { printf "%s%s", (n++ ? "," : ""), $1 }' "$RETRY_F" 2>/dev/null; }
# shellcheck disable=SC2329
retry_rewrite() {
    # WHY: id·해시가 모두 같은 줄만 뺀다. 배수하는 동안 post-commit 이 같은 id 의 해시를 새 커밋으로 교체했다면 그 줄은 남는다(id 만 비교하면 교체본이 지워진다 — 2026-10-17 Grok 10차).
    if OKPAIRS="$1" awk -F'\t' 'BEGIN { n = split(ENVIRON["OKPAIRS"], a, "\n"); for (i = 1; i <= n; i++) if (a[i] != "") ok[a[i]] = 1 } !(($1 "\t" $2) in ok)' "$RETRY_F" > "$RETRY_F.tmp.$$" 2>/dev/null; then
        mv "$RETRY_F.tmp.$$" "$RETRY_F"
    else
        rm -f "$RETRY_F.tmp.$$"; return 1
    fi
}
# NEVER: 대장을 읽지 못하면 큐를 건드리지 않는다. 상태 조회가 빈 값이 되어 «id 없음» 폐기로 오인된다.
if [ -s "$RETRY_F" ] && [ -f "$CAND_FILE" ] && [ ! -r "$CAND_FILE" ]; then
    printf '%s attach-retry: 대장 읽기 불가라 배수 건너뜀 (%s) — 큐 불변\n' "$(date -Is)" "$CAND_FILE" >> "$MAINT_LOG" 2>/dev/null
fi
if [ -s "$RETRY_F" ] && [ -f "$CAND_FILE" ] && [ -r "$CAND_FILE" ]; then
    if RETRY_SNAP=$(retry_locked retry_snapshot); then
        RETRY_OK=""
        RETRY_DONE=0
        while IFS=$'\t' read -r RID RHASH; do
            [ -n "$RID" ] && [ -n "$RHASH" ] || continue
            [ "$RETRY_DONE" -lt 2 ] || break
            RETRY_DONE=$((RETRY_DONE + 1))
            RST=$(ID="$RID" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $5; exit}' "$CAND_FILE" 2>/dev/null); RST_RC=$?
            # NEVER: 조회 실패를 빈 상태(«id 없음» 폐기)로 읽지 않는다. 이 줄은 RETRY_OK 에 넣지 않고 큐에 남긴다.
            if [ "$RST_RC" -ne 0 ]; then
                printf '%s attach-retry: %s 상태 조회 실패(awk rc=%s) — 줄을 큐에 남김\n' "$(date -Is)" "$RID" "$RST_RC" >> "$MAINT_LOG" 2>/dev/null
                continue
            fi
            case "$RST" in
                ""|rejected)
                    RSN="id 없음"; [ -n "$RST" ] && RSN="상태 $RST"
                    printf '%s attach-retry 폐기: %s %s\n' "$(date -Is)" "$RID" "$RSN" >> "$MAINT_LOG" 2>/dev/null
                    RETRY_OK+="$RID"$'\t'"$RHASH"$'\n'; continue ;;
            esac
            if [ "$RST" = accepted ]; then RCMD=(attach-commit "$RID" "$RHASH"); else RCMD=(set "$RID" accepted --note "commit=$RHASH" --machine); fi
            if [ "$HAVE_TIMEOUT" = 1 ]; then RTO=(timeout 2); else RTO=(); fi
            if ${RTO[@]+"${RTO[@]}"} bash "$CLAUDE_DIR/scripts/candidates-append.sh" "${RCMD[@]}" >> "$MAINT_LOG" 2>&1 < /dev/null; then
                RETRY_OK+="$RID"$'\t'"$RHASH"$'\n'
            else
                RRC=$?
                # WHY: exit 3(잠금 실패)·124(timeout)·5(입출력)·그 밖의 비0 은 일시 실패라 큐에 남긴다(2026-10-17 Codex 7차).
                # expired 의 set 과 accepted 의 attach-commit 이 exit 1 이면 영구 실패라 지운다(세션당 2줄 상한이라 영구 실패 줄이 앞에 남으면 뒷줄이 막힌다 — 2026-10-17 검수팀 재확인).
                if { [ "$RST" = expired ] || [ "$RST" = accepted ]; } && [ "$RRC" -eq 1 ]; then
                    printf '%s attach-retry 폐기: %s 상태 %s (%s 실패 rc=1)\n' "$(date -Is)" "$RID" "$RST" "${RCMD[0]}" >> "$MAINT_LOG" 2>/dev/null
                    RETRY_OK+="$RID"$'\t'"$RHASH"$'\n'
                fi
            fi
        done <<< "$RETRY_SNAP"
        if [ -n "$RETRY_OK" ]; then
            retry_locked retry_rewrite "$RETRY_OK" || printf '%s attach-retry 큐 재작성 실패(잠금) — 다음 세션이 다시 시도\n' "$(date -Is)" >> "$MAINT_LOG" 2>/dev/null
        fi
    fi
fi

# WHY: T41 효과 기록은 아래 7일 자동 만료보다 먼저 돈다(2026-10-17 Codex 2차). 만료가 먼저면 8일 된 quiet 행이 재발을 기록하기 전에
#     expired 가 되어 effect:recurred 만료 보호가 무의미해진다.
# WHY: 14일 침묵 자동 종결은 폐기했다(2026-10-17 G2: 침묵을 보상하고, qa FAIL 이 전부 coder 로 귀속되는 구조라 역할마다 치우친다).
#     대신 미결 T41 후보의 note 에 사실만 적고 판정은 스킬에서 사람이 한다.
# NEVER: 대장 파일에 직접 쓰지 않는다. 쓰기는 `candidates-append.sh set-note-batch --only-machine` 으로만 한다(읽고 잠금 밖에서 판단하면 그 사이의 사람 판정을 덮는다).
# WHY: 선정 상한은 두지 않는다(2026-10-17 Codex 4차: 상한이 있으면 201번째 미결 T41 이 기록 없이 quiet 로 만료되는데 done 은 만들어진다).
T41_PEND=0
T41_PEND_RC=0
# NEVER: awk 실패를 «미결 0» 으로 읽지 않는다(만료 전 점검에서 보류).
if [ -f "$CAND_FILE" ]; then T41_PEND=$(awk -F'\t' '$1!="id" && $2=="T41" && ($5=="pending" || $5=="pending-bench" || $5=="pending-approval") {n++} END {print n+0}' "$CAND_FILE" 2>/dev/null); T41_PEND_RC=$?; fi
if [ "${T41_PEND:-0}" -ge 1 ] 2>/dev/null && effect_claim; then
    CUT14D=$(date -d '-14 days' +%Y-%m-%d 2>/dev/null || date -v-14d +%Y-%m-%d 2>/dev/null || echo "")
    if [ -n "$CUT14D" ]; then
        # WHY: grep 종료 코드를 따로 받는다(2026-10-17 Grok 7차): 0=매치·1=매치 없음(빈 history 로 본다)·2 이상=읽기 실패(파일 없음·권한 0).
        # 읽기 실패를 빈 결과로 흘리면 재발 수 k=0 → effect:quiet → done → 7일 뒤 만료되는 fail-open 이 된다.
        T41_RAW=$(grep -E '^- [0-9]{4}-[0-9]{2}-[0-9]{2} T41: ' "$T41_HIST" 2>/dev/null); T41_GREP_RC=$?
        T41_ALL=$(printf '%s\n' "$T41_RAW" | sed -E 's/^- ([0-9]{4}-[0-9]{2}-[0-9]{2}) T41: /\1\t/; s/ — .*$//; s/[[:space:]]+$//')
        T_NS=$(now_ns)
        AXMAP=""
        while IFS= read -r AX0; do
            [ -n "$AX0" ] || continue
            AXMAP+="$AX0"$'\t'"$(norm_axis "$AX0")"$'\n'
        done < <({ printf '%s\n' "$T41_ALL" | cut -f2; awk -F'\t' '$1!="id" && $2=="T41" { p = index($6, ":"); a = (p ? substr($6, 1, p - 1) : $6); gsub(/^[ \t]+|[ \t]+$/, "", a); print a }' "$CAND_FILE" 2>/dev/null; } | sort -u)
        SPAWN_CNT=""; SPAWN_AWK_RC=0
        if [ -f "$SPAWN_LOG" ]; then
            SPAWN_CNT=$(awk -F'\t' -v c="$CUT14D" 'substr($1,1,10)>=c && $2=="post" { t=$3; sub(/[[:space:]]+$/, "", t); n[t]++ } END { for (k in n) print k "\t" n[k] }' "$SPAWN_LOG" 2>/dev/null); SPAWN_AWK_RC=$?
        fi
        declare -A SPN=()
        while IFS=$'\t' read -r SPR SPC; do
            [ -n "$SPR" ] || continue
            SPNORM=$(normalize_role "$SPR"); [ -n "$SPNORM" ] || SPNORM="$SPR"
            SPN["$SPNORM"]=$(( ${SPN["$SPNORM"]:-0} + SPC ))
        done <<< "$SPAWN_CNT"
        SPN_TXT=""
        for SPK in ${SPN[@]+"${!SPN[@]}"}; do SPN_TXT+="$SPK"$'\t'"${SPN[$SPK]}"$'\n'; done
        # WHY: 효과 계산은 awk 한 번이다(후보마다 awk 를 띄우면 2,000행에서 17초로 훅 한도를 넘었다).
        # awk 종료 코드를 확인한다(2026-10-17 Grok 6차): 비0 을 «쓸 변경 없음» 으로 보고 done 을 만들면 계산하지 못한 후보가 quiet 로 만료된다.
        EFF_BATCH=""; EFF_RC=0; EFF_WHY=""
        if [ "$T41_GREP_RC" -ge 2 ]; then
            EFF_RC="$T41_GREP_RC"; EFF_WHY="history 읽기 실패(grep rc=$T41_GREP_RC)"
        elif [ -f "$SPAWN_LOG" ] && [ ! -r "$SPAWN_LOG" ]; then
            EFF_RC=1; EFF_WHY="spawn 로그 읽기 실패($SPAWN_LOG)"
        elif [ "$SPAWN_AWK_RC" -ne 0 ]; then
            EFF_RC="$SPAWN_AWK_RC"; EFF_WHY="spawn 집계 실패(awk rc=$SPAWN_AWK_RC)"
        else
        EFF_BATCH=$(awk -F'\t' 'function trim(x) { gsub(/^[ \t]+|[ \t]+$/, "", x); return x }
                FILENAME == ARGV[1] { map[$1] = $2; next }
                FILENAME == ARGV[2] { spn[$1] = $2; next }
                FILENAME == ARGV[3] { h = ($2 in map) ? map[$2] : $2; nrec[h]++; rd[h, nrec[h]] = $1; next }
                $1 != "id" && $2 == "T41" && ($5 == "pending" || $5 == "pending-bench" || $5 == "pending-approval") \
                && ($7 == "" || $7 ~ /^kw=/ || $7 ~ /^effect:/) && $7 !~ /^effect:recurred/ {
                    p = index($6, ":"); ax = trim(p ? substr($6, 1, p - 1) : $6); an = (ax in map) ? map[ax] : ax
                    q = index(an, "/"); role = (q ? substr(an, 1, q - 1) : an)
                    n = 0; s = 0
                    for (j = 1; j <= nrec[an]; j++) { if (rd[an, j] > $3) n++; else if (rd[an, j] == $3) s++ }
                    t = n + s; if (s > 0) t--
                    nn = (t > 0) ? "effect:recurred k=" t : "effect:quiet n_spawn=" (spn[role] + 0)
                    if (nn != $7) print $1 "\t" nn
                }' <(printf '%s' "$AXMAP") <(printf '%s' "$SPN_TXT") <(printf '%s\n' "$T41_ALL") "$CAND_FILE" 2>/dev/null); EFF_RC=$?
        [ "$EFF_RC" -eq 0 ] || EFF_WHY="T41 효과 계산 실패(awk rc=$EFF_RC)"
        fi
        if [ "$EFF_RC" -ne 0 ]; then
            printf '%s %s — done 을 만들지 않음, 10분 뒤 다음 세션이 재시도\n' "$(date -Is)" "$EFF_WHY" >> "$MAINT_LOG" 2>/dev/null
            printf '%s\n' "$EFF_WHY" > "$USAGE_DIR/t41-effect-$TODAY.d/failed"
        elif [ -n "$EFF_BATCH" ]; then
            # WHY: timeout 은 5 + 행수/100 초(최소 5, 최대 10): 행이 많아도 같은 묶음이 매 세션 124 로 잘려 재시도되지 않게 한다.
            # 상한 10초 근거: SessionStart 훅의 바깥 timeout 이 15초(settings.json)라 이보다 길면 바깥이 먼저 끊는다(2026-10-17 검수팀).
            EFF_N=$(printf '%s\n' "$EFF_BATCH" | grep -c .); EFF_TMO=$((5 + ${EFF_N:-0} / 100)); [ "$EFF_TMO" -le 10 ] || EFF_TMO=10
            if [ "$HAVE_TIMEOUT" = 1 ]; then EFF_TO=(timeout "$EFF_TMO")
            else EFF_TO=(); warn "T41_EFFECT_NO_TIMEOUT: timeout 명령이 없어 T41 효과 기록을 상한 없이 실행함 → coreutils(timeout) 설치 확인"
            fi
            if printf '%s\n' "$EFF_BATCH" | ${EFF_TO[@]+"${EFF_TO[@]}"} bash "$CLAUDE_DIR/scripts/candidates-append.sh" set-note-batch --only-machine >> "$MAINT_LOG" 2>&1; then
                mark_effect_done
            else
                printf 'set-note-batch 실패(rc=%s)\n' "$?" > "$USAGE_DIR/t41-effect-$TODAY.d/failed"
            fi
        else
            mark_effect_done
        fi
        ADDED_NS=$((ADDED_NS + $(now_ns) - T_NS))
    else
        release_daily t41-effect
        EFF_NO_CUT=1
    fi
fi

# WHY: 부재뿐 아니라 빈 대장과 밀린 pending 까지 본다(2026-09-14). 09-06 수리가 파일만 만들고 쓰는 코드가 없어 헤더 1줄로 8일을 보냈는데
#    부재 검사만 있어 통과했다(09-14 감사 §2-3·§2-4).
CP_N=0
# WHY: 만료 전 점검 두 가지(2026-10-17 Codex 3차): 재시도 큐에 남은 id 는 만료에서 제외하고, T41 효과 기록이 끝났을 때만 만료한다.
#   다른 세션이 효과를 집계하는 중이면 8일 된 quiet 행이 재발 기록 전에 만료되기 때문이다.
EXPIRE_OK=1; RETRY_IDS=""; EXPIRE_FORCE=""
if [ -f "$CAND_FILE" ]; then
    if [ -e "$RETRY_F" ]; then
        if RETRY_IDS=$(retry_locked retry_ids); then
            RETRY_LEFT=$(printf '%s' "$RETRY_IDS" | awk -F, 'NF {print NF}'); RETRY_LEFT=${RETRY_LEFT:-0}
            [ "$RETRY_LEFT" -ge 1 ] 2>/dev/null && warn "CANDIDATES_ATTACH_RETRY ${RETRY_LEFT}건: 후보-커밋 연결이 잠금 실패로 밀려 있음(다음 세션에 다시 시도, 계속 남으면 _usage/candidates-attach-retry.tsv 의 id 상태 확인)"
        else
            EXPIRE_OK=0
            printf '%s expire 건너뜀: 재시도 큐 잠금을 못 잡아 큐의 id 를 알 수 없음\n' "$(date -Is)" >> "$MAINT_LOG" 2>/dev/null
        fi
    fi
    EFFECT_DIR="$USAGE_DIR/t41-effect-$TODAY.d"
    if [ "$T41_PEND_RC" -ne 0 ]; then
        EXPIRE_OK=0
        printf '%s expire 건너뜀: 미결 T41 수를 세지 못함(awk rc=%s) — 효과 기록 보호 여부를 알 수 없음\n' "$(date -Is)" "$T41_PEND_RC" >> "$MAINT_LOG" 2>/dev/null
    # NEVER: done 생성 실패·날짜 계산 실패·미결 집계 실패는 승계 턴에서도 --force 만료로 가지 않는다(그 턴 만료를 보류한다).
    elif [ "$EFF_DONE_FAIL" = 1 ]; then
        EXPIRE_OK=0
        printf '%s expire 건너뜀: 효과 기록 완료 표지(done)를 만들지 못함\n' "$(date -Is)" >> "$MAINT_LOG" 2>/dev/null
    elif [ "$EFF_NO_CUT" = 1 ]; then
        EXPIRE_OK=0
        printf '%s expire 건너뜀: 날짜 계산 실패로 이번 세션은 T41 효과 기록을 하지 못함\n' "$(date -Is)" >> "$MAINT_LOG" 2>/dev/null
    elif [ "${T41_PEND:-0}" -ge 1 ] 2>/dev/null && [ ! -e "$EFFECT_DIR/done" ]; then
        if [ -d "$EFFECT_DIR" ] && [ -n "$(find "$EFFECT_DIR" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
            printf '%s expire 허용: 효과 기록 선점이 10분 넘게 done 없이 남음(기록 세션 중단 추정)\n' "$(date -Is)" >> "$MAINT_LOG" 2>/dev/null
        elif [ "$EFF_TAKEOVER" = 1 ]; then
            EXPIRE_FORCE=1
            printf '%s expire 허용: 10분 지난 선점을 승계했으나 효과 기록이 다시 실패함(done 없음) — 기록 실패가 만료를 영구히 막지 않게\n' "$(date -Is)" >> "$MAINT_LOG" 2>/dev/null
        else
            EXPIRE_OK=0
            printf '%s expire 건너뜀: T41 효과 기록이 아직 끝나지 않음(done 없음) — 다음 세션이 만료\n' "$(date -Is)" >> "$MAINT_LOG" 2>/dev/null
        fi
    fi
fi
if { [ -e "$USAGE_DIR/t41-effect-$TODAY.d/failed" ] && [ ! -e "$USAGE_DIR/t41-effect-$TODAY.d/done" ]; } || [ "$EFF_DONE_FAIL" = 1 ]; then
    EFF_FAIL_WHY=$(head -n 1 "$USAGE_DIR/t41-effect-$TODAY.d/failed" 2>/dev/null)
    [ -n "$EFF_FAIL_WHY" ] || EFF_FAIL_WHY="done 생성 실패"
    if [ "$EXPIRE_OK" = 1 ] && [ -n "$EXPIRE_FORCE" ]; then
        warn "T41_EFFECT_FAIL(${EFF_FAIL_WHY}): T41 효과 기록이 실패함 → _usage/maintenance.log 확인. 이번 세션은 승계 뒤 재실패라 만료를 허용함(10분 뒤 다음 세션이 다시 시도)"
    else
        warn "T41_EFFECT_FAIL(${EFF_FAIL_WHY}): T41 효과 기록이 실패함 → _usage/maintenance.log 확인, 10분 뒤 다음 세션이 다시 시도하고 그때까지 7일 만료는 보류됨"
    fi
fi
if [ -f "$CAND_FILE" ] && [ "$EXPIRE_OK" = 1 ]; then
    T_NS=$(now_ns)
    EXP_OUT=$(bash "$CLAUDE_DIR/scripts/candidates-append.sh" expire --older-than-days 7 ${RETRY_IDS:+--skip-ids "$RETRY_IDS"} ${EXPIRE_FORCE:+--force} 2>&1); EXP_RC=$?
    ADDED_NS=$((ADDED_NS + $(now_ns) - T_NS))
    printf '%s expire rc=%s %s\n' "$(date -Is)" "$EXP_RC" "$EXP_OUT" >> "$MAINT_LOG" 2>/dev/null
    if [ "$EXP_RC" -eq 0 ]; then
        EXP_N=$(printf '%s' "$EXP_OUT" | sed -n 's/^expire: \([0-9][0-9]*\)건.*/\1/p')
        [ "${EXP_N:-0}" -gt 0 ] && echo "ℹ CANDIDATES_EXPIRED(${EXP_N}건): 7일 초과 pending 후보를 expired 로 자동 만료함 (사람 비고·effect:recurred 행 제외, 삭제 없음)"
    elif [ "$EXP_RC" -ne 3 ] && [ "$EXP_RC" -ne 4 ]; then   # WHY: 3=잠금 실패, 4=효과 기록 전이라 만료 보류: 조용히 건너뛰고 위 maintenance.log 줄만 남긴다
        warn "CANDIDATES_EXPIRE_FAIL(rc=${EXP_RC}): 후보 자동 만료 실패 → _usage/maintenance.log 확인"
    fi
fi
if [ ! -f "$CAND_FILE" ]; then
    warn "CANDIDATES_MISSING: _evolve/candidates.tsv 없음 → bash scripts/setup-harness.sh 로 생성 (T12·T40 학습 후보 대장)"
else
    CAND_ROWS=$(awk -F'\t' 'NF>0 && $1!="id" {n++} END {print n+0}' "$CAND_FILE" 2>/dev/null); CAND_ROWS=${CAND_ROWS:-0}
    if [ "$CAND_ROWS" -eq 0 ] 2>/dev/null; then
        warn "CANDIDATES_EMPTY: _evolve/candidates.tsv 데이터 0행 → T12·T40·T41 기록 경로 점검 (pattern-detect.sh·correction-detect.sh 훅 등록 여부)"
    else
        CUT7=$(date -d '-7 days' +%Y-%m-%d 2>/dev/null || date -v-7d +%Y-%m-%d 2>/dev/null || echo "")
        # WHY: 미결 상태 3종을 모두 센다 (2026-09-14 재감사 B2). 종전엔 `pending` 만 세서, 스킬이 상태를
        # 정본 어휘(pending-bench→pending-approval)로 올리는 첫 순간 후보가 경보에서 사라졌다 —
        # 판정을 시작한 후보일수록 안 보이는 역전. 어휘 정본: pending → pending-bench →
        # pending-approval → accepted | rejected.
        CAND_PEND=$(awk -F'\t' -v c="$CUT7" '
            $1!="id" && ($5=="pending" || $5=="pending-bench" || $5=="pending-approval") {
                n++; s[$5]++; ty[$2]++; if (c!="" && $3<c) m++
                if (length($3)==10 && (mn=="" || $3<mn)) mn=$3
            } END { print (n+0)"\t"(m+0)"\t"(s["pending"]+0)"\t"(s["pending-bench"]+0)"\t"(s["pending-approval"]+0)"\t"(ty["T12"]+0)"\t"(ty["T40"]+0)"\t"(ty["T41"]+0)"\t"mn }' \
            "$CAND_FILE" 2>/dev/null)
        CP_N=$(printf '%s' "$CAND_PEND" | cut -f1); CP_M=$(printf '%s' "$CAND_PEND" | cut -f2)
        CP_A=$(printf '%s' "$CAND_PEND" | cut -f3); CP_B=$(printf '%s' "$CAND_PEND" | cut -f4)
        CP_C=$(printf '%s' "$CAND_PEND" | cut -f5)
        CP_T12=$(printf '%s' "$CAND_PEND" | cut -f6); CP_T40=$(printf '%s' "$CAND_PEND" | cut -f7); CP_T41=$(printf '%s' "$CAND_PEND" | cut -f8)
        CP_MIN=$(printf '%s' "$CAND_PEND" | cut -f9)
        CP_N=${CP_N:-0}; CP_M=${CP_M:-0}; CP_A=${CP_A:-0}; CP_B=${CP_B:-0}; CP_C=${CP_C:-0}
        CP_T12=${CP_T12:-0}; CP_T40=${CP_T40:-0}; CP_T41=${CP_T41:-0}
        [ "$CP_N" -ge 1 ] 2>/dev/null && warn "CANDIDATES_PENDING: ${CP_N}건(신규 ${CP_A} · 벤치 대기 ${CP_B} · 승인 대기 ${CP_C} · 7일 초과 ${CP_M}건 · T12 ${CP_T12}·T40 ${CP_T40}·T41 ${CP_T41}) → /learn-from-feedback 로 판정 (스킬화·편입·룰화·기각)"
        # WHY: 마커가 아예 없을 때는 «미결 후보의 가장 이른 생성일이 30일 초과» 일 때만 경보한다(마커 도입 첫날의 오경보 방지). 마커가 있으면 mtime 30일(43200분).
        if [ "$CP_N" -ge 1 ] 2>/dev/null; then
            CP_MARK="$USAGE_DIR/candidates-reviewed-last"
            if [ ! -e "$CP_MARK" ]; then
                CUT30=$(date -d '-30 days' +%Y-%m-%d 2>/dev/null || date -v-30d +%Y-%m-%d 2>/dev/null || echo "")
                if [ -n "$CP_MIN" ] && [ -n "$CUT30" ] && [[ "$CP_MIN" < "$CUT30" ]]; then
                    warn "CANDIDATES_UNJUDGED_30D: 30일 넘게 판정 0건(판정 기록 없음, 미결 ${CP_N}건) → /learn-from-feedback"
                fi
            elif [ -n "$(find "$CP_MARK" -mmin +43200 2>/dev/null)" ]; then
                warn "CANDIDATES_UNJUDGED_30D: 30일 넘게 판정 0건(미결 ${CP_N}건) → /learn-from-feedback"
            fi
        fi
    fi
fi

# WHY: 30건 문턱: 주 30회 미만 소집이면 표본이 작아 0건이 정상일 수 있어 경보를 내지 않는다(2026-09-14 신설, 09-14 실측 분모 652 / 분자 0).
if [ -f "$SPAWN_LOG" ]; then
    CUT7D=$(date -d '-7 days' +%Y-%m-%d 2>/dev/null || date -v-7d +%Y-%m-%d 2>/dev/null || echo "")
    if [ -n "$CUT7D" ]; then
        POST_N=$(awk -F'\t' -v c="$CUT7D" 'substr($1,1,10)>=c && $2=="post" {n++} END {print n+0}' "$SPAWN_LOG" 2>/dev/null); POST_N=${POST_N:-0}
        T41_N=$(grep -oE '^- [0-9]{4}-[0-9]{2}-[0-9]{2} T41:' "$CLAUDE_DIR/_audit/history.md" 2>/dev/null \
            | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | awk -v c="$CUT7D" '$1>=c {n++} END {print n+0}'); T41_N=${T41_N:-0}
        if [ "$POST_N" -ge 30 ] 2>/dev/null && [ "$T41_N" -eq 0 ] 2>/dev/null; then
            warn "T41_SILENT(최근 7일 소집 ${POST_N}건 / T41 기록 0건): 에이전트 약점 루프 정지 → agent-spawn-log.sh 자동 호출·scripts/t41-append.sh 점검"
        fi
    fi
fi

# WHY: 창은 30일(agent-eval §1.5 창 정본, 2026-09-14 신설). 무제한 누적이면 한 번 3회를
#     넘긴 축이 영구히 경보를 내 배경 소음이 되고, 개선 반영 뒤 조용해진 사실도 드러나지 않는다.
T41_REP=""
if [ -f "$T41_HIST" ]; then
    CUT30D=$(date -d '-30 days' +%Y-%m-%d 2>/dev/null || date -v-30d +%Y-%m-%d 2>/dev/null || echo "")
    # WHY: 축 키는 공백을 포함한다 — agent-eval §2 차원 이름이 «구현 정확성»·«범위 준수» 처럼 두 낱말이다
    # (2026-09-14: 훅이 쓰던 `auto` 를 실제 차원으로 바꾸면서). 종전 `[^ ]+/[^ ]+` 는 첫 낱말에서 잘려
    # 경보 문구가 «coder/구현» 으로 나왔다. 날짜와 축만 남기고 신호 본문(« — » 뒤)은 떼어 센다.
    T41_REP=$(grep -E '^- [0-9]{4}-[0-9]{2}-[0-9]{2} T41: ' "$T41_HIST" 2>/dev/null \
        | sed -E 's/^- ([0-9]{4}-[0-9]{2}-[0-9]{2}) T41: /\1\t/; s/ — .*$//; s/[[:space:]]+$//' \
        | awk -F'\t' -v c="$CUT30D" '{ if (c == "" || $1 >= c) n[$2]++ } END { for (k in n) if (n[k] >= 3) print k " ×" n[k] }' \
        | sort | head -5 | paste -sd, - 2>/dev/null)
    if [ -n "$T41_REP" ]; then
        warn "T41_REPEAT: ${T41_REP} (최근 30일) → agent-eval §3 개선 제안 게이트 진입 대상 (agents/*.md 회피 가이드 제안)"
    fi
fi

# WHY: 사람이 후보를 보는 경로가 /learn-from-feedback 수동 호출뿐이라 pending 이 55건까지 쌓여 하루 1회 5건을 요약해 보인다(2026-10-17 G2·결정 B1).
#     건수 3→5(2026-11-12): 하루 약 13건 유입에 3건/일로는 7일 만료 안에 21건밖에 못 봤다.
#     미결이 5건을 넘으면 `--skip` 을 날짜의 연중 일수로 돌려 날마다 다른 5건을 보인다. T41_REPEAT 축을 알아야 해서 그 계산 뒤에 둔다.
# REF: skills/learn-from-feedback/SKILL.md 트리거 표 «세션 시작(T03)» 행
if [ "${CP_N:-0}" -ge 1 ] 2>/dev/null && claim_daily candidates-digest; then
    T41_AXES_RAW=$(printf '%s' "$T41_REP" | sed -E 's/ ×[0-9]+//g')
    T41_AXES=""
    IFS=',' read -ra AX_ARR <<< "$T41_AXES_RAW"
    for AX1 in ${AX_ARR[@]+"${AX_ARR[@]}"}; do T41_AXES+="${T41_AXES:+,}$(norm_axis "$AX1")"; done
    DIGEST_SKIP=0
    [ "$CP_N" -gt 5 ] 2>/dev/null && DIGEST_SKIP=$(( (10#$(date +%j) % ((CP_N + 4) / 5)) * 5 ))
    DIGEST=$(bash "$CLAUDE_DIR/scripts/candidates-append.sh" oldest-pending --limit 5 --skip "$DIGEST_SKIP" --t41-axes "$T41_AXES" 2>/dev/null)
    if [ -n "$DIGEST" ]; then
        printf '%s\n' "$DIGEST" | while IFS=$'\t' read -r DID DTYPE DSUM; do echo "  · ${DID} [${DTYPE}] ${DSUM}"; done
        echo "  → 첫 작업성 응답 끝에 결정 팝업 하나로 판정을 묻는다(후보마다 accepted/rejected/보류, 모바일 모드면 AskUserQuestion) — learn-from-feedback T03 행"
    else
        release_daily candidates-digest
    fi
fi

# WHY: MEMORY.md 는 세션마다 통째로 올라가는 상시 비용이라 160줄을 넘으면 알린다(2026-10-17 G5-1). 프로젝트 폴더 이름은
#     Claude Code 와 같은 규칙(영숫자 아닌 글자 → `-`)으로 cwd 에서 만든다.
MEM_PROJ=$(printf '%s' "$PWD" | sed 's/[^A-Za-z0-9]/-/g')
MEM_DIR="$CLAUDE_DIR/projects/$MEM_PROJ/memory"
if [ -f "$MEM_DIR/MEMORY.md" ]; then
    MI_LINES=$(wc -l < "$MEM_DIR/MEMORY.md" 2>/dev/null | tr -d ' ')
    [ "${MI_LINES:-0}" -gt 160 ] 2>/dev/null && warn "MEMORY_INDEX_LONG(${MI_LINES}줄): 현재 프로젝트 MEMORY.md 가 160줄 초과 → 종료된 항목을 목차 한 줄로 묶거나 정리 (rules-lazy/memory-write.md § 자동 메모리 색인)"
fi
# WHY: decisions 정리 대상은 short-term 고정 루트(서버 등록부 paths.short_term_root, rules-lazy/memory-write.md 의 실제 기록 위치)와 cwd 기반 현재 프로젝트 두 곳이다.
# 현재 프로젝트만 정리하면 다른 프로젝트에서 시작한 세션이 고정 루트를 영영 못 치운다.
ST_ROOT=$(python3 -I "$CLAUDE_DIR/scripts/harness_registry.py" host paths.short_term_root --default '' 2>/dev/null)
ST_ROOT="${ST_ROOT/#\~/$HOME}"; ST_ROOT="${ST_ROOT%/}"
PRUNE_DIRS=()
[ -n "$ST_ROOT" ] && PRUNE_DIRS+=("$ST_ROOT")
[ "$MEM_DIR" != "$ST_ROOT" ] && PRUNE_DIRS+=("$MEM_DIR")
for PR_DIR in "${PRUNE_DIRS[@]}"; do
    [ -f "$PR_DIR/short-term/decisions.md" ] || continue
    T_NS=$(now_ns)
    PRUNE_OUT=$(bash "$CLAUDE_DIR/scripts/decisions-prune.sh" "$PR_DIR" 2>&1)
    ADDED_NS=$((ADDED_NS + $(now_ns) - T_NS))
    if [ -n "$PRUNE_OUT" ]; then
        printf '%s prune %s\n' "$(date -Is)" "$PRUNE_OUT" >> "$MAINT_LOG" 2>/dev/null
        PRUNE_N=$(printf '%s' "$PRUNE_OUT" | sed -n 's/^decisions-prune: \([0-9][0-9]*\)건.*/\1/p')
        if [ -n "$PRUNE_N" ]; then echo "ℹ DECISIONS_PRUNED(${PRUNE_N}건): $(basename "$(dirname "$PR_DIR")") 의 decisions.md 7일 초과 항목을 decisions-archive.md 로 옮김 (삭제 없음)"
        else warn "DECISIONS_PRUNE_FAIL: decisions-prune.sh 실패 → _usage/maintenance.log 확인"; fi
    fi
done

# WHY: 정본(2026-09-14 확정) 6열: 일시·프로젝트·게이트·대상·근거·주체. 열 수만 세던 판정은 3열에 비게이트 값이
#    들어와도 통과시켜, 230행 중 어느 스키마로도 집계되지 않는 행이 쌓였다(09-14 감사 §2-9·§2-10).
OV_FILE="$CLAUDE_DIR/_audit/oversight.tsv"
OV_GATES="commit launch external-send publish data-change deploy audit approve delete other"
# WHY: 어휘 검사는 정본 확정일(2026-09-14) 이상인 행에만 건다 — 그 이전 129행은 어휘 도입 전
# 기록이라 구 어휘(git-commit·decision·- 등) 그대로 두기로 했다(2026-09-14 결정). 열 수 검사도 같은 기준(2026-10-01).
OV_CUTOFF="2026-09-14"
if [ -f "$OV_FILE" ]; then
    OV_BADCOL=$(awk -F'\t' -v c="$OV_CUTOFF" 'NF>0 && NF!=6 && substr($1,1,10)>=c {print NR}' "$OV_FILE" 2>/dev/null)
    OV_BADGATE=$(awk -F'\t' -v g=" $OV_GATES " -v c="$OV_CUTOFF" 'NF==6 && substr($1,1,10)>=c && index(g, " " $3 " ")==0 {print NR}' "$OV_FILE" 2>/dev/null)
    # WHY: 행 번호는 앞 8개만 — 경보 한 줄이 세션 시작 주입을 삼키지 않게 한다(토큰 설계 상수 유지).
    if [ -n "$OV_BADCOL" ]; then
        N=$(printf '%s\n' "$OV_BADCOL" | wc -l | tr -d ' ')
        warn "OVERSIGHT_FORMAT(열 수 ${N}행): _audit/oversight.tsv 6열 아님 — 행 $(printf '%s\n' "$OV_BADCOL" | head -8 | tr '\n' ',' | sed 's/,$//')$([ "$N" -gt 8 ] && echo ' 외') → scripts/oversight-fix-5col.py 확인"
    fi
    if [ -n "$OV_BADGATE" ]; then
        N=$(printf '%s\n' "$OV_BADGATE" | wc -l | tr -d ' ')
        warn "OVERSIGHT_FORMAT(게이트 어휘 ${N}행): 3열이 허용 어휘(${OV_GATES}) 밖 — 행 $(printf '%s\n' "$OV_BADGATE" | head -8 | tr '\n' ',' | sed 's/,$//')$([ "$N" -gt 8 ] && echo ' 외') → 이후 기록은 scripts/oversight-append.sh 로"
    fi
fi

NTFY_CHECK_DAY="${NTFY_DAY:-$(date -u +%Y%m%d 2>/dev/null)}"
[[ "$NTFY_CHECK_DAY" =~ ^[0-9]{8}$ ]] || NTFY_CHECK_DAY=$(date -u +%Y%m%d 2>/dev/null)
NTFY_HALT="$USAGE_DIR/ntfy-$NTFY_CHECK_DAY.halt"
NTFY_QUEUE="$USAGE_DIR/ntfy-queue.tsv"
if [ -f "$NTFY_HALT" ] || [ -s "$NTFY_QUEUE" ]; then
    NTFY_COUNT=0
    NTFY_CAP=200
    [ -f "$USAGE_DIR/ntfy-$NTFY_CHECK_DAY.count" ] &&
        read -r NTFY_COUNT < "$USAGE_DIR/ntfy-$NTFY_CHECK_DAY.count"
    [ -f "$USAGE_DIR/ntfy-cap" ] && read -r NTFY_CAP < "$USAGE_DIR/ntfy-cap"
    [[ "$NTFY_COUNT" =~ ^[0-9]+$ ]] || NTFY_COUNT=0
    [[ "$NTFY_CAP" =~ ^[0-9]+$ ]] || NTFY_CAP=200
    NTFY_QUEUED=0
    [ -f "$NTFY_QUEUE" ] && NTFY_QUEUED=$(awk 'END {print NR+0}' "$NTFY_QUEUE" 2>/dev/null)
    [[ "$NTFY_QUEUED" =~ ^[0-9]+$ ]] || NTFY_QUEUED=0
    # WHY: 중단은 NTFY_HALT_RETRY_SEC(기본 3600, 0=하루 통째) 초 안에 갱신된 halt 만 유효(claude-notify.sh halt_active 와 같은 판정)
    NTFY_STOP="no"
    if [ -f "$NTFY_HALT" ]; then
        NTFY_RETRY="${NTFY_HALT_RETRY_SEC:-3600}"
        [[ "$NTFY_RETRY" =~ ^[0-9]{1,6}$ ]] || NTFY_RETRY=3600
        NTFY_RETRY=$((10#$NTFY_RETRY))
        NTFY_HALT_MTIME=$(stat -c %Y "$NTFY_HALT" 2>/dev/null || echo 0)
        if [ "$NTFY_RETRY" -eq 0 ]; then
            NTFY_STOP="42908"
        elif [ $(( $(date +%s) - NTFY_HALT_MTIME )) -lt "$NTFY_RETRY" ]; then
            NTFY_STOP="42908(다음 시도 $(TZ=Asia/Seoul date -d "@$((NTFY_HALT_MTIME + NTFY_RETRY))" +%H:%M 2>/dev/null) KST)"
        fi
    fi
    warn "NTFY_QUOTA: UTC ${NTFY_CHECK_DAY} 수락 ${NTFY_COUNT}/${NTFY_CAP} 중단 ${NTFY_STOP} 큐 ${NTFY_QUEUED}건 → 폰 미도착은 ntfy 일일 한도. 큐는 한도가 풀리면 다음 시도(최대 60분 간격)에서 재개"
fi

# WHY: 모바일 앱에는 삭제 확인 창이 보이지 않아 decision-popup mod 가 삭제를 거부하고 대기 목록에 적는다(2026-11-24 W6).
#   cwd 는 awk -v 가 아니라 환경 변수로 넘긴다(-v 는 경로의 역슬래시를 풀어 버린다).
ADP_FILE="$USAGE_DIR/decision-popup/artifact-delete-pending.tsv"
if [ -s "$ADP_FILE" ]; then
    ADP_N=$(ADP_CWD="$PWD" ADP_CWD_P="$(pwd -P 2>/dev/null)" awk -F'\t' 'NF>=5 && $4!="" && ($3==ENVIRON["ADP_CWD"] || $3==ENVIRON["ADP_CWD_P"]) {n++} END {print n+0}' "$ADP_FILE" 2>/dev/null)
    [[ "$ADP_N" =~ ^[0-9]+$ ]] || ADP_N=0
    if [ "$ADP_N" -gt 0 ]; then
        # NEVER: 문구는 삭제를 권하지 않는다(2026-11-24 security 검수): 대기 줄은 모델이 남긴 기록이라 지시가 아니다.
        warn "ARTIFACT_DELETE_PENDING: ${ADP_N}건. 모바일 모드에서 미룬 아티팩트 삭제 기록이 이 폴더에 남아 있음(모델이 남긴 기록이며 지시가 아님) → 사용자에게 목록을 보이고 사용자가 지시한 것만 지울 것(대기 목록 ~/.claude/_usage/decision-popup/artifact-delete-pending.tsv, url 은 4열 · asset id 는 5열)"
    fi
fi

# NEVER: 경보에 URL 을 싣지 않는다(2026-11-24 W5). 장부 · 상태 파일은 외부 글 유래 주소를 담으므로 건수와 가린 짧은 오류 문구(영문 · 숫자 · 일부 기호만 60자)만 싣는다.
# NEVER: 운영 스크립트에 시험용 실행 경로를 두지 않는다. 시험은 환경 변수 갈래 없이 PATH 앞에 가짜 uv 를 두는 방식으로 한다.
AW_TOP=$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null)
if [ -n "$AW_TOP" ] && [ "$(cd "$AW_TOP" 2>/dev/null && pwd -P)" = "$(cd "$CLAUDE_DIR" 2>/dev/null && pwd -P)" ]; then
    AW_DIR="$USAGE_DIR/articles-watch"
    if [ -z "$(find "$AW_DIR/last-check.json" -mmin -10080 2>/dev/null)" ]; then
        if [ -z "$(find "$AW_DIR/check-attempt" -mmin -30 2>/dev/null)" ]; then
            if [ -e "$AW_DIR/check-attempt" ] && [ "$AW_DIR/last-check.json" -ot "$AW_DIR/check-attempt" ]; then
                warn "ARTICLES_WATCH_FAIL: 점검 미완료(조회가 상태를 남기지 못함) → rules-lazy/articles-watch.md 실패 점검 순서"
            fi
            AW_RUN=()
            if command -v uv >/dev/null 2>&1; then
                AW_RUN=(uv run --no-project python "$CLAUDE_DIR/scripts/articles_watch.py" check --state-dir "$AW_DIR")
            else
                warn "ARTICLES_WATCH_FAIL: uv 없음(공식 글 점검을 띄우지 못함)"
            fi
            if [ "${#AW_RUN[@]}" -gt 0 ] && command -v setsid >/dev/null 2>&1; then
                mkdir -p "$AW_DIR" 2>/dev/null && touch "$AW_DIR/check-attempt" 2>/dev/null
                AW_WRAP=()
                command -v timeout >/dev/null 2>&1 && AW_WRAP+=(timeout 60)
                setsid nohup ${AW_WRAP[@]+"${AW_WRAP[@]}"} "${AW_RUN[@]}" >/dev/null 2>&1 < /dev/null &
            fi
        fi
    else
        AW_NEW=0
        [ -f "$AW_DIR/ledger.tsv" ] && AW_NEW=$(awk -F'\t' 'NR>1 && $3=="new" {n++} END {print n+0}' "$AW_DIR/ledger.tsv" 2>/dev/null)
        [[ "$AW_NEW" =~ ^[0-9]+$ ]] || AW_NEW=0
        [ "$AW_NEW" -gt 0 ] && warn "ARTICLES_NEW: ${AW_NEW}건 → rules-lazy/articles-watch.md 절차(searcher 정독 → 반영 후보 결정 → articles_watch.py mark)"
        if grep -qE '^ "ok": false,?$' "$AW_DIR/last-check.json" 2>/dev/null; then
            AW_ERR=$(sed -n 's/^ "error": "\(.*\)",\{0,1\}$/\1/p' "$AW_DIR/last-check.json" 2>/dev/null | head -n 1 | tr -cd 'A-Za-z0-9 _=<>()-' | cut -c1-60)
            warn "ARTICLES_WATCH_FAIL: ${AW_ERR:-사유 없음} (마지막 조회 실패, 장부는 바뀌지 않음) → rules-lazy/articles-watch.md 실패 점검 순서"
        fi
    fi
fi

# NEVER: 저장소 파일의 글을 경보에 그대로 내보내지 않는다(registered 는 경과 일수만, 2026-11-24 W4 · W11).
# NEVER: 경보 문자열에는 백틱을 쓰지 않는다(커밋 훅의 없는 파일 참조 검사와 부딪힌다).
if [ -n "$AW_TOP" ] && [ "$(cd "$AW_TOP" 2>/dev/null && pwd -P)" = "$(cd "$CLAUDE_DIR" 2>/dev/null && pwd -P)" ]; then
    APG_CFG="$CLAUDE_DIR/config/agent-prompt-gate.json"
    APG_DAYS=""
    if [ -f "$APG_CFG" ] && command -v jq >/dev/null 2>&1; then
        APG_REG=$(jq -r '.registered | strings' "$APG_CFG" 2>/dev/null)
        if [[ "$APG_REG" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
            APG_S=$(date -d "$APG_REG" +%s 2>/dev/null)
            [[ "$APG_S" =~ ^[0-9]+$ ]] && APG_DAYS=$(( ($(date +%s) - APG_S) / 86400 ))
        fi
    fi
    if [ -n "$APG_DAYS" ]; then
        APG_MODE=$(jq -r '.mode | strings' "$APG_CFG" 2>/dev/null)
        APG_DONE=$(jq -r '.report_7d_done == true' "$APG_CFG" 2>/dev/null)
        if [ "$APG_DAYS" -ge 7 ] && [ "$APG_MODE" = observe ] && [ "$APG_DONE" != true ]; then
            warn "AGENT_PROMPT_GATE_REPORT_DUE: 등록 ${APG_DAYS}일째 → python3 ~/.claude/scripts/agent-prompt-gate.py --report --days 7 표를 사용자에게 보고하고 enforce 전환 여부를 확인(자동 전환 없음, 보고 뒤 config 의 report_7d_done 을 true 로)"
        fi
        if [ "$APG_DAYS" -ge 30 ] && [ ! -e "$USAGE_DIR/context-loss-report-last" ]; then
            warn "CONTEXT_LOSS_REPORT_DUE: 등록 ${APG_DAYS}일째 → rules-lazy/agent-eval.md 의 계수 명령으로 «맥락 누락 · 방향 이탈» 건수를 사용자에게 보고(보고 뒤 touch ~/.claude/_usage/context-loss-report-last)"
        fi
    fi
    MR_AGE=$(age_days "$USAGE_DIR/memory-review-last")
    if [ "$MR_AGE" -lt 0 ]; then
        warn "MEMORY_REVIEW_DUE: 메모리 · 지식 노트 정리 한 번도 안 함 → rules-lazy/memory-write.md § 정기 정리 (30일)"
    elif [ "$MR_AGE" -gt 30 ]; then
        warn "MEMORY_REVIEW_DUE: 메모리 · 지식 노트 정리 ${MR_AGE}일째 → rules-lazy/memory-write.md § 정기 정리 (30일)"
    fi
    # REF: intent/2026-11-24-always-on-rule-reduction.md (상시 규칙 축소 실험 0단계)
    # NEVER: 파일 글을 그대로 내보내지 않는다. label · 날짜 형식이 맞을 때만 값을 싣고 앞 200자만 읽는다.
    RRW="$USAGE_DIR/rule-reduction-window"
    if [ -f "$RRW" ] && [ ! -L "$RRW" ]; then
        RRW_LABEL="" RRW_END="" RRW_EXTRA=""
        IFS=$'\t' read -r -n 200 RRW_LABEL RRW_END RRW_EXTRA < "$RRW" 2>/dev/null
        # WHY: CRLF 로 저장된 표지에서 경보가 조용히 빠지지 않게 줄 끝 CR 하나를 뗀다(2026-11-24 qa)
        RRW_END="${RRW_END%$'\r'}" RRW_EXTRA="${RRW_EXTRA%$'\r'}"
        if [[ "$RRW_LABEL" =~ ^[A-Za-z0-9._-]{1,40}$ ]] && [[ "$RRW_END" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && [ -z "$RRW_EXTRA" ] \
            && date -d "$RRW_END" +%s >/dev/null 2>&1 && [[ ! "$RRW_END" > "$(date +%F)" ]]; then
            warn "RULE_REDUCTION_WINDOW_DUE: ${RRW_LABEL} 창 끝(${RRW_END}) → rule_reduction_metrics.py 로 집계"
        fi
    fi
fi

# WHY: W14 성공 기준 6 (intent/2026-11-24-harness-review-six-items.md). 최근 24시간 _usage/hook-runs 의 verdict error · killed 를
# 훅 이름별로 세어 하네스 저장소 세션(위 AW_TOP 판정과 같음)에만 알린다. 시각 비교는 기록과 같은 지역 시각대의 글자 비교다.
# NEVER: 기록 글을 그대로 경보에 싣지 않는다. 이름은 [A-Za-z0-9_.:-] 만 남기고, 일반 파일이 아닌 기록 자리는 읽지 않는다(FIFO 는 awk 를 멈춘다).
if [ -n "$AW_TOP" ] && [ "$(cd "$AW_TOP" 2>/dev/null && pwd -P)" = "$(cd "$CLAUDE_DIR" 2>/dev/null && pwd -P)" ]; then
    HR_SINCE=$(date -d '24 hours ago' +%Y-%m-%dT%H:%M:%S%z 2>/dev/null)
    HR_FILES=()
    for HR_DAY in "$(date -d yesterday +%F 2>/dev/null)" "$TODAY"; do
        HR_F="$USAGE_DIR/hook-runs/$HR_DAY.tsv"
        [ -f "$HR_F" ] && [ ! -L "$HR_F" ] && HR_FILES+=("$HR_F")
    done
    if [ -n "$HR_SINCE" ] && [ "${#HR_FILES[@]}" -gt 0 ]; then
        HR_OUT=$(awk -F'\t' -v since="$HR_SINCE" 'NF == 9 && $1 >= since && ($8 == "error" || $8 == "killed") {
                h = $5; gsub(/[^A-Za-z0-9_.:-]/, "", h); n[substr(h, 1, 64)]++ }
            END { for (k in n) printf "%s=%d\n", k, n[k] }' "${HR_FILES[@]}" 2>/dev/null \
            | sort -t= -k2,2nr -k1,1 | head -n 10 | paste -sd ' ' -)
        [ -n "$HR_OUT" ] && warn "HOOK_ERRORS_24H: ${HR_OUT} → python3 -I ~/.claude/scripts/harness_log_report.py --days 1"
    fi
fi

# WHY: 2026-11-24 사용자 지시 «나중에 할 일은 꼭 진행할 수 있도록» 의 자리가 knowledge/harness/code-todo.md 표다. 하네스 저장소 세션
# (위 AW_TOP 판정과 같음)에서 id 칸이 CT- 로 시작하는 행을 할 일 행으로 보고, 오른쪽부터 훑어 처음 만나는 칸이 정확히 open 이면 센다.
# 칸 수 · 끝 | 유무 · 글 속 | 에 흔들리지 않게 하려는 것이다(2026-11-24 qa). open · done 칸이 없는 CT- 행은 형식 오류로 따로 센다.
# 적은 날(둘째 칸)이 YYYY-MM-DD 꼴인 것 가운데 가장 이른 날을 알린다.
# NEVER: 표의 글을 경보에 싣지 않는다(건수와 날짜만). 링크이거나 일반 파일이 아니면 읽지 않는다.
CT_FILE="$CLAUDE_DIR/knowledge/harness/code-todo.md"
if [ -n "$AW_TOP" ] && [ "$(cd "$AW_TOP" 2>/dev/null && pwd -P)" = "$(cd "$CLAUDE_DIR" 2>/dev/null && pwd -P)" ] \
    && [ -f "$CT_FILE" ] && [ ! -L "$CT_FILE" ]; then
    CT_N="" CT_BAD="" CT_OLD=""
    read -r CT_N CT_BAD CT_OLD < <(awk -F'|' '/^[ \t]*\|/ {
            id = $2; gsub(/^[ \t]+|[ \t\r]+$/, "", id); if (id !~ /^CT-/) next
            st = ""
            for (i = NF; i >= 3; i--) { c = $i; gsub(/^[ \t\r]+|[ \t\r]+$/, "", c); if (c == "open" || c == "done") { st = c; break } }
            if (st == "") { bad++; next }
            if (st != "open") next
            n++; d = $3; gsub(/^[ \t]+|[ \t]+$/, "", d)
            if (d ~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/ && (old == "" || d < old)) old = d }
        END { if (n || bad) print n + 0, bad + 0, (old == "" ? "-" : old) }' "$CT_FILE" 2>/dev/null)
    if [[ "$CT_N" =~ ^[0-9]+$ ]] && [[ "$CT_BAD" =~ ^[0-9]+$ ]]; then
        CT_MSG="${CT_N}건"
        [[ "$CT_OLD" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && CT_MSG="${CT_MSG}(가장 오래된 것 ${CT_OLD})"
        [ "$CT_BAD" -gt 0 ] && CT_MSG="${CT_MSG} · 형식 오류 ${CT_BAD}행"
        warn "CODE_TODO_OPEN: ${CT_MSG} → knowledge/harness/code-todo.md"
    fi
fi

# WHY: 하네스 커밋은 보류되고 매니저가 모든 작업을 마친 뒤 release 로 한 번 내보낸다(intent/2026-10-21-harness-change-propagation-gate.md 개정 3,
# 2026-11-24 사용자 지시). 보류가 잊히지 않게 하네스 저장소 세션(위 CODE_TODO_OPEN 과 같은 판정)에서 건수와 가장 오래된 시각을 알린다.
# NEVER: 보류 줄의 글(제목 · 작성 세션)을 경보에 싣지 않는다. 보류 파일이 링크이거나 일반 파일이 아니면 읽지 않는다(propagate-queue.sh held 가 거부).
if [ -n "$AW_TOP" ] && [ "$(cd "$AW_TOP" 2>/dev/null && pwd -P)" = "$(cd "$CLAUDE_DIR" 2>/dev/null && pwd -P)" ]; then
    PH_OUT=$(bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/propagate-queue.sh" held 2>/dev/null)
    PH_N="${PH_OUT%%$'\t'*}"
    PH_OLD="${PH_OUT#*$'\t'}"
    if [[ "$PH_N" =~ ^[0-9]+$ ]] && [ "$PH_N" -gt 0 ]; then
        PH_MSG="${PH_N}건"
        [[ "$PH_OLD" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}$ ]] && PH_MSG="${PH_MSG}(가장 오래된 것 ${PH_OLD})"
        warn "PROPAGATE_HELD: ${PH_MSG} → 작업이 다 끝났으면 bash scripts/propagate-queue.sh release"
    fi
fi

# WHY: W14 전제 «기록 보존 180일» (intent/2026-11-24-harness-review-six-items.md 전제 표). 하루 1회, 다섯 기록 폴더에서 이름이
# YYYY-MM-DD.tsv 이고 그 날짜가 180일보다 앞선 일반 파일만 지운다. 표지 _usage/.harness-logs-pruned 에 오늘 날짜를 쓴다.
HL_MARK="$USAGE_DIR/.harness-logs-pruned"
HL_LAST=""
[ -f "$HL_MARK" ] && [ ! -L "$HL_MARK" ] && IFS= read -r -t 1 HL_LAST < "$HL_MARK"
if [ "$HL_LAST" != "$TODAY" ]; then
    HL_CUT=$(date -d '180 days ago' +%F 2>/dev/null)
    for HL_SUB in hook-runs tool-use rule-reads agent-runs session-events; do
        [ -n "$HL_CUT" ] && [ -d "$USAGE_DIR/$HL_SUB" ] && [ ! -L "$USAGE_DIR/$HL_SUB" ] || continue
        for HL_F in "$USAGE_DIR/$HL_SUB"/????-??-??.tsv; do
            HL_N=${HL_F##*/}
            HL_N=${HL_N%.tsv}
            if [[ $HL_N =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && [[ $HL_N < $HL_CUT ]] && [ -f "$HL_F" ] && [ ! -L "$HL_F" ]; then
                rm -f -- "$HL_F"
            fi
        done
    done
    # NEVER: write the mark through a link (a dangling one too, where -e is false) or into a FIFO · folder.
    if [ -n "$HL_CUT" ] && [ ! -L "$HL_MARK" ] && { [ ! -e "$HL_MARK" ] || [ -f "$HL_MARK" ]; }; then
        printf '%s\n' "$TODAY" > "$HL_MARK" 2>/dev/null
    fi
fi

# WHY: npm 전역 claude 가 낡은 판에 머물면 임시 데몬이 낡은 판으로 세션을 띄워 상태창·최신 모델이 사라진다(2026-11-13).
CLI_STALE_SH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/claude-cli-stale-check.sh"
if [ -f "$CLI_STALE_SH" ]; then
    CLI_STALE_OUT=$(bash "$CLI_STALE_SH" 2>/dev/null || true)
    # WHY: 세션 쪽과 systemd 쪽 두 줄이 나올 수 있어 줄마다 경보로 낸다(2026-11-16, 합치면 둘째 줄에 ⚠ 가 안 붙음).
    while IFS= read -r CLI_STALE_LINE; do
        [ -n "$CLI_STALE_LINE" ] && warn "$CLI_STALE_LINE"
    done <<< "$CLI_STALE_OUT"
fi

bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/login-expiry-export.sh" >/dev/null 2>&1 || true

bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/audit-history-autocommit.sh" >/dev/null 2>&1 || true

[ "$ADDED_NS" -gt 0 ] && printf '%s added_ms=%s\n' "$(date -Is)" "$((ADDED_NS / 1000000))" >> "$MAINT_LOG" 2>/dev/null
[ "$ISSUES" -eq 0 ] && echo "USAGE OK"
exit 0
