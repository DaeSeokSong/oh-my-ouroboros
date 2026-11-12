#!/usr/bin/env bash
# decisions-prune.sh — short-term/decisions.md 의 7일 초과 항목을 decisions-archive.md 로 옮긴다 (2026-10-17 G2·G5-1)
#
# 왜: decisions.md 는 «7일» 단기 기억(제목에 명시)인데 정리하는 주체가 없어 527줄까지 쌓였고, 세션마다 읽는 비용이 커졌다.
#   삭제하지 않고 아카이브 파일에 **붙인다**(되돌릴 수 있게). 승격 대상은 memory-promotion.md 의 몫이며 여기서 판단하지 않는다.
#
# 사용: bash scripts/decisions-prune.sh <memory 폴더>        예: <서버 등록부 paths.short_term_root>
#   harness-usage-check.sh 가 폴더마다 한 번씩 호출한다: short-term 고정 루트(memory-write.md, 서버 등록부 paths.short_term_root)와
#   cwd 기반 현재 프로젝트(둘이 같으면 1회). SessionStart 경로라 bash 만, 느린 도구·uv run 금지.
# 항목 경계: 줄머리가 `- YYYY-MM-DD` 또는 굵은 꼴 `- **YYYY-MM-DD …**`(memory-write.md 작성 예시) 인 줄부터 다음 날짜 줄 직전까지(계속 행·빈 줄·`## ` 소제목 포함).
#   첫 항목 앞 줄(제목·머리말)은 항상 남긴다. 항목 날짜 < 오늘-7일 이면 이동한다.
#   알려진 한계: 날짜로 시작하지 않는 줄(`## ` 소제목, `- 사용자 원문` 같은 불릿, 빈 줄)은 모두 **직전 항목의 계속 행**으로 본다.
#   그래서 오래된 항목 뒤에 붙은 소제목 블록이 그 항목과 함께 아카이브로 가고, 반대로 최근 항목 뒤의 오래된 소제목 블록은 남는다.
#   항목 경계를 날짜 줄로만 정의한 단순함의 대가이며, 소제목 단위 정리가 필요하면 decisions.md 쪽 서식을 바꿔야 한다.
# 안전장치:
#   - `flock -n <폴더>/.decisions-prune.lock` — 이미 다른 세션이 정리 중이면 조용히 exit 0.
#   - 하루 1회 — 마커는 폴더별 `~/.claude/_usage/decisions-prune-last-<프로젝트 폴더명>` 이고 «날짜 폴더» 를 적어 같으면 건너뛴다.
#   - 읽은 뒤 교체 직전에 decisions.md 의 크기·mtime 이 그대로인지 확인하고 달라졌으면 중단한다(그 사이 append 된 줄을 mv 가 덮어 지우는 것 방지).
#   - 수용한 한계(코드 변경 없음): decisions.md 의 마지막 검사와 mv 사이의 마이크로초 창은 남는다. 다른 작성자(모델의 Edit 등)가 이 잠금을 쓰지 않기 때문이다.
#   - 순서: 아카이브에 먼저 append → decisions.md 를 tmp→mv 로 교체. 중간에 죽어도 항목이 사라지지 않고 중복만 남는다.
# 출력: 옮긴 항목이 있을 때만 stdout 한 줄 `decisions-prune: N건을 decisions-archive.md 로 옮김`(0건이면 무출력). 실패는 exit 0 + stderr.
set -uo pipefail

DIR="${1:-}"
[ -n "$DIR" ] && [ -d "$DIR" ] || exit 0
DEC="$DIR/short-term/decisions.md"
ARC="$DIR/short-term/decisions-archive.md"
[ -f "$DEC" ] || exit 0

USAGE_DIR="$HOME/.claude/_usage"
PROJ_NAME="$(basename "$(dirname "$DIR")")"   # <projects>/<프로젝트 폴더>/memory 의 프로젝트 폴더 이름. 마커를 폴더별로 둔다
MARK="$USAGE_DIR/decisions-prune-last-$PROJ_NAME"
TODAY=$(date +%Y-%m-%d)
[ "$(cat "$MARK" 2>/dev/null)" = "$TODAY $DIR" ] && exit 0

# 중괄호로 감싼다: `exec 9>… 2>/dev/null` 은 파일 열기 실패뿐 아니라 이 스크립트 전체의 stderr 를 영구히 닫아 아래 실패 메시지가 사라진다(2026-10-17 검수).
{ exec 9>"$DIR/.decisions-prune.lock"; } 2>/dev/null || exit 0
command -v flock >/dev/null 2>&1 && { flock -n 9 || exit 0; }
# 잠금을 쥔 **뒤에** 오늘 마커를 다시 본다: 앞선 세션이 방금 끝내 마커를 쓰고 잠금을 놓은 직후에 들어온 세션이 같은 날 일을 또 하지 않게(원자성).
[ "$(cat "$MARK" 2>/dev/null)" = "$TODAY $DIR" ] && exit 0

CUT=$(date -d '-7 days' +%Y-%m-%d 2>/dev/null) || exit 0
KEEP="$DEC.keep.$$"; MOVED="$DEC.moved.$$"
: > "$KEEP"; : > "$MOVED"
# 읽기→교체 사이의 쓰기 유실 방지(2026-10-17 검수): 모델이 decisions.md 에 항목을 append 하는 중이면 mv 가 그 줄을 덮어 지운다.
# 읽을 때의 크기·mtime(ns)을 기억했다가 교체 직전에 다시 보고, 달라졌으면 아무것도 건드리지 않고 중단한다(마커를 남기지 않아 다음 실행이 재시도).
# DECISIONS_PRUNE_TEST_SLEEP 은 시험 전용 seam: 읽은 직후 잠시 멈춰 시험이 그 사이에 파일을 바꾸게 한다.
SIG0=$(stat -c '%s %y' "$DEC" 2>/dev/null)
N=$(awk -v c="$CUT" -v kf="$KEEP" -v mf="$MOVED" '
    /^- (\*\*)?[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/ { s = $0; sub(/^- (\*\*)?/, "", s); mv = (substr(s, 1, 10) < c); started = 1; if (mv) n++ }
    { if (started && mv) print > mf; else print > kf }
    END { print n + 0 }' "$DEC" 2>/dev/null)
if ! [[ "${N:-}" =~ ^[0-9]+$ ]]; then
    echo "decisions-prune: 항목 분리 실패 ($DEC)" >&2; rm -f "$KEEP" "$MOVED"; exit 0
fi
[ -n "${DECISIONS_PRUNE_TEST_SLEEP:-}" ] && sleep "$DECISIONS_PRUNE_TEST_SLEEP"
changed() { [ -n "$SIG0" ] && [ "$(stat -c '%s %y' "$DEC" 2>/dev/null)" = "$SIG0" ] && return 1; return 0; }
if [ "$N" -gt 0 ]; then
    changed && { echo "decisions-prune: 읽는 동안 $DEC 가 바뀌어 중단함(다음 실행이 재시도)" >&2; rm -f "$KEEP" "$MOVED"; exit 0; }
    if ! { { [ -f "$ARC" ] || printf '# 합의 결정 이력 아카이브 (decisions.md 에서 7일 초과분을 옮김, 삭제 없음)\n\n' > "$ARC"; } \
        && cat "$MOVED" >> "$ARC"; }; then
        echo "decisions-prune: 이동 실패 ($DEC → $ARC)" >&2; rm -f "$KEEP" "$MOVED"; exit 0
    fi
    # 아카이브에 먼저 붙인 뒤 교체한다. 이 사이에 바뀌었으면 교체를 포기한다(아카이브에 중복만 남고 항목은 사라지지 않는다).
    changed && { echo "decisions-prune: 교체 직전 $DEC 가 바뀌어 중단함(다음 실행이 재시도, 아카이브에 중복이 남을 수 있음)" >&2; rm -f "$KEEP" "$MOVED"; exit 0; }
    mv "$KEEP" "$DEC" || { echo "decisions-prune: 교체 실패 ($KEEP → $DEC)" >&2; rm -f "$KEEP" "$MOVED"; exit 0; }
fi
rm -f "$KEEP" "$MOVED"
mkdir -p "$USAGE_DIR" 2>/dev/null && printf '%s %s\n' "$TODAY" "$DIR" > "$MARK" 2>/dev/null
[ "$N" -gt 0 ] && echo "decisions-prune: ${N}건을 decisions-archive.md 로 옮김"
exit 0
