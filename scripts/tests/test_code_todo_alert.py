"""Tests for the CODE_TODO_OPEN alert of scripts/harness-usage-check.sh (knowledge/harness/code-todo.md, 2026-11-24).

Run: uv run --no-project --with pytest python -m pytest scripts/tests/test_code_todo_alert.py -q -p no:cacheprovider
Each case builds a throwaway HOME whose .claude is a git repository holding a copy of the script.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
HEAD = (
    "---\ntitle: t\n---\n\n"
    "| id | 적은 날 | 위치(파일과 함수) | 할 일 | 상태(open · done) | 닫은 날과 커밋 |\n"
    "|---|---|---|---|---|---|\n"
)


@pytest.fixture
def harness(tmp_path):
    home = tmp_path / "home"
    claude = home / ".claude"
    (claude / "scripts").mkdir(parents=True)
    shutil.copy(
        SCRIPTS / "harness-usage-check.sh", claude / "scripts/harness-usage-check.sh"
    )
    subprocess.run(["git", "init", "-q", str(claude)], check=True)
    (claude / "_usage/articles-watch").mkdir(parents=True)
    (claude / "_usage/articles-watch/last-check.json").write_text("{}\n")
    (claude / "knowledge/harness").mkdir(parents=True)
    elsewhere = tmp_path / "proj"
    elsewhere.mkdir()
    return home, claude, elsewhere


def alert(home, cwd):
    r = subprocess.run(
        ["bash", str(home / ".claude/scripts/harness-usage-check.sh")],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
        cwd=str(cwd),
        timeout=120,
        check=False,
    )
    return [ln for ln in r.stdout.splitlines() if "CODE_TODO_OPEN" in ln]


def put(claude, rows):
    (claude / "knowledge/harness/code-todo.md").write_text(
        HEAD + "".join(rows), encoding="utf-8"
    )


def test_no_open_rows_is_quiet(harness):
    home, claude, _ = harness
    put(claude, ["| CT-001 | 2026-11-20 | a.sh f | x | done | 2026-11-21 abc |\n"])
    assert alert(home, claude) == []
    put(claude, [])
    assert alert(home, claude) == []


def test_one_open_row(harness):
    home, claude, _ = harness
    put(claude, ["| CT-001 | 2026-11-20 | a.sh f | secret words | open | |\n"])
    assert alert(home, claude) == [
        "⚠ CODE_TODO_OPEN: 1건(가장 오래된 것 2026-11-20) → knowledge/harness/code-todo.md"
    ]


def test_many_open_rows_report_oldest(harness):
    home, claude, _ = harness
    put(
        claude,
        [
            "| CT-001 | 2026-11-22 | a.sh | x | open | |\n",
            "| CT-002 | 2026-10-05 | b.py | y \\| z | open | |\n",
            "| CT-003 | 2026-09-01 | c.js | w | done | 2026-09-02 def |\n",
            "| CT-004 | 2026-11-01 | d.sh | v | open | |\n",
        ],
    )
    assert alert(home, claude) == [
        "⚠ CODE_TODO_OPEN: 3건(가장 오래된 것 2026-10-05) → knowledge/harness/code-todo.md"
    ]


def test_broken_date_counts_without_date(harness):
    home, claude, _ = harness
    put(claude, ["| CT-001 | 지난주 `rm -rf` | a.sh | x | open | |\n"])
    assert alert(home, claude) == [
        "⚠ CODE_TODO_OPEN: 1건 → knowledge/harness/code-todo.md"
    ]
    put(
        claude,
        [
            "| CT-001 | 2026-1-5 | a.sh | x | open | |\n",
            "| CT-002 | 2026-11-23 | b | y | open | |\n",
        ],
    )
    assert alert(home, claude) == [
        "⚠ CODE_TODO_OPEN: 2건(가장 오래된 것 2026-11-23) → knowledge/harness/code-todo.md"
    ]


def test_missing_file_is_quiet(harness):
    home, claude, _ = harness
    assert alert(home, claude) == []


def test_other_repository_cwd_is_quiet(harness, tmp_path):
    home, claude, elsewhere = harness
    put(claude, ["| CT-001 | 2026-11-20 | a.sh | x | open | |\n"])
    assert alert(home, elsewhere) == []
    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    assert alert(home, other) == []


def test_symlinked_file_is_not_read(harness, tmp_path):
    home, claude, _ = harness
    target = tmp_path / "t.md"
    target.write_text(
        HEAD + "| CT-001 | 2026-11-20 | a | x | open | |\n", encoding="utf-8"
    )
    (claude / "knowledge/harness/code-todo.md").symlink_to(target)
    assert alert(home, claude) == []


TAIL = " → knowledge/harness/code-todo.md"


@pytest.mark.parametrize(
    "row",
    [
        "| CT-001 | 2026-11-20 | a.sh | x | open |\n",
        "| CT-001 | 2026-11-20 | a.sh | x | open | closed later\n",
        "| CT-001 | 2026-11-20 | a.sh | x | open | 2026 | abc |\n",
        "| CT-001 | 2026-11-20 | a.sh | x \\| y | z | open | |\n",
    ],
)
def test_status_found_from_the_right(harness, row):
    home, claude, _ = harness
    put(claude, [row])
    assert alert(home, claude) == [
        f"⚠ CODE_TODO_OPEN: 1건(가장 오래된 것 2026-11-20){TAIL}"
    ]


def test_open_inside_todo_text_with_done_status_is_not_counted(harness):
    home, claude, _ = harness
    put(claude, ["| CT-001 | 2026-11-20 | a.sh | open | done | 2026-11-21 abc |\n"])
    assert alert(home, claude) == []


def test_bad_status_rows_are_format_errors(harness):
    home, claude, _ = harness
    put(
        claude,
        [
            "| CT-001 | 2026-11-20 | a | x | Open | |\n",
            "| CT-002 | 2026-11-21 | b | y | open(보류) | |\n",
        ],
    )
    assert alert(home, claude) == [f"⚠ CODE_TODO_OPEN: 0건 · 형식 오류 2행{TAIL}"]
    put(
        claude,
        [
            "| CT-001 | 2026-11-20 | a | x | Open | |\n",
            "| CT-002 | 2026-11-19 | b | y | open | |\n",
        ],
    )
    assert alert(home, claude) == [
        f"⚠ CODE_TODO_OPEN: 1건(가장 오래된 것 2026-11-19) · 형식 오류 1행{TAIL}"
    ]


def test_rows_without_ct_id_are_ignored(harness):
    home, claude, _ = harness
    put(claude, ["| note | 2026-11-20 | a | x | open | |\n"])
    assert alert(home, claude) == []
