"""harness_registry.py regression tests (temporary registry folders, values are fake).

Run: uv run --with pytest python -m pytest scripts/tests/test_harness_registry.py -q
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import harness_registry as hr

TOOL = SCRIPTS / "harness_registry.py"


@pytest.fixture
def root(tmp_path):
    (tmp_path / "config/hosts").mkdir(parents=True)
    (tmp_path / "config/projects").mkdir(parents=True)
    (tmp_path / "config/hosts/box1.json").write_text(json.dumps({"grp": {"n": 32, "s": "8-19", "l": [1, 2]}}))
    (tmp_path / "config/projects/proj1.json").write_text(json.dumps({"issue_prefix": "ABC"}))
    return tmp_path


def cli(*args):
    return subprocess.run([sys.executable, "-I", str(TOOL), *args], check=False, capture_output=True, text=True)


def test_value_present(root):
    assert hr.lookup("host", "grp.n", "box1", root=root) == 32
    assert hr.lookup("host", "grp.s", "box1", root=root) == "8-19"
    assert hr.lookup("project", "issue_prefix", "proj1", root=root) == "ABC"


def test_missing_with_default(root):
    assert hr.lookup("host", "grp.none", "box1", default="7", root=root) == "7"
    assert hr.lookup("host", "grp.n", "no-such-box", default=None, root=root) is None
    r = cli("host", "x.y", "--host", "no-such-host-for-test", "--default", "fallback")
    assert r.returncode == 0 and r.stdout == "fallback\n"


def test_missing_without_default_names_file_and_key(root):
    with pytest.raises(hr.RegistryError, match=r"box1\.json.*grp\.none"):
        hr.lookup("host", "grp.none", "box1", root=root)
    with pytest.raises(hr.RegistryError, match=r"no-such-box\.json"):
        hr.lookup("host", "grp.n", "no-such-box", root=root)
    r = cli("project", "issue_prefix", "--project", "no-such-project-for-test")
    assert r.returncode == 1 and r.stdout == ""
    assert "no-such-project-for-test.json" in r.stderr and "issue_prefix" in r.stderr


def test_bad_shapes(root):
    with pytest.raises(hr.RegistryError, match="invalid host name"):
        hr.lookup("host", "grp.n", "../box1", root=root)
    (root / "config/hosts/broken.json").write_text("{not json")
    with pytest.raises(hr.RegistryError, match="cannot read"):
        hr.lookup("host", "grp.n", "broken", default="ignored", root=root)
    with pytest.raises(hr.RegistryError):
        hr.lookup("host", "grp.n.deeper", "box1", root=root)
    assert cli("host", "k", "--host", "../etc").returncode == 1
    assert cli("bogus", "k").returncode == 2


def test_cli_prints_lists_as_json(root, monkeypatch, capsys):
    monkeypatch.setattr(hr, "ROOT", root)
    assert hr.main(["host", "grp.l", "--host", "box1"]) == 0
    assert capsys.readouterr().out == "[1, 2]\n"


def test_current_project_inside_harness_is_claude_global():
    assert hr.current_project(str(SCRIPTS)) == "claude-global"
