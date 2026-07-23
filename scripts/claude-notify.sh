#!/bin/bash
# =============================================================
# Claude Code Notification Script v1.1
# - Phone + PC push notification (ntfy.sh)
# - Terminal bell (SSH 환경에서도 동작)
# - Desktop notification (DISPLAY 있을 때만)
# =============================================================

# ── Configuration ──
# Load from env-config if available; skip notifications if not configured.
# 양쪽 경로 모두 시도 (사용자 환경 호환): root + config/ 하위
CLAUDE_HOME="${CLAUDE_HOME:-${HOME}/.claude}"
for _cfg in "${CLAUDE_HOME}/env-config" "${CLAUDE_HOME}/config/env-config"; do
    [ -f "$_cfg" ] && source "$_cfg"
done
unset _cfg

NTFY_TOPIC="${USER_NTFY_TOPIC:-}"      # Set USER_NTFY_TOPIC in env-config (or config/env-config)
NTFY_SERVER="${NTFY_SERVER:-https://ntfy.sh}"  # Change to self-hosted URL if needed
SERVER="$(hostname -s)"                # 동적 호스트명

# ── Message ──
PROJECT="${1:-Claude}"
SUMMARY="${2:-작업 완료}"
TITLE="[$SERVER: $PROJECT]"
MSG="$SUMMARY"

# ── 1. Push Notification (ntfy.sh → Phone + PC browser) ──
# Requires USER_NTFY_TOPIC set in config/env-config; skipped if not configured.
if [ -n "$NTFY_TOPIC" ] && command -v curl &>/dev/null; then
    # --max-time (2026-07-18 Codex): 무한 curl + 말미 wait이 훅을 영구 hang → 상한 8s(훅 timeout 10s 내)
    curl -s --max-time 8 \
        -H "Title: $TITLE" \
        -H "Priority: default" \
        -H "Tags: white_check_mark" \
        -d "$MSG" \
        "$NTFY_SERVER/$NTFY_TOPIC" >/dev/null 2>&1 &
fi

# ── 2. Terminal Bell (SSH/tmux 환경에서도 동작) ──
# tmux를 통해 모든 클라이언트에 bell 전달
if [ -n "$TMUX" ]; then
    tmux run-shell "printf '\a'" 2>/dev/null
else
    printf '\a' 2>/dev/null
fi

# ── 3. Desktop Notification (DISPLAY가 있는 로컬 환경일 때만) ──
if [ -n "$DISPLAY" ] && command -v notify-send &>/dev/null; then
    notify-send -i dialog-information -u normal "$TITLE" "$MSG" 2>/dev/null &
fi


wait
