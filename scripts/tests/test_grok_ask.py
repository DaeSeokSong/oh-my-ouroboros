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
        # 2026-10-25: 빈 응답(종료 코드 0)은 래퍼가 exit 75 로 바꾸므로 가짜도 답을 한 줄 낸다
        fake.write_text(f'#!/bin/sh\necho "$@" > "{home}/argv.txt"\necho fake answer\n', encoding="utf-8")
        fake.chmod(0o755)
        (home / ".claude/scripts").mkdir(parents=True)
        if with_preflight:
            (home / ".claude/scripts/external_send_preflight.py").symlink_to(PREFLIGHT)
        r = subprocess.run(["bash", str(WRAPPER), *args], capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(home)), timeout=60, check=False)
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

# --- 2026-10-25: 세션 고정 폴더·직렬화·실패 드러내기 (실측: 두 번째 호출이 «so nothing ran» 인데 종료 코드 0) ---
def make_home(td):
    """가짜 HOME 을 만든다. 가짜 grok 은 인자·cwd·cwd 목록을 적고 FAKE_MODE(ok|empty|nothing)에 따라 답한다."""
    home = Path(td)
    (home / ".grok/bin").mkdir(parents=True)
    fake = home / ".grok/bin/grok"
    fake.write_text(
        f'#!/bin/sh\necho "$@" > "{home}/argv.txt"\npwd -P > "{home}/cwd.txt"\nls -A > "{home}/ls.txt"\n'
        'case "${FAKE_MODE:-ok}" in\n  empty) ;;\n'
        "  nothing) echo \"This session's folder no longer exists, so nothing ran.\" ;;\n"
        "  quote) printf 'line1\\nline2\\nline3\\nline4\\n> This session folder no longer exists, so nothing ran\\n' ;;\n"
        '  *) echo "fake answer" ;;\nesac\n', encoding="utf-8")
    fake.chmod(0o755)
    (home / ".claude/scripts").mkdir(parents=True)
    (home / ".claude/scripts/external_send_preflight.py").symlink_to(PREFLIGHT)
    return home


def call(home, args, mode="ok"):
    """래퍼를 한 번 돌려 (CompletedProcess, argv, cwd, cwd 목록 줄들) 를 돌려준다. grok 이 안 불렸으면 None."""
    for name in ("argv.txt", "cwd.txt", "ls.txt"):
        (home / name).unlink(missing_ok=True)
    r = subprocess.run(["bash", str(WRAPPER), *args], capture_output=True, text=True,
                       env=dict(os.environ, HOME=str(home), FAKE_MODE=mode), timeout=60, check=False)
    rd = [(home / n).read_text(encoding="utf-8").strip() if (home / n).exists() else None
          for n in ("argv.txt", "cwd.txt", "ls.txt")]
    return r, rd[0], rd[1], (rd[2].splitlines() if rd[2] is not None else None)


with tempfile.TemporaryDirectory() as td:
    home = make_home(td)
    ex = home.resolve() / "grok-exchange"
    run_dir = ex / ".sessions/s1.run"
    r, argv, cwd, ls = call(home, ["--session", "s1", "첫 질문"])
    sid = (ex / ".sessions/s1.id").read_text(encoding="utf-8").strip() if (ex / ".sessions/s1.id").exists() else ""
    check("세션 첫 호출: -s <UUID>, cwd=세션 고정 폴더, 폴더 잔존·프롬프트 파일 없음, id 파일 있음",
          r.returncode == 0 and bool(sid) and argv is not None and f"-s {sid}" in argv and cwd == str(run_dir)
          and run_dir.is_dir() and not list(run_dir.glob(".prompt-*.md")) and "fake answer" in r.stdout,
          f"rc={r.returncode} argv={argv} cwd={cwd} err={r.stderr[-200:]}")
    r, argv, cwd, ls = call(home, ["--session", "s1", "둘째 질문"])
    check("같은 세션 두 번째 호출: -r 같은 UUID, 같은 cwd",
          r.returncode == 0 and argv is not None and f"-r {sid}" in argv and cwd == str(run_dir),
          f"rc={r.returncode} argv={argv} cwd={cwd} err={r.stderr[-200:]}")

with tempfile.TemporaryDirectory() as td:
    home = make_home(td)
    sess = home.resolve() / "grok-exchange/.sessions"
    sess.mkdir(parents=True, mode=0o700)
    (sess / "old.id").write_text("6df2ce22-0000-4000-8000-000000000000\n", encoding="utf-8")
    r, argv, cwd, ls = call(home, ["--session", "old", "질문"])
    check("id 파일만 있고 .run 없음(옛 세션) → exit 75, grok 미호출",
          r.returncode == 75 and argv is None and "재개 불가" in r.stderr, f"rc={r.returncode} argv={argv} err={r.stderr[-200:]}")

with tempfile.TemporaryDirectory() as td:
    home = make_home(td)
    r, argv, cwd, ls = call(home, ["질문"], mode="nothing")
    check("grok 이 «so nothing ran» 출력 → exit 75 (원문은 stdout 으로 그대로)",
          r.returncode == 75 and "so nothing ran" in r.stdout and "아무것도 실행하지 않았습니다" in r.stderr, f"rc={r.returncode} out={r.stdout} err={r.stderr[-200:]}")
    r, argv, cwd, ls = call(home, ["질문"], mode="empty")
    check("grok 빈 출력 + 종료 코드 0 → exit 75", r.returncode == 75 and "빈 응답" in r.stderr, f"rc={r.returncode} err={r.stderr[-200:]}")
    left = [p.name for p in (home.resolve() / "grok-exchange").glob(".*") if p.name.startswith((".out-", ".err-", ".prompt-"))]
    check("실패 호출 뒤에도 임시 출력·프롬프트 파일 없음", not left, f"left={left}")

with tempfile.TemporaryDirectory() as td:
    home = make_home(td)
    r, argv, cwd, ls = call(home, ["질문"])
    check("세션 없는 호출: cwd=.run-<PID>, 끝나면 폴더 없음, 답은 stdout 그대로",
          r.returncode == 0 and cwd is not None and "/.run-" in cwd and not Path(cwd).exists() and r.stdout == "fake answer\n",
          f"rc={r.returncode} cwd={cwd} out={r.stdout!r}")

with tempfile.TemporaryDirectory() as td:
    home = make_home(td)
    r, argv, cwd, ls = call(home, ["--session", "r", "첫 질문"])
    stale = home.resolve() / "grok-exchange/.sessions/r.run/.prompt-999999.md"
    stale.write_text("이전 호출의 프롬프트\n", encoding="utf-8")
    r, argv, cwd, ls = call(home, ["--session", "r", "둘째 질문"])
    prompts = [x for x in (ls or []) if x.startswith(".prompt-")]
    check("세션 폴더의 잔재 .prompt-999999.md → grok 이 볼 때 이번 프롬프트 하나만",
          r.returncode == 0 and len(prompts) == 1 and prompts[0] != ".prompt-999999.md" and not stale.exists(),
          f"rc={r.returncode} ls={ls}")

# --- 2026-10-26 main 검수: 판정 범위 좁히기 · 실패한 첫 호출은 .id 를 남기지 않음 ---
with tempfile.TemporaryDirectory() as td:
    home = make_home(td)
    r, argv, cwd, ls = call(home, ["질문"], mode="quote")
    check("답 본문 넷째 줄 뒤에 «nothing ran» 문장을 인용 → 실패 아님(exit 0)",
          r.returncode == 0 and "so nothing ran" in r.stdout, f"rc={r.returncode} err={r.stderr[-200:]}")

with tempfile.TemporaryDirectory() as td:
    home = make_home(td)
    sess = home.resolve() / "grok-exchange/.sessions"
    r, argv, cwd, ls = call(home, ["--session", "f", "첫 질문"], mode="empty")
    check("세션 첫 호출 실패(빈 응답) → exit 75, .id 없음",
          r.returncode == 75 and not (sess / "f.id").exists(), f"rc={r.returncode} err={r.stderr[-200:]}")
    r, argv, cwd, ls = call(home, ["--session", "f", "다시 질문"])
    sid = (sess / "f.id").read_text(encoding="utf-8").strip() if (sess / "f.id").exists() else ""
    check("실패 뒤 같은 이름 재호출 → 신규(-s)로 다시 시작하고 성공 뒤 .id 저장",
          r.returncode == 0 and bool(sid) and argv is not None and f"-s {sid}" in argv, f"rc={r.returncode} argv={argv}")

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({n} cases)")
sys.exit(1 if fail else 0)
