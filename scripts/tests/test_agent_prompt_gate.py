"""Tests for agent-prompt-gate.py (spawn prompt 5요소 검사 훅, intent/2026-11-24-harness-review-six-items.md W4).

Isolation: the hook is copied with its config into a temp harness folder (config is read next to the script) and run
with HOME set to a temp folder (the log lives under HOME). No test-only variable exists in the hook, so the real
~/.claude/_audit/agent-prompt-gate.tsv is never touched.

Run: uv run --no-project --with pytest python -m pytest scripts/tests/test_agent_prompt_gate.py -q
REF: knowledge/harness/code-history/scripts__tests__test_agent_prompt_gate.py.md
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

REAL = pathlib.Path(__file__).resolve().parent.parent
FULL_KO = ("[SKILL_DEPTH: 0]\n## 목표(objective)\nx\n## 사용자 지시 원문\n«y»\n## 도구 · 자료(tools/sources)\nRead\n"
           "## 출력 형식(output_format)\n표\n## 경계(task_boundary)\n쓰기 금지\n")
FULL_EN = "objective: a\nuser_request: b\ntools/sources: Read\noutput_format: c\ntask_boundary: d\n"


@pytest.fixture
def env(tmp_path):
    harness = tmp_path / "harness"
    (harness / "scripts").mkdir(parents=True)
    (harness / "config").mkdir()
    shutil.copy(REAL / "agent-prompt-gate.py", harness / "scripts")
    shutil.copy(REAL.parent / "config/agent-prompt-gate.json", harness / "config")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)

    class E:
        cfg = harness / "config/agent-prompt-gate.json"
        tsv = home / ".claude/_audit/agent-prompt-gate.tsv"

        @staticmethod
        def set_mode(mode):
            d = json.loads(E.cfg.read_text(encoding="utf-8"))
            d["mode"] = mode
            E.cfg.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

        @staticmethod
        def run(payload=None, args=(), raw=None):
            text = raw if raw is not None else json.dumps(payload, ensure_ascii=False)
            return subprocess.run([sys.executable, str(harness / "scripts/agent-prompt-gate.py"), *args], input=text,
                                  capture_output=True, text=True, check=False, timeout=30,
                                  env={**os.environ, "HOME": str(home)})

        @staticmethod
        def rows():
            return [ln.split("\t") for ln in E.tsv.read_text(encoding="utf-8").splitlines()] if E.tsv.exists() else []

    return E


def call(sub, prompt, sid="abcdef1234567890", tool="Agent"):
    ti = {"description": "d", "prompt": prompt}
    if sub is not None:
        ti["subagent_type"] = sub
    return {"tool_name": tool, "session_id": sid, "tool_input": ti}


def deny_reason(r):
    assert r.returncode == 0 and len(r.stdout.splitlines()) == 1, r
    spec = json.loads(r.stdout)["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny"
    return spec["permissionDecisionReason"]


def test_observe_logs_missing_but_passes(env):
    r = env.run(call("coder", "목표(objective): 하나만 있음"))
    assert (r.returncode, r.stdout) == (0, "")
    (row,) = env.rows()
    assert row[1:] == ["abcdef12", "coder", "observe", "user_request,tools_sources,output_format,task_boundary", "no", "miss"]


def test_observe_full_korean_markers_ok(env):
    r = env.run(call("coder", FULL_KO))
    assert r.stdout == ""
    assert env.rows()[0][4:] == ["-", "yes", "ok"]


def test_english_keys_ok(env):
    env.set_mode("enforce")
    r = env.run(call("qa", FULL_EN))
    assert (r.returncode, r.stdout) == (0, "")
    assert env.rows()[0][3:] == ["enforce", "-", "no", "ok"]


def test_enforce_denies_with_names_and_canon(env):
    env.set_mode("enforce")
    reason = deny_reason(env.run(call("coder", FULL_EN.replace("user_request: b\n", ""))))
    assert "사용자 지시 원문" in reason and "rules-lazy/agent-routing-mcp.md" in reason
    assert env.rows()[0][4:] == ["user_request", "no", "deny"]


def test_token_boundary(env):
    env.set_mode("enforce")
    prompt = FULL_EN.replace("objective: a", "objectives: a").replace("tools/sources: Read", "my_tools/sources: Read")
    reason = deny_reason(env.run(call("coder", prompt)))
    assert "목표(objective)" in reason and "도구 · 자료(tools/sources)" in reason


@pytest.mark.parametrize("prompt", [
    FULL_KO,
    "objective: a\n사용자 지시 원문: «b»\n- **tools/sources**: Read\n> output_format (형식): 표\n[task_boundary] 쓰기 금지\n",
    ("  ## 목표(objective)\r\nx\r\n## 사용자 지시 원문\r\n## 도구 · 자료(tools/sources)\r\n## 출력 형식(output_format)\r\n"
     "## 경계(task_boundary)\r\n"),
    "1. 목표(objective): a\n2) 사용자 지시 원문: b\n3. 도구 · 자료(tools/sources): c\n4) 출력 형식(output_format): d\n5. 경계(task_boundary): e\n",
    "`objective`: a\n`user_request`: b\n`tools/sources`: c\n`output_format`: d\n`task_boundary`: e\n",
    "　objective: a\n user_request (원문): b\n-　tools/sources: c\noutput_format　(표): d\ntask_boundary: e\n",
])
def test_label_position_passes(env, prompt):
    env.set_mode("enforce")
    assert env.run(call("coder", prompt)).stdout == ""
    assert env.rows()[0][4:6] == ["-", "yes" if "SKILL_DEPTH" in prompt else "no"]


@pytest.mark.parametrize("prompt, missing", [
    ("implement the objective function; tools: use ruff", "objective,user_request,tools_sources,output_format,task_boundary"),
    ("objective user_request tools/sources output_format task_boundary",
     "objective,user_request,tools_sources,output_format,task_boundary"),
    ("objective: a\nsee the user_request: b\ntools: Read\noutput_format: c\ntask_boundary: d\n", "user_request,tools_sources"),
])
def test_label_position_misses(env, prompt, missing):
    env.set_mode("enforce")
    deny_reason(env.run(call("coder", prompt)))
    assert env.rows()[0][4] == missing


def test_bookkeeping_fields_ignored(env):
    d = json.loads(env.cfg.read_text(encoding="utf-8"))
    assert isinstance(d.get("registered"), str) and isinstance(d.get("report_7d_done"), bool)
    for reg, done in ((123, "x"), (None, None)):
        d["registered"], d["report_7d_done"] = reg, done
        env.cfg.write_text(json.dumps(d), encoding="utf-8")
        assert env.run(call("coder", FULL_EN)).stdout == ""
    del d["registered"], d["report_7d_done"]
    env.cfg.write_text(json.dumps(d), encoding="utf-8")
    assert env.run(call("coder", FULL_EN)).stdout == ""
    assert [r[6] for r in env.rows()] == ["ok", "ok", "ok"]


def test_exempt_types_skip_user_request(env):
    env.set_mode("enforce")
    no_user = FULL_EN.replace("user_request: b\n", "")
    for sub in ("scout", "searcher", "citation-verifier"):
        assert env.run(call(sub, no_user)).stdout == ""
    assert [r[6] for r in env.rows()] == ["ok", "ok", "ok"]
    deny_reason(env.run(call("planner", no_user)))


def test_outside_roster_passes(env):
    env.set_mode("enforce")
    for sub in (None, "general-purpose", "codex:codex-rescue", "fork", "claude-security:x"):
        assert env.run(call(sub, "")).stdout == ""
    assert [r[6] for r in env.rows()] == ["skip"] * 5
    assert env.rows()[0][2] == "general-purpose"


def test_other_tool_not_logged(env):
    assert env.run({"tool_name": "Bash", "tool_input": {"command": "ls"}}).stdout == ""
    assert env.rows() == []


@pytest.mark.parametrize("broken", ["missing", "json", "mode", "markers"])
def test_broken_config_passes_even_in_enforce(env, broken):
    if broken == "missing":
        env.cfg.unlink()
    elif broken == "json":
        env.cfg.write_text("{ not json", encoding="utf-8")
    else:
        d = json.loads(env.cfg.read_text(encoding="utf-8"))
        d["mode"] = "enforce"
        if broken == "mode":
            d["mode"] = "block"
        else:
            del d["markers"]["task_boundary"]
        env.cfg.write_text(json.dumps(d), encoding="utf-8")
    r = env.run(call("coder", ""))
    assert (r.returncode, r.stdout) == (0, "")
    assert env.rows()[0][6] == "error"


def test_broken_stdin_passes(env):
    r = env.run(raw="not json")
    assert (r.returncode, r.stdout) == (0, "")
    assert env.rows()[0][6] == "error"


def test_empty_prompt(env):
    env.set_mode("enforce")
    reason = deny_reason(env.run(call("coder", "")))
    assert reason.count(",") == 4
    assert env.rows()[0][4] == "objective,user_request,tools_sources,output_format,task_boundary"


def test_big_prompt_and_no_body_in_tsv(env):
    secret_line = "sk-" + "A" * 40
    prompt = FULL_KO + ("가" * 300_000) + secret_line
    r = env.run(call("coder", prompt))
    assert r.stdout == ""
    text = env.tsv.read_text(encoding="utf-8")
    assert env.rows()[0][6] == "ok" and secret_line not in text and "가가" not in text and len(text) < 300


def test_session_and_type_sanitized(env):
    env.run(call("coder\t/../x", FULL_EN, sid="../../e\tvil"))
    row = env.rows()[0]
    assert len(row) == 7 and row[1] == "....evil"[:8] and "/" not in row[2]


def test_tsv_mode_and_rotation(env):
    env.tsv.parent.mkdir(parents=True)
    old = "2026-01-01T00:00:00+00:00\t-\tqa\tobserve\t-\tno\tok\n"
    env.tsv.write_text(old * 46_000, encoding="utf-8")
    assert env.tsv.stat().st_size > 2 * 1024 * 1024
    env.run(call("coder", FULL_EN))
    size = env.tsv.stat().st_size
    assert size < 1.2 * 1024 * 1024
    rows = env.rows()
    assert all(len(r) == 7 for r in rows) and rows[-1][2] == "coder"


def test_new_tsv_is_private(env):
    env.run(call("coder", FULL_EN))
    assert oct(env.tsv.stat().st_mode & 0o777) == "0o600"


def test_report(env):
    env.tsv.parent.mkdir(parents=True)
    now = datetime.now(UTC)
    old = (now - timedelta(days=10)).isoformat(timespec="seconds")
    new = now.isoformat(timespec="seconds")
    env.tsv.write_text(
        f"{old}\t-\tcoder\tobserve\tobjective\tno\tmiss\n"
        f"{new}\t-\tcoder\tobserve\tuser_request,task_boundary\tno\tmiss\n"
        f"{new}\t-\tcoder\tobserve\t-\tyes\tok\n"
        f"{new}\t-\tgeneral-purpose\tobserve\t-\tno\tskip\n"
        f"{new}\t-\t-\t-\tJSONDecodeError\t-\terror\n"
        f"{new}\t-\tqa|<b>\x1b[31m\tobserve\t-\tno\tok\n"
        "broken line\n", encoding="utf-8")
    r = env.run(args=("--report", "--days", "7"), raw="")
    assert r.returncode == 0
    lines = r.stdout.splitlines()
    coder = next(ln for ln in lines if ln.startswith("| coder |"))
    assert coder == "| coder | 2 | 2 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 0 | 0 |"
    assert "| qab31m | 1 | 1 | 0 |" in r.stdout and "\x1b" not in r.stdout and "<b>" not in r.stdout
    total = next(ln for ln in lines if ln.startswith("| 합계 |"))
    assert total == "| 합계 | 5 | 3 | 1 | 0 | 1 | 0 | 0 | 1 | 2 | 1 | 1 |"
    assert lines[-1].startswith("miss 는 표지 기준이라 실제 누락의 하한이다.") and "_audit/agent-prompts/" in lines[-1]
    r30 = env.run(args=("--report", "--days", "30"), raw="")
    assert "| coder | 3 | 3 | 2 | 1 |" in r30.stdout
    for bad in (("--bogus",), ("--days", "99999999999"), ("--days", "0"), ("--days", "²"), ("--days", "٣")):
        rb = env.run(args=("--report", *bad), raw="")
        assert rb.returncode == 2 and "Traceback" not in rb.stderr, rb.stderr
