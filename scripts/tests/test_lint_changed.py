"""Tests for scripts/lint_changed.py (intent/2026-11-24-harness-review-six-items.md W17).

Run: uv run --no-project --with pytest python -m pytest scripts/tests/test_lint_changed.py -q -p no:cacheprovider
Git cases build throwaway repositories under pytest tmp_path. Cases that need ruff or shellcheck skip when the tool is missing.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

LINTER = Path(__file__).resolve().parents[1] / "lint_changed.py"
ENV = dict(
    os.environ,
    GIT_CONFIG_GLOBAL="/dev/null",
    GIT_CONFIG_SYSTEM="/dev/null",
    GIT_AUTHOR_NAME="t",
    GIT_AUTHOR_EMAIL="t@t",
    GIT_COMMITTER_NAME="t",
    GIT_COMMITTER_EMAIL="t@t",
)
needs_ruff = pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff 없음")
needs_shellcheck = pytest.mark.skipif(
    shutil.which("shellcheck") is None, reason="shellcheck 없음"
)


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=ENV)


def make_repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    for name, body in files.items():
        (repo / name).write_text(body, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def lint(cwd, *files, env=ENV):
    r = subprocess.run(
        [sys.executable, "-I", str(LINTER), *files],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return r.returncode, r.stdout + r.stderr


@needs_ruff
def test_py_reports_only_changed_lines(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "import os\n# old plain\nx = 1\n"})
    (repo / "a.py").write_text(
        "import os\n# old plain\nx = 1\nimport sys\ny = 2  # new plain\n",
        encoding="utf-8",
    )
    rc, out = lint(repo, "a.py")
    assert rc == 1
    assert "a.py:4: [ruff F401]" in out
    assert "a.py:5: [no-tag]" in out
    assert "a.py:1:" not in out
    assert "a.py:2:" not in out
    assert out.rstrip().endswith("RESULT: FAIL (3건)")


@needs_ruff
def test_untracked_file_is_checked_whole(tmp_path):
    repo = make_repo(tmp_path, {"base.txt": "x\n"})
    (repo / "new.py").write_text("import os\n", encoding="utf-8")
    rc, out = lint(repo, "new.py")
    assert rc == 1
    assert "new.py:1: [ruff F401]" in out


@needs_ruff
def test_file_outside_any_repo_is_checked_whole(tmp_path):
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")
    rc, out = lint(tmp_path, str(tmp_path / "a.py"))
    assert rc == 1
    assert "[ruff F401]" in out


@needs_ruff
def test_syntax_error_always_reported(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x = 1\ny = 2\n"})
    (repo / "a.py").write_text("x = (1,\ny = 2\n", encoding="utf-8")
    rc, out = lint(repo, "a.py")
    assert rc == 1
    assert "[ruff invalid-syntax]" in out or "[ruff SyntaxError]" in out


@needs_shellcheck
def test_sh_bash_n_and_shellcheck_on_changed_lines(tmp_path):
    repo = make_repo(tmp_path, {"a.sh": "#!/bin/bash\nOLD=1\n"})
    (repo / "a.sh").write_text("#!/bin/bash\nOLD=1\nNEW=2\n", encoding="utf-8")
    rc, out = lint(repo, "a.sh")
    assert rc == 1
    assert "a.sh:3: [shellcheck SC2034]" in out
    assert "a.sh:2:" not in out
    (repo / "a.sh").write_text("#!/bin/bash\nOLD=1\nif true; then\n", encoding="utf-8")
    rc, out = lint(repo, "a.sh")
    assert rc == 1
    assert "[bash -n]" in out


def test_shellcheck_missing_prints_note(tmp_path):
    repo = make_repo(tmp_path, {"base.txt": "x\n"})
    (repo / "a.sh").write_text("#!/bin/bash\necho 1\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("git", "bash"):
        (bin_dir / tool).symlink_to(shutil.which(tool))
    rc, out = lint(repo, "a.sh", env=dict(ENV, PATH=str(bin_dir)))
    assert rc == 0
    assert "shellcheck 없음" in out
    assert out.rstrip().endswith("RESULT: PASS (건너뜀: shellcheck)")
    (repo / "b.py").write_text("x = 1\n", encoding="utf-8")
    rc, out = lint(repo, "a.sh", "b.py", env=dict(ENV, PATH=str(bin_dir)))
    assert rc == 0
    assert out.rstrip().endswith("RESULT: PASS (건너뜀: ruff, shellcheck)")


@needs_ruff
def test_read_only(tmp_path):
    repo = make_repo(tmp_path, {"base.txt": "x\n"})
    target = repo / "a.py"
    target.write_text("import os,sys\nx=1\n", encoding="utf-8")
    before = (target.read_bytes(), target.stat().st_mtime_ns)
    lint(repo, "a.py")
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    assert not (repo / ".ruff_cache").exists()


def test_clean_and_error_exit_codes(tmp_path):
    repo = make_repo(tmp_path, {"base.txt": "x\n"})
    (repo / "a.js").write_text("foo(); // REF: https://example.com\n", encoding="utf-8")
    (repo / "notes.md").write_text("# plain\n", encoding="utf-8")
    assert lint(repo, "a.js", "notes.md") == (0, "RESULT: PASS\n")
    rc, out = lint(repo, "missing.py")
    assert rc == 2
    assert "RESULT: ERROR (1건)" in out
    assert lint(repo)[0] == 2


HOSTILE = "\x1b\x07" + chr(0x85) + chr(0x202E) + chr(0x2066) + chr(0x200F)


@pytest.mark.parametrize(
    ("name", "body"),
    [("n\x1b\x07.py", "import os\n"), ("n\x1b\x07.sh", "#!/bin/bash\nX=1\n")],
)
def test_output_masks_c0_c1_and_bidi(tmp_path, name, body):
    (tmp_path / name).write_text(f"{body}# plain {HOSTILE}\n", encoding="utf-8")
    rc, out = lint(tmp_path, name)
    assert rc == 1
    assert "[no-tag]" in out
    assert not any(ch in out for ch in HOSTILE)
