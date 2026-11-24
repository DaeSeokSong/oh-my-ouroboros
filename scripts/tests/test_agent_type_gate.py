"""Unit tests for agent-type-gate.py (run the hook as a subprocess, like Claude Code does).

REF: knowledge/harness/code-history/scripts__tests__test_agent_type_gate.py.md
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HOOK = pathlib.Path(__file__).resolve().parent.parent / "agent-type-gate.py"
ALLOWED_12 = ["searcher", "scout", "planner", "coder", "qa", "reviewer", "security", "researcher",
              "docs", "gitops", "citation-verifier", "tutor"]
EMPTY_HOME = tempfile.mkdtemp(prefix="gate-empty-home-")


def run(payload, home=EMPTY_HOME) -> subprocess.CompletedProcess:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    env = {**os.environ, "HOME": home}
    return subprocess.run([sys.executable, str(HOOK)], input=text, capture_output=True, text=True, check=False,
                          env=env)


def agent(sub=None, desc="", tool="Agent") -> dict:
    ti = {"description": desc, "prompt": "x"}
    if sub is not None:
        ti["subagent_type"] = sub
    return {"tool_name": tool, "tool_input": ti}


class AgentTypeGateTest(unittest.TestCase):
    def assert_pass(self, payload, home=EMPTY_HOME):
        r = run(payload, home)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def assert_deny(self, payload, home=EMPTY_HOME):
        r = run(payload, home)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout.splitlines()), 1)
        spec = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(spec["hookEventName"], "PreToolUse")
        self.assertEqual(spec["permissionDecision"], "deny")
        return spec["permissionDecisionReason"]

    def make_home(self, marker=None, age_seconds=0, content="active"):
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
        for name in ALLOWED_12:
            with self.subTest(name=name):
                self.assert_pass(agent(name))

    def test_designer_denied(self):
        for tool in ["Agent", "Task"]:
            with self.subTest(tool=tool):
                self.assertIn("(designer)", self.assert_deny(agent("designer", tool=tool)))

    def test_code_simplifier_allowed(self):
        self.assert_pass(agent("code-simplifier:code-simplifier"))

    def test_task_tool_name(self):
        self.assert_pass(agent("scout", tool="Task"))
        self.assert_deny(agent("Explore", tool="Task"))

    def test_denied_types(self):
        for sub in ["general-purpose", "Explore", "Plan", "", None]:
            with self.subTest(sub=sub):
                self.assert_deny(agent(sub, desc="sonnet: do thing"))

    def test_reason_text(self):
        self.assertEqual(self.assert_deny(agent("Explore")),
                         "표 밖 에이전트 타입(Explore)은 소집하지 않습니다. agent-routing 표의 에이전트(예: 정찰은 scout)를 쓰십시오.")

    def test_graphify_without_marker_denied(self):
        self.assert_deny(agent("general-purpose", desc="graphify extract"))
        self.assert_deny(agent("general-purpose", desc="graphify extract"), self.make_home())

    def test_graphify_with_fresh_marker_passes(self):
        home = self.make_home("file", 20 * 60)
        self.assert_pass(agent("general-purpose", desc="graphify extract chunk 3"), home)
        self.assert_pass(agent("", desc="  GraphIfy extract"), home)
        self.assert_deny(agent("Explore", desc="graphify extract"), home)

    def test_graphify_with_stale_marker_denied(self):
        self.assert_deny(agent("general-purpose", desc="graphify extract"), self.make_home("file", 31 * 60))

    def test_graphify_marker_content(self):
        for content in ["done", "activex", "active" + " " * 60 + "x", "x" * 100, ""]:
            with self.subTest(content=content[:12]):
                home = self.make_home("file", 60, content)
                self.assert_deny(agent("general-purpose", desc="graphify extract"), home)
        self.assert_pass(agent("general-purpose", desc="graphify extract"), self.make_home("file", 60, "active\n"))

    def test_graphify_future_mtime_denied(self):
        self.assert_deny(agent("general-purpose", desc="graphify extract"), self.make_home("file", -600))

    def test_graphify_description_prefix(self):
        home = self.make_home("file", 60)
        for desc in ["graphifyevil", "graphify scan", "graphify  extract", "graphify"]:
            with self.subTest(desc=desc):
                self.assert_deny(agent("general-purpose", desc=desc), home)

    def test_graphify_with_symlink_marker_denied(self):
        self.assert_deny(agent("general-purpose", desc="graphify extract"), self.make_home("symlink", 60))

    def test_graphify_must_start_description(self):
        home = self.make_home("file", 60)
        self.assert_deny(agent("general-purpose", desc="read x then graphify"), home)

    def test_codex_and_security_plugin(self):
        self.assert_pass(agent("codex:codex-rescue"))
        self.assert_pass(agent("claude-security:scan-researcher"))
        self.assert_deny(agent("codex:other"))

    def test_other_tool_passes(self):
        self.assert_pass({"tool_name": "Bash", "tool_input": {"command": "ls", "subagent_type": "Explore"}})

    def test_broken_json_passes(self):
        for raw in ["{not json", "", "[1,2]", '{"tool_name":"Agent","tool_input":{"subagent_type":5}}']:
            with self.subTest(raw=raw):
                r = run(raw)
                self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_control_chars_and_truncation(self):
        r = run(agent("Bad\nType\x1b[31m\r\t x" + "y" * 100))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout.splitlines()), 1)
        reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        shown = reason.split("(", 1)[1].split(")", 1)[0]
        self.assertLessEqual(len(shown), 64)
        self.assertTrue(shown.startswith("BadType31mx"))
        self.assertTrue(set(shown) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789:_.-"))

    def test_invisible_and_bidi_chars_removed(self):
        bad = [chr(c) for c in (0x200B, 0x200D, 0x2028, 0x2029, 0x202E, 0x2066, 0x2069, 0xFEFF)]
        r = run(agent("Ex" + "".join(bad) + "plore"))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout.splitlines()), 1)
        reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        for c in bad:
            self.assertNotIn(c, reason)
        self.assertIn("(Explore)", reason)


def load_gate():
    spec = importlib.util.spec_from_file_location("agent_type_gate_mod", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


UNIT = "claude-ontology-refresh.service"
UID = os.getuid()
NIGHTLY_PATH = f"/user.slice/user-{UID}.slice/user@{UID}.service/app.slice/{UNIT}"
V2_NIGHTLY = f"0::{NIGHTLY_PATH}\n"
GE = "graphify extract chunk 1"


class NightlyCgroupTest(unittest.TestCase):
    def setUp(self):
        self.gate = load_gate()
        self.home = tempfile.mkdtemp(prefix="gate-nh-")
        self.addCleanup(shutil.rmtree, self.home, True)
        patcher = mock.patch.dict(os.environ, {"HOME": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)

    def allowed(self, cgroup, desc=GE, sub="general-purpose", running=True):
        with (mock.patch.object(self.gate, "read_cgroup", return_value=cgroup),
              mock.patch.object(self.gate, "unit_running", return_value=running)):
            return self.gate.is_allowed(sub, desc)

    def test_nightly_unit_with_extract_allowed(self):
        self.assertTrue(self.allowed(V2_NIGHTLY))

    def test_nightly_unit_other_description_denied(self):
        for desc in ["sonnet: do thing", "read x then graphify extract", ""]:
            self.assertFalse(self.allowed(V2_NIGHTLY, desc), desc)

    def test_nightly_unit_other_type_denied(self):
        self.assertFalse(self.allowed(V2_NIGHTLY, GE, "Explore"))

    def test_interactive_scope_denied(self):
        self.assertFalse(self.allowed(f"0::/user.slice/user-{UID}.slice/session-1.scope\n"))

    def test_lookalike_paths_denied(self):
        base = f"/user.slice/user-{UID}.slice/user@{UID}.service/app.slice"
        other = UID + 1
        paths = [f"{base}/{UNIT}.evil", f"{base}/x-{UNIT}", f"{base}/claude-ontology-refresh.servic",
                 f"{base}/{UNIT}/other", f"{base}/run-x.scope/{UNIT}", f"/user.slice/app.slice/{UNIT}",
                 f"/user.slice/user-{other}.slice/user@{other}.service/app.slice/{UNIT}",
                 f"/user.slice/user-{UID}.slice/user@{other}.service/app.slice/{UNIT}", f"{NIGHTLY_PATH}/"]
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(self.allowed(f"0::{path}\n"))

    def test_unit_not_running_denied(self):
        self.assertFalse(self.allowed(V2_NIGHTLY, running=False))

    def _unit_running(self, stdout="active\n", returncode=0, which="/usr/bin/systemctl", exc=None):
        run = mock.Mock(side_effect=exc) if exc else mock.Mock(
            return_value=subprocess.CompletedProcess([], returncode, stdout, ""))
        with mock.patch.object(self.gate.shutil, "which", return_value=which), \
                mock.patch.object(self.gate.subprocess, "run", run):
            return self.gate.unit_running(), run

    def test_unit_running_states(self):
        for out, rc, want in [("active\n", 0, True), ("activating\n", 0, True), ("inactive\n", 0, False),
                              ("failed\n", 0, False), ("", 0, False), ("active\n", 1, False)]:
            with self.subTest(out=out, rc=rc):
                self.assertEqual(self._unit_running(out, rc)[0], want)

    def test_unit_running_failures_denied(self):
        for exc in [subprocess.TimeoutExpired("systemctl", 2), OSError("x")]:
            with self.subTest(exc=type(exc).__name__):
                self.assertFalse(self._unit_running(exc=exc)[0])
        self.assertFalse(self._unit_running(which=None)[0])
        ok, run = self._unit_running()
        self.assertTrue(ok)
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "/usr/bin/systemctl")
        self.assertEqual(kwargs["timeout"], 2)

    def test_systemctl_not_run_without_need(self):
        with mock.patch.object(self.gate, "unit_running") as ur:
            with mock.patch.object(self.gate, "read_cgroup", return_value=V2_NIGHTLY):
                self.gate.is_allowed("general-purpose", "sonnet: x")
                self.gate.is_allowed("Explore", GE)
            with mock.patch.object(self.gate, "read_cgroup", return_value="0::/user.slice/session-1.scope\n"):
                self.gate.is_allowed("general-purpose", GE)
            ur.assert_not_called()

    def test_unreadable_cgroup_denied(self):
        with mock.patch("builtins.open", side_effect=OSError("nope")):
            self.assertEqual(self.gate.read_cgroup(), "")
        self.assertFalse(self.allowed(""))

    def test_v1_multiline(self):
        ok = f"12:cpu,cpuacct:/user.slice\n3:name=systemd:{NIGHTLY_PATH}\n"
        self.assertTrue(self.allowed(ok))
        bad = f"12:cpu,cpuacct:{NIGHTLY_PATH}\n1:name=systemd:/user.slice/session-1.scope\n"
        self.assertFalse(self.allowed(bad))
        hybrid = f"1:name=systemd:/user.slice/session-1.scope\n0::{NIGHTLY_PATH}\n"
        self.assertTrue(self.allowed(hybrid))

    def test_marker_route_regression(self):
        scratch = pathlib.Path(self.home, ".claude", ".scratch")
        scratch.mkdir(parents=True)
        (scratch / "graphify-active").write_text("active")
        self.assertTrue(self.allowed("0::/user.slice/session-1.scope\n"))


if __name__ == "__main__":
    unittest.main()
