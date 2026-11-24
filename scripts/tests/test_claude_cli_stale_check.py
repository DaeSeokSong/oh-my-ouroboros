"""claude-cli-stale-check.sh 시험 (2026-11-13): PATH 의 claude 판이 설치 최신 판보다 낮을 때만 경보 한 줄."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "claude-cli-stale-check.sh"


def make_versions(tmp_path, names):
    vdir = tmp_path / "versions"
    vdir.mkdir()
    for n in names:
        (vdir / n).write_text("#!/bin/sh\n")
        (vdir / n).chmod(0o755)
    return vdir


def make_npm(tmp_path, version):
    pkg = tmp_path / "npm/lib/node_modules/@anthropic-ai/claude-code"
    (pkg / "bin").mkdir(parents=True)
    (pkg / "bin/claude.exe").write_text("#!/bin/sh\n")
    (pkg / "bin/claude.exe").chmod(0o755)
    (pkg / "package.json").write_text(f'{{\n  "name": "@anthropic-ai/claude-code",\n  "version": "{version}"\n}}\n')
    link = tmp_path / "bin/claude"
    link.parent.mkdir()
    link.symlink_to(pkg / "bin/claude.exe")
    return link


def run(bin_path, vdir, sys_path=""):
    env = dict(os.environ, CLAUDE_BIN=str(bin_path), CLAUDE_VERSIONS_DIR=str(vdir), CLAUDE_SYSTEMD_PATH=sys_path)
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, check=False)


def pick(home, vdir):
    env = dict(os.environ, HOME=str(home), CLAUDE_VERSIONS_DIR=str(vdir))
    r = subprocess.run(["bash", "-c", f"source {SCRIPT}; claude_pick_newest"], capture_output=True, text=True, env=env, check=False)
    return r.stdout.strip(), r.returncode


def fake_home_npm(home, version):
    pkg = home / ".npm-global/lib/node_modules/@anthropic-ai/claude-code"
    (pkg / "bin").mkdir(parents=True)
    (pkg / "bin/claude.exe").write_text("#!/bin/sh\n")
    (pkg / "bin/claude.exe").chmod(0o755)
    (pkg / "package.json").write_text(f'{{"version": "{version}"}}\n')
    (home / ".npm-global/bin").mkdir(parents=True)
    (home / ".npm-global/bin/claude").symlink_to(pkg / "bin/claude.exe")


def test_npm_older_than_installed_warns(tmp_path):
    vdir = make_versions(tmp_path, ["2.1.321", "2.1.322", "notaversion"])
    r = run(make_npm(tmp_path, "2.1.197"), vdir)
    lines = r.stdout.splitlines()
    assert r.returncode == 0 and len(lines) == 1
    assert lines[0].startswith("CLAUDE_CLI_STALE: PATH 의 claude 2.1.197(") and "< 설치판 2.1.322" in lines[0]


def test_npm_newer_than_installed_quiet(tmp_path):
    r = run(make_npm(tmp_path, "2.1.323"), make_versions(tmp_path, ["2.1.322"]))
    assert r.returncode == 0 and r.stdout == ""


def test_same_version_quiet(tmp_path):
    r = run(make_npm(tmp_path, "2.1.322"), make_versions(tmp_path, ["2.1.322"]))
    assert r.returncode == 0 and r.stdout == ""


def test_missing_versions_dir_quiet(tmp_path):
    r = run(make_npm(tmp_path, "2.1.197"), tmp_path / "nope")
    assert r.returncode == 0 and r.stdout == ""


def test_bin_inside_versions_dir_warns(tmp_path):
    vdir = make_versions(tmp_path, ["2.1.300", "2.1.322"])
    r = run(vdir / "2.1.300", vdir)
    assert r.returncode == 0 and "claude 2.1.300(" in r.stdout and "< 설치판 2.1.322" in r.stdout


def test_version_sort_is_numeric(tmp_path):
    vdir = make_versions(tmp_path, ["2.1.100"])
    r = run(make_npm(tmp_path, "2.1.99"), vdir)
    assert "claude 2.1.99(" in r.stdout and "< 설치판 2.1.100" in r.stdout
    # WHY: reverse: PATH 2.1.100 vs installed 2.1.99 must stay quiet (string sort would warn)
    other = tmp_path / "other"
    other.mkdir()
    r = run(make_npm(other, "2.1.100"), make_versions(other, ["2.1.99"]))
    assert r.stdout == ""


def test_systemd_path_old_warns(tmp_path):
    sess = tmp_path / "sess"
    sess.mkdir()
    old = tmp_path / "sys"
    old.mkdir()
    vdir = make_versions(sess, ["2.1.322"])
    r = run(make_npm(sess, "2.1.323"), vdir, sys_path=f"/nonexistent:{make_npm(old, '2.0.50').parent}")
    lines = r.stdout.splitlines()
    assert r.returncode == 0 and len(lines) == 1
    assert lines[0].startswith("CLAUDE_CLI_STALE: systemd PATH 의 claude 2.0.50(") and "< 설치판 2.1.322" in lines[0]
    assert "sudo npm " in lines[0] and "-g @anthropic-ai/claude-code" in lines[0]


def test_systemd_path_current_quiet(tmp_path):
    sess = tmp_path / "sess"
    sess.mkdir()
    other = tmp_path / "sys"
    other.mkdir()
    r = run(make_npm(sess, "2.1.323"), make_versions(sess, ["2.1.322"]), sys_path=str(make_npm(other, "2.1.323").parent))
    assert r.returncode == 0 and r.stdout == ""


def test_systemd_same_file_as_session_one_line(tmp_path):
    link = make_npm(tmp_path, "2.0.50")
    r = run(link, make_versions(tmp_path, ["2.1.322"]), sys_path=str(link.parent))
    lines = r.stdout.splitlines()
    assert len(lines) == 1 and lines[0].startswith("CLAUDE_CLI_STALE: PATH 의 claude 2.0.50(")


def test_systemd_path_without_claude_quiet(tmp_path):
    r = run(make_npm(tmp_path, "2.1.323"), make_versions(tmp_path, ["2.1.322"]), sys_path=str(tmp_path / "empty"))
    assert r.returncode == 0 and r.stdout == ""


def test_pick_newest_npm_wins(tmp_path):
    home = tmp_path / "home"
    fake_home_npm(home, "2.1.323")
    out, rc = pick(home, make_versions(tmp_path, ["2.1.322"]))
    assert rc == 0 and out == f"{home}/.npm-global/bin/claude\t2.1.323"


def test_pick_newest_versions_wins(tmp_path):
    home = tmp_path / "home"
    fake_home_npm(home, "2.1.197")
    vdir = make_versions(tmp_path, ["2.1.322"])
    out, rc = pick(home, vdir)
    assert rc == 0 and out == f"{vdir}/2.1.322\t2.1.322"


def test_pick_newest_none_falls_back(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    out, rc = pick(home, tmp_path / "nope")
    assert rc == 1 and out == ""
