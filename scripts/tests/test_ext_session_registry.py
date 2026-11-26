"""ext_session_registry.py · exchange-prune.sh 대장 정리 호출 시험.

실행: uv run --with pytest python -m pytest scripts/tests/test_ext_session_registry.py -q
격리: 실제 홈을 건드리지 않도록 HOME 을 임시 폴더로 바꾸고, PATH 맨 앞에 가짜 codex 를 둔다(실제 codex 는 부르지 않는다).
  가짜 codex 는 받은 인자를 $HOME/codex-calls.txt 에 적고, `delete --force <UUID>` 면 그 UUID 의 rollout 파일을 지운다.
REF: docs/superpowers/plans/2026-11-26-ext-review-gate-sessions.md §3 · §5
"""
import fcntl
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
REGISTRY_PY = SCRIPTS / "ext_session_registry.py"
PRUNE_SH = SCRIPTS / "exchange-prune.sh"
DAY = 86400
U1 = "019f634c-4046-7851-90ed-52eb74521e9a"
U2 = "01a1cfad-5c4e-7201-9c6a-0e89ea7a498d"
FAKE_CODEX = """#!/bin/sh
echo "$*" >> "$HOME/codex-calls.txt"
[ -n "$FAKE_CODEX_BYTES" ] && printf '\\377\\376 bad\\n' && printf '\\377\\n' >&2
[ -n "$FAKE_CODEX_FAIL" ] && exit 1
[ -n "$FAKE_CODEX_KEEP" ] && exit 0
if [ "$1" = delete ] && [ "$2" = --force ]; then
    find "$HOME/.codex" -name "rollout-*$3.jsonl" -delete
fi
exit 0
"""


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    (h / "bin").mkdir(parents=True)
    fake = h / "bin/codex"
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    fake.chmod(0o755)
    return h


def env_for(home, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EXT_SESSION", "EXCHANGE_PRUNE", "FAKE_CODEX"))}
    env.update(HOME=str(home), PATH=f"{home}/bin:/usr/bin:/bin")
    env.update(extra)
    return env


def reg(home, *args, **extra):
    return subprocess.run([sys.executable, "-I", str(REGISTRY_PY), *args], capture_output=True, text=True,
                          env=env_for(home, **extra), check=False)


def age(path, days):
    ts = time.time() - days * DAY
    if path.is_dir() and not path.is_symlink():
        for root, dirs, files in os.walk(path, topdown=False):
            for n in dirs + files:
                os.utime(os.path.join(root, n), (ts, ts), follow_symlinks=False)
    os.utime(path, (ts, ts), follow_symlinks=False)


def make_grok(home, name, days):
    sess = home / "grok-exchange/.sessions"
    run = sess / f"{name}.run"
    run.mkdir(parents=True)
    (run / "note.txt").write_text("x", encoding="utf-8")
    (sess / f"{name}.id").write_text("sid\n", encoding="utf-8")
    (sess / f"{name}.lock").write_text("", encoding="utf-8")
    store = home / ".grok/sessions" / urllib.parse.quote(str(run), safe="")
    (store / "sid").mkdir(parents=True)
    (store / "sid/messages.json").write_text("{}", encoding="utf-8")
    paths = [run, sess / f"{name}.id", store]
    for p in paths + [sess / f"{name}.lock"]:
        age(p, days)
    return paths


def make_codex(home, uuid, days, archived=False):
    d = home / (".codex/archived_sessions" if archived else ".codex/sessions/2026/11/01")
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"rollout-2026-11-01T00-00-00-{uuid}.jsonl"
    f.write_text("{}\n", encoding="utf-8")
    age(f, days)
    return f


def write_registry(home, grok=(), codex=()):
    head = "| 세션 | 프로젝트 | 주제 | intent | plan | 만든 날 | 마지막 사용 |\n|---|---|---|---|---|---|---|\n"
    body = "# 외부 모델 세션 대장\n\n## Grok\n\n" + head
    body += "".join(f"| {r} |\n" for r in grok) + "\n## Codex\n\n" + head + "".join(f"| {r} |\n" for r in codex)
    path = home / ".claude/_usage/ext-sessions.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def old_row(sid, days=30):
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - days * DAY))
    return f"{sid} | P | 주제 |  |  | {stamp} | {stamp}"


def listed(home, tool=None):
    out = reg(home, "list", *(["--tool", tool] if tool else [])).stdout
    return [ln.split("\t") for ln in out.splitlines()]


def codex_calls(home):
    f = home / "codex-calls.txt"
    return f.read_text(encoding="utf-8").splitlines() if f.exists() else []


def test_add_list_and_update(home):
    assert reg(home, "add", "--tool", "grok", "--id", "exp-plan.v1", "--project", "exp", "--topic", "a | b",
               "--intent", "intent/x.md", "--plan", "docs/p.md").returncode == 0
    assert reg(home, "add", "--tool", "codex", "--id", U1, "--project", "exp", "--topic", "코드 검토").returncode == 0
    rows = listed(home)
    assert [r[:2] for r in rows] == [["grok", "exp-plan.v1"], ["codex", U1]]
    assert rows[0][4:] == ["a | b", "intent/x.md", "docs/p.md"]
    reg(home, "add", "--tool", "grok", "--id", "exp-plan.v1", "--project", "exp", "--topic", "새 주제")
    grok = listed(home, "grok")
    assert len(grok) == 1 and grok[0][4] == "새 주제" and grok[0][5] == "intent/x.md"


def test_add_rejects_bad_ids(home):
    assert reg(home, "add", "--tool", "grok", "--id", "../evil", "--project", "P", "--topic", "t").returncode != 0
    assert reg(home, "add", "--tool", "codex", "--id", "not-a-uuid", "--project", "P", "--topic", "t").returncode != 0
    assert not (home / ".claude/_usage/ext-sessions.md").exists()


def test_match_by_path_topic_and_mismatch(home):
    for sid, proj, topic, extra in [("a", "P", "학습 계획 검토", ["--intent", "intent/x.md"]),
                                    ("b", "P", "모델 코드 리뷰", []),
                                    ("c", "Q", "학습 계획 검토", ["--plan", "docs/q.md"])]:
        make_grok(home, sid, 1)
        reg(home, "add", "--tool", "grok", "--id", sid, "--project", proj, "--topic", topic, *extra)
    out = reg(home, "match", "--tool", "grok", "--project", "P", "--topic", "학습 계획 다시",
              "--intent", "intent/x.md").stdout.splitlines()
    assert [ln.split("\t")[1] for ln in out] == ["a"]
    assert int(out[0].split("\t")[0]) >= 100
    out = reg(home, "match", "--tool", "grok", "--project", "P", "--topic", "코드 리뷰").stdout.splitlines()
    assert [ln.split("\t")[1] for ln in out] == ["b"]
    out = reg(home, "match", "--tool", "grok", "--project", "P", "--topic", "무관", "--plan", "docs/q.md").stdout
    assert [ln.split("\t")[1] for ln in out.splitlines()] == ["c"]
    assert reg(home, "match", "--tool", "grok", "--project", "Z", "--topic", "학습 계획").stdout == ""
    assert reg(home, "match", "--tool", "codex", "--project", "P", "--topic", "학습 계획").stdout == ""


def test_match_skips_sessions_gone_from_disk(home):
    make_grok(home, "live", 1)
    make_codex(home, U2, 1)
    for tool, sid in [("grok", "live"), ("grok", "dead"), ("codex", U1), ("codex", U2)]:
        reg(home, "add", "--tool", tool, "--id", sid, "--project", "P", "--topic", "학습 계획 검토")
    out = reg(home, "match", "--tool", "grok", "--project", "P", "--topic", "학습 계획").stdout
    assert [ln.split("\t")[1] for ln in out.splitlines()] == ["live"]
    out = reg(home, "match", "--tool", "codex", "--project", "P", "--topic", "학습 계획").stdout
    assert [ln.split("\t")[1] for ln in out.splitlines()] == [U2]


def test_add_lowercases_codex_id(home):
    assert reg(home, "add", "--tool", "codex", "--id", U1.upper(), "--project", "P", "--topic", "t").returncode == 0
    reg(home, "add", "--tool", "codex", "--id", U1, "--project", "P", "--topic", "t2")
    assert [(x[1], x[4]) for x in listed(home, "codex")] == [(U1, "t2")]


def test_prune_without_registry_creates_nothing(home):
    for args in ([], ["--dry-run"]):
        r = reg(home, "prune", *args)
        assert r.returncode == 0, r.stderr
    assert not (home / ".claude/_usage").exists()


def test_malformed_cell_count_warns_with_line_number(home):
    path = write_registry(home, grok=["ok-1 | P | t |  |  | s | s", "bad | P | t | x"])
    no = path.read_text(encoding="utf-8").splitlines().index("| bad | P | t | x |") + 1
    r = reg(home, "list")
    assert f"{no}번째 줄" in r.stderr and "bad" not in r.stderr
    assert [x[1] for x in listed(home)] == ["ok-1"]
    r = reg(home, "add", "--tool", "grok", "--id", "ok-2", "--project", "P", "--topic", "t")
    assert r.returncode == 0 and f"{no}번째 줄" in r.stderr


def test_prune_isolates_row_errors(home):
    if os.geteuid() == 0:
        print("건너뜀: root 는 권한 오류가 나지 않아 행 격리 시험을 할 수 없습니다")
        pytest.skip("root 로 실행되어 권한 오류를 만들 수 없음")
    a = make_grok(home, "a", 10)
    b = make_grok(home, "b", 10)
    locked_dir = b[0] / "locked"
    locked_dir.mkdir()
    (locked_dir / "f.txt").write_text("x", encoding="utf-8")
    age(b[0], 10)
    locked_dir.chmod(0o500)
    c = make_codex(home, U1, 10)
    write_registry(home, grok=[old_row("a"), old_row("b")], codex=[old_row(U1)])
    try:
        r = reg(home, "prune")
    finally:
        locked_dir.chmod(0o700)
    assert r.returncode == 0, r.stderr
    assert "grok b 처리 실패" in r.stderr
    assert not any(os.path.lexists(p) for p in a) and not c.exists()
    assert os.path.lexists(b[0]) and os.path.lexists(b[1])
    assert [x[1] for x in listed(home)] == ["b"]
    log = (home / ".claude/_audit/ext-session-prune.log").read_text(encoding="utf-8").splitlines()
    assert [ln.split("\t")[2::2] for ln in log] == [["a", "deleted"], ["b", "failed"], [U1, "deleted"]]


def test_prune_codex_exit0_but_file_left_keeps_row(home):
    f = make_codex(home, U1, 10)
    write_registry(home, codex=[old_row(U1)])
    assert reg(home, "prune", FAKE_CODEX_KEEP="1").returncode == 0
    assert codex_calls(home) == [f"delete --force {U1}"]
    assert f.exists() and [x[1] for x in listed(home)] == [U1]


def test_prune_codex_missing_binary_warns_once(home):
    (home / "bin/codex").unlink()
    make_codex(home, U1, 10)
    make_codex(home, U2, 10)
    write_registry(home, codex=[old_row(U1), old_row(U2)])
    r = reg(home, "prune", PATH=str(home / "bin"))
    assert r.returncode == 0 and r.stderr.count("PATH 에 없어") == 1
    assert sorted(x[1] for x in listed(home)) == sorted([U1, U2])


def test_prune_grok_old_deleted_recent_kept_unregistered_untouched(home):
    old = make_grok(home, "old", 10)
    new = make_grok(home, "new", 1)
    stray = make_grok(home, "stray", 30)
    store = home / ".grok/sessions"
    (store / "session_search.sqlite").write_text("db", encoding="utf-8")
    age(store / "session_search.sqlite", 30)
    reg(home, "add", "--tool", "grok", "--id", "old", "--project", "P", "--topic", "t")
    reg(home, "add", "--tool", "grok", "--id", "new", "--project", "P", "--topic", "t")
    r = reg(home, "prune")
    assert r.returncode == 0, r.stderr
    assert not any(os.path.lexists(p) for p in old)
    assert (home / "grok-exchange/.sessions/old.lock").exists()
    assert all(p.exists() for p in new + stray) and (store / "session_search.sqlite").exists()
    assert [x[1] for x in listed(home)] == ["new"]
    log = (home / ".claude/_audit/ext-session-prune.log").read_text(encoding="utf-8").splitlines()
    assert len(log) == 1 and log[0].split("\t")[1:3] == ["grok", "old"] and log[0].endswith("\tdeleted")


def test_prune_gone_sessions_remove_row_only(home):
    write_registry(home, grok=[old_row("vanished")], codex=[old_row(U1)])
    assert reg(home, "prune").returncode == 0
    assert listed(home) == []
    assert codex_calls(home) == []
    log = (home / ".claude/_audit/ext-session-prune.log").read_text(encoding="utf-8")
    assert log.count("\tgone") == 2


def test_prune_codex_calls_delete_force(home):
    f_old = make_codex(home, U1, 10)
    f_new = make_codex(home, U2, 1, archived=True)
    write_registry(home, codex=[old_row(U1), old_row(U2)])
    assert reg(home, "prune").returncode == 0
    assert codex_calls(home) == [f"delete --force {U1}"]
    assert not f_old.exists() and f_new.exists()
    assert [x[1] for x in listed(home)] == [U2]


def test_prune_codex_failure_keeps_row(home):
    f = make_codex(home, U1, 10)
    write_registry(home, codex=[old_row(U1)])
    assert reg(home, "prune", FAKE_CODEX_FAIL="1").returncode == 0
    assert f.exists() and [x[1] for x in listed(home)] == [U1]
    assert (home / ".claude/_audit/ext-session-prune.log").read_text(encoding="utf-8").rstrip().endswith("\tfailed")


def test_prune_skips_malformed_rows(home):
    bait = home / "grok-exchange/evil.id"
    bait.parent.mkdir(parents=True)
    bait.write_text("x", encoding="utf-8")
    write_registry(home, grok=[old_row("../evil")], codex=[old_row("nope")])
    r = reg(home, "prune")
    assert r.returncode == 0 and "형식이 맞지 않아" in r.stderr
    assert bait.exists() and codex_calls(home) == []
    assert sorted(x[1] for x in listed(home)) == ["../evil", "nope"]


def test_prune_refuses_symlinked_session_paths(home, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("k", encoding="utf-8")
    sess = home / "grok-exchange/.sessions"
    sess.mkdir(parents=True)
    (sess / "lnk.run").symlink_to(outside)
    (sess / "lnk.id").write_text("sid", encoding="utf-8")
    age(sess / "lnk.id", 30)
    age(sess / "lnk.run", 30)
    write_registry(home, grok=[old_row("lnk")])
    assert reg(home, "prune").returncode == 0
    assert (outside / "keep.txt").exists() and (sess / "lnk.id").exists()
    assert [x[1] for x in listed(home)] == ["lnk"]


def test_prune_skips_grok_session_in_use(home):
    make_grok(home, "busy", 10)
    write_registry(home, grok=[old_row("busy")])
    fd = os.open(home / "grok-exchange/.sessions/busy.lock", os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert reg(home, "prune").returncode == 0
    finally:
        os.close(fd)
    assert (home / "grok-exchange/.sessions/busy.id").exists()
    assert [x[1] for x in listed(home)] == ["busy"]


def test_prune_ignores_fresh_lock_mtime(home):
    g = make_grok(home, "old", 10)
    lock = home / "grok-exchange/.sessions/old.lock"
    os.utime(lock)
    write_registry(home, grok=[old_row("old")])
    assert reg(home, "prune").returncode == 0
    assert not any(os.path.lexists(p) for p in g) and lock.exists()
    assert listed(home) == []


def test_prune_warns_on_refused_grok(home, tmp_path):
    outside = tmp_path / "outside"
    store = home / ".grok"
    store.mkdir(parents=True)
    (store / "sessions").symlink_to(outside, target_is_directory=True)
    outside.mkdir()
    g = make_grok(home, "far", 10)
    write_registry(home, grok=[old_row("far")])
    r = reg(home, "prune")
    assert r.returncode == 0 and "grok far 삭제 거부" in r.stderr
    assert all(os.path.lexists(p) for p in g) and [x[1] for x in listed(home)] == ["far"]


def test_prune_refuses_dangling_symlink_lock(home, tmp_path):
    g = make_grok(home, "dl", 10)
    lock = home / "grok-exchange/.sessions/dl.lock"
    lock.unlink()
    victim = tmp_path / "victim-not-exist"
    lock.symlink_to(victim)
    write_registry(home, grok=[old_row("dl")])
    r = reg(home, "prune")
    assert r.returncode == 0 and "grok dl 삭제 거부" in r.stderr
    assert all(os.path.lexists(p) for p in g) and [x[1] for x in listed(home)] == ["dl"]
    assert os.path.islink(lock) and not victim.exists()


def test_match_skips_grok_session_without_run_folder(home):
    make_grok(home, "half", 1)
    shutil.rmtree(home / "grok-exchange/.sessions/half.run")
    write_registry(home, grok=[old_row("half").replace("주제", "백본 교체 계획")])
    r = reg(home, "match", "--tool", "grok", "--project", "P", "--topic", "백본 교체 계획")
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_prune_survives_unwritable_log(home):
    f = make_codex(home, U1, 10)
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude/_audit").write_text("not a dir", encoding="utf-8")
    write_registry(home, codex=[old_row(U1)])
    r = reg(home, "prune")
    assert r.returncode == 0, r.stderr
    assert r.stderr.count("삭제 기록을 쓰지 못함") == 1
    assert not f.exists() and listed(home) == []


def test_prune_codex_non_utf8_output(home):
    f = make_codex(home, U1, 10)
    write_registry(home, codex=[old_row(U1)])
    r = reg(home, "prune", FAKE_CODEX_BYTES="1")
    assert r.returncode == 0, r.stderr
    assert not f.exists() and listed(home) == []


def test_prune_uppercase_codex_row(home):
    f = make_codex(home, U1, 10)
    write_registry(home, codex=[old_row(U1.upper())])
    assert reg(home, "prune").returncode == 0
    assert codex_calls(home) == [f"delete --force {U1}"]
    assert not f.exists() and listed(home) == []


def test_dry_run_deletes_nothing(home):
    g = make_grok(home, "old", 10)
    c = make_codex(home, U1, 10)
    path = write_registry(home, grok=[old_row("old"), old_row("vanished")], codex=[old_row(U1)])
    before = path.read_bytes()
    r = reg(home, "prune", "--dry-run")
    assert r.returncode == 0
    assert "old" in r.stdout and U1 in r.stdout and "vanished" in r.stdout
    assert all(os.path.lexists(p) for p in g) and c.exists()
    assert path.read_bytes() == before and codex_calls(home) == []
    assert not (home / ".claude/_audit/ext-session-prune.log").exists()


@pytest.mark.parametrize("days, survives", [("0", True), ("abc", True), ("2", False)])
def test_days_env(home, days, survives):
    g = make_grok(home, "mid", 3)
    write_registry(home, grok=[old_row("mid")])
    reg(home, "prune", EXT_SESSION_DAYS=days)
    assert os.path.lexists(g[1]) is survives


def run_exchange_prune(home, **extra):
    return subprocess.run(["bash", str(PRUNE_SH)], capture_output=True, text=True,
                          env=env_for(home, **extra), check=False)


def test_exchange_prune_calls_registry_only_without_roots(home):
    g = make_grok(home, "old", 10)
    write_registry(home, grok=[old_row("old")])
    r = run_exchange_prune(home, EXCHANGE_PRUNE_ROOTS=str(home / "grok-exchange"))
    assert r.returncode == 0 and os.path.lexists(g[1])
    r = run_exchange_prune(home)
    assert r.returncode == 0, r.stderr
    assert not os.path.lexists(g[1]) and listed(home) == []
