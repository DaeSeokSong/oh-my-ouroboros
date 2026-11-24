"""scope-gate.sh 회귀 테스트 — 프로젝트 경계 + 하네스 핵심 경로·매니저 예외.

실행: uv run -q --no-project --with pytest python -m pytest scripts/tests/test_scope_gate.py -q
대상 훅은 env SCOPE_GATE_SCRIPT 로 바꿀 수 있다(기본 scripts/scope-gate.sh). 개발 중 훅을 제자리에서 고치지 않고 사본으로 시험하기 위함.

격리: 모든 케이스가 임시 HOME(tmp_path/home) 아래에서 돈다. 실제 ~/.claude 와 sessions/ 를 건드리지 않는다.
  harness 픽스처는 두 배치를 모두 돈다: «plain»(HOME/.claude 가 실제 폴더) · «symlink»(HOME/.claude 가 다른 폴더를 가리키는 심볼릭, host1 과 같은 배치).
  허용 목록은 훅의 SCOPE_ALLOW_FILE·SCOPE_ALLOW_LOCAL_FILE 환경변수로 임시 파일을 끼워 실제 config 를 보호한다.

알려진 한계 (시험하지 않고 여기에 기록 — 설계 개정 2 G1 보강):
  - Bash 로 sessions/*.json 을 위조하면 매니저 판정이 속는다. 이 훅은 Write·Edit 만 타므로 못 막고,
    bash-write-check.sh 의 리다이렉션·heredoc 차단이 유일한 방어다.
  - 같은 이름 «[Harness] Manager» 의 다른 세션, 그리고 매니저 세션이 띄운 subagent 는 같은 session_id 로 통과한다.
REF: knowledge/harness/code-history/scripts__tests__test_scope_gate.py.md
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(os.environ.get("SCOPE_GATE_SCRIPT") or Path(__file__).resolve().parent.parent / "scope-gate.sh")
MGR = "[Harness] Manager"
MGR_SID = "sid-manager-0001"
OTHER_SID = "sid-other-0002"


def git_init(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)


def proc_start(pid: int) -> str:
    stat = Path(f"/proc/{pid}/stat").read_text()
    return stat.rsplit(") ", 1)[1].split()[19]


class Result:
    def __init__(self, cp):
        self.rc, self.out, self.err = cp.returncode, cp.stdout, cp.stderr
        self.blocked = cp.returncode == 2 or '"block"' in cp.stdout


class Harness:
    def __init__(self, root: Path, symlinked: bool):
        self.root = root
        self.home = root / "home"
        self.home.mkdir()
        if symlinked:
            self.real = root / "real_harness"
            git_init(self.real)
            (self.home / ".claude").symlink_to(self.real)
        else:
            self.real = self.home / ".claude"
            git_init(self.real)
        self.logical = self.home / ".claude"
        for d in ("sessions", "scope"):
            (self.real / d).mkdir()
        self.repo_a, self.repo_b = root / "repo_a", root / "repo_b"
        git_init(self.repo_a)
        git_init(self.repo_b)
        self.nogit = root / "nogit"
        self.nogit.mkdir()
        self.allow = self.local = None

    def add_session(self, fname, sid, name=MGR, pid=None, pstart=None):
        pid = os.getpid() if pid is None else pid
        if pstart is None:
            pstart = proc_start(pid)
        (self.real / "sessions" / f"{fname}.json").write_text(json.dumps(
            {"pid": pid, "sessionId": sid, "name": name, "procStart": pstart, "cwd": "/x"}))

    def run(self, cwd, target, sid=OTHER_SID, **kw) -> Result:
        payload = {"cwd": str(cwd), "tool_input": {"file_path": str(target)}}
        if sid is not None:
            payload["session_id"] = sid
        env = dict(os.environ, HOME=str(self.home))
        absent = self.root / "absent-does-not-exist.txt"
        env["SCOPE_ALLOW_FILE"] = str(kw.get("allow") or absent)
        env["SCOPE_ALLOW_LOCAL_FILE"] = str(kw.get("local") or absent)
        if kw.get("path"):
            env["PATH"] = kw["path"]
        stdin = kw["raw"] if kw.get("raw") else json.dumps(payload)
        cp = subprocess.run([shutil.which("bash"), str(SCRIPT)], input=stdin, check=False, capture_output=True, text=True,
                            env=env, timeout=kw.get("timeout", 30))
        return Result(cp)


@pytest.fixture(params=["plain", "symlink"])
def hk(request, tmp_path):
    return Harness(tmp_path, request.param == "symlink")


def test_project_boundary_cases(hk):
    a, b = hk.repo_a, hk.repo_b
    sub = a / "sub"
    git_init(sub)
    (b / "x.py").write_text("b")
    (a / "x.py").write_text("a")
    (hk.root / "plain.txt").write_text("p")
    allowed, denied, local_only = hk.root / "allowed", hk.root / "denied", hk.root / "local_only"
    for d in (allowed, denied, local_only):
        d.mkdir()
    allow = hk.root / "scope-allow.txt"
    allow.write_text(f"# 주석\n\n{allowed}\n")
    local = hk.root / "scope-allow.local.txt"
    local.write_text(f"# 서버 전용\n{local_only}\n")
    root, h = hk.root, hk.logical
    mem = h / "projects/-zz-test/memory/MEMORY.md"
    cases = [
        ("다른 저장소 기존 파일", a, b / "x.py", True, None, None),
        ("다른 저장소 미존재 파일", a, b / "new.py", True, None, None),
        ("같은 저장소", a, a / "x.py", False, None, None),
        ("중첩 저장소", a, sub / "y.py", False, None, None),
        ("저장소 밖 일반 파일", a, root / "plain.txt", False, None, None),
        ("프로젝트 memory 기록", a, h / "projects/-zz-test/memory/short-term/decisions.md", False, None, None),
        ("프로젝트 자동 메모리", a, mem, False, None, None),
        ("하네스 jobs tmp, 다른 저장소 cwd", a, h / "jobs/zz-test/tmp/x.py", True, None, None),
        ("하네스 jobs tmp, 하네스 cwd (현행 유지)", h, h / "jobs/zz-test/tmp/x.py", False, None, None),
        ("하네스 teams, 다른 저장소 cwd", a, h / "teams/t/x.json", True, None, None),
        ("하네스 daemon, 다른 저장소 cwd", a, h / "daemon/x.log", True, None, None),
        ("하네스 루트 README.md, 다른 저장소 cwd (기본값 매니저 전용)", a, h / "README.md", True, None, None),
        ("하네스 루트 README.md, 하네스 cwd (기본값 매니저 전용)", h, h / "README.md", True, None, None),
        ("깊은 projects 경로의 memory, 다른 저장소 cwd", a, h / "projects/-zz-test/sub/memory/x.md", True, None, None),
        ("projects 세션 산출물(jsonl)", a, h / "projects/-zz-test/session.jsonl", True, None, None),
        ("상대 경로로 다른 저장소", a, "../repo_b/x.py", True, None, None),
        ("상대 경로로 같은 저장소", a, "x.py", False, None, None),
        ("저장소 밖 cwd + 허용 목록 없음", root, b / "x.py", True, None, None),
        ("저장소 밖 cwd + 허용 접두 아래", root, allowed / "x.py", False, allow, None),
        ("저장소 밖 cwd + 허용 접두 밖", root, denied / "x.py", True, allow, None),
        ("저장소 밖 cwd + memory 예외", root, mem, False, None, None),
        ("저장소 밖 cwd + 서버별 목록 아래", root, local_only / "x.py", False, None, local),
        ("저장소 밖 cwd + 공통·서버별 합집합, 공통 접두", root, allowed / "x.py", False, allow, local),
        ("저장소 밖 cwd + 공통·서버별 합집합, 서버별 접두", root, local_only / "x.py", False, allow, local),
        ("저장소 밖 cwd + 서버별 목록만, 접두 밖", root, denied / "x.py", True, None, local),
        ("저장소 밖 cwd + 공통 목록만, 서버별 접두", root, local_only / "x.py", True, allow, None),
    ]
    bad = []
    for name, cwd, target, want, al, lo in cases:
        r = hk.run(cwd, target, allow=al, local=lo)
        if r.blocked != want:
            bad.append(f"{name}: block={r.blocked} (기대 {want}) rc={r.rc} out={r.out[:120]!r}")
    assert not bad, "\n".join(bad)


ALWAYS_BLOCK = [
    ".git/hooks/x", ".git/config",
    "sessions/9999.json", "sessions/new/x.json",
    "scope/other-session.json", "scope/sub/x.json",
    "_evolve/candidates.tsv", "_evolve/candidates.lock", "_evolve/crosscheck.tsv", "_evolve/prompts.jsonl",
    "_evolve/t41-ledger.jsonl", "_evolve/t41-ledger.lock",
    "_usage/bench-last", "_usage/sub/x",
    "_audit/publish-approval/used.tsv", "_audit/publish-approval/x.json",
    "projects/-zz-test/abcd.jsonl", "projects/-zz-test/abcd/subagents/x.jsonl",
]


@pytest.mark.parametrize("rel", ALWAYS_BLOCK)
def test_always_block_even_for_manager(hk, rel):
    hk.add_session("m1", MGR_SID)
    for cwd in (hk.nogit, hk.logical, hk.repo_a):
        r = hk.run(cwd, hk.logical / rel, sid=MGR_SID)
        assert r.blocked, f"{rel} cwd={cwd}: {r.out!r}"
        r = hk.run(cwd, hk.real / rel, sid=MGR_SID)
        assert r.blocked, f"물리 {rel} cwd={cwd}: {r.out!r}"


def test_always_block_via_dotdot(hk):
    hk.add_session("m1", MGR_SID)
    assert hk.run(hk.logical, hk.logical / "scripts/../sessions/x.json", sid=MGR_SID).blocked
    assert hk.run(hk.logical, hk.logical / "knowledge/../_usage/x", sid=OTHER_SID).blocked


def test_projects_memory_jsonl_is_exempt_from_forgery_rule(hk):
    assert not hk.run(hk.logical, hk.logical / "projects/-zz-test/memory/note.jsonl").blocked


def test_own_scope_file_passes_everywhere_other_blocked(hk):
    assert not hk.run(hk.nogit, hk.logical / f"scope/{OTHER_SID}.json", sid=OTHER_SID).blocked
    assert hk.run(hk.nogit, hk.logical / "scope/sid-someone-else.json", sid=OTHER_SID).blocked
    assert hk.run(hk.logical, hk.logical / "scope/sid-someone-else.json", sid=OTHER_SID).blocked
    assert hk.run(hk.logical, hk.logical / f"scope/{OTHER_SID}.json", sid=None).blocked


ALLOW_ALL = [
    "knowledge/proj/note.md", "doc-formats/exp/form.md", "_evolve/quiz/q1.md", ".scratch/job/x.py",
    "projects/-zz-test/memory/MEMORY.md", "projects/-zz-test/memory/short-term/decisions.md",
]


@pytest.mark.parametrize("rel", ALLOW_ALL)
def test_all_sessions_may_write_own_records(hk, rel):
    for cwd in (hk.nogit, hk.repo_a, hk.logical):
        r = hk.run(cwd, hk.logical / rel)
        assert not r.blocked, f"{rel} cwd={cwd}: rc={r.rc} {r.out!r} {r.err!r}"


def test_deep_memory_is_not_allowed_everywhere(hk):
    rel = "projects/-zz-test/sub/memory/x.md"
    assert hk.run(hk.nogit, hk.logical / rel).blocked
    assert not hk.run(hk.logical, hk.logical / rel).blocked


def test_symlink_pointing_outside_is_not_allowed(hk, tmp_path):
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    (hk.real / "knowledge").symlink_to(outside)
    assert hk.run(hk.nogit, hk.logical / "knowledge/x.md").blocked


def test_symlinked_core_dir_pointing_outside_is_still_core(hk, tmp_path):
    outside = tmp_path / "outside_scripts"
    outside.mkdir()
    (hk.real / "scripts").symlink_to(outside)
    r = hk.run(hk.logical, hk.logical / "scripts/x.sh")
    assert r.rc == 2 and "매니저 전용" in r.err


def test_symlinked_projects_dir_still_blocks_jsonl_forgery(hk, tmp_path):
    outside = tmp_path / "outside_projects"
    (outside / "p").mkdir(parents=True)
    (hk.real / "projects").symlink_to(outside)
    assert hk.run(hk.logical, hk.logical / "projects/p/abcd.jsonl").blocked


CORE = [
    "CLAUDE.md", "settings.json", "settings.local.json", ".mcp.json",
    "rules/x.md", "rules-lazy/x.md", "agents/x.md", "skills/s/SKILL.md", "scripts/x.sh", "scripts/tests/t.py",
    "tools/t/x.sh", "config/c.json", "hooks/h.sh", "mods/m/x.md", "dev-mods/d/x.md", "intent/i.md",
    "docs/superpowers/plans/p.md", "_audit/history.md", "_bench/b.tsv",
]


@pytest.mark.parametrize("rel", CORE)
def test_core_paths_blocked_for_non_manager_even_in_harness_cwd(hk, rel):
    hk.add_session("o1", OTHER_SID, name="[exp] Manager")
    for cwd in (hk.logical, hk.repo_a, hk.nogit):
        r = hk.run(cwd, hk.logical / rel, sid=OTHER_SID)
        assert r.rc == 2 and "매니저 전용" in r.err and "이름 불일치" in r.err, f"{rel} cwd={cwd}: rc={r.rc} {r.err!r}"
    assert hk.run(hk.logical, hk.real / rel, sid=OTHER_SID).rc == 2


@pytest.mark.parametrize("rel", CORE)
def test_core_paths_allowed_for_manager_in_any_cwd(hk, rel):
    hk.add_session("m1", MGR_SID)
    for cwd in (hk.nogit, hk.repo_a, hk.logical):
        r = hk.run(cwd, hk.logical / rel, sid=MGR_SID)
        assert r.rc == 0 and not r.blocked, f"{rel} cwd={cwd}: rc={r.rc} {r.out!r} {r.err!r}"
        r = hk.run(cwd, hk.real / rel, sid=MGR_SID)
        assert r.rc == 0 and not r.blocked, f"물리 {rel} cwd={cwd}: {r.out!r} {r.err!r}"


def test_core_dotdot_traversal_is_normalized(hk):
    hk.add_session("o1", OTHER_SID, name="x")
    assert hk.run(hk.logical, hk.logical / "knowledge/../rules/x.md", sid=OTHER_SID).rc == 2
    assert hk.run(hk.repo_a, "../home/.claude/rules/x.md", sid=OTHER_SID).rc == 2


def test_reason_no_session_file(hk):
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid="sid-nobody")
    assert r.rc == 2 and "세션 파일 없음" in r.err


def test_reason_no_session_id_in_hook_input(hk):
    hk.add_session("m1", MGR_SID)
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=None)
    assert r.rc == 2 and "세션 파일 없음" in r.err


def test_reason_dead_pid(hk):
    p = subprocess.Popen(["true"])
    p.wait()
    hk.add_session("dead", MGR_SID, pid=p.pid, pstart="123")
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
    assert r.rc == 2 and "pid 없음" in r.err


def test_reason_pid_missing_field(hk):
    (hk.real / "sessions/nopid.json").write_text(json.dumps({"sessionId": MGR_SID, "name": MGR, "procStart": "1"}))
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
    assert r.rc == 2 and "pid 없음" in r.err


def test_reason_proc_start_mismatch(hk):
    hk.add_session("reused", MGR_SID, pstart="1")
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
    assert r.rc == 2 and "procStart 불일치" in r.err


def test_name_must_match_exactly(hk):
    for bad in ("[Harness] Manager ", "[harness] manager", "[Harness] Manager2", "x[Harness] Manager"):
        hk.add_session("n1", MGR_SID, name=bad)
        r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
        assert r.rc == 2 and "이름 불일치" in r.err, bad


@pytest.mark.parametrize("good_first", [True, False])
def test_two_files_same_session_id_one_failing_is_rejected(hk, good_first):
    hk.add_session("a_file" if good_first else "z_file", MGR_SID)
    hk.add_session("z_file" if good_first else "a_file", MGR_SID, pstart="1")
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
    assert r.rc == 2 and "procStart 불일치" in r.err


def test_two_good_files_same_session_id_pass(hk):
    hk.add_session("a_file", MGR_SID)
    hk.add_session("b_file", MGR_SID)
    assert hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID).rc == 0


def test_manager_file_for_other_session_does_not_help(hk):
    hk.add_session("m1", MGR_SID)
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=OTHER_SID)
    assert r.rc == 2 and "세션 파일 없음" in r.err


DEFAULT_DENY = ["README.md", "AGENTS.md", "RULES.md", ".gitignore", "commands/x.md", "graphify-out/g.json",
                "_evolve/other.txt", "brand-new-dir/x.md", "backups/x"]


@pytest.mark.parametrize("rel", DEFAULT_DENY)
def test_default_deny_for_non_manager_and_allowed_for_manager(hk, rel):
    hk.add_session("m1", MGR_SID)
    hk.add_session("o1", OTHER_SID, name="[exp] Manager")
    for cwd in (hk.nogit, hk.repo_a, hk.logical):
        r = hk.run(cwd, hk.logical / rel, sid=MGR_SID)
        assert r.rc == 0 and not r.blocked, f"{rel} cwd={cwd}: {r.out!r} {r.err!r}"
        r = hk.run(cwd, hk.logical / rel, sid=OTHER_SID)
        assert r.rc == 2 and "매니저 전용" in r.err, f"{rel} cwd={cwd}: rc={r.rc} {r.err!r}"


@pytest.mark.parametrize("rel", [".git/hooks/x", ".git/hooks/commit-msg", ".git/config", ".git"])
def test_dot_git_always_blocked_even_for_manager(hk, rel):
    hk.add_session("m1", MGR_SID)
    hk.add_session("o1", OTHER_SID, name="[exp] Manager")
    for sid in (MGR_SID, OTHER_SID):
        for cwd in (hk.nogit, hk.logical):
            assert hk.run(cwd, hk.logical / rel, sid=sid).blocked, f"{rel} sid={sid} cwd={cwd}"


def test_fallthrough_set_stays_on_project_boundary(hk):
    for rel in ("jobs/zz/tmp/x.py", "teams/t/x.json", "daemon/x.log", "daemon.log", "projects/-zz/x.txt"):
        assert not hk.run(hk.logical, hk.logical / rel).blocked, rel
        assert hk.run(hk.repo_a, hk.logical / rel).blocked, rel
        assert hk.run(hk.nogit, hk.logical / rel).blocked, rel


def test_key_files_are_never_read(hk):
    marker = "KEY-FILE-SECRET-MARKER-12345"
    (hk.real / "sessions" / f"{os.getpid()}.deadbeef.key").write_text(marker)
    os.mkfifo(hk.real / "sessions" / "999.cafe.key")
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
    assert r.rc == 2 and "세션 파일 없음" in r.err
    assert marker not in r.out + r.err
    hk.add_session("m1", MGR_SID)
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
    assert r.rc == 0 and marker not in r.out + r.err
    (hk.real / "sessions" / "777.abc.key").write_text(json.dumps({"sessionId": OTHER_SID, "name": MGR}))
    assert hk.run(hk.logical, hk.logical / "rules/x.md", sid=OTHER_SID).rc == 2


def test_fifo_named_json_does_not_hang_and_non_manager_is_blocked(hk):
    os.mkfifo(hk.real / "sessions" / "fifo.json")
    t0 = time.monotonic()
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=OTHER_SID, timeout=5)
    assert time.monotonic() - t0 < 3
    assert r.rc == 2 and "세션 파일 없음" in r.err


def test_fifo_named_json_does_not_block_a_real_manager(hk):
    os.mkfifo(hk.real / "sessions" / "fifo.json")
    hk.add_session("m1", MGR_SID)
    assert hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID, timeout=5).rc == 0


def test_tilde_path_is_expanded_to_home(hk):
    hk.add_session("m1", MGR_SID)
    hk.add_session("o1", OTHER_SID, name="[exp] Manager")
    assert hk.run(hk.nogit, "~/.claude/rules/x.md", sid=OTHER_SID).rc == 2
    assert hk.run(hk.nogit, "~/.claude/rules/x.md", sid=MGR_SID).rc == 0
    assert hk.run(hk.nogit, "~/.claude/sessions/x.json", sid=MGR_SID).blocked
    assert not hk.run(hk.nogit, "~/.claude/knowledge/x.md", sid=OTHER_SID).blocked


def test_malformed_candidate_file_vetoes_manager(hk):
    hk.add_session("a_good", MGR_SID)
    (hk.real / "sessions" / "z_broken.json").write_text(f'{{"sessionId": "{MGR_SID}", "name": ')
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
    assert r.rc == 2 and "파싱 실패" in r.err
    (hk.real / "sessions" / "z_broken.json").write_text("{not json at all")
    assert hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID).rc == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root 는 권한 0 파일도 읽는다")
def test_unreadable_session_file_vetoes_manager(hk):
    hk.add_session("a_good", MGR_SID)
    bad = hk.real / "sessions" / "z_unreadable.json"
    bad.write_text(json.dumps({"sessionId": MGR_SID, "name": MGR}))
    bad.chmod(0)
    try:
        r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
        assert r.rc == 2 and "읽기 실패" in r.err
    finally:
        bad.chmod(0o600)


@pytest.fixture
def nojq_path(tmp_path):
    d = tmp_path / "nojq_bin"
    d.mkdir()
    for tool in ("realpath", "dirname", "head", "cat", "ls", "git"):
        (d / tool).symlink_to(shutil.which(tool))
    assert not (d / "jq").exists()
    return str(d)


def test_without_jq_harness_paths_fail_closed(hk, nojq_path):
    hk.add_session("m1", MGR_SID)
    for rel in ("rules/x.md", "README.md", "CLAUDE.md"):
        r = hk.run(hk.nogit, hk.logical / rel, sid=MGR_SID, path=nojq_path)
        assert r.rc == 2 and "jq 없음" in r.err, rel
    for rel in ("sessions/x.json", "_usage/x", ".git/hooks/x"):
        assert hk.run(hk.nogit, hk.logical / rel, sid=MGR_SID, path=nojq_path).rc == 2, rel


def test_without_jq_allow_list_and_outside_paths_still_pass(hk, nojq_path):
    assert hk.run(hk.nogit, hk.logical / "knowledge/x.md", path=nojq_path).rc == 0
    assert hk.run(hk.nogit, hk.logical / "projects/-zz/memory/x.md", path=nojq_path).rc == 0
    assert hk.run(hk.nogit, hk.logical / f"scope/{OTHER_SID}.json", path=nojq_path).rc == 0
    assert hk.run(hk.repo_a, hk.repo_a / "x.py", path=nojq_path).rc == 0


@pytest.mark.parametrize("rel", ["jobs/x", "teams/x", "daemon-x/y", "projects/-zz/notes.md"])
def test_without_jq_fallthrough_harness_paths_fail_closed(hk, nojq_path, rel):
    r = hk.run(hk.nogit, hk.logical / rel, path=nojq_path)
    assert r.rc == 2 and "jq 없음" in r.err and "경계 판정 불가" in r.err, rel


def test_plans_is_fallthrough_for_non_manager(hk):
    assert not hk.run(hk.logical, hk.logical / "plans/x.md").blocked
    assert hk.run(hk.repo_a, hk.logical / "plans/x.md").blocked
    assert hk.run(hk.logical, hk.logical / "rules/x.md").blocked


def test_with_jq_fallthrough_harness_path_still_uses_project_boundary(hk):
    assert hk.run(hk.repo_a, hk.logical / "jobs/x").rc == 0


def test_missing_session_id_does_not_fall_back_to_latest_scope_file(hk):
    (hk.real / "scope" / f"{OTHER_SID}.json").write_text(json.dumps({"scope": [{"path": str(hk.repo_a / "x.py")}]}))
    r = hk.run(hk.repo_a, hk.repo_a / "x.py", sid=None)
    assert r.rc == 2 and "session_id" in r.err
    assert hk.run(hk.repo_a, hk.repo_a / "x.py", sid="sid-unregistered").rc == 0


@pytest.mark.parametrize("name", [
    "[Harness] Manager\n", "[Harness] Manager\u001f1", "\u001f[Harness] Manager", "[Harness] Manager\u0000",
    "[Harness] Manager\u001f%d\u001f%s",
])
def test_name_with_control_chars_cannot_forge_field_boundaries(hk, name):
    if "%d" in name:
        name = name % (os.getpid(), proc_start(os.getpid()))
        (hk.real / "sessions/forge.json").write_text(json.dumps({"sessionId": MGR_SID, "name": name}))
    else:
        hk.add_session("forge", MGR_SID, name=name)
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
    assert r.rc == 2 and "이름 불일치" in r.err


@pytest.mark.parametrize("patch,why", [
    ({"pid": str(os.getpid())}, "pid 없음"),
    ({"pid": 0}, "pid 없음"),
    ({"procStart": "123\n"}, "pid 없음"),
    ({"procStart": None}, "pid 없음"),
])
def test_pid_and_procstart_types_are_strict(hk, patch, why):
    base = {"pid": os.getpid(), "sessionId": MGR_SID, "name": MGR, "procStart": proc_start(os.getpid())}
    (hk.real / "sessions/x.json").write_text(json.dumps({**base, **patch}))
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
    assert r.rc == 2 and why in r.err


def test_escaped_session_id_in_a_second_file_still_counts(hk):
    hk.add_session("a_good", MGR_SID)
    esc = "\\u0073" + MGR_SID[1:]
    (hk.real / "sessions/z_esc.json").write_text(
        f'{{"sessionId": "{esc}", "name": "{MGR}", "pid": {os.getpid()}, "procStart": "1"}}')
    assert esc not in (hk.real / "sessions/a_good.json").read_text()
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
    assert r.rc == 2 and "procStart 불일치" in r.err


def test_escaped_session_id_alone_is_the_manager_file(hk):
    esc = "\\u0073" + MGR_SID[1:]
    (hk.real / "sessions/only.json").write_text(
        f'{{"sessionId": "{esc}", "name": "{MGR}", "pid": {os.getpid()}, "procStart": "{proc_start(os.getpid())}"}}')
    assert hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID).rc == 0


def test_oversize_session_file_means_undecidable(hk):
    hk.add_session("a_good", MGR_SID)
    big = hk.real / "sessions/z_big.json"
    big.write_text(json.dumps({"sessionId": "other", "pad": "x" * 70000}))
    r = hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID)
    assert r.rc == 2 and "64KB" in r.err
    big.write_text(json.dumps({"sessionId": "other", "pad": "x" * 60000}))
    assert hk.run(hk.logical, hk.logical / "rules/x.md", sid=MGR_SID).rc == 0


def test_without_jq_escaped_or_unparsed_paths_are_blocked(hk, nojq_path):
    esc = f'{{"cwd": "{hk.nogit}", "session_id": "s", "tool_input": {{"file_path": "{hk.home}/.claude/\\u0072ules/x.md"}}}}'
    r = hk.run(hk.nogit, "x", raw=esc, path=nojq_path)
    assert r.rc == 2 and "jq 없음" in r.err
    odd = f'{{"cwd": "{hk.nogit}", "tool_input": {{"file_path": 5}}}}'
    assert hk.run(hk.nogit, "x", raw=odd, path=nojq_path).rc == 2
    plain = f'{{"cwd": "{hk.nogit}", "session_id": "s", "tool_input": {{"file_path": "{hk.home}/.claude/rules/x.md"}}}}'
    assert hk.run(hk.nogit, "x", raw=plain, path=nojq_path).rc == 2


@pytest.mark.parametrize("folder,rel", [
    ("sessions", "x.json"), ("_usage", "bench-last"), ("scope", "other.json"), ("_evolve", "candidates.tsv"), ("_evolve", "t41-ledger.jsonl"),
    ("_audit/publish-approval", "used.tsv"), ("projects", "p/abcd.jsonl"),
])
def test_symlinked_protected_folder_is_protected_by_its_realpath(hk, tmp_path, folder, rel):
    outside = tmp_path / "outside" / folder.replace("/", "_")
    (outside / Path(rel).parent).mkdir(parents=True, exist_ok=True)
    link = hk.real / folder
    if link.exists():
        link.rmdir()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    hk.add_session("m1", MGR_SID)
    for cwd in (hk.nogit, hk.logical):
        assert hk.run(cwd, outside / rel, sid=MGR_SID).blocked, f"실제 위치 {folder}/{rel} cwd={cwd}"
        assert hk.run(cwd, hk.logical / folder / rel, sid=MGR_SID).blocked, f"논리 {folder}/{rel} cwd={cwd}"


@pytest.mark.parametrize("tail", [".json.bak", ".json.tmp", ".json/../x", ".json/x.json", ".bak"])
def test_scope_filename_variants_of_own_session_are_blocked(hk, tail):
    target = f"{hk.logical}/scope/{OTHER_SID}{tail}"
    assert hk.run(hk.nogit, target, sid=OTHER_SID).blocked, target


def _git(path: Path, *args):
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def _repo_with_commit(path: Path):
    git_init(path)
    (path / "f.txt").write_text("f")
    _git(path, "add", "f.txt")
    _git(path, "commit", "-q", "-m", "c")


def test_same_repo_worktree_passes_other_repo_worktree_blocked(hk):
    root = hk.root / "wt_case"
    a, b = root / "A", root / "B"
    w1, w2, wb = root / "W1", root / "W2", root / "WB"
    _repo_with_commit(a)
    _repo_with_commit(b)
    _git(a, "worktree", "add", "-q", str(w1), "-b", "w1")
    _git(a, "worktree", "add", "-q", str(w2), "-b", "w2")
    _git(b, "worktree", "add", "-q", str(wb), "-b", "wb")
    cases = [
        ("A→W1 기존 파일", a, w1 / "f.txt", False),
        ("A→W1 새 파일", a, w1 / "new.txt", False),
        ("A→W1 없는 하위 폴더의 새 파일", a, w1 / "no/such/dir/new.txt", False),
        ("W1→A", w1, a / "f.txt", False),
        ("W1→W2", w1, w2 / "f.txt", False),
        ("A→B", a, b / "f.txt", True),
        ("A→WB", a, wb / "f.txt", True),
        ("W1→B", w1, b / "f.txt", True),
    ]
    bad = []
    for name, cwd, target, want in cases:
        r = hk.run(cwd, target)
        if r.blocked != want:
            bad.append(f"{name}: block={r.blocked} (기대 {want}) out={r.out[:120]!r}")
        if want and "다른 저장소" not in r.out:
            bad.append(f"{name}: 사유에 «다른 저장소» 없음 out={r.out[:120]!r}")
    assert not bad, "\n".join(bad)


def test_git_env_vars_cannot_fool_worktree_check(hk, monkeypatch):
    root = hk.root / "wt_env"
    a, b = root / "A", root / "B"
    _repo_with_commit(a)
    _repo_with_commit(b)
    monkeypatch.setenv("GIT_DIR", str(a / ".git"))
    monkeypatch.setenv("GIT_COMMON_DIR", str(a / ".git"))
    r = hk.run(a, b / "f.txt")
    assert r.blocked and "다른 저장소" in r.out, r.out[:200]


def _wt_world(hk, tag):
    root = hk.root / tag
    a, b = root / "A", root / "B"
    w1, w2, wb = root / "W1", root / "W2", root / "WB"
    _repo_with_commit(a)
    _repo_with_commit(b)
    _git(a, "worktree", "add", "-q", str(w1), "-b", "w1")
    _git(a, "worktree", "add", "-q", str(w2), "-b", "w2")
    _git(b, "worktree", "add", "-q", str(wb), "-b", "wb")
    assert (a / ".git" / "worktrees" / "W1" / "gitdir").is_file()
    assert (b / ".git" / "worktrees" / "WB" / "gitdir").is_file()
    return a, b, w1, w2, wb


def _run_cases(hk, cases):
    bad = []
    for name, cwd, target, want, msg in cases:
        r = hk.run(cwd, target)
        if r.blocked != want:
            bad.append(f"{name}: block={r.blocked} (기대 {want}) out={r.out[:120]!r} err={r.err[:80]!r}")
        elif want and msg and "다른 저장소" not in r.out:
            bad.append(f"{name}: 사유에 «다른 저장소» 없음 out={r.out[:120]!r}")
    return bad


def test_worktree_pass_includes_git_dirs_of_own_repo(hk):
    a, _b, w1, _w2, _wb = _wt_world(hk, "wt_pass")
    gw = a / ".git" / "worktrees" / "W1"
    cases = [
        ("A→A/.git/info/exclude", a, a / ".git" / "info" / "exclude", False, False),
        ("W1→A/.git/worktrees/W1/x", w1, gw / "x", False, False),
        ("A→A/.git/worktrees/W1/x", a, gw / "x", False, False),
        ("A→W1/f.txt", a, w1 / "f.txt", False, False),
    ]
    bad = _run_cases(hk, cases)
    assert not bad, "\n".join(bad)


def test_worktree_pass_with_relative_gitdir_and_no_trailing_newline(hk):
    a, _b, w1, w2, _wb = _wt_world(hk, "wt_rel")
    (w1 / ".git").write_text("gitdir: ../A/.git/worktrees/W1")
    (a / ".git" / "worktrees" / "W1" / "gitdir").write_text("../../../../W1/.git\n")
    cases = [
        ("A→W1", a, w1 / "f.txt", False, False),
        ("W1→A", w1, a / "f.txt", False, False),
        ("W1→W2", w1, w2 / "f.txt", False, False),
    ]
    bad = _run_cases(hk, cases)
    assert not bad, "\n".join(bad)


def test_other_repo_git_dir_and_trees_are_blocked(hk):
    a, b, w1, _w2, wb = _wt_world(hk, "wt_other")
    gb = b / ".git" / "worktrees" / "WB"
    cases = [
        ("A→B/.git/hooks/pre-commit", a, b / ".git" / "hooks" / "pre-commit", True, True),
        ("A→B/.git/config", a, b / ".git" / "config", True, True),
        ("A→B/.git/commondir", a, b / ".git" / "commondir", True, True),
        ("A→B/.git/worktrees/WB/gitdir", a, gb / "gitdir", True, True),
        ("W1→B/.git/hooks/pre-commit", w1, b / ".git" / "hooks" / "pre-commit", True, True),
        ("A→B/.git (그 자체)", a, b / ".git", True, True),
        ("A→B", a, b / "f.txt", True, True),
        ("A→WB", a, wb / "f.txt", True, True),
        ("W1→B", w1, b / "f.txt", True, True),
    ]
    bad = _run_cases(hk, cases)
    assert not bad, "\n".join(bad)


def test_forged_b_commondir_pointing_at_a_cannot_open_b(hk):
    a, b, _w1, _w2, _wb = _wt_world(hk, "wt_forge_b")
    (b / ".git" / "commondir").write_text(f"{a / '.git'}\n")
    bad = _run_cases(hk, [("A→B/x.py", a, b / "x.py", True, True), ("A→B/f.txt", a, b / "f.txt", True, True)])
    assert not bad, "\n".join(bad)


def test_forged_a_commondir_pointing_at_b_cannot_open_b(hk):
    a, b, _w1, _w2, _wb = _wt_world(hk, "wt_forge_a")
    (a / ".git" / "commondir").write_text(f"{b / '.git'}\n")
    bad = _run_cases(hk, [("A→B/x.py", a, b / "x.py", True, False), ("A→B/f.txt", a, b / "f.txt", True, False)])
    assert not bad, "\n".join(bad)


def test_worktree_gitfile_repointed_at_other_repo_worktree_is_rejected(hk):
    _a, b, w1, _w2, _wb = _wt_world(hk, "wt_repoint")
    (w1 / ".git").write_text(f"gitdir: {b / '.git' / 'worktrees' / 'WB'}\n")
    bad = _run_cases(hk, [("W1→B/x.py", w1, b / "x.py", True, False), ("W1→B/f.txt", w1, b / "f.txt", True, False)])
    assert not bad, "\n".join(bad)


def _break_w1_a(a, w1, kind):
    gw = a / ".git" / "worktrees" / "W1"
    if kind == "symlink":
        real = w1.parent / "w1-gitfile.txt"
        real.write_text((w1 / ".git").read_text())
        (w1 / ".git").unlink()
        (w1 / ".git").symlink_to(real)
    elif kind == "no_gitdir_line":
        (w1 / ".git").write_text("not a gitdir line\n")
    elif kind == "no_backpointer":
        (gw / "gitdir").unlink()
    elif kind == "parent_not_worktrees":
        mod = a / ".git" / "modules" / "x"
        mod.parent.mkdir()
        shutil.copytree(gw, mod)
        (w1 / ".git").write_text(f"gitdir: {mod}\n")


@pytest.mark.parametrize("kind", ["symlink", "no_gitdir_line", "no_backpointer", "parent_not_worktrees"])
def test_malformed_worktree_link_is_not_treated_as_same_repo(hk, kind):
    a, _b, w1, _w2, _wb = _wt_world(hk, "wt_bad_" + kind)
    _break_w1_a(a, w1, kind)
    if kind == "no_gitdir_line":
        r = hk.run(w1, a / "f.txt")
        assert r.blocked, f"{kind} W1→A: 통과해 버림 out={r.out[:120]!r}"
        return
    for name, cwd, target in [("A→W1", a, w1 / "f.txt"), ("A→W1 새 파일", a, w1 / "new.txt")]:
        r = hk.run(cwd, target)
        assert r.blocked, f"{kind} {name}: 통과해 버림 out={r.out[:120]!r}"


def _two_repos(hk, tag):
    root = hk.root / tag
    a, b = root / "A", root / "B"
    git_init(a)
    git_init(b)
    return root, a, b


def test_core_worktree_in_config_cannot_move_the_session_root(hk):
    _root, a, b = _two_repos(hk, "rw_core")
    with (a / ".git" / "config").open("a") as f:
        f.write(f"[core]\n\tworktree = {b}\n")
    bad = _run_cases(hk, [("cwd=A→B/x.py", a, b / "x.py", True, True), ("cwd=A→A/own.py", a, a / "own.py", False, False)])
    assert not bad, "\n".join(bad)


def test_worktree_gitfile_redirected_to_fake_gitdir_cannot_open_other_repo(hk):
    a, b, w1, _w2, _wb = _wt_world(hk, "rw_fakegit")
    fake = w1.parent / "fakegit"
    fake.mkdir()
    (fake / "HEAD").write_text("ref: refs/heads/x\n")
    (fake / "commondir").write_text(f"{a / '.git'}\n")
    (fake / "config").write_text(f"[core]\n\tworktree = {b}\n")
    (w1 / ".git").write_text(f"gitdir: {fake}\n")
    bad = _run_cases(hk, [("cwd=W1→B/x.py", w1, b / "x.py", True, True), ("cwd=W1→B/f.txt", w1, b / "f.txt", True, True)])
    assert not bad, "\n".join(bad)


def test_empty_shell_dot_git_above_is_not_a_root_and_cannot_be_filled(hk):
    root, a, b = _two_repos(hk, "rw_shell")
    (root / ".git" / "info").mkdir(parents=True)
    plain = root / "plainsub"
    plain.mkdir()
    (a / "x.py").write_text("a")
    shell = root / ".git"
    cases = [
        ("cwd=A→B/x.py", a, b / "x.py", True, True),
        ("cwd=plainsub→A/x.py (껍데기를 뿌리로 치면 통과해 버린다)", plain, a / "x.py", True, False),
        ("cwd=A→P/.git/HEAD", a, shell / "HEAD", True, True),
        ("cwd=A→P/.git/objects/x", a, shell / "objects" / "x", True, True),
        ("cwd=A→P/.git/refs/x", a, shell / "refs" / "x", True, True),
    ]
    bad = _run_cases(hk, cases)
    r = hk.run(plain, a / "x.py")
    if "저장소 밖" not in r.out:
        bad.append(f"cwd=plainsub→A/x.py: 사유에 «저장소 밖» 없음 out={r.out[:120]!r}")
    assert not bad, "\n".join(bad)


def test_dot_git_inside_non_repo_folder_is_blocked_but_plain_file_passes(hk):
    root, a, _b = _two_repos(hk, "rw_nonrepo")
    n = root / "N"
    n.mkdir()
    cases = [
        ("cwd=A→N/.git/HEAD", a, n / ".git" / "HEAD", True, True),
        ("cwd=A→N/plain.txt", a, n / "plain.txt", False, False),
    ]
    bad = _run_cases(hk, cases)
    assert not bad, "\n".join(bad)


def test_own_repo_dot_git_and_nested_repo_creation_pass(hk):
    _root, a, _b = _two_repos(hk, "rw_own")
    (a / "sub").mkdir()
    cases = [
        ("cwd=A→A/sub/.git/HEAD", a, a / "sub" / ".git" / "HEAD", False, False),
        ("cwd=A→A/.git/config", a, a / ".git" / "config", False, False),
    ]
    bad = _run_cases(hk, cases)
    assert not bad, "\n".join(bad)


def test_dot_git_file_without_gitdir_line_is_not_a_root(hk):
    _root, a, _b = _two_repos(hk, "rw_nogitdir")
    fake = a / "fake"
    fake.mkdir()
    (fake / ".git").write_text("not a gitdir line\n")
    (a / "f.txt").write_text("f")
    cases = [
        ("cwd=A→A/fake/x.py", a, fake / "x.py", False, False),
        ("cwd=A/fake→A/f.txt", fake, a / "f.txt", False, False),
    ]
    bad = _run_cases(hk, cases)
    assert not bad, "\n".join(bad)


def test_symlinked_gitdir_file_still_marks_a_root_but_is_never_same_repo(hk):
    a, _b, _w1, _w2, wb = _wt_world(hk, "rw_symgit")
    real = wb.parent / "wb-gitfile.txt"
    real.write_text((wb / ".git").read_text())
    (wb / ".git").unlink()
    (wb / ".git").symlink_to(real)
    cases = [
        ("cwd=A→WB/f.txt", a, wb / "f.txt", True, True),
        ("cwd=A→WB/new.txt", a, wb / "new.txt", True, True),
        ("cwd=WB→WB/own.py", wb, wb / "own.py", False, False),
        ("cwd=WB→A/f.txt", wb, a / "f.txt", True, True),
    ]
    bad = _run_cases(hk, cases)
    assert not bad, "\n".join(bad)


def test_git_env_vars_pointing_at_b_cannot_move_the_root(hk, monkeypatch):
    _root, a, b = _two_repos(hk, "rw_env")
    monkeypatch.setenv("GIT_DIR", str(b / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(b))
    monkeypatch.setenv("GIT_COMMON_DIR", str(b / ".git"))
    bad = _run_cases(hk, [("cwd=A→B/x.py", a, b / "x.py", True, True), ("cwd=A→A/own.py", a, a / "own.py", False, False)])
    assert not bad, "\n".join(bad)


def test_non_repo_cwd_under_allow_list_cannot_write_dot_git_markers(hk):
    allowed, denied = hk.root / "rw_allowed", hk.root / "rw_denied"
    d = allowed / "proj"
    d.mkdir(parents=True)
    denied.mkdir()
    allow = hk.root / "rw-scope-allow.txt"
    allow.write_text(f"{allowed}\n")
    cases = [
        ("D/.git", d / ".git", True),
        ("D/.git/HEAD", d / ".git" / "HEAD", True),
        ("D/.git/objects/x", d / ".git" / "objects" / "x", True),
        ("D/.git/refs/x", d / ".git" / "refs" / "x", True),
        ("상위 폴더의 .git", allowed / ".git", True),
        ("D/ok.txt", d / "ok.txt", False),
        ("D/.gitignore", d / ".gitignore", False),
        ("D/.github/x", d / ".github" / "x", False),
        ("허용 목록 밖 일반 파일", denied / "x.py", True),
    ]
    bad = []
    for name, target, want in cases:
        r = hk.run(d, target, allow=allow)
        if r.blocked != want:
            bad.append(f"{name}: block={r.blocked} (기대 {want}) out={r.out[:120]!r}")
        elif want and name != "허용 목록 밖 일반 파일" and "git 저장소 밖" not in r.out:
            bad.append(f"{name}: 사유에 «git 저장소 밖» 없음 out={r.out[:120]!r}")
    assert not bad, "\n".join(bad)
