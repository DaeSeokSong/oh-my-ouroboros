"""audit-history-autocommit.sh 시험: 덧붙임만 임시 저장소에서 자동 커밋, 그 밖은 건너뜀.

REF: knowledge/harness/code-history/scripts__tests__test_audit_history_autocommit.py.md
"""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "audit-history-autocommit.sh"
ENV = dict(
    os.environ,
    GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
    GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=ENV, check=True).stdout


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "_audit").mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "_audit/history.md").write_text("a\nb\n")
    (repo / "other.txt").write_text("x\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def run(repo):
    r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=dict(ENV, AUDIT_REPO=str(repo)), check=False)
    assert r.returncode == 0 and r.stdout == ""


def count(repo):
    return int(git(repo, "rev-list", "--count", "HEAD").strip())


def test_append_only_commits_without_other_staged(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "_audit/history.md").write_text("a\nb\nc\n")
    (repo / "other.txt").write_text("y\n")
    git(repo, "add", "other.txt")
    run(repo)
    assert count(repo) == 2
    assert git(repo, "show", "--name-only", "--format=%s", "HEAD").split() == ["chore:", "Record", "audit", "history", "lines", "_audit/history.md"]
    assert git(repo, "diff", "--cached", "--name-only").split() == ["other.txt"]
    assert not (repo / "_usage/audit-autocommit.lock").exists()


def test_deleted_line_skips(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "_audit/history.md").write_text("a\nB\nc\n")
    run(repo)
    assert count(repo) == 1


def test_index_lock_skips(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "_audit/history.md").write_text("a\nb\nc\n")
    (repo / ".git/index.lock").write_text("")
    run(repo)
    assert count(repo) == 1


def test_no_change_skips(tmp_path):
    repo = make_repo(tmp_path)
    run(repo)
    assert count(repo) == 1


def test_lock_dir_contention_skips(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "_audit/history.md").write_text("a\nb\nc\n")
    (repo / "_usage/audit-autocommit.lock").mkdir(parents=True)
    run(repo)
    assert count(repo) == 1
    assert (repo / "_usage/audit-autocommit.lock").exists()


def test_staged_differs_from_worktree_skips(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "_audit/history.md").write_text("a\nb\nc\n")
    git(repo, "add", "_audit/history.md")
    (repo / "_audit/history.md").write_text("a\nb\nc\nd\n")
    run(repo)
    assert count(repo) == 1


def test_rebase_in_progress_skips(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "_audit/history.md").write_text("a\nb\nc\n")
    (repo / ".git/rebase-merge").mkdir()
    run(repo)
    assert count(repo) == 1
