"""harness-usage-check.sh 의 G2·G5-1 추가분 + agent-crosscheck.sh 회귀 테스트 (2026-10-17 신설).

대상: ① 7일 pending 자동 만료 호출·maintenance.log·잠금 실패 무시 ② CANDIDATES_PENDING digest 하루 1회
      ③ T41_REPEAT 때 후보 note 에 effect 기록(상태 불변·사람 note 보존) ④ MEMORY_INDEX_LONG(160줄)
      ⑤ decisions-prune 호출과 한 줄 보고 ⑥ crosscheck 7일 초과 → 잠금이 비면 백그라운드 --auto, 차 있으면 경보
      ⑦ agent-crosscheck.sh latest 신선도(일치 vs stale) · --auto 잠금 점유 시 무음 종료 · auto 열 append.

격리: 임시 HOME 에 scripts/ 를 **복사본**으로 두고(agent-crosscheck 는 시험 목적별 stub 또는 실물) cwd 는 임시 프로젝트 폴더.
      SessionStart 경로의 실행 환경(git·systemctl·crontab)은 실제 것을 쓰므로 단언은 대상 줄만 본다.
실행: python3 ~/.claude/scripts/tests/test_usage_check_t41_note.py → 실패 0 이면 exit 0
"""
import fcntl
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
HDR7 = "id\tsource\t생성일\tbench_id\tstatus\t요약\tnote\n"
TODAY = date.today().isoformat()
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def d(n):
    return (date.today() - timedelta(days=n)).isoformat()


# stub: `latest` 는 실물(agent-crosscheck-real.sh)에 위임하고(신선도 판정은 실물 로직을 시험), --auto 는 실행 표지만 남긴다
STUB = ('#!/usr/bin/env bash\n'
        'if [ "${1:-}" = latest ]; then exec bash "$HOME/.claude/scripts/agent-crosscheck-real.sh" latest; fi\n'
        'printf "%s\\n" "$*" > "$HOME/.claude/_usage/stub-ran"\n')


def iso_ago(days=0, hours=0):
    return (datetime.now().astimezone() - timedelta(days=days, hours=hours)).isoformat(timespec="seconds")


def write_cc(home, days=0, hours=0, verdict="일치"):
    (home / ".claude/_evolve/crosscheck.tsv").write_text(f"{iso_ago(days, hours)}\tD\t1\t1\t{verdict}\n", encoding="utf-8")


def make_env(tmp, rows=(), stub_crosscheck=True, projname="proj"):
    home = Path(tmp) / "home"
    claude = home / ".claude"
    for sub in ("_evolve", "_usage", "_audit", "agents", "scripts", "projects"):
        (claude / sub).mkdir(parents=True)
    for n in ("harness-usage-check.sh", "candidates-append.sh", "decisions-prune.sh", "agent-crosscheck.sh", "role-alias.sh",
              "harness_registry.py"):
        shutil.copy(SCRIPTS / n, claude / "scripts" / n)
    # The fixed short-term root now comes from the host registry (config/hosts/<hostname>.json, 2026-11-10).
    (claude / "config/hosts").mkdir(parents=True)
    (claude / "config/hosts" / f"{socket.gethostname()}.json").write_text(
        '{"paths": {"short_term_root": "~/.claude/projects/-home-user-workspace/memory/"}}', encoding="utf-8")
    shutil.copy(SCRIPTS / "agent-crosscheck.sh", claude / "scripts/agent-crosscheck-real.sh")
    if stub_crosscheck:
        (claude / "scripts/agent-crosscheck.sh").write_text(STUB, encoding="utf-8")
    (claude / "_evolve/candidates.tsv").write_text(HDR7 + "".join(r + "\n" for r in rows), encoding="utf-8")
    # 교차검증이 신선하다고 두어 기본 상태에서 crosscheck 분기가 조용하게 한다
    write_cc(home)
    proj = Path(tmp) / projname
    proj.mkdir()
    return home, proj


def run_usage(home, proj, timeout=60, **extra_env):
    env = dict(os.environ, HOME=str(home), **extra_env)
    r = subprocess.run(["bash", str(home / ".claude/scripts/harness-usage-check.sh")], capture_output=True, text=True,
                       env=env, cwd=str(proj), timeout=timeout, check=False)
    return r.stdout


def cand_rows(home):
    return [l.split("\t") for l in (home / ".claude/_evolve/candidates.tsv").read_text(encoding="utf-8").splitlines()[1:]]


def mem_dir(home, proj):
    name = "".join(c if c.isalnum() and c.isascii() else "-" for c in os.path.realpath(proj))
    p = home / ".claude/projects" / name / "memory"
    p.mkdir(parents=True, exist_ok=True)
    return p


def wait_for(path, secs=5.0):
    t0 = time.time()
    while time.time() - t0 < secs:
        if path.exists():
            return True
        time.sleep(0.1)
    return False


def test_expire_in_usage_check():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [
            f"T12-1\tT12\t{d(30)}\t-\tpending\t오래된 교정",
            f"T12-2\tT12\t{d(30)}\t-\tpending\t검토 중인 교정\t사람 note",
            f"T12-3\tT12\t{d(1)}\t-\tpending\t새 교정",
            f"T12-4\tT12\t{d(30)}\t-\tpending\t기계 비고만 있는 교정\tkw=왜",
        ])
        out = run_usage(home, proj)
        st = {r[0]: r[4] for r in cand_rows(home)}
        check("expire: 보호 note 없는(빈 값·kw=) 7일 초과 pending 만 expired",
              st == {"T12-1": "expired", "T12-2": "pending", "T12-3": "pending", "T12-4": "expired"}, str(st))
        check("expire: 훅 출력에는 변경 건수 한 줄만", "CANDIDATES_EXPIRED(2건)" in out and "expire:" not in out and "생성일 <" not in out, out)
        check("Grok7③: 만료 안내 문구가 «사람 비고·effect:recurred 행 제외»(기계 비고는 보호가 아님)", "사람 비고·effect:recurred 행 제외" in out and "note 있는 행 제외" not in out, out)
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("expire: maintenance.log 에 rc 와 원문 stdout", "expire rc=0" in log and "expire: 2건" in log, log)
        check("expire: 추가분 계측 added_ms 기록", "added_ms=" in log, log)
        check("expire: reviewed-last 불변", not (home / ".claude/_usage/candidates-reviewed-last").exists())

    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-1\tT12\t{d(30)}\t-\tpending\t오래된 교정"])
        fd = os.open(str(home / ".claude/_evolve/candidates.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            t0 = time.time()
            out = run_usage(home, proj)
            dt = time.time() - t0
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        check("expire 잠금 실패(exit 3)는 조용히 건너뜀·나머지 경보 계속",
              "EXPIRE_FAIL" not in out and cand_rows(home)[0][4] == "pending" and "CANDIDATES_PENDING" in out, out)
        check("잠금 대기로 훅이 오래 멈추지 않음", dt < 20, f"{dt:.1f}s")


def test_maintenance_log_rotation():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        log = home / ".claude/_usage/maintenance.log"
        log.write_text("".join(f"line{i}\n" for i in range(1100)), encoding="utf-8")
        run_usage(home, proj)
        lines = log.read_text(encoding="utf-8").splitlines()
        check("maintenance.log 1000줄 초과 → 마지막 500줄 + 이번 실행분", 500 <= len(lines) <= 510 and lines[0] == "line600" and "line1099" in lines, f"{len(lines)} {lines[:1]}")
        check("회전 임시 파일이 남지 않음", not list(log.parent.glob("maintenance.log.tmp.*")))
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        log = home / ".claude/_usage/maintenance.log"
        log.write_text("".join(f"line{i}\n" for i in range(900)), encoding="utf-8")
        run_usage(home, proj)
        check("1000줄 이하는 자르지 않음", len(log.read_text(encoding="utf-8").splitlines()) >= 900)


def test_digest_once_per_day():
    rows = [f"T12-{i}\tT12\t{d(i)}\t-\tpending\t교정 요약 {i}" for i in (1, 2, 3, 4)] + [
        f"T40-1\tT40\t{d(5)}\t-\tpending\t반복 패턴 요약"]
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, rows)
        out = run_usage(home, proj)
        lines = [l for l in out.splitlines() if l.startswith("  · ")]
        check("digest: 5건, 교정(T12)이 그 밖(T40)보다 먼저·같은 급은 오래된 순(2026-11-12)",
              len(lines) == 5 and [ln.split()[1] for ln in lines] == ["T12-4", "T12-3", "T12-2", "T12-1", "T40-1"], "\n".join(lines))
        check("digest: 마무리 한 줄", "→ 첫 작업성 응답 끝에 결정 팝업 하나로 판정을 묻는다(후보마다 accepted/rejected/보류, 모바일 모드면 AskUserQuestion)" in out, out)
        check("digest: CANDIDATES_PENDING 경보와 함께", "CANDIDATES_PENDING: 5건" in out, out)
        marker = home / f".claude/_usage/candidates-digest-{TODAY}.d"
        check("digest: 오늘 선점 디렉터리가 생김(mkdir 원자 마커)", marker.is_dir())
        out2 = run_usage(home, proj)
        check("digest: 같은 날 두 번째는 출력 안 함", "  · " not in out2 and "→ 첫 작업성" not in out2 and "CANDIDATES_PENDING" in out2, out2)
        marker.rmdir()   # 다음 날을 흉내(어제 것은 치워지고 오늘 것은 없는 상태)
        out3 = run_usage(home, proj)
        check("digest: 마커가 지난 날짜면 다시 출력", "  · T40-1" in out3, out3)
        check("digest: 대장은 변하지 않음(상태 불변)", all(r[4] == "pending" for r in cand_rows(home)))
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-1\tT12\t{d(1)}\t-\taccepted\t끝난 것"])
        out = run_usage(home, proj)
        check("digest: 미결이 없으면 출력 없음", "  · " not in out and not (home / f".claude/_usage/candidates-digest-{TODAY}.d").exists(), out)


def test_t41_effect_note():
    hist = "# history\n" + "".join(f"- {TODAY} T41: coder/구현 정확성 — RESULT: FAIL {i}\n" for i in range(3))
    spawn = "".join(f"{TODAY}T01:0{i}:00+09:00\tpost\t{role} \tn{i} \tsonnet \td\n"
                    for i, role in enumerate(("qa", "qa", "coder")))
    rows = [
        f"T41-a\tT41\t{d(3)}\t-\tpending\tcoder/구현 정확성: RESULT: FAIL",
        f"T41-b\tT41\t{d(3)}\t-\tpending\tqa/범위 준수: RESULT: BLOCKED",
        f"T41-c\tT41\t{d(3)}\t-\tpending\tcoder/구현 정확성: 사람이 본 것\t사람이 남긴 판정 기록",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, rows)
        (home / ".claude/_audit/history.md").write_text(hist, encoding="utf-8")
        (home / ".claude/_audit/agent-spawn.log").write_text(spawn, encoding="utf-8")
        out = run_usage(home, proj)
        r = {x[0]: x for x in cand_rows(home)}
        check("T41_REPEAT 발화 확인", "T41_REPEAT: coder/구현 정확성 ×3" in out, out)
        check("effect: 후보 생성일 이후 재발 → recurred k=3", r["T41-a"][6] == "effect:recurred k=3", str(r["T41-a"]))
        check("effect: 재발 없고 역할 소집 2건 → quiet n_spawn=2", r["T41-b"][6] == "effect:quiet n_spawn=2", str(r["T41-b"]))
        check("effect: 사람이 남긴 note 는 덮어쓰지 않음", r["T41-c"][6] == "사람이 남긴 판정 기록", str(r["T41-c"]))
        check("effect: 상태는 전부 pending 그대로", all(x[4] == "pending" for x in r.values()), str([x[4] for x in r.values()]))
        check("effect: 하루 1회 선점 디렉터리", (home / f".claude/_usage/t41-effect-{TODAY}.d").is_dir())
        # 같은 날 spawn 이 늘어도 다시 쓰지 않는다
        with open(home / ".claude/_audit/agent-spawn.log", "a", encoding="utf-8") as f:
            f.write(f"{TODAY}T02:00:00+09:00\tpost\tqa \tn9 \tsonnet \td\n")
        run_usage(home, proj)
        check("effect: 같은 날 두 번째 실행은 기록 안 함", {x[0]: x for x in cand_rows(home)}["T41-b"][6] == "effect:quiet n_spawn=2")
        # 마커를 지워 다음 날을 흉내
        shutil.rmtree(home / f".claude/_usage/t41-effect-{TODAY}.d")   # done 표지가 든 선점 디렉터리를 치워 다음 날을 흉내
        run_usage(home, proj)
        check("effect: 다음 날에는 갱신(소집 3건)", {x[0]: x for x in cand_rows(home)}["T41-b"][6] == "effect:quiet n_spawn=3")
    # ② 3회 문턱 아래 재발(1건)이어도 미결 T41 후보가 있으면 effect:recurred 가 기록된다(T41_REPEAT 와 무관)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [rows[0]])
        (home / ".claude/_audit/history.md").write_text("# history\n" + hist_lines("coder/구현 정확성", 0), encoding="utf-8")
        out = run_usage(home, proj)
        row = cand_rows(home)[0]
        check("effect: T41_REPEAT 없이(재발 1건) 미결 T41 이 있으면 recurred k=1 기록", "T41_REPEAT" not in out and row[6] == "effect:recurred k=1", f"{row} {out}")
    # 미결 T41 이 없으면(T12 뿐) 기록도 선점도 하지 않는다
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-1\tT12\t{d(1)}\t-\tpending\t교정"])
        (home / ".claude/_audit/history.md").write_text("# history\n", encoding="utf-8")
        run_usage(home, proj)
        row = cand_rows(home)[0]
        check("effect: 미결 T41 이 없으면 note 를 쓰지 않고 선점도 안 함", (len(row) < 7 or row[6] == "") and not (home / f".claude/_usage/t41-effect-{TODAY}.d").exists(), str(row))
    # 50칸 상한: 이미 recurred 인 행 50개가 새 후보의 효과 기록을 막지 않는다
    axis = "coder/구현 정확성"
    with tempfile.TemporaryDirectory() as tmp:
        rr = [f"T41-r{i:02d}\tT41\t{d(2)}\t-\tpending-bench\t{axis}: 재발 {i}\teffect:recurred k=9" for i in range(50)]
        rr.append(f"T41-new\tT41\t{d(2)}\t-\tpending-bench\tqa/범위 준수: BLOCKED")
        home, proj = make_env(tmp, rr)
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        run_usage(home, proj)
        r2 = {x[0]: x for x in cand_rows(home)}
        check("effect: recurred 50행 뒤의 새 후보도 기록됨(recurred 행은 선정에서 제외)", r2["T41-new"][6].startswith("effect:"), str(r2["T41-new"]))
        check("effect: 기존 recurred 행 비고는 그대로", all(r2[f"T41-r{i:02d}"][6] == "effect:recurred k=9" for i in range(50)))


def hist_lines(axis, *days_ago):
    return "".join(f"- {d(n)} T41: {axis} — RESULT: FAIL\n" for n in days_ago)


def test_effect_aggregation_and_batch():
    axis = "coder/구현 정확성"
    # 재발 수: 20일 전 생성(pending-approval 이라 expire 대상 아님)·18/17/16일 전 재발 3건 → 전체 기간 집계 k=3 (14일 창이면 0 이었을 것)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-old\tT41\t{d(20)}\t-\tpending-approval\t{axis}: RESULT: FAIL"])
        (home / ".claude/_audit/history.md").write_text("# h\n" + hist_lines(axis, 18, 17, 16), encoding="utf-8")
        out = run_usage(home, proj)
        check("effect: 20일 전 생성·재발 3건 → recurred k=3", "T41_REPEAT" in out and cand_rows(home)[0][6] == "effect:recurred k=3", str(cand_rows(home)[0]) + out)
    # 생성일 당일 기록은 후보 자신이라 1건 제외: 당일 2건 + 이후 1건 → k=2
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-self\tT41\t{d(10)}\t-\tpending-bench\t{axis}: RESULT: FAIL"])
        (home / ".claude/_audit/history.md").write_text("# h\n" + hist_lines(axis, 10, 10, 5), encoding="utf-8")
        run_usage(home, proj)
        check("effect: 생성일 당일 2건(자기 1건 제외)+이후 1건 → k=2", cand_rows(home)[0][6] == "effect:recurred k=2", str(cand_rows(home)[0]))
    # 앞 10건 고정 금지: 보호 비고 행 10개 뒤의 11번째가 갱신된다
    with tempfile.TemporaryDirectory() as tmp:
        rows = [f"T41-h{i:02d}\tT41\t{d(2)}\t-\tpending-bench\t{axis}: 사람 {i}\t사람 판정 {i}" for i in range(10)]
        rows.append(f"T41-last\tT41\t{d(2)}\t-\tpending-bench\tqa/범위 준수: BLOCKED")
        home, proj = make_env(tmp, rows)
        (home / ".claude/_audit/history.md").write_text("# h\n" + hist_lines(axis, 1, 1, 1), encoding="utf-8")
        run_usage(home, proj)
        r = {x[0]: x for x in cand_rows(home)}
        check("effect: 보호 행 10개 뒤의 11번째도 갱신", r["T41-last"][6].startswith("effect:"), str(r["T41-last"]))
        check("effect: 보호 행 10개는 그대로", all(r[f"T41-h{i:02d}"][6] == f"사람 판정 {i}" for i in range(10)))
    # 잠금 경합: 일괄 갱신이 실패하면 오늘 선점을 풀어 다음 세션이 재시도한다(기록은 성공 뒤에만)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-c\tT41\t{d(2)}\t-\tpending-bench\t{axis}: RESULT: FAIL"])
        (home / ".claude/_audit/history.md").write_text("# h\n" + hist_lines(axis, 1, 1, 1), encoding="utf-8")
        fd = os.open(str(home / ".claude/_evolve/candidates.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            t0 = time.time()
            out = run_usage(home, proj)
            dt = time.time() - t0
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
        check("effect: 잠금 경합이면 비고 불변", len(cand_rows(home)[0]) < 7 or cand_rows(home)[0][6] == "", str(cand_rows(home)[0]))
        check("②③ 기록 실패 시 rmdir 하지 않고 failed 를 남김(done 없음)·T41_EFFECT_FAIL 경보", (edir / "failed").exists() and not (edir / "done").exists() and "T41_EFFECT_FAIL" in out, f"{list(edir.glob('*'))} {out[-200:]}")
        check("Grok7②: set-note-batch 실패 원인이 failed 표지와 경보에 적힘", "set-note-batch 실패(rc=" in (edir / "failed").read_text(encoding="utf-8") and "T41_EFFECT_FAIL(set-note-batch 실패(rc=" in out, f"{(edir / 'failed').read_text(encoding='utf-8')!r}")
        check("effect: 훅은 일괄 대기(5초 상한)를 넘겨 멈추지 않음", dt < 25, f"{dt:.1f}s")
        run_usage(home, proj)
        check("② 10분 안에는 다시 시도하지 않음(비고 불변)", len(cand_rows(home)[0]) < 7 or cand_rows(home)[0][6] == "", str(cand_rows(home)[0]))
        set_mtime(edir, minutes=20)
        run_usage(home, proj)
        check("② 10분이 지나면 다음 세션이 승계해 재시도·기록되고 done 이 생기며 failed 는 지워짐",
              cand_rows(home)[0][6].startswith("effect:") and (edir / "done").exists() and not (edir / "failed").exists(), f"{cand_rows(home)[0]} {list(edir.glob('*'))}")


def test_digest_parallel_single_output():
    rows = [f"T12-{i}\tT12\t{d(i)}\t-\tpending\t교정 요약 {i}" for i in (1, 2, 3)]
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, rows)
        env = dict(os.environ, HOME=str(home))
        procs = [subprocess.Popen(["bash", str(home / ".claude/scripts/harness-usage-check.sh")], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=env, cwd=str(proj)) for _ in range(5)]
        outs = [p.communicate()[0] for p in procs]
        n = sum(o.count("→ 첫 작업성 응답 끝에 결정 팝업 하나로 판정을 묻는다") for o in outs)
        check("digest: 병렬 5세션이어도 출력은 정확히 1회", n == 1, f"count={n}")


def test_memory_index_long_and_prune():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        md = mem_dir(home, proj)
        (md / "MEMORY.md").write_text("- 줄\n" * 160, encoding="utf-8")
        out = run_usage(home, proj)
        check("MEMORY.md 160줄은 경보 없음", "MEMORY_INDEX_LONG" not in out, out)
        (md / "MEMORY.md").write_text("- 줄\n" * 161, encoding="utf-8")
        out = run_usage(home, proj)
        check("MEMORY.md 161줄은 MEMORY_INDEX_LONG(161줄)", "MEMORY_INDEX_LONG(161줄)" in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        # cwd 에 `.` 가 든 경우: Claude Code 규칙은 `/` 와 `.` 를 모두 `-` 로 바꾼다(`/home/u/.claude` → `-home-u--claude`)
        home, proj = make_env(tmp, projname=".dot.proj")
        md = mem_dir(home, proj)
        check("시험 전제: 폴더 이름에 '.' 가 '-' 로 바뀌어 있음", "--dot-proj" in str(md) and "." not in md.parent.name, str(md))
        (md / "MEMORY.md").write_text("- 줄\n" * 161, encoding="utf-8")
        (md / "short-term").mkdir()
        (md / "short-term/decisions.md").write_text(f"# 머리\n\n- {d(20)} 오래됨\n", encoding="utf-8")
        out = run_usage(home, proj)
        check("cwd 에 '.' 가 있어도 MEMORY.md 를 찾음", "MEMORY_INDEX_LONG(161줄)" in out, out)
        check("cwd 에 '.' 가 있어도 decisions 정리가 돎", "DECISIONS_PRUNED(1건)" in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        out = run_usage(home, proj)
        check("현재 프로젝트 MEMORY.md 가 없으면 건너뜀", "MEMORY_INDEX_LONG" not in out)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        md = mem_dir(home, proj)
        (md / "short-term").mkdir()
        (md / "short-term/decisions.md").write_text(f"# 머리\n\n- {d(1)} 최근\n\n- {d(20)} 오래됨\n  계속\n", encoding="utf-8")
        out = run_usage(home, proj)
        check("prune: 훅 출력은 한 줄 보고뿐", "DECISIONS_PRUNED(1건)" in out and "decisions-prune:" not in out, out)
        arc = (md / "short-term/decisions-archive.md").read_text(encoding="utf-8")
        check("prune: 오래된 항목이 아카이브로 이동", "오래됨" in arc and "오래됨" not in (md / "short-term/decisions.md").read_text(encoding="utf-8"))
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("prune: 원문 stdout 은 maintenance.log 에", "prune decisions-prune: 1건" in log, log)
        out = run_usage(home, proj)
        check("prune: 같은 날 두 번째는 무보고", "DECISIONS_PRUNED" not in out, out)


def test_prune_targets_fixed_root_and_cwd_project():
    """decisions 정리 대상: short-term 고정 루트(-home-user-workspace) + cwd 기반 현재 프로젝트, 같으면 1회."""
    stub = '#!/usr/bin/env bash\nprintf "%s\\n" "$1" >> "$HOME/.claude/_usage/prune-calls"\n'

    def calls(home):
        p = home / ".claude/_usage/prune-calls"
        return p.read_text(encoding="utf-8").splitlines() if p.exists() else []

    def setup_stub(home):
        (home / ".claude/scripts/decisions-prune.sh").write_text(stub, encoding="utf-8")
        for root in (home / ".claude/projects/-home-user-workspace/memory", ):
            (root / "short-term").mkdir(parents=True, exist_ok=True)
            (root / "short-term/decisions.md").write_text("# x\n", encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        setup_stub(home)
        cur = mem_dir(home, proj)
        (cur / "short-term").mkdir()
        (cur / "short-term/decisions.md").write_text("# y\n", encoding="utf-8")
        run_usage(home, proj)
        fixed = str(home / ".claude/projects/-home-user-workspace/memory")
        check("두 폴더가 다르면 prune 을 두 번 호출(고정 루트 먼저)", calls(home) == [fixed, str(cur)], str(calls(home)))
    with tempfile.TemporaryDirectory() as tmp:
        home, _ = make_env(tmp)
        setup_stub(home)
        run_usage(home, Path("~/workspace"))   # cwd 에서 유도한 프로젝트 이름이 고정 루트와 같다(HOME 만 임시)
        fixed = str(home / ".claude/projects/-home-user-workspace/memory")
        check("두 폴더가 같으면 prune 을 한 번만 호출", calls(home) == [fixed], str(calls(home)))
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        (home / ".claude/scripts/decisions-prune.sh").write_text(stub, encoding="utf-8")   # 어느 폴더에도 decisions.md 없음
        run_usage(home, proj)
        check("decisions.md 가 없는 폴더는 호출하지 않음", calls(home) == [], str(calls(home)))
    # 실물 스크립트로: 고정 루트와 현재 프로젝트 둘 다 실제로 정리되고 마커가 폴더별로 생긴다
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        cur = mem_dir(home, proj)
        fixed = home / ".claude/projects/-home-user-workspace/memory"
        for root in (cur, fixed):
            (root / "short-term").mkdir(parents=True, exist_ok=True)
            (root / "short-term/decisions.md").write_text(f"# 머리\n\n- **{d(20)} 오래됨 {root.parent.name[-6:]}**\n", encoding="utf-8")
        out = run_usage(home, proj)
        check("실물: 두 폴더 모두 정리·보고 두 줄", out.count("DECISIONS_PRUNED(1건)") == 2
              and (cur / "short-term/decisions-archive.md").exists() and (fixed / "short-term/decisions-archive.md").exists(), out)
        names = sorted(p.name for p in (home / ".claude/_usage").glob("decisions-prune-last-*"))
        check("마커가 폴더별 파일로 생김", names == sorted(["decisions-prune-last-" + cur.parent.name, "decisions-prune-last--home-user-workspace"]), str(names))


def test_crosscheck_background_launch():
    def stub_marker(home):
        return home / ".claude/_usage/stub-ran"

    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        out = run_usage(home, proj)
        check("crosscheck 신선하면 자동 실행·경보 없음", "CROSSCHECK" not in out and not stub_marker(home).exists(), out)
        # 오래된 ts + **새 mtime**(방금 파일을 만진 것과 같음): mtime 으로 보면 신선하지만 latest 는 stale 로 본다
        write_cc(home, days=10)
        out = run_usage(home, proj)
        check("ts 가 7일 초과면 mtime 이 새것이어도 CROSSCHECK_AUTO 한 줄(경보 아님)", "CROSSCHECK_AUTO(10d)" in out and "CROSSCHECK_STALE" not in out, out)
        check("백그라운드로 --auto 실행됨", wait_for(stub_marker(home)) and "--auto" in stub_marker(home).read_text(), "")
        stub_marker(home).unlink()
        out = run_usage(home, proj)
        check("6시간 안에는 다시 띄우지 않고 종전 경보(폭주 방지)", "CROSSCHECK_STALE(10d)" in out and "CROSSCHECK_AUTO" not in out, out)
        time.sleep(0.4)
        check("두 번째에는 실행하지 않음", not stub_marker(home).exists())
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        write_cc(home, days=7, hours=23)
        out = run_usage(home, proj)
        check("7일 23시간은 정수 일수로는 7일이지만 stale 로 판정", "CROSSCHECK_AUTO(7d)" in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        write_cc(home, days=6, hours=23)
        out = run_usage(home, proj)
        check("6일 23시간은 신선", "CROSSCHECK" not in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        write_cc(home, days=0, verdict="분모 불일치")
        out = run_usage(home, proj)
        check("최신 판정이 일치가 아니면(방금 것이어도) 자동 실행 대상", "CROSSCHECK_AUTO(0d)" in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        write_cc(home, days=10)
        fd = os.open(str(home / ".claude/_usage/crosscheck.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            out = run_usage(home, proj)
            time.sleep(0.6)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        check("잠금이 차 있으면 종전 경보 CROSSCHECK_STALE(10d)", "CROSSCHECK_STALE(10d)" in out and "CROSSCHECK_AUTO" not in out, out)
        check("잠금이 차 있으면 실행하지 않음", not stub_marker(home).exists())
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        (home / ".claude/_evolve/crosscheck.tsv").unlink()
        out = run_usage(home, proj)
        check("기록 없음도 자동 실행 대상", "CROSSCHECK_AUTO(기록 없음)" in out and wait_for(stub_marker(home)), out)


def make_cc_home(tmp):
    """실물 agent-crosscheck.sh 용: 로그 1건 + transcript 의 Agent tool_use 1건(일치 판정이 되는 최소 구성)."""
    home = Path(tmp) / "home"
    claude = home / ".claude"
    for sub in ("_evolve", "_usage", "_audit", "projects/p1"):
        (claude / sub).mkdir(parents=True)
    (claude / "_audit/agent-spawn.log").write_text("2026-10-01T00:00:00+09:00\tpost\tcoder \tn \tsonnet \td\n", encoding="utf-8")
    (claude / "projects/p1/s.jsonl").write_text(agent_line("2026-10-02T00:00:00.000Z", "toolu_AAA1"), encoding="utf-8")
    return home


def agent_line(ts, *ids):
    """실제 transcript 형식의 assistant 한 줄: message.content 에 Agent tool_use 가 ids 개수만큼 든다."""
    blocks = ",".join(f'{{"type":"tool_use","name":"Agent","id":"{i}","input":{{}}}}' for i in ids)
    return f'{{"timestamp":"{ts}","type":"assistant","message":{{"content":[{{"type":"text","text":"x"}},{blocks}]}}}}\n'


def cc(home, *args):
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(["bash", str(SCRIPTS / "agent-crosscheck.sh"), *args], capture_output=True, text=True, env=env, check=False)


def test_crosscheck_without_jq_alerts():
    # 검수팀 8: jq 가 없으면 transcript 계수를 못 하므로 0건으로 세어 «일치» 로 오판하지 않고 «분모 미상: jq 없음» 으로 exit 2, 행도 append 하지 않는다.
    with tempfile.TemporaryDirectory() as tmp:
        home = make_cc_home(tmp)
        env = dict(os.environ, HOME=str(home), PATH=build_path_without(tmp, "jq"))
        r = subprocess.run(["bash", str(SCRIPTS / "agent-crosscheck.sh")], capture_output=True, text=True, env=env, check=False)
        tsv = home / ".claude/_evolve/crosscheck.tsv"
        check("검수팀 8: PATH 에 jq 없음 → exit 2·«분모 미상: jq 없음»·일치 판정 없음·crosscheck.tsv 불변", r.returncode == 2 and "분모 미상: jq 없음" in r.stdout and "판정=일치" not in r.stdout and not tsv.exists(), f"{r.returncode} {r.stdout} {r.stderr}")


def test_crosscheck_latest_and_auto():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_cc_home(tmp)
        tsv = home / ".claude/_evolve/crosscheck.tsv"
        r = cc(home, "latest")
        check("latest: 기록 없음 → exit 2", r.returncode == 2, r.stdout)
        fresh = (date.today() - timedelta(days=2)).isoformat() + "T10:00:00+09:00"
        tsv.write_text(f"{fresh}\t2026-10-01T00:00:00+09:00\t5\t5\t일치\n", encoding="utf-8")
        r = cc(home, "latest")
        check("latest: 일치 + 7일 이내 → exit 0", r.returncode == 0 and "stale" not in r.stdout, r.stdout)
        old = (date.today() - timedelta(days=9)).isoformat() + "T10:00:00+09:00"
        tsv.write_text(f"{old}\t2026-10-01T00:00:00+09:00\t5\t5\t일치\n", encoding="utf-8")
        r = cc(home, "latest")
        check("latest: 일치여도 7일 초과 → stale·exit 2", r.returncode == 2 and "stale" in r.stdout, r.stdout)
        tsv.write_text(f"{fresh}\t2026-10-01T00:00:00+09:00\t5\t9\t분모 불일치\n", encoding="utf-8")
        r = cc(home, "latest")
        check("latest: 최신인데 불일치 → exit 2", r.returncode == 2, r.stdout)
        tsv.write_text(f"{fresh}\tD\t5\t5\t일치\tauto\n", encoding="utf-8")
        r = cc(home, "latest")
        check("latest: auto 열이 붙은 행도 읽음(5열 소비자 호환)", r.returncode == 0, r.stdout)
        for label, ts, want in (("7일 23시간", iso_ago(7, 23), 2), ("7일 1분 전", (datetime.now().astimezone() - timedelta(days=7, minutes=1)).isoformat(timespec="seconds"), 2),
                                ("6일 23시간", iso_ago(6, 23), 0), ("미래 ts(+1시간)", (datetime.now().astimezone() + timedelta(hours=1)).isoformat(timespec="seconds"), 2)):
            tsv.write_text(f"{ts}\tD\t5\t5\t일치\n", encoding="utf-8")
            r = cc(home, "latest")
            check(f"latest: {label} → exit {want}" + (" (stale)" if want == 2 else ""), r.returncode == want and (want == 0 or "stale" in r.stdout), f"{r.returncode} {r.stdout}")

    with tempfile.TemporaryDirectory() as tmp:
        home = make_cc_home(tmp)
        tsv = home / ".claude/_evolve/crosscheck.tsv"
        r = cc(home, "--auto")
        row = tsv.read_text(encoding="utf-8").rstrip("\n").split("\t") if tsv.exists() else []
        check("--auto: 계수 성공 뒤 행 append·6열 auto", r.returncode == 0 and len(row) == 6 and row[4] == "일치" and row[5] == "auto", f"{r.stdout} {row}")
        n_before = len(tsv.read_text(encoding="utf-8").splitlines())
        r = cc(home)
        rows = tsv.read_text(encoding="utf-8").splitlines()
        check("수동 실행은 5열 그대로(auto 표식 없음)", len(rows) == n_before + 1 and len(rows[-1].split("\t")) == 5, str(rows))
        fd = os.open(str(home / ".claude/_usage/crosscheck.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            r = cc(home, "--auto")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        check("--auto: 잠금이 차 있으면 조용히 exit 0·행 추가 없음",
              r.returncode == 0 and r.stdout == "" and len(tsv.read_text(encoding="utf-8").splitlines()) == n_before + 1, f"{r.returncode} {r.stdout}")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_cc_home(tmp)
        (home / ".claude/_audit/agent-spawn.log").write_text("", encoding="utf-8")
        r = cc(home, "--auto")
        check("--auto: 계수 실패(로그 없음)는 행을 남기지 않음", r.returncode == 2 and not (home / ".claude/_evolve/crosscheck.tsv").exists(), r.stdout)


def set_mtime(path, days=0, minutes=0):
    t = time.time() - days * 86400 - minutes * 60
    os.utime(path, (t, t))


def test_pending_type_counts_and_unjudged_alarm():
    rows = [f"T12-{i}\tT12\t{d(1)}\t-\tpending\t교정 {i}" for i in (1, 2)] + [
        f"T40-1\tT40\t{d(2)}\t-\tpending-bench\t반복 패턴",
        f"T41-1\tT41\t{d(2)}\t-\tpending\tcoder/구현 정확성: a", f"T41-2\tT41\t{d(2)}\t-\tpending-approval\tqa/범위 준수: b",
        f"T41-3\tT41\t{d(40)}\t-\tpending\tqa/범위 준수: c\t사람이 보는 중",    # 7일 초과지만 보호 note 라 만료 안 됨(마커 없이 30일 초과 → ④ 경보 조건)
        f"T12-9\tT12\t{d(1)}\t-\taccepted\t끝난 것"]                            # 미결 집계에서 제외
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, rows)
        out = run_usage(home, proj)
        check("B1: CANDIDATES_PENDING 에 유형별 건수(T12 2·T40 1·T41 3)와 7일 초과 1건",
              "CANDIDATES_PENDING: 6건(신규 4 · 벤치 대기 1 · 승인 대기 1 · 7일 초과 1건 · T12 2·T40 1·T41 3)" in out, out)
        check("B2: 판정 마커가 없으면 CANDIDATES_UNJUDGED_30D(판정 기록 없음)", "CANDIDATES_UNJUDGED_30D: 30일 넘게 판정 0건(판정 기록 없음, 미결 6건)" in out, out)
        mark = home / ".claude/_usage/candidates-reviewed-last"
        mark.touch()
        set_mtime(mark, days=31)
        out = run_usage(home, proj)
        check("B2: 마커 mtime 31일 전이면 경보", "CANDIDATES_UNJUDGED_30D: 30일 넘게 판정 0건(미결 6건) → /learn-from-feedback" in out, out)
        set_mtime(mark, days=29, minutes=1)
        out = run_usage(home, proj)
        check("B2: 29일 전이면 경보 없음", "CANDIDATES_UNJUDGED_30D" not in out, out)
        set_mtime(mark, days=3)
        out = run_usage(home, proj)
        check("B2: 3일 전이면 경보 없음(PENDING 은 그대로)", "CANDIDATES_UNJUDGED_30D" not in out and "CANDIDATES_PENDING: 6건" in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-1\tT12\t{d(1)}\t-\taccepted\t끝난 것"])
        out = run_usage(home, proj)
        check("B2: 미결이 없으면 마커가 없어도 경보 없음", "CANDIDATES_UNJUDGED_30D" not in out, out)


def test_digest_rotates_by_day():
    ca_stub = ('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$HOME/.claude/_usage/ca-calls"\n'
               'case "$1" in expire) echo "expire: 0건을 expired 로 바꿈";; esac\nexit 0\n')
    fake_date = ('#!/bin/bash\n[ "${1:-}" = "+%j" ] && { echo "${FAKE_J:?}"; exit 0; }\nexec /usr/bin/date "$@"\n')

    def skip_of(home):
        calls = (home / ".claude/_usage/ca-calls").read_text(encoding="utf-8").splitlines()
        op = [c for c in calls if c.startswith("oldest-pending")]
        return int(op[-1].split("--skip ")[1].split()[0]) if op else None

    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-{i}\tT12\t{d(1 + i % 3)}\t-\tpending\t교정 {i}" for i in range(7)])
        (home / ".claude/scripts/candidates-append.sh").write_text(ca_stub, encoding="utf-8")
        bindir = Path(tmp) / "bin"
        bindir.mkdir()
        (bindir / "date").write_text(fake_date, encoding="utf-8")
        (bindir / "date").chmod(0o755)
        path = f"{bindir}:{os.environ['PATH']}"
        got = []
        for j in ("001", "002", "003", "004", "009"):
            for dd in home.joinpath(".claude/_usage").glob("candidates-digest-*.d"):
                dd.rmdir()
            (home / ".claude/_usage/ca-calls").unlink(missing_ok=True)
            run_usage(home, proj, PATH=path, FAKE_J=j)
            got.append(skip_of(home))
        check("B3: CP_N=7 이면 --skip 이 날짜(연중 일수 % 2)*5 로 회전(0/5, digest 5건 2026-11-12)", got == [5, 0, 5, 0, 5], str(got))
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-{i}\tT12\t{d(1 + i)}\t-\tpending\t교정 {i}" for i in range(3)])
        (home / ".claude/scripts/candidates-append.sh").write_text(ca_stub, encoding="utf-8")
        run_usage(home, proj)
        check("B3: CP_N<=5 이면 --skip 0", skip_of(home) == 0, "")
    today_j = int(date.today().strftime("%j"))
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-{i}\tT12\t{d(1 + i % 3)}\t-\tpending\t교정 {i}" for i in range(7)])
        (home / ".claude/scripts/candidates-append.sh").write_text(ca_stub, encoding="utf-8")
        run_usage(home, proj)
        check("B3: 실제 날짜로도 (오늘 일수 % 2)*5", skip_of(home) == (today_j % 2) * 5, f"{skip_of(home)} j={today_j}")


def test_crosscheck_attempt_and_success_markers():
    attempt, last = "crosscheck-auto-attempt", "crosscheck-auto-last"
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        write_cc(home, days=10)
        m = home / ".claude/_usage" / attempt
        m.touch()
        set_mtime(m, minutes=20)
        out = run_usage(home, proj)
        time.sleep(0.4)
        check("B4: 시도 마커가 20분 전이면 자동 실행 안 함·종전 경보", not (home / ".claude/_usage/stub-ran").exists() and "CROSSCHECK_STALE(10d)" in out and "CROSSCHECK_AUTO" not in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        write_cc(home, days=10)
        m = home / ".claude/_usage" / attempt
        m.touch()
        set_mtime(m, minutes=40)
        out = run_usage(home, proj)
        check("B4: 시도 마커가 40분 전이면 다시 띄움", "CROSSCHECK_AUTO(10d)" in out and wait_for(home / ".claude/_usage/stub-ran"), out)
        check("B4: 띄운 자리에서 시도 마커를 새로 찍고 성공 마커는 찍지 않음",
              time.time() - m.stat().st_mtime < 120 and not (home / ".claude/_usage" / last).exists(), "")
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        write_cc(home, days=10)
        m = home / ".claude/_usage" / last
        m.touch()
        set_mtime(m, minutes=180)
        out = run_usage(home, proj)
        time.sleep(0.4)
        check("B4: 성공 마커가 3시간 전이면(시도 마커 없어도) 자동 실행 안 함", not (home / ".claude/_usage/stub-ran").exists() and "CROSSCHECK_AUTO" not in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp)
        write_cc(home, days=10)
        m = home / ".claude/_usage" / last
        m.touch()
        set_mtime(m, minutes=400)
        out = run_usage(home, proj)
        check("B4: 성공 마커가 6시간 넘었으면 띄움", "CROSSCHECK_AUTO(10d)" in out, out)


def test_crosscheck_counts_multiple_agents_per_line():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_cc_home(tmp)
        (home / ".claude/_audit/agent-spawn.log").write_text("".join(f"2026-10-01T00:00:0{i}+09:00\tpost\tcoder \tn{i} \tsonnet \td\n" for i in range(2)), encoding="utf-8")
        (home / ".claude/projects/p1/s.jsonl").write_text(
            agent_line("2026-10-02T00:00:00.000Z", "toolu_AAA1", "toolu_AAA2")        # 한 줄에 Agent 2개
            + agent_line("2026-10-02T00:00:01.000Z", "toolu_AAA2")                    # 같은 id 중복 → 1회만
            + agent_line("2026-09-01T00:00:00.000Z", "toolu_OLD1")                    # D 이전 → 제외
            + '{"timestamp":"2026-10-02T00:00:02.000Z","type":"user","message":{"content":"\\"name\\":\\"Agent\\" 언급뿐"}}\n',  # 문자열 언급은 계수 안 함
            encoding="utf-8")
        r = cc(home)
        check("C1: 한 jsonl 줄에 Agent tool_use 2개 → transcript_agent_uniq=2·일치", "transcript_agent_uniq=2" in r.stdout and "판정=일치" in r.stdout and r.returncode == 0, r.stdout)
        row = (home / ".claude/_evolve/crosscheck.tsv").read_text(encoding="utf-8").rstrip("\n").split("\t")
        check("C1: crosscheck.tsv 의 transcript 열 = 2", row[3] == "2", str(row))


def test_crosscheck_auto_success_marker():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_cc_home(tmp)
        marker = home / ".claude/_usage/crosscheck-auto-last"
        cc(home)
        check("C2: 수동 실행은 성공 마커를 찍지 않음", not marker.exists(), "")
        r = cc(home, "--auto")
        check("C2: --auto 가 행을 append 한 직후 성공 마커를 찍음", r.returncode == 0 and marker.exists(), r.stdout)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_cc_home(tmp)
        (home / ".claude/_audit/agent-spawn.log").write_text("", encoding="utf-8")
        cc(home, "--auto")
        check("C2: --auto 계수 실패(append 없음)는 성공 마커를 찍지 않음", not (home / ".claude/_usage/crosscheck-auto-last").exists(), "")


def build_path_without(tmp, *names):
    """/usr/bin 의 모든 실행 파일을 링크한 PATH 전용 폴더에서 names 만 뺀다(그 명령이 없는 환경 모의)."""
    bindir = Path(tmp) / "bin-without"
    bindir.mkdir()
    for p in Path("/usr/bin").iterdir():
        if p.name not in names:
            (bindir / p.name).symlink_to(p)
    return str(bindir)


def make_repo(tmp):
    """커밋 1개짜리 임시 저장소 → (경로, 짧은 해시). attach-commit 이 해시 실재를 확인하는 HARNESS_GIT_DIR 용."""
    repo = Path(tmp) / "repo"
    repo.mkdir()
    genv = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")

    def g(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=str(repo), capture_output=True, text=True, env=genv, check=True)

    g("init", "-q")
    (repo / "f").write_text("1")
    g("add", ".")
    g("commit", "-q", "-m", "c1")
    return repo, g("rev-parse", "--short=7", "HEAD").stdout.strip()


def test_unjudged_alarm_without_marker_needs_old_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-1\tT12\t{d(3)}\t-\tpending\t최근 교정"])
        out = run_usage(home, proj)
        check("④ 마커가 없어도 미결이 전부 최근이면 경보 없음(첫날 오경보 제거)", "CANDIDATES_UNJUDGED_30D" not in out and "CANDIDATES_PENDING" in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-1\tT12\t{d(29)}\t-\tpending\t29일 된 교정\t사람 note"])
        out = run_usage(home, proj)
        check("④ 마커 없음·가장 이른 생성일 29일 → 경보 없음", "CANDIDATES_UNJUDGED_30D" not in out, out)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-1\tT12\t{d(31)}\t-\tpending\t31일 된 교정\t사람 note", f"T12-2\tT12\t{d(1)}\t-\tpending\t최근 교정"])
        out = run_usage(home, proj)
        check("④ 마커 없음·가장 이른 생성일 31일 → 경보(판정 기록 없음)", "CANDIDATES_UNJUDGED_30D: 30일 넘게 판정 0건(판정 기록 없음, 미결 2건)" in out, out)


def test_attach_retry_queue():
    with tempfile.TemporaryDirectory() as tmp:
        repo, h = make_repo(tmp)
        home, proj = make_env(tmp, [f"R-1\tT12\t{d(1)}\t-\tpending\t미결 교정", f"R-2\tT12\t{d(1)}\t-\taccepted\t선승인", f"R-3\tT12\t{d(1)}\t-\taccepted\t해시 없는 선승인"])
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text(f"R-1\t{h}\nR-2\t{h}\nR-3\tdeadbee\n", encoding="utf-8")
        out = run_usage(home, proj, HARNESS_GIT_DIR=str(repo))
        r = {x[0]: x for x in cand_rows(home)}
        check("② 재시도: pending 줄은 set accepted + commit=<해시>", r["R-1"][4] == "accepted" and r["R-1"][6] == f"commit={h}", str(r["R-1"]))
        check("② 재시도: 이미 accepted 줄은 attach-commit 으로 해시만 붙음", r["R-2"][4] == "accepted" and r["R-2"][6] == f"commit={h}", str(r["R-2"]))
        check("② 재시도: 실패한 줄(없는 해시)만 큐에 남고 성공한 줄은 지워짐", q.read_text(encoding="utf-8") == "R-3\tdeadbee\n", repr(q.read_text(encoding="utf-8")))
        check("② 재시도: 남은 줄이 있으면 한 줄 경보 CANDIDATES_ATTACH_RETRY 1건", "CANDIDATES_ATTACH_RETRY 1건" in out, out)
        check("③ 재시도의 자동 set 은 --machine 이라 판정 마커를 만들지 않음", not (home / ".claude/_usage/candidates-reviewed-last").exists(), "")
        q.write_text(f"R-3\t{h}\n", encoding="utf-8")
        out = run_usage(home, proj, HARNESS_GIT_DIR=str(repo))
        check("② 재시도: 모두 성공하면 큐는 빈 파일로 남고(rm 없음) 경보 없음", q.exists() and q.read_text(encoding="utf-8") == "" and "CANDIDATES_ATTACH_RETRY" not in out and {x[0]: x for x in cand_rows(home)}["R-3"][6] == f"commit={h}", out)


def test_attach_retry_discards_impossible_lines():
    with tempfile.TemporaryDirectory() as tmp:
        repo, h = make_repo(tmp)
        home, proj = make_env(tmp, [f"R-1\tT12\t{d(1)}\t-\trejected\t기각됨", f"R-2\tT12\t{d(1)}\t-\texpired\t만료됨", f"R-3\tT12\t{d(1)}\t-\tpending\t미결",
                                    f"R-4\tT12\t{d(1)}\t-\texpired\t해시가 깨진 만료"])
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text(f"R-1\t{h}\nR-2\t{h}\nNOPE-9\t{h}\nR-3\t{h}\nR-4\tzzzz\n", encoding="utf-8")
        # 기대값 변경 근거(2026-10-17 team-lead 승인): 배수는 세션당 2줄 상한(바깥 훅 15초)이라 5줄 큐를 «2줄 → 2줄 → 1줄» 세션 3번으로 나눠 같은 최종 결과를 확인한다.
        run_usage(home, proj, HARNESS_GIT_DIR=str(repo))
        check("(b) 첫 세션은 2줄만 처리(R-1 rejected·R-2 expired 연결)하고 3줄이 큐에 남음", q.read_text(encoding="utf-8") == f"NOPE-9\t{h}\nR-3\t{h}\nR-4\tzzzz\n", repr(q.read_text(encoding="utf-8")))
        run_usage(home, proj, HARNESS_GIT_DIR=str(repo))
        check("(b) 둘째 세션은 NOPE-9·R-3 을 처리하고 R-4 한 줄이 남음", q.read_text(encoding="utf-8") == "R-4\tzzzz\n", repr(q.read_text(encoding="utf-8")))
        out = run_usage(home, proj, HARNESS_GIT_DIR=str(repo))
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        r = {x[0]: x for x in cand_rows(home)}
        check("(b) rejected·없는 id·set 이 실패하는 expired 줄은 큐에서 지워지고 영구 경보 없음", q.read_text(encoding="utf-8") == "" and "CANDIDATES_ATTACH_RETRY" not in out, f"{q.read_text(encoding='utf-8')!r} {out[-200:]}")
        check("(b) maintenance.log 에 'attach-retry 폐기: <id> <사유>' 한 줄씩(rejected·없는 id·expired set 실패)",
              "attach-retry 폐기: R-1 상태 rejected" in log and "attach-retry 폐기: NOPE-9 id 없음" in log and "attach-retry 폐기: R-4 상태 expired (set 실패 rc=1)" in log
              and "폐기: R-2" not in log and log.count("attach-retry 폐기") == 3, log)
        check("(b) 연결 가능한 줄(R-3 pending)은 정상 처리", r["R-3"][6] == f"commit={h}", str(cand_rows(home)))
        check("① 큐의 expired(R-2)는 폐기하지 않고 expired→accepted 예외로 연결(commit=<해시>)", r["R-2"][4] == "accepted" and r["R-2"][6] == f"commit={h}", str(r["R-2"]))


def test_retry_queue_keeps_transient_failures():
    with tempfile.TemporaryDirectory() as tmp:
        repo, h = make_repo(tmp)
        home, proj = make_env(tmp, [f"R-2\tT12\t{d(1)}\t-\texpired\t만료됨", f"R-3\tT12\t{d(1)}\t-\tpending\t미결"])
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text(f"R-2\t{h}\nR-3\t{h}\n", encoding="utf-8")
        before = (home / ".claude/_evolve/candidates.tsv").read_text(encoding="utf-8")
        fd = os.open(str(home / ".claude/_evolve/candidates.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            out = run_usage(home, proj, HARNESS_GIT_DIR=str(repo))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("Codex7: 잠금 보유 중 배수 → expired·pending 줄 모두 큐에 유지·대장 불변·폐기 로그 없음",
              q.read_text(encoding="utf-8") == f"R-2\t{h}\nR-3\t{h}\n" and (home / ".claude/_evolve/candidates.tsv").read_text(encoding="utf-8") == before and "attach-retry 폐기" not in log,
              f"{q.read_text(encoding='utf-8')!r} {log[-200:]}")
        check("Codex7: 일시 실패로 남은 줄은 경보(CANDIDATES_ATTACH_RETRY 2건)", "CANDIDATES_ATTACH_RETRY 2건" in out, out[-300:])
        run_usage(home, proj, HARNESS_GIT_DIR=str(repo))
        r = {x[0]: x for x in cand_rows(home)}
        check("Codex7: 잠금이 풀린 다음 세션에 재시도되어 둘 다 연결·큐 비움", r["R-2"][4] == "accepted" and r["R-2"][6] == f"commit={h}" and r["R-3"][6] == f"commit={h}" and q.read_text(encoding="utf-8") == "", f"{r['R-2']} {r['R-3']}")


def test_retry_accepted_attach_permanent_failure_discarded():
    # 검수팀 재확인 2: accepted 줄의 attach-commit 이 exit 1(영구 실패)이면 폐기 로그를 남기고 지워 뒷줄이 세션당 2줄 상한에 막히지 않는다. exit 3 은 일시 실패라 큐에 남는다.
    stub = ('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$HOME/.claude/_usage/stub-calls"\n'
            'case "$1" in attach-commit) exit "${STUB_ATTACH_RC:-0}";; expire) echo "expire: 0건을 expired 로 바꿈";; esac\nexit 0\n')
    rows = [f"Q-A\tT12\t{d(1)}\t-\taccepted\t선승인", f"Q-B\tT12\t{d(1)}\t-\tpending\t미결 B", f"Q-C\tT12\t{d(1)}\t-\tpending\t미결 C"]
    for rc, label in ((1, "exit 1"), (3, "exit 3")):
        with tempfile.TemporaryDirectory() as tmp:
            home, proj = make_env(tmp, rows)
            (home / ".claude/scripts/candidates-append.sh").write_text(stub, encoding="utf-8")
            q = home / ".claude/_usage/candidates-attach-retry.tsv"
            q.write_text("Q-A\taaaaaaa\nQ-B\tbbbbbbb\nQ-C\tccccccc\n", encoding="utf-8")
            run_usage(home, proj, STUB_ATTACH_RC=str(rc))
            log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
            left = q.read_text(encoding="utf-8")
            if rc == 1:
                check("검수팀 재확인 2: accepted attach-commit exit 1 → 폐기 로그·줄 제거·뒷줄(Q-B) 처리·세션 상한으로 Q-C 만 잔존",
                      "attach-retry 폐기: Q-A 상태 accepted (attach-commit 실패 rc=1)" in log and left == "Q-C\tccccccc\n", f"{left!r} {log[-250:]}")
            else:
                check("검수팀 재확인 2: accepted attach-commit exit 3(일시) → 줄 유지·폐기 로그 없음(상한 2줄이라 Q-C 도 남음)",
                      left == "Q-A\taaaaaaa\nQ-C\tccccccc\n" and "attach-retry 폐기" not in log, f"{left!r} {log[-250:]}")


def test_retry_queue_keeps_storage_failures():
    if os.geteuid() == 0:
        check("exit 5 큐 유지 시험은 root 에서 건너뜀", True, "")
        return
    with tempfile.TemporaryDirectory() as tmp:
        repo, h = make_repo(tmp)
        home, proj = make_env(tmp, [f"R-2\tT12\t{d(1)}\t-\texpired\t만료됨", f"R-3\tT12\t{d(1)}\t-\tpending\t미결"])
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text(f"R-2\t{h}\nR-3\t{h}\n", encoding="utf-8")
        (home / ".claude/_evolve/candidates.lock").touch()
        edir = home / ".claude/_evolve"
        before = (edir / "candidates.tsv").read_text(encoding="utf-8")
        os.chmod(edir, 0o555)
        try:
            run_usage(home, proj, HARNESS_GIT_DIR=str(repo))
        finally:
            os.chmod(edir, 0o755)
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("Codex8: 대장 저장 입출력 오류(exit 5) → expired·pending 줄 모두 큐에 유지·대장 불변·폐기 로그 없음",
              q.read_text(encoding="utf-8") == f"R-2\t{h}\nR-3\t{h}\n" and (edir / "candidates.tsv").read_text(encoding="utf-8") == before and "attach-retry 폐기" not in log, f"{q.read_text(encoding='utf-8')!r} {log[-250:]}")
        run_usage(home, proj, HARNESS_GIT_DIR=str(repo))
        check("Codex8: 쓰기가 가능해진 다음 세션에 둘 다 연결·큐 비움", q.read_text(encoding="utf-8") == "" and {x[0]: x for x in cand_rows(home)}["R-2"][4] == "accepted", str(cand_rows(home)))


def test_retry_rewrite_keeps_concurrent_updates():
    # 배수(set 호출) 도중 post-commit 이 같은 id 의 해시를 교체하고 새 id 를 덧붙이는 경합을 대역 candidates-append 가 흉내낸다.
    stub = ('#!/usr/bin/env bash\nQ="$HOME/.claude/_usage/candidates-attach-retry.tsv"\n'
            'case "$1" in\n'
            '  set) awk -F"\\t" -v OFS="\\t" \'$1=="R-1" {$2="bbbbbbb"} {print}\' "$Q" > "$Q.x" && mv "$Q.x" "$Q"; printf "R-NEW\\tccccccc\\n" >> "$Q"; exit 0 ;;\n'
            '  expire) echo "expire: 0건을 expired 로 바꿈"; exit 0 ;;\n'
            'esac\nexit 0\n')
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"R-1\tT12\t{d(1)}\t-\tpending\t미결", f"R-2\tT12\t{d(1)}\t-\tpending\t다른 미결", f"R-NEW\tT12\t{d(1)}\t-\tpending\t새 줄"])
        (home / ".claude/scripts/candidates-append.sh").write_text(stub, encoding="utf-8")
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text("R-1\taaaaaaa\nR-2\tdddddddd\n", encoding="utf-8")
        run_usage(home, proj)
        lines = q.read_text(encoding="utf-8").splitlines()
        check("Grok10 4: 배수 중 같은 id(R-1)의 해시가 교체됐으면 스냅샷 해시와 달라 줄을 남기고, 새로 덧붙은 R-NEW 도 보존",
              "R-1\tbbbbbbb" in lines and "R-NEW\tccccccc" in lines, str(lines))
        check("Grok10 4: 스냅샷과 id·해시가 모두 같고 성공한 줄(R-2)은 지워짐", not any(ln.startswith("R-2\t") for ln in lines), str(lines))


def test_retry_queue_keeps_lines_when_ledger_unreadable():
    # Grok 16차 1: 대장 읽기 실패(권한 0)·상태 조회 awk 실패를 «id 없음» 폐기로 오인하지 않고 큐 줄을 보존한다.
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"R-1\tT12\t{d(1)}\t-\tpending\t미결"])
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text("R-1\taaaaaaa\n", encoding="utf-8")
        run_usage(home, proj, PATH=awk_shim(tmp, ['ENVIRON["ID"]']))
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("Grok16 1: 상태 조회 awk 실패 → 줄 보존·폐기 로그 없음·조회 실패 로그", q.read_text(encoding="utf-8") == "R-1\taaaaaaa\n" and "attach-retry 폐기" not in log and "상태 조회 실패" in log, f"{q.read_text(encoding='utf-8')!r} {log[-250:]}")
    if os.geteuid() == 0:
        check("Grok16 1: 대장 권한 0 시험은 root 에서 건너뜀", True, "")
        return
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"R-1\tT12\t{d(1)}\t-\tpending\t미결"])
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text("R-1\taaaaaaa\n", encoding="utf-8")
        ledger = home / ".claude/_evolve/candidates.tsv"
        os.chmod(ledger, 0)
        try:
            run_usage(home, proj)
        finally:
            os.chmod(ledger, 0o644)
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("Grok16 1: 대장 권한 0 → 큐 불변·폐기 로그 없음·«대장 읽기 불가라 배수 건너뜀» 한 줄", q.read_text(encoding="utf-8") == "R-1\taaaaaaa\n" and "attach-retry 폐기" not in log and "대장 읽기 불가라 배수 건너뜀" in log, f"{q.read_text(encoding='utf-8')!r} {log[-250:]}")


def test_retry_drain_limited_to_two_per_session():
    # 검수팀 코드 검수 5: 바깥 훅 15초 안에 들도록 세션당 2줄만 처리하고 나머지는 큐에 남긴다.
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"R-{i}\tT12\t{d(1)}\t-\tpending\t미결 {i}" for i in (1, 2, 3)])
        stub = '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$HOME/.claude/_usage/stub-calls"\ncase "$1" in expire) echo "expire: 0건을 expired 로 바꿈";; esac\nexit 0\n'
        (home / ".claude/scripts/candidates-append.sh").write_text(stub, encoding="utf-8")
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text("R-1\taaaaaaa\nR-2\tbbbbbbb\nR-3\tccccccc\n", encoding="utf-8")
        run_usage(home, proj)
        calls = (home / ".claude/_usage/stub-calls").read_text(encoding="utf-8").splitlines()
        sets = [c for c in calls if c.startswith("set ")]
        check("검수팀 5: 3줄 큐 → 이번 세션은 2건만 처리하고 1줄(R-3) 잔존", len(sets) == 2 and q.read_text(encoding="utf-8") == "R-3\tccccccc\n", f"{sets} {q.read_text(encoding='utf-8')!r}")
        run_usage(home, proj)
        check("검수팀 5: 다음 세션이 남은 줄을 이어 처리", q.read_text(encoding="utf-8") == "", q.read_text(encoding="utf-8"))


def test_digest_axis_normalized():
    # Grok 16차 3: history 의 sec-g1/x 와 후보의 security/x 가 같은 축으로 비교돼 우선순위 0(같은 날짜면 T12 보다 먼저)을 받는다.
    hist = "# h\n" + "".join(f"- {TODAY} T41: sec-g1/x — RESULT: FAIL {i}\n" for i in range(3))
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-a\tT12\t{d(3)}\t-\tpending\t교정 요약", f"T41-s\tT41\t{d(3)}\t-\tpending\tsecurity/x: 보안 약점"])
        (home / ".claude/agents/security.md").write_text("x", encoding="utf-8")
        (home / ".claude/_audit/history.md").write_text(hist, encoding="utf-8")
        out = run_usage(home, proj)
        lines = [ln for ln in out.splitlines() if ln.startswith("  · ")]
        check("Grok16 3: sec-g1/x 기록 대 security/x 후보 → T41 후보가 같은 날 T12 보다 먼저", len(lines) == 2 and "T41-s" in lines[0], "\n".join(lines) + "\n" + out)


def test_expire_waits_for_effect_done():
    axis = "coder/구현 정확성"
    row = f"T41-q\tT41\t{d(8)}\t-\tpending\t{axis}: 조용한 후보\teffect:quiet n_spawn=0"
    logs = lambda h: (h / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:   # a) 다른 세션이 효과를 집계하는 중(선점 디렉터리만 있고 done 없음) → 이번 세션은 만료하지 않는다
        home, proj = make_env(tmp, [row])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        (home / f".claude/_usage/t41-effect-{TODAY}.d").mkdir()
        run_usage(home, proj)
        check("① 선점만 있고 done 없음 → 8일 된 후보를 만료하지 않고 maintenance.log 한 줄", cand_rows(home)[0][4] == "pending" and "expire 건너뜀: T41 효과 기록이 아직 끝나지 않음" in logs(home), f"{cand_rows(home)[0]}")
    with tempfile.TemporaryDirectory() as tmp:   # b) done 이 생기면 만료가 돈다
        home, proj = make_env(tmp, [row])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        dd = home / f".claude/_usage/t41-effect-{TODAY}.d"
        dd.mkdir()
        (dd / "done").touch()
        run_usage(home, proj)
        check("① done 이 있으면 만료 실행", cand_rows(home)[0][4] == "expired", str(cand_rows(home)[0]))
    with tempfile.TemporaryDirectory() as tmp:   # c) 선점 세션이 죽어 10분 넘게 done 이 없으면 만료 허용
        home, proj = make_env(tmp, [row])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        dd = home / f".claude/_usage/t41-effect-{TODAY}.d"
        dd.mkdir()
        set_mtime(dd, minutes=20)
        run_usage(home, proj)
        check("① ② 선점 디렉터리가 10분 넘게 done 없이 남으면(기록 세션 중단) 뒤 세션이 승계해 기록하고 done 을 만든 뒤 만료",
              cand_rows(home)[0][4] == "expired" and (dd / "done").exists(), f"{cand_rows(home)[0]} {(dd / 'done').exists()}")
    with tempfile.TemporaryDirectory() as tmp:   # d) 미결 T41 이 없으면 보호할 효과 기록이 없어 바로 만료
        home, proj = make_env(tmp, [f"T12-o\tT12\t{d(8)}\t-\tpending\t오래된 교정"])
        (home / f".claude/_usage/t41-effect-{TODAY}.d").mkdir()
        run_usage(home, proj)
        check("① 미결 T41 이 없으면 done 없이도 만료", cand_rows(home)[0][4] == "expired", str(cand_rows(home)[0]))
    with tempfile.TemporaryDirectory() as tmp:   # e) 단독 세션: 효과 기록이 끝나면 done 이 생기고 만료가 이어서 돈다
        home, proj = make_env(tmp, [row])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        run_usage(home, proj)
        check("① 단독 세션: 기록 완료 뒤 done 생성·만료 실행", (home / f".claude/_usage/t41-effect-{TODAY}.d/done").exists() and cand_rows(home)[0][4] == "expired", str(cand_rows(home)[0]))


def test_expire_skips_ids_in_retry_queue():
    stub = ('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$HOME/.claude/_usage/ca-calls"\n'
            'case "$1" in expire) echo "expire: 0건을 expired 로 바꿈";; set|attach-commit) exit 1;; esac\nexit 0\n')
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"R-8\tT12\t{d(8)}\t-\tpending\t큐에 남는 후보", f"R-9\tT12\t{d(8)}\t-\tpending\t다른 후보"])
        (home / ".claude/scripts/candidates-append.sh").write_text(stub, encoding="utf-8")
        (home / ".claude/_usage/candidates-attach-retry.tsv").write_text("R-8\tabc1234\n", encoding="utf-8")
        run_usage(home, proj)
        calls = (home / ".claude/_usage/ca-calls").read_text(encoding="utf-8").splitlines()
        exp = [i for i, c in enumerate(calls) if c.startswith("expire")]
        ret = [i for i, c in enumerate(calls) if c.startswith("set R-8")]
        check("② 순서: 재시도 큐 배수(set R-8) 다음에 expire", ret and exp and ret[0] < exp[0], str(calls))
        check("② 배수에 실패해 큐에 남은 id 는 expire --skip-ids 로 제외", exp and "--skip-ids R-8" in calls[exp[0]], str(calls))
    with tempfile.TemporaryDirectory() as tmp:   # 실물 expire: 큐의 id 는 8일이 지나도 pending 으로 남는다
        home, proj = make_env(tmp, [f"R-8\tT12\t{d(8)}\t-\tpending\t큐에 남는 후보", f"R-9\tT12\t{d(8)}\t-\tpending\t다른 후보"])
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text("R-8\tabc1234\n", encoding="utf-8")
        fd = os.open(str(home / ".claude/_evolve/candidates.lock"), os.O_CREAT | os.O_RDWR)   # set 이 잠금 실패(rc 3)로 큐에 남게 한다
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            run_usage(home, proj)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        check("② 큐 줄은 연결 실패로 남고 경보", q.read_text(encoding="utf-8") == "R-8\tabc1234\n", repr(q.read_text(encoding="utf-8")))
        out = run_usage(home, proj)
        st = {x[0]: x[4] for x in cand_rows(home)}
        check("② 실물: 큐의 R-8 은 만료되지 않고 다른 8일 후보 R-9 만 expired", st["R-9"] == "expired" and st["R-8"] in ("pending", "accepted"), f"{st} {out[-200:]}")


def test_retry_queue_lock_and_no_rm():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"R-1\tT12\t{d(1)}\t-\tpending\t미결"])
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text("R-1\tabc1234\n", encoding="utf-8")
        fd = os.open(str(home / ".claude/_usage/candidates-attach-retry.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            t0 = time.time()
            run_usage(home, proj)
            dt = time.time() - t0
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("③ 큐 잠금을 못 잡으면 소비자는 건너뜀(큐 불변·후보 pending)·만료도 건너뜀", q.read_text(encoding="utf-8") == "R-1\tabc1234\n" and cand_rows(home)[0][4] == "pending"
              and "expire 건너뜀: 재시도 큐 잠금" in log, f"{cand_rows(home)[0]} {log[-200:]} {dt:.1f}s")
        run_usage(home, proj)
        check("③ 잠금이 풀리면 배수되고 큐 파일은 빈 파일로 남음(rm 아님)", q.exists() and q.read_text(encoding="utf-8") == "" and cand_rows(home)[0][4] == "accepted", f"{q.exists()} {cand_rows(home)[0]}")


def test_role_alias_shared_with_effect_count():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-s\tT41\t{d(3)}\t-\tpending-bench\tsecurity/범위 준수: x", f"T41-t\tT41\t{d(3)}\t-\tpending-bench\tsec-g1/범위 준수: y"])
        for n in ("security", "qa", "coder"):
            (home / f".claude/agents/{n}.md").write_text("x", encoding="utf-8")
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        spawn = "".join(f"{TODAY}T01:0{i}:00+09:00\tpost\t{role} \tn{i} \tsonnet \td\n" for i, role in enumerate(("sec-g1", "sec-g1", "security", "qa")))
        (home / ".claude/_audit/agent-spawn.log").write_text(spawn, encoding="utf-8")
        r = subprocess.run(["bash", "-c", '. "$HOME/.claude/scripts/role-alias.sh"; normalize_role sec-g1; echo; normalize_role qa_v_rep; echo; normalize_role nobody'],
                           capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), check=False)
        check("⑤ role-alias.sh: normalize_role(sec-g1)=security·qa_v_rep=qa·표 밖은 빈 값", r.stdout.split("\n")[:3] == ["security", "qa", ""], repr(r.stdout))
        run_usage(home, proj)
        rr = {x[0]: x for x in cand_rows(home)}
        check("⑤ 효과 집계가 후보 역할과 소집 로그(sec-g1)를 같은 이름으로 정규화 → n_spawn=3", rr["T41-s"][6] == "effect:quiet n_spawn=3" and rr["T41-t"][6] == "effect:quiet n_spawn=3", f"{rr['T41-s']} {rr['T41-t']}")


def test_effect_axis_rule_and_limit_200():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-a\tT41\t{d(3)}\t-\tpending-bench\tcoder/구현 정확성 : 콜론 앞 공백"])
        (home / ".claude/_audit/history.md").write_text("# h\n" + hist_lines("coder/구현 정확성", 0), encoding="utf-8")
        run_usage(home, proj)
        check("⑨ 효과 집계의 축은 첫 ':' 앞(공백 제거) → recurred k=1", cand_rows(home)[0][6] == "effect:recurred k=1", str(cand_rows(home)[0]))
    with tempfile.TemporaryDirectory() as tmp:
        rr = [f"T41-n{i:03d}\tT41\t{d(2)}\t-\tpending-bench\tcoder/구현 정확성: 후보 {i}" for i in range(120)]
        home, proj = make_env(tmp, rr)
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        run_usage(home, proj, timeout=120)
        got = [x[6] if len(x) > 6 else "" for x in cand_rows(home)]
        check("⑥ 효과 기록 상한 200: 120개 후보 모두 기록(종전 50 이면 70개 누락)", all(g.startswith("effect:") for g in got), f"{sum(g.startswith('effect:') for g in got)}/120")


def test_effect_recorded_before_expire():
    axis = "coder/구현 정확성"
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-q\tT41\t{d(8)}\t-\tpending\t{axis}: 조용했던 후보\teffect:quiet n_spawn=0"])
        (home / ".claude/_audit/history.md").write_text("# h\n" + hist_lines(axis, 1), encoding="utf-8")
        out = run_usage(home, proj)
        row = cand_rows(home)[0]
        check("⑫ 8일 전 quiet 행 + 어제 재발 → 만료되지 않고 pending 에 effect:recurred k=1", row[4] == "pending" and row[6] == "effect:recurred k=1" and "CANDIDATES_EXPIRED" not in out, f"{row} {out[-300:]}")
        check("⑫ 하루 1회 선점 디렉터리는 그대로", (home / f".claude/_usage/t41-effect-{TODAY}.d").is_dir())
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-q\tT41\t{d(8)}\t-\tpending\t{axis}: 계속 조용\teffect:quiet n_spawn=0"])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        run_usage(home, proj)
        check("⑫ 재발이 없으면 종전처럼 8일 된 quiet 행은 만료", cand_rows(home)[0][4] == "expired", str(cand_rows(home)[0]))


def test_effect_selection_pending_first():
    axis = "coder/구현 정확성"
    with tempfile.TemporaryDirectory() as tmp:
        rr = [f"T41-b{i:03d}\tT41\t{d(20)}\t-\tpending-bench\t{axis}: 벤치 {i}\teffect:quiet n_spawn=0" for i in range(200)]
        rr.append(f"T41-p\tT41\t{d(8)}\t-\tpending\t{axis}: 맨 뒤의 pending\teffect:quiet n_spawn=0")
        home, proj = make_env(tmp, rr)
        (home / ".claude/_audit/history.md").write_text("# h\n" + hist_lines(axis, 1), encoding="utf-8")
        run_usage(home, proj, timeout=120)
        r = {x[0]: x for x in cand_rows(home)}
        check("③ 200칸을 bench 행이 채워도 pending 이 먼저 선정돼 effect:recurred 기록·만료 보호", r["T41-p"][4] == "pending" and r["T41-p"][6] == "effect:recurred k=1", str(r["T41-p"]))
        nb = sum(1 for k, x in r.items() if k.startswith("T41-b") and x[6].startswith("effect:recurred"))
        check("④ 미결 T41 201건이어도 상한 없이 전부 기록(bench 200개 모두)·done 생성", nb == 200 and (home / f".claude/_usage/t41-effect-{TODAY}.d/done").exists(), str(nb))


def test_expire_rc4_is_quiet():
    stub = '#!/usr/bin/env bash\ncase "$1" in expire) echo "candidates-append: 효과 기록 전이라 만료 보류" >&2; exit 4;; esac\nexit 0\n'
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T12-1\tT12\t{d(8)}\t-\tpending\t오래된 교정"])
        (home / ".claude/scripts/candidates-append.sh").write_text(stub, encoding="utf-8")
        out = run_usage(home, proj)
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("⑤ expire 가 exit 4 면 usage-check 는 조용히 건너뜀(실패 경보 없음)·로그에 rc=4", "CANDIDATES_EXPIRE_FAIL" not in out and "expire rc=4" in log, f"{out[-200:]} {log[-150:]}")


def test_effect_rec_axis_normalized():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-s\tT41\t{d(3)}\t-\tpending-bench\tsec-g1/범위 준수: 줄임말 축", f"T41-t\tT41\t{d(3)}\t-\tpending-bench\tsecurity/범위 준수: 정식 축"])
        (home / ".claude/agents/security.md").write_text("x", encoding="utf-8")
        (home / ".claude/_audit/history.md").write_text(f"# h\n- {d(1)} T41: security/범위 준수 — RESULT: BLOCKED\n- {d(1)} T41: sec-g1/범위 준수 — RESULT: BLOCKED\n", encoding="utf-8")
        run_usage(home, proj)
        r = {x[0]: x for x in cand_rows(home)}
        check("④ 후보 축 sec-g1/… 과 history security/… 가 정규화 뒤 같은 축으로 재발 집계(둘 다 k=2)", r["T41-s"][6] == "effect:recurred k=2" and r["T41-t"][6] == "effect:recurred k=2", f"{r['T41-s'][6]} {r['T41-t'][6]}")


def test_retry_queue_without_flock():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"R-1\tT12\t{d(1)}\t-\tpending\t미결"])
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text("R-1\tabc1234\n", encoding="utf-8")
        run_usage(home, proj, PATH=build_path_without(tmp, "flock"))
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("① flock 이 없으면 소비자는 큐를 읽거나 쓰지 않고(무잠금 진행 금지) 후보도 그대로", q.read_text(encoding="utf-8") == "R-1\tabc1234\n" and cand_rows(home)[0][4] == "pending" and "잠금 불가(flock 없음)" in log, f"{cand_rows(home)[0]} {log[-200:]}")


def test_effect_timeout_scales_with_rows():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-n{i:03d}\tT41\t{d(2)}\t-\tpending-bench\tcoder/구현 정확성: 후보 {i}" for i in range(250)])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        shim = Path(tmp) / "shim"
        shim.mkdir()
        (shim / "timeout").write_text('#!/bin/bash\nprintf "%s\\n" "$1" >> "$HOME/.claude/_usage/to-args"\nexec /usr/bin/timeout "$@"\n', encoding="utf-8")
        (shim / "timeout").chmod(0o755)
        run_usage(home, proj, timeout=120, PATH=f"{shim}:{os.environ['PATH']}")
        args = (home / ".claude/_usage/to-args").read_text(encoding="utf-8").split()
        check("⑥ 효과 기록 timeout 은 5 + 행수/100 초(250행 → 7)", "7" in args, str(args))
        check("⑥ 250행도 시간 안에 전부 기록", all(x[6].startswith("effect:") for x in cand_rows(home)), "")


def test_effect_2000_rows_constant_processes():
    axis = "coder/구현 정확성"
    with tempfile.TemporaryDirectory() as tmp:
        base_home, base_proj = make_env(Path(tmp) / "b", [])
        t0 = time.time()
        run_usage(base_home, base_proj, timeout=120)
        t_base = time.time() - t0
    with tempfile.TemporaryDirectory() as tmp:
        rr = [f"T41-n{i:04d}\tT41\t{d(2)}\t-\tpending-bench\t{axis if i % 2 else 'qa/범위 준수'}: 후보 {i}" for i in range(2000)]
        home, proj = make_env(tmp, rr)
        (home / ".claude/_audit/history.md").write_text("# h\n" + hist_lines(axis, 1, 1), encoding="utf-8")
        (home / ".claude/_audit/agent-spawn.log").write_text("".join(f"{TODAY}T01:00:0{i % 9}+09:00\tpost\tqa \tn{i} \tsonnet \td\n" for i in range(30)), encoding="utf-8")
        t0 = time.time()
        run_usage(home, proj, timeout=120)
        dt = time.time() - t0
        got = {x[0]: x[6] for x in cand_rows(home)}
        check("② 후보 2,000행 효과 기록: 전부 기록(홀수 인덱스=recurred k=2, 짝수=quiet n_spawn=30)", got["T41-n0001"] == "effect:recurred k=2" and got["T41-n0000"] == "effect:quiet n_spawn=30"
              and all(v.startswith("effect:") for v in got.values()), f"{got['T41-n0001']} {got['T41-n0000']}")
        check("② 후보 2,000행이어도 프로세스 상수(빈 대장 실행 대비 증가분 3초 이내)", dt - t_base < 3.0, f"base={t_base:.1f}s total={dt:.1f}s")


def test_effect_awk_failure_is_not_done():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-q\tT41\t{d(8)}\t-\tpending\tcoder/구현 정확성: 조용한 후보\teffect:quiet n_spawn=0"])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        shim = Path(tmp) / "shim"
        shim.mkdir()
        # 효과 계산 awk 만(입력에 프로세스 치환 /dev/fd/N 이 있는 호출) 실패시키는 awk 대역 — 입력 파일을 읽을 수 없는 상황을 흉내
        (shim / "awk").write_text('#!/bin/bash\nfor a in "$@"; do case "$a" in /dev/fd/*) echo "awk: cannot open $a" >&2; exit 2;; esac; done\nexec /usr/bin/awk "$@"\n', encoding="utf-8")
        (shim / "awk").chmod(0o755)
        out = run_usage(home, proj, PATH=f"{shim}:{os.environ['PATH']}")
        edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("Grok6: 효과 계산 awk 가 실패하면 done 을 만들지 않고 failed 표식·T41_EFFECT_FAIL·maintenance.log 한 줄",
              not (edir / "done").exists() and (edir / "failed").exists() and "T41_EFFECT_FAIL" in out and "T41 효과 계산 실패(awk rc=2)" in log, f"{list(edir.glob('*'))} {out[-200:]} {log[-200:]}")
        check("Grok6: done 이 없으므로 7일 만료도 보류(8일 된 quiet 행 pending 유지)", cand_rows(home)[0][4] == "pending", str(cand_rows(home)[0]))
        check("Grok7②: failed 표지에 원인(awk rc=2)이 적히고 T41_EFFECT_FAIL 경보가 그 원인을 보여 줌",
              "awk rc=2" in (edir / "failed").read_text(encoding="utf-8") and "T41_EFFECT_FAIL(T41 효과 계산 실패(awk rc=2))" in out, f"{(edir / 'failed').read_text(encoding='utf-8')!r} {out[-300:]}")


def test_takeover_failure_still_allows_expire():
    axis = "coder/구현 정확성"
    with tempfile.TemporaryDirectory() as tmp:
        # history 가 계속 안 읽히는 환경(파일 없음). 10분 넘은 선점(failed 표지, done 없음)을 이 세션이 승계해 기록을 다시 시도하지만 또 실패한다.
        home, proj = make_env(tmp, [f"T41-q\tT41\t{d(2)}\t-\tpending-bench\t{axis}: 기록 실패 중인 후보\teffect:quiet n_spawn=0", f"T12-o\tT12\t{d(8)}\t-\tpending\t오래된 교정"])
        edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
        edir.mkdir()
        (edir / "failed").write_text("history 읽기 실패(grep rc=2)\n", encoding="utf-8")
        set_mtime(edir, minutes=20)
        out = run_usage(home, proj)
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        r = {x[0]: x for x in cand_rows(home)}
        check("Grok8①: 승계했으나 기록이 또 실패 → failed 재작성·done 없음·T41_EFFECT_FAIL",
              (edir / "failed").exists() and not (edir / "done").exists() and "T41_EFFECT_FAIL(history 읽기 실패(grep rc=2))" in out, f"{list(edir.glob('*'))} {out[-250:]}")
        check("Grok8①: 그래도 만료는 돈다(8일 넘은 pending T12 가 expired)·maintenance.log 에 «승계했으나 … 다시 실패»", r["T12-o"][4] == "expired" and "10분 지난 선점을 승계했으나 효과 기록이 다시 실패함" in log,
              f"{r['T12-o']} {log[-300:]}")
        check("Grok8①: 효과 기록 실패 대상(pending-bench T41)은 그대로", r["T41-q"][4] == "pending-bench" and r["T41-q"][6] == "effect:quiet n_spawn=0", str(r["T41-q"]))
        # 승계하지 않은 보통 세션은 종전 그대로: 선점이 10분 미만이면 만료를 보류한다
        home2, proj2 = make_env(Path(tmp) / "n", [f"T41-q\tT41\t{d(2)}\t-\tpending-bench\t{axis}: x\teffect:quiet n_spawn=0", f"T12-o\tT12\t{d(8)}\t-\tpending\t오래된 교정"])
        (home2 / f".claude/_usage/t41-effect-{TODAY}.d").mkdir()
        run_usage(home2, proj2)
        check("Grok8①: 승계하지 않은 보통 세션(선점 10분 미만)은 여전히 만료 보류", {x[0]: x for x in cand_rows(home2)}["T12-o"][4] == "pending", str(cand_rows(home2)))


def awk_shim(tmp, needles):
    """프로그램 문자열에 needles 가 전부 든 awk 호출만 실패(rc 2)시키는 awk 대역을 만든 PATH 접두를 돌려준다."""
    shim = Path(tmp) / "awk-shim"
    shim.mkdir()
    cond = " && ".join(f'[[ "$*" == *\'{n}\'* ]]' for n in needles)
    (shim / "awk").write_text(f'#!/bin/bash\nif {cond}; then echo "awk: injected failure" >&2; exit 2; fi\nexec /usr/bin/awk "$@"\n', encoding="utf-8")
    (shim / "awk").chmod(0o755)
    return f"{shim}:{os.environ['PATH']}"


def test_grok9_effect_fail_paths():
    axis = "coder/구현 정확성"
    t41 = f"T41-q\tT41\t{d(2)}\t-\tpending-bench\t{axis}: 후보\teffect:quiet n_spawn=0"
    old = f"T12-o\tT12\t{d(8)}\t-\tpending\t오래된 교정"
    # 2: 문구 분리 — 승계 뒤 재실패 턴은 «만료를 허용함», 보통 실패 턴은 «만료는 보류됨»
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [t41, old])
        edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
        edir.mkdir()
        (edir / "failed").write_text("history 읽기 실패(grep rc=2)\n", encoding="utf-8")
        set_mtime(edir, minutes=20)
        out = run_usage(home, proj)
        check("Grok9 2: 승계 뒤 재실패 턴의 경보는 «이번 세션은 승계 뒤 재실패라 만료를 허용함» (만료 보류 문구 아님)",
              "이번 세션은 승계 뒤 재실패라 만료를 허용함" in out and "7일 만료는 보류됨" not in out and {x[0]: x for x in cand_rows(home)}["T12-o"][4] == "expired", out[-400:])
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [t41, old])   # history 없음 → 새 선점 세션의 보통 실패
        out = run_usage(home, proj)
        check("Grok9 2: 승계가 아닌 보통 실패 턴의 경보는 «7일 만료는 보류됨»", "7일 만료는 보류됨" in out and "만료를 허용함" not in out and {x[0]: x for x in cand_rows(home)}["T12-o"][4] == "pending", out[-400:])
    # 4: 소집 로그 집계 awk 실패
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [t41, old])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        (home / ".claude/_audit/agent-spawn.log").write_text(f"{TODAY}T01:00:00+09:00\tpost\tcoder \tn \tsonnet \td\n", encoding="utf-8")
        out = run_usage(home, proj, PATH=awk_shim(tmp, ["n[t]++"]))
        edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
        check("Grok9 4: 소집 로그 집계 awk 실패 → failed 원인 «spawn 집계 실패(awk rc=2)»·done 없음·경보", (edir / "failed").exists() and not (edir / "done").exists()
              and "spawn 집계 실패(awk rc=2)" in (edir / "failed").read_text(encoding="utf-8") and "T41_EFFECT_FAIL(spawn 집계 실패(awk rc=2))" in out, f"{list(edir.glob('*'))} {out[-300:]}")
        check("Grok9 4: 집계 실패 턴은 효과 기록 없음(비고 불변)·만료 보류", cand_rows(home)[0][6] == "effect:quiet n_spawn=0" and {x[0]: x for x in cand_rows(home)}["T12-o"][4] == "pending", str(cand_rows(home)))
    # 5: T41_PEND awk 실패 → 미결 0 으로 읽지 않고 만료 보류
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [t41, old])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        run_usage(home, proj, PATH=awk_shim(tmp, ['$2=="T41"', "END {print n+0}"]))
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("Grok9 5: 미결 T41 수를 세는 awk 실패 → 만료 보류(T12 pending)·maintenance.log «미결 T41 수를 세지 못함(awk rc=2)»",
              {x[0]: x for x in cand_rows(home)}["T12-o"][4] == "pending" and "미결 T41 수를 세지 못함(awk rc=2)" in log, f"{cand_rows(home)} {log[-250:]}")
    # 6: done 생성 실패(깨진 심볼릭 링크로 흉내) → failed «done 생성 실패»·그 턴 만료 안 함(승계 턴이어도 --force 금지)
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [t41, old])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
        edir.mkdir()
        (edir / "done").symlink_to(Path(tmp) / "no-such-dir" / "x")   # -e 는 거짓이지만 쓰기는 실패
        set_mtime(edir, minutes=20)
        out = run_usage(home, proj)
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("Grok9 6: done 생성 실패 → failed 원인 «done 생성 실패»·경보", "done 생성 실패" in (edir / "failed").read_text(encoding="utf-8") and "T41_EFFECT_FAIL(done 생성 실패)" in out, f"{list(edir.glob('*'))} {out[-250:]}")
        check("Grok9 6: 승계 턴이어도 그 턴은 만료하지 않음(T12 pending·--force 없음)·로그 «done 을 만들지 못함»", {x[0]: x for x in cand_rows(home)}["T12-o"][4] == "pending" and "done)를 만들지 못함" in log, f"{cand_rows(home)} {log[-250:]}")
    # 7: CUT14D 를 못 구함 → 승계 턴이어도 --force 만료로 가지 않고 보류
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [t41, old])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
        edir.mkdir()
        set_mtime(edir, minutes=20)
        shim = Path(tmp) / "date-shim"
        shim.mkdir()
        (shim / "date").write_text('#!/bin/bash\ncase "$*" in *"-14 days"*|*"-v-14d"*) exit 1;; esac\nexec /usr/bin/date "$@"\n', encoding="utf-8")
        (shim / "date").chmod(0o755)
        run_usage(home, proj, PATH=f"{shim}:{os.environ['PATH']}")
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("Grok9 7: 날짜 계산 실패(CUT14D 없음)면 승계 턴이어도 기록 없이 --force 만료로 가지 않음(T12 pending)·로그", {x[0]: x for x in cand_rows(home)}["T12-o"][4] == "pending" and "날짜 계산 실패로 이번 세션은 T41 효과 기록을 하지 못함" in log, f"{cand_rows(home)} {log[-250:]}")


def test_effect_spawn_log_unreadable_fails_closed():
    axis = "coder/구현 정확성"
    row = f"T41-q\tT41\t{d(8)}\t-\tpending\t{axis}: 조용했던 후보\teffect:quiet n_spawn=0"
    with tempfile.TemporaryDirectory() as tmp:   # 없는 소집 로그는 소집 0 으로 정상(done)
        home, proj = make_env(tmp, [row])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        run_usage(home, proj)
        edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
        check("Grok8②: 소집 로그가 없는 것은 정상(done)", (edir / "done").exists() and not (edir / "failed").exists(), f"{list(edir.glob('*'))}")
    if os.geteuid() != 0:
        with tempfile.TemporaryDirectory() as tmp:
            home, proj = make_env(tmp, [row])
            (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
            spawn = home / ".claude/_audit/agent-spawn.log"
            spawn.write_text(f"{TODAY}T01:00:00+09:00\tpost\tcoder \tn \tsonnet \td\n", encoding="utf-8")
            os.chmod(spawn, 0)
            try:
                out = run_usage(home, proj)
            finally:
                os.chmod(spawn, 0o644)
            edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
            check("Grok8②: 소집 로그가 있는데 읽을 수 없으면 failed 원인 «spawn 로그 읽기 실패»·done 없음·경보·후보 pending 유지",
                  (edir / "failed").exists() and not (edir / "done").exists() and "spawn 로그 읽기 실패" in (edir / "failed").read_text(encoding="utf-8")
                  and "T41_EFFECT_FAIL(spawn 로그 읽기 실패" in out and cand_rows(home)[0][4] == "pending", f"{list(edir.glob('*'))} {out[-250:]}")


def test_effect_history_unreadable_fails_closed():
    axis = "coder/구현 정확성"
    row = f"T41-q\tT41\t{d(8)}\t-\tpending\t{axis}: 조용했던 후보\teffect:quiet n_spawn=0"
    with tempfile.TemporaryDirectory() as tmp:   # 파일 없음 → grep rc=2
        home, proj = make_env(tmp, [row])
        out = run_usage(home, proj)
        edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
        log = (home / ".claude/_usage/maintenance.log").read_text(encoding="utf-8")
        check("Grok7①: history 파일이 없으면 done 없이 failed 표지(원인 history 읽기 실패(grep rc=2))",
              (edir / "failed").exists() and not (edir / "done").exists() and "history 읽기 실패(grep rc=2)" in (edir / "failed").read_text(encoding="utf-8"), f"{list(edir.glob('*'))}")
        check("Grok7①②: 경보 T41_EFFECT_FAIL 이 원인을 보여 주고 maintenance.log 에 «history 읽기 실패(grep rc=2)»", "T41_EFFECT_FAIL(history 읽기 실패(grep rc=2))" in out and "history 읽기 실패(grep rc=2)" in log, f"{out[-300:]} {log[-200:]}")
        check("Grok7①: fail-open 방지 — 8일 된 quiet 행이 effect 기록 없이 만료되지 않음(pending 유지·비고 불변)", cand_rows(home)[0][4] == "pending" and cand_rows(home)[0][6] == "effect:quiet n_spawn=0", str(cand_rows(home)[0]))
    if os.geteuid() != 0:
        with tempfile.TemporaryDirectory() as tmp:   # 권한 0 → grep rc=2
            home, proj = make_env(tmp, [row])
            hist = home / ".claude/_audit/history.md"
            hist.write_text("# h\n", encoding="utf-8")
            os.chmod(hist, 0)
            try:
                out = run_usage(home, proj)
            finally:
                os.chmod(hist, 0o644)
            edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
            check("Grok7①: history 권한 0 도 같은 실패 경로(done 없음·pending 유지)", (edir / "failed").exists() and not (edir / "done").exists() and cand_rows(home)[0][4] == "pending" and "history 읽기 실패" in out, f"{list(edir.glob('*'))} {out[-200:]}")
    with tempfile.TemporaryDirectory() as tmp:   # 매치 없음(rc=1)은 빈 history — 정상 경로(done)
        home, proj = make_env(tmp, [row])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        run_usage(home, proj)
        edir = home / f".claude/_usage/t41-effect-{TODAY}.d"
        check("Grok7①: 매치 없음(grep rc=1)은 빈 history 로 보아 정상 처리(done)", (edir / "done").exists() and not (edir / "failed").exists(), f"{list(edir.glob('*'))}")


def test_effect_without_timeout_warns():
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-a\tT41\t{d(2)}\t-\tpending-bench\tcoder/구현 정확성: 후보"])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        out = run_usage(home, proj, PATH=build_path_without(tmp, "timeout"))
        check("⑧ timeout 이 없으면 경보 한 줄 + 상한 없이 효과 기록은 수행", out.count("T41_EFFECT_NO_TIMEOUT") == 1 and cand_rows(home)[0][6].startswith("effect:"), f"{cand_rows(home)[0]} {out[-400:]}")
    with tempfile.TemporaryDirectory() as tmp:
        home, proj = make_env(tmp, [f"T41-a\tT41\t{d(2)}\t-\tpending-bench\tcoder/구현 정확성: 후보"])
        (home / ".claude/_audit/history.md").write_text("# h\n", encoding="utf-8")
        out = run_usage(home, proj)
        check("⑧ timeout 이 있으면 경보 없음", "T41_EFFECT_NO_TIMEOUT" not in out, out)


for fn in (test_unjudged_alarm_without_marker_needs_old_candidate, test_attach_retry_queue, test_attach_retry_discards_impossible_lines, test_retry_queue_keeps_transient_failures, test_retry_queue_keeps_storage_failures, test_retry_accepted_attach_permanent_failure_discarded, test_retry_rewrite_keeps_concurrent_updates, test_retry_queue_keeps_lines_when_ledger_unreadable, test_retry_drain_limited_to_two_per_session, test_digest_axis_normalized, test_expire_waits_for_effect_done, test_expire_skips_ids_in_retry_queue,
           test_retry_queue_lock_and_no_rm, test_role_alias_shared_with_effect_count,
           test_effect_axis_rule_and_limit_200, test_effect_without_timeout_warns, test_effect_selection_pending_first, test_effect_awk_failure_is_not_done, test_effect_history_unreadable_fails_closed, test_takeover_failure_still_allows_expire, test_grok9_effect_fail_paths, test_effect_spawn_log_unreadable_fails_closed, test_effect_2000_rows_constant_processes, test_effect_timeout_scales_with_rows, test_effect_rec_axis_normalized, test_retry_queue_without_flock, test_expire_rc4_is_quiet, test_effect_recorded_before_expire,
           test_pending_type_counts_and_unjudged_alarm, test_digest_rotates_by_day, test_crosscheck_attempt_and_success_markers,
           test_crosscheck_counts_multiple_agents_per_line, test_crosscheck_without_jq_alerts, test_crosscheck_auto_success_marker,
           test_expire_in_usage_check, test_maintenance_log_rotation, test_digest_once_per_day, test_digest_parallel_single_output, test_t41_effect_note, test_effect_aggregation_and_batch, test_memory_index_long_and_prune,
           test_prune_targets_fixed_root_and_cwd_project, test_crosscheck_background_launch, test_crosscheck_latest_and_auto):
    fn()

fail = 0
for name, ok, detail in results:
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       실제: {detail[:400]}")
    fail += 0 if ok else 1
print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(results)} checks)")
sys.exit(1 if fail else 0)
