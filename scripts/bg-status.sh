#!/usr/bin/env bash
# Quick health check for Claude Code background (Agent View) sessions.
# Lists bg sessions, current state, supervisor PID, and recent restore log.
set -u

JOBS="${HOME}/.claude/jobs"
DAEMON_STATUS="${HOME}/.claude/daemon.status.json"
RESTORE_LOG="${HOME}/.claude/bg-restore.log"

echo "=== daemon supervisor ==="
if [ -r "$DAEMON_STATUS" ]; then
  python3 - <<'PY' "$DAEMON_STATUS"
import json, sys, os, time
p = sys.argv[1]
d = json.load(open(p))
pid = d.get("supervisorPid")
alive = False
if pid:
    alive = os.path.exists(f"/proc/{pid}")
print(f"  supervisorPid: {pid}  alive={alive}")
print(f"  writtenAt: {d.get('writtenAt')}")
workers = d.get("workers") or {}
print(f"  workers: {len(workers)}")
PY
else
  echo "  daemon.status.json not found"
fi

echo
echo "=== bg sessions (template:bg) ==="
shopt -s nullglob
COUNT=0
for f in "$JOBS"/*/state.json; do
  if grep -q '"template": "bg"' "$f" 2>/dev/null; then
    COUNT=$((COUNT+1))
    python3 - <<'PY' "$f"
import json, sys, os
p = sys.argv[1]
short = os.path.basename(os.path.dirname(p))
try:
    d = json.load(open(p))
except Exception as e:
    print(f"  [{short}] (unreadable: {e})")
    sys.exit(0)
name = d.get("name") or "(no name)"
state = d.get("state") or "(no state)"
cwd = d.get("cwd") or "?"
updated = d.get("updatedAt") or "?"
sid = d.get("sessionId") or "?"
print(f"  [{short}] {name}")
print(f"     state={state}  updatedAt={updated}")
print(f"     cwd={cwd}")
print(f"     sessionId={sid}")
PY
  fi
done
[ "$COUNT" -eq 0 ] && echo "  (none)"

echo
echo "=== restore log (last 10 lines) ==="
if [ -r "$RESTORE_LOG" ]; then
  tail -n 10 "$RESTORE_LOG"
else
  echo "  $RESTORE_LOG not yet created"
fi

echo
echo "=== quick commands ==="
echo "  manual restore         :  claude respawn --all"
echo "  trigger systemd restore:  systemctl --user start claude-bg-restore.service"
echo "  resume specific session:  claude --resume <sessionId>"
echo "  daemon log tail        :  tail -f ~/.claude/daemon.log"
