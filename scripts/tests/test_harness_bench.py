"""harness-bench.sh 회귀 시험 (2026-10-01 감사 P6 신설).

대상: 근거 경로 비교(심볼릭 링크 HOME/.claude 의 실경로 비교) · 지표 값 중복 거부 ·
      근거 실경로의 공백 거부 · 요약의 백슬래시 보존 · 도움말 범위.

격리: 임시 HOME 을 만들고 HOME/.claude 를 HOME/real/claude 로 가는 심볼릭 링크로 둔다
      (실제 서버의 ~/.claude → workspace/.claude 구조 재현). 실제 _bench 는 건드리지 않는다.

실행: python3 ~/.claude/scripts/tests/test_harness_bench.py → 실패 0 이면 exit 0
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
BENCH = str(SCRIPTS / "harness-bench.sh")
TOK = "attempts=1 interventions=0 qa_fail=0\n"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def make_home(tmp):
    home = Path(tmp) / "home"
    (home / "real/claude").mkdir(parents=True)
    (home / ".claude").symlink_to(home / "real/claude")
    (home / "work").mkdir()
    return home


def bench(home, *args):
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(["bash", BENCH, *args], capture_output=True, text=True, env=env, check=False)


def evidence(path, text=TOK):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def record(home, bid, summary):
    bench(home, "init", "t", bid)
    return bench(home, "before", bid, summary)


def test_paths_resolved_both_sides():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        ok = evidence(home / "work/qa-report-ok.md")
        r = record(home, "b-ok", f"{TOK.strip()} path={ok}")
        check("bench: 정상 근거는 기록(기준선)", r.returncode == 0, f"{r.returncode} {r.stderr[:200]}")

        inb = evidence(home / ".claude/_bench/qa-report-b.md")
        r = record(home, "b-bench", f"{TOK.strip()} path={inb}")
        check("bench: _bench 안 근거는 심볼릭 HOME/.claude 로 적어도 거부", r.returncode == 3,
              f"{r.returncode} {r.stderr[:200]}")

        tr = evidence(home / ".claude/projects/p/s.jsonl")
        r = record(home, "b-tr", f"{TOK.strip()} path={tr}")
        check("bench: 세션 transcript jsonl 근거 허용(링크 HOME/.claude/projects)", r.returncode == 0,
              f"{r.returncode} {r.stderr[:200]}")


def test_duplicate_metric_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        ok = evidence(home / "work/qa-report-ok.md")
        r = record(home, "b-dup", f"attempts=1 attempts=2 interventions=0 qa_fail=0 path={ok}")
        check("bench: 같은 지표 두 값은 기록 거부", r.returncode == 3 and "지표마다 값 하나만" in r.stderr,
              f"{r.returncode} {r.stderr[:200]}")

        # 손으로 쓴 벤치 파일: gate 도 중복 지표를 값 없음으로 취급해 inconclusive(2)
        d = Path(home / ".claude/_bench")
        d.mkdir(exist_ok=True)
        cyc = "- 사이클 {n} (2026-10-01T00:00:0{n}+09:00): attempts=1 attempts=2 interventions=0 qa_fail=0 evidence=x evidence_sha=y\n"
        body = "# b\n\n## Before\n" + "".join(cyc.format(n=i) for i in (1, 2, 3)) \
            + "\n## After\n" + "".join(cyc.format(n=i) for i in (4, 5, 6))
        (d / "b-hand.md").write_text(body, encoding="utf-8")
        g = bench(home, "gate", "b-hand")
        check("bench: gate 는 중복 지표 사이클을 inconclusive 로", g.returncode == 2 and "중복" in g.stdout,
              f"{g.returncode} {g.stdout[:200]}")


def test_whitespace_and_backslash():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        real = evidence(home / "work/sp ace/qa-report-real.md")
        link = home / "work/qa-report-link.md"
        link.symlink_to(real)
        r = record(home, "b-sp", f"{TOK.strip()} path={link}")
        check("bench: 공백이 든 근거 실경로는 거부", r.returncode == 3, f"{r.returncode} {r.stderr[:200]}")

        ok = evidence(home / "work/qa-report-ok.md")
        r = record(home, "b-bs", f"{TOK.strip()} memo=a\\tb path={ok}")
        text = (home / ".claude/_bench/b-bs.md").read_text(encoding="utf-8")
        ncyc = sum(1 for ln in text.splitlines() if ln.startswith("- 사이클"))
        check("bench: 요약의 백슬래시는 이스케이프로 해석되지 않고 한 줄 유지",
              r.returncode == 0 and "memo=a\\tb" in text and ncyc == 1,
              f"{r.returncode} {r.stderr[:100]} {text[-300:]!r}")


def test_help_range():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        out = bench(home, "help").stdout
        check("bench: 도움말에 gate·report·list 포함", all(k in out for k in ("gate", "report", "list")), out)


# 2026-10-17 G2: bench-last 마커는 측정을 만드는 init|before|after 에서만 찍힌다(gate·report·list·help 는 안 찍는다)
def test_marker_only_on_measuring_actions():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        marker = home / ".claude/_usage/bench-last"
        for act in (("list",), ("help",), ("report", "nope"), ("gate", "nope")):
            bench(home, *act)
            check(f"bench: {act[0]} 은 bench-last 를 찍지 않음", not marker.exists(), "")
        bench(home, "init", "t", "b-m")
        check("bench: init 은 bench-last 를 찍음", marker.exists(), "")
        marker.unlink()
        r = bench(home, "before", "b-m", TOK.strip())
        check("bench: 근거 없어 거부된 before(exit≠0)는 bench-last 를 찍지 않음", r.returncode != 0 and not marker.exists(), f"{r.returncode}")
        r = bench(home, "before", "없는ID", TOK.strip())
        check("bench: 존재하지 않는 벤치 ID before 실패도 마커 불변", r.returncode != 0 and not marker.exists(), f"{r.returncode}")
        r = bench(home, "init", "t", "b-m")
        check("bench: 중복 init 실패도 마커 불변", r.returncode != 0 and not marker.exists(), f"{r.returncode}")
        old = 1_000_000_000
        marker.touch()
        os.utime(marker, (old, old))
        bench(home, "before", "없는ID", TOK.strip())
        check("bench: 실패 호출 뒤 기존 마커 mtime 불변", int(marker.stat().st_mtime) == old, str(marker.stat().st_mtime))
        ok = evidence(home / "work/qa-report-m.md")
        r = bench(home, "before", "b-m", f"{TOK.strip()} path={ok}")
        check("bench: 성공한 before 는 마커 mtime 을 갱신", r.returncode == 0 and int(marker.stat().st_mtime) > old, f"{r.returncode} {r.stderr[:100]}")


# 2026-10-17 Codex 3차: 저장 명령이 실패해도 뒤의 echo 가 종료 코드를 0 으로 만들어 실패한 init·before 가 마커를 갱신하던 문제
def test_write_failure_is_failure():
    if os.geteuid() == 0:
        check("bench: 쓰기 실패 주입 시험은 root 에서 건너뜀(읽기 전용 폴더에도 쓰기 가능)", True, "")
        return
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        marker = home / ".claude/_usage/bench-last"
        ok = evidence(home / "work/qa-report-w.md")
        bench(home, "init", "t", "b-w")
        marker.unlink()
        marker.touch()
        os.utime(marker, (1_000_000_000, 1_000_000_000))
        bdir = home / ".claude/_bench"
        os.chmod(bdir, 0o555)
        try:
            r = bench(home, "before", "b-w", f"{TOK.strip()} path={ok}")
            check("bench: 읽기 전용이라 before 저장 실패 → 비0 종료·stderr·마커 mtime 불변",
                  r.returncode != 0 and "저장 실패" in r.stderr and int(marker.stat().st_mtime) == 1_000_000_000 and "✅" not in r.stdout, f"{r.returncode} {r.stderr[:160]} {r.stdout[:80]}")
            r = bench(home, "init", "t", "b-w2")
            check("bench: 읽기 전용이라 init 파일 생성 실패 → 비0 종료·파일 없음·마커 mtime 불변",
                  r.returncode != 0 and "생성 실패" in r.stderr and not (bdir / "b-w2.md").exists() and int(marker.stat().st_mtime) == 1_000_000_000 and "✅" not in r.stdout,
                  f"{r.returncode} {r.stderr[:160]} {r.stdout[:80]}")
        finally:
            os.chmod(bdir, 0o755)
        r = bench(home, "before", "b-w", f"{TOK.strip()} path={ok}")
        check("bench: 쓰기가 가능해지면 같은 호출이 성공하고 마커 갱신", r.returncode == 0 and int(marker.stat().st_mtime) > 1_000_000_000, f"{r.returncode} {r.stderr[:120]}")


for fn in (test_paths_resolved_both_sides, test_duplicate_metric_rejected, test_write_failure_is_failure,
           test_whitespace_and_backslash, test_help_range, test_marker_only_on_measuring_actions):
    fn()

fail = 0
for name, ok, detail in results:
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       실제: {detail[:300]}")
    fail += 0 if ok else 1

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(results)} checks)")
sys.exit(1 if fail else 0)
