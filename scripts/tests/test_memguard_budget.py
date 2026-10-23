"""memguard-run.sh(안 자란 몫·압력 검사)·mem-watch.sh(압력 기록·알림)·train-watcher.sh(압력 표본 판정) 시험.

실제 cgroup·ntfy·학습은 건드리지 않는다. 가짜 나무(MEMGUARD_TEST_ROOT: meminfo + cgroup/)를 읽게 하고, 알림은 가짜 claude-notify.sh 가 파일에만 적는다.
대상 스크립트 위치: MG_SCRIPT_DIR(memguard-run.sh·mem-watch.sh, 기본 tools/mem-guard) · TW_SCRIPT_DIR(train-watcher.sh, 기본 tools/train-watcher).
교체 전 사본(.scratch/…/memfix)을 확인할 때는 두 변수를 모두 그 폴더로 준다.
실행: MG_SCRIPT_DIR=<사본> TW_SCRIPT_DIR=<사본> uv run --no-project --with pytest python -B -m pytest scripts/tests/test_memguard_budget.py -q -p no:cacheprovider --color=no
(와쳐 시험은 실제 train-watcher.sh 를 몇 초짜리 가짜 프로세스로 돌려 30초쯤 걸린다.)
"""
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MG_DIR = Path(os.environ.get("MG_SCRIPT_DIR") or ROOT / "tools" / "mem-guard")
TW_DIR = Path(os.environ.get("TW_SCRIPT_DIR") or ROOT / "tools" / "train-watcher")
GIB = 1 << 30


def psi(a10, a60):
    return f"some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10={a10} avg60={a60} avg300=0.00 total=0\n"


def make_tree(root, avail_gib=100.0, scopes=(), pressure=("0.00", "0.00")):
    """가짜 meminfo + cgroup 나무. scopes = [(이름, high(GiB 또는 'max'), current GiB, full avg10[, scope 직속 프로세스 수 = 1[, 하위 cgroup 프로세스 수 = 0]])]."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "meminfo").write_text(f"MemTotal: {int(251.5 * 1048576)} kB\nMemAvailable: {int(avail_gib * 1048576)} kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
    cg = root / "cgroup"
    cg.mkdir(exist_ok=True)
    if pressure:
        (cg / "memory.pressure").write_text(psi(*pressure))
    for i, (name, high, cur, a10, *procs) in enumerate(scopes):
        d = cg / "app.slice" / f"memguard-{name}-{1000 + i}.scope"   # 재귀로 찾는지 보려고 한 층 아래에 둔다
        d.mkdir(parents=True)
        own, nested = (procs[0] if procs else 1), (procs[1] if len(procs) > 1 else 0)
        (d / "cgroup.procs").write_text("".join(f"{4000 + k}\n" for k in range(own)))
        (d / "sub").mkdir()
        (d / "sub" / "cgroup.procs").write_text("".join(f"{5000 + k}\n" for k in range(nested)))
        (d / "memory.high").write_text(("max" if high == "max" else str(int(high * GIB))) + "\n")
        (d / "memory.current").write_text(f"{int(cur * GIB)}\n")
        (d / "memory.pressure").write_text(psi(a10, "0.00"))
    return root


def guard(root, *args):
    r = subprocess.run(["bash", str(MG_DIR / "memguard-run.sh"), "--preflight-only", "--swap-max", "none", "--high", "44G", "--max", "50G", *args],
                       check=False, capture_output=True, text=True, timeout=30, env={**os.environ, "MEMGUARD_TEST_ROOT": str(root)})
    return r.returncode, r.stdout + r.stderr


# 예: 여섯 판 high 44G
OCT12 = [(f"a{i}", 44, c, "0.00") for i, c in enumerate([40, 38, 35, 30, 16.5, 9])]


def test_a_sixth_scope_refused_at_oct12_numbers(tmp_path):
    rc, out = guard(make_tree(tmp_path / "t", 93.3, OCT12))
    assert rc == 75
    assert "거부" in out and "남은 메모리 93.3GiB" in out and "안 자란 몫 95.5GiB(scope 6개)" in out
    assert "OS 예약 32.0" in out and "작업 예산 50.0" in out and "필요 82.0GiB" in out


def test_b_fifth_scope_passes_when_four_are_fully_grown(tmp_path):
    four = [(f"a{i}", 44, 38, "0.00") for i in range(4)]          # 안 자란 몫 24GiB
    rc, out = guard(make_tree(tmp_path / "t", 110, four))
    assert rc == 0 and "preflight PASS" in out and "안 자란 몫 24.0GiB(scope 4개)" in out
    rc, out = guard(make_tree(tmp_path / "edge", 105, four))      # 105 − 24 = 81 < 82 → 경계 바로 아래는 거부
    assert rc == 75 and "= 81.0GiB < 필요 82.0GiB" in out


def test_c_scope_with_high_max_is_skipped(tmp_path):
    scopes = [(f"a{i}", 44, 38, "0.00") for i in range(4)] + [("free", "max", 40, "0.00")]
    rc, out = guard(make_tree(tmp_path / "t", 110, scopes))
    assert rc == 0 and "안 자란 몫 24.0GiB(scope 4개)" in out


def test_c2_empty_scopes_are_skipped_and_counted(tmp_path):
    """10-17 실사고: 프로세스 0개인 scope 의 high − current 는 안 자란 몫에서 뺀다(빼지 않으면 아래 숫자는 거부된다)."""
    live = [(f"a{i}", 44, 38, "0.00") for i in range(4)]                     # 직속 프로세스 1개씩 → 안 자란 몫 24GiB
    dead = [(f"d{i}", 44, 0, "0.00", 0) for i in range(3)]                   # 프로세스 0개 → 132GiB 였을 몫
    rc, out = guard(make_tree(tmp_path / "t", 110, live + dead))
    assert rc == 0 and "안 자란 몫 24.0GiB(scope 4개) · 빈 scope 3개 제외" in out
    rc, out = guard(make_tree(tmp_path / "all", 110, dead))
    assert rc == 0 and "안 자란 몫 0.0GiB(scope 0개) · 빈 scope 3개 제외" in out   # 7개 전부 빈 실사고 꼴
    rc, out = guard(make_tree(tmp_path / "edge", 105, live + dead))
    assert rc == 75 and "= 81.0GiB < 필요 82.0GiB" in out and "빈 scope 3개 제외" in out   # 경계 계산은 종전 그대로


def test_c3_scope_with_only_nested_procs_is_counted(tmp_path):
    """직속은 0개여도 하위 cgroup(예: 워커)에 프로세스가 있으면 비어 있지 않다."""
    scopes = [("nested", 44, 38, "0.00", 0, 2), ("own", 44, 38, "0.00", 3, 0)]
    rc, out = guard(make_tree(tmp_path / "t", 110, scopes))
    assert rc == 0 and "안 자란 몫 12.0GiB(scope 2개) · 빈 scope 0개 제외" in out


def test_c4_high_max_scope_still_skipped_with_procs(tmp_path):
    scopes = [("a", 44, 38, "0.00"), ("free", "max", 40, "0.00", 5)]
    rc, out = guard(make_tree(tmp_path / "t", 110, scopes))
    assert rc == 0 and "안 자란 몫 6.0GiB(scope 1개) · 빈 scope 0개 제외" in out


@pytest.mark.skipif(os.geteuid() == 0, reason="root 는 권한 없는 파일도 읽는다")
def test_c5_unreadable_procs_file_counts_as_nonempty(tmp_path):
    root = make_tree(tmp_path / "t", 110, [("a", 44, 38, "0.00", 0)])
    f = next((root / "cgroup").rglob("cgroup.procs"))
    f.chmod(0)
    try:
        rc, out = guard(root)
    finally:
        f.chmod(0o644)
    assert rc == 0 and "안 자란 몫 6.0GiB(scope 1개) · 빈 scope 0개 제외" in out


@pytest.mark.skipif(os.geteuid() == 0, reason="root 는 권한 없는 폴더도 읽는다")
def test_c6_find_failure_counts_as_nonempty(tmp_path):
    """직속 프로세스 0개라도 하위 폴더를 못 열어 find 가 실패하면 비어 있지 않은 것으로 센다(낙관 실패 차단)."""
    root = make_tree(tmp_path / "t", 110, [("a", 44, 38, "0.00", 0)])
    sub = next((root / "cgroup").rglob("sub"))
    sub.chmod(0)
    try:
        rc, out = guard(root)
    finally:
        sub.chmod(0o755)
    assert rc == 0 and "안 자란 몫 6.0GiB(scope 1개) · 빈 scope 0개 제외" in out


def test_d_pressure_threshold(tmp_path):
    plenty = lambda p: make_tree(tmp_path / f"p{p[1]}", 200, [], p)
    rc, out = guard(plenty(("5.00", "12.00")))
    assert rc == 75 and "거부" in out and "full avg60 12.00%" in out and "문턱 10%" in out
    rc, out = guard(plenty(("5.00", "9.99")))
    assert rc == 0 and "압력 full avg60 9.99% < 10%" in out
    rc, out = guard(plenty(("5.00", "12.00")), "--pressure-max", "15")
    assert rc == 0
    rc, out = guard(plenty(("5.00", "50.00")), "--pressure-max", "0")
    assert rc == 0 and "압력 검사 끔" in out
    nofile = make_tree(tmp_path / "nofile", 200, [], None)
    rc, out = guard(nofile)
    assert rc == 0 and "memory.pressure 를 읽지 못해 압력 검사를 건너뜁니다" in out


def test_d2_unreadable_cgroup_root_falls_back_to_old_check(tmp_path):
    root = tmp_path / "noroot"
    root.mkdir()
    (root / "meminfo").write_text(f"MemAvailable: {100 * 1048576} kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
    rc, out = guard(root)
    assert rc == 0 and "뿌리" in out and "종전 검사만" in out
    (root / "meminfo").write_text(f"MemAvailable: {60 * 1048576} kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
    rc, out = guard(root)
    assert rc == 75 and "안 자란 몫 0.0GiB(scope 0개)" in out


def test_e_test_root_warning_line(tmp_path):
    _, out = guard(make_tree(tmp_path / "t", 200))
    assert "경고: 시험용 경로 사용 중" in out and str(tmp_path / "t") in out


def test_bad_pressure_max_is_usage_error(tmp_path):
    rc, _ = guard(make_tree(tmp_path / "t", 200), "--pressure-max", "abc")
    assert rc == 64


# ───────────── memguard-run.sh 거부 알림 (가짜 claude-notify.sh, 실제 전송 없음) ─────────────

def _guard_with_notify(tmp_path, root, args, notify_script="ok"):
    """복사본 memguard-run.sh 를 tmp/tools/mem-guard 에 두고 tmp/scripts/claude-notify.sh 를 가짜로 둔다. 반환: (rc, 출력, 알림 줄 목록)."""
    mgdir = tmp_path / "tools" / "mem-guard"
    mgdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(MG_DIR / "memguard-run.sh", mgdir / "memguard-run.sh")
    (tmp_path / "scripts").mkdir(exist_ok=True)
    sent = tmp_path / "notify.txt"
    if notify_script == "ok":
        (tmp_path / "scripts" / "claude-notify.sh").write_text(f'echo "$1|$2" >> {shlex.quote(str(sent))}\n')
    elif notify_script == "fail":
        (tmp_path / "scripts" / "claude-notify.sh").write_text(f'echo "$1|$2" >> {shlex.quote(str(sent))}\nexit 9\n')
    r = subprocess.run(["bash", str(mgdir / "memguard-run.sh"), "--swap-max", "none", "--high", "44G", "--max", "50G", *args],
                       check=False, capture_output=True, text=True, timeout=30, env={**os.environ, "MEMGUARD_TEST_ROOT": str(root)})
    return r.returncode, r.stdout + r.stderr, (sent.read_text().splitlines() if sent.exists() else [])


def test_refusal_notified_once_on_real_launch_budget_and_pressure(tmp_path):
    rc, _, sent = _guard_with_notify(tmp_path / "b", make_tree(tmp_path / "bt", 93.3, OCT12), ["--name", "exp-x", "--", "true"])
    assert rc == 75 and len(sent) == 1
    assert sent[0].startswith("memguard|🚫 [memguard ") and "발사 거부(메모리): exp-x — 남은 메모리 93.3GiB" in sent[0] and "안 자란 몫 95.5GiB" in sent[0]
    rc, _, sent = _guard_with_notify(tmp_path / "p", make_tree(tmp_path / "pt", 200, [], ("5.00", "12.00")), ["--", "/usr/bin/python3", "x.py"])
    assert rc == 75 and len(sent) == 1 and "발사 거부(메모리): python3 — 메모리 압력 full avg60 12.00% ≥ 문턱 10%" in sent[0]


def test_preflight_only_refusal_is_not_notified(tmp_path):
    rc, out, sent = _guard_with_notify(tmp_path / "b", make_tree(tmp_path / "bt", 93.3, OCT12), ["--preflight-only"])
    assert rc == 75 and "거부" in out and sent == []
    rc, _, sent = _guard_with_notify(tmp_path / "p", make_tree(tmp_path / "pt", 200, [], ("5.00", "12.00")), ["--preflight-only"])
    assert rc == 75 and sent == []


def test_refusal_exit_code_unchanged_when_notify_script_missing_or_failing(tmp_path):
    rc, _, sent = _guard_with_notify(tmp_path / "m", make_tree(tmp_path / "mt", 93.3, OCT12), ["--", "true"], notify_script=None)
    assert rc == 75 and sent == []                                  # 알림 스크립트 없음: 조용히 건너뜀
    rc, _, sent = _guard_with_notify(tmp_path / "f", make_tree(tmp_path / "ft", 93.3, OCT12), ["--", "true"], notify_script="fail")
    assert rc == 75 and len(sent) == 1                              # 알림이 exit 9 로 실패해도 거부 코드는 그대로


# ───────────── memguard-run.sh 자가 정리 (가짜 systemd-run·systemctl, 실제 systemd 호출 없음) ─────────────

STUB_RUN = r"""#!/usr/bin/env bash
echo "systemd-run $*" >> "$STUB_CALLS"
unit=""
while [ $# -gt 0 ]; do case "$1" in --unit) unit="$2"; shift 2 ;; --) shift; break ;; *) shift ;; esac; done
export FAKE_SCOPE_DIR="$MEMGUARD_TEST_ROOT/cgroup/app.slice/$unit.scope"
mkdir -p "$FAKE_SCOPE_DIR"; : > "$FAKE_SCOPE_DIR/cgroup.procs"
"$@"; exit $?
"""
STUB_CTL = '#!/usr/bin/env bash\necho "systemctl $*" >> "$STUB_CALLS"\n'


def _run_selfstop(tmp_path, inner, env_extra=None, name="exp-x"):
    """복사본 memguard-run.sh 를 가짜 systemd-run/systemctl 과 함께 본 실행한다. 반환: (rc, 호출 기록 읽기 함수, 가짜 scope 폴더 찾기 함수)."""
    mgdir = tmp_path / "tools" / "mem-guard"
    mgdir.mkdir(parents=True)
    shutil.copy(MG_DIR / "memguard-run.sh", mgdir / "memguard-run.sh")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for fn, body in (("systemd-run", STUB_RUN), ("systemctl", STUB_CTL)):
        (bindir / fn).write_text(body)
        (bindir / fn).chmod(0o755)
    root = make_tree(tmp_path / "root", 200)
    (root / "cgroup" / "cgroup.controllers").write_text("memory pids\n")
    calls = tmp_path / "calls.txt"
    env = {**os.environ, "MEMGUARD_TEST_ROOT": str(root), "STUB_CALLS": str(calls), "MEMGUARD_STOP_POLL": "0.1",
           "PATH": f"{bindir}:{os.environ['PATH']}", **(env_extra or {})}
    r = subprocess.run(["bash", str(mgdir / "memguard-run.sh"), "--swap-max", "none", "--high", "44G", "--max", "50G", "--name", name, "--", *inner],
                       check=False, capture_output=True, text=True, timeout=30, env=env)
    read = lambda: calls.read_text().splitlines() if calls.exists() else []
    return r, read, root / "cgroup" / "app.slice"


def _wait(pred, sec=8.0):
    end = time.time() + sec
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _stops(read):
    return [ln for ln in read() if ln.startswith("systemctl ")]


def test_h_self_stop_after_child_exits_and_exit_code_propagates(tmp_path):
    r, read, _ = _run_selfstop(tmp_path, ["bash", "-c", "exit 3"])
    assert r.returncode == 3                                              # 감싼 명령의 exit code 가 exec 체인을 지나 그대로 나온다
    assert _wait(lambda: _stops(read)), read()
    (run,) = [ln for ln in read() if ln.startswith("systemd-run ")]
    unit = run.split("--unit ")[1].split()[0]
    assert re.fullmatch(r"memguard-exp-x-\d+", unit) and "--collect" in run
    assert _stops(read) == [f"systemctl --user stop {unit}.scope"]        # 같은 unit 을 정확히 한 번 stop


def test_h_self_stop_disabled_by_env(tmp_path):
    r, read, _ = _run_selfstop(tmp_path, ["bash", "-c", "exit 0"], {"MEMGUARD_SELF_STOP": "0"})
    assert r.returncode == 0
    time.sleep(1.5)                                                       # 켜져 있었다면 poll 0.1초로 충분히 호출됐을 시간
    assert _stops(read) == [] and any(ln.startswith("systemd-run ") for ln in read())


def test_h_self_stop_waits_while_scope_still_has_processes(tmp_path):
    """주 프로세스가 끝나도 하위 cgroup 에 남은(고아) 프로세스가 있으면 stop 하지 않고, 비워지면 한 번 stop 한다."""
    inner = ["bash", "-c", 'mkdir -p "$FAKE_SCOPE_DIR/sub"; echo 4242 > "$FAKE_SCOPE_DIR/sub/cgroup.procs"']
    r, read, appslice = _run_selfstop(tmp_path, inner)
    assert r.returncode == 0
    time.sleep(1.5)
    assert _stops(read) == []
    next(appslice.glob("*.scope")).joinpath("sub", "cgroup.procs").write_text("")
    assert _wait(lambda: len(_stops(read)) == 1), read()
    time.sleep(0.5)
    assert len(_stops(read)) == 1                                         # 중복 stop 없음


@pytest.mark.parametrize("bad", ["a*b", "a b", "../x", "a/b", "x?"])
def test_h_name_with_glob_or_space_is_usage_error(tmp_path, bad):
    r, read, _ = _run_selfstop(tmp_path, ["bash", "-c", "exit 0"], name=bad)
    assert r.returncode == 64 and "--name" in r.stderr and read() == []


def test_h_self_stop_skipped_without_name(tmp_path):
    """--name 이 없으면 unit 이름을 알 수 없어 자가 정리를 하지 않는다(종전 동작)."""
    r, read, _ = _run_selfstop(tmp_path, ["bash", "-c", "exit 0"], name="")
    assert r.returncode == 0
    time.sleep(1.5)
    assert _stops(read) == [] and not any("--unit" in ln for ln in read())


# ───────────── mem-watch.sh ─────────────

@pytest.fixture
def mw(tmp_path):
    """복사본 mem-watch.sh + 가짜 claude-notify.sh(파일에 한 줄) + 빈 oom-watch.py. 반환: run(root, **env) -> 실행 결과."""
    mgdir = tmp_path / "tools" / "mem-guard"
    mgdir.mkdir(parents=True)
    shutil.copy(MG_DIR / "mem-watch.sh", mgdir / "mem-watch.sh")
    (mgdir / "oom-watch.py").write_text("pass\n")
    (tmp_path / "scripts").mkdir()
    sent = tmp_path / "notify.txt"
    (tmp_path / "scripts" / "claude-notify.sh").write_text(f'echo "$2" >> {shlex.quote(str(sent))}\n')
    log, st = tmp_path / "mw.log", tmp_path / "mw.state"

    def run(root, **env):
        e = {**os.environ, "MEMWATCH_LOG": str(log), "MEMWATCH_STATE": str(st),
             "MEMGUARD_TEST_ROOT": str(root), "WARN_AVAIL_GB": "0", "CRIT_AVAIL_GB": "0", "REALERT_SEC": "1800"}
        e.update({k: str(v) for k, v in env.items()})
        return subprocess.run(["bash", str(mgdir / "mem-watch.sh")], check=False, capture_output=True, text=True, timeout=60, env=e)

    run.sent = lambda: sent.read_text().splitlines() if sent.exists() else []
    run.log = lambda: log.read_text() if log.exists() else ""
    run.state, run.dir = st, mgdir
    return run


SEVEN = [("exp-r68", 44, 30, "1.00"), ("exp-r66", 44, 40, "40.00"), ("eff-x", 44, 20, "22.50"), ("exp-r1", 44, 35, "9.00"),
         ("exp-r2", 44, 10, "3.00"), ("exp-r3", 44, 12, "2.00"), ("exp-r4", 44, 8, "0.50")]


def test_f_pressure_logged_every_minute_without_alert_below_threshold(mw, tmp_path):
    r = mw(make_tree(tmp_path / "t", scopes=SEVEN, pressure=("3.00", "5.00")))
    assert "경고: 시험용 경로 사용 중" in r.stderr
    assert "Pressure=3.00/5.00%" in mw.log() and mw.sent() == [] and "압력 상위" not in mw.log()


def test_f_pressure_unreadable_shows_question_mark(mw, tmp_path):
    root = make_tree(tmp_path / "t", scopes=SEVEN, pressure=None)
    mw(root)
    assert "Pressure=?" in mw.log() and mw.sent() == []


def test_f_high_pressure_is_logged_only_never_alerted(mw, tmp_path):
    """압력은 기록만 한다(2026-10-12 사용자 지시): 진입·지속·해제 어느 쪽도 알림 0회, 상태 파일도 만들지 않는다."""
    root = make_tree(tmp_path / "t", scopes=SEVEN, pressure=("30.00", "20.00"))
    mw(root)
    tops = [ln for ln in mw.log().splitlines() if "압력 상위" in ln]
    assert len(tops) == 5 and "상위 1: exp-r66 full avg10=40.00% current=40GiB" in tops[0] and "memguard" not in " ".join(tops)
    mw(root, REALERT_SEC=0)                                        # 지속 + 재알림 시간 경과여도 알림 없음
    (root / "cgroup" / "memory.pressure").write_text(psi("1.00", "2.00"))
    mw(root)                                                       # 해제여도 알림 없음
    assert mw.sent() == [] and "[alert]" not in mw.log()
    assert not list(mw.dir.glob("*.state")) and not list(tmp_path.glob("*pressure*"))


def test_f_log_threshold_env_and_mem_available_crit_unchanged(mw, tmp_path):
    root = make_tree(tmp_path / "t", scopes=SEVEN, pressure=("30.00", "20.00"))
    mw(root, PRESSURE_LOG_PCT=25)
    assert "압력 상위" not in mw.log()                              # avg60 20 < 기록 문턱 25
    # 기존 MemAvailable CRIT: CRIT_AVAIL_GB 를 크게 → CRIT 알림 1회, 지속 억제, 해제 ✅ 는 종전 규칙
    calm = make_tree(tmp_path / "calm", scopes=SEVEN, pressure=("1.00", "2.00"))
    mw(calm, CRIT_AVAIL_GB=100000, WARN_AVAIL_GB=100000)
    (crit,) = mw.sent()
    assert crit.startswith("🚨") and "CRIT:" in crit and "Pressure=1.00/2.00%" in crit and mw.state.read_text().split()[0] == "CRIT"
    mw(calm, CRIT_AVAIL_GB=100000, WARN_AVAIL_GB=100000)
    assert len(mw.sent()) == 1                                     # CRIT 지속 억제
    mw(calm)                                                       # CRIT 해제
    assert len(mw.sent()) == 2 and mw.sent()[1].startswith("✅") and "CRIT 해제" in mw.sent()[1]


# ───────────── train-watcher.sh ─────────────

def _spawn_dummy(sec, log, text):
    p = subprocess.Popen(["bash", "-c", f"sleep {sec}; printf %s {shlex.quote(text)} >> {shlex.quote(str(log))}"])
    threading.Thread(target=p.wait, daemon=True).start()          # 좀비로 남으면 kill -0 이 계속 성공하므로 거둔다
    return p.pid


def _watch(tmp_path, tag, log_text, root, sec=4):
    log = tmp_path / f"{tag}.log"
    log.write_text("")
    cmd = ["bash", str(TW_DIR / "train-watcher.sh"), "--pid", str(_spawn_dummy(sec, log, log_text)), "--log", str(log), "--done-regex", "TRAIN_DONE",
           "--eval-cmd", "true", "--title", tag, "--interval", "1", "--no-notify"]
    env = {**os.environ, "MEMGUARD_TEST_ROOT": str(root)}
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=tmp_path, env=env), tmp_path / f"{tag}.watch-report.md"


def test_g_watcher_report_has_pressure_samples_and_verdict(tmp_path):
    suspect = make_tree(tmp_path / "suspect", pressure=("30.00", "8.00"))
    low = make_tree(tmp_path / "low", pressure=("3.50", "2.00"))
    none = make_tree(tmp_path / "none", pressure=None)
    ok = make_tree(tmp_path / "ok", pressure=("30.00", "20.00"))
    jobs = {"suspect": _watch(tmp_path, "suspect", "no marker\n", suspect, sec=13),   # 13초 → 표본 10개를 넘겨 «최근 10개»만 남는지도 본다
            "low": _watch(tmp_path, "low", "no marker\n", low), "none": _watch(tmp_path, "none", "no marker\n", none),
            "ok": _watch(tmp_path, "ok", "TRAIN_DONE\n", ok)}
    outs = {k: p.communicate(timeout=120)[0] for k, (p, _) in jobs.items()}
    rcs = {k: p.returncode for k, (p, _) in jobs.items()}
    assert rcs == {"suspect": 2, "low": 2, "none": 2, "ok": 0}, (rcs, outs)     # 종료 코드는 종전 그대로
    rep = {k: r.read_text() for k, (_, r) in jobs.items()}
    s = rep["suspect"]
    assert "메모리 압력 종료(systemd-oomd) 의심 — 확정은 sudo journalctl -u systemd-oomd" in s
    assert len([ln for ln in s.splitlines() if ln.startswith("- ") and "full avg10=30.00% avg60=8.00%" in ln]) == 10
    assert "종료 직전 메모리 압력 낮음(최대 avg10 3.5%)" in rep["low"] and "full avg10=3.50% avg60=2.00%" in rep["low"]
    assert "압력 표본 없음" in rep["none"]
    assert "메모리 압력" not in rep["ok"]                                         # 정상 종료 보고에는 압력 절이 없다


def test_g_watcher_crash_notification_body_contains_verdict(tmp_path):
    """비정상 종료 알림 본문에 압력 판정 한 줄이 들어간다(HOME 을 가짜로 바꿔 가짜 claude-notify.sh 가 받게 한다)."""
    home = tmp_path / "home"
    (home / ".claude" / "scripts").mkdir(parents=True)
    sent = tmp_path / "sent.txt"
    (home / ".claude" / "scripts" / "claude-notify.sh").write_text(f'echo "$2" >> {shlex.quote(str(sent))}\n')
    log = tmp_path / "n.log"
    log.write_text("")
    root = make_tree(tmp_path / "r", pressure=("30.00", "20.00"))
    cmd = ["bash", str(TW_DIR / "train-watcher.sh"), "--pid", str(_spawn_dummy(2, log, "no marker\n")), "--log", str(log), "--done-regex", "TRAIN_DONE",
           "--eval-cmd", "true", "--title", "n", "--interval", "1"]
    p = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60, cwd=tmp_path, env={**os.environ, "HOME": str(home), "MEMGUARD_TEST_ROOT": str(root)})
    assert p.returncode == 2
    (body,) = sent.read_text().splitlines()
    assert "비정상 종료 의심" in body and "압력: 메모리 압력 종료(systemd-oomd) 의심" in body
