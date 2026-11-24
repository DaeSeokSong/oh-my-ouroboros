"""Tests for the PROPAGATE_HELD alert of scripts/harness-usage-check.sh (intent/2026-10-21-harness-change-propagation-gate.md 개정 3).

Run: uv run --no-project --with pytest python -m pytest scripts/tests/test_propagate_held_alert.py -q -p no:cacheprovider
Each case builds a throwaway HOME whose .claude is a git repository holding copies of harness-usage-check.sh and propagate-queue.sh.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
SID = "11111111-1111-4111-8111-111111111111"
TAIL = " → 작업이 다 끝났으면 bash scripts/propagate-queue.sh release"


@pytest.fixture
def harness(tmp_path):
    home = tmp_path / "home"
    claude = home / ".claude"
    (claude / "scripts").mkdir(parents=True)
    for name in ("harness-usage-check.sh", "propagate-queue.sh"):
        shutil.copy(SCRIPTS / name, claude / "scripts" / name)
    subprocess.run(["git", "init", "-q", str(claude)], check=True)
    (claude / "_usage/articles-watch").mkdir(parents=True)
    (claude / "_usage/articles-watch/last-check.json").write_text("{}\n")
    (claude / "_usage/propagate").mkdir(parents=True)
    return home, claude


def alert(home, cwd):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PROPAGATE_")}
    r = subprocess.run(
        ["bash", str(home / ".claude/scripts/harness-usage-check.sh")],
        capture_output=True,
        text=True,
        env={**env, "HOME": str(home)},
        cwd=str(cwd),
        timeout=120,
        check=False,
    )
    return [ln for ln in r.stdout.splitlines() if "PROPAGATE_HELD" in ln]


def line(ts, subject="feat: secret words"):
    return json.dumps({"ts": ts, "hash": "abcdef123", "subject": subject, "author": SID}) + "\n"


def stamp(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def test_no_held_file_is_quiet(harness):
    home, claude = harness
    assert alert(home, claude) == []


def test_empty_held_file_is_quiet(harness):
    home, claude = harness
    (claude / "_usage/propagate/held.jsonl").write_text("")
    assert alert(home, claude) == []


def test_many_held_lines_report_count_and_oldest(harness):
    home, claude = harness
    now = int(time.time())
    (claude / "_usage/propagate/held.jsonl").write_text(line(now - 60) + line(now - 7200) + line(now))
    out = alert(home, claude)
    assert out == [f"⚠ PROPAGATE_HELD: 3건(가장 오래된 것 {stamp(now - 7200)}){TAIL}"]
    assert "secret" not in out[0] and SID not in out[0]


def test_one_held_line(harness):
    home, claude = harness
    now = int(time.time())
    (claude / "_usage/propagate/held.jsonl").write_text(line(now))
    assert alert(home, claude) == [f"⚠ PROPAGATE_HELD: 1건(가장 오래된 것 {stamp(now)}){TAIL}"]


def test_symlinked_held_file_is_not_read(harness, tmp_path):
    home, claude = harness
    target = tmp_path / "t.jsonl"
    target.write_text(line(int(time.time())))
    (claude / "_usage/propagate/held.jsonl").symlink_to(target)
    assert alert(home, claude) == []


def test_other_repository_cwd_is_quiet(harness, tmp_path):
    home, claude = harness
    (claude / "_usage/propagate/held.jsonl").write_text(line(int(time.time())))
    elsewhere = tmp_path / "proj"
    elsewhere.mkdir()
    assert alert(home, elsewhere) == []
    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    assert alert(home, other) == []
