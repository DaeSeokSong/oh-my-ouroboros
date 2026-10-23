"""respawn-peers.sh 시험: 이 세션·대화형 세션·형식 어긋난 id 를 빼고, 이름의 제어 문자를 지우고, 작업 중 표시를 붙인다.

실행: python3 -I scripts/tests/test_respawn_peers.py  → 실패 0 이면 exit 0
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "respawn-peers.sh"
FAILS = []


def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name + ("" if cond else f": {detail}"))
    if not cond:
        FAILS.append(name)


def run(agents, self_sid="self"):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(agents, f, ensure_ascii=False)
    env = {**os.environ, "CLAUDE_CODE_SESSION_ID": self_sid, "RESPAWN_AGENTS_JSON": f.name}
    try:
        return subprocess.run(["bash", str(SCRIPT)], check=False, capture_output=True, text=True, env=env)
    finally:
        os.unlink(f.name)


agents = [
    {"id": "aaaaaaaa", "sessionId": "s1", "name": "[exp] 2.0.0\u0007\u0085", "kind": "background", "status": "busy"},
    {"id": "bad id;rm", "sessionId": "s2", "name": "n", "kind": "background", "status": "idle"},
    {"id": "bbbbbbbb", "sessionId": "self", "name": "[Harness] Manager", "kind": "background", "status": "busy"},
    {"id": "cccccccc", "sessionId": "s3", "name": "대화형", "kind": "interactive", "status": "idle"},
    {"id": "dddddddd", "sessionId": "s4", "name": "[Research] Lab", "kind": "background", "status": "idle"},
]
r = run(agents)
out = r.stdout
check("종료 코드 0", r.returncode == 0, r.stderr)
check("다른 백그라운드 세션 명령", "claude respawn aaaaaaaa" in out and "claude respawn dddddddd" in out, out)
check("이 세션은 빼기", "bbbbbbbb" not in out, out)
check("대화형 세션은 빼기", "cccccccc" not in out, out)
check("형식 어긋난 id 는 빼기", "bad id" not in out, out)
check("한글 이름 보존·제어 문자 제거", "# [exp] 2.0.0 (" in out and "\u0007" not in out and "\u0085" not in out, out)
check("작업 중 표시", "작업 중 · 쉴 때 실행" in out, out)
check("--all 금지 안내", "--all" in out, out)
tricky = [
    {"id": "eeeeeeee\n", "sessionId": "s5", "name": "개행 id", "kind": "background", "status": "idle"},
    {"id": "ffffffff", "sessionId": "s6", "name": "a" + chr(0x202E) + "b" + chr(0x2028) + "c" + chr(0x200B) + "d", "kind": "background", "status": "idle"},
    {"id": "abababab", "sessionId": "s7", "name": "", "kind": "background", "status": "idle"},
    {"id": "cdcdcdcd", "sessionId": "s8", "name": "back\\slash", "kind": "background", "status": "idle"},
]
out = run(tricky).stdout
check("id 끝 줄바꿈은 빼기", "eeeeeeee" not in out, out)
check("방향·줄 구분·폭 없는 문자 제거", "# abcd (idle)" in out, out)
check("빈 이름은 «이름 없음», 칸 밀림 없음", "claude respawn abababab   # 이름 없음 (idle)" in out, out)
check("역슬래시 한 번만", "# back\\slash (idle)" in out, out)
r = run(agents, self_sid="")
check("이 세션 id 를 모르면 출력하지 않음", r.returncode != 0 and "claude respawn" not in r.stdout, r.stdout + r.stderr)
r = run([agents[2]])
check("다른 세션 없으면 안내만", "다시 띄울 다른 백그라운드 세션이 없습니다" in r.stdout and "claude respawn" not in r.stdout, r.stdout)
print(f"\n실패 {len(FAILS)}건")
sys.exit(1 if FAILS else 0)
