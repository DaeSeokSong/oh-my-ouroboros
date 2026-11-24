"""Tests for scripts/skill-usage-log.sh (intent/2026-11-24-harness-review-six-items.md W10 성공 기준 1).

Isolation: every run uses a temp HOME; the hook has no test-only switch.
Run: uv run --no-project --with pytest python -m pytest scripts/tests/test_skill_usage_log.py -q
"""
import json
import os
import pathlib
import shutil
import subprocess

import pytest

HOOK = pathlib.Path(__file__).resolve().parent.parent / "skill-usage-log.sh"
BASH = shutil.which("bash")
HEADER = "time\tsession\tskill\tcaller"


@pytest.fixture
def home(tmp_path):
    return tmp_path


def log_path(home):
    return home / ".claude" / "_usage" / "skill-usage.tsv"


def payload(skill="commit", tool="Skill", sid="abcdef1234567890", **extra):
    p = {"session_id": sid, "tool_name": tool, "tool_input": {"skill": skill, "args": "SECRET-ARG-123"}, **extra}
    return json.dumps(p, ensure_ascii=False)


def run(home, stdin, env=None):
    return subprocess.run([BASH, str(HOOK)], input=stdin, text=True, capture_output=True, check=False, timeout=30,
                          env={**os.environ, "HOME": str(home), **(env or {})})


def rows(home):
    return [ln.split("\t") for ln in log_path(home).read_text(encoding="utf-8").splitlines()]


def test_skill_call_is_logged_without_args(home):
    r = run(home, payload())
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    lines = rows(home)
    assert lines[0] == HEADER.split("\t")
    assert len(lines) == 2 and lines[1][1:] == ["abcdef12", "commit", "main"]
    assert "SECRET-ARG-123" not in log_path(home).read_text()
    assert oct(log_path(home).stat().st_mode & 0o777) == "0o600"


def test_header_written_only_once(home):
    run(home, payload("a"))
    run(home, payload("b"))
    assert [ln[2] for ln in rows(home)] == ["skill", "a", "b"]


def test_other_tools_not_logged(home):
    run(home, payload(tool="Agent"))
    run(home, payload(tool="Bash"))
    assert not log_path(home).exists()


def test_name_with_disallowed_chars_dropped_and_plugin_form_kept(home):
    run(home, payload("plugin:my-skill_v1.2"))
    for bad in ("a b/../c;rm\tx\ny", "한글ok", "ok\n", "ok\t", "$(;/ /)", "a/b"):
        run(home, payload(bad))
    run(home, payload("k" * 100))
    names = [ln[2] for ln in rows(home)[1:]]
    assert names == ["plugin:my-skill_v1.2", "k" * 80]


def test_caller_from_agent_type(home):
    run(home, payload("s1", agent_type="coder"))
    run(home, payload("s2", agent_type="we ird/type"))
    assert [ln[3] for ln in rows(home)[1:]] == ["coder", "weirdtype"]


def test_size_cap_keeps_second_half(home):
    p = log_path(home)
    p.parent.mkdir(parents=True)
    body = "".join(f"2026-01-01T00:00:00+00:00\tsess0000\told{i % 10}\tmain\n" for i in range(50000))
    p.write_text(HEADER + "\n" + body)
    assert p.stat().st_size > 2 * 1024 * 1024
    run(home, payload("newest"))
    assert p.stat().st_size < 1.2 * 1024 * 1024
    lines = rows(home)
    assert lines[0] == HEADER.split("\t") and lines[-1][2] == "newest"
    assert all(len(ln) == 4 for ln in lines)
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert not list(p.parent.glob(".skill-usage.*"))


def test_failed_trim_keeps_original(home, tmp_path):
    p = log_path(home)
    p.parent.mkdir(parents=True)
    body = "".join(f"2026-01-01T00:00:00+00:00\tsess0000\told{i % 10}\tmain\n" for i in range(50000))
    p.write_text(HEADER + "\n" + body)
    before = p.stat().st_size
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "tail").write_text("#!/bin/sh\nexit 1\n")
    (fake / "tail").chmod(0o755)
    r = run(home, payload("newest"), env={"PATH": f"{fake}:{os.environ['PATH']}"})
    assert r.returncode == 0
    lines = p.read_text().splitlines()
    assert len(lines) == 50002 and lines[0] == HEADER and lines[-1].split("\t")[2] == "newest"
    assert p.stat().st_size > before
    assert not list(p.parent.glob(".skill-usage.*"))


def test_no_jq_does_nothing(home, tmp_path):
    empty = tmp_path / "emptybin"
    empty.mkdir()
    r = run(home, payload(), env={"PATH": str(empty)})
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    assert not log_path(home).exists()


@pytest.mark.parametrize("stdin", ["not json", "", "{", '{"tool_name": "Skill"}', '{"tool_name":"Skill","tool_input":{"skill":5}}'])
def test_garbage_stdin_is_silent(home, stdin):
    r = run(home, stdin)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    assert not log_path(home).exists()


def test_symlinked_log_file_not_written(home, tmp_path):
    target = tmp_path / "victim.txt"
    target.write_text("keep\n")
    log_path(home).parent.mkdir(parents=True)
    log_path(home).symlink_to(target)
    r = run(home, payload())
    assert r.returncode == 0 and target.read_text() == "keep\n"


def test_symlinked_dir_not_written(home, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "_usage").symlink_to(other)
    r = run(home, payload())
    assert r.returncode == 0 and not list(other.iterdir())


def test_symlinked_lock_file_not_followed(home, tmp_path):
    target = tmp_path / "victim.txt"
    target.write_text("keep\n")
    log_path(home).parent.mkdir(parents=True)
    (log_path(home).parent / "skill-usage.tsv.lock").symlink_to(target)
    r = run(home, payload())
    assert r.returncode == 0 and target.read_text() == "keep\n" and not log_path(home).exists()


def test_concurrent_calls_keep_every_line(home):
    procs = [subprocess.Popen([BASH, str(HOOK)], stdin=subprocess.PIPE, text=True, stdout=subprocess.DEVNULL,
                              env={**os.environ, "HOME": str(home)}) for _ in range(20)]
    for i, pr in enumerate(procs):
        pr.communicate(payload(f"s{i}"), timeout=30)
    lines = rows(home)
    assert len(lines) == 21 and lines[0] == HEADER.split("\t")
    assert sorted(ln[2] for ln in lines[1:]) == sorted(f"s{i}" for i in range(20))
