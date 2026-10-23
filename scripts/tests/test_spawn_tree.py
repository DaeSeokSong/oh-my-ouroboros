"""spawn-tree.sh 검사 면제 회귀 테스트 (SPAWN_TREE_HOME 임시 폴더 — 실제 하네스·transcript 는 건드리지 않는다).

실행: uv run --with pytest python -m pytest scripts/tests/test_spawn_tree.py -q
규칙 문면(스크립트 머리 주석): 검사 면제에 이름 glob 을 쓰지 않는다 — 면제는 하네스 홈 고정 접두뿐이다.
"""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "spawn-tree.sh"


@pytest.fixture
def st(tmp_path):
    home = tmp_path / "home"
    (home / "projects").mkdir(parents=True)
    (home / "keep.txt").write_text("x")
    env = {**os.environ, "SPAWN_TREE_HOME": str(home)}
    tree = tmp_path / "tree" / ".spawn-tree-t"
    tree.parent.mkdir()

    def sh(*a):
        return subprocess.run(["bash", str(SCRIPT), *a], env=env, capture_output=True, text=True)

    assert sh("snapshot", str(tree), str(home)).returncode == 0
    return type("S", (), {"home": home, "check": staticmethod(lambda: sh("check", str(tree)))})


def test_harness_home_runtime_paths_stay_exempt(st):
    p = st.home / "jobs/j1/tmp"
    p.mkdir(parents=True)
    (p / "scratch.txt").write_text("에이전트 스크래치")
    r = st.check()
    assert r.returncode == 0 and "RESULT: PASS" in r.stdout, r.stdout


def test_same_named_folder_at_other_depth_is_not_exempt(st):
    p = st.home / "notes/jobs/j1/tmp"       # 하네스 홈의 jobs 가 아니라 임의 깊이의 같은 이름 폴더
    p.mkdir(parents=True)
    (p / "dropper.sh").write_text("#!/bin/sh\n")
    r = st.check()
    assert r.returncode == 1 and "dropper.sh" in r.stdout   # 수정 전에는 이름 glob 에 걸려 PASS 였다
