#!/usr/bin/env bash
# PostToolUse(Write|Edit) hook — Graphify 자동 재인덱싱 (증분, 백그라운드)
#
# 목적: Graphify가 설정된 프로젝트에서 코드 파일이 Write/Edit로 변경될 때마다
#       graphify-out/graph.json을 백그라운드에서 자동 재인덱싱한다 (stale drift 방지).
#       사용자 편집 흐름은 절대 차단하지 않는다 — 모든 경로에서 exit 0, stdout 없음.
# 등록: settings.json → hooks.PostToolUse (matcher: "Write|Edit")
# 참고: stdin JSON hook 처리 선례 — scripts/prompt-log.sh
#
# 가드 (모두 즉시 exit 0):
#   1. jq 미설치 또는 file_path 비어있음
#   2. graphify-out 보유 프로젝트 루트 미발견 (최대 15단계 walk-up, / 또는 $HOME 도달 시 중단)
#   3. 발견된 루트가 $HOME/.claude (하네스 격리)
#   4. 변경 파일 경로가 graphify-out/ 내부 (재귀 방지)
#   5. graphify 미설치 (command -v 실패)
#   6. debounce 120초 이내 재실행
#   7. lock 존재 + 10분 이내 (동시 실행 방지, 10분 초과 stale lock은 제거 후 진행)
set -uo pipefail

DEBOUNCE_SEC=120
LOCK_STALE_SEC=600
MAX_WALKUP=15
HOME_DIR="${HOME:-}"

INPUT=$(cat 2>/dev/null) || exit 0
command -v jq >/dev/null 2>&1 || exit 0

FILE_PATH=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null)
[ -z "${FILE_PATH:-}" ] && exit 0

case "$FILE_PATH" in
    /*) : ;;
    *) exit 0 ;;  # 상대 경로는 신뢰하지 않음
esac

START_DIR=$(dirname -- "$FILE_PATH" 2>/dev/null) || exit 0
[ -z "${START_DIR:-}" ] && exit 0

# 프로젝트 루트 탐색: graphify-out 보유 디렉토리를 최대 15단계 walk-up
ROOT=""
CUR="$START_DIR"
LEVELS=0
while :; do
    if [ -d "$CUR/graphify-out" ]; then
        ROOT="$CUR"
        break
    fi
    if [ "$CUR" = "/" ] || { [ -n "$HOME_DIR" ] && [ "$CUR" = "$HOME_DIR" ]; }; then
        break
    fi
    LEVELS=$((LEVELS + 1))
    [ "$LEVELS" -gt "$MAX_WALKUP" ] && break
    CUR=$(dirname -- "$CUR" 2>/dev/null) || break
done

[ -z "${ROOT:-}" ] && exit 0

# ROOT 절대경로 정규화 (2026-07-18 Codex): FILE_PATH가 상대경로면 GRAPH_DIR도 상대가 되어
# 백그라운드 `cd "$ROOT"` 후 마커가 엉뚱한 위치에 쓰이고 surfacing이 못 찾아 실패가 침묵 →
# 절대화하면 marker write(bg cd 이후)와 read(원 cwd)가 동일 경로.
ROOT=$(cd "$ROOT" 2>/dev/null && pwd) || exit 0
[ -z "$ROOT" ] && exit 0

# 하네스 격리
[ -n "$HOME_DIR" ] && [ "$ROOT" = "$HOME_DIR/.claude" ] && exit 0

# 재귀 방지: 변경 파일 자체가 graphify-out/ 내부
case "$FILE_PATH" in
    "$ROOT"/graphify-out/*) exit 0 ;;
esac

GRAPH_DIR="$ROOT/graphify-out"

# 완료 보고 (2026-07-10 사용자 요청): 직전 백그라운드 재인덱싱이 남긴 완료 플래그가 있으면
# 한 줄 보고 후 제거. 재인덱싱은 비동기(hook 반환 후 완료)라 완료 순간엔 보고 채널이 없으므로,
# 다음 Write/Edit 훅 호출이 전달자 역할을 한다 — "한 편집 늦은 보고"가 유일하게 진실한 시점.
if [ -f "$GRAPH_DIR/.autoindex-updated" ]; then
    echo "[graphify] $(cat "$GRAPH_DIR/.autoindex-updated" 2>/dev/null) — 코드 그래프 자동 갱신 완료"
    rm -f "$GRAPH_DIR/.autoindex-updated" 2>/dev/null
fi
# 실패 마커도 surface (2026-07-18 Codex): 종전엔 .autoindex-failed를 쓰기만 하고 보고 안 해
# graphify 실패가 침묵 → 다음 훅 호출이 한 줄 경고로 노출 후 마커 제거.
if [ -f "$GRAPH_DIR/.autoindex-failed" ]; then
    echo "[graphify] ⚠️ $(cat "$GRAPH_DIR/.autoindex-failed" 2>/dev/null) — 코드 그래프 자동 갱신 실패 (수동 graphify . 확인)"
    rm -f "$GRAPH_DIR/.autoindex-failed" 2>/dev/null
fi

command -v graphify >/dev/null 2>&1 || exit 0

MARKER="$GRAPH_DIR/.autoindex-last"
LOCK="$GRAPH_DIR/.autoindex-lock"
NOW=$(date +%s 2>/dev/null) || exit 0

# debounce: 연속 Edit 폭주 방지 (leading-edge — 의도적).
# 알려진 특성 (2026-07-18 Codex): 120초 창 내 후속 edit는 즉시 재인덱싱 안 됨. 그러나 창 밖 다음
# edit이 재인덱싱을 트리거해 자가 치유되고, 하네스 온톨로지 그래프는 별도 나이틀리 타이머가 빌드하므로
# 이 편의성 코드-그래프의 순간 stale은 correctness 무관 — trailing 타이머 도입(과잉)보다 leading 유지.
if [ -f "$MARKER" ]; then
    LAST=$(stat -c %Y "$MARKER" 2>/dev/null || stat -f %m "$MARKER" 2>/dev/null)
    if [ -n "${LAST:-}" ]; then
        AGE=$((NOW - LAST))
        [ "$AGE" -lt "$DEBOUNCE_SEC" ] && exit 0
    fi
fi
touch "$MARKER" 2>/dev/null || exit 0

# lock: 동시 실행 방지 — mkdir 원자적 획득 (check-then-touch 경합 제거, 2026-07-06 Codex F12)
if [ -d "$LOCK" ]; then
    LOCK_TS=$(stat -c %Y "$LOCK" 2>/dev/null || stat -f %m "$LOCK" 2>/dev/null)
    if [ -n "${LOCK_TS:-}" ]; then
        LOCK_AGE=$((NOW - LOCK_TS))
        if [ "$LOCK_AGE" -lt "$LOCK_STALE_SEC" ]; then
            exit 0
        fi
        # stale 후보(>10min): owner PID가 살아있으면 느린 실행이므로 양보 — 제거 시 동시 실행+손상
        # (2026-07-18 Codex). 죽었을 때만 제거.
        OWNER_PID=$(cut -d- -f1 "$LOCK/owner" 2>/dev/null)
        [ -n "${OWNER_PID:-}" ] && kill -0 "$OWNER_PID" 2>/dev/null && exit 0
    fi
    rm -rf "$LOCK" 2>/dev/null || exit 0  # 죽은 stale lock 제거 (실패 = 타 프로세스 선점)
fi
mkdir "$LOCK" 2>/dev/null || exit 0  # 원자적 획득 — 경쟁 패배 시 즉시 종료

# 백그라운드 증분 재인덱싱 — hook은 여기서 즉시 반환.
# owner 토큰은 **워커 서브셸의 $BASHPID** (2026-07-18 Codex 재지적: 부모 훅 $$는 즉시 종료돼
# liveness 체크가 무의미 — stale 판정이 살아있는 워커를 죽은 걸로 오인). 서브셸 안에서 기록·검사.
# 락 해제는 내 토큰일 때만 — 타 프로세스가 내 stale lock 제거 후 재획득했으면 건드리지 않음.
( MYTOKEN="$BASHPID-$(date +%s 2>/dev/null || echo 0)"
  echo "$MYTOKEN" > "$LOCK/owner" 2>/dev/null
  cd "$ROOT" 2>/dev/null && graphify . >/dev/null 2>&1 \
    && printf '%s %s' "$(date '+%m-%d %H:%M')" "$(basename "$ROOT")" > "$GRAPH_DIR/.autoindex-updated" 2>/dev/null \
    || printf '%s %s FAIL' "$(date '+%m-%d %H:%M')" "$(basename "$ROOT")" > "$GRAPH_DIR/.autoindex-failed" 2>/dev/null
  [ "$(cat "$LOCK/owner" 2>/dev/null)" = "$MYTOKEN" ] && rm -rf "$LOCK" 2>/dev/null ) &

exit 0
