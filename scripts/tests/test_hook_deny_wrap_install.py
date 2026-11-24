"""Tests for hook_deny_wrap_install.py (intent/2026-11-24-harness-review-six-items.md 개정 1 W9 · 개정 2 W14).

Isolation: the real settings.json is only read; every write goes to a copy in a temp folder passed with --settings, and every
hook run uses a temp HOME.

Run: uv run --no-project --with pytest python -m pytest scripts/tests/test_hook_deny_wrap_install.py -q
REF: knowledge/harness/code-history/scripts__tests__test_hook_deny_wrap_install.py.md
"""
import json
import os
import pathlib
import stat
import subprocess
import sys
import time

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent
TOOL = SCRIPTS / "hook_deny_wrap_install.py"
REAL = SCRIPTS.parent / "settings.json"
sys.path.insert(0, str(SCRIPTS))
import hook_deny_wrap_install as inst

NOT_DENY = ["bash $HOME/.claude/scripts/train-launch-warn.sh", "bash $HOME/.claude/scripts/agent-spawn-log.sh pre",
            "bash $HOME/.claude/scripts/skill-usage-log.sh"]


@pytest.fixture
def copy(tmp_path):
    p = tmp_path / "settings.json"
    p.write_bytes(REAL.read_bytes())
    # WHY: the live settings.json got the W14 wrap in 0e3efaf65d (2026-11-24); these tests start from the W9-only state it had
    # before, so --revert brings the copy back to it (a no-op on a server still at W9).
    assert run(p, "--revert").returncode == 0
    for b in tmp_path.glob("settings.json.pre-*"):
        b.unlink()
    return p


def run(p, *args):
    return subprocess.run([sys.executable, str(TOOL), *args, "--settings", str(p)], capture_output=True, text=True,
                          check=False, timeout=30)


def cmds(p, ev=None):
    d = json.loads(p.read_text(encoding="utf-8"))
    return [h.get("command") for e, entries in d["hooks"].items() if ev in (None, e) for x in entries
            for h in x["hooks"] if h.get("type") == "command"]


def usage_events(p):
    d = json.loads(p.read_text(encoding="utf-8"))
    return sorted(e for e, entries in d["hooks"].items() for x in entries for h in x["hooks"]
                  if h.get("command") == inst.USAGE_CMD)


def to_do(p):
    plain = [c for c in cmds(p) if inst.unwrap(c) is None and "hook-deny-wrap" not in c and inst.USAGE_SCRIPT not in c]
    return len(plain) + len(set(inst.USAGE_EVENTS) - set(usage_events(p)))


def home_with_wrapper(tmp_path, state="present"):
    home = tmp_path / "home"
    (home / ".claude/scripts").mkdir(parents=True)
    make_wrapper(home / ".claude/scripts/hook-deny-wrap.sh", state, tmp_path)
    return home


def test_every_target_is_registered_once():
    pre =[inst.unwrap(c) or c for c in cmds(REAL, "PreToolUse")]
    for name, key in inst.TARGETS:
        assert sum(key in c for c in pre) == 1, name
    assert len([c for c in pre if c not in NOT_DENY]) == len(inst.TARGETS)


def test_dry_run_writes_nothing(copy):
    before =copy.read_bytes()
    for args in ((), ("--dry-run",)):
        r = run(copy, *args)
        assert r.returncode == 0 and f"바뀔 항목 {to_do(copy)}개" in r.stdout
    assert copy.read_bytes() == before
    assert sorted(x.name for x in copy.parent.iterdir()) == ["settings.json"]


def test_apply_revert_round_trip(copy):
    orig = copy.read_bytes()
    orig_cmds = cmds(copy)
    r = run(copy, "--apply")
    assert r.returncode == 0, r.stderr
    backups = list(copy.parent.glob("settings.json.pre-hook-deny-wrap.*"))
    assert len(backups) == 1 and backups[0].read_bytes() == orig
    new = copy.read_bytes()
    now = [c for c in cmds(copy) if c != inst.USAGE_CMD]
    assert all(c.startswith(inst.WRAP) for c in now)
    assert [inst.unwrap(c) for c in now] == [inst.unwrap(c) or c for c in orig_cmds]
    assert sorted(inst.unwrap(c) for c in now if not inst.log_only(c)) == sorted(
        inst.unwrap(c) for c in orig_cmds if inst.unwrap(c))
    assert usage_events(copy) == sorted(inst.USAGE_EVENTS)
    assert run(copy, "--apply").stdout.startswith(f"[apply] {copy} — 바뀔 항목 0개")
    assert copy.read_bytes() == new
    mode = os.stat(copy).st_mode
    r = run(copy, "--revert")
    assert r.returncode == 0 and copy.read_bytes() == orig
    assert os.stat(copy).st_mode == mode and stat.S_IMODE(os.stat(backups[0]).st_mode) == 0o600


def test_full_cycle_from_before_w9(copy):
    run(copy, "--revert")
    w9 = copy.read_bytes()
    run(copy, "--revert-all")
    pre = copy.read_bytes()
    assert not any("hook-deny-wrap" in c for c in cmds(copy)) and usage_events(copy) == []
    run(copy, "--apply")
    full = copy.read_bytes()
    assert all(c.startswith(inst.WRAP) for c in cmds(copy) if c != inst.USAGE_CMD)
    run(copy, "--revert")
    assert copy.read_bytes() == w9
    run(copy, "--apply")
    assert copy.read_bytes() == full
    run(copy, "--revert-all")
    assert copy.read_bytes() == pre


def test_events_subset(copy):
    orig = copy.read_bytes()
    r = run(copy, "--apply", "--events", "PostToolUse,SessionStart")
    assert r.returncode == 0 and usage_events(copy) == ["PostToolUse", "SessionStart"]
    wrapped = [c for c in cmds(copy) if inst.log_only(c)]
    assert wrapped and to_do(copy) == 6
    r = run(copy, "--revert", "--events", "PostToolUse")
    assert "(명령 0 · 기록 훅 항목 1)" in r.stdout and usage_events(copy) == ["SessionStart"]
    assert [c for c in cmds(copy) if inst.log_only(c)] == wrapped
    r = run(copy, "--apply")
    assert "(명령 0 · 기록 훅 항목 7)" in r.stdout and usage_events(copy) == sorted(inst.USAGE_EVENTS)
    run(copy, "--revert", "--events", "PreCompact,PostCompact")
    assert [c for c in cmds(copy) if inst.log_only(c)] == wrapped
    run(copy, "--revert")
    assert copy.read_bytes() == orig
    assert run(copy, "--apply", "--events", "PostToolUse,Bogus").returncode == 2


def test_leading_events_of_only_ours_are_removed(tmp_path):
    u = {"type": "command", "command": inst.USAGE_CMD, "timeout": inst.USAGE_TIMEOUT}
    other = {"hooks": [{"type": "command", "command": "bash $HOME/.claude/scripts/o.sh"}]}
    d = {"hooks": {"PostToolUse": [{"hooks": [u]}], "SessionEnd": [{"hooks": [u]}], "Stop": [other],
                   "PreCompact": [{"hooks": [u]}], "PostCompact": [{"hooks": [u]}]}}
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    r = run(p, "--revert", "--events", "PostToolUse,SessionEnd,PreCompact,PostCompact")
    assert r.returncode == 0, r.stderr
    assert json.loads(p.read_text(encoding="utf-8")) == {"hooks": {"Stop": [other]}}
    p.write_text(json.dumps({"hooks": {"PostToolUse": [{"hooks": [u]}]}}, indent=2), encoding="utf-8")
    before = p.read_bytes()
    r = run(p, "--revert")
    assert r.returncode == 0 and "모든 이벤트가 우리 항목뿐" in r.stdout and p.read_bytes() == before


def test_symlinked_settings_stays_a_link(copy, tmp_path):
    orig = copy.read_bytes()
    link = tmp_path / "linkdir" / "settings.json"
    link.parent.mkdir()
    link.symlink_to(copy)
    assert run(link, "--apply").returncode == 0
    assert link.is_symlink() and copy.read_bytes() != orig and usage_events(copy) == sorted(inst.USAGE_EVENTS)
    assert run(link, "--revert").returncode == 0
    assert link.is_symlink() and copy.read_bytes() == orig
    assert sorted(x.name for x in link.parent.iterdir()) == ["settings.json"]
    broken = tmp_path / "broken.json"
    broken.symlink_to(tmp_path / "nowhere.json")
    r = run(broken, "--apply")
    assert r.returncode == 1 and "풀 수 없는 링크" in r.stderr and broken.is_symlink()


def test_change_after_read_aborts(copy, monkeypatch, capsys):
    orig = copy.read_bytes()
    real_edit = inst.edit_text

    def edit_then_touch(*args):
        out = real_edit(*args)
        copy.write_bytes(orig + b" ")
        return out

    monkeypatch.setattr(inst, "edit_text", edit_then_touch)
    monkeypatch.setattr(sys, "argv", ["x", "--apply", "--settings", str(copy)])
    assert inst.main() == 1
    assert "다시 실행" in capsys.readouterr().err
    assert copy.read_bytes() == orig + b" "
    assert sorted(x.name for x in copy.parent.iterdir()) == ["settings.json"]


def test_revert_without_backup(copy):
    orig =copy.read_bytes()
    run(copy, "--apply")
    for b in copy.parent.glob("settings.json.pre-*"):
        b.unlink()
    run(copy, "--revert")
    assert copy.read_bytes() == orig


SYNTH = """{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {"type": "command", "command": "bash $HOME/.claude/scripts/dup.sh"},
          {"type": "command", "command": "echo \\u00e9t\\u00e9 || true"}
        ]
      }
    ],
    "SubagentStop": [{"hooks": [{"type": "command", "command": "bash $HOME/.claude/scripts/dup.sh"}]}],
    "PreToolUse": [{"matcher": "Bash", "hooks": [
      {"type": "command", "command": "bash x.sh $1"}, {"type": "command", "command": "echo $PPID"},
      {"type": "prompt", "prompt": "p"}]}]
  },
  "other": "keep  "
}
"""


def test_text_edits_keep_other_bytes(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(SYNTH, encoding="utf-8")
    r = run(p, "--apply")
    assert r.returncode == 0, r.stderr
    assert "위치 인자 · $PPID" in r.stdout and "command 훅 아님" in r.stdout
    got = cmds(p)
    assert sum(c.startswith(inst.WRAP + inst.LOG + "dup") for c in got) == 2
    assert "bash x.sh $1" in got and "echo $PPID" in got
    assert "\\u00e9" in p.read_text(encoding="utf-8")
    assert usage_events(p) == sorted(inst.USAGE_EVENTS)
    run(p, "--revert")
    assert p.read_text(encoding="utf-8") == SYNTH


def test_usage_entry_first_or_mixed(tmp_path):
    u = {"type": "command", "command": inst.USAGE_CMD, "timeout": inst.USAGE_TIMEOUT}
    other = {"type": "command", "command": "bash $HOME/.claude/scripts/o.sh"}
    d = {"hooks": {"PostToolUse": [{"hooks": [u]}, {"hooks": [other]}], "SessionEnd": [{"hooks": [u, other]}]}}
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    r = run(p, "--revert", "--events", "PostToolUse,SessionEnd")
    assert r.returncode == 0 and "손으로 확인): SessionEnd" in r.stdout
    after = json.loads(p.read_text(encoding="utf-8"))
    assert after["hooks"]["PostToolUse"] == [{"hooks": [other]}] and after["hooks"]["SessionEnd"] == d["hooks"]["SessionEnd"]


@pytest.mark.parametrize("path,blocked", [("/x/.env", True), ("/x/a.py", False), ("/x/it's.pem", True),
                                          ("/x/a\\b.key", True)])
def test_inline_hook_quoting(tmp_path, path, blocked):
    orig =next(inst.unwrap(c) or c for c in cmds(REAL, "PreToolUse") if "민감 파일 보호" in c)
    w = inst.wrap("sensitive-file", orig)
    assert inst.MID + "sh -c '" in w and inst.unwrap(w) == orig
    home = home_with_wrapper(tmp_path)
    data = json.dumps({"session_id": "s1234567", "tool_name": "Write", "tool_input": {"file_path": path}})
    env = {**os.environ, "HOME": str(home)}
    a = subprocess.run(["sh", "-c", orig], input=data, capture_output=True, text=True, env=env, check=False)
    b = subprocess.run(["sh", "-c", w], input=data, capture_output=True, text=True, env=env, check=False)
    assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr)
    assert ('"decision": "block"' in a.stdout) is blocked
    assert (home / ".claude/_audit/hook-deny.tsv").exists() is blocked


def test_simple_form_and_sh_form():
    for c in("bash ~/.claude/scripts/scope-gate.sh", "$HOME/.claude/scripts/read-once.sh",
              "FOO=1 python3 x.py", "a; b", "sh -c 'x'", "sh -c x"):
        for log in (False, True):
            w = inst.wrap("n", c, log)
            assert inst.unwrap(w) == c and inst.log_only(w) is log
            assert (w == f"{inst.WRAP}{inst.LOG if log else ''}n{inst.MID}{c}") is bool(inst.SIMPLE.fullmatch(c))
    assert inst.unwrap("python3 x.py") is None
    c = "bash $HOME/.claude/scripts/g.sh || true"
    assert inst.wrap("g", c, True).endswith(inst.MID + c) and inst.unwrap(inst.wrap("g", c, True)) == c
    assert inst.wrap("g", c).endswith("sh -c " + "'" + c + "'")


def test_real_log_wrapped_commands_behave_the_same(copy, tmp_path):
    changes, _ = inst.plan(json.loads(copy.read_text(encoding="utf-8")), "apply")
    logs = [(before, after) for _, _, before, after in changes if inst.log_only(after)]
    assert logs
    home = home_with_wrapper(tmp_path)
    for name in {m.group(1) for b, _ in logs for m in inst.SCRIPT_NAME.finditer(b)}:
        for ext in ("sh", "py"):
            stub = home / ".claude/scripts" / f"{name}.{ext}"
            stub.write_text('#!/usr/bin/env bash\ncat >/dev/null; echo "out $0 $*"; echo "err $PWD" >&2; exit 3\n')
            stub.chmod(0o755)
    env = {**os.environ, "HOME": str(home)}
    data = json.dumps({"session_id": "s1234567", "hook_event_name": "Stop", "tool_name": "Bash"})
    for before, after in logs:
        a = subprocess.run(["sh", "-c", before], input=data, capture_output=True, text=True, env=env, check=False,
                           cwd=tmp_path, timeout=30)
        b = subprocess.run(["sh", "-c", after], input=data, capture_output=True, text=True, env=env, check=False,
                           cwd=tmp_path, timeout=30)
        assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr), before
    runs = (home / ".claude/_usage/hook-runs").glob("*.tsv")
    rows = [ln.split("\t") for f in runs for ln in f.read_text().splitlines()]
    assert len(rows) == len(logs)
    # WHY: the stubs exit 3, so «x || true» forms record the real 3 while the hook result stays 0 (graphify-autoindex, 2026-11-24).
    assert any(r[4] == "graphify-autoindex" and r[6:8] == ["3", "error"] for r in rows)


def test_installed_pass_overhead(tmp_path):
    hook =tmp_path / "pass.sh"
    hook.write_text("#!/usr/bin/env bash\ncat >/dev/null\n")
    home = home_with_wrapper(tmp_path)
    env = {**os.environ, "HOME": str(home)}
    data = json.dumps({"session_id": "s1234567", "tool_name": "Bash", "tool_input": {"command": "x"}})

    def bench(c):
        t = time.perf_counter()
        for _ in range(100):
            subprocess.run(["sh", "-c", c], input=data, capture_output=True, text=True, env=env, check=False)
        return (time.perf_counter() - t) * 10

    raw, wrapped, logged = bench(f"bash {hook}"), bench(inst.wrap("t", f"bash {hook}")), bench(inst.wrap("t", f"bash {hook}", True))
    print(f"\n[installed overhead] raw {raw:.2f} ms · deny form {wrapped:.2f} ms · log form {logged:.2f} ms")
    assert wrapped - raw < 200 and logged - raw < 200


FAKE_HOOKS = {
    "pass": "cat >/dev/null; exit 0",
    "exit2": "cat >/dev/null; printf 'blocked\\n' >&2; exit 2",
    "json_deny": "cat >/dev/null; printf '%s\\n' '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\","
                 "\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"no\"}}'",
    "hash": "sha256sum; exit 2",
}
WRAPPER_TEXT = (SCRIPTS / "hook-deny-wrap.sh").read_text(encoding="utf-8")
STATES = ["present", "missing", "empty", "shebang_only", "truncated_last_line", "truncated_before_main",
          "truncated_half", "syntax_error", "unreadable", "directory", "broken_link"]


def make_wrapper(w, state, tmp_path):
    lines =WRAPPER_TEXT.splitlines(keepends=True)
    if state == "present":
        w.symlink_to(SCRIPTS / "hook-deny-wrap.sh")
    elif state == "empty":
        w.write_text("")
    elif state == "shebang_only":
        w.write_text("#!/usr/bin/env bash\n")
    elif state == "truncated_last_line":
        assert lines[-1].startswith('main "$@"; exit')
        w.write_text("".join(lines[:-1]))
    elif state == "truncated_before_main":
        w.write_text("".join(lines[:next(i for i, ln in enumerate(lines) if ln.startswith("main() {"))]))
    elif state == "truncated_half":
        w.write_text(WRAPPER_TEXT[:len(WRAPPER_TEXT) // 2])
    elif state == "syntax_error":
        w.write_text("".join(lines[:-1]) + "if then fi\n" + lines[-1])
    elif state == "unreadable":
        w.write_text(WRAPPER_TEXT)
        w.chmod(0)
    elif state == "directory":
        w.mkdir()
    elif state == "broken_link":
        w.symlink_to(tmp_path / "nowhere.sh")


def test_ping_does_not_read_stdin():
    r =subprocess.run(["sh", "-c", f"bash {SCRIPTS / 'hook-deny-wrap.sh'} --ping; cat"], input="abc",
                       capture_output=True, text=True, check=False)
    assert (r.returncode, r.stdout, r.stderr) == (0, "hook-deny-wrap ok\nabc", "")


@pytest.mark.parametrize("log", [False, True])
@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("fake", sorted(FAKE_HOOKS))
def test_installed_command_falls_back_without_wrapper(tmp_path, state, fake, log):
    hook =tmp_path / f"{fake}.sh"
    hook.write_text("#!/usr/bin/env bash\necho ran >> " + str(tmp_path / "runs") + "\n" + FAKE_HOOKS[fake] + "\n")
    home = home_with_wrapper(tmp_path, state)
    orig = f"bash {hook}"
    cmd = inst.wrap("t", orig, log)
    env = {**os.environ, "HOME": str(home)}
    data = json.dumps({"session_id": "s1234567", "tool_name": "Bash", "tool_input": {"command": "x"}})
    a = subprocess.run(["sh", "-c", orig], input=data, capture_output=True, text=True, env=env, check=False)
    b = subprocess.run(["sh", "-c", cmd], input=data, capture_output=True, text=True, env=env, check=False)
    assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr)
    assert (tmp_path / "runs").read_text() == "ran\nran\n"
    assert (home / ".claude/_audit/hook-deny.tsv").exists() is (state == "present" and fake != "pass" and not log)
    assert (home / ".claude/_usage/hook-runs").exists() is (state == "present")


def test_unwrap_knows_second_round_form(copy):
    lit =next(c for c in cmds(copy, "PreToolUse") if "scope-gate.sh" in c)
    orig = inst.unwrap(lit) or lit
    v2 = inst.WRAP_V2 + "scope-gate" + inst.MID + orig
    assert inst.unwrap(v2) == orig
    inline = next(inst.unwrap(c) or c for c in cmds(copy, "PreToolUse") if "민감 파일 보호" in c)
    v2i = inst.WRAP_V2 + "sensitive-file" + inst.wrap("sensitive-file", inline)[len(inst.WRAP) + len("sensitive-file"):]
    assert inst.unwrap(v2i) == inline
    raw = copy.read_text(encoding="utf-8").replace(json.dumps(lit), json.dumps(v2))
    copy.write_text(raw, encoding="utf-8")
    r = run(copy, "--apply")
    assert "이미 감쌈" in r.stdout and v2 in cmds(copy)
    run(copy, "--revert")
    assert copy.read_text(encoding="utf-8") == raw
    run(copy, "--revert-all")
    assert orig in cmds(copy)


def test_unknown_wrapped_form_is_skipped(copy):
    lit =next(c for c in cmds(copy, "PreToolUse") if "scope-gate.sh" in c)
    v1 = f"bash $HOME/.claude/scripts/hook-deny-wrap.sh scope-gate -- {inst.unwrap(lit) or lit}"
    raw = copy.read_text(encoding="utf-8").replace(json.dumps(lit), json.dumps(v1))
    copy.write_text(raw, encoding="utf-8")
    for mode in ("--dry-run", "--apply", "--revert", "--revert-all"):
        r = run(copy, mode)
        assert "알아보는 꼴이 아님" in r.stdout and v1 in r.stdout
        assert v1 in cmds(copy)
    run(copy, "--apply")
    run(copy, "--revert")
    assert v1 in cmds(copy)
