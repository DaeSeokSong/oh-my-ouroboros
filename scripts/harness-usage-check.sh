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

set -uo pipefail
CLAUDE_DIR="$HOME/.claude"
USAGE_DIR="$CLAUDE_DIR/_usage"
mkdir -p "$USAGE_DIR" 2>/dev/null
ISSUES=0

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

# 1) 하네스 감사 주기 (30일) — 기존 T03 인라인 체크 흡수
A=$(age_days "$CLAUDE_DIR/_audit/last-run")
if [ "$A" -lt 0 ]; then
    # last-run은 머신 로컬(gitignore) — 감사는 repo 단위이므로 git 추적되는 history.md의
    # 최신 일자로 폴백해 타서버 오경보(AUDIT_NEVER)를 막는다 (2026-07-13 _audit 추적 전환과 한 쌍).
    HD=$(grep -om1 '^## [0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' "$CLAUDE_DIR/_audit/history.md" 2>/dev/null | grep -o '[0-9][0-9-]*')
    if [ -n "$HD" ]; then
        HS=$(date -d "$HD" +%s 2>/dev/null || date -jf %Y-%m-%d "$HD" +%s 2>/dev/null || echo "")
        [ -n "$HS" ] && A=$(( ($(date +%s) - HS) / 86400 ))
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

# 4.5) 대화 지식 축적 (knowledge/) — 최근 14일 노트 0건이면 캡처 루프 정지 의심 (2026-07-13 신설)
#      event-구동이지만 "대화는 매일 있는데 산출이 장기 0건"은 rot — 최신 노트 나이로 근사 감시.
if [ -d "$CLAUDE_DIR/knowledge" ]; then
    # -maxdepth 제거 (2026-07-14): 프로젝트별 하위 폴더(harness/·modularnet/ 등) 재귀 검사 — maxdepth 1 유지 시 오경보
    KN=$(find "$CLAUDE_DIR/knowledge" -name '*.md' ! -name 'README.md' -newermt '-14 days' 2>/dev/null | head -1)
    if [ -z "$KN" ]; then
        warn "KNOWLEDGE_SILENT: 최근 14일 지식 노트 0건 → 대화 지식 캡처 루프 점검 (rules-lazy/knowledge-capture.md)"
    fi
fi

# 5) harness-bench — 축약 후보가 감사에 기록돼 있는데 bench가 한 번도/오래 안 돌면 축약 루프 블로킹
B=$(age_days "$USAGE_DIR/bench-last")
if grep -q "축약 후보" "$CLAUDE_DIR/_audit/history.md" 2>/dev/null; then
    if [ "$B" -lt 0 ]; then
        warn "BENCH_PENDING: 축약 후보 대기 중인데 harness-bench 실행 이력 없음 → /harness-bench 제안"
    elif [ "$B" -gt 60 ]; then
        warn "BENCH_STALE(${B}d): 축약 후보 검증 지연 → /harness-bench 제안"
    fi
fi

[ "$ISSUES" -eq 0 ] && echo "USAGE OK"
exit 0
