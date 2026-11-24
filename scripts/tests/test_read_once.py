"""read-once.sh --clear 회귀 테스트 (2026-09-08 결정 6: PreCompact 에서 캐시 삭제).

실행: python3 ~/.claude/scripts/tests/test_read_once.py → 실패 0 이면 exit 0

■ 계약 (소스 대조)
  · 캐시 폴더는 `$HOME/.claude/_cache/read-once/*.cache`. HOME 을 가짜로 바꾸면 실제 캐시는 건드리지 않는다.
  · `--clear` 는 stdin 을 읽지 않고 캐시 파일 전부를 지운 뒤 exit 0.
  · 캐시 이외 파일(.cache 아닌 것)은 남긴다.
REF: knowledge/harness/code-history/scripts__tests__test_read_once.py.md
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path.home() / ".claude/scripts/read-once.sh"

fail = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fail
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}{'' if ok else ' (' + detail + ')'}")


with tempfile.TemporaryDirectory() as td:
    fake_home = Path(td)
    cache = fake_home / ".claude/_cache/read-once"
    cache.mkdir(parents=True)
    (cache / ("a" * 16 + ".cache")).write_text("sig 1\n")
    (cache / ("b" * 16 + ".cache")).write_text("sig 2\n")
    (cache / "keep.txt").write_text("not a cache\n")
    env = dict(os.environ, HOME=str(fake_home))

    r = subprocess.run(["bash", str(SCRIPT), "--clear"], input="", capture_output=True, text=True, env=env, check=False)
    check("--clear exit 0", r.returncode == 0, f"rc={r.returncode} stderr={r.stderr.strip()}")
    left = sorted(p.name for p in cache.glob("*.cache"))
    check("--clear 뒤 *.cache 0개", left == [], f"남음={left}")
    check("--clear 는 .cache 아닌 파일 보존", (cache / "keep.txt").exists())
    check("--clear 는 stdout 침묵", r.stdout == "", f"stdout={r.stdout!r}")

    r2 = subprocess.run(["bash", str(SCRIPT), "--clear"], input="", capture_output=True, text=True,
                        env=dict(env, HOME=str(fake_home / "empty")), check=False)
    check("캐시 폴더 부재 시 --clear exit 0", r2.returncode == 0, f"rc={r2.returncode}")

def hook(env, mode, tool_input, session="s1", agent=None, response=None):
    d = {"tool_name": "Read", "session_id": session, "tool_input": tool_input}
    if agent:
        d["agent_id"] = agent
    if response is not None:
        d["tool_response"] = response
    args = ["bash", str(SCRIPT)] + ([] if mode == "check" else [mode])
    return subprocess.run(args, input=json.dumps(d), capture_output=True, text=True, env=env, check=False).stdout


with tempfile.TemporaryDirectory() as td:
    env = dict(os.environ, HOME=str(Path(td) / "home"))
    f = Path(td) / "doc.txt"
    f.write_text("내용\n")
    ti = {"file_path": str(f)}

    check("첫 읽기는 통과", hook(env, "check", ti) == "")
    hook(env, "--record", ti, response={})
    check("기록 뒤 같은 전체 읽기는 차단", '"block"' in hook(env, "check", ti))
    check("offset 읽기는 면제", hook(env, "check", {**ti, "offset": 0, "limit": 5}) == "")
    check("pages(PDF 쪽 범위) 읽기는 면제", hook(env, "check", {**ti, "pages": "6-10"}) == "")
    check("오류 응답은 기록하지 않음",
          (hook(env, "--record", {"file_path": str(f)}, session="s2", response={"error": "x"}),
           hook(env, "check", ti, session="s2"))[1] == "")
    check("agent_id 가 다르면 서로 막지 않음(부모 기록 → 서브에이전트 통과)", hook(env, "check", ti, agent="sub-1") == "")
    hook(env, "--record", ti, agent="sub-1", response={})
    check("서브에이전트 자기 기록은 자기가 차단", '"block"' in hook(env, "check", ti, agent="sub-1"))
    check("다른 서브에이전트는 통과", hook(env, "check", ti, agent="sub-2") == "")
    check("부모는 여전히 자기 기록으로 차단", '"block"' in hook(env, "check", ti))

real = Path.home() / ".claude/_cache/read-once"
check("실제 캐시 폴더는 건드리지 않음", real.exists())

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} (15 cases)")
sys.exit(1 if fail else 0)
