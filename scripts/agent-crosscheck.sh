#!/usr/bin/env bash
# agent-crosscheck.sh — agent-eval §1.5 분모 교차 대조 (읽기 전용 계수 + 집행 기록 1줄 append)
#
# 왜 스크립트인가 (2026-08-25 11라운드): 룰 두 파일(rules-lazy/agent-eval.md · skills/learn-from-feedback/SKILL.md)에
# 같은 인라인 명령을 복사해 두니 창·디렉터리·재귀 깊이·mtime 기준이 라운드마다 어긋났고(드리프트 4회),
# 인라인 awk 의 `>=` 는 bash-write-check 훅이 리다이렉션으로 오인해 main 이 실행조차 못 했다.
# 계수 규칙: ① 로그 = _audit/agent-spawn.log 의 post 줄 ② transcript = ~/.claude/projects/*/*.jsonl (세션 최상위만,
#   */subagents/*.jsonl 제외) 안에서 이벤트 timestamp ≥ 로그 첫 기록 시각(D)인 Agent tool_use 의 id 를 중복 제거(jq 필요, 없으면 «분모 미상» exit 2).
# 판정: 같은 자릿수면 "일치"(±10% 이내면 일치, 그 밖은 분모 불일치), 자릿수가 다르면 "분모 미상".
# 집행 기록: ~/.claude/_evolve/crosscheck.tsv 에 `일시 \t D \t log \t transcript \t 판정[\t auto]` 1줄 append (§3 게이트는 최신 판정이 "일치"일 때만).
# 최신 판정 = crosscheck.tsv 의 **마지막 줄**(append-only 라 파일 순서=시간 순서, 12라운드 렌즈3: 판별 방법 미정의 교정).
#   `latest` 부명령: 그 줄을 출력하고 판정이 "일치"면 exit 0, 아니면(기록 없음 포함) exit 2. 계수·append 는 하지 않는다 — 게이트 진입 직전 재확인용.
#   한계(정직 표기, 14라운드 Grok 낮음): `latest` 는 마지막 줄의 형식만 믿는다. crosscheck.tsv 는 spawn-tree.sh 의 append-only 표에 있어 spawn 창 안의 변조는 잡히지만
#   창 밖에서 Edit 도구로 고친 줄은 못 가른다 — 의심 시 인자 없이 재실행해 새 줄을 만들고 그 원문을 인용한다.
#
# 2026-10-17 G2 개정 두 가지:
#   ① `latest` 신선도: 판정 열이 일치이고 마지막 줄 ts 의 나이가 0 이상 604800초(7일) 이하일 때만 exit 0(초 단위, 미래 ts 는 stale). 일치여도 7일을 넘으면 `stale` 을 출력하고 exit 2
#      (agent-eval 게이트는 stale 을 미통과로 본다 — 한 번의 오래된 «일치» 가 영구 통과 증표가 되던 구멍을 닫는다).
#   ② `--auto`: SessionStart(harness-usage-check.sh)가 7일 초과를 보면 `setsid nohup … --auto &` 로 띄운다. 전용 잠금
#      `_usage/crosscheck.lock` 을 `flock -n` 으로 **실행 내내** 쥔다(이미 도는 중이면 조용히 exit 0 — 세션이 겹쳐도 하나만 돈다).
#      행은 계수가 끝난 뒤에만 append 하므로(D 파싱 실패·로그 없음은 append 전에 exit 2) 실패한 시도는 성공 마커를 남기지 않는다.
#      성공 마커 `_usage/crosscheck-auto-last` 는 --auto 가 행을 append 한 직후 여기서 찍는다(6시간 안이면 SessionStart 가 다시 띄우지 않음).
#      시도 마커 `_usage/crosscheck-auto-attempt`(30분)는 harness-usage-check.sh 가 띄울 때 찍는다 — 실패하면 30분 뒤 다음 세션이 다시 시도한다.
#      자동 실행 행은 6번째 열에 `auto` 를 단다. 기존 소비자는 앞 5열만 읽으므로(`cut -f5`, spawn-tree 의 줄 형식 정규식은 앞 4열 숫자까지만) 호환된다.
set -u
export LC_ALL=C   # WHY: 바이트 단위 매칭·정렬 고정 (14라운드: 로캘 의존 `.` 매칭 실측)
LOG="$HOME/.claude/_audit/agent-spawn.log"
OUT="$HOME/.claude/_evolve/crosscheck.tsv"
FRESH_DAYS=7
if [ "${1:-}" = latest ]; then
    [ -s "$OUT" ] || { echo "최신 판정 없음: $OUT 기록 없음"; exit 2; }
    L=$(tail -n 1 "$OUT"); echo "latest: $L"
    case "$(printf '%s' "$L" | cut -f5)" in 일치) ;; *) exit 2 ;; esac
    TS_E=$(date -d "$(printf '%s' "$L" | cut -f1)" +%s 2>/dev/null) || { echo "stale: ts 파싱 실패"; exit 2; }
    # WHY: 정수 일수 나눗셈은 7일 23시간을 «7일» 로 보아 통과시킨다. 미래 ts(시계 오류·위조)도 stale.
    AGE_S=$(( $(date +%s) - TS_E ))
    [ "$AGE_S" -ge 0 ] && [ "$AGE_S" -le $(( FRESH_DAYS * 86400 )) ] \
        || { echo "stale: 마지막 일치의 나이 ${AGE_S}초(허용 0~$(( FRESH_DAYS * 86400 ))초) — 인자 없이 재실행해 새 줄을 만든다"; exit 2; }
    exit 0
fi
AUTO_COL=""
if [ "${1:-}" = "--auto" ]; then
    mkdir -p "$HOME/.claude/_usage" 2>/dev/null
    exec 9>"$HOME/.claude/_usage/crosscheck.lock" || exit 0
    flock -n 9 || exit 0
    AUTO_COL=$'\tauto'
fi
[ -s "$LOG" ] || { echo "분모 미상: $LOG 없음/비어 있음"; exit 2; }
D=$(head -1 "$LOG" | cut -f1)
DU=$(date -u -d "$D" +%Y-%m-%dT%H:%M:%S 2>/dev/null) || { echo "D 파싱 실패: $D"; exit 2; }
NLOG=$(grep -c $'\tpost\t' "$LOG")
# WHY: grep 은 후보 줄 선별용이고, 줄 안의 Agent tool_use 는 jq 가 전부 센다. 한 assistant 메시지에 Agent 호출이 여럿이면 줄마다 첫 id 하나만 세던 종전 awk 가 누락했다(2026-10-17).
command -v jq >/dev/null 2>&1 || { echo "분모 미상: jq 없음"; exit 2; }
NTR=$(find "$HOME/.claude/projects" -mindepth 2 -maxdepth 2 -name '*.jsonl' -newermt "$D" -exec grep -h '"name":"Agent"' {} + 2>/dev/null \
    | jq -rR --arg d "$DU" 'fromjson? | select(.timestamp >= $d) | .message.content[]? | select(type=="object" and .type=="tool_use" and .name=="Agent") | .id' \
    | sort -u | wc -l)
digits() { printf '%s' "${#1}"; }
if [ "$(digits "$NLOG")" != "$(digits "$NTR")" ]; then
    VERDICT="분모 미상"
else
    LO=$(( NLOG * 9 / 10 )); HI=$(( NLOG * 11 / 10 + 1 ))
    if [ "$NTR" -ge "$LO" ] && [ "$NTR" -le "$HI" ]; then VERDICT="일치"; else VERDICT="분모 불일치"; fi
fi
mkdir -p "$(dirname "$OUT")"
# WHY: 자동 실행의 성공 마커는 행이 append 된 직후에만 찍는다(harness-usage-check.sh 가 6시간 재시도 간격으로 읽음. 시도 마커는 그쪽이 띄울 때 찍는다).
if printf '%s\t%s\t%s\t%s\t%s%s\n' "$(date -Iseconds)" "$D" "$NLOG" "$NTR" "$VERDICT" "$AUTO_COL" >> "$OUT" && [ -n "$AUTO_COL" ]; then
    touch "$HOME/.claude/_usage/crosscheck-auto-last" 2>/dev/null
fi
echo "D=$D log_post=$NLOG transcript_agent_uniq=$NTR 판정=$VERDICT (기록: $OUT)"
case "$VERDICT" in 일치) exit 0 ;; *) exit 2 ;; esac
