"""exchange-prune.sh 회귀 테스트 (자체 완결 — 임시 뿌리에서만 지운다).

실행: python3 ~/.claude/scripts/tests/test_exchange_prune.py → 실패 0 이면 exit 0

■ 파악한 계약 (소스 대조)
  · 대상 = 뿌리 바로 아래 항목. 디렉터리는 안쪽까지 훑은 **가장 최근 mtime** 으로 나이를 잰다.
  · 기한 = EXCHANGE_PRUNE_DAYS(기본 14)일. 뿌리 목록 = EXCHANGE_PRUNE_ROOTS(콜론 구분).
  · 보존 = `.` 로 시작하는 항목 전부(`.sessions/`) · `dbg.log`.
  · 로그 = `$HOME/.claude/_audit/exchange-prune.log` 에 `날짜<TAB>경로<TAB>mtime` append.
  · `--dry-run` 은 지우지 않고 출력만. 뿌리 부재는 조용히 exit 0.
  · 실제 로그를 더럽히지 않으려고 **HOME 을 임시 폴더로 바꿔** 실행한다(로그 경로가 $HOME
    기준이라 이 한 수로 격리된다. 뿌리는 어차피 EXCHANGE_PRUNE_ROOTS 로 지정한다).

■ 케이스
  1. 20일 된 폴더 → 삭제
  2. 오늘 폴더 → 보존
  3. `.sessions/` 안이 전부 오래돼도 → 보존
  4. `dbg.log` 가 오래돼도 → 보존
  5. 폴더 mtime 은 오래됐지만 안에 최근 파일이 있으면 → 보존(가장 최근 mtime 기준)
  6. 로그에 삭제 1건이 `날짜<TAB>경로<TAB>mtime` 으로 남는다
  7. --dry-run 은 하나도 지우지 않는다
EXCHANGE_PRUNE_SCRIPT 에 스크립트 경로를 주면 그 사본을 시험한다(수정 전 사본 대조용).
REF: knowledge/harness/code-history/scripts__tests__test_exchange_prune.py.md
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = Path(os.environ.get("EXCHANGE_PRUNE_SCRIPT") or Path.home() / ".claude/scripts/exchange-prune.sh")
DAY = 86400


def touch(path: Path, days_ago: float):
    ts = time.time() - days_ago * DAY
    os.utime(path, (ts, ts))


def build(root: Path):
    root.mkdir(parents=True, exist_ok=True)

    old = root / "old_bundle"
    old.mkdir()
    (old / "a.md").write_text("old\n", encoding="utf-8")
    touch(old / "a.md", 20)
    touch(old, 20)

    recent = root / "recent_bundle"
    recent.mkdir()
    (recent / "b.md").write_text("recent\n", encoding="utf-8")

    sessions = root / ".sessions"
    sessions.mkdir()
    (sessions / "grok-session-id").write_text("sid\n", encoding="utf-8")
    touch(sessions / "grok-session-id", 30)
    touch(sessions, 30)

    dbg = root / "dbg.log"
    dbg.write_text("debug\n", encoding="utf-8")
    touch(dbg, 30)

    mixed = root / "mixed_bundle"
    mixed.mkdir()
    (mixed / "fresh.md").write_text("fresh\n", encoding="utf-8")
    touch(mixed, 25)
    return old, recent, sessions, dbg, mixed


def run(roots, home: Path, dry: bool = False, extra_env: dict | None = None):
    env = dict(os.environ)
    env.update(extra_env or {})
    env["HOME"] = str(home)
    env["EXCHANGE_PRUNE_ROOTS"] = ":".join(str(r) for r in roots)
    cmd = ["bash", str(SCRIPT)] + (["--dry-run"] if dry else [])
    return subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)


fail = 0


def check(name: str, ok: bool, detail: str = ""):
    global fail
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}{'' if ok else f' ({detail})'}")


with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    home = base / "fake_home"
    home.mkdir()

    # WHY: 뿌리는 HOME 아래 두 교환 폴더 이름이어야 인정된다(2026-10-01 감사 — 임의 뿌리 거부)
    dry_home = base / "dry_home"
    dry_home.mkdir()
    dry_root = dry_home / "grok-exchange"
    d_old, d_recent, d_sessions, d_dbg, d_mixed = build(dry_root)
    r = run([dry_root], dry_home, dry=True)
    all_alive = all(p.exists() for p in (d_old, d_recent, d_sessions, d_dbg, d_mixed))
    check("⑦ --dry-run 은 삭제 0", r.returncode == 0 and all_alive,
          f"rc={r.returncode} old={d_old.exists()} out={r.stdout.strip()[:120]!r}")
    check("   --dry-run 출력에 대상 표시", "old_bundle" in r.stdout, f"out={r.stdout.strip()[:120]!r}")

    root_a, root_b = home / "grok-exchange", home / "codex-exchange"
    a_old, a_recent, a_sessions, a_dbg, a_mixed = build(root_a)
    b_old, b_recent, b_sessions, b_dbg, b_mixed = build(root_b)
    missing_root = base / "does-not-exist"

    r = run([root_a, root_b, missing_root], home)
    check("   실행 rc 0(없는 뿌리 포함)", r.returncode == 0, f"rc={r.returncode} err={r.stderr.strip()[:120]!r}")
    check("① 20일 된 폴더 → 삭제", not a_old.exists() and not b_old.exists(),
          f"a={a_old.exists()} b={b_old.exists()}")
    check("② 오늘 폴더 → 보존", a_recent.exists() and b_recent.exists())
    check("③ .sessions 는 오래돼도 보존",
          a_sessions.exists() and (a_sessions / "grok-session-id").exists())
    check("④ dbg.log 는 오래돼도 보존", a_dbg.exists())
    check("⑤ 안에 최근 파일이 있는 폴더 → 보존", a_mixed.exists())

    log = home / ".claude/_audit/exchange-prune.log"
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    ok_log = len(lines) == 2 and all(len(ln.split("\t")) == 3 for ln in lines)
    check("⑥ 로그에 삭제 건마다 날짜·경로·mtime 3열", ok_log, f"lines={lines}")
    if lines:
        print(f"   로그 예시: {lines[0]}")

    outside = base / "outside-root"
    o_old, o_recent, *_ = build(outside)
    escape = home / "grok-exchange" / ".." / "escape-root"
    (home / "escape-root").mkdir()
    e_old, e_recent, *_ = build(home / "escape-root")
    r = run([outside, escape], home)
    check("⑧ 교환 폴더 밖·`..` 탈출 뿌리 → 삭제 0", r.returncode == 0 and o_old.exists() and e_old.exists(),
          f"outside={o_old.exists()} escape={e_old.exists()} err={r.stderr.strip()[:120]!r}")
    # WHY: 일수 0 은 기한이 «지금» 이라 전부 지운다 — 양의 정수가 아니면 기본 14일로 되돌아가 최근 폴더가 남아야 한다
    fresh = home / "codex-exchange" / "fresh_again"
    fresh.mkdir()
    (fresh / "x.md").write_text("x\n", encoding="utf-8")
    for bad in ("0", "-5", "abc"):
        run([root_b], home, extra_env={"EXCHANGE_PRUNE_DAYS": bad})
        check(f"⑨ EXCHANGE_PRUNE_DAYS={bad!r} → 기본 14일로 복귀(최근 폴더 보존)", fresh.exists() and b_recent.exists())

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} (14 checks)")
sys.exit(1 if fail else 0)
