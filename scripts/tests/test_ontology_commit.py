"""ontology-commit.sh 시험 (2026-11-24): 임시 저장소에서 미리보기 · 종료 코드 · 정상 경로를 확인한다.
REF: knowledge/harness/code-history/scripts__tests__test_ontology_commit.py.md
"""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "ontology-commit.sh"
BASE_ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
    GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=BASE_ENV, check=True).stdout


def make_repo(tmp_path, staged=True, msg="chore(ontology): test commit"):
    repo = tmp_path / "repo"
    (repo / "graphify-out").mkdir(parents=True)
    (repo / "knowledge").mkdir()
    git(repo, "init", "-q")
    (repo / ".gitignore").write_text("graphify-out/.commit-msg\n")
    (repo / "graphify-out/a.md").write_text("a\n")
    (repo / "graphify-out/b.md").write_text("b\n")
    (repo / "knowledge/k.md").write_text("k\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    (repo / "graphify-out/a.md").write_text("a2\n")
    (repo / "graphify-out/c.md").write_text("c\n")
    (repo / "knowledge/k.md").write_text("k2\n")
    (repo / "knowledge/new.md").write_text("n\n")
    if staged:
        git(repo, "add", "graphify-out/")
    if msg is not None:
        (repo / "graphify-out/.commit-msg").write_text(msg + "\n" if msg else "")
    stub = tmp_path / "oversight_stub.sh"
    stub.write_text('#!/usr/bin/env bash\nprintf "%s|" "$@" > "$STUB_LOG"\n')
    return repo, stub, tmp_path / "stub.log"


def run(repo, stub, log, *args):
    env = dict(BASE_ENV, ONTOLOGY_COMMIT_TEST="1", ONTOLOGY_COMMIT_REPO=str(repo), ONTOLOGY_COMMIT_OVERSIGHT=str(stub), STUB_LOG=str(log))
    return subprocess.run(["bash", str(SCRIPT), *args], check=False, capture_output=True, text=True, env=env)


def snapshot(repo):
    return git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain"), git(repo, "diff", "--cached", "--name-status")


def test_preview_changes_nothing(tmp_path):
    repo, stub, log = make_repo(tmp_path)
    before = snapshot(repo)
    r = run(repo, stub, log)
    assert r.returncode == 0
    assert "수정 1" in r.stdout and "추가 1" in r.stdout
    assert "chore(ontology): test commit" in r.stdout
    assert "knowledge/new.md" in r.stdout and "knowledge/k.md" in r.stdout
    assert "index.lock" in r.stdout
    assert snapshot(repo) == before and not log.exists()


def test_apply_without_reason_exits_2(tmp_path):
    repo, stub, log = make_repo(tmp_path)
    before = snapshot(repo)
    assert run(repo, stub, log, "--apply").returncode == 2
    assert snapshot(repo) == before


def test_lock_exits_3(tmp_path):
    repo, stub, log = make_repo(tmp_path)
    (repo / ".git/index.lock").write_text("")
    before_head = git(repo, "rev-parse", "HEAD")
    assert run(repo, stub, log, "--apply", "--reason", "r").returncode == 3
    assert git(repo, "rev-parse", "HEAD") == before_head


def test_missing_or_empty_message_exits_4(tmp_path):
    repo, stub, log = make_repo(tmp_path, msg=None)
    assert run(repo, stub, log, "--apply", "--reason", "r").returncode == 4
    (repo / "graphify-out/.commit-msg").write_text("")
    assert run(repo, stub, log, "--apply", "--reason", "r").returncode == 4


def test_no_staged_changes_exits_0_without_commit(tmp_path):
    repo, stub, log = make_repo(tmp_path, staged=False)
    before_head = git(repo, "rev-parse", "HEAD")
    r = run(repo, stub, log, "--apply", "--reason", "r")
    assert r.returncode == 0 and "커밋할 것 없음" in r.stdout
    assert git(repo, "rev-parse", "HEAD") == before_head and not log.exists()


def test_apply_commits_graphify_only_and_signs(tmp_path):
    repo, stub, log = make_repo(tmp_path)
    git(repo, "add", "knowledge/k.md")
    n_before = int(git(repo, "rev-list", "--count", "HEAD"))
    r = run(repo, stub, log, "--apply", "--reason", "온톨로지 변경사항 커밋")
    assert r.returncode == 0, r.stderr
    assert int(git(repo, "rev-list", "--count", "HEAD")) == n_before + 1
    assert set(git(repo, "show", "--name-only", "--format=", "HEAD").split()) == {"graphify-out/a.md", "graphify-out/c.md"}
    assert git(repo, "log", "-1", "--format=%s") == "chore(ontology): test commit\n"
    status = git(repo, "status", "--porcelain")
    assert "knowledge/k.md" in status and "knowledge/new.md" in status and "graphify-out" not in status
    head7 = git(repo, "rev-parse", "--short=7", "HEAD").strip()
    assert log.read_text() == f"commit|{head7} 온톨로지 자동 추출분|온톨로지 변경사항 커밋|main|"
    assert "따로 커밋" in r.stdout


def test_env_without_test_marker_exits_2(tmp_path):
    repo, _stub, _log = make_repo(tmp_path)
    before = snapshot(repo)
    for var in ("ONTOLOGY_COMMIT_REPO", "ONTOLOGY_COMMIT_OVERSIGHT"):
        env = dict(BASE_ENV, **{var: str(repo)})
        r = subprocess.run(["bash", str(SCRIPT), "--apply", "--reason", "r"], check=False, capture_output=True, text=True, env=env)
        assert r.returncode == 2 and "ONTOLOGY_COMMIT_TEST" in r.stderr
    assert snapshot(repo) == before


def test_signing_failure_exits_5_after_commit_and_runs_in_repo(tmp_path):
    repo, stub, log = make_repo(tmp_path)
    stub.write_text('#!/usr/bin/env bash\npwd -P > "$STUB_LOG"\nexit 1\n')
    n_before = int(git(repo, "rev-list", "--count", "HEAD"))
    r = run(repo, stub, log, "--apply", "--reason", "r")
    assert r.returncode == 5
    assert int(git(repo, "rev-list", "--count", "HEAD")) == n_before + 1
    assert log.read_text().strip() == str(repo.resolve())


def test_unstaged_change_after_staging_exits_6_without_commit(tmp_path):
    repo, stub, log = make_repo(tmp_path)
    (repo / "graphify-out/a.md").write_text("a3\n")
    before_head = git(repo, "rev-parse", "HEAD")
    r = run(repo, stub, log, "--apply", "--reason", "r")
    assert r.returncode == 6 and "스테이징 뒤 바뀐 파일 1건" in r.stderr
    assert git(repo, "rev-parse", "HEAD") == before_head and not log.exists()
    assert "스테이징 뒤 바뀐 graphify-out/ 추적 파일: 1건" in run(repo, stub, log).stdout


def test_symlinked_message_file_exits_4_without_leaking_target(tmp_path):
    repo, stub, log = make_repo(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("TOP-SECRET-CONTENT\n")
    (repo / "graphify-out/.commit-msg").unlink()
    (repo / "graphify-out/.commit-msg").symlink_to(target)
    for args in ((), ("--apply", "--reason", "r")):
        r = run(repo, stub, log, *args)
        assert r.returncode == 4
        assert "TOP-SECRET-CONTENT" not in r.stdout + r.stderr
    assert not log.exists()
