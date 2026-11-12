"""host-hardening.sh argument checks that run before any registry read or system change (no sudo, check mode only).

Run: uv run --with pytest python -m pytest scripts/tests/test_host_hardening.py -q
"""
import subprocess
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent.parent / "tools/mem-guard"


def run(name, *args):
    return subprocess.run(["bash", str(TOOLS / name), *args], check=False, capture_output=True, text=True)


def test_leading_zero_number_is_rejected():
    r = run("host-hardening.sh", "--reserve-gb", "010")
    assert r.returncode == 64 and "010" in r.stderr


def test_help_is_same_through_old_name():
    new, old = run("host-hardening.sh", "--help"), run("host1-hardening.sh", "--help")
    assert new.returncode == old.returncode == 64 and new.stdout == old.stdout and "--apply" in new.stdout
