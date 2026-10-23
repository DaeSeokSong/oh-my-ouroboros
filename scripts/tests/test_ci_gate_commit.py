#!/usr/bin/env python3
"""ci-gate-commit.sh 회귀 테스트 (2026-10-01 감사 A1) — 임시 git 저장소에 파일을 stage 해 훅을 돌린다.

실행: python3 ~/.claude/scripts/tests/test_ci_gate_commit.py → 실패 0 이면 exit 0
케이스: 비ASCII 이름 파일의 시크릿 탐지(옛 코드는 인용형 이름이라 조회 실패 → 검사 생략 후 통과) / 개행 든 이름은 fail-closed /
        따옴표 키(`"password": "…"`) 대입 탐지 / 한 줄에 자리표시자가 앞·실제 값이 뒤일 때 줄 전체 제외 금지 / 자리표시자뿐이면 통과.
시크릿 꼴 문자열은 조각을 이어 붙여 만든다(이 파일 자체가 훅 검사 대상이라 그대로 적으면 자기 커밋이 막힌다).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(os.environ.get("CI_GATE_HOOK") or Path(__file__).resolve().parents[1] / "ci-gate-commit.sh")   # 수정 전 사본 대조용
KEY = "API" + "_KEY"
TOK = "TO" + "KEN"
PW = "pass" + "word"


def run_case(files: dict[str, str]):
    """임시 저장소에 files 를 stage 하고 훅을 돌려 (exit, 출력) 을 돌려준다."""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
        subprocess.run(["git", "init", "-q", tmp], check=True, capture_output=True, env=env)
        for name, body in files.items():
            p = Path(tmp) / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp, check=True, capture_output=True, env=env)
        r = subprocess.run(["bash", str(HOOK)], cwd=tmp, capture_output=True, text=True, env=env)
        return r.returncode, (r.stdout + r.stderr)


REAL = "abcdefgh12345678"
CASES = [
    # (이름, 파일들, 기대 exit, 출력에 있어야 할 문구)
    ("비ASCII 이름 파일의 시크릿 → 차단", {"한글노트.md": f'{KEY}="{REAL}"\n'}, 1, "SECRET DETECTED"),
    ("비ASCII 이름 파일 깨끗 → 통과", {"한글노트.md": "안녕\n"}, 0, "PASSED"),
    ("개행이 든 이름 → fail-closed 차단", {"a\nb.md": "x\n"}, 1, "SKIPPED"),
    ("JSON 따옴표 키 대입 → 차단", {"c.json": f'{{"{PW}": "{REAL}"}}\n'}, 1, "SECRET DETECTED"),
    ("md 따옴표 키 대입 → 차단", {"n.md": f'"{PW}": "{REAL}"\n'}, 1, "SECRET DETECTED"),
    ("한 줄 자리표시자 앞·실제 값 뒤 → 차단", {"n.md": f'{KEY}="<YOUR_KEY_HERE>" {TOK}="{REAL}"\n'}, 1, "SECRET DETECTED"),
    ("한 줄 모두 자리표시자 → 통과", {"n.md": f'{KEY}="<YOUR_KEY_HERE>" {TOK}="<YOUR_TOKEN_HERE>"\n'}, 0, "PASSED"),
]

fail = 0
for name, files, want, phrase in CASES:
    rc, out = run_case(files)
    ok = rc == want and phrase in out
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}: exit {rc} (기대 {want})" + ("" if ok else f"\n     {out[:300]}"))

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(CASES)} cases)")
sys.exit(1 if fail else 0)
