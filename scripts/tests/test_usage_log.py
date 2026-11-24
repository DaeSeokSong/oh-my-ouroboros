"""Tests for usage-log.sh and usage_log_agent.py (intent/2026-11-24-harness-review-six-items.md 개정 2 W14).

Isolation: every run uses a temp HOME under pytest tmp_path, so the real ~/.claude/_usage is never touched.
Run: uv run --no-project --with pytest python -m pytest scripts/tests/test_usage_log.py -q -p no:cacheprovider
"""
import json
import os
import pathlib
import stat
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent
LOGGER = SCRIPTS / "usage-log.sh"
MARK = "LEAKMARK_77e1"
SID = "sess1234abcd" + MARK
AGENT = "a1b2c3d4e5f6g7h8i"
FOLDERS = ("tool-use", "rule-reads", "agent-runs", "session-events", "hook-runs")


@pytest.fixture
def env(tmp_path):
    real = tmp_path / "realclaude"
    for rel in ("rules/a.md", "rules/b.md", "knowledge/k/n.md", "other/x.md", "CLAUDE.md", 'rules/q"x.md', "rules/t\tx.md"):
        (real / rel).parent.mkdir(parents=True, exist_ok=True)
        (real / rel).write_text("x", encoding="utf-8")
    outside = tmp_path / "project" / MARK / "secret.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("x", encoding="utf-8")
    (real / "rules/link.md").symlink_to(outside)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").symlink_to(real)
    base = {**os.environ, "HOME": str(home)}

    class E:
        h = home
        claude = home / ".claude"
        root = real
        out = outside
        base_env = base

        @staticmethod
        def run(data, env=None, timeout=20):
            r = subprocess.run(["bash", str(LOGGER)], input=data, capture_output=True, env=env or E.base_env,
                               timeout=timeout, check=False)
            assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
            return r

        @staticmethod
        def rows(folder):
            d = real / "_usage" / folder
            if not d.is_dir():
                return []
            return [ln.split("\t") for f in sorted(d.iterdir()) for ln in f.read_text(encoding="utf-8").splitlines()]

    return E


def common(agent=None):
    d = {"session_id": SID, "transcript_path": f"/proj/{MARK}/t.jsonl", "cwd": f"/data/{MARK}", "permission_mode": "default"}
    if agent:
        d["agent_id"] = agent
        d["agent_type"] = "coder"
    d["effort"] = {"level": "high"}
    return d


def dump(d, spaced=False):
    return json.dumps(d, ensure_ascii=False, separators=None if spaced else (",", ":")).encode()


def post(tool, tool_input=None, response=None, ev="PostToolUse", agent=None, ms=12, mcp=None, spaced=False):
    d = {**common(agent), "hook_event_name": ev, "tool_name": tool,
         "tool_input": tool_input if tool_input is not None else {"command": f"echo {MARK}"}}
    if ev == "PostToolUse":
        d["tool_response"] = response if response is not None else {"stdout": MARK * 400}
    d["tool_use_id"] = "toolu_01"
    if ev == "PostToolUseFailure":
        d["error"] = f"failed {MARK}"
        d["is_interrupt"] = False
    if ms is not None:
        d["duration_ms"] = ms
    if mcp:
        d["mcp_server"] = mcp
    return dump(d, spaced)


def test_tool_use_and_own_hook_run(env):
    env.run(post("Bash"))
    env.run(post("Bash", ev="PostToolUseFailure", ms=7))
    rows = env.rows("tool-use")
    assert [r[1:] for r in rows] == [["sess1234", "main", "Bash", "1", "12"], ["sess1234", "main", "Bash", "0", "7"]]
    runs = env.rows("hook-runs")
    assert [r[1:8] for r in runs] == [["sess1234", "main", "PostToolUse", "usage-log", "Bash", "0", "pass"],
                                      ["sess1234", "main", "PostToolUseFailure", "usage-log", "Bash", "0", "pass"]]
    assert all(len(r) == 9 and r[8].isdigit() for r in runs)
    for f in (env.root / "_usage").rglob("*.tsv"):
        assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_mcp_name_spaced_json_and_missing_duration(env):
    env.run(post("mcp__claude_ai_Atlassian__getJiraIssue", mcp="claude.ai Atlassian", ms=345, spaced=True))
    env.run(post("Grep", ms=None))
    assert [r[3:] for r in env.rows("tool-use")] == [["mcp__claude_ai_Atlassian__getJiraIssue", "1", "345"],
                                                      ["Grep", "1", "-"]]


def test_caller_only_from_common_fields(env):
    env.run(post("Bash", agent=AGENT))
    env.run(post("SendMessage", tool_input={"agent_id": "zzzzzzzzzz", "message": "x"}))
    assert [r[2] for r in env.rows("tool-use")] == ["a1b2c3d4", "main"]


@pytest.mark.parametrize("rel,want", [
    ("rules/a.md", "rules/a.md"), ("knowledge/k/n.md", "knowledge/k/n.md"), ("CLAUDE.md", "CLAUDE.md"),
    ("other/x.md", None), ("rules/link.md", None), ("rules/../other/x.md", None), ("rules/../rules/b.md", "rules/b.md"),
    ('rules/q"x.md', 'rules/q"x.md'), ("rules/t\tx.md", "rules/tx.md"), ("rules/missing.md", "rules/missing.md"),
])
def test_rule_reads(env, rel, want):
    env.run(post("Read", tool_input={"file_path": f"{env.claude}/{rel}"}, response={"file": {"content": MARK}}))
    got = [r for r in env.rows("rule-reads")]
    assert all(len(r) == 5 for r in got)
    assert [r[3:] for r in got] == ([["read", want]] if want else [])


def test_rule_reads_ignores_outside_and_relative(env):
    for p in (str(env.out), "rules/a.md", str(env.root / "rules/a.md")):
        env.run(post("Read", tool_input={"file_path": p}))
    assert [r[4] for r in env.rows("rule-reads")] == ["rules/a.md"]
    assert len(env.rows("tool-use")) == 3


def test_failed_read_is_not_a_rule_read(env):
    env.run(post("Read", tool_input={"file_path": f"{env.claude}/rules/a.md"}, ev="PostToolUseFailure"))
    assert env.rows("rule-reads") == []


def test_instructions_loaded(env):
    for p, reason in ((f"{env.claude}/CLAUDE.md", "session_start"), (f"{env.claude}/rules/a.md", "path_glob_match"),
                      (str(env.out), "nested_traversal")):
        d = {**common(), "hook_event_name": "InstructionsLoaded", "file_path": p, "memory_type": "User", "load_reason": reason}
        env.run(dump(d))
    assert [r[3:] for r in env.rows("rule-reads")] == [["loaded:session_start", "CLAUDE.md"],
                                                        ["loaded:path_glob_match", "rules/a.md"]]


def test_session_events(env):
    env.run(dump({**common(), "hook_event_name": "SessionStart", "source": "startup", "agent_type": "x",
                  "model": "claude-opus-5-5", "session_title": MARK}))
    env.run(dump({**common(), "hook_event_name": "SessionEnd", "reason": "clear"}))
    env.run(dump({**common(), "hook_event_name": "PreCompact", "trigger": "auto", "custom_instructions": MARK}))
    env.run(dump({**common(), "hook_event_name": "PostCompact", "trigger": "manual", "compact_summary": MARK}))
    assert [r[1:] for r in env.rows("session-events")] == [
        ["sess1234", "start:startup", "claude-opus-5-5"], ["sess1234", "end:clear", "-"],
        ["sess1234", "precompact:auto", "-"], ["sess1234", "postcompact:manual", "-"]]


def agent_post(name=True):
    ti = {"description": "d", "prompt": f"long {MARK} " * 600, "subagent_type": "coder", "model": "opus", "effort": "high"}
    if name:
        ti["name"] = "worker"
    resp = {"status": "async_launched", "agentId": "abc123def456ghi78", "prompt": MARK, "resolvedModel": "claude-x",
            "name": "teamname"}
    return post("Agent", tool_input=ti, response=resp)


def test_agent_launch_line(env):
    env.run(agent_post())
    env.run(agent_post(name=False))
    assert [r[3:] for r in env.rows("agent-runs")] == [["launch", "abc123def456ghi78", "coder", "opus", "high", "1"],
                                                        ["launch", "abc123def456ghi78", "coder", "opus", "high", "0"]]


def write_transcript(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def assistant(mid, ts, usage, model="claude-sonnet-4-6", effort="high"):
    return {"type": "assistant", "timestamp": ts, "effort": effort,
            "message": {"id": mid, "model": model, "usage": usage, "content": [{"type": "text", "text": MARK}]}}


U1 = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20}
U2 = {"input_tokens": 1, "output_tokens": 50, "cache_read_input_tokens": 200, "cache_creation_input_tokens": 0}


def stop(env, tp, msg=f"done {MARK}\nRESULT: DONE\n", agent_type="coder"):
    d = {**common(AGENT), "hook_event_name": "SubagentStop", "stop_hook_active": False, "agent_id": AGENT,
         "agent_transcript_path": str(tp), "agent_type": agent_type, "last_assistant_message": msg}
    return env.run(dump(d))


def test_subagent_stop_line(env):
    tp = env.claude / "projects/p/s/subagents" / f"agent-{AGENT}.jsonl"
    write_transcript(tp, [
        {"type": "user", "timestamp": "2026-11-24T01:00:00.000Z", "message": {"content": MARK}},
        assistant("m1", "2026-11-24T01:00:01.000Z", U1), assistant("m1", "2026-11-24T01:00:01.500Z", U1),
        assistant("m2", "2026-11-24T01:00:03.250Z", U2),
        assistant("m3", "2026-11-24T01:00:03.300Z", U2, model="<synthetic>", effort="medium"),
    ])
    stop(env, tp)
    rows = env.rows("agent-runs")
    assert len(rows) == 1 and len(rows[0]) == 14
    assert rows[0][1:] == ["sess1234", "a1b2c3d4", "stop", AGENT, "coder", "claude-sonnet-4-6", "high", "12", "105", "500",
                           "20", "3300", "DONE"]


@pytest.mark.parametrize("msg,want", [("x\nRESULT: PASS", "PASS"), ("RESULT: SECRETWORD", "other"), ("no line", "none"),
                                      ("RESULT: FAIL\nlater\n  RESULT: DONE_WITH_CONCERNS (n)", "DONE_WITH_CONCERNS")])
def test_subagent_status(env, msg, want):
    stop(env, env.claude / "projects/none.jsonl", msg=msg)
    assert env.rows("agent-runs")[0][13] == want


def test_subagent_transcript_size_guards(env):
    tp = env.claude / "projects/p/s/subagents" / f"agent-{AGENT}.jsonl"
    tp.parent.mkdir(parents=True)
    big = json.dumps({"type": "assistant", "pad": "x" * (17 * 1024 * 1024), "message": {"id": "mx", "model": "huge",
                                                                                         "usage": U2}})
    tp.write_text(big + "\n" + json.dumps(assistant("m1", "2026-11-24T01:00:01.000Z", U1)) + "\n", encoding="utf-8")
    stop(env, tp)
    huge = env.claude / "projects/p/s/subagents/agent-huge.jsonl"
    huge.write_text(json.dumps(assistant("m1", "2026-11-24T01:00:01.000Z", U1)) + "\n", encoding="utf-8")
    with open(huge, "r+b") as f:
        f.truncate(200 * 1024 * 1024 + 1)
    stop(env, huge)
    rows = env.rows("agent-runs")
    assert rows[0][6:13] == ["claude-sonnet-4-6", "high", "10", "5", "100", "20", "0"]
    assert rows[1][6:13] == ["-", "high", "-", "-", "-", "-", "-"]


def test_subagent_transcript_outside_projects_is_not_read(env, tmp_path):
    tp = tmp_path / "elsewhere" / "agent-x.jsonl"
    write_transcript(tp, [assistant("m1", "2026-11-24T01:00:01.000Z", U1)])
    stop(env, tp, agent_type="")
    r = env.rows("agent-runs")[0]
    assert r[5:13] == ["-", "-", "high", "0", "0", "0", "0", "-"]


def test_nothing_forbidden_is_recorded(env):
    tp = env.claude / "projects/p/s/subagents" / f"agent-{AGENT}.jsonl"
    write_transcript(tp, [assistant("m1", "2026-11-24T01:00:01.000Z", U1)])
    payloads = [post("Bash"), post("Bash", ev="PostToolUseFailure"), agent_post(),
                post("Read", tool_input={"file_path": str(env.out)}),
                dump({**common(), "hook_event_name": "SessionStart", "source": "resume", "session_title": MARK}),
                dump({**common(), "hook_event_name": "PostCompact", "trigger": "auto", "compact_summary": MARK}),
                dump({**common(), "hook_event_name": "InstructionsLoaded", "file_path": str(env.out), "load_reason": "include"})]
    for p in payloads:
        env.run(p)
    stop(env, tp)
    text = "".join(f.read_text(encoding="utf-8") for f in (env.root / "_usage").rglob("*") if f.is_file())
    assert text and MARK not in text and SID not in text and "abcd" + MARK not in text
    assert "/data/" not in text and "/proj/" not in text and str(env.out.parent) not in text


def test_tabs_and_newlines_in_names(env):
    env.run(post("a\tb\nc|d", agent="x\ty\nz"))
    raw = post("Bash").replace(b'"Bash"', b'"Ba\tsh"')
    env.run(raw)
    rows = env.rows("tool-use")
    assert [r[2:4] for r in rows] == [["xtynz", "atbncd"], ["main", "Bash"]]
    assert all(len(r) == 6 for r in rows)


@pytest.mark.parametrize("data", [b"", b"not json", b"\x00\xff" * 100, b'{"hook_event_name":"Nope"}'])
def test_garbage_input_is_silent(env, data):
    env.run(data)


def test_unusable_record_places(env, tmp_path):
    day = time.strftime("%Y-%m-%d")
    base = env.root / "_usage"
    (base / "tool-use").mkdir(parents=True)
    os.mkfifo(base / "tool-use" / f"{day}.tsv")
    (base / "hook-runs").mkdir()
    victim = tmp_path / "victim"
    victim.write_text("keep\n")
    (base / "hook-runs" / f"{day}.tsv").symlink_to(victim)
    (base / "agent-runs").mkdir()
    victim2 = tmp_path / "victim2"
    victim2.write_text("keep\n")
    os.link(victim2, base / "agent-runs" / f"{day}.tsv")
    (base / "session-events").mkdir()
    (base / "session-events" / f"{day}.tsv").mkdir()
    t = time.perf_counter()
    env.run(post("Bash"))
    env.run(agent_post())
    env.run(dump({**common(), "hook_event_name": "SessionEnd", "reason": "other"}))
    stop(env, env.claude / "projects/none.jsonl")
    assert time.perf_counter() - t < 10
    assert victim.read_text() == "keep\n" and victim2.read_text() == "keep\n"


def test_unwritable_and_no_home(env):
    env.root.chmod(0o500)
    try:
        env.run(post("Bash"))
    finally:
        env.root.chmod(0o700)
    assert not (env.root / "_usage").exists()
    env.run(post("Bash"), env={k: v for k, v in env.base_env.items() if k != "HOME"})


def test_parallel_twenty(env):
    with ThreadPoolExecutor(20) as ex:
        list(ex.map(lambda i: env.run(post(f"Tool{i}")), range(20)))
    rows = env.rows("tool-use")
    assert len(rows) == 20 and all(len(r) == 6 for r in rows)
    assert sorted(r[3] for r in rows) == sorted(f"Tool{i}" for i in range(20))
    assert len(env.rows("hook-runs")) == 20
