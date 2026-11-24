#!/usr/bin/env bash
# Harness Bench: Before/After 측정
# 룰/스킬 변경 전후 동일 작업을 실행하여 효과 비교
# After 측정은 변경 직후 같은 맥락이 아니라 무관 작업 1개+ 뒤에 실행할 것
# (같은 맥락 즉시 측정은 과대평가 — FinEvo-Bench 교차 배치 설계, 2026-08-18)
# 사용법:
#   harness-bench.sh init "작업 설명" "벤치 ID"     - 측정 환경 초기화
#   harness-bench.sh before "벤치 ID" "결과 요약"  - Before 결과 기록
#   harness-bench.sh after "벤치 ID" "결과 요약"   - After 결과 기록 + 비교 보고
#   harness-bench.sh gate "벤치 ID"                - Pareto gate 판정 (exit 0=개선, 1=미개선, 2=inconclusive)
#   harness-bench.sh report "벤치 ID"              - 측정 결과 조회
#   harness-bench.sh list                           - 모든 벤치 목록
#
# 산출 읽는 법 (2026-09-06): settings.json 이 Read(./_bench/**) 를 deny 하므로 Read 도구로는 못 읽는다.
# _bench 산출 소비는 Bash `cat` 이 정본이며, deny 는 대용량 산출이 컨텍스트로 통째로 빨려드는 것을 막기 위한 것이다.
# _usage/bench-last 가 빈 파일인 것도 정상이다. 내용이 아니라 mtime 만 쓰는 EXIT trap 신선도 마커다.

set -uo pipefail

BENCH_DIR="$HOME/.claude/_bench"
mkdir -p "$BENCH_DIR"
# WHY: 경로 비교는 양쪽을 실경로로 맞춘다 (2026-10-01 감사 P6): ~/.claude 가 심볼릭 링크라 readlink -f 한 근거 경로는
# /home/<u>/workspace/.claude/… 인데 $BENCH_DIR·$HOME/.claude/projects 는 링크 쪽 문자열이라 _bench 제외가 안 맞고
# transcript jsonl 근거는 항상 거부됐다 (oversight-append.sh 가 pwd -P 로 비교하는 것과 같은 방식).
HOME_REAL="$(readlink -f "$HOME")"
BENCH_REAL="$(cd "$BENCH_DIR" && pwd -P)"
CLAUDE_REAL="$(readlink -f "$HOME/.claude")"

ACTION="${1:-help}"

# WHY: 벤치 ID 정규화 (2026-08-25 3라운드 검수): '../' 류로 _bench 밖에 파일을 만들 수 없게 slug 만 허용
BID_RAW=""
case "$ACTION" in init) BID_RAW="${3:-}" ;; before|after|gate|report) BID_RAW="${2:-}" ;; esac
if [ -n "$BID_RAW" ]; then
    case "$BID_RAW" in
        *[!A-Za-z0-9._-]*|.*) echo "❌ 벤치 ID는 [A-Za-z0-9._-]만 허용하고 '.'로 시작할 수 없음: $BID_RAW" >&2; exit 64 ;;
    esac
fi

# WHY: 사용 마커 — harness-usage-check.sh의 BENCH_PENDING/STALE 판정 기준점.
# EXIT trap인 이유: init 등 일부 arm이 중간 exit하므로 파일 끝 배치로는 안 찍힘 (Codex 교차검증 P2). 단 종료 코드가 0 일 때만 찍는다.
# help/무인자 호출은 실사용이 아니므로 마커를 찍지 않는다 (찍으면 미사용 상태가 가려짐).
# 2026-10-17 G2: gate·report·list 도 찍지 않는다 — 읽기 전용 조회가 «측정을 했다» 는 마커를 갱신하면
#   BENCH_PENDING(마지막 bench 이후 규칙 변경 14일) 이 실제 측정 없이 꺼진다. 측정을 만드는 init|before|after 만 찍는다.
case "$ACTION" in
    init|before|after)
        # WHY: 성공(exit 0)한 호출 뒤에만 찍는다(2026-10-17 Codex 2차): 실패·사용법 오류·근거 거부가 마커를 움직이면 BENCH_PENDING 기준점이 측정 없이 이동한다.
        trap 'if [ "$?" -eq 0 ]; then mkdir -p "$HOME/.claude/_usage" 2>/dev/null; touch "$HOME/.claude/_usage/bench-last" 2>/dev/null; fi' EXIT
        ;;
esac

case "$ACTION" in
    init)
        DESC="${2:-}"
        BENCH_ID="${3:-bench-$(date +%Y%m%d-%H%M%S)}"
        BENCH_FILE="$BENCH_DIR/$BENCH_ID.md"
        if [ -f "$BENCH_FILE" ]; then
            echo "❌ 벤치 ID '$BENCH_ID' 이미 존재" >&2
            exit 1
        fi
        cat > "$BENCH_FILE" <<EOF
# Harness Bench: $BENCH_ID

- **작업 설명**: $DESC
- **초기화**: $(date -Iseconds)
- **상태**: 측정 대기

## Before
(미측정)

## After
(미측정)

## Gate 판정
(미산출)

## 비교 결과
(미산출)
EOF
        # WHY: 저장 실패(읽기 전용·없는 경로)를 뒤의 echo 가 성공(exit 0)으로 덮지 않게 반환값을 먼저 확인한다(2026-10-17 Codex 3차). 실패하면 마커도 안 찍힌다.
        INIT_RC=$?
        [ "$INIT_RC" -eq 0 ] || { echo "❌ 벤치 파일 생성 실패(rc=$INIT_RC): $BENCH_FILE" >&2; exit 1; }
        echo "✅ 벤치 초기화: $BENCH_FILE"
        ;;
    before|after)
        BENCH_ID="${2:-}"
        SUMMARY="${3:-}"
        BENCH_FILE="$BENCH_DIR/$BENCH_ID.md"
        [ ! -f "$BENCH_FILE" ] && { echo "❌ 벤치 ID '$BENCH_ID' 미존재" >&2; exit 1; }
        TIMESTAMP=$(date -Iseconds)
        # WHY: 원시 근거 경로 강제 (2026-08-25): 요약에 '/'가 든 경로 토큰이 없으면 기록 거부
        OK_PATH=0; OK_GAP=0
        EVID=""
        good_evidence() {   # WHY: 원시 근거: 실존 · 일반 파일 · 비어있지 않음 · $HOME 아래(작업 산출물) · _bench 밖 (5·6라운드: /dev/null·/etc/hosts 통과)
            [ -n "$1" ] && [ -f "$1" ] && [ -s "$1" ] || return 1
            local r; r="$(readlink -f "$1")"
            case "$r" in "$HOME_REAL"/*) : ;; *) return 1 ;; esac
            case "$r" in "$BENCH_REAL"/*|"$HOME_REAL"/.cache/*|"$HOME_REAL"/.local/*) return 1 ;; esac
            # WHY: 공백·개행이 든 실경로는 거부 — 사이클 줄이 공백 토큰으로 쪼개져(gate 의 evidence= 파싱) 결박이 깨진다 (2026-10-01 감사 P6)
            case "$r" in *[[:space:]]*) echo "❌ 근거 실경로에 공백이 있음: $r" >&2; return 1 ;; esac
            # WHY: 값-내용 결박 (6라운드 렌즈3 실측: 무관 파일을 path= 로 걸고 조작 수치 3회면 PASS):
            #  1) 근거 파일 안에 이번 요약의 attempts=/interventions=/qa_fail= 토큰이 그대로 있어야 한다(QA 리포트·세션 로그가 지표를 명시)
            #  2) 같은 벤치에서 같은 근거 파일 재사용 금지  3) 근거 파일 mtime 이 직전 사이클 기록 시각 이후여야 한다(기존 무관 파일 사후 인용 차단)
            #  5) 출처 형식: 자유 형식 텍스트가 아니라 QA 리포트·와쳐 로그·발사 state·세션 transcript 류 파일명만 (7라운드 렌즈2·Grok — 여전히 자기보고 도구이며 출처 위조를 완전히 막지는 못한다, SKILL 정직 표기)
            case "$(basename "$r")" in
                qa-report*.md|*qa-report*.md|*watcher*.log|launch-state-*.json|session*.log|train*.log|*eval*.log) : ;;
                *.jsonl) case "$r" in "$CLAUDE_REAL"/projects/*/*.jsonl|"$CLAUDE_REAL"/jobs/*/*.jsonl) : ;;   # WHY: 세션 transcript 경로만 (8라운드 렌즈2: ~/attempts.jsonl 위조)
                         *) echo "❌ *.jsonl 근거는 세션 transcript 경로(~/.claude/projects/*/ 또는 jobs/*/)만: $r" >&2; return 1 ;; esac ;;
                *) echo "❌ 근거 파일명이 허용 형식(qa-report*.md·*watcher*.log·launch-state-*.json·transcript *.jsonl·session*/train*/*eval*.log)이 아님: $r" >&2; return 1 ;;
            esac
            local k
            for k in attempts interventions qa_fail; do
                # WHY: 지표마다 값은 하나만 (2026-10-01 감사 P6): 근거 검사는 첫 값, gate 판정은 마지막 값을 써서 중복이면 둘이 갈렸다
                local ndup; ndup=$(printf '%s\n' "$SUMMARY" | tr -s '[:space:]' '\n' | grep -cE "^$k=[0-9]+$")
                [ "$ndup" -le 1 ] || { echo "❌ 요약에 '$k=' 지표가 ${ndup}번 — 지표마다 값 하나만 허용" >&2; return 1; }
                local tokv; tokv=$(printf '%s\n' "$SUMMARY" | tr -s '[:space:]' '\n' | grep -m1 -E "^$k=[0-9]+$")
                # WHY: 토큰은 숫자 경계로 정확 일치 (7라운드 Grok: 파일 attempts=30 이 요약 attempts=3 에 부분 일치)
                if ! { [ -n "$tokv" ] && grep -qE -- "(^|[^A-Za-z0-9_=])${tokv}([^0-9]|$)" "$r"; }; then
                    echo "❌ 근거 파일에 '$tokv' 토큰이 없음: $r (지표는 근거 파일이 명시해야 함)" >&2; return 1
                fi
            done
            if [ "$ACTION" = "after" ]; then   # NEVER: 요약에만 적은 무관작업개재=Y 를 받지 않는다(근거 파일 안에 있어야 함)
                grep -qE -- '(^|[^A-Za-z0-9_])무관작업개재=Y([^A-Za-z0-9]|$)' "$r" || { echo "❌ 근거 파일에 '무관작업개재=Y' 가 없음: $r" >&2; return 1; }
            fi
            grep -qF -- "evidence=$r " "$BENCH_FILE" && { echo "❌ 같은 근거 파일을 이 벤치에서 이미 사용: $r" >&2; return 1; }
            # WHY: 내용 해시로도 재사용 판정 (10라운드 렌즈3: 같은 바이트를 파일명만 바꿔 3회 인용하면 경로 검사가 뚫렸다)
            grep -qF -- "evidence_sha=$(sha256sum "$r" | cut -c1-16)" "$BENCH_FILE" && { echo "❌ 같은 내용(sha)의 근거를 이 벤치에서 이미 사용: $r" >&2; return 1; }
            # WHY: 최근성은 ctime 기준 (touch 로 mtime 만 올리는 조작 차단 — 7라운드 Grok)
            local last; last=$(grep -oE '^- 사이클 [0-9]+ \([^)]+\)' "$BENCH_FILE" | sed -E 's/.*\((.*)\)/\1/' | sort | tail -1)
            local ct; ct=$(date -d "@$(stat -c %Z "$r")" -Iseconds)
            if [ -n "$last" ] && [ "$ct" \< "$last" ]; then
                echo "❌ 근거 파일 ctime($ct)이 직전 사이클 기록($last)보다 앞섬 — 이 사이클의 산출물이 아님: $r" >&2; return 1
            fi
            EVID="$r"
            return 0
        }
        set -f   # WHY: 글롭 억제 (4라운드 검수: 요약 토큰 '*/*' 가 CWD 의 a/b 로 확장돼 -e 를 통과했다)
        for tok in $SUMMARY; do
            case "$tok" in
                path=*) v="${tok#path=}"; good_evidence "$v" && OK_PATH=1 ;;   # WHY: path= 값은 실존·비어있지 않은 일반 파일 (4·5라운드 검수)
                무관작업개재=Y) OK_GAP=1 ;;
                */*) good_evidence "$tok" && OK_PATH=1 ;;
            esac
        done
        set +f
        if [ "$OK_PATH" != 1 ]; then
            echo "❌ $ACTION 기록 거부: 요약에 **실존하는** 원시 근거 경로(세션 로그·QA 리포트·watcher.log 등, -e 통과) 또는 'path=' 키가 없음 ('3/50' 같은 슬래시 토큰은 불인정)" >&2
            exit 3
        fi
        # WHY: After 는 무관 작업 개재가 스크립트 강제 (4라운드 Codex 지적: SKILL 만 요구하고 코드가 안 세면 N 으로 3회 넣어도 PASS)
        if [ "$ACTION" = "after" ] && [ "$OK_GAP" != 1 ]; then
            echo "❌ after 기록 거부: 요약에 '무관작업개재=Y' 가 없음 — 변경 직후 같은 맥락 측정은 과대평가라 무관 작업 1개+ 뒤에 재고 그 사실을 토큰으로 남겨야 함 (N 이면 기록 자체 거부)" >&2
            exit 3
        fi
        # WHY: 사이클 누적 (2026-08-25): 덮어쓰지 않고 '- 사이클 N (ts): 요약' 줄을 섹션 끝에 추가
        SECTION="## ${ACTION^}"
        NCYC=$(awk -v sec="$SECTION" '$0==sec{in_sec=1;next} in_sec&&/^## /{in_sec=0} in_sec&&/^- 사이클 /{n++} END{print n+0}' "$BENCH_FILE")
        NCYC=$((NCYC+1))
        # WHY: 근거 파일을 사이클과 결박: 기록 시점 sha256 을 줄에 고정 → gate 가 재검증 (6라운드 Grok: 존재만 보면 임의 파일로 게이트 통과)
        EVSHA="$(sha256sum "$EVID" | cut -c1-16)"
        # WHY: 줄은 ENVIRON 으로 넘긴다 (2026-10-01 감사 P6): `awk -v` 는 값의 백슬래시를 이스케이프로 해석해 요약·경로의
        # `\t`·`\n` 이 탭·개행으로 바뀌어 사이클 줄이 쪼개졌다.
        BENCH_LINE="- 사이클 $NCYC ($TIMESTAMP): $SUMMARY evidence=$EVID evidence_sha=$EVSHA" awk -v sec="$SECTION" '
            BEGIN { line = ENVIRON["BENCH_LINE"] }
            $0 == sec { print; in_sec=1; next }
            in_sec && /^\(미측정\)$/ { next }          # init 이 심은 placeholder 는 첫 사이클에서 제거 (10라운드 렌즈3)
            in_sec && /^## / { print line; in_sec=0 }
            { print }
            END { if (in_sec) print line }
        ' "$BENCH_FILE" > "$BENCH_FILE.tmp" && mv "$BENCH_FILE.tmp" "$BENCH_FILE"
        WRITE_RC=$?
        if [ "$WRITE_RC" -ne 0 ]; then
            rm -f "$BENCH_FILE.tmp" 2>/dev/null
            echo "❌ $ACTION 기록 저장 실패(rc=$WRITE_RC): $BENCH_FILE" >&2
            exit 1
        fi
        echo "✅ $ACTION 기록 (사이클 $NCYC): $BENCH_FILE"
        if [ "$ACTION" = "after" ]; then
            echo ""
            echo "📊 비교 보고 (각 섹션 마지막 사이클):"
            echo "  Before: $(awk '/^## Before/{f=1;next} /^## /{f=0} f&&/^- 사이클/{l=$0} END{print (l==""?"(미측정)":l)}' "$BENCH_FILE" | cut -c1-160)"
            echo "  After:  $(awk '/^## After/{f=1;next} /^## /{f=0} f&&/^- 사이클/{l=$0} END{print (l==""?"(미측정)":l)}' "$BENCH_FILE" | cut -c1-160)"
        fi
        ;;
    gate)
        BENCH_ID="${2:-}"
        BENCH_FILE="$BENCH_DIR/$BENCH_ID.md"
        [ ! -f "$BENCH_FILE" ] && { echo "❌ 벤치 ID '$BENCH_ID' 미존재" >&2; exit 1; }

        # WHY: 사이클 단위 파싱 (2026-08-25 v2, 3라운드 검수 반영): 각 '- 사이클 N' 라인에서 key=N 을 뽑고
        # **전 사이클 평균**으로 판정한다(마지막 사이클만 좋게 쓰는 조작 차단, Anthropic 3사이클 평균 권장과 일치).
        # 어느 사이클이든 게이트 metric 이 빠지면 inconclusive.
        cycle_vals() {
            awk -v sec="$1" -v k="$2" '
                $0 == sec { in_sec=1; next }
                in_sec && /^## / { in_sec=0 }
                in_sec && /^- 사이클 / { v=""; c=0; n=split($0,t," "); for(i=1;i<=n;i++) if (t[i] ~ "^"k"=[0-9]+$") { split(t[i],a,"="); v=a[2]; c++ } print (c==1 ? v : "") }   # 같은 지표가 2번 이상이면 값 없음 취급 → inconclusive (기록기와 같은 «값 하나» 규칙)
            ' "$BENCH_FILE"
        }
        count_cycles() { cycle_vals "$1" attempts | wc -l; }
        mean_of() { cycle_vals "$1" "$2" | awk 'NF{s+=$1;n++} END{ if(n) printf "%.2f", s/n }'; }
        NB=$(count_cycles "## Before"); NA=$(count_cycles "## After")
        NMIN=$(( NB < NA ? NB : NA ))
        # WHY: 3사이클 게이트 (2026-08-25 룰→스크립트 강제): min(nB,nA) < 3 이면 잠정, Tier-1 통과 아님
        if [ "$NMIN" -lt 3 ]; then
            echo "⚠️  gate 잠정(n=${NMIN}: before ${NB}·after ${NA}) — 3사이클 미만이라 Tier-1 통과로 취급하지 않음 (exit 2). 사이클을 더 쌓은 뒤 재실행"
            exit 2
        fi
        MISSING=0
        for sec in "## Before" "## After"; do
            for k in attempts interventions qa_fail; do
                if cycle_vals "$sec" "$k" | grep -q '^$'; then MISSING=1; fi
            done
        done
        if [ "$MISSING" -eq 1 ]; then
            echo "⚠️  gate inconclusive: 게이트 metric(attempts/interventions/qa_fail)이 빠졌거나 한 사이클에 같은 지표가 중복된 사이클이 있음 (exit 2)"
            echo "   모든 사이클 요약에 'attempts=N interventions=N qa_fail=N' 을 지표마다 하나씩 필요"
            exit 2
        fi
        # WHY: 근거 파일 재검증 (6·8라운드): 각 사이클 줄의 evidence=/evidence_sha= 가 현재 파일과 일치하고, 기록기 조건(파일명 형식·$HOME 경계·
        # 토큰 실재·After 의 무관작업개재=Y 파일 내 실재)을 **gate 에서 다시** 통과해야 판정 — 기록기를 안 타고 벤치 md 를 손으로 써도 같은 검사를 받는다
        gate_evidence_check() {   # NEVER: 이 함수를 `$( )` 안에 인라인하지 않는다. case 패턴 `)` 가 bash 파서를 깨뜨림(실측)
            local sec e s line k tv r ts ct seen prev
            seen=""; prev=""
            # WHY: 줄 순서(파일 순)대로 ts 를 뽑아 재사용·ctime 순서까지 gate 에서 재검증 (9라운드 렌즈3: 기록기 규칙 두 개가 gate 에 없었다)
            awk '/^## Before/{sec="B"} /^## After/{sec="A"} /^- 사이클 /{e="";s="";ts=""; if (match($0,/\(([^)]+)\)/)) ts=substr($0,RSTART+1,RLENGTH-2); n=split($0,t," "); for(i=1;i<=n;i++){ if(t[i]~"^evidence="){e=substr(t[i],10)} if(t[i]~"^evidence_sha="){s=substr(t[i],14)} } if(e==""||s=="") {print "missing"} else {print sec"\t"e"\t"s"\t"ts"\t"$0} }' "$BENCH_FILE" \
            | sort -t $'\t' -k4,4 \
            | while IFS=$'\t' read -r sec e s ts line; do   # NEVER: ts 순 정렬을 빼지 않는다. Before/After 는 섹션별로 모여 있지만 기록은 시간순 교차다
                if [ "$sec" = "missing" ]; then echo "근거 결박 없는 사이클 줄"; continue; fi
                [ -f "$e" ] && [ "$(sha256sum "$e" | cut -c1-16)" = "$s" ] || { echo "근거 불일치: $e"; continue; }
                r="$(readlink -f "$e")"
                case " $seen " in *" $r "*|*" sha:$s "*) echo "근거 파일 재사용(경로 또는 내용 해시): $e"; continue ;; esac
                seen="$seen $r sha:$s"
                ct=$(date -d "@$(stat -c %Z "$r")" -Iseconds)
                if [ -n "$prev" ] && [ "$ct" \< "$prev" ]; then echo "근거 ctime($ct)이 직전 사이클 기록($prev)보다 앞섬: $e"; fi
                prev="$ts"
                case "$r" in "$HOME_REAL"/*) : ;; *) echo "근거가 HOME 밖: $e"; continue ;; esac
                case "$r" in "$BENCH_REAL"/*|"$HOME_REAL"/.cache/*|"$HOME_REAL"/.local/*) echo "근거가 제외 경로(_bench/.cache/.local): $e"; continue ;; esac   # WHY: 기록기와 동일 제외 (9라운드 Grok)
                case "$(basename "$e")" in
                    qa-report*.md|*qa-report*.md|*watcher*.log|launch-state-*.json|session*.log|train*.log|*eval*.log) : ;;
                    *.jsonl) case "$r" in "$CLAUDE_REAL"/projects/*/*.jsonl|"$CLAUDE_REAL"/jobs/*/*.jsonl) : ;; *) echo "근거 형식 위반: $e"; continue ;; esac ;;
                    *) echo "근거 형식 위반: $e"; continue ;;
                esac
                for k in attempts interventions qa_fail; do
                    tv=$(printf '%s\n' "$line" | tr -s '[:space:]' '\n' | grep -m1 -E "^${k}=[0-9]+\$")
                    [ -n "$tv" ] && grep -qE -- "(^|[^A-Za-z0-9_=])${tv}([^0-9]|\$)" "$e" || echo "근거 파일에 $k 토큰 없음: $e"
                done
                if [ "$sec" = "A" ]; then
                    grep -qE -- '(^|[^A-Za-z0-9_])무관작업개재=Y([^A-Za-z0-9]|$)' "$e" || echo "After 근거 파일에 무관작업개재=Y 없음: $e"
                fi
              done
        }
        EVBAD=$(gate_evidence_check)
        if [ -n "$EVBAD" ]; then
            echo "⚠️  gate inconclusive: 근거 파일 결박 실패 (exit 2)"; printf '   %s\n' "$EVBAD"; exit 2
        fi
        # NEVER: After 전 사이클의 무관작업개재=Y 확인을 gate 에서 빼지 않는다. 기록 시에도 거부하지만 손으로 쓴 파일은 기록기를 거치지 않는다.
        NGAP=$(awk '$0=="## After"{s=1;next} s&&/^## /{s=0} s&&/^- 사이클 /&&/무관작업개재=Y/{n++} END{print n+0}' "$BENCH_FILE")
        if [ "$NGAP" -lt "$NA" ]; then
            echo "⚠️  gate inconclusive: After 사이클 ${NA}개 중 '무관작업개재=Y' 표기가 ${NGAP}개뿐 (exit 2) — 같은 맥락 즉시 측정분은 판정에 쓰지 않음"
            exit 2
        fi

        B_ATT=$(mean_of "## Before" attempts); B_INT=$(mean_of "## Before" interventions); B_QAF=$(mean_of "## Before" qa_fail)
        A_ATT=$(mean_of "## After" attempts);  A_INT=$(mean_of "## After" interventions);  A_QAF=$(mean_of "## After" qa_fail)
        B_TOK=$(mean_of "## Before" tokens); A_TOK=$(mean_of "## After" tokens)

        echo "📊 Gate 판정 결과 (사이클 평균, before n=${NB} · after n=${NA}):"
        echo "  attempts:      ${B_ATT} → ${A_ATT}"
        echo "  interventions: ${B_INT} → ${A_INT}"
        echo "  qa_fail:       ${B_QAF} → ${A_QAF}"
        [ -n "$B_TOK" ] || B_TOK="(미기록)"
        [ -n "$A_TOK" ] || A_TOK="(미기록)"
        echo "  tokens (모니터 전용, 게이트 제외): ${B_TOK} → ${A_TOK}"

        REGRESSION=0
        IMPROVED=0
        for pair in "${B_ATT}:${A_ATT}" "${B_INT}:${A_INT}" "${B_QAF}:${A_QAF}"; do
            bv="${pair%%:*}"
            av="${pair##*:}"
            awk -v a="$av" -v b="$bv" 'BEGIN{exit !(a > b)}' && REGRESSION=1
            awk -v a="$av" -v b="$bv" 'BEGIN{exit !(a < b)}' && IMPROVED=1
        done

        if [ "$REGRESSION" -eq 1 ]; then
            echo "  판정: ❌ FAIL — 게이트 metric 악화 (exit 1)"
            exit 1
        elif [ "$IMPROVED" -eq 1 ]; then
            echo "  판정: ✅ PASS — Pareto strict improvement (exit 0)"
            exit 0
        else
            echo "  판정: ⚠️  동점 — 개선 없음 (exit 1)"
            exit 1
        fi
        ;;
    report)
        BENCH_ID="${2:-}"
        BENCH_FILE="$BENCH_DIR/$BENCH_ID.md"
        [ ! -f "$BENCH_FILE" ] && { echo "❌ 벤치 ID '$BENCH_ID' 미존재" >&2; exit 1; }
        cat "$BENCH_FILE"
        ;;
    list)
        echo "📋 등록된 벤치:"
        for f in "$BENCH_DIR"/*.md; do
            [ -e "$f" ] || continue
            b="${f##*/}"; printf '  - %s\n' "${b%.md}"
        done
        ;;
    help|*)
        sed -n '2,12p' "$0"   # NEVER: 범위를 사용법 6줄(init·before·after·gate·report·list) 끝보다 짧게 잡지 않는다. 종전 2,9p 는 gate·report·list 를 잘랐다
        ;;
esac
