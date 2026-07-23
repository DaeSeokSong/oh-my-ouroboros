#!/usr/bin/env bash
# Restore Claude Code background (Agent View) sessions after reboot.
# Runs `claude respawn --all` after ensuring the daemon can be booted on-demand.
# Designed to be invoked by ~/.config/systemd/user/claude-bg-restore.service.
set -u

CLAUDE_BIN="${CLAUDE_BIN:-${HOME}/.local/bin/claude}"
LOG="${HOME}/.claude/bg-restore.log"
mkdir -p "$(dirname "$LOG")"
log() { printf '[%s] %s\n' "$(date -Iseconds)" "$*" >> "$LOG"; }

log "=== start ==="
sleep 5  # network / home mount stabilize after boot

if [ ! -x "$CLAUDE_BIN" ]; then
  log "ERROR claude binary not executable at $CLAUDE_BIN"
  exit 1
fi

BG_COUNT=$(grep -l '"template": "bg"' "$HOME/.claude/jobs/"*/state.json 2>/dev/null | wc -l)
log "bg session dirs: $BG_COUNT"
if [ "$BG_COUNT" -eq 0 ]; then
  log "no bg sessions — exit"
  exit 0
fi

log "running: $CLAUDE_BIN respawn --all"
"$CLAUDE_BIN" respawn --all >> "$LOG" 2>&1
RC=$?
log "exit=$RC"
log "=== done ==="
exit "$RC"
