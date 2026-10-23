"""민감 파일 차단 정규식 시험 (2026-10-17 G1-2, 원본 .scratch/9d9904f7/audit/cred_regex_test.py).

실행: uv run -q --no-project --with pytest python -m pytest scripts/tests/test_sensitive_path_regex.py -q

배경: settings.json 의 Write|Edit 민감 파일 훅은 `\\/credentials(\\.json)?$` 처럼 앞에 `/` 를 요구해서
      `~/.claude/.credentials.json`(앞이 `.`)을 못 막았다. 제안식은 `(^|/)\\.?credentials(\\.json)?$`.
      settings.json 은 사용자만 고치므로, 첫 시험은 제안식 자체를 grep -E 로 검증하고
      둘째 시험은 훅 matcher 가 Write·Edit 를 포함하는지 본다.
      셋째 시험은 settings.json 의 실제 훅 식이 제안식에 맞게 고쳐졌는지 본다(2026-10-17 사용자 수정 뒤 상시 시험,
      그 전에는 xfail(strict) 로 두어 XPASS 가 «고쳐졌다» 신호였다). 식 원문은 출력하지 않는다.

알려진 한계 (제안식이 잡지 못한다. 확장은 사용자 결정, NOT_BLOCKED 에 시험값으로 고정):
  x_credentials.json · credentials.yml · credentials.json.bak
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

PROPOSED = r"(^|/)\.?credentials(\.json)?$"
SETTINGS = Path(__file__).resolve().parent.parent.parent / "settings.json"

BLOCKED = ["/home/u/.claude/.credentials.json", "/x/credentials.json", "/x/credentials"]
# 알려진 한계 3경로: 제안식이 잡지 못한다(확장은 사용자 결정). 시험값으로 명시해 한계가 바뀌면 이 목록이 먼저 깨지게 한다.
NOT_BLOCKED = ["/x/x_credentials.json", "/x/credentials.yml", "/x/credentials.json.bak"]


def grep_blocks(pattern: str, path: str) -> bool:
    """훅과 같은 `grep -qE` 로 판정한다(파이썬 re 와 ERE 차이를 배제)."""
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
    """settings.json PreToolUse 훅 중 credentials 를 보는 명령의 (matcher, grep -E 식) 목록."""
    out = []
    for g in json.loads(SETTINGS.read_text())["hooks"].get("PreToolUse", []):
        for h in g.get("hooks", []):
            c = h.get("command", "")
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
    # 2026-10-17 사용자가 settings.json 을 제안식으로 고쳐 XPASS(strict) 가 났고, 그 신호대로 xfail 표식을 지웠다.
    # 다시 옛 식으로 돌아가면 이 시험이 실패해 알린다.
    pats = [p for _, p in live_hooks()]
    assert pats
    for path in BLOCKED:
        assert any(grep_blocks(p, path) for p in pats), (
            f"{path} 가 실제 훅에서 통과한다"
        )
