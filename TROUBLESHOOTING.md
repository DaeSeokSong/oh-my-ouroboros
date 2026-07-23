# Troubleshooting

Common issues and their solutions.

---

## MCP Server Not Connected

**Symptom**: `mcp__mem0__add_memory` or `mcp__tavily__search` tool not found. Agents fail on memory or search steps.

**Diagnosis**:
```bash
claude --mcp-debug
# or check settings.json
cat ~/.claude/settings.json | grep -A5 mcpServers
```

**Fix**:
1. Verify API keys are set in environment:
   ```bash
   echo $MEM0_API_KEY
   echo $TAVILY_API_KEY
   ```
2. If empty, add to shell profile (`~/.bashrc` or `~/.zshrc`):
   ```bash
   export MEM0_API_KEY="your-key-here"
   export TAVILY_API_KEY="your-key-here"
   ```
3. Restart Claude Code session after updating env vars
4. Check MCP server process is running (for self-hosted Mem0):
   ```bash
   ps aux | grep mem0
   ```

**Fallback**: If MCP is unavailable, rules fall back to file-based memory (`short-term/decisions.md`). See `rules-lazy/mcp-fallback.md`.

---

## Hook Blocking Commands

**Symptom**: Bash command silently fails or returns "blocked by hook". Claude says "실행하려고 했지만 차단되었습니다".

**Diagnosis**: `scripts/bash-write-check.sh` detected a pattern matching secrets or unsafe writes.

**Fix**:
- Check what triggered the block: look for patterns like `sk-`, `key=`, `/home/username/` in the command
- If the block is a false positive, add an exception comment in the command
- For legitimate execution: Claude will ask for explicit approval — respond with the command and `# APPROVED` prefix

**Common false positives**:
| Pattern | Why blocked | Fix |
|---------|------------|-----|
| `echo "test_key=abc"` | Matches `key=` pattern | Use `echo "test-key: abc"` |
| Path with username | Absolute path with `/home/user/` | Use `$HOME` variable |
| Long hex string | Looks like API key | Add `# not-a-secret` comment |

---

## Background Session Not Restoring

**Symptom**: `bg` tmux session missing after system restart. Background tasks not running.

**Diagnosis**:
```bash
# Check if systemd unit is active
systemctl --user status bg-restore.timer
systemctl --user status bg-restore.service

# Check restore log
cat ~/.claude/bg-restore-systemd.log
```

**Fix**:
```bash
# Re-enable systemd units
systemctl --user enable bg-restore.timer
systemctl --user start bg-restore.timer

# Manual restore
bash ~/.claude/scripts/restore-bg-sessions.sh

# Check session status
bash ~/.claude/scripts/bg-status.sh
```

**If systemd not available** (no lingering session):
```bash
loginctl enable-linger $USER
```

---

## Git Worktree Conflicts

**Symptom**: `fatal: 'path' is already checked out` when creating worktree. Multiple branches pointing to same path.

**Diagnosis**:
```bash
git worktree list
```

**Fix**:
```bash
# Remove stale worktree entry (if directory no longer exists)
git worktree prune

# Force remove specific worktree
git worktree remove --force /path/to/worktree

# If branch is locked
git worktree unlock /path/to/worktree
git worktree remove /path/to/worktree
```

**Prevention**: Always use `git worktree remove` when done with a branch. Do not delete worktree directories manually.

---

## Mem0 Memory Not Saving

**Symptom**: Decisions made in session not appearing in next session. T01 trigger fires but memory not retrievable.

**Diagnosis**:
```bash
# Test Mem0 connectivity
claude --print "search for recent decisions in project X"
```

**Possible causes**:

1. **Project name mismatch**: Mem0 uses text prefix `[project-name]` for isolation. If project name differs between sessions, memories won't surface.
   - Fix: Check that cwd-based project name is consistent

2. **Infer stripping content**: Mem0's `infer=True` may rewrite memory text, dropping specific numbers.
   - Fix: For numeric configs, include exact values in `text` field explicitly

3. **Search limit too low**: Default `limit=5` may not surface older memories.
   - Fix: Temporarily use `limit=10` for retrieval

4. **API rate limit**: Mem0 free tier has request limits.
   - Fix: Check Mem0 dashboard for rate limit status

---

## API Key Not Set / Wrong Model

**Symptom**: Claude uses wrong model or "model not found" error. Haiku/Sonnet/Opus routing not working.

**Diagnosis**:
```bash
grep '"model"' ~/.claude/settings.local.json 2>/dev/null; echo "ANTHROPIC_MODEL=$ANTHROPIC_MODEL"
# 새 세션에서 /status 로 실제 적용 모델 확인
```

**Fix**:
1. Model pin is machine-local (2026-07-15 — tracked `settings.json` has no `model` key). Set it in gitignored `~/.claude/settings.local.json`:
   ```json
   {
     "model": "opus"
   }
   ```
   If a new session's `/status` does not reflect it, export `ANTHROPIC_MODEL` in your shell instead.
2. Subagent models use aliases (`opus`/`sonnet`/`haiku`) in agent frontmatter, not settings
3. If using Claude API directly: ensure `ANTHROPIC_API_KEY` is set

---

## Context Too Large / Premature Compact

**Symptom**: Claude compacts session before work is complete. Handover context lost.

**Prevention** (built-in): At 75% context, T02 triggers automatic Mem0 backup before compact.

**If compact happened without T02**:
```bash
# Check if handover.md was written
cat ~/.claude/projects/$(pwd | tr '/' '-')/memory/short-term/handover.md
```

**Recovery**:
1. Search Mem0 for recent session state:
   ```
   search_memories(query="[project-name] session state handover", category="context")
   ```
2. If handover.md exists, read it to restore context
3. If neither: review git log for last commit to reconstruct state

---

## Scout / Coder Ignoring Rule Files

**Symptom**: Agent doesn't follow a rule from `rules-lazy/`. Behavior inconsistent with documented rule.

**Diagnosis**: Lazy rules require explicit loading. If the trigger condition was not met, the rule was not loaded.

**Fix**:
1. Check the rule file's `트리거` header — was the trigger condition present in this turn?
2. If needed, explicitly mention the rule: "apply `coding-conventions.md`"
3. For persistent rule gaps: promote the rule from lazy to eager (`rules/`)

---

## tmux Panels Not Closing After Discussion

**Symptom**: Teammate panels persist after discuss session ends. Extra tmux windows remain.

**Fix**:
```bash
# Purge all teammate panels, keep main
bash ~/.claude/scripts/tmux-panels.sh purge
```

**Prevention**: The purge condition requires all teammate opinions delivered to main AND `shutdown_request` sent to all teammates. If discussion ends abruptly (compact, error), panels may linger.

---

## ntfy Notification Not Firing

**Symptom**: No push notification when Claude session ends.

**Diagnosis**:
```bash
# Test notification manually
bash ~/.claude/scripts/claude-notify.sh "test"

# Check ntfy server
curl https://ntfy.sh/YOUR_TOPIC
```

**Fix**:
1. Verify `NTFY_TOPIC` environment variable is set
2. Verify ntfy app is installed and subscribed to correct topic
3. Check stop hook is registered in `settings.json`:
   ```json
   {
     "hooks": {
       "Stop": [{"command": "bash ~/.claude/scripts/claude-notify.sh"}]
     }
   }
   ```
