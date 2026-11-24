"""tools/mem-guard/oom-watch.py 의 순수 판정(build_alerts·파서) 시험. 실제 cgroup·저널은 건드리지 않는다.
REF: knowledge/harness/code-history/scripts__tests__test_oom_watch.py.md
"""
import importlib.util
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "tools" / "mem-guard" / "oom-watch.py"
spec = importlib.util.spec_from_file_location("oom_watch", SRC)
ow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ow)

G = ow.GIB_KB
UNIT = "memguard-exp-demo-1c-x58t-123.scope"
SWAP_FULL = (32 * G, 32 * G)
SWAP_HALF = (16 * G, 32 * G)


def scope(oom=0, kill=0, smax=0, sfail=0, procs=None, swap=0, swap_max=5 * G):
    return {"oom": oom, "oom_kill": kill, "swap_ev_max": smax, "swap_fail": sfail,
            "mem_kb": 40 * G, "mem_max_kb": 40 * G, "swap_kb": swap, "swap_max_kb": swap_max,
            "procs": procs if procs is not None else {"10": {"cmd": "python train.py", "rss_kb": 20 * G},
                                                       "11": {"cmd": "python worker", "rss_kb": 3 * G}}}


def run(prev, cur, user_oom=None, kernel=None, oomd=None, swap=SWAP_HALF, seen=None):
    return ow.build_alerts("host1", prev, cur, user_oom or {}, kernel or [], oomd or [], swap,
                           seen if seen is not None else set())


def test_individual_limit_kill_names_vanished_worker():
    prev = {UNIT: scope()}
    cur = {UNIT: scope(oom=1, kill=1, smax=1, swap=5 * G, procs={"10": prev[UNIT]["procs"]["10"]})}
    (a,) = run(prev, cur)
    assert a.startswith("💀")
    assert "exp-demo-1c-x58t" in a and "개별 한도 초과" in a
    assert "pid 11 python (" in a and "worker" not in a
    assert "판 5.0/5.0GiB 상한 도달" in a and "전체 50%" in a


def test_alert_names_program_only_not_command_line():
    cmd = "/opt/venv/bin/python /data/PRIVATE/train.py --token=abc123 --subject=홍길동"
    prev = {UNIT: scope(procs={"10": {"cmd": cmd, "rss_kb": 3 * G}})}
    cur = {UNIT: scope(oom=1, kill=1, procs={})}
    (a,) = run(prev, cur)
    assert "pid 10 python (" in a
    assert "PRIVATE" not in a and "train.py" not in a and "--token" not in a and "/opt" not in a


def test_global_exhaustion_when_oom_counter_unchanged():
    prev = {UNIT: scope()}
    cur = {UNIT: scope(kill=1, sfail=3, swap=1 * G, procs={"10": prev[UNIT]["procs"]["10"]})}
    (a,) = run(prev, cur, swap=SWAP_FULL)
    assert "호스트 전체 메모리·swap 고갈" in a
    assert "판 1.0/5.0GiB ·" in a and "전체 100% 고갈" in a


def test_normal_exit_scope_vanished_is_silent():
    assert run({UNIT: scope()}, {}) == []


def test_no_counter_change_is_silent():
    assert run({UNIT: scope()}, {UNIT: scope()}) == []


def test_vanished_scope_with_user_journal_line():
    (a,) = run({UNIT: scope()}, {}, user_oom={UNIT: ["u1.0:" + UNIT]})
    assert "구분 불가" in a and "pid 10" in a


def test_kernel_log_overrides_counters_and_names_victim():
    lines = [
        ("1727600000.1 host1 kernel: oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=/,mems_allowed=0-1,"
         f"oom_memcg=/,task_memcg=/user.slice/user-1002.slice/user@1002.service/app.slice/{UNIT},task=python,pid=10,uid=1002"),
        "1727600000.1 host1 kernel: Out of memory: Killed process 10 (python) total-vm:1kB, anon-rss:20971520kB, file-rss:0kB",
    ]
    kev = ow.parse_kernel(lines)
    assert kev[0]["constraint"] == "CONSTRAINT_NONE" and kev[0]["rss_kb"] == 20 * G
    prev = {UNIT: scope()}
    cur = {UNIT: scope(oom=1, kill=1)}
    seen = set()
    (a,) = run(prev, cur, kernel=kev, seen=seen)
    assert "호스트 전체" in a and "pid 10 python (RSS 20.0GiB, 커널 로그)" in a
    assert run(prev, cur, kernel=kev, seen=seen)[0].count("커널 로그") == 0


def test_oomd_pressure_kill():
    lines = [("1727600000.2 host1 systemd-oomd[900]: Killed "
              f"/user.slice/user-1002.slice/user@1002.service/app.slice/{UNIT} due to memory pressure for x being 61% > 50%")]
    (a,) = run({}, {}, oomd=ow.parse_oomd(lines))
    assert a.startswith("💀") and "systemd-oomd 압력 종료: exp-demo-1c-x58t" in a


def test_scope_born_and_killed_between_runs():
    (a,) = run({}, {}, user_oom={UNIT: ["u2.0:" + UNIT]})
    assert "exp-demo-1c-x58t" in a and "구분 불가" in a


def test_user_journal_line_not_realerted_after_vanish():
    seen = set()
    prev = {UNIT: scope()}
    cur = {UNIT: scope(oom=1, kill=1)}
    assert len(run(prev, cur, user_oom={UNIT: ["u3.0:" + UNIT]}, seen=seen)) == 1
    assert run(cur, {}, user_oom={UNIT: ["u3.0:" + UNIT]}, seen=seen) == []


def test_parse_user_oom_and_label():
    got = ow.parse_user_oom([f"1727600001.0 host1 systemd[6435]: {UNIT}: A process of this unit has been killed by the OOM killer."])
    assert got == {UNIT: [f"u1727600001.0:{UNIT}"]}
    assert ow.scope_label(UNIT) == "exp-demo-1c-x58t"
