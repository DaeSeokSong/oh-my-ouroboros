#!/usr/bin/env bash
# harness-usage-check.sh — "구축됐지만 사용 안 되는" 인프라 감지 (T03 세션 시작 시 1회 호출)
#
# 설계 근거 (2026-07-09, 판단 근거 이식):
#   하네스의 반복 결함 5번째 패턴 = "구축-미사용 rot" — 인프라를 만들고 루프에 정의까지 해도,
#   실제 사용 여부를 아무도 추적하지 않으면 조용히 썩고 유지 토큰만 낭비된다 (실측 사례:
#   harness-bench가 정의된 지 수개월간 미실행 → Step 1 축약 루프가 영구 블로킹 / graphify
#   query 사용 추적 부재 → §5 "5회마다 점검"이 측정 불가).
#   원칙: **cadence(주기)-구동 인프라는 신선도 마커 필수, event-구동 인프라는 트리거 배선만**.
#   이 스크립트는 cadence-구동 항목의 신선도만 검사한다 — event-구동(citation-log, rollback,
#   killswitch 등)은 이벤트가 없으면 미사용이 정상이므로 검사하지 않는다.
#
# 토큰 설계: 검사는 전부 bash(토큰 0), 모델에게는 **이상 항목만** 1줄씩 노출.
#   전부 정상이면 "USAGE OK" 한 줄 — T03에서 모델이 읽는 비용을 상수로 고정한다.
#   (이 스크립트가 mem0-auto T03의 인라인 체크 3종을 흡수 — always-on 텍스트 축소와 한 쌍)
#
# 사용 마커 규약: 각 도구는 실행 시 ~/.claude/_usage/<이름>-last 를 touch 한다 (gitignore).
#   마커가 없으면 "한 번도 실행 안 됨"으로 판정 가능 — 부재 자체가 신호다.

# 2026-10-17 G2·G5-1 추가분 (모두 bash, SessionStart 경로라 `uv run`·python3 금지, 추가 비용 목표 +0.3초):
#   · 후보 대장 7일 pending 자동 만료(candidates-append.sh expire) · crosscheck 7일 초과 시 백그라운드 자동 실행
#   · CANDIDATES_PENDING 아래 하루 1회 오래된 후보 3건 요약(digest) · 미결 T41 후보가 있으면 하루 1회 후보 note 에 효과 기록(effect, T41_REPEAT 와 무관)
#   · MEMORY.md 160줄 경보 · decisions.md 7일 초과분 아카이브(decisions-prune.sh)
#   원칙: 판정(accepted/rejected)을 새로 내리지는 않는다(learner 불변식 «자동 적용 없음»). 상태는 두 경우에만 바뀐다: 만료(pending→expired)와
#   재시도 큐 배수(post-commit 이 못 한 `set accepted` 를 다시 시도, 커밋 trailer 가 이미 준 판정의 재현)이고, 효과 기록은 note 만 쓴다.
#   expire·prune 의 stdout 은 `_usage/maintenance.log` 로 보내고 모델 입력에는 변경 건수·실패 한 줄만 낸다.
#   추가분 계측: expire·prune 구간의 `date +%s%N` 차를 합쳐 maintenance.log 에 `added_ms=` 로 남긴다(git fetch 5초 분산에 묻히지 않게 구간만 잰다).

set -uo pipefail
CLAUDE_DIR="$HOME/.claude"
USAGE_DIR="$CLAUDE_DIR/_usage"
mkdir -p "$USAGE_DIR" 2>/dev/null
ISSUES=0
MAINT_LOG="$USAGE_DIR/maintenance.log"
# maintenance.log 는 세션마다 몇 줄씩 늘어난다: 1000줄을 넘으면 마지막 500줄만 남긴다(tmp→mv, 실패는 무시).
if [ -f "$MAINT_LOG" ] && [ "$(wc -l < "$MAINT_LOG" 2>/dev/null || echo 0)" -gt 1000 ]; then
    if ! { tail -n 500 "$MAINT_LOG" > "$MAINT_LOG.tmp.$$" 2>/dev/null && mv "$MAINT_LOG.tmp.$$" "$MAINT_LOG" 2>/dev/null; }; then rm -f "$MAINT_LOG.tmp.$$" 2>/dev/null; fi
fi
TODAY=$(date +%Y-%m-%d)
ADDED_NS=0
# 하루 1회 일은 `_usage/<이름>-<날짜>.d` 디렉터리를 mkdir 로 선점한 세션만 한다. 마커 파일을 «읽고 판단하고 쓰기» 하면 병렬 세션이 둘 다 통과한다(2026-10-17 외부 검토).
claim_daily() { mkdir "$USAGE_DIR/$1-$TODAY.d" 2>/dev/null; }
release_daily() { rmdir "$USAGE_DIR/$1-$TODAY.d" 2>/dev/null; return 0; }
# T41 효과 기록 선점(2026-10-17 Grok 4차): mkdir 로 선점하되, 선점 디렉터리가 있는데 done 이 없고 mtime 이 10분 넘었으면(기록 세션이 죽었거나 직전 기록이 실패)
# 뒤 세션이 승계한다(디렉터리 mtime 을 갱신해 동시에 둘이 승계하지 않게 하고, 직전 실패 표지 failed 는 지운다). 승계 경합은 set-note-batch 가 멱등이라 무해하다.
# 승계에 성공하면 전역 EFF_TAKEOVER=1 을 둔다: 승계로 mtime 이 갱신돼 같은 세션의 만료 검사가 «10분 미경과» 로 보므로, 이번 기록이 또 실패하면(done 없음)
# --force 만료의 근거로 쓴다(아래 만료 전 점검 ②). 그러지 않으면 기록이 계속 실패할 때 만료(T12·T40 포함)가 영영 멈춘다.
# 단 승계 턴의 --force 만료는 «효과 기록 실패» 에만 적용한다. done 생성 실패·날짜 계산 실패·미결 집계 실패는 승계 턴에서도 그 턴 만료를 보류한다.
EFF_TAKEOVER=0; EFF_DONE_FAIL=0; EFF_NO_CUT=0
mark_effect_done() {  # 효과 기록 완료 표지. 못 만들면(디스크 풀 등) failed(원인 «done 생성 실패»)로 보내고 EFF_DONE_FAIL=1 — 그 턴은 만료하지 않는다(승계 턴의 --force 만료도 금지)
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
norm_axis() {  # role/dim → 역할 부분만 normalize_role 로 정규화(표 밖이면 그대로). 후보·history 의 줄임말 역할(sec-g1)을 같은 축으로 비교하려는 용도
    local role n
    case "$1" in */*) ;; *) printf '%s' "$1"; return ;; esac
    role="${1%%/*}"; n=$(normalize_role "$role"); [ -n "$n" ] || n="$role"
    printf '%s/%s' "$n" "${1#*/}"
}
# 어제 이전 선점 디렉터리는 비어 있으니 치운다(rmdir 라서 내용이 있으면 남는다).
find "$USAGE_DIR" -mindepth 2 -maxdepth 2 -type f \( -name 'done' -o -name 'failed' \) -path '*/t41-effect-*.d/*' ! -path "*-$TODAY.d/*" -delete 2>/dev/null
find "$USAGE_DIR" -maxdepth 1 -type d \( -name 'candidates-digest-*.d' -o -name 't41-effect-*.d' \) ! -name "*-$TODAY.d" -exec rmdir {} + 2>/dev/null
HAVE_TIMEOUT=0
command -v timeout >/dev/null 2>&1 && HAVE_TIMEOUT=1
# 역할 정규화 정본은 role-alias.sh(t41-append.sh 와 공유). 없으면 이름을 그대로 쓴다.
if [ -f "$CLAUDE_DIR/scripts/role-alias.sh" ]; then
    # shellcheck source=/dev/null
    . "$CLAUDE_DIR/scripts/role-alias.sh"
else
    normalize_role() { printf '%s' "$1"; }
fi
now_ns() {  # 나노초(GNU date). BSD 처럼 %N 미지원이면 0 → 계측만 건너뛴다
    local t; t=$(date +%s%N 2>/dev/null); [[ "$t" =~ ^[0-9]+$ ]] && echo "$t" || echo 0
}

# (2026-10-01 감사 P6) 여기서 `git add settings.json` 으로 stat-dirty 소음을 지우던 줄을 뺐다.
# 읽기 전용이어야 할 점검이 세션마다 색인을 바꾸면 사용자가 스테이징한 상태와 섞이고, 커밋 시점에
# settings.json 이 «수정됨»으로 보이는 원인이 된다. model 키는 clean 필터가 이미 diff 에서 제외한다.

warn() { echo "⚠ $1"; ISSUES=$((ISSUES + 1)); }

age_days() {  # $1=파일, 출력: 경과 일수 (없으면 -1). stat은 GNU/BSD 겸용 (Codex 교차검증 P2)
    if [ -e "$1" ]; then
        local m
        m=$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0)
        echo $(( ($(date +%s) - m) / 86400 ))
    else
        echo -1
    fi
}
age_min() {  # $1=파일, 출력: 경과 분 (없으면 -1)
    if [ -e "$1" ]; then
        local m
        m=$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0)
        echo $(( ($(date +%s) - m) / 60 ))
    else
        echo -1
    fi
}

# 1) 하네스 감사 주기 (30일) — 기존 T03 인라인 체크 흡수
A=$(age_days "$CLAUDE_DIR/_audit/last-run")
# last-run은 머신 로컬(gitignore) — 감사는 repo 단위이므로 git 추적되는 history.md의
# 최신 일자와 함께 보고 더 새로운 쪽을 쓴다 (2026-07-13 _audit 추적 전환과 한 쌍).
# sort|tail-1 = 최대 일자 (2026-07-31 감사 교정: history.md는 하단 append라 -om1 첫 매치가
# 최상단(최고령) 항목을 "최신"으로 오판 — 순서 무관하게 최대값을 취한다).
# 2026-09-14 교정 2건: ① 절 표기가 `### YYYY-MM-DD` 로 바뀌었는데 `## ` 만 보아 09-06·09-14 감사를
# 못 봤다 ② 이 폴백이 last-run 부재일 때만 돌아, 오래된 last-run 이 있으면 새 감사 기록이 무시됐다.
# 2026-09-14 교정 3: history.md 의 날짜 절에는 감사 말고 수리·다이어트 기록도 들어온다. 전부 세면
# 규칙을 고친 날마다 감사 시계가 리셋돼 «30일째 감사 없음»이 영영 안 뜬다 — 제목에 감사·점검 계열
# 낱말이 있는 절만 감사로 친다(재감사 §3).
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

# 2) 온톨로지 타이머 — 기존 T03 게이트 흡수 (미활성 + mem0 미결정이면 3택: code-graph §8)
if command -v systemctl >/dev/null 2>&1; then
    if ! systemctl --user is-enabled claude-ontology-refresh.timer >/dev/null 2>&1; then
        warn "TIMER_UNSET: 온톨로지 타이머 미활성 → mem0 결정 확인 후 3택 게이트 (code-graph.md §8)"
    else
        # 활성인데 성공이 오래 없음 = 조용한 고장. "성공 존재 여부"가 아니라 "마지막 성공의
        # 시점"으로 판정 — 존재 여부로 통과시키면 과거 성공 1회가 이후 연속 실패를 영구히
        # 가린다 (Codex 교차검증 P2 반영, 2026-07-09). 일간 타이머 + 여유 1일 = 2일 임계 (2026-07-13 주간→일간 전환).
        L="$CLAUDE_DIR/ontology-refresh.log"
        if [ -f "$L" ]; then
            # "finalize 완료"는 pipeline finalize 성공 종점에서 무조건 찍히는 유일 마커.
            # "변경 없음"은 detect 단계의 "시맨틱 변경 없음"과도 매칭돼 실패를 성공으로 오인시킴 (qa 정독 P1)
            LAST_OK_LINE=$(grep -E "finalize 완료" "$L" 2>/dev/null | tail -1)
            # 미push 백로그로 인한 정상 skip은 침묵 사망이 아니다 — 마지막 이벤트가 skip이면
            # TIMER_SILENT를 억제 (push 대기는 PUSH_NEEDED 경보가 담당). 일간 전환으로 push보다
            # 빌드가 잦아져 skip이 정상 상태가 됨 (2026-07-13 주간→일간과 한 쌍).
            LAST_EVENT=$(grep -E "finalize 완료|이번 주기 skip" "$L" 2>/dev/null | tail -1)
            if [ -n "$LAST_EVENT" ] && [ "$LAST_EVENT" != "$LAST_OK_LINE" ]; then
                :  # 최신 이벤트가 push-gate skip — 경보 없음
            elif [ -n "$LAST_OK_LINE" ]; then
                LAST_OK_TS=$(printf '%s' "$LAST_OK_LINE" | sed -E 's/^\[([^]]+)\].*/\1/')
                # GNU date -d → BSD date -j 순서 폴백. 둘 다 실패하면 경고 — 감지기의 파싱 실패가
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
                # 성공 기록 없음 + 로그 존재 = 실행됐으나 전부 실패. 로그 mtime(LA)은 실패로도 갱신돼
                # 마스킹되므로(2026-07-18 Codex) 실행 횟수로 판정: '갱신 시작' ≥2회면 반복 실패 확정
                # (1회는 첫 실행 진행 중일 수 있어 유예).
                RUN_COUNT=$(grep -c '갱신 시작' "$L" 2>/dev/null); RUN_COUNT=${RUN_COUNT:-0}
                [ "$RUN_COUNT" -ge 2 ] && warn "TIMER_SILENT: 타이머 ${RUN_COUNT}회 실행했으나 성공 기록 0 → ontology-refresh.log 확인"
            fi
        else
            # 타이머는 활성인데 로그 자체가 없음 = 한 번도 못 돌았거나 로그 경로가 어긋남. 침묵하면 감시기가 침묵 사망한다.
            warn "TIMER_SILENT(로그 부재): 온톨로지 타이머 활성이나 ontology-refresh.log 없음 → 타이머 동작·로그 경로 점검"
        fi
    fi
fi

# 3) push 권장 — 하네스 변경(룰·스킬·스크립트·vault 전부)이 1커밋이라도 원격 미반영이면 알림
#    (2026-07-10 사용자 확정: 온톨로지뿐 아니라 하네스 자체 변경도 모두 — vault 포함 여부는 병기)
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

# 3b) 온톨로지 커밋 대기 — 나이틀리는 스테이징+메시지 준비까지만 (2026-08-05 자동 커밋 폐지)
if [ -f "$CLAUDE_DIR/graphify-out/.commit-msg" ] && ! git -C "$CLAUDE_DIR" diff --quiet HEAD -- graphify-out/ 2>/dev/null; then
    warn "ONTOLOGY_COMMIT_PENDING: 나이틀리 산출물 커밋 대기 → git pull 확인 후 git commit -F graphify-out/.commit-msg -- graphify-out/ && git push"
fi

# 3c) pull 권장 — 원격 실비교 우선 (2026-07-10 사용자 제안): 세션 시작 시 best-effort fetch
#     (비대화형·5초 제한 — 세션 시작 지연 방지)로 remote와 비교, 새 커밋 있으면 pull 권장.
#     자격증명 캐시가 없는 서버에선 fetch가 조용히 실패 → 소비 서버 한정 로컬 휴리스틱(8일)로 강등.
#     권장 채널은 세션 응답만 — ntfy 미사용 (사용자 결정).
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

# 4) 자가진화 패턴 마이닝 — 프롬프트 로그는 쌓이는데 pattern-detect가 오래 안 돌면 학습 루프 정지
PD=$(age_days "$USAGE_DIR/pattern-detect-last")
EVOLVE_LINES=$(cat "$CLAUDE_DIR"/_evolve/*.jsonl 2>/dev/null | wc -l)
if [ "$EVOLVE_LINES" -gt 50 ] && { [ "$PD" -lt 0 ] || [ "$PD" -gt 7 ]; }; then
    warn "PATTERNS_UNMINED(${EVOLVE_LINES}줄/${PD}d): pattern-detect 실행 제안 (T40 자가진화 루프 정지 상태)"
fi
# 사실만 남긴다(2026-10-01 P6 검수): 위 PATTERNS_UNMINED 는 SessionStart 의 pattern-detect 가 매번 pattern-detect-last 를 찍어 사실상 도달 불가
# (훅이 죽었을 때만 울린다). «후보를 안 본다» 경보는 아래 CANDIDATES_PENDING(미결 건수·7일 초과 건수) 하나가 맡는다 — 같은 상황에 둘이 매 세션 겹쳐 울리지 않게 한다.

# 4.5) 대화 지식 축적 (knowledge/) — 최근 14일 노트 0건이면 캡처 루프 정지 의심 (2026-07-13 신설)
#      event-구동이지만 "대화는 매일 있는데 산출이 장기 0건"은 rot — 최신 노트 나이로 근사 감시.
if [ -d "$CLAUDE_DIR/knowledge" ]; then
    # -maxdepth 제거 (2026-07-14): 프로젝트별 하위 폴더(harness/ 등) 재귀 검사 — maxdepth 1 유지 시 오경보
    KN=$(find "$CLAUDE_DIR/knowledge" -name '*.md' ! -name 'README.md' -newermt '-14 days' 2>/dev/null | head -1)
    if [ -z "$KN" ]; then
        warn "KNOWLEDGE_SILENT: 최근 14일 지식 노트 0건 → 대화 지식 캡처 루프 점검 (rules-lazy/knowledge-capture.md)"
    fi
fi

# 5) harness-bench — 규칙을 고친 뒤 측정으로 돌아오는 고리. (2026-09-14 재정의)
#    왜 바꿨나: 이전 판정은 history.md 의 '축약 후보' 언급이 '종결' 문구를 포함하는지로 무장/해제했고
#    임계가 60일이었다. 08-19 감사가 '종결'을 적은 뒤로는 규칙을 아무리 고쳐도 경보가 영구 침묵했다
#    (09-14 감사 §2-13). 이제 문구가 아니라 **사실**로 판정한다: 마지막 bench 이후 규칙 계열 파일이
#    바뀐 커밋이 있고, 그 첫 커밋으로부터 14일이 지났으면 측정이 밀린 것이다.
B=$(age_days "$USAGE_DIR/bench-last")
BENCH_TS=$(stat -c %Y "$USAGE_DIR/bench-last" 2>/dev/null || stat -f %m "$USAGE_DIR/bench-last" 2>/dev/null || echo 0)
if git -C "$CLAUDE_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    # --reverse | head -1 = bench 이후 첫 규칙 변경 커밋. 마지막이 아니라 첫 커밋 기준이라야
    # 계속 고치는 동안 경보가 뒤로 밀리지 않는다(래칫 반대 방향의 침묵 방지).
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

# 6) mem-watch cron 생존 — cron이 등록돼 있는데(등록 흔적=crontab 라인) 로그가 30분+ 침묵이면
#    감시기의 침묵 사망(fail-visible 원칙, 2026-08-19 검수 발견). cron 미등록 서버에선 침묵.
if crontab -l 2>/dev/null | grep -q mem-watch.sh; then
    MW_LOG="$CLAUDE_DIR/tools/mem-guard/mem-watch.log"
    MW_AGE=$(age_min "$MW_LOG" 2>/dev/null || echo -1)
    if [ "$MW_AGE" -lt 0 ] 2>/dev/null; then
        warn "MEMWATCH_SILENT: cron 등록됐는데 mem-watch.log 부재 → cron 동작 점검"
    elif [ "$MW_AGE" -gt 30 ] 2>/dev/null; then
        warn "MEMWATCH_SILENT(${MW_AGE}m): mem-watch cron이 30분+ 침묵 → cron 동작 점검"
    fi
fi

# 7) 에이전트 교차검증 신선도 — agent-crosscheck.sh 는 훅·타이머 배선이 없어 손으로만 돈다.
#    T41 약점 루프의 유일한 기록점이므로 오래 침묵하면 루프가 멈춘 것과 같다 (2026-09-06 검수 발견).
#    2026-10-17 G2: 경보만 내던 것을 자동 실행으로 바꾼다. 동기로 돌리면 transcript 전수 grep 이 SessionStart 를 막으므로
#    전용 잠금(`_usage/crosscheck.lock`)이 비어 있을 때만 `setsid nohup … --auto &` 로 분리해 띄우고 한 줄만 알린다
#    (잠금은 자식이 실행 내내 쥔다. 여기서는 비었는지만 `flock -n` 으로 확인하고 즉시 놓는다). 잠금이 차 있으면(이미 도는 중)
#    종전 경보를 그대로 낸다. 결과 행은 성공 계수 뒤에만 append 되므로 실패하면 다음 세션이 다시 시도한다.
#    신선도 판정은 파일 mtime 이 아니라 `agent-crosscheck.sh latest`(마지막 행이 일치이고 ts 가 0~7일, exit 0=신선)를 쓴다 — mtime 은
#    손으로 파일을 만지거나 다른 줄을 붙여도 갱신돼 «오래된 판정» 을 가린다(2026-10-17 외부 검토). 최신 판정이 일치가 아닐 때도 stale 로 본다.
#    재시도 폭주 방지: 마커를 둘로 나눈다. 시도 마커 `_usage/crosscheck-auto-attempt`(30분 안이면 재시도 안 함)는 띄우는 이 자리에서 찍고,
#    성공 마커 `_usage/crosscheck-auto-last`(6시간)는 여기서 찍지 않는다 — agent-crosscheck.sh --auto 가 행을 append 한 직후에만 찍는다
#    (종전엔 띄우기만 해도 6시간을 막아 계수가 죽으면 6시간 동안 재시도가 없었다). 두 조건 모두 «안에 있으면 건너뜀»이고, 건너뛰는 동안은 종전 경보를 낸다.
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
        # 15분 상한·최저 CPU/IO 우선순위(2026-10-17 검수): transcript 전수 grep 이 작업 중인 학습·세션과 디스크를 다투지 않게 한다.
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

# 7b) 이 자리에서 쓰는 경로(아래 8·8b·8c 절도 같은 값을 쓴다 — 효과 기록이 7일 만료보다 앞서야 해서 정의를 앞당겼다)
CAND_FILE="$CLAUDE_DIR/_evolve/candidates.tsv"
SPAWN_LOG="$CLAUDE_DIR/_audit/agent-spawn.log"
T41_HIST="$CLAUDE_DIR/_audit/history.md"
# 7c) post-commit 연결 재시도 큐 배수 (2026-10-17 Grok 2차·Codex 3차) — 순서는 «재시도 큐 배수 → T41 효과 기록 → 7일 만료» 다.
#     ci-gate-post-commit.sh 가 잠금 실패(exit 3)로 연결하지 못한 `id<TAB>해시` 를 큐 파일에 남긴다. 줄마다 다시 시도해(pending 계열이면
#     `set <id> accepted --note commit=<해시> --machine`, 이미 accepted 면 `attach-commit`) 성공한 줄만 지우고 실패는 남긴다. id 가 대장에 없거나
#     rejected 면 연결이 불가능하므로 줄을 지우고 maintenance.log 에 «attach-retry 폐기» 한 줄. expired 는 폐기하지 않고 같은 set 으로 시도한다
#     (expired→accepted 예외, 그래도 실패하면 그때 폐기 로그). 큐에 남은 id 는 아래 7일 만료에서 제외한다(만료가 큐를 앞지르지 않게).
#     큐 파일은 전용 잠금(`_usage/candidates-attach-retry.lock`, flock -w 2) 아래에서만 읽고(스냅샷) 쓴다(남은 줄을 tmp→mv 로 다시 씀, rm 없음 — 빈 큐는 빈 파일로 남는다).
#     세션당 최대 2줄만 처리한다(바깥 훅 15초 안에 들게: 줄당 timeout 2초 × 2 + 효과 기록 ≤10초 = 14초. 2초로 모자라 124 가 나면 일시 실패라 큐에 남아 다음 세션이 이어 간다).
#     소비자가 잠금을 못 잡으면 이번 세션은 배수를 건너뛰고 7일 만료도 건너뛴다(큐에 뭐가 있는지 모르므로).
RETRY_F="$USAGE_DIR/candidates-attach-retry.tsv"
RETRY_LOCK="$USAGE_DIR/candidates-attach-retry.lock"
retry_locked() {  # 큐 잠금 아래에서 "$@" 를 실행한다. 잠금을 못 잡으면 1. flock 이 없으면 큐를 건드리지 않고 1(무잠금으로 읽고 쓰면 생산자와 경합한다)
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
retry_rewrite() {  # $1=성공·폐기한 줄의 «id<TAB>해시» 목록(개행 구분) — 지금 큐 내용(잠금 안에서 다시 읽음)에서 스냅샷과 id·해시가 모두 같은 줄만 빼고 tmp→mv.
    # 배수하는 동안 post-commit 이 같은 id 의 해시를 새 커밋으로 교체했거나 새 id 를 덧붙였다면 그 줄은 남는다(id 만 비교하면 교체본이 지워진다 — 2026-10-17 Grok 10차).
    if OKPAIRS="$1" awk -F'\t' 'BEGIN { n = split(ENVIRON["OKPAIRS"], a, "\n"); for (i = 1; i <= n; i++) if (a[i] != "") ok[a[i]] = 1 } !(($1 "\t" $2) in ok)' "$RETRY_F" > "$RETRY_F.tmp.$$" 2>/dev/null; then
        mv "$RETRY_F.tmp.$$" "$RETRY_F"
    else
        rm -f "$RETRY_F.tmp.$$"; return 1
    fi
}
if [ -s "$RETRY_F" ] && [ -f "$CAND_FILE" ] && [ ! -r "$CAND_FILE" ]; then
    # 대장을 읽지 못하면 상태 조회가 빈 값이 되어 «id 없음» 폐기로 오인된다. 생산자(post-commit)가 같은 실패를 일부러 큐에 넣으므로 소비자는 큐를 건드리지 않는다.
    printf '%s attach-retry: 대장 읽기 불가라 배수 건너뜀 (%s) — 큐 불변\n' "$(date -Is)" "$CAND_FILE" >> "$MAINT_LOG" 2>/dev/null
fi
if [ -s "$RETRY_F" ] && [ -f "$CAND_FILE" ] && [ -r "$CAND_FILE" ]; then
    if RETRY_SNAP=$(retry_locked retry_snapshot); then
        RETRY_OK=""
        RETRY_DONE=0   # 세션당 처리 줄 수 상한 2건: 줄당 timeout 2초 × 2 + 효과 기록 ≤10초 = 14초가 바깥 훅 15초 안에 들게 한다(124 는 일시 실패라 큐에 남고, 나머지는 큐에 남아 다음 세션이 이어 간다. 배수는 멱등이라 끊겨도 안전)
        while IFS=$'\t' read -r RID RHASH; do
            [ -n "$RID" ] && [ -n "$RHASH" ] || continue
            [ "$RETRY_DONE" -lt 2 ] || break
            RETRY_DONE=$((RETRY_DONE + 1))
            RST=$(ID="$RID" awk -F'\t' '$1!="id" && $1==ENVIRON["ID"] {print $5; exit}' "$CAND_FILE" 2>/dev/null); RST_RC=$?
            if [ "$RST_RC" -ne 0 ]; then   # 조회 실패를 빈 상태(«id 없음» 폐기)로 읽지 않는다: 이 줄은 RETRY_OK 에 넣지 않고 큐에 남긴다
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
                # 실패 종류를 가른다(2026-10-17 Codex 7차). exit 3(잠금 실패)·124(timeout)·그 밖의 비0 은 일시 실패라 큐에 남겨 다음 세션이 재시도하고,
                # 영구 실패(exit 1: 어휘 밖·전이 불가·id 없음·해시가 정리돼 없음)만 폐기 로그를 남기고 지운다. 대장 저장 입출력 오류(exit 5)도 일시 실패라 남긴다.
                # expired 의 set 과 accepted 의 attach-commit 이 exit 1 이면 영구 실패다(세션당 2줄 상한이라 영구 실패 줄이 앞에 남으면 뒷줄이 막히므로 지운다 — 2026-10-17 검수팀 재확인).
                # pending 계열의 set 은 어떤 실패든 큐에 남는다(위 RCMD 시도가 멱등). 2초 timeout 으로 모자라 124 가 나도 일시 실패라 큐에 남는다.
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

# 순서 제약(2026-10-17 Codex 2차): 아래 8) 의 7일 자동 만료보다 **먼저** 돈다. 만료가 먼저면 8일 된 quiet 행이 재발을 기록하기 전에 expired 가 되어
# effect:recurred 만료 보호가 무의미해진다. 하루 1회 선점 규칙은 그대로다.
# 8-pre) T41 효과 기록 (옛 8c-2) (2026-10-17 G2) — 미결 T41 후보가 하나라도 있으면, 하루 1회(선점 디렉터리 `_usage/t41-effect-<날짜>.d`).
#     T41_REPEAT(3회 문턱) 여부와 무관하다: 재발이 문턱 아래여도 effect:recurred 가 기록돼야 7일 만료 보호를 받는다.
#     14일 침묵 자동 종결은 폐기했다(침묵을 보상하고, qa FAIL 이 전부 coder 로 귀속되는 구조라 역할마다 치우친다).
#     대신 미결 T41 후보의 **note** 에 사실만 적는다: 같은 역할의 최근 14일 소집 수(n_spawn)와, 후보 생성일 이후 같은 role/dim 재발 수(k).
#     `effect:quiet n_spawn=X` 또는 `effect:recurred k=Y`. 상태는 바꾸지 않고 판정은 스킬에서 사람이 한다.
#     effect 비고는 **미결 T41 후보에만** 쓴다. accepted 가 된 뒤의 효과 추적은 여기가 아니라 감사의 hit 정의(skills/harness-audit/SKILL.md)가 맡는다.
#     쓰기는 파일을 직접 건드리지 않고 `candidates-append.sh set-note-batch --only-machine` 으로만 한다: 잠금 1회·재작성 1회·전체 `timeout 5 + 행수/100 초(최대 10, 바깥 훅 15초)`
#     이고, 비고가 비었거나 기계 비고(kw=·effect:)인 행만 잠금 **안에서** 다시 확인해 갱신한다(읽고 잠금 밖에서 판단하면 그 사이의 사람 판정을 덮는다).
#     후보 선정도 같은 보호 필터를 먼저 적용한 뒤 남은 미결 T41 전부(상한 없음)를 본다(앞 10건 고정이면 보호 행 10개가 뒤를 가린다).
#     상한은 두지 않는다(2026-10-17 Codex 4차:
#     상한이 있으면 201번째 미결 T41 이 기록 없이 quiet 로 만료되는데 done 은 만들어진다. 대장 awk 는 한 번이라 비용이 무시할 만하다). done 은 선정한 모든 행을 처리했을 때만 만든다.
#     이미 `effect:recurred` 로 시작하는 행은 선정에서 뺀다(만료되지 않는 recurred 행이 칸을 채우면 매번 다시 계산할 이유가 없다).
#     축(role/dim)은 후보 요약의 첫 `:` 앞(앞뒤 공백 제거)이고 digest(oldest-pending)의 축 일치와 같은 규칙이다. 역할은 role-alias.sh 의 normalize_role 로
#     후보 쪽과 소집 로그(3열) 쪽을 둘 다 정규화해 비교한다(sec-g1 와 security 가 갈라져 n_spawn 이 0 이 되지 않게). `timeout` 이 없으면 상한 없이 실행하고 경보 한 줄.
#     재발 수 k = 후보 생성일 이후(같은 날 포함, 생성일의 첫 기록은 후보 자신이라 1건 제외) 같은 축의 전체 기간 기록 수. 소집 수 n_spawn 만 최근 14일.
#     하루 1회는 `_usage/t41-effect-<날짜>.d` 를 mkdir 로 선점한 세션만(원자적). 일괄 갱신이 실패하면 failed 표지(첫 줄=원인)를 남기고 선점은 유지하며, 10분 뒤 다음 세션이 승계(takeover)해 재시도한다.
T41_PEND=0
T41_PEND_RC=0
if [ -f "$CAND_FILE" ]; then T41_PEND=$(awk -F'\t' '$1!="id" && $2=="T41" && ($5=="pending" || $5=="pending-bench" || $5=="pending-approval") {n++} END {print n+0}' "$CAND_FILE" 2>/dev/null); T41_PEND_RC=$?; fi   # awk 실패를 «미결 0» 으로 읽지 않는다(만료 전 점검에서 보류)
if [ "${T41_PEND:-0}" -ge 1 ] 2>/dev/null && effect_claim; then
    CUT14D=$(date -d '-14 days' +%Y-%m-%d 2>/dev/null || date -v-14d +%Y-%m-%d 2>/dev/null || echo "")
    if [ -n "$CUT14D" ]; then
        # 축별 전체 기록: 날짜<TAB>role/dim (signal 본문은 떼고 센다 — T41_REPEAT 와 같은 파싱)
        # grep 종료 코드를 따로 받는다(2026-10-17 Grok 7차): 0=매치·1=매치 없음(빈 history 로 본다)·2 이상=읽기 실패(파일 없음·권한 0).
        # 읽기 실패를 빈 결과로 흘리면 재발 수 k=0 → effect:quiet → done → 7일 뒤 만료되는 fail-open 이 된다.
        T41_RAW=$(grep -E '^- [0-9]{4}-[0-9]{2}-[0-9]{2} T41: ' "$T41_HIST" 2>/dev/null); T41_GREP_RC=$?
        T41_ALL=$(printf '%s\n' "$T41_RAW" | sed -E 's/^- ([0-9]{4}-[0-9]{2}-[0-9]{2}) T41: /\1\t/; s/ — .*$//; s/[[:space:]]+$//')
        T_NS=$(now_ns)
        # 축 정규화 표(2026-10-17 Codex 6차 이후 구조): history·후보의 원축 → 역할 정규화한 축. 서로 다른 축 이름만큼(수십 개 이하)만 normalize_role 을 부른다.
        AXMAP=""
        while IFS= read -r AX0; do
            [ -n "$AX0" ] || continue
            AXMAP+="$AX0"$'\t'"$(norm_axis "$AX0")"$'\n'
        done < <({ printf '%s\n' "$T41_ALL" | cut -f2; awk -F'\t' '$1!="id" && $2=="T41" { p = index($6, ":"); a = (p ? substr($6, 1, p - 1) : $6); gsub(/^[ \t]+|[ \t]+$/, "", a); print a }' "$CAND_FILE" 2>/dev/null; } | sort -u)
        # 소집 로그의 최근 14일 post 를 역할(정규화)별로 센다(서로 다른 역할 이름만큼만 normalize_role).
        # 집계 awk 는 변수로 받아 종료 코드를 확인한다(프로세스 치환은 rc 를 못 본다). 없는 로그는 소집 0 으로 정상이다.
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
        # 효과 계산은 awk 한 번이다(후보 수에 무관하게 프로세스 상수 — 후보마다 awk 를 띄우면 2,000행에서 17초로 훅 한도를 넘었다).
        # 입력 파일 4개: ① 축 정규화 표 ② 역할별 소집 수 ③ history(날짜<TAB>축) ④ 후보 대장. 앞 셋은 프로세스 치환이라 인자 길이 한도와 무관하다.
        # 후보마다 NEW_NOTE 를 계산하고(재발 수 k = 후보 생성일 이후 같은 정규화 축의 기록 수, 생성일 당일이면 후보 자신 1건 제외) 바뀐 것만 `id<TAB>비고` 로 낸다.
        # awk 종료 코드를 확인한다(2026-10-17 Grok 6차): 비0(awk 실패·입력 파일 읽기 실패)을 «쓸 변경 없음» 으로 보고 done 을 만들면 계산하지 못한 후보가 quiet 로 만료된다.
        # history 를 읽지 못했으면(grep rc≥2) awk 를 돌리지 않고 같은 실패 경로로 보낸다. 실패 원인은 failed 표지의 첫 줄에 적어 T41_EFFECT_FAIL 경보가 보여 준다.
        EFF_BATCH=""; EFF_RC=0; EFF_WHY=""
        if [ "$T41_GREP_RC" -ge 2 ]; then
            EFF_RC="$T41_GREP_RC"; EFF_WHY="history 읽기 실패(grep rc=$T41_GREP_RC)"
        elif [ -f "$SPAWN_LOG" ] && [ ! -r "$SPAWN_LOG" ]; then
            # 소집 로그가 있는데 읽을 수 없으면 n_spawn 이 0 으로 샌다(없는 파일은 소집 0 으로 정상). history 와 같은 실패 경로.
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
            # timeout 은 5 + 행수/100 초(최소 5, 최대 10): 행이 많아도 같은 묶음이 매 세션 124 로 잘려 재시도되지 않게 한다.
            # 상한 10초 근거: SessionStart 훅의 바깥 timeout 이 15초(settings.json)라 이보다 길면 바깥이 먼저 끊는다(2026-10-17 검수팀).
            # 바깥이 끊어도 안전하다: done·failed 없이 끊기면 10분 뒤 다음 세션이 선점을 승계해 다시 계산하고, set-note-batch 는 잠금 안에서 한 번에 재작성한다.
            EFF_N=$(printf '%s\n' "$EFF_BATCH" | grep -c .); EFF_TMO=$((5 + ${EFF_N:-0} / 100)); [ "$EFF_TMO" -le 10 ] || EFF_TMO=10
            if [ "$HAVE_TIMEOUT" = 1 ]; then EFF_TO=(timeout "$EFF_TMO")
            else EFF_TO=(); warn "T41_EFFECT_NO_TIMEOUT: timeout 명령이 없어 T41 효과 기록을 상한 없이 실행함 → coreutils(timeout) 설치 확인"
            fi
            # 성공하면 선점 디렉터리에 done 을 둔다(아래 7일 만료는 done 이 있을 때만 돈다). 실패하면 rmdir 하지 않고 `failed` 를 남긴다 —
            # 디렉터리 mtime 이 갱신되어 10분 뒤 다음 세션이 승계(effect_claim)하고, 만료도 10분 경과면 풀린다(기록이 계속 실패해도 만료가 영원히 멈추지 않음).
            if printf '%s\n' "$EFF_BATCH" | ${EFF_TO[@]+"${EFF_TO[@]}"} bash "$CLAUDE_DIR/scripts/candidates-append.sh" set-note-batch --only-machine >> "$MAINT_LOG" 2>&1; then
                mark_effect_done
            else
                printf 'set-note-batch 실패(rc=%s)\n' "$?" > "$USAGE_DIR/t41-effect-$TODAY.d/failed"
            fi
        else
            mark_effect_done   # 쓸 변경이 없으면 기록 완료와 같다
        fi
        ADDED_NS=$((ADDED_NS + $(now_ns) - T_NS))
    else
        release_daily t41-effect
        EFF_NO_CUT=1   # 날짜 계산 실패로 기록을 못 했다: 승계 턴이어도 --force 만료로 가지 않게 아래 만료 전 점검이 이번 턴 만료를 보류한다
    fi
fi

# 8) 학습 후보 대장 — T12·T40·T41 이 후보를 적어 넣을 정본. 부재뿐 아니라 **빈 대장**과 **밀린 pending**
#    까지 본다 (2026-09-14). 왜: 09-06 수리가 파일만 만들고 쓰는 코드가 없어 헤더 1줄로 8일을 보냈는데
#    부재 검사만 있어 통과했다(09-14 감사 §2-3·§2-4). 대장이 비어 있는 것은 정상이 아니라 루프 정지 신호다.
CP_N=0
# 7일 넘은 pending 은 집계 전에 자동 만료한다(기계 비고 kw=·effect:quiet 는 보호하지 않고, effect:recurred 와 사람 비고 행은 만료에서 제외) — 만료 뒤 건수를 보여야 «밀린 것» 경보가 소음이 되지 않는다.
# 잠금은 `flock -w 1` 이라 못 잡으면 exit 3 으로 건너뛴다(대기형이면 이 훅 전체가 타임아웃에 죽는다). 상태 승격은 하지 않는다.
# 만료 전 점검 두 가지(2026-10-17 Codex 3차):
#   ① 재시도 큐에 남은 id 는 만료에서 제외한다(`--skip-ids`). 큐 잠금을 못 잡아 목록을 모르면 이번 세션은 만료하지 않는다.
#   ② T41 효과 기록이 끝났을 때(`t41-effect-<날짜>.d/done`)만 만료한다. 다른 세션이 효과를 집계하는 중이면 8일 된 quiet 행이 재발 기록 전에 만료되기 때문이다.
#      미결 T41 이 없으면 보호할 효과 기록이 없으니 바로 만료한다. 선점 디렉터리가 10분 넘게 done 없이 남았으면(기록 세션이 죽음) 만료를 허용한다.
#      승계 턴의 --force 만료는 효과 기록 실패에만 적용하고, done 생성 실패·날짜 계산 실패·미결 T41 집계 실패는 승계 턴에서도 그 턴 만료를 보류한다.
EXPIRE_OK=1; RETRY_IDS=""; EXPIRE_FORCE=""   # 비어 있지 않을 때만 --force 를 붙인다
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
            # 이 세션이 10분 지난 선점을 승계했는데 이번 기록도 실패했다(done 없음). 승계가 mtime 을 갱신해 위 조건에 안 걸리므로 여기서 허용한다.
            # candidates-append.sh 의 같은 보류(exit 4)도 mtime 기준이라 --force 로 넘긴다.
            EXPIRE_FORCE=1
            printf '%s expire 허용: 10분 지난 선점을 승계했으나 효과 기록이 다시 실패함(done 없음) — 기록 실패가 만료를 영구히 막지 않게\n' "$(date -Is)" >> "$MAINT_LOG" 2>/dev/null
        else
            EXPIRE_OK=0
            printf '%s expire 건너뜀: T41 효과 기록이 아직 끝나지 않음(done 없음) — 다음 세션이 만료\n' "$(date -Is)" >> "$MAINT_LOG" 2>/dev/null
        fi
    fi
fi
# T41 효과 기록 실패 경보(2026-10-17 Grok 9차: 만료 전 점검 뒤에서 낸다 — 승계 뒤 재실패한 턴은 만료를 허용하므로 «만료 보류» 문구와 갈라야 한다).
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
    elif [ "$EXP_RC" -ne 3 ] && [ "$EXP_RC" -ne 4 ]; then   # 3=잠금 실패, 4=효과 기록 전이라 만료 보류: 조용히 건너뛰고 위 maintenance.log 줄만 남긴다
        warn "CANDIDATES_EXPIRE_FAIL(rc=${EXP_RC}): 후보 자동 만료 실패 → _usage/maintenance.log 확인"
    fi
fi
if [ ! -f "$CAND_FILE" ]; then
    warn "CANDIDATES_MISSING: _evolve/candidates.tsv 없음 → bash scripts/setup-harness.sh 로 생성 (T12·T40 학습 후보 대장)"
else
    # 헤더(id 로 시작하는 첫 행)는 데이터가 아니다.
    CAND_ROWS=$(awk -F'\t' 'NF>0 && $1!="id" {n++} END {print n+0}' "$CAND_FILE" 2>/dev/null); CAND_ROWS=${CAND_ROWS:-0}
    if [ "$CAND_ROWS" -eq 0 ] 2>/dev/null; then
        warn "CANDIDATES_EMPTY: _evolve/candidates.tsv 데이터 0행 → T12·T40·T41 기록 경로 점검 (pattern-detect.sh·correction-detect.sh 훅 등록 여부)"
    else
        CUT7=$(date -d '-7 days' +%Y-%m-%d 2>/dev/null || date -v-7d +%Y-%m-%d 2>/dev/null || echo "")
        # 미결 상태 3종을 모두 센다 (2026-09-14 재감사 B2). 종전엔 `pending` 만 세서, 스킬이 상태를
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
        CP_MIN=$(printf '%s' "$CAND_PEND" | cut -f9)   # 미결 후보의 가장 이른 생성일(YYYY-MM-DD, 없으면 빈 값)
        CP_N=${CP_N:-0}; CP_M=${CP_M:-0}; CP_A=${CP_A:-0}; CP_B=${CP_B:-0}; CP_C=${CP_C:-0}
        CP_T12=${CP_T12:-0}; CP_T40=${CP_T40:-0}; CP_T41=${CP_T41:-0}
        [ "$CP_N" -ge 1 ] 2>/dev/null && warn "CANDIDATES_PENDING: ${CP_N}건(신규 ${CP_A} · 벤치 대기 ${CP_B} · 승인 대기 ${CP_C} · 7일 초과 ${CP_M}건 · T12 ${CP_T12}·T40 ${CP_T40}·T41 ${CP_T41}) → /learn-from-feedback 로 판정 (스킬화·편입·룰화·기각)"
        # 판정 정체: 마지막 사람 판정 시각 마커(candidates-append.sh 의 touch_reviewed 가 만드는 `_usage/candidates-reviewed-last`)가 없거나
        # 30일(43200분) 넘게 안 바뀌었는데 미결이 있으면, 후보가 쌓이기만 하고 아무도 안 보는 상태다(자동 만료는 이 마커를 건드리지 않는다).
        # 마커가 아예 없을 때는 «미결 후보의 가장 이른 생성일이 30일 초과» 일 때만 경보한다(마커 도입 첫날의 오경보 방지). 마커가 있으면 mtime 30일.
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

# 8b) T41 침묵 — 소집은 활발한데 약점 기록이 0이면 에이전트 자가진화 루프가 멈춘 것이다 (2026-09-14 신설).
#     분모는 agent-spawn.log 의 post(성립한 소집), 분자는 history.md 의 T41 행. 09-14 실측 분모 652 / 분자 0.
#     30건 문턱: 주 30회 미만 소집이면 표본이 작아 0건이 정상일 수 있어 경보를 내지 않는다.
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

# 8c) T41 반복 — 같은 role/dim 이 3회+ 쌓이면 agent-eval §3 개선 제안 게이트가 열린다 (2026-09-14 신설).
#     왜 훅인가: "동일 약점 3회+ 시 agents/{name}.md 개선 제안"은 모델 의무 문장뿐이라 누가 세지도
#     않았다. 기록은 기계가 하는데 소비는 사람이 기억해야 하는 비대칭이 루프를 끊었다 — 세는 일까지
#     기계가 한다. 창은 30일(agent-eval §1.5 창 정본). 창을 두는 이유: 무제한 누적이면 한 번 3회를
#     넘긴 축이 영구히 경보를 내 배경 소음이 되고, 개선 반영 뒤 조용해진 사실도 드러나지 않는다.
T41_REP=""
if [ -f "$T41_HIST" ]; then
    CUT30D=$(date -d '-30 days' +%Y-%m-%d 2>/dev/null || date -v-30d +%Y-%m-%d 2>/dev/null || echo "")
    # 축 키는 공백을 포함한다 — agent-eval §2 차원 이름이 «구현 정확성»·«범위 준수» 처럼 두 낱말이다
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

# 8c-3) 후보 판정 digest (2026-10-17 G2·결정 B1) — CANDIDATES_PENDING 이 떠 있으면 하루 1회, 가장 오래된 3건을 요약해 보여
#     main 이 턴 끝 1줄로 판정을 묻게 한다(사람이 후보를 보는 경로가 /learn-from-feedback 수동 호출뿐이라 pending 이 55건까지 쌓였다).
#     정렬은 오래된 순, 같은 날짜면 T41 축 > T12 > T40, 날짜 기준 회전(미결이 3건을 넘으면 `--skip` 을 날짜의 연중 일수로 돌려 날마다 다른 3건을 보인다 —
#     고정 «가장 오래된 3건» 이면 판정하지 않는 한 같은 3건만 반복된다). T41_REPEAT 축을 알아야 해서 8c 뒤에 둔다.
#     Grok 의 토큰 반대(CANDIDATES_PENDING 과 일부 겹침)는 선택지 표에 기록된 사실이며, 하루 1회·3건·60자 상한으로 상수 비용을 지킨다.
#     하루 1회는 `_usage/candidates-digest-<날짜>.d` 를 mkdir 로 선점한 세션만 출력한다(원자적 — 병렬 세션이 같은 날 같은 digest 를 중복 출력하지 않는다).
#     보여 줄 후보가 없으면 선점을 풀어 둔다.
if [ "${CP_N:-0}" -ge 1 ] 2>/dev/null && claim_daily candidates-digest; then
    T41_AXES_RAW=$(printf '%s' "$T41_REP" | sed -E 's/ ×[0-9]+//g')
    T41_AXES=""   # 효과 기록과 같은 규칙으로 역할 부분을 정규화해 넘긴다(candidates-append 쪽도 후보 축을 같은 규칙으로 정규화)
    IFS=',' read -ra AX_ARR <<< "$T41_AXES_RAW"
    for AX1 in ${AX_ARR[@]+"${AX_ARR[@]}"}; do T41_AXES+="${T41_AXES:+,}$(norm_axis "$AX1")"; done
    DIGEST_SKIP=0
    [ "$CP_N" -gt 3 ] 2>/dev/null && DIGEST_SKIP=$(( (10#$(date +%j) % ((CP_N + 2) / 3)) * 3 ))
    DIGEST=$(bash "$CLAUDE_DIR/scripts/candidates-append.sh" oldest-pending --limit 3 --skip "$DIGEST_SKIP" --t41-axes "$T41_AXES" 2>/dev/null)
    if [ -n "$DIGEST" ]; then
        printf '%s\n' "$DIGEST" | while IFS=$'\t' read -r DID DTYPE DSUM; do echo "  · ${DID} [${DTYPE}] ${DSUM}"; done
        echo "  → 턴 끝에 1줄로 판정을 묻는다(accepted/rejected/보류)"
    else
        release_daily candidates-digest
    fi
fi

# 8d) 기억 정리 (2026-10-17 G5-1) — MEMORY.md 경보는 현재 프로젝트 하나만, decisions 정리는 고정 루트 + 현재 프로젝트. 프로젝트 폴더 이름은 Claude Code 와 같은 규칙(영숫자 아닌 글자 → `-`,
#     `/home/u/.claude` → `-home-u--claude`)으로 cwd 에서 만든다. MEMORY.md 는 세션마다 통째로 올라가는 상시 비용이라 160줄을 넘으면 알린다.
#     decisions.md 는 7일 초과 항목을 decisions-archive.md 로 옮긴다(하루 1회·잠금·삭제 없음 — decisions-prune.sh 헤더 참조).
MEM_PROJ=$(printf '%s' "$PWD" | sed 's/[^A-Za-z0-9]/-/g')
MEM_DIR="$CLAUDE_DIR/projects/$MEM_PROJ/memory"
if [ -f "$MEM_DIR/MEMORY.md" ]; then
    MI_LINES=$(wc -l < "$MEM_DIR/MEMORY.md" 2>/dev/null | tr -d ' ')
    [ "${MI_LINES:-0}" -gt 160 ] 2>/dev/null && warn "MEMORY_INDEX_LONG(${MI_LINES}줄): 현재 프로젝트 MEMORY.md 가 160줄 초과 → 종료된 항목을 목차 한 줄로 묶거나 정리 (rules-lazy/memory-write.md § 자동 메모리 색인)"
fi
# decisions 정정 대상은 두 곳이다: ① short-term 고정 루트(서버 등록부 paths.short_term_root, rules-lazy/memory-write.md 의 실제 기록 위치)
# ② cwd 기반 현재 프로젝트. 현재 프로젝트만 정리하면 다른 프로젝트에서 시작한 세션이 고정 루트를 영영 못 치운다. 둘이 같으면 한 번만 돈다.
# 마커는 decisions-prune.sh 가 폴더별로 둔다. 등록부에 고정 루트가 없는 서버는 ② 만 돈다.
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

# 9) 감시 서명 원장 형식 — 열 수가 어긋나거나 게이트 어휘가 제멋대로면 집계에서 샌다.
#    정본(2026-09-14 확정) 6열: 일시·프로젝트·게이트·대상·근거·주체.
#    왜 어휘까지 보나: 열 수만 세던 판정은 6열이기만 하면 3열에 `result`·`finding` 같은 비게이트 값이
#    들어와도 통과시켜, 230행 중 어느 스키마로도 집계되지 않는 행이 쌓였다(09-14 감사 §2-9·§2-10).
OV_FILE="$CLAUDE_DIR/_audit/oversight.tsv"
OV_GATES="commit launch external-send publish data-change deploy audit approve delete other"
# 어휘 검사는 정본 확정일(2026-09-14) 이상인 행에만 건다 — 그 이전 129행은 어휘 도입 전
# 기록이라 구 어휘(git-commit·decision·- 등) 그대로 두기로 했다(2026-09-14 결정). 열 수 검사도 같은 기준(2026-10-01).
OV_CUTOFF="2026-09-14"
if [ -f "$OV_FILE" ]; then
    # 열 수도 정본 확정일 이상인 행에만 건다 (2026-10-01 감사 P6) — oversight-signature.md «구 행은 열·어휘 검사 대상이 아니다».
    # 전 행을 보면 손으로 적은 옛 행이 영구히 OVERSIGHT_FORMAT 경보를 낸다.
    OV_BADCOL=$(awk -F'\t' -v c="$OV_CUTOFF" 'NF>0 && NF!=6 && substr($1,1,10)>=c {print NR}' "$OV_FILE" 2>/dev/null)
    OV_BADGATE=$(awk -F'\t' -v g=" $OV_GATES " -v c="$OV_CUTOFF" 'NF==6 && substr($1,1,10)>=c && index(g, " " $3 " ")==0 {print NR}' "$OV_FILE" 2>/dev/null)
    # 행 번호는 앞 8개만 — 경보 한 줄이 세션 시작 주입을 삼키지 않게 한다(토큰 설계 상수 유지).
    if [ -n "$OV_BADCOL" ]; then
        N=$(printf '%s\n' "$OV_BADCOL" | wc -l | tr -d ' ')
        warn "OVERSIGHT_FORMAT(열 수 ${N}행): _audit/oversight.tsv 6열 아님 — 행 $(printf '%s\n' "$OV_BADCOL" | head -8 | tr '\n' ',' | sed 's/,$//')$([ "$N" -gt 8 ] && echo ' 외') → scripts/oversight-fix-5col.py 확인"
    fi
    if [ -n "$OV_BADGATE" ]; then
        N=$(printf '%s\n' "$OV_BADGATE" | wc -l | tr -d ' ')
        warn "OVERSIGHT_FORMAT(게이트 어휘 ${N}행): 3열이 허용 어휘(${OV_GATES}) 밖 — 행 $(printf '%s\n' "$OV_BADGATE" | head -8 | tr '\n' ',' | sed 's/,$//')$([ "$N" -gt 8 ] && echo ' 외') → 이후 기록은 scripts/oversight-append.sh 로"
    fi
fi

# 설계 ①·③: 중단 또는 남은 큐가 있을 때만 폰 미도착의 원인을 한 줄로 알린다.
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
    # 중단은 NTFY_HALT_RETRY_SEC(기본 3600, 0=하루 통째) 초 안에 갱신된 halt 만 유효(claude-notify.sh halt_active 와 같은 판정)
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

[ "$ADDED_NS" -gt 0 ] && printf '%s added_ms=%s\n' "$(date -Is)" "$((ADDED_NS / 1000000))" >> "$MAINT_LOG" 2>/dev/null
[ "$ISSUES" -eq 0 ] && echo "USAGE OK"
exit 0
