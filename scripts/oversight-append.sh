#!/usr/bin/env bash
# oversight-append.sh — 감시 서명 원장(_audit/oversight.tsv) 의 유일한 쓰기 경로. (2026-09-14 신설)
#
# 왜 스크립트인가: 원장은 main 이 손으로 적어 왔고 그 결과 230행이 5열·6열·비게이트 어휘로 갈라져
#   어느 스키마로도 집계되지 않았다(09-14 감사 §2-9·§2-10). 형식을 문서로만 정해 두면 지켜지지 않으므로
#   열 구성과 게이트 어휘를 이 스크립트가 강제한다. t41-append.sh 와 같은 이유·같은 형태다.
#
# 정본 6열(2026-09-14 확정): 일시 \t 프로젝트 \t 게이트 \t 대상 \t 근거 \t 주체
# 사용: bash scripts/oversight-append.sh <게이트> "<대상>" "<근거>" [주체]
set -euo pipefail

GATES="commit launch external-send publish data-change deploy audit approve delete other"

usage() {
    echo "사용법: bash scripts/oversight-append.sh <게이트> \"<대상>\" \"<근거>\" [주체]" >&2
    echo "  게이트: ${GATES}" >&2
}

if [ $# -lt 3 ] || [ $# -gt 4 ]; then
    usage
    exit 2
fi

GATE="$1"; TARGET="$2"; BASIS="$3"; ACTOR="${4:-main}"

case " ${GATES} " in
    *" ${GATE} "*) ;;
    *) usage; echo "  게이트 '${GATE}' 는 허용 어휘 밖" >&2; exit 2 ;;
esac

# 탭·개행 살균 — 한 행이 여러 줄로 쪼개지면 행 번호 기반 검사(harness-usage-check 9번)가 전부 어긋난다.
san() { printf '%s' "$1" | tr '\t\n\r' '   '; }

# 프로젝트: cwd 가 속한 저장소 이름. 하네스 자신은 basename 이 `.claude` 라 읽히지 않으므로 harness 로 적는다.
# ~/.claude 는 심볼릭 링크라 show-toplevel 이 실제 경로를 돌려준다 → 물리 경로로 비교한다.
TOP=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
HARNESS_TOP=$(cd "$HOME/.claude" 2>/dev/null && pwd -P || echo "$HOME/.claude")
if [ -z "$TOP" ]; then
    PROJECT="none"   # 저장소 밖 cwd — harness 로 적으면 하네스 게이트와 구분이 안 된다 (2026-10-01 감사 P6)
elif [ "$TOP" = "$HARNESS_TOP" ]; then
    PROJECT="harness"
else
    PROJECT=$(basename "$TOP")
fi

TSV="${HOME}/.claude/_audit/oversight.tsv"
mkdir -p "$(dirname "$TSV")"
LINE="$(date '+%Y-%m-%d %H:%M')	${PROJECT}	${GATE}	$(san "$TARGET")	$(san "$BASIS")	$(san "$ACTOR")"
printf '%s\n' "$LINE" >> "$TSV"
printf '%s\n' "$LINE"
