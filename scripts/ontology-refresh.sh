#!/usr/bin/env bash
# ontology-refresh.sh — 하네스 온톨로지 무인 갱신 오케스트레이터 (systemd timer 진입점)
#
# 흐름: pipeline detect → (uncached 있으면) 헤드리스 Claude로 시맨틱 추출 → pipeline finalize
#
# 권한 설계 (2026-07-09 사용자 승인):
#   - bash 단계(detect/finalize)는 systemd가 직접 실행 — Claude 도구 훅과 무관 (restore-bg-sessions.sh 선례)
#   - Claude는 추출 단계만 헤드리스 참여. 편집 허용은 이 호출의 플래그(acceptEdits)에만 존재 —
#     settings 상시 예외 없음, 훅 수정 없음. 프롬프트가 Bash 사용 금지 + graphify-out/ 밖 쓰기 금지를 지시.
#   - git push 없음 (파이프라인 전 구간).
#
# 멀티서버 (code-graph.md §7.1): 이 타이머는 정확히 1개 서버에만 설치한다.
# REF: knowledge/harness/code-history/scripts__ontology-refresh.sh.md

set -uo pipefail

# WHY: systemd 최소 PATH에는 ~/.local/bin(uv tool 설치 위치)이 없어 pipeline detect의
# resolve_python 폴백(command -v graphify)이 실패한다 (2026-08-12 주력 서버 첫 타이머 실사고).
# 기존 PATH 보강(claude/node)은 추출 분기(N>0)에만 있어 여기 초입에서 선치해 detect부터 적용.
export PATH="$HOME/.local/bin:$PATH"

CLAUDE_DIR="$HOME/.claude"
LOG="$CLAUDE_DIR/ontology-refresh.log"
LOCK="$CLAUDE_DIR/graphify-out/.refresh-lock"
PROMPT_FILE="$CLAUDE_DIR/scripts/ontology-extract-prompt.md"

# WHY: systemd 경유 시 StandardOutput=append:LOG가 stdout을 같은 파일에 다시 붙여 tee는 이중 기록이 된다
# (2026-07-13 로그 중복 실측) — systemd가 주입하는 INVOCATION_ID로 분기.
tee_log() { if [ -n "${INVOCATION_ID:-}" ]; then cat; else tee -a "$LOG"; fi; }
log() { echo "[$(date -Iseconds)] [refresh] $*" | tee_log; }

notify_fail() {
    bash "$CLAUDE_DIR/scripts/claude-notify.sh" "ontology" "온톨로지 갱신 실패: $1 (로그: ontology-refresh.log)" 2>/dev/null || true
}

if [ -d "$LOCK" ]; then
    LOCK_TS=$(stat -c %Y "$LOCK" 2>/dev/null || stat -f %m "$LOCK" 2>/dev/null || echo 0)
    if [ $(( $(date +%s) - LOCK_TS )) -lt 7200 ]; then
        log "이미 실행 중 (lock 존재) — 종료"
        exit 0
    fi
    # WHY: stale lock(>2h) 제거 실패 = 깨진 lock이 이후 모든 run을 영구 차단 → 성공위장 대신 중단+ntfy (2026-07-18 Codex)
    rmdir "$LOCK" 2>/dev/null || { log "stale lock 제거 실패 — 수동 확인 필요"; notify_fail "stale lock 제거 실패"; exit 1; }
fi
mkdir -p "$CLAUDE_DIR/graphify-out"
# WHY: lock 획득 실패는 경합(정상)과 권한/IO 오류(실패)를 구분 (2026-07-18 Codex): dir 존재=경합 exit 0,
# 부재=mkdir가 다른 이유로 실패 → 성공위장 대신 중단+ntfy.
mkdir "$LOCK" 2>/dev/null || {
    if [ -d "$LOCK" ]; then log "이미 실행 중 (lock 경합) — 종료"; exit 0
    else log "lock 획득 실패(권한/IO) — 중단"; notify_fail "lock 획득 실패"; exit 1; fi
}
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

log "===== 갱신 시작 ====="

bash "$CLAUDE_DIR/scripts/ontology-pipeline.sh" detect
DRC=$?
if [ "$DRC" -eq 2 ]; then
    # NEVER: 미push 백로그 스킵(exit 2)에서 finalize로 진행하지 않는다. detect 산출물 부재로 크래시한다.
    log "이번 주기 skip (미push 백로그 — pipeline이 ntfy로 push 필요 알림 발송함)"
    exit 0
elif [ "$DRC" -ne 0 ]; then
    # WHY: pipeline detect 단계는 실패 직전 log()로 구체 사유를 [pipeline] 줄에 이미 남기므로
    # 그 마지막 줄을 그대로 알림에 싣는다(2026-08-30 실사고: 추측한 원인 문구가 실제 원인을 가렸다).
    REASON=$(tail -n 20 "$LOG" | grep '\[pipeline\]' | tail -n 1 | sed -E 's/^\[[^]]*\] \[pipeline\] //')
    log "detect 실패 — 종료 (사유: ${REASON:-확인 불가, 로그 직접 확인 필요})"
    notify_fail "detect 단계 — ${REASON:-사유 확인 불가(로그 직접 확인 필요)}"
    exit 1
fi

# WHY: detect가 uncached.txt를 반드시 생성함(detect RC 가드) — 부재는 이상 신호로 중단 (2026-07-17 Codex)
if [ ! -f "$CLAUDE_DIR/graphify-out/.graphify_uncached.txt" ]; then
    log "detect 산출물(.graphify_uncached.txt) 부재 — detect 실패 의심, 중단"
    notify_fail "detect 산출물 부재"
    exit 1
fi
# NEVER: `|| echo 0`을 붙이지 않는다. grep -c는 0건이어도 "0"을 출력하며 exit 1로 끝나 "0\n0"이 된다 (2026-07-27)
N=$(grep -c . "$CLAUDE_DIR/graphify-out/.graphify_uncached.txt" 2>/dev/null); N=${N:-0}

# WHY: stale 목적지 청크 제거를 N과 무관하게 선행 (2026-07-17 Codex): N=0 재시도에서 이전 실패
# finalize가 남긴 청크가 재병합되는 것 방지 — 이번 run이 추출 없이 finalize로 가도 안전.
find "$CLAUDE_DIR/graphify-out" -maxdepth 1 -type f -name '.graphify_chunk_*.json' -delete \
    || { log "stale 청크 삭제 실패 — 잔여 재병합 방지 위해 중단"; notify_fail "stale 청크 삭제 실패"; exit 1; }

if [ "$N" -gt 0 ]; then
    # WHY: systemd 사용자 유닛의 PATH 에는 ~/.npm-global/bin 이 없어 `command -v claude` 가 /usr/bin/claude(2.0.50,
    # root 소유 옛 npm 판)를 집었다(2026-11-16). 그래서 npm 전역(~/.npm-global/bin)과 versions/ 최고판 중
    # 판이 높은 쪽을 먼저 고른다. 판 구하기는 세션 시작 경보(claude-cli-stale-check.sh)와 같은 함수를 source 해 쓴다.
    # 둘 다 없을 때만 기존 폴백(command -v → ~/.local/bin → nvm).
    # shellcheck source=/dev/null
    . "$CLAUDE_DIR/scripts/claude-cli-stale-check.sh"
    CLAUDE_BIN=""; CLAUDE_VER=""
    if PICK=$(claude_pick_newest); then CLAUDE_BIN="${PICK%%$'\t'*}"; CLAUDE_VER="${PICK#*$'\t'}"; fi
    [ -z "$CLAUDE_BIN" ] && CLAUDE_BIN=$(command -v claude 2>/dev/null)
    [ -z "$CLAUDE_BIN" ] && [ -x "$HOME/.local/bin/claude" ] && CLAUDE_BIN="$HOME/.local/bin/claude"
    [ -z "$CLAUDE_BIN" ] && CLAUDE_BIN=$(find "$HOME/.nvm/versions/node" -maxdepth 3 -name claude -type f 2>/dev/null | head -1)
    if [ -z "$CLAUDE_BIN" ]; then
        log "claude CLI 미발견 — 시맨틱 추출 불가, 부분 빌드 방지 위해 중단"
        notify_fail "claude CLI 미발견"
        exit 1
    fi

    log "claude CLI: $CLAUDE_BIN (${CLAUDE_VER:-판 미상})"

    # WHY: systemd 최소 PATH에선 `node`가 /usr/bin/node(v12)로 풀려 플러그인 훅이 신 문법(??)에서
    # SyntaxError로 죽는다 (2026-07-13 실측). claude가 ~/.local/bin 네이티브 설치면 그 옆에 node가
    # 없어 dirname 선치만으론 부족 — node가 신 문법을 못 돌리면 nvm 최신 node를 추가 선치.
    PATH="$(dirname "$CLAUDE_BIN"):$PATH"; export PATH
    if ! node -e 'null ?? 0' >/dev/null 2>&1; then
        NEW_NODE=$(find "$HOME/.nvm/versions/node" -maxdepth 3 -name node -type f 2>/dev/null | sort -V | tail -1)
        [ -n "$NEW_NODE" ] && PATH="$(dirname "$NEW_NODE"):$PATH" && export PATH
    fi
    # WHY: 추출 프롬프트가 동기 dispatch(run_in_background:false)를 강제하지만, 모델이 그래도 백그라운드를
    # 쓰면 -p 모드의 기본 600s 대기 상한이 에이전트를 죽여 청크 0개가 된다(2026-07-13 첫 타이머 실사고).
    # 안전핀으로 상한을 30분으로 — 전체 상한은 unit TimeoutStartSec=3600이 관장하므로 무한 대기 아님.
    export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=1800000
    # WHY: T40 수집층 오염 방지 (2026-07-16): 이 헤드리스 추출 프롬프트가 UserPromptSubmit 훅에
    # 잡혀 _evolve에 축적되던 것 제외 — prompt-log.sh가 이 변수를 보고 스킵
    export CLAUDE_PROMPT_LOG_SKIP=1

    log "시맨틱 추출: ${N}개 파일 — 헤드리스 Claude 시작"
    # WHY: 스테이징 cwd + add-dir 설계 (2026-07-13 실측 T1~T9 — 헤드리스 권한 모델 3면):
    #   1) Write: acceptEdits 자동 승인은 "세션 cwd 안"만 + ~/.claude는 내장 민감 가드가 별도 승인
    #     요구 → 헤드리스(-p)엔 승인자가 없어 영구 거부
    #   2) Read: settings의 Read(**) 허용은 cwd 상대 → cwd를 밖으로 옮기면 ~/.claude 읽기가 막힘
    #     → --add-dir로 ~/.claude를 추가 작업 디렉토리 등록해 읽기 개방
    #   3) 안전: --add-dir 상태에서도 ~/.claude "쓰기"는 민감 가드가 계속 차단함을 실측 확인 —
    #     읽기만 열리는 최소 권한. 청크는 스테이징 cwd에 상대경로로 받고, graphify-out 배치는
    #     systemd 소유 bash(이 스크립트)가 수행. settings 권한 완화 0 — "완화 대신 실행 주체
    #     이동" 원칙(code-graph §8) 유지.
    # NEVER: 모델을 특정 버전으로 하드코딩하지 않는다(별칭 sonnet).
    # WHY: 도구 제한 (2026-10-01 감사 D): Bash 금지가 프롬프트 문장뿐이라 --tools 로 빌트인 도구를 프롬프트가
    # 허용한 Read·Glob·Grep·Write·Agent 로 한정한다(프롬프트 6행 «Only Read, Glob, Grep, Agent, Write»와 같은 집합).
    STAGING="$HOME/.cache/claude-ontology/chunks"
    mkdir -p "$STAGING"
    # WHY: staging 청소 RC 검사 (2026-07-18 Codex): 실패 시 이전 run의 stale 청크가 이후 move로
    # 재병합돼 손상 그래프가 커밋될 수 있음 → find -delete(ARG_MAX 안전) + 실패 시 중단.
    find "$STAGING" -maxdepth 1 -type f \( -name 'chunk_*.json' -o -name 'wtest.json' \) -delete \
        || { log "staging 청크 청소 실패 — stale 재병합 방지 위해 중단"; notify_fail "staging 청소 실패"; exit 1; }
    # WHY: scripts/ontology-extract-prompt.md names the harness as {CLAUDE_DIR} (no machine path in the file); fill it in here.
    PROMPT_TEXT=$(cat "$PROMPT_FILE"); PROMPT_TEXT=${PROMPT_TEXT//\{CLAUDE_DIR\}/$CLAUDE_DIR}
    # WHY: 읽기 허용 규칙 (2026-11-16, 사용자 결정 «나이틀리 명령에만 추가»): CLI 2.1.302 이후 -p 의 권한 처리가
    # 엄격해져 settings 의 Read(**)(작업 폴더=staging 기준)가 --add-dir 로 연 하네스 파일에 맞지 않고, 11-16 헤드리스가
    # graphify-out/.graphify_uncached.txt 를 «permission denied» 로 못 읽었다(11-13 CLI 2.1.197 은 읽음).
    # 절대 경로 규칙(//)으로 하네스 읽기만 연다. ~/.claude 쓰기는 보호 경로라 이 규칙으로 열리지 않는다.
    # 하네스가 심볼릭 링크라 링크 경로와 실제 경로 양쪽을 적는다(경로 가드 양측 물리화 원칙).
    CLAUDE_DIR_REAL=$(readlink -f "$CLAUDE_DIR" 2>/dev/null || echo "$CLAUDE_DIR")
    READ_RULES="Read(/$CLAUDE_DIR/**),Read(/$CLAUDE_DIR_REAL/**)"
    if ! (cd "$STAGING" && "$CLAUDE_BIN" -p "$PROMPT_TEXT" --model sonnet --tools "Read,Glob,Grep,Write,Agent" --allowedTools "$READ_RULES" --permission-mode acceptEdits --add-dir "$CLAUDE_DIR") >> "$LOG" 2>&1; then
        # WHY: 실패 원인 1줄을 알림에 포함 (2026-07-21 사용자 지시): 로그를 안 열어도 원인·조치를
        # 알게 한다. claude CLI의 stderr는 위 리다이렉션으로 이 LOG에 append되므로 tail에서
        # 대표 에러 라인을 패턴 매칭 — auth 만료는 무인 복구 불가(대화형 /login 필요)라 조치를 명시.
        ERRLINE=$(tail -n 8 "$LOG" | grep -m1 -E 'Failed to authenticate|invalid[ _-]?api[ _-]?key|rate[ _-]?limit|overloaded|ECONN|ENOTFOUND|ETIMEDOUT' | cut -c1-120)
        case "$ERRLINE" in
            *authenticate*|*OAuth*) HINT="OAuth 만료 — 이 서버에서 claude 대화형 /login 필요" ;;
            "")                     HINT="원인 미상 — 로그 tail 확인" ;;
            *)                      HINT="$ERRLINE" ;;
        esac
        log "헤드리스 추출 실패 — finalize 건너뜀 (원인: ${HINT})"
        notify_fail "헤드리스 시맨틱 추출: ${HINT}"
        exit 1
    fi
    # WHY: stale 목적지 청크 제거 (2026-07-17 Codex): 이전에 실패한 run이 graphify-out에 남긴
    # .graphify_chunk_*.json이 이번 추출분과 함께 재병합되는 것 방지 — 이번 run 청크만 계수.
    find "$CLAUDE_DIR/graphify-out" -maxdepth 1 -type f -name '.graphify_chunk_*.json' -delete \
        || { log "stale 청크 삭제 실패 — 중단"; notify_fail "stale 청크 삭제 실패"; exit 1; }   # WHY: ARG_MAX 안전 + RC 검사 (2026-07-17 Codex)
    GPY=$(cat "$CLAUDE_DIR/graphify-out/.graphify_python" 2>/dev/null || command -v python3 2>/dev/null || echo "")
    for f in "$STAGING"/chunk_*.json; do
        [ -e "$f" ] || continue
        if [ -n "$GPY" ] && ! "$GPY" -c "import json,sys; json.load(open(sys.argv[1]))" "$f" >/dev/null 2>&1; then
            log "손상된 청크 감지($(basename "$f")) — 부분 쓰기 의심, 중단"
            notify_fail "손상된 추출 청크"
            exit 1
        fi
        mv -f "$f" "$CLAUDE_DIR/graphify-out/.graphify_$(basename "$f")"
    done

    CHUNKS=$(find "$CLAUDE_DIR/graphify-out" -maxdepth 1 -name '.graphify_chunk_*.json' | wc -l)
    if [ "$CHUNKS" -eq 0 ]; then
        log "추출 결과 청크 0개 — 스텁 빌드 방지 위해 중단"
        notify_fail "추출 청크 0개"
        exit 1
    fi
    # WHY: 부분 추출 하한 검사 (2026-07-17 Codex): 청크당 ~10파일 규약(<20)의 안전 하한 ceil(N/15).
    # CHUNKS가 이보다 적으면 일부 uncached 파일이 누락된 부분 추출 → 중단 (shrink-guard의 상위 방어).
    EXPECTED_MIN=$(( (N + 14) / 15 ))
    if [ "$CHUNKS" -lt "$EXPECTED_MIN" ]; then
        log "부분 추출 의심: 청크 ${CHUNKS} < 예상 최소 ${EXPECTED_MIN} (uncached ${N}파일) — 중단"
        notify_fail "부분 추출 (청크 부족)"
        exit 1
    fi
    log "추출 완료: 청크 ${CHUNKS}개 (uncached ${N}파일, 예상 최소 ${EXPECTED_MIN})"

    # WHY: 파일별 완전 커버리지 검증 (2026-07-18 Codex — fail-closed strict).
    # 근거: extraction-spec가 source_file를 FILE_LIST 항목 verbatim 복사로 규정하고 FILE_LIST는
    # uncached.txt에서 그대로 오므로, 노드 source_file == uncached 엔트리가 구성상 정확 일치 →
    # 정규화 없는 exact-match가 오탐 없이 성립. uncached는 시맨틱 경로(문서)라 항상 ≥1 노드 생성
    # (zero-node는 AST 경로의 config뿐) → 미커버 파일 = 부분추출 확정.
    # fail-closed: 미커버가 1건이라도 있으면 중단. covered=0(형식 드리프트=스펙 위반)도 중단 —
    # 조용한 불완전 그래프보다 시끄러운 중단+ntfy가 옳다(자가개선 파이프라인의 correctness 우선).
    if [ -n "$GPY" ]; then
        COV_RC=0
        COV_OUT=$("$GPY" - "$CLAUDE_DIR" <<'PYEOF'
import json, sys, glob, os
root = sys.argv[1]; out = os.path.join(root, "graphify-out")
uncached = [l.strip() for l in open(os.path.join(out, ".graphify_uncached.txt")) if l.strip()]
covered = set()
for cf in glob.glob(os.path.join(out, ".graphify_chunk_*.json")):
    try: d = json.load(open(cf))
    except Exception: continue
    # 노드 기준만 커버리지 인정 (2026-07-18 Codex): edge/hyperedge만 있고 노드 없는 파일은
    # 불완전 추출 — 파일의 실체 노드가 있어야 "추출됨". edge/hyperedge는 타 파일 노드 참조일 수 있음.
    for it in d.get("nodes", []):
        sf = it.get("source_file")
        if sf: covered.add(sf)
uncovered = [u for u in uncached if u not in covered]
if uncovered:
    kind = "부분추출" if covered else "형식 드리프트(covered=0, 스펙 위반)"
    print("INCOMPLETE %s %d/%d 미커버: %s" % (kind, len(uncovered), len(uncached), ", ".join(uncovered[:5]))); sys.exit(1)
print("커버리지 완전: %d/%d" % (len(uncached), len(uncached))); sys.exit(0)
PYEOF
        ) || COV_RC=$?
        log "coverage: ${COV_OUT}"
        if [ "$COV_RC" -ne 0 ]; then
            log "불완전 추출(파일별 커버리지 미달) — 중단"
            notify_fail "불완전 추출 (파일 커버리지)"
            exit 1
        fi
    fi
else
    log "시맨틱 변경 없음 — 추출 생략 (AST/캐시만으로 finalize)"
fi

bash "$CLAUDE_DIR/scripts/ontology-pipeline.sh" finalize
RC=$?
[ "$RC" -ne 0 ] && notify_fail "finalize 단계 (빌드/export)"
log "===== 갱신 종료 (exit $RC) ====="
exit $RC
