"""Tests for hook-deny-wrap.sh (반복 차단 폴백, intent/2026-11-24-harness-review-six-items.md 개정 1 W9).

Isolation: every run uses a temp HOME (the record and counters live under HOME/.claude), so the real
~/.claude/_audit/hook-deny.tsv and _cache/hook-deny/ are never touched. The wrapper has no test-only switch.

Run: uv run --no-project --with pytest python -m pytest scripts/tests/test_hook_deny_wrap.py -q
REF: knowledge/harness/code-history/scripts__tests__test_hook_deny_wrap.py.md
"""
import json
import os
import pathlib
import shutil
import stat
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

WRAP = pathlib.Path(__file__).resolve().parent.parent / "hook-deny-wrap.sh"
LEAK_MARK = "LEAKMARK_9f3a"
MARK = "[반복 차단]"

FAKES = {
    "quiet_pass": "cat >/dev/null; exit 0",
    "stdout_pass": "cat >/dev/null; printf '%s\\n' '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\","
                   "\"additionalContext\":\"word deny and block here\"}}'; exit 0",
    "exit2": "cat >/dev/null; printf 'blocked: 이유 한 줄\\n' >&2; exit 2",
    "exit2_nonl": "cat >/dev/null; printf 'no newline' >&2; exit 2",
    "json_deny": "cat >/dev/null; printf '%s\\n' '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\","
                 "\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"거부 사유\"}}'; exit 0",
    "old_block": "cat >/dev/null; printf '%s' '{\"decision\": \"block\", \"reason\": \"옛 꼴\"}'; exit 0",
    "exit1": "cat >/dev/null; printf 'oops\\n' >&2; exit 1",
    "exit1_json_deny": "cat >/dev/null; printf '%s\\n' '{\"hookSpecificOutput\":{\"permissionDecision\":\"deny\","
                       "\"permissionDecisionReason\":\"r\"}}'; exit 1",
    "exit2_json": "cat >/dev/null; printf '%s\\n' '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\","
                  "\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"둘 다\"}}'; "
                  "printf 'stderr 사유\\n' >&2; exit 2",
    "ask_json": "cat >/dev/null; printf '%s\\n' '{\"hookSpecificOutput\":{\"permissionDecision\":\"ask\","
                "\"permissionDecisionReason\":\"not deny\"}}'; exit 0",
    "big_stdout": "cat >/dev/null; head -c 3000000 /dev/zero | tr '\\0' 'x'; printf 'deny\\n'; exit 0",
    "nul_stdout": "cat >/dev/null; printf 'a\\0b\\0deny\\0'; printf 'e\\0rr' >&2; exit 0",
    "slow": "cat >/dev/null; sleep 1; printf 'late\\n'; exit 0",
    "no_stdin": "printf 'did not read\\n'; exit 0",
    "no_stdin_deny": "printf 'deny without reading\\n' >&2; exit 2",
    "stdin_hash": "sha256sum; wc -c; exit 0",
    "big_stderr": "cat >/dev/null; head -c 1000000 /dev/zero | tr '\\0' 'e' >&2; printf 'end\\n' >&2; exit 2",
    "big_both": "cat >/dev/null; head -c 1000000 /dev/zero | tr '\\0' 'o'; head -c 1000000 /dev/zero | tr '\\0' 'e' >&2; "
                "exit 2",
    "nan_deny": "cat >/dev/null; printf '%s\\n' '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\","
                "\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"r\",\"x\":NaN}}'; exit 0",
    "inf_block": "cat >/dev/null; printf '%s' '{\"decision\":\"block\",\"reason\":\"r\",\"x\":-Infinity}'; exit 0",
}
DENY_FAKES = {"exit2", "exit2_nonl", "json_deny", "old_block", "exit1_json_deny", "exit2_json", "no_stdin_deny"}


@pytest.fixture
def env(tmp_path):
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    for name, body in FAKES.items():
        (fakes / f"{name}.sh").write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    base = {**os.environ, "HOME": str(home)}

    class E:
        tmp = tmp_path
        h = home
        tsv = home / ".claude/_audit/hook-deny.tsv"
        cdir = home / ".claude/_cache/hook-deny"
        base_env = base

        @staticmethod
        def payload(sid="sess1234abcd", agent=None, tool="Bash", extra=""):
            # REF: common fields (session_id · agent_id · agent_type) precede hook_event_name in Claude Code 2.1.323 (binary
            # strings, 2026-11-24).
            d = {"session_id": sid, **({"agent_id": agent, "agent_type": "coder"} if agent else {}),
                 "hook_event_name": "PreToolUse", "tool_name": tool,
                 "tool_input": {"command": f"echo {LEAK_MARK} {extra}"}, "tool_use_id": "toolu_1"}
            return json.dumps(d, ensure_ascii=False).encode()

        @staticmethod
        def raw(fake, data, env=None, cmd=None):
            argv = cmd or ["bash", str(fakes / f"{fake}.sh")]
            return subprocess.run(argv, input=data, capture_output=True, env=env or E.base_env, timeout=60, check=False)

        @staticmethod
        def wrapped(fake, data, hook="testhook", env=None, cmd=None):
            argv = cmd or ["bash", str(fakes / f"{fake}.sh")]
            return subprocess.run(["bash", str(WRAP), hook, "--", *argv], input=data, capture_output=True,
                                  env=env or E.base_env, timeout=60, check=False)

        @staticmethod
        def rows():
            return [ln.split("\t") for ln in E.tsv.read_text(encoding="utf-8").splitlines()] if E.tsv.exists() else []

    return E


def same(a, b):
    assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr)


@pytest.mark.parametrize("fake", sorted(set(FAKES) - {"nul_stdout"}))
def test_first_call_is_byte_identical(env, fake):
    data = env.payload()
    same(env.wrapped(fake, data), env.raw(fake, data))


def test_nul_bytes_are_dropped_only(env):
    data = env.payload()
    r, b = env.wrapped("nul_stdout", data), env.raw("nul_stdout", data)
    assert r.returncode == b.returncode == 0
    assert r.stdout == b.stdout.replace(b"\0", b"") and r.stderr == b.stderr.replace(b"\0", b"")
    assert not env.rows()


def test_missing_command_keeps_shell_result(env):
    r = env.wrapped(None, env.payload(), cmd=["/nonexistent/hook"])
    assert r.returncode == 127 and r.stdout == b""
    assert not env.rows()


@pytest.mark.parametrize("fake", sorted(DENY_FAKES))
def test_deny_streak_and_record(env, fake):
    data = env.payload()
    base = env.raw(fake, data)
    outs = [env.wrapped(fake, data) for _ in range(4)]
    for r in outs[:2]:
        same(r, base)
    for n, r in ((3, outs[2]), (4, outs[3])):
        assert r.returncode == base.returncode
        tail = f"연속 {n}회".encode()
        if fake in {"json_deny", "old_block", "exit1_json_deny", "exit2_json"}:
            o, b = json.loads(r.stdout), json.loads(base.stdout)
            key = ("hookSpecificOutput", "permissionDecisionReason") if "hookSpecificOutput" in b else ("reason",)
            got, want = o, b
            for k in key[:-1]:
                got, want = got[k], want[k]
            assert got[key[-1]].startswith(want[key[-1]] + "\n" + MARK) and tail.decode() in got[key[-1]]
            got.pop(key[-1])
            want.pop(key[-1])
            assert o == b
        else:
            assert r.stdout == base.stdout
        if base.returncode == 2:
            assert r.stderr.startswith(base.stderr) and MARK.encode() in r.stderr and tail in r.stderr
            assert r.stderr.endswith(b"\n")
        else:
            assert r.stderr == base.stderr
    rows = env.rows()
    assert rows[0] == ["time", "session", "caller", "hook", "tool", "streak"]
    assert [r[1:] for r in rows[1:]] == [["sess1234", "main", "testhook", "Bash", str(i)] for i in (1, 2, 3, 4)]
    assert all(len(r) == 6 for r in rows)
    assert LEAK_MARK not in env.tsv.read_text(encoding="utf-8")
    assert all(LEAK_MARK not in p.read_text() for p in env.cdir.iterdir())
    assert stat.S_IMODE(env.tsv.stat().st_mode) == 0o600


def test_exit2_without_trailing_newline_gets_one(env):
    data = env.payload()
    for _ in range(2):
        env.wrapped("exit2_nonl", data)
    r = env.wrapped("exit2_nonl", data)
    assert r.stderr.startswith(b"no newline\n" + MARK.encode())


def test_pass_resets_streak(env):
    data = env.payload()
    for _ in range(2):
        env.wrapped("exit2", data)
    same(env.wrapped("quiet_pass", data), env.raw("quiet_pass", data))
    assert not list(env.cdir.glob("sess1234.*"))
    r = env.wrapped("exit2", data)
    assert MARK.encode() not in r.stderr
    r = env.wrapped("exit2", data)
    assert MARK.encode() not in r.stderr
    assert MARK.encode() in env.wrapped("exit2", data).stderr
    assert [r[5] for r in env.rows()[1:]] == ["1", "2", "1", "2", "3"]


def test_non_deny_json_and_exit1_are_passes(env):
    data = env.payload()
    for _ in range(2):
        env.wrapped("exit2", data)
    for fake in ("ask_json", "exit1", "stdout_pass"):
        same(env.wrapped(fake, data), env.raw(fake, data))
    assert len(env.rows()) == 3
    assert not list(env.cdir.glob("sess1234.*"))


def test_counts_are_separate(env):
    a = env.payload()
    for _ in range(2):
        env.wrapped("exit2", a, hook="h1")
    env.wrapped("exit2", a, hook="h2")
    env.wrapped("exit2", env.payload(sid="othersess999"), hook="h1")
    sub = env.payload(agent="agentXYZ123456")
    env.wrapped("exit2", sub, hook="h1")
    env.wrapped("exit2", sub, hook="h1")
    assert MARK.encode() not in env.wrapped("exit2", env.payload(sid="othersess999"), hook="h1").stderr
    assert MARK.encode() in env.wrapped("exit2", a, hook="h1").stderr
    assert MARK.encode() in env.wrapped("exit2", sub, hook="h1").stderr
    names = sorted(p.name for p in env.cdir.iterdir() if not p.name.startswith("."))
    assert names == ["otherses.main.h1", "sess1234.agentXYZ.h1", "sess1234.main.h1", "sess1234.main.h2"]
    env.wrapped("quiet_pass", sub, hook="h1")
    assert not (env.cdir / "sess1234.agentXYZ.h1").exists() and (env.cdir / "sess1234.main.h1").exists()


def no_jq_path(tmp):
    b = tmp / "nojq-bin"
    b.mkdir()
    for t in ("bash", "sh", "cat", "mktemp", "rm", "flock", "stat", "tail", "find", "mv", "chmod", "mkdir", "head",
              "tr", "sleep", "sha256sum", "wc", "printf"):
        p = shutil.which(t)
        if p:
            (b / t).symlink_to(p)
    return str(b)


@pytest.mark.parametrize("fake", ["quiet_pass", "exit2", "json_deny", "old_block", "exit2_json", "big_stdout"])
def test_no_jq(env, fake):
    e = {**env.base_env, "PATH": no_jq_path(env.tmp)}
    data = env.payload()
    for _ in range(3):
        r, b = env.wrapped(fake, data, env=e), env.raw(fake, data, env=e)
        assert r.returncode == b.returncode and r.stdout == b.stdout
        assert r.stderr == b.stderr or (fake.startswith("exit2") and r.stderr.startswith(b.stderr))
    if fake.startswith("exit2"):
        assert [x[1:] for x in env.rows()[1:]] == [["sess1234", "main", "testhook", "Bash", str(i)] for i in (1, 2, 3)]


@pytest.mark.parametrize("fake", ["exit2", "json_deny", "quiet_pass", "stdin_hash"])
def test_unwritable_audit_dir(env, fake):
    env.h.joinpath(".claude").chmod(0o500)
    try:
        data = env.payload()
        for _ in range(4):
            same(env.wrapped(fake, data), env.raw(fake, data))
    finally:
        env.h.joinpath(".claude").chmod(0o700)
    assert not env.tsv.exists()


@pytest.mark.parametrize("fake", ["exit2", "json_deny", "quiet_pass", "stdin_hash"])
def test_no_home(env, fake):
    e = {k: v for k, v in env.base_env.items() if k != "HOME"}
    data = env.payload()
    for _ in range(4):
        same(env.wrapped(fake, data, env=e), env.raw(fake, data, env=e))


@pytest.mark.parametrize("tmpdir", ["readonly", "missing", "devfull"])
@pytest.mark.parametrize("fake", ["exit2", "json_deny", "stdin_hash", "no_stdin", "big_stdout"])
def test_unusable_tmpdir_keeps_verdict(env, fake, tmpdir):
    ro = env.tmp / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    path = {"readonly": str(ro), "missing": str(env.tmp / "nope/deeper"), "devfull": "/dev/full"}[tmpdir]
    e = {**env.base_env, "TMPDIR": path}
    data = env.payload(extra="x" * 100000)
    try:
        outs = [(env.wrapped(fake, data, env=e), env.raw(fake, data, env=e)) for _ in range(3)]
    finally:
        ro.chmod(0o700)
    for w, r in outs[:2]:
        same(w, r)
    w, r = outs[2]
    assert w.returncode == r.returncode
    if fake in DENY_FAKES:
        assert MARK.encode() in (w.stderr + w.stdout)
        assert len(env.rows()) == 4
    else:
        same(w, r)
        assert not env.tsv.exists()


def test_tmpdir_deleted_during_hook(env):
    tdir = env.tmp / "vanishing"
    hook = env.tmp / "rm_tmpdir_deny.sh"
    hook.write_text(f"#!/usr/bin/env bash\ncat >/dev/null; rm -rf -- '{tdir}'; printf 'gone\\n' >&2; exit 2\n")
    data = env.payload()
    outs = []
    for _ in range(2):
        tdir.mkdir(exist_ok=True)
        e = {**env.base_env, "TMPDIR": str(tdir)}
        w = env.wrapped(None, data, env=e, cmd=["bash", str(hook)])
        tdir.mkdir(exist_ok=True)
        r = env.raw(None, data, env=e, cmd=["bash", str(hook)])
        outs.append((w, r))
    for w, r in outs:
        same(w, r)
        assert w.returncode == 2 and w.stderr == b"gone\n"


@pytest.mark.parametrize("fake", ["big_stderr", "big_stdout", "big_both"])
def test_large_output_is_linear(env, fake):
    data = env.payload()
    t = time.perf_counter()
    w = env.wrapped(fake, data)
    elapsed = time.perf_counter() - t
    same(w, env.raw(fake, data))
    assert elapsed < 3, elapsed


@pytest.mark.parametrize("fake", ["nan_deny", "inf_block"])
def test_nonstandard_json_is_not_counted(env, fake):
    data = env.payload()
    for _ in range(4):
        same(env.wrapped(fake, data), env.raw(fake, data))
    assert not env.tsv.exists()


def special_file(path, kind, keep):
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "dir":
        path.mkdir()
    else:
        import socket
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(path))
        keep.append(s)


@pytest.mark.parametrize("which", ["lock", "log"])
@pytest.mark.parametrize("kind", ["fifo", "dir", "socket"])
def test_special_file_at_lock_or_log(env, which, kind):
    env.tsv.parent.mkdir(parents=True)
    target = pathlib.Path(f"{env.tsv}.lock") if which == "lock" else env.tsv
    keep = []
    special_file(target, kind, keep)
    try:
        data = env.payload()
        for _ in range(3):
            t = time.perf_counter()
            w = env.wrapped("exit2", data)
            assert time.perf_counter() - t < 3
            same(w, env.raw("exit2", data))
    finally:
        for s in keep:
            s.close()
    assert not env.cdir.exists()


@pytest.mark.parametrize("opts", ["errexit", "nounset", "pipefail", "errexit:nounset:pipefail", "xtrace"])
@pytest.mark.parametrize("fake", ["exit2", "json_deny", "quiet_pass", "stdin_hash"])
def test_inherited_shell_options(env, opts, fake):
    e = {**env.base_env, "SHELLOPTS": opts}
    data = env.payload()
    outs = [(env.wrapped(fake, data, env=e), env.raw(fake, data, env=e)) for _ in range(3)]
    for w, r in outs[:2]:
        same(w, r)
    w, r = outs[2]
    if fake in ("quiet_pass", "stdin_hash"):
        same(w, r)
        assert not env.tsv.exists()
    else:
        assert w.returncode == r.returncode and MARK.encode() in w.stdout + w.stderr
        assert len(env.rows()) == 4


def test_dead_inner_subshell_is_never_rc_zero(env):
    hook = env.tmp / "kill_parent.sh"
    hook.write_text("#!/usr/bin/env bash\ncat >/dev/null; kill -9 $PPID; exit 2\n")
    w = env.wrapped(None, env.payload(), cmd=["bash", str(hook)])
    assert w.returncode == 1


def test_utf8_locale_large_input_is_fast(env):
    e = {**env.base_env, "LC_ALL": "C.UTF-8"}
    data = env.payload(extra="한" * (6 * 1024 * 1024))
    t = time.perf_counter()
    w = env.wrapped("stdin_hash", data, env=e)
    elapsed = time.perf_counter() - t
    same(w, env.raw("stdin_hash", data, env=e))
    print(f"\n[utf8 18MB stdin] wrapped {elapsed:.2f} s")
    assert elapsed < 2


@pytest.mark.parametrize("which", ["counter", "pruned"])
def test_fifo_at_counter_or_pruned(env, which):
    env.cdir.mkdir(parents=True)
    os.mkfifo(env.cdir / ("sess1234.main.testhook" if which == "counter" else ".pruned"))
    data = env.payload()
    for i in range(3):
        t = time.perf_counter()
        w = env.wrapped("exit2", data)
        assert time.perf_counter() - t < 3
        r = env.raw("exit2", data)
        if which == "pruned" and i == 2:
            assert w.returncode == r.returncode and w.stderr.startswith(r.stderr) and MARK.encode() in w.stderr
        else:
            same(w, r)


def test_hardlinked_files_are_not_written(env):
    env.cdir.mkdir(parents=True)
    env.tsv.parent.mkdir(parents=True)
    victim = env.tmp / "victim"
    victim.write_text("7\n")
    os.link(victim, env.cdir / "sess1234.main.testhook")
    victim2 = env.tmp / "victim2"
    victim2.write_text("keep\n")
    os.link(victim2, env.tsv)
    victim3 = env.tmp / "victim3"
    victim3.write_text("2000-01-01\n")
    os.link(victim3, env.cdir / ".pruned")
    data = env.payload()
    for _ in range(4):
        same(env.wrapped("exit2", data), env.raw("exit2", data))
    assert victim.read_text() == "7\n" and victim2.read_text() == "keep\n" and victim3.read_text() == "2000-01-01\n"
    assert not [p for p in env.cdir.iterdir() if p.name.startswith(".tmp.")]


def test_lock_timeout_skips_record(env):
    import fcntl
    env.tsv.parent.mkdir(parents=True)
    with open(f"{env.tsv}.lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        data = env.payload()
        t = time.perf_counter()
        outs = [(env.wrapped("exit2", data), env.raw("exit2", data)) for _ in range(3)]
        elapsed = (time.perf_counter() - t) / 3
    for w, r in outs:
        same(w, r)
    assert elapsed < 1.5
    assert not env.tsv.exists() and not env.cdir.exists()


def test_parallel_twenty(env):
    data = env.payload()
    with ThreadPoolExecutor(20) as ex:
        res = list(ex.map(lambda _: env.wrapped("exit2", data), range(20)))
    assert all(r.returncode == 2 for r in res)
    rows = env.rows()
    assert len(rows) == 21 and all(len(r) == 6 for r in rows)
    assert sorted(int(r[5]) for r in rows[1:]) == list(range(1, 21))
    assert (env.cdir / "sess1234.main.testhook").read_text() == "20\n"


def test_name_sanitising(env):
    data = env.payload(sid="../../ab\tcd/../x", agent="../\tq")
    for _ in range(3):
        r = env.wrapped("exit2", data, hook="../../evil\tname")
    assert MARK.encode() in r.stderr
    files = [p for p in env.h.rglob("*") if p.is_file()]
    runs = env.h / ".claude/_usage/hook-runs" / f"{time.strftime('%Y-%m-%d')}.tsv"
    assert sorted(str(p.relative_to(env.h)) for p in files) == sorted(
        [".claude/_audit/hook-deny.tsv", ".claude/_audit/hook-deny.tsv.lock", ".claude/_cache/hook-deny/.pruned",
         ".claude/_cache/hook-deny/....abtc...q.....evilname", str(runs.relative_to(env.h))])
    rows = env.rows()
    assert all(len(r) == 6 for r in rows)
    assert rows[1][1:5] == ["....abtc", "..q", "....evilname", "Bash"]
    runs_rows = [ln.split("\t") for ln in runs.read_text().splitlines()]
    assert len(runs_rows) == 3 and all(len(r) == 9 for r in runs_rows)
    # WHY: runlog in scripts/hook-deny-wrap.sh reads agent_id by regex on the raw JSON, so the escape \t leaves a literal t
    # (the counter file name uses jq, which decodes it to a tab that is then dropped).
    assert runs_rows[0][1:8] == ["....abtc", "..tq", "PreToolUse", "....evilname", "Bash", "2", "deny"]


def test_stdin_five_mb(env):
    data = env.payload(extra="y" * (5 * 1024 * 1024))
    same(env.wrapped("stdin_hash", data), env.raw("stdin_hash", data))


def test_usage_errors(env):
    r = subprocess.run(["bash", str(WRAP)], capture_output=True, input=b"", check=False)
    assert r.returncode == 0 and r.stdout == b"" and r.stderr
    r = subprocess.run(["bash", str(WRAP), "name", "--"], capture_output=True, input=b"", check=False)
    assert r.returncode == 0
    fake = env.tmp / "fakes/exit2.sh"
    r = subprocess.run(["bash", str(WRAP), "--", "bash", str(fake)], capture_output=True, input=b"{}", check=False,
                       env=env.base_env)
    same(r, env.raw("exit2", b"{}"))
    assert not env.tsv.exists()


def test_prune_and_trim(env):
    env.cdir.mkdir(parents=True)
    old = env.cdir / "oldsess1.main.x"
    old.write_text("5\n")
    os.utime(old, (time.time() - 8 * 86400,) * 2)
    fresh = env.cdir / "newsess1.main.x"
    fresh.write_text("1\n")
    target = env.tmp / "outside"
    target.write_text("keep")
    link = env.cdir / "linksess.main.x"
    link.symlink_to(target)
    os.utime(link, (time.time() - 8 * 86400,) * 2, follow_symlinks=False)
    env.tsv.parent.mkdir(parents=True)
    env.tsv.write_text("time\tsession\tcaller\thook\ttool\tstreak\n" + ("a\tb\tc\td\te\t1\n" * 400000))
    env.wrapped("exit2", env.payload())
    assert not old.exists() and fresh.exists() and link.is_symlink() and target.read_text() == "keep"
    assert env.tsv.stat().st_size < 1100000
    rows = env.rows()
    assert rows[0][0] == "time" and rows[-1][1:] == ["sess1234", "main", "testhook", "Bash", "1"]
    old.write_text("5\n")
    os.utime(old, (time.time() - 8 * 86400,) * 2)
    env.wrapped("exit2", env.payload())
    assert old.exists()


def test_pass_overhead(env):
    data = env.payload()
    n = 100

    def bench(fn):
        t = time.perf_counter()
        for _ in range(n):
            fn()
        return (time.perf_counter() - t) / n * 1000

    raw = bench(lambda: env.raw("quiet_pass", data))
    wrapped = bench(lambda: env.wrapped("quiet_pass", data))
    env.wrapped("exit2", data)
    with_counter = bench(lambda: (env.wrapped("exit2", data), env.wrapped("quiet_pass", data)))
    print(f"\n[pass overhead] raw {raw:.2f} ms · wrapped {wrapped:.2f} ms · extra {wrapped - raw:.2f} ms/call "
          f"· deny+pass pair with counter file {with_counter:.2f} ms")
    assert wrapped - raw < 200


# REF: W14 hook-runs record and --log-only mode, intent/2026-11-24-harness-review-six-items.md 개정 2.

def runs_rows(env):
    d = env.h / ".claude/_usage/hook-runs"
    return [ln.split("\t") for f in sorted(d.glob("*.tsv")) for ln in f.read_text().splitlines()] if d.is_dir() else []


def logged(env, fake, data, hook="logthis", env_=None, cmd=None, **kw):
    argv = cmd or ["bash", str(env.tmp / "fakes" / f"{fake}.sh")]
    return subprocess.run(["bash", str(WRAP), "--log-only", hook, "--", *argv], input=data, capture_output=True,
                          env=env_ or env.base_env, timeout=60, check=False, **kw)


def test_hook_runs_in_deny_mode(env):
    data = env.payload(agent="agentXYZ123456")
    for fake in ("quiet_pass", "exit2", "exit1", "json_deny", "exit1_json_deny"):
        env.wrapped(fake, data)
    rows = runs_rows(env)
    assert [r[1:8] for r in rows] == [["sess1234", "agentXYZ", "PreToolUse", "testhook", "Bash", rc, v] for rc, v in
                                      (("0", "pass"), ("2", "deny"), ("1", "error"), ("0", "deny"), ("1", "deny"))]
    assert all(len(r) == 9 and r[8].isdigit() for r in rows)
    assert LEAK_MARK not in "".join("\t".join(r) for r in rows)
    assert stat.S_IMODE(next((env.h / ".claude/_usage/hook-runs").iterdir()).stat().st_mode) == 0o600


@pytest.mark.parametrize("fake", sorted(FAKES))
def test_log_only_is_byte_identical(env, fake):
    data = env.payload()
    for _ in range(3):
        same(logged(env, fake, data), env.raw(fake, data))
    assert not env.tsv.exists() and not env.cdir.exists()
    rc = env.raw(fake, data).returncode
    want = "pass" if rc == 0 else "deny" if rc == 2 else "error"
    assert [r[6:8] for r in runs_rows(env)] == [[str(rc), want]] * 3


def test_log_only_does_not_wait_for_background_children(env):
    hook = env.tmp / "bg.sh"
    hook.write_text("#!/usr/bin/env bash\ncat >/dev/null; (sleep 3; echo late; echo late2 >&2) & echo now; exit 0\n")
    out = env.tmp / "out"
    with open(out, "wb") as fo:
        t = time.perf_counter()
        r = subprocess.run(["bash", str(WRAP), "--log-only", "bg", "--", "bash", str(hook)], input=env.payload(),
                           stdout=fo, stderr=fo, env=env.base_env, timeout=30, check=False)
        elapsed = time.perf_counter() - t
    assert r.returncode == 0 and elapsed < 1.5, elapsed
    assert out.read_bytes() == b"now\n"
    assert [r[4:8] for r in runs_rows(env)] == [["bg", "Bash", "0", "pass"]]


@pytest.mark.parametrize("kind", ["fifo", "symlink", "dir", "readonly"])
def test_log_only_unusable_record_place(env, kind):
    d = env.h / ".claude/_usage/hook-runs"
    d.mkdir(parents=True)
    f = d / f"{time.strftime('%Y-%m-%d')}.tsv"
    victim = env.tmp / "victim"
    victim.write_text("keep\n")
    if kind == "fifo":
        os.mkfifo(f)
    elif kind == "symlink":
        f.symlink_to(victim)
    elif kind == "dir":
        f.mkdir()
    else:
        d.chmod(0o500)
    data = env.payload()
    try:
        for fake in ("exit2", "stdout_pass", "stdin_hash"):
            t = time.perf_counter()
            same(logged(env, fake, data), env.raw(fake, data))
            same(env.wrapped(fake, data), env.raw(fake, data))
            assert time.perf_counter() - t < 5
    finally:
        d.chmod(0o700)
    assert victim.read_text() == "keep\n"


def start_slow(env, mode, marker):
    hook = env.tmp / "slow_hook.sh"
    hook.write_text(f"#!/usr/bin/env bash\ncat >/dev/null; : > '{marker}'; sleep 30; exit 0\n")
    head = ["--log-only", "slowhook"] if mode == "log" else ["slowhook"]
    p = subprocess.Popen(["bash", str(WRAP), *head, "--", "bash", str(hook)], stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env.base_env, start_new_session=True)
    p.stdin.write(env.payload())
    p.stdin.close()
    t = time.time()
    while not marker.exists() and time.time() - t < 10:
        time.sleep(0.02)
    return p


@pytest.mark.parametrize("mode", ["log", "deny"])
@pytest.mark.parametrize("sig,code", [(15, 143), (2, 130), (1, 129)])
def test_group_signal_is_recorded_as_killed(env, mode, sig, code):
    p = start_slow(env, mode, env.tmp / "started")
    os.killpg(p.pid, sig)
    assert p.wait(timeout=10) == -sig
    assert [r[4:8] for r in runs_rows(env)] == [["slowhook", "Bash", str(code), "killed"]]


def test_sigkill_leaves_no_row(env):
    # REF: limit 10 in the scripts/hook-deny-wrap.sh header (SIGKILL leaves no row).
    p = start_slow(env, "log", env.tmp / "started")
    os.killpg(p.pid, 9)
    assert p.wait(timeout=10) == -9
    assert runs_rows(env) == []


def test_signal_to_wrapper_only_waits_for_hook(env):
    # REF: limit 10 in the scripts/hook-deny-wrap.sh header (a trap waits for the foreground hook to end).
    hook = env.tmp / "short.sh"
    marker = env.tmp / "started"
    hook.write_text(f"#!/usr/bin/env bash\ncat >/dev/null; : > '{marker}'; sleep 1; echo out\n")
    p = subprocess.Popen(["bash", str(WRAP), "--log-only", "short", "--", "bash", str(hook)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env.base_env)
    p.stdin.write(env.payload())
    p.stdin.close()
    t = time.time()
    while not marker.exists() and time.time() - t < 10:
        time.sleep(0.02)
    p.send_signal(15)
    out = p.stdout.read()
    assert p.wait(timeout=10) == -15 and out == b"out\n"
    assert [r[6:8] for r in runs_rows(env)] == [["143", "killed"]]


def test_log_only_usage_errors(env):
    r = subprocess.run(["bash", str(WRAP), "--log-only", "n", "--"], capture_output=True, input=b"", check=False)
    assert r.returncode == 0
    fake = env.tmp / "fakes/exit2.sh"
    r = subprocess.run(["bash", str(WRAP), "--log-only", "n", "x", "--", "bash", str(fake)], capture_output=True,
                       input=b"{}", check=False, env=env.base_env)
    same(r, env.raw("exit2", b"{}"))
    assert runs_rows(env) == []


def test_log_only_parallel_twenty(env):
    data = env.payload()
    with ThreadPoolExecutor(20) as ex:
        res = list(ex.map(lambda i: logged(env, "exit2", data, hook=f"h{i}"), range(20)))
    assert all(r.returncode == 2 for r in res)
    rows = runs_rows(env)
    assert len(rows) == 20 and all(len(r) == 9 for r in rows)
    assert sorted(r[4] for r in rows) == sorted(f"h{i}" for i in range(20))
