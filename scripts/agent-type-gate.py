"""PreToolUse hook: deny Agent/Task calls whose subagent_type is outside the harness allow-list.

Registration (user does it): settings.json
PreToolUse, matcher `Agent|Task`, command `python3 $HOME/.claude/scripts/agent-type-gate.py`.

Contract: hook JSON on stdin. Unreadable JSON or other tools exit 0 without blocking (a broken hook must not stop
work). Denial is a one-line hookSpecificOutput JSON on stdout with exit 0.

graphify marker: general-purpose passes only when (1) the description, stripped and lowercased, starts with
`graphify extract` and (2) the marker file `~/.claude/.scratch/graphify-active` is a regular file (not a symlink)
modified within the last 30 minutes (future mtime rejected) whose content (at most 64 bytes, stripped) is exactly
`active`. Who: main writes `active` with Write right before dispatching the /graphify extraction subagents
(skills/graphify/SKILL.md Step B2) and overwrites it with `done` with Write once extraction ends (rm is blocked by
a hook, so the marker is closed by content).

Nightly route: the nightly ontology refresh
(scripts/ontology-refresh.sh, ExecStart of the user unit `claude-ontology-refresh.service`) runs a headless Claude
that dispatches the same extraction agents but never writes the marker file. So general-purpose also passes when
(1) the description starts with `graphify extract` (same rule as above, still required), (2) the WHOLE systemd
cgroup path of this hook process in /proc/self/cgroup (cgroup v2 `0::/...` or the v1 `name=systemd` line) equals
exactly `/user.slice/user-<uid>.slice/user@<uid>.service/app.slice/claude-ontology-refresh.service` with
<uid>=os.getuid() (the unit's Slice is app.slice, checked with `systemctl --user show -p Slice`), and (3) the unit is
really running: `systemctl --user show claude-ontology-refresh.service -p ActiveState --value` is `active` or
`activating` (absolute path via shutil.which, 2 s timeout, any failure means False). Step (3) only runs when the
description matches and the marker route failed, so normal calls pay nothing.
REMAINING RISK (stated honestly, not a guarantee):
processes under user@<uid>.service (for example started with `systemd-run --user`) can be moved into the real unit
cgroup because app.slice is user-owned, so while the unit runs such a process can pass. Also, during the nightly
window (up to 1 hour) an injected phrase in a file the headless session reads can imitate the same description.
No test-only override variable exists on purpose (it would itself be a bypass); tests monkeypatch `read_cgroup` and
`unit_running`.
REF: knowledge/harness/code-history/scripts__agent-type-gate.py.md
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time

ALLOWED = {
    "searcher", "scout", "planner", "coder", "qa", "reviewer", "security", "researcher",
    "docs", "gitops", "citation-verifier", "tutor",
    "codex:codex-rescue",
    "code-simplifier:code-simplifier",  # WHY: conditional refactoring used by agents/coder.md
}
ALLOWED_PREFIXES = ("claude-security:",)
MARKER = "~/.claude/.scratch/graphify-active"
MARKER_TTL = 30 * 60
NIGHTLY_UNIT = "claude-ontology-refresh.service"
REASON = "표 밖 에이전트 타입({t})은 소집하지 않습니다. agent-routing 표의 에이전트(예: 정찰은 scout)를 쓰십시오."


def marker_fresh() -> bool:
    path = os.path.expanduser(MARKER)
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or not 0 <= time.time() - st.st_mtime <= MARKER_TTL:
            return False
        with open(path, "rb") as f:
            raw = f.read(65)
        return len(raw) <= 64 and raw.decode("utf-8", "replace").strip() == "active"
    except OSError:
        return False


def read_cgroup() -> str:
    try:
        with open("/proc/self/cgroup", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def unit_running() -> bool:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False
    try:
        r = subprocess.run([systemctl, "--user", "show", NIGHTLY_UNIT, "-p", "ActiveState", "--value"],
                           capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() in ("active", "activating")


def in_nightly_unit() -> bool:
    uid = os.getuid()
    expected = f"/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{NIGHTLY_UNIT}"
    for line in read_cgroup().splitlines():
        hier, _, rest = line.partition(":")
        ctrl, _, path = rest.partition(":")
        is_systemd = (hier == "0" and ctrl == "") or "name=systemd" in ctrl.split(",")
        if is_systemd and path == expected:
            return unit_running()
    return False


def is_allowed(subagent_type: str, description: str) -> bool:
    if subagent_type == "general-purpose":
        return description.strip().lower().startswith("graphify extract") and (marker_fresh() or in_nightly_unit())
    return subagent_type in ALLOWED or subagent_type.startswith(ALLOWED_PREFIXES)


def main() -> int:
    try:
        data = json.load(sys.stdin)
        tool_name = data.get("tool_name")
        tool_input = data.get("tool_input") or {}
        sub = tool_input.get("subagent_type") or "general-purpose"
        desc = tool_input.get("description") or ""
        if not isinstance(sub, str) or not isinstance(desc, str):
            raise TypeError("unexpected field type")
    except Exception as exc:  # noqa: BLE001
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
