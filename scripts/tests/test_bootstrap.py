"""bootstrap.sh env-config 처리 회귀 테스트 (가짜 git·claude 등 — 네트워크·실제 HOME 금지).

실행: uv run --with pytest python -m pytest scripts/tests/test_bootstrap.py -q
tty 가 없는 환경(start_new_session)에서 돌려 /dev/tty 질문이 기본값으로 떨어지게 한다.
REF: knowledge/harness/code-history/scripts__tests__test_bootstrap.py.md
"""
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bootstrap.sh"

FAKE_GIT = textwrap.dedent('''\
    #!/bin/bash
    # 가짜 git: clone URL DIR → DIR/.git + scripts/ 만 만든다. -C DIR pull 은 성공만 한다.
    if [ "$1" = clone ]; then mkdir -p "$3/.git" "$3/scripts"; exit 0; fi
    exit 0
''')


@pytest.fixture
def bs(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("git", "curl", "node", "npm", "npx", "uvx", "claude"):
        f = bin_dir / name
        f.write_text(FAKE_GIT if name == "git" else "#!/bin/bash\nexit 0\n")
        f.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "LANG": "C.UTF-8"}

    def run():
        return subprocess.run(["bash", str(SCRIPT), "--skip-mcp", "--skip-plugins"], env=env, cwd=tmp_path,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL, start_new_session=True, check=False)

    return type("B", (), {"home": home, "run": staticmethod(run)})


def test_fresh_server_without_claude_dir_writes_env_config_after_clone(bs):
    r = bs.run()
    assert r.returncode == 0, r.stdout + r.stderr
    cfg = (bs.home / ".claude/env-config").read_text()
    assert "DEFAULT_MODEL=sonnet" in cfg and "BIO_PLAUSIBILITY=false" in cfg and "CONFLUENCE_MCP=false" in cfg
    assert (bs.home / ".claude/settings.local.json").exists()


def test_rerun_keeps_existing_user_keys_and_updates_only_three(bs):
    claude = bs.home / ".claude"
    (claude / ".git").mkdir(parents=True)
    (claude / "scripts").mkdir()
    (claude / "env-config").write_text("NTFY_TOPIC=my-private-topic\nDEFAULT_MODEL=opus\nCUSTOM=1\n")
    r = bs.run()
    assert r.returncode == 0, r.stdout + r.stderr
    cfg = (claude / "env-config").read_text()
    assert "NTFY_TOPIC=my-private-topic" in cfg and "CUSTOM=1" in cfg
    assert "DEFAULT_MODEL=sonnet" in cfg and "DEFAULT_MODEL=opus" not in cfg
    assert "BIO_PLAUSIBILITY=false" in cfg and "CONFLUENCE_MCP=false" in cfg


def test_rerun_with_env_config_lacking_trailing_newline_does_not_glue_keys(bs):
    claude = bs.home / ".claude"
    (claude / ".git").mkdir(parents=True)
    (claude / "scripts").mkdir()
    (claude / "env-config").write_text("CUSTOM=1")
    r = bs.run()
    assert r.returncode == 0, r.stdout + r.stderr
    lines = (claude / "env-config").read_text().splitlines()
    assert "CUSTOM=1" in lines and "CONFLUENCE_MCP=false" in lines


def test_ntfy_guidance_points_to_env_config_not_tracked_script(bs):
    claude = bs.home / ".claude"
    (claude / ".git").mkdir(parents=True)
    (claude / "scripts").mkdir()
    (claude / "scripts" / "claude-notify.sh").write_text("#!/bin/bash\n")
    r = bs.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "USER_NTFY_TOPIC" in r.stdout and "sed -i" not in r.stdout and "NTFY_TOPIC=\"" not in r.stdout
