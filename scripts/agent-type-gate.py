"""PreToolUse hook: deny Agent/Task calls whose subagent_type is outside the harness allow-list.

Why: "method 3 (hook block)" of agent cleanup step 4, adopted 2026-11-09 by the step 4 adoption rule (methods 1, 2, 4
failed F7 3/3 in fresh main sessions; this hook blocked both F7 inputs). Registration (user does it): settings.json
PreToolUse, matcher `Agent|Task`, command `python3 $HOME/.claude/scripts/agent-type-gate.py`.

Contract: hook JSON on stdin. Unreadable JSON or other tools exit 0 without blocking (a broken hook must not stop
work). Denial is a one-line hookSpecificOutput JSON on stdout with exit 0.

graphify marker: general-purpose passes only when (1) the description, stripped and lowercased, starts with
`graphify extract` and (2) the marker file `~/.claude/.scratch/graphify-active` is a regular file (not a symlink)
modified within the last 30 minutes (future mtime rejected) whose content (at most 64 bytes, stripped) is exactly
`active`. Who: main writes `active` with Write right before dispatching the /graphify extraction subagents
(skills/graphify/SKILL.md Step B2) and overwrites it with `done` with Write once extraction ends (rm is blocked by
a hook, so the marker is closed by content). Why: while a marker stays open, any description imitation passes for
that long, so the window is short and the content closes it early; a description alone can be imitated by an
injected prompt, so a second signal that only main's Write step produces is required.
"""
import json
import os
import re
import stat
import sys
import time

ALLOWED = {
    "searcher", "scout", "planner", "coder", "qa", "reviewer", "security", "researcher",
    "docs", "gitops", "citation-verifier", "tutor",  # designer folded into skills/figure (2026-11-10)
    "codex:codex-rescue",  # Codex delegation gate route
    "code-simplifier:code-simplifier",  # conditional refactoring used by agents/coder.md
}
ALLOWED_PREFIXES = ("claude-security:",)  # security plugin, summoned by main behind the depth gate
MARKER = "~/.claude/.scratch/graphify-active"
MARKER_TTL = 30 * 60
REASON = "표 밖 에이전트 타입({t})은 소집하지 않습니다. agent-routing 표의 에이전트(예: 정찰은 scout)를 쓰십시오."


def marker_fresh() -> bool:
    """Return True when the marker is a regular file (no symlink), modified within 30 minutes, with content `active`."""
    path = os.path.expanduser(MARKER)
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or not 0 <= time.time() - st.st_mtime <= MARKER_TTL:
            return False
        with open(path, "rb") as f:
            raw = f.read(65)  # one byte over the limit is enough to reject
        return len(raw) <= 64 and raw.decode("utf-8", "replace").strip() == "active"
    except OSError:
        return False


def is_allowed(subagent_type: str, description: str) -> bool:
    """Return True when the type is on the allow-list (general-purpose only for marked graphify extraction)."""
    if subagent_type == "general-purpose":
        return description.strip().lower().startswith("graphify extract") and marker_fresh()
    return subagent_type in ALLOWED or subagent_type.startswith(ALLOWED_PREFIXES)


def main() -> int:
    """Read the hook JSON from stdin and print a deny decision when the type is not allowed."""
    try:
        data = json.load(sys.stdin)
        tool_name = data.get("tool_name")
        tool_input = data.get("tool_input") or {}
        sub = tool_input.get("subagent_type") or "general-purpose"
        desc = tool_input.get("description") or ""
        if not isinstance(sub, str) or not isinstance(desc, str):
            raise TypeError("unexpected field type")
    except Exception as exc:  # noqa: BLE001 - fail-open: a broken hook must never block work
        print(f"agent_type_gate: unreadable hook input ({type(exc).__name__}), not blocking", file=sys.stderr)
        return 0
    if tool_name not in ("Agent", "Task") or is_allowed(sub, desc):
        return 0
    shown = re.sub(r"[^A-Za-z0-9:_.-]", "", sub)[:64]
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                  "permissionDecisionReason": REASON.format(t=shown)}}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
