#!/usr/bin/env bash
# UserPromptSubmit hook — 사용자 프롬프트를 _evolve/prompts.jsonl에 append.
#
# 목적: 자가진화 감지의 "수집층". LLM 외부(hook)에서 실행되므로 토큰 0.
#       반복 패턴 감지는 이 로그를 pattern-detect.sh가 빈도 분석한다.
# 입력: stdin으로 UserPromptSubmit hook payload(JSON) 수신.
# 안전: 실패해도 사용자 입력 흐름을 막지 않도록 항상 exit 0.
# REF: knowledge/harness/code-history/scripts__prompt-log.sh.md
set -uo pipefail

# WHY: 자동화가 띄우는 -p 세션의 프롬프트가 수집되면 반복 패턴 감지를 오염시킨다(2026-07-16 실측: 추출 코디네이터 프롬프트가 빈도 3위 ×5).
# 자동화 호출부는 이 변수를 export 한다.
[ -n "${CLAUDE_PROMPT_LOG_SKIP:-}" ] && exit 0
# WHY: claudenews 플러그인의 번역·요약 자식 세션은 위 변수를 export 하지 않아 T40 후보 1·2위(×44 · ×24)를 차지했다(2026-09-11 실측).
# 이 표식은 플러그인이 자식 env 에 직접 넣는다(hooks/background_claude.py::build_background_env).
[ -n "${CODE_EARN_BACKGROUND_CHILD:-}" ] && exit 0

# WHY: 프롬프트 원문(앞 2000자)이 담기므로 같은 그룹 계정이 읽지 못하게 600 으로 만든다(2026-10-01 감사 D).
# 새 파일(로테이션 임시 파일 포함)은 umask 로, 이미 664 로 만들어진 기존 파일은 chmod 로 맞춘다.
umask 077
EVOLVE_DIR="$HOME/.claude/_evolve"
LOG="$EVOLVE_DIR/prompts.jsonl"
mkdir -p "$EVOLVE_DIR" 2>/dev/null || exit 0
[ -f "$LOG" ] && chmod 600 "$LOG" 2>/dev/null

INPUT=$(cat 2>/dev/null) || exit 0
command -v jq >/dev/null 2>&1 || exit 0

PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // .user_prompt // .input // empty' 2>/dev/null)
[ -z "$PROMPT" ] && exit 0

# WHY: 백그라운드 태스크 알림·피어 세션 메시지·시스템 알림이 프롬프트 자리로 들어와 T40 빈도와 T12 교정 탐지를 오염시킨다
# (2026-08-15 감사, 2026-09-14 재감사 §3).
case "$PROMPT" in
  '<task-notification'*|'<agent-message'*|'<teammate-message'*|'Another Claude session sent a message'*|'{"type":"idle_notification"'*) exit 0 ;;
  '<cross-session-message'*|'<local-command-stdout'*|'[SYSTEM NOTIFICATION'*) exit 0 ;;
esac

# WHY: 200자 절단이 최근 400줄 중 89줄을 잘라 `# APPROVED` 인용 검사와 T12 교정 탐지가 문장 뒤쪽을 못 봤다(2026-09-14, 200 → 2000).
# 빈도 키는 pattern-detect 가 읽는 쪽에서 앞 200자로 잘라 쓴다.
# WHY: C 로케일에서 cut -c 는 바이트 절단이라 한글(3B)이 경계에서 깨져 로그 JSON 이 손상된다(2026-07-18 Codex).
SNIPPET=$(printf '%s' "$PROMPT" | tr '\n\t' '  ' | { python3 -c 'import sys; sys.stdout.write(sys.stdin.read()[:2000])' 2>/dev/null || cut -c1-2000; })
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "")
CWD=$(pwd 2>/dev/null || echo "")

jq -cn --arg ts "$TS" --arg cwd "$CWD" --arg p "$SNIPPET" \
  '{ts:$ts, cwd:$cwd, prompt:$p}' >> "$LOG" 2>/dev/null || exit 0

LINES=$(wc -l < "$LOG" 2>/dev/null || echo 0)
if [ "$LINES" -gt 5000 ]; then
  # WHY: 공유 "$LOG.tmp" 는 동시 세션 로테이션이 서로 덮어쓴다(2026-07-18 Codex). append 중 로테이션 유실은 빈도 로그 특성상 무해하다.
  TMP="$LOG.tmp.$$.$(date +%N 2>/dev/null || echo 0)"
  if ! { tail -n 3000 "$LOG" > "$TMP" 2>/dev/null && mv "$TMP" "$LOG" 2>/dev/null; }; then rm -f "$TMP" 2>/dev/null; fi
fi
exit 0
