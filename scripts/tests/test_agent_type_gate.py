"""Unit tests for agent-type-gate.py (run the hook as a subprocess, like Claude Code does)."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

HOOK = pathlib.Path(__file__).resolve().parent.parent / "agent-type-gate.py"
ALLOWED_12 = ["searcher", "scout", "planner", "coder", "qa", "reviewer", "security", "researcher",
              "docs", "gitops", "citation-verifier", "tutor"]
EMPTY_HOME = tempfile.mkdtemp(prefix="gate-empty-home-")  # never holds a marker, so the real HOME cannot leak in


def run(payload, home=EMPTY_HOME) -> subprocess.CompletedProcess:
    """Run the hook with a payload (dict is JSON-encoded, str is sent raw) under the given HOME."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    env = {**os.environ, "HOME": home}
    return subprocess.run([sys.executable, str(HOOK)], input=text, capture_output=True, text=True, check=False,
                          env=env)


def agent(sub=None, desc="", tool="Agent") -> dict:
    """Build a hook payload for an Agent call."""
    ti = {"description": desc, "prompt": "x"}
    if sub is not None:
        ti["subagent_type"] = sub
    return {"tool_name": tool, "tool_input": ti}


class AgentTypeGateTest(unittest.TestCase):
    """Cases from the spec."""

    def assert_pass(self, payload, home=EMPTY_HOME):
        """Exit 0 with empty stdout."""
        r = run(payload, home)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def assert_deny(self, payload, home=EMPTY_HOME):
        """Exit 0 with a deny JSON on one line."""
        r = run(payload, home)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout.splitlines()), 1)
        spec = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(spec["hookEventName"], "PreToolUse")
        self.assertEqual(spec["permissionDecision"], "deny")
        return spec["permissionDecisionReason"]

    def make_home(self, marker=None, age_seconds=0, content="active"):
        """Create a temp HOME; marker is None (absent), 'file' or 'symlink', with mtime age_seconds ago."""
        tmp = tempfile.TemporaryDirectory(prefix="gate-home-")
        self.addCleanup(tmp.cleanup)
        scratch = pathlib.Path(tmp.name, ".claude", ".scratch")
        scratch.mkdir(parents=True)
        path = scratch / "graphify-active"
        when = time.time() - age_seconds
        if marker == "file":
            path.write_text(content)
            os.utime(path, (when, when))
        elif marker == "symlink":
            target = scratch / "real-target"
            target.write_text(content)
            os.utime(target, (when, when))
            path.symlink_to(target)
        return tmp.name

    def test_twelve_allowed(self):
        """The 12 routing-table agents pass."""
        for name in ALLOWED_12:
            with self.subTest(name=name):
                self.assert_pass(agent(name))

    def test_designer_denied(self):
        """designer was folded into the figure skill on 2026-11-10, so summoning it is denied."""
        for tool in ["Agent", "Task"]:
            with self.subTest(tool=tool):
                self.assertIn("(designer)", self.assert_deny(agent("designer", tool=tool)))

    def test_code_simplifier_allowed(self):
        """code-simplifier:code-simplifier (used by agents/coder.md) passes."""
        self.assert_pass(agent("code-simplifier:code-simplifier"))

    def test_task_tool_name(self):
        """Task is gated like Agent."""
        self.assert_pass(agent("scout", tool="Task"))
        self.assert_deny(agent("Explore", tool="Task"))

    def test_denied_types(self):
        """general-purpose without graphify, Explore, Plan, empty and missing type are denied."""
        for sub in ["general-purpose", "Explore", "Plan", "", None]:
            with self.subTest(sub=sub):
                self.assert_deny(agent(sub, desc="sonnet: do thing"))

    def test_reason_text(self):
        """Reason names the type in the specified sentence."""
        self.assertEqual(self.assert_deny(agent("Explore")),
                         "표 밖 에이전트 타입(Explore)은 소집하지 않습니다. agent-routing 표의 에이전트(예: 정찰은 scout)를 쓰십시오.")

    def test_graphify_without_marker_denied(self):
        """general-purpose with a graphify description but no marker file is denied."""
        self.assert_deny(agent("general-purpose", desc="graphify extract"))
        self.assert_deny(agent("general-purpose", desc="graphify extract"), self.make_home())

    def test_graphify_with_fresh_marker_passes(self):
        """A regular active marker modified 20 minutes ago lets a description starting with graphify extract through."""
        home = self.make_home("file", 20 * 60)
        self.assert_pass(agent("general-purpose", desc="graphify extract chunk 3"), home)
        self.assert_pass(agent("", desc="  GraphIfy extract"), home)
        self.assert_deny(agent("Explore", desc="graphify extract"), home)

    def test_graphify_with_stale_marker_denied(self):
        """An active marker last modified 31 minutes ago is stale."""
        self.assert_deny(agent("general-purpose", desc="graphify extract"), self.make_home("file", 31 * 60))

    def test_graphify_marker_content(self):
        """Only the exact content `active` opens the gate: done, junk and over-64-byte content are denied."""
        for content in ["done", "activex", "active" + " " * 60 + "x", "x" * 100, ""]:
            with self.subTest(content=content[:12]):
                home = self.make_home("file", 60, content)
                self.assert_deny(agent("general-purpose", desc="graphify extract"), home)
        self.assert_pass(agent("general-purpose", desc="graphify extract"), self.make_home("file", 60, "active\n"))

    def test_graphify_future_mtime_denied(self):
        """A marker with a future mtime is rejected."""
        self.assert_deny(agent("general-purpose", desc="graphify extract"), self.make_home("file", -600))

    def test_graphify_description_prefix(self):
        """Only the exact `graphify extract` prefix passes even with a fresh active marker."""
        home = self.make_home("file", 60)
        for desc in ["graphifyevil", "graphify scan", "graphify  extract", "graphify"]:
            with self.subTest(desc=desc):
                self.assert_deny(agent("general-purpose", desc=desc), home)

    def test_graphify_with_symlink_marker_denied(self):
        """A symlinked marker is never accepted, even when fresh."""
        self.assert_deny(agent("general-purpose", desc="graphify extract"), self.make_home("symlink", 60))

    def test_graphify_must_start_description(self):
        """graphify later in the description is not enough, even with a fresh marker."""
        home = self.make_home("file", 60)
        self.assert_deny(agent("general-purpose", desc="read x then graphify"), home)

    def test_codex_and_security_plugin(self):
        """codex:codex-rescue and the claude-security: prefix pass."""
        self.assert_pass(agent("codex:codex-rescue"))
        self.assert_pass(agent("claude-security:scan-researcher"))
        self.assert_deny(agent("codex:other"))

    def test_other_tool_passes(self):
        """Non-Agent tools are never blocked."""
        self.assert_pass({"tool_name": "Bash", "tool_input": {"command": "ls", "subagent_type": "Explore"}})

    def test_broken_json_passes(self):
        """Unreadable input exits 0 with a stderr line and no stdout."""
        for raw in ["{not json", "", "[1,2]", '{"tool_name":"Agent","tool_input":{"subagent_type":5}}']:
            with self.subTest(raw=raw):
                r = run(raw)
                self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_control_chars_and_truncation(self):
        """Characters outside [A-Za-z0-9:_.-] are removed, type is cut to 64 chars, output stays one line."""
        r = run(agent("Bad\nType\x1b[31m\r\t x" + "y" * 100))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout.splitlines()), 1)
        reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        shown = reason.split("(", 1)[1].split(")", 1)[0]
        self.assertLessEqual(len(shown), 64)
        self.assertTrue(shown.startswith("BadType31mx"))
        self.assertTrue(set(shown) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789:_.-"))

    def test_invisible_and_bidi_chars_removed(self):
        """Zero-width, bidi and line-separator characters never reach the reason string."""
        bad = [chr(c) for c in (0x200B, 0x200D, 0x2028, 0x2029, 0x202E, 0x2066, 0x2069, 0xFEFF)]
        r = run(agent("Ex" + "".join(bad) + "plore"))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout.splitlines()), 1)
        reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        for c in bad:
            self.assertNotIn(c, reason)
        self.assertIn("(Explore)", reason)


if __name__ == "__main__":
    unittest.main()
