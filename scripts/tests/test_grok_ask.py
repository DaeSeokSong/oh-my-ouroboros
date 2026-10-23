#!/usr/bin/env python3
"""grok-ask.sh 회귀 테스트 (2026-10-01 감사: 등호형 옵션·인라인 본문 사전검사). 실제 grok 은 부르지 않는다.

실행: python3 ~/.claude/scripts/tests/test_grok_ask.py → 실패 0 이면 exit 0
가짜 HOME 에 `.grok/bin/grok`(받은 인자를 파일에 적는 가짜)과 실제 사전검사 스크립트 링크를 둔다.
기대값은 지적된 사고에서 만든다: 게이트가 읽은 `--model=값` 이 래퍼에서도 같은 값으로 전달되어야 하고,
비밀이 든 인라인 본문은 grok 호출 전에 거부되어야 한다.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WRAPPER = Path.home() / ".claude/tools/grok-exchange/grok-ask.sh"
PREFLIGHT = Path.home() / ".claude/scripts/external_send_preflight.py"
SECRET = "tok" + 'en="' + "Sk9w" + "Q2vL" + 'p7zzz"'      # 소스에 키 모양 리터럴을 두지 않는다

fail = 0
n = 0


def run(args, with_preflight=True, file_bytes=None):
    """가짜 HOME 에서 래퍼를 돌려 (rc, stderr, grok 이 받은 인자 or None) 을 돌려준다. file_bytes 면 그 크기의 --file 을 만들어 넘긴다."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        if file_bytes is not None:
            (home / "grok-exchange").mkdir(mode=0o700)
            big = home / "grok-exchange/big.md"
            big.write_text(("abcdefghi\n" * (file_bytes // 10 + 1))[:file_bytes], encoding="utf-8")
            args = [*args, "--file", str(big)]
        (home / ".grok/bin").mkdir(parents=True)
        fake = home / ".grok/bin/grok"
        fake.write_text(f'#!/bin/sh\necho "$@" > "{home}/argv.txt"\n', encoding="utf-8")
        fake.chmod(0o755)
        (home / ".claude/scripts").mkdir(parents=True)
        if with_preflight:
            (home / ".claude/scripts/external_send_preflight.py").symlink_to(PREFLIGHT)
        r = subprocess.run(["bash", str(WRAPPER), *args], capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(home)), timeout=60)
        argv = (home / "argv.txt").read_text(encoding="utf-8") if (home / "argv.txt").exists() else None
    return r.returncode, r.stderr, argv


def check(name, ok, detail=""):
    global fail, n
    n += 1
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}" + ("" if ok else f": {detail}"))


rc, err, argv = run(["--model=grok-4.6", "--effort=high", "깨끗한 질문입니다"])
check("등호형 --model=·--effort= 가 옵션으로 해석되어 전달", rc == 0 and argv is not None and "-m grok-4.6" in argv
      and "--reasoning-effort high" in argv, f"rc={rc} argv={argv} err={err[-200:]}")

rc, err, argv = run(["--model", "grok-4.6", "--effort", "low", "깨끗한 질문입니다"])
check("공백형도 그대로 동작", rc == 0 and argv is not None and "-m grok-4.6" in argv and "--reasoning-effort low" in argv,
      f"rc={rc} argv={argv}")

rc, err, argv = run(["--effort=high", f"설정 {SECRET} 를 봐 주세요"])
check("비밀이 든 인라인 본문 → 거부(grok 미호출)", rc == 78 and argv is None and "전송 전 검사" in err, f"rc={rc} argv={argv} err={err[-200:]}")

rc, err, argv = run(["깨끗한 질문입니다"], with_preflight=False)
check("사전검사 스크립트 부재 → 거부(grok 미호출)", rc == 78 and argv is None, f"rc={rc} argv={argv}")

rc, err, argv = run([], file_bytes=110_000)
check("프롬프트 100KB 초과 → 표준에러 경고, 전송은 진행", rc == 0 and argv is not None and "[grok-ask] 경고: 프롬프트" in err, f"rc={rc} argv={argv} err={err[-200:]}")

rc, err, argv = run([], file_bytes=50_000)
check("프롬프트 100KB 이하 → 경고 없음", rc == 0 and argv is not None and "[grok-ask] 경고" not in err, f"rc={rc} argv={argv} err={err[-200:]}")

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({n} cases)")
sys.exit(1 if fail else 0)
