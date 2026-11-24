"""민감 파일 차단 정규식 시험.

실행: uv run -q --no-project --with pytest python -m pytest scripts/tests/test_sensitive_path_regex.py -q
REF: knowledge/harness/code-history/scripts__tests__test_sensitive_path_regex.py.md

알려진 한계 (제안식이 잡지 못한다. 확장은 사용자 결정, NOT_BLOCKED 에 시험값으로 고정):
  x_credentials.json · credentials.yml · credentials.json.bak
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROPOSED = r"(^|/)\.?credentials(\.json)?$"
SETTINGS = Path(__file__).resolve().parent.parent.parent / "settings.json"
sys.path.insert(0, str(SETTINGS.parent / "scripts"))
from hook_deny_wrap_install import unwrap

BLOCKED = ["/home/u/.claude/.credentials.json", "/x/credentials.json", "/x/credentials"]
NOT_BLOCKED = ["/x/x_credentials.json", "/x/credentials.yml", "/x/credentials.json.bak"]


def grep_blocks(pattern: str, path: str) -> bool:
    return (
        subprocess.run(
            ["grep", "-qE", pattern, "--"],
            input=path,
            text=True,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


@pytest.mark.parametrize("path", BLOCKED)
def test_proposed_pattern_blocks(path):
    assert grep_blocks(PROPOSED, path)
    assert re.search(PROPOSED, path)


@pytest.mark.parametrize("path", NOT_BLOCKED)
def test_proposed_pattern_known_gap(path):
    assert not grep_blocks(PROPOSED, path)


def live_hooks() -> list[tuple[str, str]]:
    out = []
    for g in json.loads(SETTINGS.read_text())["hooks"].get("PreToolUse", []):
        for h in g.get("hooks", []):
            c = h.get("command", "")
            c = unwrap(c) or c
            if "credentials" in c:
                m = re.search(r"grep -[a-zA-Z]*E[a-zA-Z]* '([^']+)'", c)
                if m:
                    out.append((g.get("matcher", ""), m.group(1)))
    return out


def test_live_sensitive_hook_covers_write_and_edit():
    hooks = live_hooks()
    assert hooks, (
        "settings.json 에서 credentials 를 보는 grep -E 훅을 찾지 못했다(훅 구조가 바뀌었는지 확인)"
    )
    assert any("Write" in m and "Edit" in m for m, _ in hooks), (
        "민감 파일 훅의 matcher 가 Write·Edit 를 모두 포함하지 않는다"
    )


def test_live_settings_hook_blocks_dot_credentials():
    pats = [p for _, p in live_hooks()]
    assert pats
    for path in BLOCKED:
        assert any(grep_blocks(p, path) for p in pats), (
            f"{path} 가 실제 훅에서 통과한다"
        )
