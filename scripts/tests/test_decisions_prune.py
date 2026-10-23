#!/usr/bin/env python3
"""decisions-prune.sh 회귀 테스트 (2026-10-17 G2·G5-1 신설) — 항목 경계·7일 컷·아카이브 append·하루 1회·잠금.

격리: 임시 HOME(폴더별 마커 `_usage/decisions-prune-last-<프로젝트 폴더명>`) + 임시 memory 폴더. 실제 decisions.md 는 건드리지 않는다.
실행: python3 ~/.claude/scripts/tests/test_decisions_prune.py → 실패 0 이면 exit 0
"""
import fcntl
import os
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

SH = str(Path(__file__).resolve().parent.parent / "decisions-prune.sh")
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def d(n):
    return (date.today() - timedelta(days=n)).isoformat()


def make(tmp, body):
    home = Path(tmp) / "home"
    (home / ".claude/_usage").mkdir(parents=True)
    mem = Path(tmp) / "mem"
    (mem / "short-term").mkdir(parents=True)
    (mem / "short-term/decisions.md").write_text(body, encoding="utf-8")
    return home, mem


def marker_of(home, mem):
    """폴더별 하루 마커: `_usage/decisions-prune-last-<프로젝트 폴더명>` (프로젝트 폴더 = memory 의 부모)."""
    return home / ".claude/_usage" / ("decisions-prune-last-" + mem.parent.name)


def run(home, mem):
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(["bash", SH, str(mem)], capture_output=True, text=True, env=env)


def test_boundaries_and_cut():
    body = (
        "# 합의 결정 이력 (short-term, 7일)\n\n"
        f"- {d(1)} 최근 항목 A\n  A 계속 행\n\n"
        f"- {d(30)} 오래된 항목 B\n  B 계속 행\n\n## 소제목은 B 에 붙는다\n- 불릿은 계속 행\n\n"
        f"- {d(7)} 정확히 7일 전 항목 C\n"
        f"- {d(8)} 8일 전 항목 D 23:xx\n  D 계속 행\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        home, mem = make(tmp, body)
        r = run(home, mem)
        kept = (mem / "short-term/decisions.md").read_text(encoding="utf-8")
        arc = (mem / "short-term/decisions-archive.md").read_text(encoding="utf-8")
        check("출력은 옮긴 건수 한 줄(2건: B·D)", r.returncode == 0 and "2건" in r.stdout and len(r.stdout.strip().splitlines()) == 1, r.stdout + r.stderr)
        check("머리말과 최근·정확히 7일 항목은 남음", kept.startswith("# 합의 결정 이력") and "항목 A" in kept and "A 계속 행" in kept and "항목 C" in kept, kept)
        check("7일 초과 항목(B·D)은 본문에서 빠짐", "항목 B" not in kept and "항목 D" not in kept, kept)
        check("아카이브에 B·D 와 계속 행·소제목이 붙음", all(s in arc for s in ("항목 B", "B 계속 행", "## 소제목은 B 에 붙는다", "불릿은 계속 행", "항목 D", "D 계속 행")), arc)
        check("아카이브에 남은 항목은 없음", "항목 A" not in arc and "항목 C" not in arc, arc)
        check("남은 줄 + 옮긴 줄 = 원문 줄(손실 0)",
              len(kept.splitlines()) + len(arc.splitlines()) - 2 == len(body.splitlines()),
              f"{len(kept.splitlines())} {len(arc.splitlines())} {len(body.splitlines())}")


def test_archive_append_and_daily_marker():
    body = f"# 머리\n\n- {d(20)} 항목 X\n"
    with tempfile.TemporaryDirectory() as tmp:
        home, mem = make(tmp, body)
        (mem / "short-term/decisions-archive.md").write_text("# 기존 아카이브\n- 2026-01-01 옛 항목\n", encoding="utf-8")
        run(home, mem)
        arc = (mem / "short-term/decisions-archive.md").read_text(encoding="utf-8")
        check("기존 아카이브 뒤에 append(덮어쓰기 아님)", arc.startswith("# 기존 아카이브") and "옛 항목" in arc and "항목 X" in arc, arc)
        marker = marker_of(home, mem)
        check("마커에 날짜 기록", marker.exists() and marker.read_text().startswith(date.today().isoformat()))
        # 같은 날 다시 — 새 오래된 항목이 생겨도 건너뜀
        p = mem / "short-term/decisions.md"
        p.write_text(p.read_text(encoding="utf-8") + f"- {d(40)} 항목 Y\n", encoding="utf-8")
        r = run(home, mem)
        check("같은 날 재실행은 무출력·불변", r.stdout == "" and "항목 Y" in p.read_text(encoding="utf-8"), r.stdout)
        marker.write_text("2000-01-01 " + str(mem) + "\n")
        r = run(home, mem)
        check("마커가 어제 날짜면 다시 돎", "1건" in r.stdout and "항목 Y" not in p.read_text(encoding="utf-8"), r.stdout)
        marker.write_text(date.today().isoformat() + " /다른/폴더\n")
        p.write_text(p.read_text(encoding="utf-8") + f"- {d(50)} 항목 Z\n", encoding="utf-8")
        r = run(home, mem)
        check("마커의 폴더가 다르면 같은 날이어도 돎", "1건" in r.stdout, r.stdout)


def test_zero_entries_silent():
    with tempfile.TemporaryDirectory() as tmp:
        home, mem = make(tmp, f"# 머리\n\n- {d(1)} 최근뿐\n")
        before = (mem / "short-term/decisions.md").read_text(encoding="utf-8")
        r = run(home, mem)
        check("0건이면 무출력·본문 불변·아카이브 미생성",
              r.stdout == "" and (mem / "short-term/decisions.md").read_text(encoding="utf-8") == before
              and not (mem / "short-term/decisions-archive.md").exists(), r.stdout)
        check("0건이어도 하루 마커는 남김", marker_of(home, mem).exists())


def test_lock_busy_and_missing():
    with tempfile.TemporaryDirectory() as tmp:
        home, mem = make(tmp, f"# 머리\n\n- {d(30)} 오래됨\n")
        before = (mem / "short-term/decisions.md").read_text(encoding="utf-8")
        fd = os.open(str(mem / ".decisions-prune.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            r = run(home, mem)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        check("잠금 점유 중이면 조용히 건너뜀(exit 0·불변·마커 없음)",
              r.returncode == 0 and r.stdout == "" and (mem / "short-term/decisions.md").read_text(encoding="utf-8") == before
              and not marker_of(home, mem).exists(), f"{r.returncode} {r.stdout} {r.stderr}")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        (home / ".claude/_usage").mkdir(parents=True)
        r = run(home, Path(tmp) / "nope")
        check("폴더·파일이 없으면 exit 0 무출력", r.returncode == 0 and r.stdout == "" and r.stderr == "")


def test_bold_date_entries():
    """memory-write.md 작성 예시 꼴 `- **YYYY-MM-DD …**` 도 항목으로 인식한다(일반 날짜와 혼재 포함)."""
    body = (
        "# 머리\n\n"
        f"- **{d(30)} 굵은 오래된 항목 B1**\n  B1 계속 행\n"
        f"- {d(25)} 일반 오래된 항목 P1\n"
        f"- **{d(2)} 굵은 최근 항목 B2**\n  B2 계속 행\n"
        f"- **{d(9)} 굵은 8일 초과 항목 B3** 본문\n"
        f"- {d(1)} 일반 최근 항목 P2\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        home, mem = make(tmp, body)
        r = run(home, mem)
        kept = (mem / "short-term/decisions.md").read_text(encoding="utf-8")
        arc = (mem / "short-term/decisions-archive.md").read_text(encoding="utf-8")
        check("굵은·일반 혼재: 7일 초과 3건(B1·P1·B3) 이동", "3건" in r.stdout, r.stdout + r.stderr)
        check("굵은 오래된 항목과 계속 행이 아카이브로", "굵은 오래된 항목 B1" in arc and "B1 계속 행" in arc and "굵은 8일 초과 항목 B3" in arc and "일반 오래된 항목 P1" in arc, arc)
        check("굵은 최근 항목은 남음(계속 행 포함)·일반 최근도 남음", "굵은 최근 항목 B2" in kept and "B2 계속 행" in kept and "일반 최근 항목 P2" in kept, kept)
        check("이동한 항목은 본문에서 빠짐", all(s not in kept for s in ("B1", "P1", "B3")), kept)
    with tempfile.TemporaryDirectory() as tmp:
        home, mem = make(tmp, f"# 머리\n\n- **{d(1)} 굵은 최근만**\n")
        r = run(home, mem)
        check("굵은 날짜 최근 항목만이면 무출력·불변", r.stdout == "" and "굵은 최근만" in (mem / "short-term/decisions.md").read_text(encoding="utf-8"), r.stdout)


def test_stderr_not_swallowed():
    """lock 열기용 `exec 9>… 2>/dev/null` 이 스크립트 전체 stderr 를 닫던 결함(2026-10-17 검수) 회귀."""
    with tempfile.TemporaryDirectory() as tmp:
        home, mem = make(tmp, f"# 머리\n\n- {d(30)} 오래됨\n")
        (mem / "short-term/decisions-archive.md").mkdir()   # 아카이브 경로가 디렉터리라 이동이 실패한다
        before = (mem / "short-term/decisions.md").read_text(encoding="utf-8")
        r = run(home, mem)
        check("이동 실패 메시지가 stderr 로 나옴(exit 0)", r.returncode == 0 and "이동 실패" in r.stderr, f"{r.returncode} {r.stderr!r}")
        check("이동 실패 시 decisions.md 불변·마커 없음",
              (mem / "short-term/decisions.md").read_text(encoding="utf-8") == before and not marker_of(home, mem).exists())


def test_concurrent_write_aborts():
    """읽은 뒤 교체 전에 decisions.md 가 바뀌면(append 중) 중단하고 그 줄을 보존한다."""
    with tempfile.TemporaryDirectory() as tmp:
        home, mem = make(tmp, f"# 머리\n\n- {d(30)} 오래됨\n")
        dec = mem / "short-term/decisions.md"
        env = dict(os.environ, HOME=str(home), DECISIONS_PRUNE_TEST_SLEEP="1.5")
        p = subprocess.Popen(["bash", SH, str(mem)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        import time
        time.sleep(0.6)
        with open(dec, "a", encoding="utf-8") as f:
            f.write(f"- {d(0)} 그 사이에 들어온 새 항목\n")
        out, err = p.communicate(timeout=20)
        text = dec.read_text(encoding="utf-8")
        check("읽는 동안 바뀌면 중단 메시지", "바뀌어 중단" in err and out == "", f"out={out!r} err={err!r}")
        check("그 사이 append 된 줄이 보존됨(유실 0)", "그 사이에 들어온 새 항목" in text and "오래됨" in text, text)
        check("중단 시 아카이브 미생성·마커 없음(다음 실행이 재시도)",
              not (mem / "short-term/decisions-archive.md").exists() and not marker_of(home, mem).exists())
        r = run(home, mem)
        check("다음 실행은 정상 이동", "1건" in r.stdout and "그 사이에 들어온 새 항목" in dec.read_text(encoding="utf-8"), r.stdout + r.stderr)


for fn in (test_boundaries_and_cut, test_archive_append_and_daily_marker, test_zero_entries_silent, test_lock_busy_and_missing,
           test_bold_date_entries, test_stderr_not_swallowed, test_concurrent_write_aborts):
    fn()

fail = 0
for name, ok, detail in results:
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       실제: {detail[:400]}")
    fail += 0 if ok else 1
print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(results)} checks)")
sys.exit(1 if fail else 0)
