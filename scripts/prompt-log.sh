#!/usr/bin/env bash
# UserPromptSubmit hook — 사용자 프롬프트를 _evolve/prompts.jsonl에 append.
#
# 목적: 자가진화 감지의 "수집층". LLM 외부(hook)에서 실행되므로 토큰 0.
#       반복 패턴 감지는 이 로그를 pattern-detect.sh가 빈도 분석한다.
# 입력: stdin으로 UserPromptSubmit hook payload(JSON) 수신.
# 안전: 실패해도 사용자 입력 흐름을 막지 않도록 항상 exit 0.
set -uo pipefail

# 자동화/헤드리스 세션 제외 (2026-07-16 — T40 수집층 자기 오염 방지): 온톨로지 타이머 등
# 자동화가 띄우는 -p 세션의 프롬프트가 수집되면 반복 패턴 감지(스킬화 후보 판정)를 오염시킨다
# — 실측: 추출 코디네이터 프롬프트가 빈도 3위(×5)로 검출됨. 자동화 호출부는 이 변수를 export.
[ -n "${CLAUDE_PROMPT_LOG_SKIP:-}" ] && exit 0

EVOLVE_DIR="$HOME/.claude/_evolve"
LOG="$EVOLVE_DIR/prompts.jsonl"
mkdir -p "$EVOLVE_DIR" 2>/dev/null || exit 0

INPUT=$(cat 2>/dev/null) || exit 0
command -v jq >/dev/null 2>&1 || exit 0

# UserPromptSubmit payload에서 프롬프트 추출 (필드명 버전차 대비 fallback)
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // .user_prompt // .input // empty' 2>/dev/null)
[ -z "$PROMPT" ] && exit 0

# 앞 200자만 보관 (민감정보·용량 최소화 — 빈도 감지엔 충분).
# UTF-8 문자 단위 절단 (2026-07-18 Codex): C 로케일에서 cut -c는 바이트 절단이라 한글(3B)이
# 경계에서 깨져 로그 JSON 손상 → python3로 문자 절단, 부재 시 cut 폴백.
SNIPPET=$(printf '%s' "$PROMPT" | tr '\n\t' '  ' | { python3 -c 'import sys; sys.stdout.write(sys.stdin.read()[:200])' 2>/dev/null || cut -c1-200; })
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "")
CWD=$(pwd 2>/dev/null || echo "")

jq -cn --arg ts "$TS" --arg cwd "$CWD" --arg p "$SNIPPET" \
  '{ts:$ts, cwd:$cwd, prompt:$p}' >> "$LOG" 2>/dev/null || exit 0

# 로테이션: 5000줄 초과 시 최근 3000줄만 유지 (무한 증가 방지)
LINES=$(wc -l < "$LOG" 2>/dev/null || echo 0)
if [ "$LINES" -gt 5000 ]; then
  # 고유 temp (2026-07-18 Codex): 공유 "$LOG.tmp"는 동시 세션 로테이션이 서로 clobber →
  # PID·nanosec로 고유화. (append-중-로테이션 유실은 빈도 로그 특성상 무해)
  TMP="$LOG.tmp.$$.$(date +%N 2>/dev/null || echo 0)"
  tail -n 3000 "$LOG" > "$TMP" 2>/dev/null && mv "$TMP" "$LOG" 2>/dev/null || rm -f "$TMP" 2>/dev/null
fi
exit 0
