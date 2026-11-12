"""tools/train-watcher/launch_queue.py(대기 목록 자동 발사)와 와쳐 --on-exit·launch-set.sh --queue 인자 검사 시험.

실제 tmux·GPU·launch-set 발사는 건드리지 않는다. 발사 백엔드는 FakeBackend, GPU 상태는 가짜 dict 다.
실행: uv run --no-project --with pytest python -m pytest scripts/tests/test_launch_queue.py -q
(와쳐 시험은 실제 train-watcher.sh 를 수 초짜리 가짜 프로세스로 돌려 15초쯤 걸린다.)
"""
import copy
import fcntl
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

TW_DIR = Path(__file__).resolve().parents[2] / "tools" / "train-watcher"
# 와쳐·발사 셸의 위치(기본 TW_DIR). 가동 중인 와쳐 때문에 제자리 교체 전의 사본(.scratch/…)을 같은 시험으로 검증할 때만 TW_SCRIPT_DIR 로 바꾼다.
SCRIPT_DIR = Path(os.environ.get("TW_SCRIPT_DIR") or TW_DIR)
_spec = importlib.util.spec_from_file_location("launch_queue", TW_DIR / "launch_queue.py")
lq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lq)


def gpu(name, total, procs=0, used=0.5):
    return {"name": name, "total_gb": total, "used_gb": used, "procs": procs}


H100, L40S = ("H100 PCIe", 80.0), ("L40S", 45.0)


def six_gpus():
    return {0: gpu(*H100), 1: gpu(*H100), 2: gpu(*L40S), 3: gpu(*L40S), 4: gpu(*L40S), 5: gpu(*L40S)}


def mk_item(root, id, **kw):
    d = {"id": id, "purpose": f"{id} 목적", "baseline": "base", "change": f"{id} 변경",
         "argv": ["env", "FAKE_GPU={GPU}", "bash", "run.sh"], "expect": "run\\.sh", "log_dir": str(root / "logs" / id),
         "vram_gb": 20, "cpu_cores": 4, "done_regex": "DONE", "eval_cmd": "true"}
    d.update(kw)
    return d


def mk_queue(tmp_path, items, name="q1", prefix="tq"):
    proj = tmp_path / "proj"
    (proj / ".claude" / "launch-queue").mkdir(parents=True, exist_ok=True)
    (proj / ".claude" / "train.env").write_text(f"TRAIN_TMUX_PREFIX={prefix}\n")
    qp = proj / ".claude" / "launch-queue" / f"{name}.json"
    qp.write_text(json.dumps({"name": name, "items": items}, ensure_ascii=False, indent=2))
    return qp


def run(be, *argv):
    return lq.main([str(a) for a in argv], backend=be)


def state(qp):
    return json.loads(lq.state_path(qp).read_text())


def statuses(qp):
    return {k: v["status"] for k, v in state(qp)["items"].items()}


def ready(tmp_path, n_items, gpus=None, **item_kw):
    """n 개 판 + 승인까지 끝낸 (큐 경로, FakeBackend)."""
    qp = mk_queue(tmp_path, [mk_item(tmp_path, f"a{i}", **item_kw) for i in range(1, n_items + 1)])
    be = lq.FakeBackend(gpus or six_gpus())
    assert run(be, "approve", qp, "--session", "test") == 0
    return qp, be


# ───────────── Phase 1: 형식·승인 ─────────────

def good(tmp_path):
    return {"name": "q1", "items": [mk_item(tmp_path, "a1"), mk_item(tmp_path, "a2")]}


def mutate_missing_purpose(q): del q["items"][0]["purpose"]
def mutate_no_gpu_token(q): q["items"][0]["argv"] = ["bash", "run.sh"]
def mutate_dup_id(q): q["items"][1]["id"] = "a1"
def mutate_unknown_key(q): q["items"][0]["vram"] = 3
def mutate_name(q): q["name"] = "other"
def mutate_vram_zero(q): q["items"][0]["vram_gb"] = 0
def mutate_rel_logdir(q): q["items"][0]["log_dir"] = "logs/a1"
def mutate_empty_items(q): q["items"] = []
def mutate_str_argv(q): q["items"][0]["argv"] = "bash run.sh {GPU}"


@pytest.mark.parametrize("mut", [mutate_missing_purpose, mutate_no_gpu_token, mutate_dup_id, mutate_unknown_key, mutate_name,
                                 mutate_vram_zero, mutate_rel_logdir, mutate_empty_items, mutate_str_argv])
def test_malformed_queue_is_rejected(tmp_path, mut):
    q = good(tmp_path)
    lq.parse_queue(json.dumps(q).encode(), "q1")   # 변형 전에는 통과
    mut(q)
    with pytest.raises(lq.QueueError):
        lq.parse_queue(json.dumps(q).encode(), "q1")


def test_approve_rejects_malformed_with_exit_2(tmp_path):
    q = good(tmp_path)
    del q["items"][0]["eval_cmd"]
    qp = mk_queue(tmp_path, q["items"])
    assert run(lq.FakeBackend(six_gpus()), "approve", qp) == 2
    assert not lq.state_path(qp).exists()


def test_edit_after_approval_halts_next(tmp_path):
    """성공 기준 2: 승인 뒤 한 글자만 바꿔도 next 는 아무것도 올리지 않고 halted 와 알림을 남긴다."""
    qp, be = ready(tmp_path, 3)
    assert run(be, "start", qp, "--gpus", "0") == 0
    assert len(be.launches) == 1
    qp.write_text(qp.read_text().replace("a2 목적", "a2 목적!"))
    assert run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0) == 0
    assert len(be.launches) == 1, "목록이 바뀌었는데 발사됨"
    st = state(qp)
    assert st["halted"]["reason"] == "queue-changed"
    assert st["items"]["a1"]["status"] == "done"   # 끝난 판의 기록은 해시와 무관하게 남긴다
    assert any("바뀌어" in n for n in be.notes)
    assert list(qp.with_name("q1.events").glob("*queue-changed*"))
    # 알림은 처음 멈출 때 한 번. 다시 불러도 계속 거부하고 알림은 늘지 않는다
    n = len(be.notes)
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0)
    assert len(be.launches) == 1 and len(be.notes) == n
    # 되돌려도 halted 는 approve 전까지 유지
    qp.write_text(qp.read_text().replace("a2 목적!", "a2 목적"))
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0)
    assert len(be.launches) == 1
    assert run(be, "approve", qp) == 0
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0)   # 이미 done 으로 처리된 보고의 되풀이는 무시된다(시도 결박, 2026-10-01)
    assert len(be.launches) == 1
    run(be, "start", qp, "--gpus", "0")                                       # halt 뒤 다시 올리는 길은 approve 후 start
    assert len(be.launches) == 2


def test_broken_json_after_approval_halts_instead_of_crashing(tmp_path):
    qp, be = ready(tmp_path, 2)
    assert run(be, "start", qp, "--gpus", "0") == 0 and len(be.launches) == 1
    qp.write_text("{ broken")
    assert run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0) == 0
    assert state(qp)["halted"]["reason"] == "queue-changed" and len(be.launches) == 1


def test_next_without_approval_is_refused(tmp_path):
    qp = mk_queue(tmp_path, [mk_item(tmp_path, "a1")])
    be = lq.FakeBackend(six_gpus())
    assert run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0) == 2
    assert not be.launches


def test_table_lists_every_item(tmp_path, capsys):
    qp, be = ready(tmp_path, 3)
    assert run(be, "table", qp, "--gpus", "0,1") == 0
    out = capsys.readouterr().out
    assert "| 판 | 목적 | 기준판 | 변경 사항 |" in out and "a3 변경" in out and "판 > GPU" in out


# ───────────── Phase 2: 발사 ─────────────

def test_eight_items_six_gpus(tmp_path):
    """성공 기준 1(로직 부분): 6개가 먼저 올라가고 끝나는 GPU 마다 나머지 2개가 사람 없이 올라간다."""
    qp, be = ready(tmp_path, 8)
    assert run(be, "start", qp, "--gpus", "0,1,2,3,4,5") == 0
    assert [(i, s) for i, s, _ in be.launches] == [(f"a{k}", f"tq{k - 1}:0") for k in range(1, 7)]   # 세션 = 접두 + GPU 번호, 첫 창
    assert statuses(qp) == {**{f"a{k}": "running" for k in range(1, 7)}, "a7": "queued", "a8": "queued"}
    assert run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0) == 0
    assert run(be, "next", "--queue", qp, "--item", "a2", "--gpu", 1, "--exit", 0) == 0
    st = state(qp)["items"]
    assert (st["a7"]["status"], st["a7"]["gpu"], st["a7"]["tmux"]) == ("running", 0, "tq0:1")   # 같은 GPU 0 의 세션에 창이 더해진다
    assert (st["a8"]["status"], st["a8"]["gpu"], st["a8"]["tmux"]) == ("running", 1, "tq1:1")
    assert st["a1"]["status"] == st["a2"]["status"] == "done"
    assert len(be.launches) == 8 and len({s for _, s, _ in be.launches}) == 8 and len(be.sessions) == 6
    assert any("자동 발사: 판 a7 → GPU 0" in n for n in be.notes)
    assert be.signatures[-1][2] == "watcher-queue" and be.signatures[0][2] == "queue-start"


def test_launch_script_is_quoted_substituted_and_valid_bash(tmp_path):
    qp, be = ready(tmp_path, 1, argv=["env", "FAKE_GPU={GPU}", "bash", "run it.sh"])
    run(be, "start", qp, "--gpus", "3")
    script = be.launches[0][2]
    text = script.read_text()
    assert "FAKE_GPU=3" in text and "'run it.sh'" in text and "unset GPU_PREFLIGHT_FAKE" in text
    assert "--gpu 3 --vram-gb 20 --cpu-cores 4" in text and f"--queue {qp}" in text and "--queue-item a1" in text
    assert "--name tq3-a1-1" in text and f"--state {tmp_path}/logs/a1/launch-state-tq3-a1-1.json" in text and f"--watcher-log {tmp_path}/logs/a1/watcher-tq3-a1-1.log" in text
    assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0
    assert script.name == "a1-1.sh" and script.parent.name == "q1.launch"


def test_big_vram_item_skips_l40s_and_lands_on_h100(tmp_path):
    """성공 기준 3: 60GB 판은 빈 L40S(45GB)를 건너뛰고 H100 이 빈 뒤에 올라간다."""
    qp = mk_queue(tmp_path, [mk_item(tmp_path, "big", vram_gb=60), mk_item(tmp_path, "small", vram_gb=20)])
    be = lq.FakeBackend({0: gpu(*L40S), 1: gpu(*H100)})
    run(be, "approve", qp)
    run(be, "start", qp, "--gpus", "0,1")
    st = state(qp)["items"]
    assert (st["small"]["gpu"], st["big"]["gpu"]) == (0, 1)
    # L40S 만 비는 상황에서는 big 이 남아 있어도 올리지 않고 알린다
    qp2 = mk_queue(tmp_path / "second", [mk_item(tmp_path, "x", vram_gb=20), mk_item(tmp_path, "big2", vram_gb=60)])
    be2 = lq.FakeBackend({0: gpu(*L40S), 1: gpu(*H100)})
    run(be2, "approve", qp2)
    run(be2, "start", qp2, "--gpus", "0")
    assert run(be2, "next", "--queue", qp2, "--item", "x", "--gpu", 0, "--exit", 0) == 0
    assert statuses(qp2) == {"x": "done", "big2": "queued"} and len(be2.launches) == 1
    assert any("들어가는 대기 판이 없습니다" in n for n in be2.notes)
    run(be2, "start", qp2, "--gpus", "1")   # H100 이 비면 올라간다
    assert statuses(qp2)["big2"] == "running" and state(qp2)["items"]["big2"]["gpu"] == 1


def test_preflight_decide_checks_vram_on_empty_gpu():
    a = lambda v: type("A", (), {"vram_gb": v, "cpu_cores": None, "util_max": 70.0, "sample_sec": 60, "cpu_reserve": 8.0, "vram_margin": 0.1})()
    g = {0: gpu(*L40S)}
    assert lq.gp.decide(g, [0], {}, None, a(None))[0]       # 크기를 안 주면 종전대로 통과
    assert lq.gp.decide(g, [0], {}, None, a(30))[0]
    ok, msgs = lq.gp.decide(g, [0], {}, None, a(60))
    assert not ok and "빈 VRAM 44.5GB < 필요 66.0GB" in msgs[0]


def test_gpu_preflight_fake_env_drives_exit_code(tmp_path):
    fake = tmp_path / "fake.json"
    fake.write_text(json.dumps({"gpus": {"0": gpu(*L40S), "1": gpu(*H100)}, "idle_cores": 90}))
    env = {**os.environ, "GPU_PREFLIGHT_FAKE": str(fake)}

    def pf(g, vram):
        return subprocess.run(["python3", str(TW_DIR / "gpu_preflight.py"), "--gpu", g, "--vram-gb", vram, "--cpu-cores", "4"],
                              check=False, env=env, capture_output=True, text=True, timeout=20)
    assert pf("0", "60").returncode == 76
    assert pf("1", "60").returncode == 0
    assert pf("0", "20").returncode == 0
    assert pf("9", "20").returncode == 64


def test_concurrent_next_never_launches_same_item_twice(tmp_path):
    """성공 기준 5: 두 판이 같은 순간 끝나도 남은 판은 한 번만 올라간다."""
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100), 1: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0,1")
    be.delay = 0.4   # 두 next 의 발사 구간을 겹치게 한다
    errors = []

    def call(item, g):
        try:
            run(be, "next", "--queue", qp, "--item", item, "--gpu", g, "--exit", 0)
        except Exception as e:   # noqa: BLE001 — 스레드 안 예외를 메인에서 단정
            errors.append(e)
    ts = [threading.Thread(target=call, args=("a1", 0)), threading.Thread(target=call, args=("a2", 1))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    assert [i for i, _, _ in be.launches].count("a3") == 1 and len(be.launches) == 3
    assert statuses(qp) == {"a1": "done", "a2": "done", "a3": "running"}


def test_record_exit_maps_codes():
    st = {"items": {k: lq.new_item_state(i) for i, k in enumerate("abcdef")}}
    for k, code in zip("abcd", [0, 2, 3, 4]):
        lq.record_exit(st, k, 7, code)
    s = {k: v["status"] for k, v in st["items"].items()}
    assert (s["a"], s["b"], s["c"], s["d"]) == ("done", "needs-fix", "eval-failed", "timeout")
    assert st["items"]["b"]["exit"] == 2 and st["items"]["b"]["gpu"] == 7
    st["items"]["e"]["attempt"] = 1
    lq.record_exit(st, "e", 7, 5)   # 발사 거부: queued 로 되돌려 목록 뒤로, 시도 수는 되돌림
    assert st["items"]["e"]["status"] == "queued" and st["items"]["e"]["rank"] > st["items"]["f"]["rank"] and st["items"]["e"]["attempt"] == 0
    lq.record_exit(st, "f", 7, 9)
    assert st["items"]["f"]["status"] == "failed"
    lq.record_exit(st, "없는판", 7, 0)   # 목록에 없는 판은 무시


def test_abnormal_exit_marks_needs_fix_and_launch_continues(tmp_path):
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    assert run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2) == 0
    st = state(qp)["items"]
    assert st["a1"]["status"] == "needs-fix" and st["a1"]["exit"] == 2
    assert st["a2"]["status"] == "running"


def test_exit_5_requeues_to_back_and_caps_refusals(tmp_path):
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100)})
    s = state(qp)
    s["items"]["a1"].update(status="running", attempt=1)
    lq.save_state(qp, s)
    be.rc["a1"] = 76   # 다시 골라져도 거부
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 5)
    st = state(qp)["items"]
    assert st["a1"]["rank"] > st["a3"]["rank"] and st["a1"]["refused"] >= 1
    assert st["a2"]["status"] == "running"        # 먼저 올라간 건 a2(a1 은 목록 뒤로 밀렸다)
    # 거부만 반복하는 판은 상한에서 닫혀 목록을 맴돌지 않는다
    for _ in range(lq.MAX_REFUSALS):
        s = state(qp)
        if s["items"]["a1"]["status"] == "launch-failed":
            break
        s["items"]["a1"]["status"] = "queued"
        s["items"]["a2"]["status"], s["items"]["a3"]["status"] = "running", "done"   # 종료 보고는 도는 판에 대해서만 받는다
        lq.save_state(qp, s)
        run(be, "next", "--queue", qp, "--item", "a2", "--gpu", 0, "--exit", 0)
    assert state(qp)["items"]["a1"]["status"] == "launch-failed"


def test_launch_refusal_76_skips_to_next_candidate(tmp_path):
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100)})
    be.rc["a1"] = 76
    run(be, "start", qp, "--gpus", "0")
    st = state(qp)["items"]
    assert [i for i, _, _ in be.launches] == ["a1", "a2"]
    assert st["a1"]["status"] == "queued" and st["a1"]["attempt"] == 0 and st["a1"]["refused"] == 1
    assert st["a2"]["status"] == "running" and st["a2"]["attempt"] == 1


def test_launch_failure_stops_that_gpu_and_notifies(tmp_path):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    be.rc["a1"] = 1   # 발사는 됐으나 verify 실패
    run(be, "start", qp, "--gpus", "0")
    st = state(qp)["items"]
    assert st["a1"]["status"] == "launch-failed" and st["a2"]["status"] == "queued" and len(be.launches) == 1
    assert any("verify-failed" in n for n in be.notes)


@pytest.mark.parametrize("rc,tail,want", [
    (0, "", "ok"), (1, "", "verify-failed"), (76, "", "refused"), (None, "", "timeout"), (64, "", "not-started"), (67, "", "not-started"), (70, "", "error"), (66, "", "error"),
    (65, "[memguard] 예산 부족 — 발사 거부", "refused"), (65, "Traceback", "crashed")])
def test_classify_launch(rc, tail, want):
    assert lq.classify_launch(rc, tail) == want


def test_stale_reservation_is_closed():
    st = {"items": {"a": {"status": "launching", "reserved_epoch": 0}, "b": {"status": "launching", "reserved_epoch": 999}}}
    lq.sweep_stale(st, now=1000)
    assert st["items"]["a"]["status"] == "launch-failed" and st["items"]["b"]["status"] == "launching"


def test_env_problem_or_missing_prefix_blocks_launch(tmp_path):
    qp, be = ready(tmp_path, 2)
    be.env_msg = "XDG_RUNTIME_DIR 없음"
    run(be, "start", qp, "--gpus", "0")
    assert not be.launches and list(qp.with_name("q1.events").glob("*launch-blocked*")) and any("발사 불가" in n for n in be.notes)
    be.env_msg = None
    (qp.parents[1] / "train.env").write_text("CKPT_ROOT=/x\n")
    run(be, "start", qp, "--gpus", "0")
    assert not be.launches


def test_pick_candidate_is_pure_and_ordered():
    items = [{"id": "big", "vram_gb": 60, "cpu_cores": 4}, {"id": "mid", "vram_gb": 20, "cpu_cores": 4}, {"id": "low", "vram_gb": 10, "cpu_cores": 4}]
    st = {k: {"status": "queued"} for k in ("big", "mid", "low")}
    gpus = {0: gpu(*L40S), 1: gpu(*H100)}
    snap = copy.deepcopy((items, st, gpus))
    assert lq.pick_candidate(items, st, 0, gpus, set())["id"] == "mid"
    assert lq.pick_candidate(items, st, 1, gpus, set())["id"] == "big"
    assert lq.pick_candidate(items, st, 0, gpus, {"mid"})["id"] == "low"
    st["mid"]["status"] = "running"
    assert lq.pick_candidate(items, st, 0, gpus, set())["id"] == "low"
    assert (items, st["big"], gpus) == (snap[0], snap[1]["big"], snap[2])


# ───────────── 와쳐 --on-exit (실제 train-watcher.sh) ─────────────

def _spawn_dummy_training(sec, log=None, text=""):
    """sec 초 뒤 text 를 log 에 덧붙이고 끝나는 가짜 학습(완료 마커는 와쳐가 뜬 «뒤»에 찍혀야 이번 실행의 것으로 본다)."""
    cmd = ["bash", "-c", f"sleep {sec}; printf %s {shlex.quote(text)} >> {shlex.quote(str(log))}"] if log else ["sleep", str(sec)]
    p = subprocess.Popen(cmd)
    threading.Thread(target=p.wait, daemon=True).start()   # 좀비로 남으면 kill -0 이 계속 성공하므로 거둔다
    return p.pid


def _watch(tmp_path, tag, log_text, on_exit=None, old_log="", extra=(), sec=2, eval_cmd="true"):
    """log_text = 가짜 학습이 끝날 때 로그에 덧붙이는 내용, old_log = 시작 전에 이미 있던 내용(재사용한 로그)."""
    log = tmp_path / f"{tag}.log"
    log.write_text(old_log)
    cmd = ["bash", str(SCRIPT_DIR / "train-watcher.sh"), "--pid", str(_spawn_dummy_training(sec, log, log_text)), "--log", str(log), "--done-regex", "TRAIN_DONE",
           "--eval-cmd", eval_cmd, "--title", tag, "--interval", "1", "--no-notify", *extra]
    if on_exit:
        cmd += ["--on-exit", on_exit]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=tmp_path)


def test_watcher_on_exit_runs_once_with_watch_exit(tmp_path):
    out0, out2, outf = tmp_path / "out0.txt", tmp_path / "out2.txt", tmp_path / "outf.txt"
    procs = {
        "ok": _watch(tmp_path, "ok", "TRAIN_DONE\n", f'echo "$WATCH_EXIT" >> {out0}'),
        "crash": _watch(tmp_path, "crash", "no marker\n", f'echo "$WATCH_EXIT" >> {out2}'),
        "failing_hook": _watch(tmp_path, "failing_hook", "TRAIN_DONE\n", f'echo "$WATCH_EXIT" >> {outf}; exit 7'),
        "no_hook": _watch(tmp_path, "no_hook", "TRAIN_DONE\n"),
    }
    outs = {k: p.communicate(timeout=60)[0] for k, p in procs.items()}
    rcs = {k: p.returncode for k, p in procs.items()}
    assert rcs == {"ok": 0, "crash": 2, "failing_hook": 0, "no_hook": 0}   # 훅 실패·유무와 무관하게 종료 코드는 그대로
    assert out0.read_text().split() == ["0"]
    assert out2.read_text().split() == ["2"]
    assert outf.read_text().split() == ["0"] and "on-exit 실패 (exit 7)" in outs["failing_hook"]
    assert "on-exit" not in outs["no_hook"]


# ───────────── launch-set.sh 인자 검사 (발사 전에 끝나는 경로만) ─────────────

def _launch_set(tmp_path, *extra):
    cmd = ["bash", str(SCRIPT_DIR / "launch-set.sh"), "launch", "--name", "n", "--log", "l.log", "--done-regex", "x", "--eval-cmd", "true",
           "--title", "t", "--expect", "e", *extra, "--", "sleep", "1"]
    r = subprocess.run(cmd, check=False, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert not list(tmp_path.glob("*.log")) and not list(tmp_path.glob("launch-state*")), "인자 단계에서 끝나야 하는데 파일이 생김"
    return r


def test_launch_set_queue_args_validated_before_any_launch(tmp_path):
    q = tmp_path / "q.json"
    q.write_text("{}")
    r = _launch_set(tmp_path, "--queue", str(q))
    assert r.returncode == 64 and "함께 줘야" in r.stderr
    r = _launch_set(tmp_path, "--queue-item", "a1")
    assert r.returncode == 64 and "함께 줘야" in r.stderr
    r = _launch_set(tmp_path, "--queue", str(q), "--queue-item", "a1")
    assert r.returncode == 64 and "--gpu" in r.stderr
    r = _launch_set(tmp_path, "--queue", str(tmp_path / "none.json"), "--queue-item", "a1", "--gpu", "0")
    assert r.returncode == 64 and "없거나" in r.stderr


@pytest.mark.parametrize("wa", ["--timeout-h 1 --on-exit foo", "--on-exit=foo"])
def test_launch_set_refuses_on_exit_in_watcher_args(tmp_path, wa):
    r = _launch_set(tmp_path, "--watcher-args", wa)
    assert r.returncode == 64 and "--on-exit" in r.stderr


def _launch_set_at(cwd, *extra):
    """Run launch-set.sh launch in cwd; a pre-existing state file makes it exit 67 right after the default-path step (no real launch)."""
    cmd = ["bash", str(SCRIPT_DIR / "launch-set.sh"), "launch", "--name", "n", "--log", "l.log", "--done-regex", "x", "--eval-cmd", "true",
           "--title", "t", "--expect", "e", *extra, "--", "sleep", "1"]
    env = {k: v for k, v in os.environ.items() if k not in ("CUDA_VISIBLE_DEVICES", "GPU_PREFLIGHT_FAKE")}
    return subprocess.run(cmd, check=False, cwd=cwd, capture_output=True, text=True, timeout=30, env=env)


def test_launch_set_default_state_and_watcher_log_go_under_scratch_launch(tmp_path):
    """Default state/watcher-log live in <git root>/.scratch/launch/ and nothing is created in cwd or the repo top level."""
    repo = tmp_path / "repo"
    sub = repo / "sub"
    sub.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    ldir = repo / ".scratch" / "launch"
    ldir.mkdir(parents=True)
    (ldir / "launch-state-n.json").write_text("{}")
    r = _launch_set_at(sub)
    assert r.returncode == 67 and str(ldir / "launch-state-n.json") in r.stderr
    assert (ldir / "launch-state-n.json.lock").exists()
    assert sorted(p.name for p in repo.iterdir()) == [".git", ".scratch", "sub"]
    assert list(sub.iterdir()) == []


def test_launch_set_default_dir_created_and_no_git_falls_back_to_cwd(tmp_path):
    """Missing default dir is created via mkdir -p (explicit --state still honoured); outside git the root is the cwd."""
    plain = tmp_path / "plain"
    plain.mkdir()
    st = plain / "mystate.json"
    st.write_text("{}")
    r = _launch_set_at(plain, "--state", str(st))
    assert r.returncode == 67 and (plain / ".scratch" / "launch").is_dir()   # watcher-log default triggered mkdir, state stayed where given
    assert not list((plain / ".scratch" / "launch").glob("launch-state*"))
    assert sorted(p.name for p in plain.iterdir()) == [".scratch", "mystate.json", "mystate.json.lock"]


def test_launch_set_default_dir_unwritable_is_refused_before_launch(tmp_path):
    """If .scratch/launch cannot be created the launch is refused (exit 64) before anything starts."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / ".scratch").write_text("not a dir")   # a file blocks mkdir -p
    r = _launch_set_at(plain)
    assert r.returncode == 64 and "기본 출력 폴더" in r.stderr


@pytest.mark.parametrize("name", ["launch-set.sh", "train-watcher.sh"])
def test_shell_scripts_parse(name):
    assert subprocess.run(["bash", "-n", str(SCRIPT_DIR / name)], check=False).returncode == 0


# ───────────── 검수 차단 B1: 시험 전용 GPU_PREFLIGHT_FAKE 가 운영 경로에 남지 않는다 ─────────────

def test_launch_set_refuses_fake_preflight_env(tmp_path):
    env = {**os.environ, "GPU_PREFLIGHT_FAKE": str(tmp_path / "fake.json")}
    for cmd in (["launch", "--name", "n", "--log", "l.log", "--done-regex", "x", "--eval-cmd", "true", "--title", "t", "--expect", "e", "--", "sleep", "1"],
                ["reattach", str(tmp_path / "none.json")]):
        r = subprocess.run(["bash", str(SCRIPT_DIR / "launch-set.sh"), *cmd], check=False, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 64 and "GPU_PREFLIGHT_FAKE" in r.stderr
    assert not list(tmp_path.glob("*.log")) and not list(tmp_path.glob("launch-state*"))


def test_make_backend_removes_fake_env_and_warns(monkeypatch, capsys):
    monkeypatch.setenv("GPU_PREFLIGHT_FAKE", "/x/fake.json")
    be = lq.make_backend()
    assert isinstance(be, lq.TmuxBackend) and "GPU_PREFLIGHT_FAKE" not in os.environ
    assert "GPU_PREFLIGHT_FAKE" in capsys.readouterr().err
    lq.make_backend()   # 변수가 없으면 경고 없음
    assert capsys.readouterr().err == ""


# ───────────── 검수 차단 B2: 큐가 가동 중으로 아는 GPU 에는 또 올리지 않는다 ─────────────

def test_exit_4_timeout_launches_nothing_and_blocks_gpu(tmp_path):
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    assert run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 4) == 0
    it = state(qp)["items"]
    assert len(be.launches) == 1 and it["a1"]["status"] == "timeout" and it["a1"]["maybe_alive"] and "살아 있을 수 있어" in it["a1"]["fail_reason"]
    assert sum("타임아웃" in n for n in be.notes) == 1
    run(be, "start", qp, "--gpus", "0")      # 살아 있을 수 있는 판이 GPU 를 쥔 채로 남는다
    assert len(be.launches) == 1
    # 와쳐가 뒤늦게라도 정상 종료를 보고하면 점유가 풀린다
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0)
    assert len(be.launches) == 2


def test_launch_rc_65_stops_chain_without_trying_next_candidate(tmp_path):
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100)})
    be.rc["a1"] = 65
    run(be, "start", qp, "--gpus", "0")
    it = state(qp)["items"]
    assert [i for i, _, _ in be.launches] == ["a1"] and it["a2"]["status"] == "queued"
    assert it["a1"]["status"] == "launch-failed" and it["a1"]["maybe_alive"]
    run(be, "start", qp, "--gpus", "0")
    assert len(be.launches) == 1


def test_start_rejects_duplicate_gpus_with_64(tmp_path):
    qp, be = ready(tmp_path, 3)
    assert run(be, "start", qp, "--gpus", "0,0") == 64
    assert not be.launches


def test_start_rerun_does_not_double_launch(tmp_path, capsys):
    qp, be = ready(tmp_path, 4, gpus={0: gpu(*H100), 1: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0,1")
    capsys.readouterr()
    assert run(be, "start", qp, "--gpus", "0,1") == 0
    out = capsys.readouterr().out
    assert len(be.launches) == 2 and out.count("쥐고 있어 건너뜀") == 2
    assert statuses(qp) == {"a1": "running", "a2": "running", "a3": "queued", "a4": "queued"}


def test_two_nexts_for_different_items_on_same_gpu_launch_once(tmp_path):
    qp, be = ready(tmp_path, 4, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    s = state(qp)
    s["items"]["a2"].update(status="running", gpu=0)   # 같은 GPU 를 나눠 쓰던 두 판
    lq.save_state(qp, s)
    be.delay = 0.4
    ts = [threading.Thread(target=run, args=(be, "next", "--queue", qp, "--item", i, "--gpu", 0, "--exit", 0)) for i in ("a1", "a2")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert [i for i, _, _ in be.launches] == ["a1", "a3"]
    assert statuses(qp) == {"a1": "done", "a2": "done", "a3": "running", "a4": "queued"}


def test_launch_exception_closes_item_and_stops_chain(tmp_path):
    class Boom(lq.FakeBackend):
        def launch(self, *a, **k):
            raise RuntimeError("tmux 서버 없음")
    qp = mk_queue(tmp_path, [mk_item(tmp_path, "a1"), mk_item(tmp_path, "a2")])
    be = Boom({0: gpu(*H100)})
    run(be, "approve", qp)
    assert run(be, "start", qp, "--gpus", "0") == 0
    it = state(qp)["items"]
    assert it["a1"]["status"] == "launch-failed" and "RuntimeError" in it["a1"]["fail_reason"] and it["a1"]["maybe_alive"]
    assert it["a2"]["status"] == "queued" and len(be.notes) == 1


@pytest.mark.parametrize("bad", ["a b", "a\nb", "a\n", "-a", ".a", "a..b", "a/b", ""])
def test_unsafe_item_id_or_name_rejected(tmp_path, bad):
    q = good(tmp_path)
    q["items"][0]["id"] = bad
    with pytest.raises(lq.QueueError):
        lq.parse_queue(json.dumps(q).encode(), "q1")
    q = good(tmp_path)
    q["name"] = bad
    with pytest.raises(lq.QueueError):
        lq.parse_queue(json.dumps(q).encode(), bad)


def test_launch_script_cd_failure_writes_rc_file(tmp_path):
    qp, be = ready(tmp_path, 1)
    run(be, "start", qp, "--gpus", "0")
    script = be.launches[0][2]
    text = script.read_text().replace(f"cd {qp.parents[2]}", "cd /nonexistent-dir-for-test")
    assert "/nonexistent-dir-for-test" in text
    broken = tmp_path / "broken.sh"
    broken.write_text(text)
    rc_file = script.with_suffix(".rc")
    rc_file.unlink(missing_ok=True)
    assert subprocess.run(["bash", str(broken)], check=False, capture_output=True).returncode == 64
    assert rc_file.read_text().strip() == "64"


# ───────────── tmux 배치: 세션 = 접두 + GPU 번호, 같은 GPU 의 여러 판은 창 ─────────────

def test_sessions_are_prefix_plus_gpu_number_and_never_grow_beyond_gpus(tmp_path):
    """8판이 6 GPU 에 오르는 동안 만들어진 세션은 접두+GPU 번호뿐이고 6개를 넘지 않는다. 늘어나는 것은 창이다."""
    qp, be = ready(tmp_path, 8)
    run(be, "start", qp, "--gpus", "0,1,2,3,4,5")
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0)
    run(be, "next", "--queue", qp, "--item", "a2", "--gpu", 1, "--exit", 0)
    assert set(be.sessions) == {f"tq{g}" for g in range(6)}
    assert all(re.fullmatch(r"tq[0-5]", s) for s in be.sessions)
    assert be.sessions["tq0"] == [0, 1] and be.sessions["tq1"] == [0, 1] and be.sessions["tq2"] == [0]


def test_consecutive_items_on_one_gpu_add_windows_not_sessions(tmp_path):
    qp, be = ready(tmp_path, 4, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    for k in (1, 2, 3):
        run(be, "next", "--queue", qp, "--item", f"a{k}", "--gpu", 0, "--exit", 0)
    assert list(be.sessions) == ["tq0"] and be.sessions["tq0"] == [0, 1, 2, 3]
    assert [t for _, t, _ in be.launches] == ["tq0:0", "tq0:1", "tq0:2", "tq0:3"]
    assert [state(qp)["items"][f"a{k}"]["tmux"] for k in range(1, 5)] == ["tq0:0", "tq0:1", "tq0:2", "tq0:3"]   # status·알림이 어느 창인지 보인다


def test_launch_name_state_and_watcher_log_are_unique_per_item_and_attempt(tmp_path):
    qp = mk_queue(tmp_path, [mk_item(tmp_path, "a1"), mk_item(tmp_path, "a1-2")])
    items = lq.parse_queue(qp.read_bytes(), "q1")["items"]
    seen = set()
    for item in items:
        for attempt in (1, 2):
            text = lq.write_launch_script(qp, item, attempt, "tq0", 0)[0].read_text()
            name = re.search(r"--name (\S+)", text).group(1)
            assert re.fullmatch(r"[A-Za-z0-9._-]+", name) and name == f"tq0-{item['id']}-{attempt}"   # launch-set.sh 의 --name 허용 형식
            assert f"launch-state-{name}.json" in text and f"watcher-{name}.log" in text
            seen.add(name)
    assert len(seen) == 4


def test_state_tmux_field_is_session_and_window_after_launch(tmp_path, capsys):
    qp, be = ready(tmp_path, 1, gpus={3: gpu(*H100)})
    run(be, "start", qp, "--gpus", "3")
    assert state(qp)["items"]["a1"]["tmux"] == "tq3:0"
    capsys.readouterr()
    run(be, "status", qp)
    assert "tq3:0" in capsys.readouterr().out


def test_old_format_state_without_window_number_still_loads(tmp_path, capsys):
    """옛 state 의 tmux 필드는 세션 이름만이다(tq7). status 와 next 가 그대로 읽고 이어 간다."""
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    set_state(qp, a1={"tmux": "tq7"})
    capsys.readouterr()
    assert run(be, "status", qp) == 0 and "tq7" in capsys.readouterr().out
    assert run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2) == 0
    st = state(qp)["items"]
    assert st["a1"]["status"] == "needs-fix" and st["a2"]["tmux"] == "tq0:1"
    assert events(qp, "needs-fix")[0]["session"] == "tq7"


def _fake_tmux_run(monkeypatch, sessions, windows=None):
    """lq.run_proc 를 가짜로 바꾼 tmux: 호출 argv 를 기록하고 세션·창 상태를 흉내 낸다(실제 tmux 는 부르지 않는다)."""
    calls, windows = [], windows if windows is not None else {}
    def fake(cmd, **kw):
        calls.append(cmd)
        assert cmd[0] == "tmux"
        sub = cmd[1]
        name = cmd[cmd.index("-s") + 1] if "-s" in cmd else cmd[cmd.index("-t") + 1].lstrip("=").split(":")[0]
        if sub == "has-session":
            return SimpleNamespace(returncode=0 if name in sessions else 1, stdout="", stderr="")
        if sub == "new-session":
            sessions.add(name)
            windows[name] = [0]
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        if sub == "new-window":
            windows[name].append(max(windows[name]) + 1)
            return SimpleNamespace(returncode=0, stdout=f"{windows[name][-1]}\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(lq, "run_proc", fake)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1/bus")
    return calls


def test_tmux_backend_creates_session_when_absent_then_adds_window_when_present(tmp_path, monkeypatch):
    calls = _fake_tmux_run(monkeypatch, set())
    be = lq.TmuxBackend()
    assert be.open_window("tq0", "/proj") == "tq0:0"
    assert [c[1] for c in calls] == ["has-session", "new-session"]
    ns = calls[1]
    assert ns[2:] == ["-d", "-P", "-F", "#{window_index}", "-s", "tq0", "-c", "/proj",
                      "-e", "XDG_RUNTIME_DIR=/run/user/1", "-e", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1/bus"]
    calls.clear()
    assert be.open_window("tq0", "/proj") == "tq0:1"                               # 세션이 이미 있으면 새 세션이 아니라 새 창
    assert [c[1] for c in calls] == ["has-session", "new-window"]
    assert calls[1][2:] == ["-d", "-P", "-F", "#{window_index}", "-t", "=tq0:", "-c", "/proj",
                            "-e", "XDG_RUNTIME_DIR=/run/user/1", "-e", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1/bus"]
    calls.clear()
    assert be.open_window("tq0", "/proj") == "tq0:2"
    calls.clear()
    rc_file = tmp_path / "a.rc"
    rc_file.write_text("0\n")
    assert be.launch("tq0:2", tmp_path / "a-1.sh", rc_file, 5) == 0
    assert calls == [["tmux", "send-keys", "-t", "=tq0:2", f"bash {tmp_path}/a-1.sh", "Enter"]]   # 방금 만든 그 창에만 키를 보낸다


def test_tmux_backend_only_touches_sessions_named_prefix_plus_gpu(tmp_path, monkeypatch):
    """qpath 쪽 발사 흐름 전체를 TmuxBackend 로 돌려, tmux 에 닿는 모든 세션 이름이 접두+GPU 번호인지 본다."""
    sessions = set()
    calls = _fake_tmux_run(monkeypatch, sessions)
    qp = mk_queue(tmp_path, [mk_item(tmp_path, f"a{i}") for i in range(1, 4)])
    fake = lq.FakeBackend({0: gpu(*H100), 1: gpu(*H100)})
    be = lq.TmuxBackend()
    be.gpus, be.env_problem, be.notify, be.sign, be.oversight = fake.gpus, fake.env_problem, fake.notify, fake.sign, fake.oversight
    be.verify = fake.verify
    monkeypatch.setattr(lq, "LAUNCH_WAIT_SEC", 5)
    real_launch = lq.TmuxBackend.launch

    def launch_with_rc(self, target, script, rc_file, timeout):
        rc_file.write_text("0\n")   # launch-set.sh 가 끝나 .rc 를 남겼다고 친다
        return real_launch(self, target, script, rc_file, timeout)
    monkeypatch.setattr(lq.TmuxBackend, "launch", launch_with_rc)
    run(be, "approve", qp)
    run(be, "start", qp, "--gpus", "0,1")
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0)
    names = {c[c.index("-s") + 1] if "-s" in c else c[c.index("-t") + 1].lstrip("=").split(":")[0] for c in calls}
    assert names == {"tq0", "tq1"} and sessions == {"tq0", "tq1"}
    assert [c[1] for c in calls].count("new-session") == 2 and [c[1] for c in calls].count("new-window") == 1
    assert [c[3] for c in calls if c[1] == "send-keys"] == ["=tq0:0", "=tq1:0", "=tq0:1"]
    assert [state(qp)["items"][i]["tmux"] for i in ("a1", "a2", "a3")] == ["tq0:0", "tq1:0", "tq0:1"]


def test_tmux_backend_falls_back_to_new_window_when_session_appears_between_check_and_create(monkeypatch):
    seq = iter([SimpleNamespace(returncode=1, stdout="", stderr=""),                    # has-session: 없음
                SimpleNamespace(returncode=1, stdout="", stderr="duplicate session"),   # new-session: 그 사이 다른 곳이 만들었다
                SimpleNamespace(returncode=0, stdout="", stderr=""),                    # has-session: 있음
                SimpleNamespace(returncode=0, stdout="4\n", stderr="")])                # new-window
    calls = []
    monkeypatch.setattr(lq, "run_proc", lambda cmd, **kw: (calls.append(cmd), next(seq))[1])
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "x")
    assert lq.TmuxBackend().open_window("tq0", "/p") == "tq0:4"
    assert [c[1] for c in calls] == ["has-session", "new-session", "has-session", "new-window"]


def test_tmux_backend_rejects_missing_window_index_and_failed_create(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "x")
    seq = iter([SimpleNamespace(returncode=0, stdout="", stderr=""), SimpleNamespace(returncode=0, stdout="oops\n", stderr="")])
    monkeypatch.setattr(lq, "run_proc", lambda cmd, **kw: next(seq))
    with pytest.raises(RuntimeError, match="창 번호"):
        lq.TmuxBackend().open_window("tq0", "/p")
    seq = iter([SimpleNamespace(returncode=1, stdout="", stderr=""), SimpleNamespace(returncode=1, stdout="", stderr="no server"), SimpleNamespace(returncode=1, stdout="", stderr="")])
    monkeypatch.setattr(lq, "run_proc", lambda cmd, **kw: next(seq))
    with pytest.raises(RuntimeError, match="new-session 실패"):
        lq.TmuxBackend().open_window("tq0", "/p")


# ───────────── Phase 3: 비정상 종료 · 재발사 · 이벤트 · 요약 ─────────────

def set_state(qp, **per_item):
    """판별 state 를 직접 만든다(시험 준비용). set_state(qp, a1={"status": "running", "gpu": 0})"""
    s = state(qp)
    for k, v in per_item.items():
        s["items"][k].update(v)
    lq.save_state(qp, s)


def events(qp, kind=None):
    d = qp.with_name("q1.events")
    found = [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.is_dir() else []
    return [e for e in found if kind in (None, e["kind"])]


def test_exit2_writes_needs_fix_event_and_next_item_still_launches(tmp_path):
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    assert run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2) == 0
    st = state(qp)["items"]
    assert st["a1"]["status"] == "needs-fix" and st["a2"]["status"] == "running"
    ev = events(qp, "needs-fix")
    assert len(ev) == 1 and ev[0]["item"] == "a1" and ev[0]["gpu"] == 0 and "relaunch" in ev[0]["hint"] and ev[0]["watcher_report"].endswith("run.watch-report.md")
    assert not any("재발사" in n for n in be.notes)   # needs-fix 는 알림 대신 이벤트로 세션을 깨운다


def test_relaunch_once_then_refail_closes_only_that_item(tmp_path, capsys):
    qp, be = ready(tmp_path, 4, gpus={0: gpu(*H100), 1: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0,1")
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)          # a1 needs-fix, a3 → GPU 0
    capsys.readouterr()
    assert run(be, "relaunch", qp, "--item", "a1", "--fix-note", "lr 오타 수정") == 0
    assert "대기 맨 앞" in capsys.readouterr().out                                      # 두 GPU 모두 점유 → 대기 맨 앞(발사 못 한 GPU 별 결과 뒤에 한 줄)
    it = state(qp)["items"]
    assert it["a1"]["status"] == "queued" and it["a1"]["fixes"] == 1 and it["a1"]["rank"] < it["a4"]["rank"] and it["a1"]["fix_note"] == "lr 오타 수정"
    run(be, "next", "--queue", qp, "--item", "a2", "--gpu", 1, "--exit", 0)           # 빈 GPU 1 → 맨 앞 a1 이 먼저
    it = state(qp)["items"]
    assert it["a1"]["status"] == "running" and it["a1"]["attempt"] == 2 and it["a1"]["gpu"] == 1 and it["a4"]["status"] == "queued"
    assert be.launches[-1][2].name == "a1-2.sh"
    n = len(be.notes)
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 1, "--exit", 2)           # 재실패 → 그 판만 failed, 나머지는 계속
    it = state(qp)["items"]
    assert it["a1"]["status"] == "failed" and it["a1"]["fail_stage"] == "refail" and it["a4"]["status"] == "running"
    assert sum("재발사 후 다시 비정상 종료" in x for x in be.notes[n:]) == 1
    assert run(be, "relaunch", qp, "--item", "a1", "--fix-note", "또") == 2          # 판당 1회 한정(failed 판은 받지 않음)


def test_relaunch_launches_immediately_on_free_gpu(tmp_path):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100), 1: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)           # a2 가 GPU 0 을 차지
    assert run(be, "relaunch", qp, "--item", "a1", "--fix-note", "수정", "--gpus", "1") == 0
    it = state(qp)["items"]
    assert it["a1"]["status"] == "running" and it["a1"]["gpu"] == 1 and it["a1"]["attempt"] == 2


def test_relaunch_rejects_non_needs_fix_and_changed_launch_args(tmp_path, capsys):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    assert run(be, "relaunch", qp, "--item", "a1", "--fix-note", "x") == 2            # running 판은 받지 않는다
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)
    n = len(be.launches)
    qp.write_text(qp.read_text().replace("run.sh", "run2.sh"))                         # 발사 인자(argv)를 바꿨다
    capsys.readouterr()
    assert run(be, "relaunch", qp, "--item", "a1", "--fix-note", "x") == 2
    assert "재승인 필요" in capsys.readouterr().err
    assert state(qp)["items"]["a1"]["status"] == "needs-fix" and len(be.launches) == n and state(qp)["halted"]


def test_gpu_excluded_after_two_different_items_refail_in_a_row(tmp_path):
    qp, be = ready(tmp_path, 5, gpus={0: gpu(*H100)})
    set_state(qp, a1={"fixes": 1, "status": "running"}, a2={"fixes": 1, "status": "running"})   # 종료 보고는 도는 판에 대해서만 받는다
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)           # 첫 재실패: 아직 제외 아님
    assert not state(qp)["excluded_gpus"]
    run(be, "next", "--queue", qp, "--item", "a2", "--gpu", 0, "--exit", 2)           # 서로 다른 두 번째 재실패 → 제외
    st = state(qp)
    assert st["excluded_gpus"] == [0] and len(events(qp, "gpu-excluded")) == 1
    n = len(be.launches)
    run(be, "next", "--queue", qp, "--item", "a3", "--gpu", 0, "--exit", 2)           # a3 는 a1 이 닫힌 뒤 이 GPU 에 올라간 판
    assert len(be.launches) == n and n >= 1                                           # 제외된 GPU 에는 더 올리지 않는다(제외 전엔 올렸다)


def test_success_between_refails_resets_gpu_exclusion_streak(tmp_path):
    qp, be = ready(tmp_path, 4, gpus={0: gpu(*H100)})
    set_state(qp, a1={"fixes": 1, "status": "running"}, a2={"fixes": 1, "status": "running"})   # 종료 보고는 도는 판에 대해서만 받는다
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)
    run(be, "next", "--queue", qp, "--item", "a3", "--gpu", 0, "--exit", 0)           # 그 GPU 의 성공이 «연속»을 끊는다
    run(be, "next", "--queue", qp, "--item", "a2", "--gpu", 0, "--exit", 2)
    assert state(qp)["excluded_gpus"] == []


def test_wait_event_emits_each_event_once_and_times_out_rc3(tmp_path, capsys):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    assert run(be, "wait-event", qp, "--timeout", "0.3", "--interval", "0.05") == 3
    assert "시간 만료" in capsys.readouterr().out
    run(be, "start", qp, "--gpus", "0")
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)
    capsys.readouterr()
    assert run(be, "events", qp, "--pending") == 0
    assert "needs-fix" in capsys.readouterr().out                                      # events 는 소비하지 않는다
    assert run(be, "wait-event", qp, "--timeout", "2", "--interval", "0.05") == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert len(lines) == 1 and lines[0]["kind"] == "needs-fix" and lines[0]["item"] == "a1"
    assert list(qp.with_name("q1.events").glob("*.consumed"))
    assert run(be, "wait-event", qp, "--timeout", "0.3", "--interval", "0.05") == 3  # 같은 이벤트를 다시 내지 않는다
    capsys.readouterr()
    assert run(be, "events", qp, "--pending") == 0 and capsys.readouterr().out == ""


def test_wait_event_wakes_when_event_appears_later(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(lq, "MIN_INTERVAL", 0)
    qp, be = ready(tmp_path, 1)
    t = threading.Timer(0.4, lq.write_event, args=(qp, "launch-failed"), kwargs={"item": "a1"})
    t.start()
    t0 = time.time()
    assert run(be, "wait-event", qp, "--timeout", "5", "--interval", "0.05") == 0
    t.join()
    assert time.time() - t0 < 3 and json.loads(capsys.readouterr().out.splitlines()[-1])["kind"] == "launch-failed"


def test_release_records_who_and_why_and_then_next_launches(tmp_path):
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100)})
    be.rc["a1"] = 65
    run(be, "start", qp, "--gpus", "0")
    assert state(qp)["items"]["a1"]["maybe_alive"] and len(be.launches) == 1
    assert len(events(qp, "launch-failed")) == 1
    assert run(be, "release", qp, "--item", "a1", "--reason", "PID 사망 확인", "--by", "tester") == 0
    s = state(qp)["items"]["a1"]
    assert not s["maybe_alive"] and s["released"][0]["by"] == "tester" and s["released"][0]["reason"] == "PID 사망 확인"
    assert len(be.launches) == 1                                                       # --then-next 없이는 발사 안 함
    assert run(be, "release", qp, "--item", "a1", "--reason", "다시") == 2            # 표시가 없으면 받지 않는다
    set_state(qp, a1={"maybe_alive": True})
    assert run(be, "release", qp, "--item", "a1", "--reason", "확인", "--then-next") == 0
    assert state(qp)["items"]["a2"]["status"] == "running" and len(be.launches) == 2


def test_summary_table_and_finished_event_once(tmp_path, capsys):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)           # a1 needs-fix, a2 GPU 0
    run(be, "relaunch", qp, "--item", "a1", "--fix-note", "lr 수정")                    # GPU 점유 → 맨 앞 대기
    capsys.readouterr()
    run(be, "summary", qp)
    assert "아직 끝나지 않았습니다" in capsys.readouterr().out
    run(be, "next", "--queue", qp, "--item", "a2", "--gpu", 0, "--exit", 0)           # a1(재발사) 올라감
    assert not events(qp, "queue-finished")
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)           # 재실패 → 모두 끝남
    assert len(events(qp, "queue-finished")) == 1 and events(qp, "queue-finished")[0]["failed"] == ["a1"]
    assert sum("대기 목록 종료" in n for n in be.notes) == 1
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)           # 같은 보고가 되풀이돼도 이벤트·알림은 1회
    assert len(events(qp, "queue-finished")) == 1 and sum("대기 목록 종료" in n for n in be.notes) == 1
    capsys.readouterr()
    assert run(be, "summary", qp) == 0
    out = capsys.readouterr().out
    assert "| 판 | 목적 | 실패 단계 | 사유 | 고친 내용 | GPU |" in out
    assert "| a1 | a1 목적 | 재발사 후 재실패 | 재발사 후 다시 비정상 종료(exit 2) | lr 수정 | 0 |" in out
    assert "| a2 |" not in out                                                         # 실패한 판만


def test_summary_without_failures_prints_no_table(tmp_path, capsys):
    qp, be = ready(tmp_path, 1, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0)
    capsys.readouterr()
    run(be, "summary", qp)
    out = capsys.readouterr().out
    assert "실패 없음" in out and "| 판 |" not in out


# ───────────── Phase 4: 남은 시간으로 기다림 판정 ─────────────

@pytest.mark.parametrize("tail,elapsed,rx,want", [
    ("Epoch 4/60\nEpoch 5/60 loss=1", 0.5, None, 5.5),            # 마지막 일치, 경과 × (전체−현재) ÷ 현재
    ("no progress here", 0.5, None, None),
    ("Epoch 5/60", None, None, None),
    ("Epoch 60/60", 2.0, None, 0.0),
    ("step 10 of 40", 1.0, r"step (\d+) of (\d+)", 3.0),
    ("Epoch 5/60", 1.0, "([", None),                              # 잘못된 정규식은 None
])
def test_remaining_hours(tail, elapsed, rx, want):
    got = lq.remaining_hours(tail, elapsed, rx)
    assert got == (pytest.approx(want) if want is not None else None)


GPUS2 = {0: gpu(*L40S), 1: gpu(*H100)}
TT = {"L": 1.0, "H": 0.5}   # 기종별 소요(h): L40S 1.0 · H100 0.5


def test_should_wait_pure_cases():
    w, why = lq.should_wait(0, GPUS2, 1, TT, {1: 0.2})                               # 느린 GPU 가 빔 · 빠른 GPU 가 곧 빔(0.2+0.5 < 1.0) · k=1 ≤ m=1
    assert w and "k ≤ m" in why
    w, why = lq.should_wait(0, GPUS2, 1, TT, {1: 0.8})                               # 멀다(0.8+0.5 ≥ 1.0) → m=0 → 바로 올림
    assert not w and "일찍 끝나는 빠른 GPU 가 없어" in why
    w, why = lq.should_wait(0, GPUS2, 1, TT, {1: None})                              # 남은 시간 None → 기다리지 않음
    assert not w and "읽지 못해" in why
    w, why = lq.should_wait(0, GPUS2, 1, {"L": 1.0}, {1: 0.2})                       # 한 기종(H) 자료 없음 → 기다리지 않음
    assert not w and "소요 자료가 없어" in why
    assert not lq.should_wait(0, GPUS2, 1, {"H": 0.5}, {1: 0.2})[0]                  # 빈 기종(L) 자료 없음
    w, why = lq.should_wait(0, GPUS2, 2, TT, {1: 0.2})                               # k=2 > m=1 → 바로 올림
    assert not w and "k > m" in why
    two = {**GPUS2, 2: gpu(*H100)}
    assert lq.should_wait(0, two, 2, TT, {1: 0.2, 2: 0.3})[0]                        # 빠른 GPU 둘이 곧 빔 → k=2 ≤ m=2
    assert not lq.should_wait(1, GPUS2, 1, TT, {0: 0.2})[0]                          # 빈 GPU 가 빠른 쪽이면 기다릴 이유 없음
    assert not lq.should_wait(0, GPUS2, 0, TT, {1: 0.2})[0]                          # 대기 판 0개


def test_collect_estimates_medians_per_kind_and_remaining():
    q = {"items": [{"id": i, "log_dir": "/nonexistent/" + i} for i in ("r", "d1", "d2")]}
    ago = lambda s: time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - s))
    st = {"items": {"r": {"status": "running", "gpu": 1, "started": ago(1800)},
                    "d1": {"status": "done", "gpu": 1, "started": ago(7200), "ended": ago(5400)},
                    "d2": {"status": "done", "gpu": 0, "started": ago(7200), "ended": ago(3600)}}}
    tt, rem = lq.collect_estimates(q, st, GPUS2)
    assert tt == {"H": pytest.approx(0.5), "L": pytest.approx(1.0)} and rem == {1: None}   # 진행 로그가 없는 도는 판은 남은 시간 None


def _iso_ago(sec):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - sec))


def _wait2(tmp_path, hrun_hours=0.45, progress="Epoch 50/60", n_hdone=1, n_queued=1, gpus=None):
    """느린 GPU(L40S 0)가 막 비는 시점. 빠른 GPU(H100 1)는 판 hrun 이 도는 중이고 같은 기종에서 끝난 판이 n_hdone 개(각 0.5h)다."""
    items = [mk_item(tmp_path, "lend"), mk_item(tmp_path, "hrun")] + [mk_item(tmp_path, f"hd{i}") for i in range(n_hdone)] + [mk_item(tmp_path, f"q{i}") for i in range(1, n_queued + 1)]
    qp = mk_queue(tmp_path, items)
    be = lq.FakeBackend(gpus or {0: gpu(*L40S), 1: gpu(*H100, procs=1, used=20.0)})
    run(be, "approve", qp)
    upd = {"lend": {"status": "running", "gpu": 0, "started": _iso_ago(3600)}, "hrun": {"status": "running", "gpu": 1, "started": _iso_ago(hrun_hours * 3600)}}
    upd.update({f"hd{i}": {"status": "done", "gpu": 1, "started": _iso_ago(7200), "ended": _iso_ago(5400)} for i in range(n_hdone)})
    set_state(qp, **upd)
    if progress:
        log = Path(items[1]["log_dir"]) / "run.log"
        log.parent.mkdir(parents=True)
        log.write_text(progress)
    run(be, "next", "--queue", qp, "--item", "lend", "--gpu", 0, "--exit", 0)      # 느린 GPU 가 먼저 빔
    return qp, be


def last_decision(qp):
    return state(qp)["decisions"][-1]


def test_slow_gpu_waits_when_fast_gpu_frees_soon(tmp_path):
    qp, be = _wait2(tmp_path)
    st = state(qp)
    assert st["items"]["q1"]["status"] == "queued" and not be.launches and "0" in st["idle_gpus"]
    d = last_decision(qp)
    assert d["wait"] is True and d["k"] == 1 and "k ≤ m" in d["why"] and d["type_total"]["L"] == pytest.approx(1.0, abs=0.01)
    assert sum("기다립니다" in n and "k ≤ m" in n for n in be.notes) == 1                 # 기다림은 알림에도 적는다
    assert len(be.notes) == 1


@pytest.mark.parametrize("kw,reason", [
    ({"hrun_hours": 4, "n_hdone": 2}, "일찍 끝나는 빠른 GPU 가 없어"),    # 멀면 즉시
    ({"progress": None}, "읽지 못해"),                                  # 남은 시간 None → 즉시
    ({"progress": None, "n_hdone": 0}, "소요 자료가 없어"),                # 자료 없음 → 즉시
    ({"n_queued": 2}, "k > m"),                                          # k > m → 즉시
])
def test_slow_gpu_launches_immediately_when_wait_not_justified(tmp_path, kw, reason):
    qp, _be = _wait2(tmp_path, **kw)
    st = state(qp)
    assert st["items"]["q1"]["status"] == "running" and st["items"]["q1"]["gpu"] == 0 and not st["idle_gpus"]
    d = last_decision(qp)
    assert d["wait"] is False and reason in d["why"]                                   # 기다리지 않은 근거도 남긴다


def test_waiting_gpu_is_reevaluated_when_fast_gpu_times_out(tmp_path):
    """기다리는 동안 빠른 GPU 판이 타임아웃(4)으로 끝나 next 가 그 GPU 에 발사하지 않아도 대기 판이 굶지 않는다."""
    qp, be = _wait2(tmp_path)
    assert not be.launches and "0" in state(qp)["idle_gpus"]
    run(be, "next", "--queue", qp, "--item", "hrun", "--gpu", 1, "--exit", 4)
    st = state(qp)
    assert st["items"]["q1"]["status"] == "running" and st["items"]["q1"]["gpu"] == 0 and not st["idle_gpus"] and last_decision(qp)["wait"] is False


def test_waiting_gpu_is_released_when_fast_gpu_launch_takes_the_item(tmp_path):
    qp, be = _wait2(tmp_path)
    run(be, "next", "--queue", qp, "--item", "hrun", "--gpu", 1, "--exit", 2)         # 빠른 GPU 가 비정상 종료 → 같은 GPU 에 다음 판(q1)이 올라간다
    st = state(qp)
    assert st["items"]["q1"]["gpu"] == 1 and st["items"]["q1"]["status"] == "running" and not st["idle_gpus"]


def test_waiting_gpu_is_reevaluated_on_release_and_relaunch_paths(tmp_path):
    qp, be = _wait2(tmp_path)
    set_state(qp, hrun={"status": "launch-failed", "maybe_alive": True})              # 빠른 GPU 판이 «살아 있을 수 있음»으로 굳음 → 더 기다릴 근거 없음
    assert run(be, "release", qp, "--item", "hrun", "--reason", "PID 사망 확인") == 0
    assert state(qp)["items"]["q1"]["status"] == "running" and not state(qp)["idle_gpus"]


def test_decisions_keep_only_last_50(tmp_path):
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100)})
    s = state(qp)
    s["decisions"] = [{"n": i} for i in range(60)]
    lq.save_state(qp, s)
    run(be, "start", qp, "--gpus", "0")
    d = state(qp)["decisions"]
    assert len(d) == 50 and d[-1].get("gpu") == 0 and d[0] == {"n": 11}


def test_vram_large_item_still_skips_l40s_with_wait_logic_on(tmp_path):
    qp = mk_queue(tmp_path, [mk_item(tmp_path, "big", vram_gb=60), mk_item(tmp_path, "small", vram_gb=20)])
    be = lq.FakeBackend({0: gpu(*L40S), 1: gpu(*H100)})
    run(be, "approve", qp)
    run(be, "start", qp, "--gpus", "0,1")
    it = state(qp)["items"]
    assert (it["small"]["gpu"], it["big"]["gpu"]) == (0, 1)


# ───────────── 진행률 읽기 견고화 ─────────────

@pytest.mark.parametrize("tail,rx", [
    ("-5/10", r"(-?\d+)/(\d+)"), ("0/10", r"(\d+)/(\d+)"), ("70/60", r"(\d+)/(\d+)"), ("1/99999999999999999999999", r"(\d+)/(\d+)"),
    ("1/" + "9" * 5000, r"(\d+)/(\d+)"), ("5/", r"(\d+)/(\d+)?"), ("x", r"(\d+)?/(\d+)?"), ("5/10", "bad("), ("5/10", r"(\d+)"),
])
def test_read_progress_unreadable_values_are_none(tail, rx):
    assert lq.read_progress(tail, rx) is None
    assert lq.remaining_hours(tail, 1.0, rx) is None and lq.estimate_total_hours(tail, 1.0, rx) is None


def test_read_progress_valid_and_estimates():
    assert lq.read_progress("Epoch 5/60") == (5, 60)
    assert lq.estimate_total_hours("Epoch 5/60", 0.5) == pytest.approx(6.0)
    assert lq.remaining_hours("Epoch 5/60", float("inf")) is None and lq.remaining_hours("Epoch 5/60", float("nan")) is None


def test_file_tail_reads_only_the_end(tmp_path):
    f = tmp_path / "big.log"
    f.write_text("Epoch 1/60 FIRST\n" + "x" * (lq.LOG_TAIL_BYTES * 2) + "\nEpoch 30/60 LAST\n")
    t = lq.file_tail(f, 400)
    assert "LAST" in t and "FIRST" not in t and len(t) <= lq.LOG_TAIL_BYTES + 10
    assert lq.file_tail(tmp_path / "none.log") == ""


@pytest.mark.parametrize("rx,ok", [(r"Epoch (\d+)/(\d+)", True), (r"(\d+)", False), (r"(\d+)(\d+)(\d+)", False), ("([", False), (r"(\d+)+/(\d+)", False), (r"((a+)+)/(\d+)", False), ("x" * 300 + r"(\d+)/(\d+)", False)])
def test_progress_regex_is_validated_at_parse_and_approve(tmp_path, rx, ok):
    items = [mk_item(tmp_path, "a1", progress_regex=rx)]
    qp = mk_queue(tmp_path, items)
    assert (run(lq.FakeBackend(six_gpus()), "approve", qp) == 0) is ok


# ───────────── Phase 5: 판 < GPU 배치 제안 ─────────────

TABLE = json.loads((TW_DIR / "placement_table.json").read_text())
SIX = {g: gpu(*(H100 if g < 2 else L40S)) for g in range(6)}
BOTH, DDP = {"DDP_READY": "1", "PROP_BATCH_READY": "1"}, {"DDP_READY": "1"}


def plan(n, env, gpus=SIX):
    return lq.propose_placement([f"j{i}" for i in range(1, n + 1)], gpus, env, TABLE)


def test_placement_without_declaration_is_one_gpu_per_job_with_reason():
    p = plan(3, {})
    assert p["mode"] == "one-per-gpu" and [g["gpus"] for g in p["groups"]] == [[0], [1], [2]] and "DDP_READY" in p["reason"] and "PROP_BATCH_READY" in p["reason"]
    p = plan(3, DDP)   # 판 3개 행은 비례 짝이 필요하다 — DDP 만 선언해서는 묶지 않는다
    assert p["mode"] == "one-per-gpu" and "PROP_BATCH_READY" in p["reason"] and "DDP_READY" not in p["reason"]


def test_placement_bundles_when_declared():
    p = plan(3, BOTH)
    assert p["mode"] == "bundle" and [g["gpus"] for g in p["groups"]] == [[0, 2], [1, 3], [4, 5]] and [g["jobs"] for g in p["groups"]] == [["j1"], ["j2"], ["j3"]]
    assert [g["gpus"] for g in plan(4, DDP)["groups"]] == [[0], [1], [2, 3], [4, 5]]
    assert [g["jobs"] for g in plan(5, BOTH)["groups"]] == [["j1", "j2"], ["j3", "j4"], ["j5"]]
    assert [g["gpus"] for g in plan(2, DDP)["groups"]] == [[0, 1], [2, 3, 4, 5]]
    assert plan(1, DDP)["mode"] == "one-per-gpu"                                      # 판 1개(6장 비례 DDP)는 비례 짝 선언까지 필요
    assert plan(1, BOTH)["groups"][0]["gpus"] == [0, 1, 2, 3, 4, 5]


def test_placement_queue_mode_and_unknown_config():
    p = plan(8, BOTH)
    assert p["mode"] == "queue" and p["waiting"] == ["j7", "j8"] and "판 > GPU" in p["label"] and len(p["groups"]) == 6
    assert plan(6, BOTH)["mode"] == "queue" and "판 = GPU" in plan(6, BOTH)["label"]
    four = {g: SIX[g] for g in (0, 2, 3, 4)}
    p = plan(2, BOTH, four)
    assert p["mode"] == "one-per-gpu" and "GPU 구성이 표" in p["reason"]


def test_place_command_only_proposes_and_table_gets_placement_column(tmp_path, capsys):
    qp, be = ready(tmp_path, 3)
    assert run(be, "place", qp, "--gpus", "0,1,2,3,4,5") == 0
    out = capsys.readouterr().out
    assert "빈 GPU 마다 한 판" in out and "판당 1장으로 내린 이유" in out and "발사하지 않습니다" in out
    (qp.parents[1] / "train.env").write_text("TRAIN_TMUX_PREFIX=tq\nDDP_READY=1\nPROP_BATCH_READY=1  # 비례 짝 구현됨\n")
    assert run(be, "table", qp, "--gpus", "0,1,2,3,4,5") == 0
    out = capsys.readouterr().out
    assert "| 배치 |" in out and "| GPU 0,2 (묶음 1, 1번째) |" in out and "| GPU 4,5 (묶음 3, 1번째) |" in out
    assert not be.launches                                                            # 제안만 — 발사 0건


def test_read_env_parses_exports_quotes_and_comments(tmp_path):
    qp = mk_queue(tmp_path, [mk_item(tmp_path, "a1")])
    (qp.parents[1] / "train.env").write_text("export TRAIN_TMUX_PREFIX='tq'  # 접두\nDDP_READY=\"1\"\n# X=1\n")
    assert lq.read_env(qp) == {"TRAIN_TMUX_PREFIX": "tq", "DDP_READY": "1"} and lq.read_prefix(qp) == "tq"


def test_ddp_ready_zero_is_not_a_declaration():
    assert plan(2, {"DDP_READY": "0"})["mode"] == "one-per-gpu" and "DDP_READY" in plan(2, {"DDP_READY": "0"})["reason"]
    assert plan(3, {"DDP_READY": "0", "PROP_BATCH_READY": "0"})["mode"] == "one-per-gpu"
    assert plan(2, {"DDP_READY": "true"})["mode"] == "one-per-gpu"                    # «1» 만 선언으로 인정한다
    assert plan(2, {"DDP_READY": "1"})["mode"] == "bundle"


def test_placement_table_values_match_benchmark_note():
    want = {"1": (0.2, 0.6), "2": (0.3, 0.6), "3": (0.5, 0.9), "4": (0.6, 0.9), "5": (0.7, 0.9)}   # placement_table.json 예시 표
    assert set(TABLE["rows"]) == set(want) and TABLE["config"] == {"H100": 2, "L40S": 4}
    for n, (fin, par) in want.items():
        assert (TABLE["rows"][n]["finish_h"], TABLE["rows"][n]["parallel_h"]) == (fin, par)
        assert sum(g["jobs"] for g in TABLE["rows"][n]["groups"]) == int(n)         # 묶음의 판 수 합 = 판 수


# ───────────── 검수 대응: 승인 경계 ─────────────

@pytest.mark.parametrize("field,val", [("purpose", "a\nb"), ("change", "x\x1b[31mred"), ("baseline", "t\tb"), ("eval_cmd", "true\nrm -rf x"), ("log_dir", "/tmp/a\nb"), ("id", "a\u0085b")])
def test_control_characters_in_any_string_field_are_rejected(tmp_path, field, val):
    q = good(tmp_path)
    q["items"][0][field] = val
    with pytest.raises(lq.QueueError):
        lq.parse_queue(json.dumps(q).encode(), "q1")
    q = good(tmp_path)
    q["items"][0]["argv"] = ["bash", "run.sh\n", "{GPU}"]
    with pytest.raises(lq.QueueError):
        lq.parse_queue(json.dumps(q).encode(), "q1")


def test_table_escapes_cells_masks_secrets_and_lists_exec_summary(tmp_path, capsys):
    items = [mk_item(tmp_path, "a1", purpose="a|b", argv=["bash", "run.sh", "--api-key", "SECRETVALUE", "{GPU}"], eval_cmd="evalrun token=XYZ789")]
    qp = mk_queue(tmp_path, items)
    be = lq.FakeBackend(six_gpus())
    assert run(be, "table", qp) == 0
    out = capsys.readouterr().out
    assert "| a/b |" in out and "a|b" not in out and "SECRETVALUE" not in out and "--api-key ***" in out
    assert "실행 요약" in out and "- a1: 명령 `bash run.sh --api-key *** {GPU}` · log_dir " in out and "XYZ789" not in out
    # 실행에 쓰이는 필드는 기본 출력에 전부 보인다(시크릿은 가림) — 예전에는 eval_cmd 를 «있음»으로만 보이고 나머지는 --full 이 있어야 보였다
    assert "eval_cmd: evalrun token=***" in out and "done_regex: DONE" in out and "expect: run\\.sh" in out
    assert run(be, "table", qp, "--full") == 0   # --full 은 옛 호출 호환용으로 받기만 한다
    full = capsys.readouterr().out
    assert "XYZ789" not in full and "eval_cmd: evalrun token=***" in full and "done_regex: DONE" in full and "expect: run\\.sh" in full
    assert run(be, "approve", qp) == 2 and not lq.state_path(qp).exists()             # 시크릿 형태는 승인 거부


def test_approve_rejects_secret_shape_in_eval_cmd_and_argv_joined(tmp_path):
    for kw in ({"eval_cmd": "curl -H 'Authorization: Bearer abc'"}, {"argv": ["bash", "run.sh", "--password", "pw", "{GPU}"]}):
        qp = mk_queue(tmp_path / str(len(kw)), [mk_item(tmp_path, "a1", **kw)])
        assert run(lq.FakeBackend(six_gpus()), "approve", qp) == 2


def _git(proj, *args):
    subprocess.run(["git", "-C", str(proj), "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def test_code_change_after_approval_is_recorded_and_notified_but_not_blocking(tmp_path):
    qp = mk_queue(tmp_path, [mk_item(tmp_path, f"a{i}") for i in range(1, 4)])
    proj = qp.parents[2]
    (proj / "run.sh").write_text("echo 1\n")
    _git(proj, "init", "-q")
    _git(proj, "add", "run.sh")
    _git(proj, "commit", "-q", "-m", "init")
    be = lq.FakeBackend({0: gpu(*H100)})
    run(be, "approve", qp)
    ap = state(qp)["approved"]["code"]
    assert len(ap["head"]) == 40 and ap["changed"] == 1                                # 승인 시점의 HEAD · 변경 파일 수(train.env 한 개, launch-queue 폴더는 제외)
    run(be, "start", qp, "--gpus", "0")
    assert not any("승인 이후 코드가" in n for n in be.notes) and "code_changed" not in state(qp)   # state·이벤트 파일이 해시를 흔들지 않는다
    (proj / "run.sh").write_text("echo 2\n")
    _git(proj, "commit", "-q", "-am", "fix")
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0)
    assert state(qp)["items"]["a2"]["status"] == "running"                             # 막지 않는다
    assert sum("승인 이후 코드가 바뀜(HEAD " in n for n in be.notes) == 1 and "HEAD" in state(qp)["code_changed"]["msg"]
    run(be, "next", "--queue", qp, "--item", "a2", "--gpu", 0, "--exit", 0)
    assert state(qp)["items"]["a3"]["status"] == "running" and sum("승인 이후 코드가" in n for n in be.notes) == 1   # 같은 변경은 다시 알리지 않는다


def test_code_snapshot_is_none_outside_git_repo(tmp_path):
    assert lq.code_snapshot(tmp_path) is None and lq.code_changed(None, None) is None


def test_oversight_signatures_for_approve_relaunch_release_halt(tmp_path):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    gates = lambda: [s[0] for s in be.signs]
    assert gates() == ["approve"] and be.signs[0][1].startswith("q1 ") and len(be.signs[0][1].split()[1]) == 12 and "test" in be.signs[0][2]
    be.rc["a1"] = 65
    run(be, "start", qp, "--gpus", "0")
    run(be, "release", qp, "--item", "a1", "--reason", "PID 사망 확인")
    set_state(qp, a2={"status": "needs-fix"})
    run(be, "relaunch", qp, "--item", "a2", "--fix-note", "수정", "--gpus", "0")
    run(be, "halt", qp, "--reason", "점검")
    assert gates() == ["approve", "approve", "launch", "other"] and "PID 사망 확인" in be.signs[1][2] and "수정" in be.signs[2][2]


def test_tmux_backend_sign_uses_env_script_and_only_warns_on_failure(tmp_path, monkeypatch, capsys):
    out, script = tmp_path / "sig.txt", tmp_path / "sig.sh"
    script.write_text(f'#!/usr/bin/env bash\nprintf "%s|" "$@" > {out}\n')
    monkeypatch.setenv("LAUNCH_QUEUE_OVERSIGHT", str(script))
    lq.TmuxBackend().sign("approve", "t", "b", "actor", str(tmp_path))
    assert out.read_text() == "approve|t|b|actor|"
    script.write_text("#!/usr/bin/env bash\nexit 3\n")
    lq.TmuxBackend().sign("launch", "t", "b", "actor", str(tmp_path))                   # 실패해도 예외 없이 경고만
    assert "감시 서명(launch) 기록 실패" in capsys.readouterr().err
    monkeypatch.setenv("LAUNCH_QUEUE_OVERSIGHT", str(tmp_path / "missing.sh"))
    lq.TmuxBackend().sign("launch", "t", "b", "actor", str(tmp_path / "no-such-cwd"))
    assert "기록 실패" in capsys.readouterr().err


def test_halt_stops_all_launching_until_approve(tmp_path):
    qp, be = ready(tmp_path, 4, gpus={0: gpu(*H100), 1: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    assert run(be, "halt", qp, "--reason", "점검 중") == 0
    assert run(be, "halt", qp, "--reason", "또") == 0                                  # 이미 멈춤: 이벤트·알림은 처음 한 번
    assert len(events(qp, "halted")) == 1 and sum("사용자 정지" in n for n in be.notes) == 1 and state(qp)["halted"]["detail"] == "점검 중"
    n = len(be.launches)
    run(be, "start", qp, "--gpus", "1")
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0)
    set_state(qp, a2={"status": "needs-fix"})
    assert run(be, "relaunch", qp, "--item", "a2", "--fix-note", "x") == 2
    assert len(be.launches) == n                                                       # start·next·relaunch 발사 0건
    run(be, "approve", qp)                                                              # 해제는 approve 뿐
    run(be, "start", qp, "--gpus", "0")                                                 # approve 는 발사하지 않는다 — 이어 올리는 길은 start(되풀이된 종료 보고는 무시)
    assert len(be.launches) == n + 1


# ───────────── 검수 대응: 낮음·비차단 묶음 ─────────────

def test_state_events_launch_dir_and_script_permissions_and_umask_restored(tmp_path):
    before = os.umask(0)
    os.umask(before)
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)             # needs-fix 이벤트
    mode = lambda p: os.stat(p).st_mode & 0o777
    assert mode(lq.state_path(qp)) == 0o600 and mode(qp.with_name("q1.lock")) == 0o600
    assert mode(qp.with_name("q1.events")) == 0o700 and mode(qp.with_name("q1.launch")) == 0o700 and mode(be.launches[0][2]) == 0o600
    assert all(mode(p) == 0o600 for p in qp.with_name("q1.events").glob("*.json"))
    after = os.umask(0)
    os.umask(after)
    assert before == after                                                              # main 이 끝나면 umask 를 되돌린다


def test_launch_script_comment_has_no_user_strings(tmp_path):
    qp = mk_queue(tmp_path, [mk_item(tmp_path, "zzitem")])
    be = lq.FakeBackend({0: gpu(*H100)})
    run(be, "approve", qp)
    run(be, "start", qp, "--gpus", "0")
    lines = be.launches[0][2].read_text().splitlines()
    assert lines[1].startswith("# ") and "zzitem" not in lines[1] and "q1" not in lines[1]


def test_rc_64_67_do_not_mark_alive_and_next_candidate_still_launches(tmp_path):
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100)})
    be.rc["a1"] = 67
    run(be, "start", qp, "--gpus", "0")
    it = state(qp)["items"]
    assert [i for i, _, _ in be.launches] == ["a1", "a2"] and it["a1"]["status"] == "launch-failed" and not it["a1"]["maybe_alive"] and "not-started" in it["a1"]["fail_reason"]
    assert it["a2"]["status"] == "running" and len(events(qp, "launch-failed")) == 1


@pytest.mark.parametrize("cmd", ["start", "next"])
def test_exceptions_become_event_notice_and_rc1(tmp_path, cmd, capsys):
    class Boom(lq.FakeBackend):
        def gpus(self):
            raise RuntimeError("nvidia-smi 없음")
    qp, ok_be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    be = Boom({0: gpu(*H100)})
    if cmd == "next":
        assert run(ok_be, "start", qp, "--gpus", "0") == 0   # a1 이 도는 중이어야 종료 보고(next)가 반영된다
    args = ("start", qp, "--gpus", "0") if cmd == "start" else ("next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0)
    assert run(be, *args) == 1
    ev = events(qp, "launch-blocked")
    assert len(ev) == 1 and "RuntimeError" in ev[0]["reason"] and len(be.notes) == 1 and "Traceback" not in capsys.readouterr().err
    assert run(be, "status", qp) == 0                                                    # 락이 풀려 있다(교착 없음)


def test_on_exit_uses_absolute_system_python():
    text = (SCRIPT_DIR / "launch-set.sh").read_text()
    assert "printf '/usr/bin/python3 %q next --queue" in text and "printf 'python3 " not in text and os.path.exists("/usr/bin/python3")


def test_wait_event_skips_and_quarantines_broken_files_and_enforces_min_interval(tmp_path, capsys, monkeypatch):
    assert lq.MIN_INTERVAL >= 5
    monkeypatch.setattr(lq, "MIN_INTERVAL", 0)
    qp, be = ready(tmp_path, 1)
    d = qp.with_name("q1.events")
    d.mkdir()
    (d / "20200101T000000-x-1-1.json").write_text("{broken")
    lq.write_event(qp, "needs-fix", item="a1")
    capsys.readouterr()
    assert run(be, "wait-event", qp, "--timeout", "2", "--interval", "0.05") == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["kind"] == "needs-fix"
    assert (d / "20200101T000000-x-1-1.json.bad").exists() and not (d / "20200101T000000-x-1-1.json.consumed").exists()
    assert run(be, "events", qp) == 0                                                    # 비 pending: *.json 과 *.consumed 만
    out = capsys.readouterr().out
    assert len(out.splitlines()) == 1 and json.loads(out)["kind"] == "needs-fix" and json.loads(out)["file"].endswith(".consumed") and ".bad" not in out


def test_exit_3_ends_the_refail_streak_and_include_gpu_restores_chain(tmp_path):
    qp, be = ready(tmp_path, 5, gpus={0: gpu(*H100)})
    set_state(qp, a1={"fixes": 1, "status": "running"}, a2={"fixes": 1, "status": "running"})   # 종료 보고는 도는 판에 대해서만 받는다
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)
    run(be, "next", "--queue", qp, "--item", "a3", "--gpu", 0, "--exit", 3)             # 학습은 정상 종료(평가만 실패) → «연속» 끊김
    run(be, "next", "--queue", qp, "--item", "a2", "--gpu", 0, "--exit", 2)
    assert state(qp)["excluded_gpus"] == []


def test_all_gpus_excluded_event_once_and_include_gpu_with_signature(tmp_path):
    qp, be = ready(tmp_path, 5, gpus={0: gpu(*H100)})
    set_state(qp, a1={"fixes": 1, "status": "running"}, a2={"fixes": 1, "status": "running"})   # 종료 보고는 도는 판에 대해서만 받는다
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)
    run(be, "next", "--queue", qp, "--item", "a2", "--gpu", 0, "--exit", 2)
    assert state(qp)["excluded_gpus"] == [0] and len(events(qp, "all-gpus-excluded")) == 1
    assert sum("모든 GPU" in n for n in be.notes) == 1
    set_state(qp, a3={"status": "done"})   # a1 이 닫힐 때 이 GPU 에 올라간 a3 는 끝난 것으로(도는 판이 쥔 GPU 에는 then-next 가 올리지 않는다)
    assert run(be, "include-gpu", qp, "--gpu", "0", "--reason", "카드 점검 완료", "--by", "tester", "--then-next") == 0
    st = state(qp)
    assert st["excluded_gpus"] == [] and "0" not in st.get("gpu_refail", {}) and any(s[0] == "approve" and "gpu0 제외 해제" in s[1] and "카드 점검 완료" in s[2] for s in be.signs)
    assert [s["status"] for p, s in st["items"].items() if p == "a4"] == ["running"]   # --then-next 로 바로 이어 올라간다
    assert run(be, "include-gpu", qp, "--gpu", "0", "--reason", "또") == 2             # 제외 상태가 아니면 받지 않는다


def test_finished_event_after_approve_rerun_reports_maybe_alive_training(tmp_path, capsys):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    be.rc["a1"] = 65
    run(be, "start", qp, "--gpus", "0")
    set_state(qp, a2={"status": "done"})
    assert not events(qp, "queue-finished")
    run(be, "approve", qp)                                                                # approve 재실행 뒤에도 종료 판정
    ev = events(qp, "queue-finished")
    assert len(ev) == 1 and ev[0]["maybe_alive"] == ["a1"] and any("살아 있을 수 있는 학습 1개" in n for n in be.notes)
    capsys.readouterr()
    run(be, "summary", qp)
    assert "살아 있을 수 있는 학습 1개" in capsys.readouterr().out


def test_finished_event_after_release(tmp_path):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    be.rc["a1"] = 65
    run(be, "start", qp, "--gpus", "0")
    set_state(qp, a2={"status": "done"})
    run(be, "release", qp, "--item", "a1", "--reason", "PID 사망 확인")
    ev = events(qp, "queue-finished")
    assert len(ev) == 1 and ev[0]["maybe_alive"] == [] and ev[0]["failed"] == ["a1"]


def test_status_and_events_warn_when_watcher_process_is_gone(tmp_path, capsys):
    qp, be = ready(tmp_path, 1, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    ls = tmp_path / "launch-state.json"
    ls.write_text(json.dumps({"watcher_pid": 99999999, "watcher_start": "1"}))
    set_state(qp, a1={"launch_state": str(ls)})
    capsys.readouterr()
    run(be, "status", qp)
    assert "경고: 판 a1(GPU 0) 와쳐 없음(자동 발사 사슬 끊김)" in capsys.readouterr().out
    run(be, "events", qp, "--pending")
    assert "와쳐 없음(자동 발사 사슬 끊김)" in capsys.readouterr().out
    start = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]
    ls.write_text(json.dumps({"watcher_pid": os.getpid(), "watcher_start": start}))     # 살아 있는 PID(시작 시각까지 일치)
    assert lq.watcher_alive(str(ls)) is True and lq.missing_watchers(state(qp)) == []
    ls.write_text(json.dumps({"watcher_pid": os.getpid(), "watcher_start": "1"}))       # PID 재사용(시작 시각 불일치)
    assert lq.watcher_alive(str(ls)) is False and lq.watcher_alive(str(tmp_path / "none.json")) is None


# ───────────── 후속: umask 누수 방지 · halt 뒤 approve ─────────────

def test_log_dir_and_child_processes_keep_the_original_umask(tmp_path):
    seen = []

    class Spy(lq.FakeBackend):
        def sign(self, *a):
            seen.append(lq.run_proc(["bash", "-c", "umask"], capture_output=True, text=True).stdout.strip())   # 자식 프로세스가 보는 umask
            super().sign(*a)
    old = os.umask(0o022)
    try:
        qp = mk_queue(tmp_path, [mk_item(tmp_path, "a1")])
        be = Spy({0: gpu(*H100)})
        assert run(be, "approve", qp) == 0 and run(be, "start", qp, "--gpus", "0") == 0
    finally:
        os.umask(old)
    ld = Path(mk_item(tmp_path, "a1")["log_dir"])
    mode = lambda p: os.stat(p).st_mode & 0o777
    assert seen == ["0022"] and mode(ld) == 0o755 and mode(ld.parent) == 0o755          # 학습 로그 폴더는 도구가 권한을 바꾸지 않는다
    assert mode(lq.state_path(qp)) == 0o600 and mode(qp.with_name("q1.launch")) == 0o700   # 도구 자신의 파일은 그대로 0600/0700
    assert lq._ORIG_UMASK is None                                                       # main 이 끝나면 되돌린다


def test_approve_after_halt_does_not_launch_clears_idle_and_hints_start(tmp_path, capsys):
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100), 1: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    s = state(qp)
    s["idle_gpus"] = {"1": {"since": "x", "why": "낡은 기록"}}
    lq.save_state(qp, s)
    run(be, "halt", qp, "--reason", "점검")
    n = len(be.launches)
    capsys.readouterr()
    assert run(be, "approve", qp) == 0
    out = capsys.readouterr().out
    assert len(be.launches) == n and state(qp)["idle_gpus"] == {} and not state(qp)["halted"]      # approve 는 발사하지 않는다
    assert "발사를 이어가려면 start --gpus" in out
    assert run(be, "start", qp, "--gpus", "0,1") == 0
    assert len(be.launches) == n + 1 and state(qp)["items"]["a2"]["gpu"] == 1                      # 이미 running 인 GPU 0 은 건너뛰고 빈 GPU 1 에만
    capsys.readouterr()
    run(be, "approve", qp)
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 0)
    run(be, "next", "--queue", qp, "--item", "a2", "--gpu", 1, "--exit", 0)
    run(be, "next", "--queue", qp, "--item", "a3", "--gpu", 1, "--exit", 0)
    capsys.readouterr()
    run(be, "approve", qp)
    assert "발사를 이어가려면" not in capsys.readouterr().out                            # queued 가 없으면 안내하지 않는다


# ───────────── E2E 결함: launch-set rc 0 뒤의 추가 verify 는 결과를 바꾸지 않는다 ─────────────

def test_rc0_with_failing_extra_verify_stays_running_without_failure_event_and_signs(tmp_path):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    be.verify_rc = 1                                                                    # launch-set 은 통과했지만 그 뒤 학습이 빨리 죽은 상황
    run(be, "start", qp, "--gpus", "0")
    a1 = state(qp)["items"]["a1"]
    assert a1["status"] == "running" and not a1["maybe_alive"] and a1["verify"].startswith("rc=1 ")   # 참고 필드에만 적는다
    assert not events(qp, "launch-failed") and not be.notes
    assert len(be.signatures) == 1 and be.signatures[0][0].endswith(" a1")             # 발사 감시 서명은 rc 0 이면 항상 남는다
    run(be, "next", "--queue", qp, "--item", "a1", "--gpu", 0, "--exit", 2)             # 빨리 죽은 판은 와쳐 exit 2 의 정상 경로로
    assert state(qp)["items"]["a1"]["status"] == "needs-fix" and len(events(qp, "needs-fix")) == 1


def test_rc1_launch_set_own_verify_failure_is_still_verify_failed(tmp_path):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    be.rc["a1"] = 1
    run(be, "start", qp, "--gpus", "0")
    a1 = state(qp)["items"]["a1"]
    assert a1["status"] == "launch-failed" and a1["maybe_alive"] and "verify-failed" in a1["fail_reason"]
    assert len(events(qp, "launch-failed")) == 1 and len(be.notes) == 1 and not be.signatures


# ───────────── 2026-10-01 감사 P6 묶음 B: 발사 도구 결함 수정의 짝 시험 ─────────────

def next_args(qp, item, gpu_no, code, attempt=None):
    return ["next", "--queue", qp, "--item", item, "--gpu", gpu_no, "--exit", code, *([] if attempt is None else ["--attempt", attempt])]


def test_stale_attempt_report_does_not_close_the_relaunched_item(tmp_path, capsys):
    """#1: 이전 시도의 종료 콜백이 재발사된 현재 판을 done 으로 닫고 GPU 점유를 지우던 결함."""
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    set_state(qp, a1={"attempt": 2})                                    # 재발사로 2번째 시도가 도는 중
    n = len(be.launches)
    assert run(be, *next_args(qp, "a1", 0, 0, attempt=1)) == 0          # 1번째 시도 와쳐의 늦은 보고
    it = state(qp)["items"]["a1"]
    assert it["status"] == "running" and it["exit"] is None and len(be.launches) == n
    assert "무시" in capsys.readouterr().out
    assert run(be, *next_args(qp, "a1", 0, 0, attempt=2)) == 0          # 현재 시도의 보고는 받는다
    assert state(qp)["items"]["a1"]["status"] == "done"
    assert len(be.launches) == n + 1                                    # 그 GPU 에 다음 판이 올라간다


def test_report_for_already_processed_item_is_ignored_even_without_attempt(tmp_path):
    """#1: --attempt 가 없는 옛 와쳐의 보고도 running·launching 일 때만 반영한다(되풀이 보고가 상태를 되돌리지 않는다)."""
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    run(be, *next_args(qp, "a1", 0, 0))
    n = len(be.launches)
    run(be, *next_args(qp, "a1", 0, 2))                                 # 이미 done — needs-fix 로 바뀌면 안 된다
    assert state(qp)["items"]["a1"]["status"] == "done" and len(be.launches) == n


@pytest.mark.parametrize("code,status_word", [(6, "평가 시간 초과"), (7, "신호")])
def test_hold_exit_codes_6_7_keep_gpu_and_launch_nothing(tmp_path, code, status_word):
    """D7: 평가 시간 초과(6)·와쳐 신호 중단(7)은 학습·평가가 살아 있을 수 있어 exit 4 처럼 GPU 를 보류한다."""
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    assert run(be, *next_args(qp, "a1", 0, code)) == 0
    it = state(qp)["items"]["a1"]
    assert it["status"] == "timeout" and it["maybe_alive"] and status_word in it["fail_reason"] and len(be.launches) == 1
    assert any(status_word.split()[0] in n or str(code) in n for n in be.notes)
    run(be, "start", qp, "--gpus", "0")
    assert len(be.launches) == 1                                        # 점유가 풀리기 전엔 올리지 않는다
    assert run(be, "release", qp, "--item", "a1", "--reason", "PID 사망 확인", "--then-next") == 0
    assert len(be.launches) == 2


def test_halt_during_launch_gap_cancels_reserved_item(tmp_path, monkeypatch):
    """#2: 예약(락 안)과 발사(락 밖) 사이에 halt 가 들어와도 «이후 발사 0건»(background-task.md)이어야 한다."""
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    real = lq.write_launch_script

    def script_then_halt(*a, **kw):
        out = real(*a, **kw)
        assert run(be, "halt", qp, "--reason", "발사 직전 정지") == 0   # 락이 풀려 있는 구간
        return out
    monkeypatch.setattr(lq, "write_launch_script", script_then_halt)
    assert run(be, "start", qp, "--gpus", "0") == 0
    st = state(qp)
    assert not be.launches and st["items"]["a1"]["status"] == "queued" and st["items"]["a1"]["attempt"] == 0 and st["items"]["a1"]["gpu"] is None
    assert st["halted"]["reason"] == "manual-halt"


def test_queue_edit_during_launch_gap_cancels_reserved_item(tmp_path, monkeypatch):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    real = lq.write_launch_script

    def script_then_edit(*a, **kw):
        out = real(*a, **kw)
        qp.write_text(qp.read_text().replace("a2 목적", "a2 목적!"))
        return out
    monkeypatch.setattr(lq, "write_launch_script", script_then_edit)
    run(be, "start", qp, "--gpus", "0")
    st = state(qp)
    assert not be.launches and st["items"]["a1"]["status"] == "queued" and st["halted"]["reason"] == "queue-changed"
    assert list(qp.with_name("q1.events").glob("*queue-changed*"))


def test_late_launch_result_does_not_overwrite_exit_report(tmp_path):
    """#3: 발사 중에 와쳐가 이미 끝났다고 알려 왔으면(빨리 죽은 판) 발사 결과 기록이 running 으로 덮어쓰면 안 된다."""
    class ReportsDuringLaunch(lq.FakeBackend):
        def launch(self, target, script, rc_file, timeout):
            run(self, *next_args(qp, "a1", 0, 0, attempt=1))   # 락이 풀려 있는 발사 구간에 종료 보고가 먼저 도착
            return super().launch(target, script, rc_file, timeout)
    qp = mk_queue(tmp_path, [mk_item(tmp_path, "a1")])
    be = ReportsDuringLaunch({0: gpu(*H100)})
    run(be, "approve", qp)
    run(be, "start", qp, "--gpus", "0")
    it = state(qp)["items"]["a1"]
    assert it["status"] == "done" and it["exit"] == 0 and it["launch_state"]   # 종료 기록은 지켜지고 발사 증거만 보태진다


def test_start_emits_queue_finished_when_every_first_launch_fails(tmp_path):
    """#4: 최초 발사가 전부 실패하면 이후 next 가 없어 queue-finished 가 안 나오던 결함."""
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    be.rc.update(a1=64, a2=64)
    run(be, "start", qp, "--gpus", "0")
    assert set(statuses(qp).values()) == {"launch-failed"}
    fin = events(qp, "queue-finished")
    assert len(fin) == 1 and fin[0]["failed"] == ["a1", "a2"] and any("대기 목록 종료" in n for n in be.notes)


def test_refusal_cap_closes_item_with_event_and_notice(tmp_path):
    """#5: 거부가 MAX_REFUSALS 에 닿아 launch-failed 로 닫힐 때 이벤트·알림이 없던 결함(launch-set 거부 경로)."""
    qp, be = ready(tmp_path, 1, gpus={0: gpu(*H100)})
    be.rc["a1"] = 76
    for _ in range(lq.MAX_REFUSALS):
        run(be, "start", qp, "--gpus", "0")
    assert state(qp)["items"]["a1"]["status"] == "launch-failed"
    ev = events(qp, "launch-failed")
    assert len(ev) == 1 and ev[0]["outcome"] == "refusal-cap" and sum("거부가" in n and "반복" in n for n in be.notes) == 1


def test_refusal_cap_via_watcher_exit_5_also_notifies(tmp_path):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    set_state(qp, a1={"status": "running", "attempt": 1, "refused": lq.MAX_REFUSALS - 1})
    run(be, *next_args(qp, "a1", 0, 5))
    assert state(qp)["items"]["a1"]["status"] == "launch-failed"
    assert [e["outcome"] for e in events(qp, "launch-failed")] == ["refusal-cap"] and any("memguard" in n and "반복" in n for n in be.notes)


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "1e999"])
@pytest.mark.parametrize("key", ["vram_gb", "cpu_cores"])
def test_non_finite_resource_amounts_are_rejected(tmp_path, key, raw):
    """#6: JSON NaN·Infinity 는 `<= 0` 검사를 통과하던 결함."""
    text = json.dumps({"name": "q1", "items": [mk_item(tmp_path, "a1", **{key: 7})]}).replace(f'"{key}": 7', f'"{key}": {raw}')
    with pytest.raises(lq.QueueError, match="유한한 양수"):
        lq.parse_queue(text.encode(), "q1")


def test_reapproval_with_reordered_list_reranks_queued_items_and_marks_removed(tmp_path):
    """#7: 순서만 바꿔 재승인해도 옛 rank 가 남던 결함 + 목록에서 뺀 queued 판은 removed(종결)로."""
    qp, be = ready(tmp_path, 3, gpus={0: gpu(*H100)})
    items = [mk_item(tmp_path, i) for i in ("a3", "a1")]               # a2 제거, a3 가 앞
    qp.write_text(json.dumps({"name": "q1", "items": items}, ensure_ascii=False, indent=2))
    assert run(be, "approve", qp) == 0
    st = state(qp)["items"]
    assert st["a3"]["rank"] < st["a1"]["rank"] and st["a2"]["status"] == "removed"
    run(be, "start", qp, "--gpus", "0")
    assert [i for i, _, _ in be.launches] == ["a3"]                     # 새 순서대로 올라간다
    run(be, *next_args(qp, "a3", 0, 0))
    run(be, *next_args(qp, "a1", 0, 0))
    fin = events(qp, "queue-finished")
    assert len(fin) == 1 and fin[0]["done"] == 2 and fin[0]["failed"] == []   # removed 는 종료 판정·완료 수에서 빠진다


def test_removed_item_does_not_count_as_waiting_and_can_be_readded(tmp_path):
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    qp.write_text(json.dumps({"name": "q1", "items": [mk_item(tmp_path, "a1")]}))
    run(be, "approve", qp)
    assert statuses(qp)["a2"] == "removed"
    qp.write_text(json.dumps({"name": "q1", "items": [mk_item(tmp_path, "a1"), mk_item(tmp_path, "a2")]}))
    run(be, "approve", qp)
    assert statuses(qp) == {"a1": "queued", "a2": "queued"}


def test_table_shows_every_executed_field_by_default_with_secrets_masked(tmp_path, capsys):
    """#8: 승인 표 기본 출력이 watcher_args·memguard_args·done_regex·expect·log 를 숨기던 결함."""
    it = mk_item(tmp_path, "a1", watcher_args="--timeout-h 5 --eval-timeout-h 3", memguard_args="--high 20G --max 24G", done_log="/x/train_run_*/train.log",
                 log="/x/a1.log", progress_regex="Epoch (\\d+)/(\\d+)", intent="intent/x.md")
    qp = mk_queue(tmp_path, [it])
    assert run(lq.FakeBackend(six_gpus()), "table", qp) == 0
    out = capsys.readouterr().out
    for want in ("watcher_args: --timeout-h 5 --eval-timeout-h 3", "memguard_args: --high 20G --max 24G", "done_regex: DONE", "expect: run\\.sh",
                 "log: /x/a1.log", "done_log: /x/train_run_*/train.log", "eval_cmd: true"):
        assert want in out, want


def test_two_items_sharing_a_log_path_are_rejected(tmp_path):
    """#9: log 를 안 주면 둘 다 <log_dir>/run.log 라 같은 log_dir 의 판들이 로그를 공유하던 결함."""
    shared = str(tmp_path / "logs" / "shared")
    items = [mk_item(tmp_path, "a1", log_dir=shared), mk_item(tmp_path, "a2", log_dir=shared)]
    with pytest.raises(lq.QueueError, match="로그 경로가 같습니다"):
        lq.parse_queue(json.dumps({"name": "q1", "items": items}).encode(), "q1")
    items[1]["log"] = f"{shared}/a2.log"                                # 같은 폴더라도 로그 파일이 다르면 허용
    lq.parse_queue(json.dumps({"name": "q1", "items": items}).encode(), "q1")


def test_wait_event_restores_event_when_output_fails(tmp_path, monkeypatch):
    """#10: 소비 표시를 붙인 뒤 출력이 실패(세션이 끊겨 파이프 닫힘)하면 이벤트가 영영 사라지던 결함."""
    qp, be = ready(tmp_path, 1)
    lq.write_event(qp, "needs-fix", item="a1")
    d = qp.with_name("q1.events")

    def broken_print(*a, **kw):
        raise BrokenPipeError
    monkeypatch.setattr("builtins.print", broken_print)
    with pytest.raises(BrokenPipeError):
        lq.cmd_wait_event(SimpleNamespace(queue=str(qp), timeout=1, interval=5), be)
    monkeypatch.undo()
    assert len(list(d.glob("*.json"))) == 1 and not list(d.glob("*.consumed"))


def test_relaunch_failure_does_not_claim_there_was_no_free_gpu(tmp_path, capsys):
    """#10: 재발사가 실패(발사 실패)했는데 «빈 GPU 가 없어 맨 앞에 두었다» 고 말하던 오문구."""
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    run(be, *next_args(qp, "a1", 0, 2))                                 # a1 needs-fix, a2 가 GPU 0
    run(be, *next_args(qp, "a2", 0, 0))
    be.rc["a1"] = 65
    capsys.readouterr()
    assert run(be, "relaunch", qp, "--item", "a1", "--fix-note", "경로 수정") == 0
    out = capsys.readouterr().out
    assert "빈 GPU 가 없어" not in out and "launch-failed 상태" in out


def test_needs_fix_hint_limits_relaunch_to_path_import_arg_errors(tmp_path):
    """D8: 자동 재발사는 경로·import·인자 오류만 — needs-fix 이벤트가 세션에 그 기준을 전한다."""
    qp, be = ready(tmp_path, 1, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    run(be, *next_args(qp, "a1", 0, 2))
    hint = events(qp, "needs-fix")[0]["hint"]
    assert "경로·import·인자" in hint and "메모리 부족" in hint and "보고" in hint


def test_dead_watcher_of_running_item_emits_watcher_lost_once_and_wait_event_reports_it(tmp_path, capsys, monkeypatch):
    """#19: SIGKILL 로 죽은 와쳐는 종료 훅이 없어 사슬이 조용히 끊긴다 — 도는 판의 와쳐 PID 가 없으면 경고 이벤트."""
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    p = subprocess.Popen(["true"])
    p.wait()
    ls = tmp_path / "launch-state-x.json"
    ls.write_text(json.dumps({"watcher_pid": p.pid, "watcher_start": ""}))
    set_state(qp, a1={"launch_state": str(ls)})
    lq.note_lost_watchers(qp, be)
    lq.note_lost_watchers(qp, be)                                       # 같은 판은 한 번만
    assert len(events(qp, "watcher-lost")) == 1 and sum("와쳐가 죽었습니다" in n for n in be.notes) == 1
    monkeypatch.setattr(lq, "MIN_INTERVAL", 0.01)
    capsys.readouterr()
    assert run(be, "wait-event", qp, "--timeout", 1, "--interval", 0) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[0])["kind"] == "watcher-lost"
    set_state(qp, a1={"launch_state": None})


def test_watcher_lost_mark_is_cleared_after_reattach_so_second_death_alerts_again(tmp_path):
    """2026-10-01 P6 검수: reattach 뒤에도 watcher_lost 표시가 남아 두 번째 사망에는 알림이 없던 결함."""
    qp, be = ready(tmp_path, 2, gpus={0: gpu(*H100)})
    run(be, "start", qp, "--gpus", "0")
    p = subprocess.Popen(["true"])
    p.wait()
    ls = tmp_path / "launch-state-x.json"
    ls.write_text(json.dumps({"watcher_pid": p.pid, "watcher_start": ""}))
    set_state(qp, a1={"launch_state": str(ls)})
    lq.note_lost_watchers(qp, be)
    assert len(events(qp, "watcher-lost")) == 1 and state(qp)["items"]["a1"].get("watcher_lost")
    ls.write_text(json.dumps({"watcher_pid": os.getpid(), "watcher_start": ""}))   # reattach: 살아 있는 와쳐 PID
    lq.note_lost_watchers(qp, be)
    assert not state(qp)["items"]["a1"].get("watcher_lost"), "reattach 뒤에도 표시가 남음"
    ls.write_text(json.dumps({"watcher_pid": p.pid, "watcher_start": ""}))         # 두 번째 사망
    lq.note_lost_watchers(qp, be)
    assert len(events(qp, "watcher-lost")) == 2 and sum("와쳐가 죽었습니다" in n for n in be.notes) == 2
    set_state(qp, a1={"launch_state": None})


def test_next_is_not_blocked_by_log_dup_check_on_already_approved_queue(tmp_path):
    """2026-10-01 P6 검수: 로그 경로 중복 검사는 승인 시점 검증이다 — 검사가 생기기 전에 승인돼 도는 목록의 next 는 막지 않는다."""
    shared = str(tmp_path / "logs" / "shared")
    items = [mk_item(tmp_path, "a1", log_dir=shared), mk_item(tmp_path, "a2", log_dir=shared)]
    raw = json.dumps({"name": "q1", "items": items}).encode()
    with pytest.raises(lq.QueueError, match="로그 경로가 같습니다"):
        lq.parse_queue(raw, "q1")                                              # 승인 시점 검증은 그대로 거부
    assert len(lq.parse_queue(raw, "q1", check_log_dup=False)["items"]) == 2   # 발사 경로(launch_one)는 이 호출을 쓴다
    qp = mk_queue(tmp_path, [mk_item(tmp_path, "a1"), mk_item(tmp_path, "a2")])
    be = lq.FakeBackend({0: gpu(*H100)})
    assert run(be, "approve", qp, "--session", "test") == 0
    run(be, "start", qp, "--gpus", "0")
    qp.write_bytes(raw)                                                        # 옛 코드로 승인된 중복 목록을 흉내: 해시만 맞춘다
    st = state(qp)
    st["approved"]["sha256"] = lq.sha256(raw)
    lq.save_state(qp, st)
    n = len(be.launches)
    run(be, *next_args(qp, "a1", 0, 0))
    assert len(be.launches) == n + 1, "승인된 목록의 next 가 로그 중복 검사에 막힘"


def test_launch_script_binds_attempt_only_when_launch_set_supports_it(tmp_path, monkeypatch):
    """#1: 시도 번호 결박 인자는 새 launch-set.sh 에만 넘긴다(옛 사본은 모르는 인자라 발사 전체가 64 로 거부된다)."""
    qp = mk_queue(tmp_path, [mk_item(tmp_path, "a1")])
    item = lq.parse_queue(qp.read_bytes(), "q1")["items"][0]
    old, new = tmp_path / "old.sh", tmp_path / "new.sh"
    old.write_text("# no attempt flag\n")
    new.write_text("# --queue-attempt supported\n")
    monkeypatch.setattr(lq, "LAUNCH_SET", old)
    script, _ = lq.write_launch_script(qp, item, 3, "tq0", 0)
    assert "--queue-attempt" not in script.read_text()
    monkeypatch.setattr(lq, "LAUNCH_SET", new)
    script, _ = lq.write_launch_script(qp, item, 3, "tq0", 0)
    assert "--queue-attempt 3" in script.read_text()


# ───────────── 묶음 B 셸 사본(launch-set.sh·train-watcher.sh)의 짝 시험 ─────────────
# 가동 중인 와쳐 때문에 두 셸은 제자리 수정을 못 해 사본(.scratch/…/fix/B)에서 고쳤다. 교체 전에는 옛 셸이라 아래 시험이 의미가 없으므로 건너뛰고,
# TW_SCRIPT_DIR 로 사본을 가리키면 돈다. 교체 뒤에는 기본 경로에서 자동으로 돈다(옛 셸에 돌리면 실제 발사·알림이 일어날 수 있어 «실패 확인» 대신 건너뜀을 택했다).
NEW_SHELL = "--queue-attempt" in (SCRIPT_DIR / "launch-set.sh").read_text() and "--eval-timeout-h" in (SCRIPT_DIR / "train-watcher.sh").read_text()
needs_new_shell = pytest.mark.skipif(not NEW_SHELL, reason="launch-set.sh·train-watcher.sh 교체 대기(감사 P6 묶음 B) — TW_SCRIPT_DIR=<사본 폴더> 로 실행")


def _fake_home(tmp_path, preflight_stub=None):
    """HOME 을 임시 폴더로 바꾼 가짜 하네스: TW·MG 는 빈 파일(발사 직전 단계에서 끝나게), 사전검사는 인자를 기록하고 76 으로 거부하는 스텁."""
    tools = tmp_path / "home" / ".claude" / "tools"
    (tools / "train-watcher").mkdir(parents=True)
    (tools / "mem-guard").mkdir(parents=True)
    (tools / "train-watcher" / "train-watcher.sh").write_text("exit 0\n")
    (tools / "mem-guard" / "memguard-run.sh").write_text("exit 0\n")   # 곧바로 끝남 → launch-set 은 «학습이 ?s 안에 종료됨» exit 65 로 끝나고 state·와쳐를 만들지 않는다
    if preflight_stub:
        (tools / "train-watcher" / "gpu_preflight.py").write_text(preflight_stub)
    return tmp_path / "home"


def _run_launch_set(tmp_path, home, *extra, state="s.json"):
    cmd = ["bash", str(SCRIPT_DIR / "launch-set.sh"), "launch", "--name", "n", "--log", "l.log", "--done-regex", "x", "--eval-cmd", "true",
           "--title", "t", "--expect", "e", "--state", state, "--settle-sec", "1", *extra, "--", "sleep", "1"]
    env = {k: v for k, v in os.environ.items() if k not in ("CUDA_VISIBLE_DEVICES", "GPU_PREFLIGHT_FAKE")}
    return subprocess.run(cmd, check=False, cwd=tmp_path, env={**env, "HOME": str(home)}, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)


@needs_new_shell
@pytest.mark.parametrize("tok", ["--vram-gb 1", "--gpu=3", "--cpu-cores 99"])
def test_preflight_args_cannot_carry_canonical_keys(tmp_path, tok):
    """#14: --preflight-args 가 정본 인자(--gpu·--vram-gb·--cpu-cores)를 덮어쓰던 결함."""
    r = _run_launch_set(tmp_path, _fake_home(tmp_path), "--gpu", "2", "--preflight-args", tok)
    assert r.returncode == 64 and "--preflight-args" in r.stderr


@needs_new_shell
def test_preflight_canonical_args_come_last(tmp_path):
    """#14: 약어(--vram)로 키 검사를 피해도 정본이 맨 뒤에 있어 argparse 의 «마지막 값이 이긴다» 로 정본이 이긴다."""
    stub = "import sys, pathlib\npathlib.Path(sys.argv[0]).with_name('argv.txt').write_text(' '.join(sys.argv[1:]))\nsys.exit(76)\n"
    home = _fake_home(tmp_path, stub)
    r = _run_launch_set(tmp_path, home, "--gpu", "2", "--vram-gb", "9", "--cpu-cores", "3", "--preflight-args", "--util-max 50 --vram 1")
    assert r.returncode == 76
    argv = (home / ".claude" / "tools" / "train-watcher" / "argv.txt").read_text().split()
    assert argv.index("--vram") < argv.index("--vram-gb") and argv[argv.index("--gpu") + 1] == "2" and argv[argv.index("--vram-gb") + 1] == "9" and argv.index("--util-max") < argv.index("--gpu")


@needs_new_shell
def test_unknown_gpu_warns_on_stderr_not_stdout(tmp_path):
    """#16: GPU 를 몰라 사전검사를 건너뛸 때 경고가 표준출력에만 있어 파이프·로그에서 묻히던 것 — 표준에러로 명시."""
    r = _run_launch_set(tmp_path, _fake_home(tmp_path))
    assert "사전검사를 건너뜁니다" in r.stderr and "사전검사를 건너뜁니다" not in r.stdout


@needs_new_shell
def test_queue_attempt_must_be_integer_and_is_baked_into_on_exit(tmp_path):
    q = tmp_path / "q.json"
    q.write_text("{}")
    r = _run_launch_set(tmp_path, _fake_home(tmp_path), "--queue", str(q), "--queue-item", "a1", "--gpu", "0", "--queue-attempt", "x1")
    assert r.returncode == 64 and "정수" in r.stderr
    text = (SCRIPT_DIR / "launch-set.sh").read_text()
    func = re.search(r"^queue_on_exit\(\) \{.*?^\}", text, re.DOTALL | re.MULTILINE).group(0)
    run_fn = lambda *a: subprocess.run(["bash", "-c", f'{func}\nTW=/x/train-watcher.sh\nqueue_on_exit "$@"', "_", *a], check=False, capture_output=True, text=True).stdout
    assert run_fn("/q.json", "a1", "0", "3").endswith(' --attempt 3 --exit "$WATCH_EXIT"')
    assert "--attempt" not in run_fn("/q.json", "a1", "0") and run_fn("/q.json", "a1", "0").endswith(' --exit "$WATCH_EXIT"')   # 옛 호출은 옛 문자열 그대로


@needs_new_shell
def test_concurrent_launch_or_reattach_on_same_state_is_refused_with_67(tmp_path):
    """#15: 같은 state 에 대한 동시 launch·reattach 에 잠금이 없어 «state 없음» 확인을 둘 다 통과하던 결함."""
    home = _fake_home(tmp_path)
    (tmp_path / "s.json").write_text("{}")
    with open(tmp_path / "s.json.lock", "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)                     # 다른 launch·reattach 가 잡고 있는 상태
        r = _run_launch_set(tmp_path, home, "--gpu", "0", "--force")
        assert r.returncode == 67 and "진행 중" in r.stderr
        re_ = subprocess.run(["bash", str(SCRIPT_DIR / "launch-set.sh"), "reattach", str(tmp_path / "s.json")], check=False, cwd=tmp_path,
                             env={**os.environ, "HOME": str(home)}, capture_output=True, text=True, timeout=30)
        assert re_.returncode == 67 and "진행 중" in re_.stderr


@needs_new_shell
def test_reattach_appends_to_watcher_log_but_new_launch_truncates(tmp_path):
    """#16: 재부착이 와쳐 로그를 비워 이전 와쳐의 종료·실패 기록이 사라지던 결함(첫 줄 nonce 는 유지돼야 verify 가 통과한다)."""
    text = (SCRIPT_DIR / "launch-set.sh").read_text()
    funcs = "\n".join(re.search(rf"^{n}\(\) \{{.*?(?:^\}}|\}}$)", text, re.DOTALL | re.MULTILINE).group(0) for n in ("alive", "proc_cmdline", "proc_start", "start_watcher"))
    dummy_tw = tmp_path / "tw.sh"
    dummy_tw.write_text("sleep 7\n")
    wlog = tmp_path / "w.log"

    def start(nonce_in_file):
        wlog.write_text(f"[launch-set] nonce={nonce_in_file} train_pid=1 started=x\n[watcher] 이전 와쳐의 종료 기록\n")
        drv = f'{funcs}\nTW={shlex.quote(str(dummy_tw))} WLOG={shlex.quote(str(wlog))} NONCE=abc TRAIN_PID=1 STARTED=x LOG=l DONE_RX=x EVAL_CMD=true TITLE=t TW_ARGS= DONE_LOG= ON_EXIT=\nstart_watcher; echo rc=$?'
        subprocess.run(["bash", "-c", drv], check=False, capture_output=True, text=True, timeout=30)
        return wlog.read_text()
    kept = start("abc")                                      # 같은 발사의 재부착
    assert kept.splitlines()[0].startswith("[launch-set] nonce=abc") and "이전 와쳐의 종료 기록" in kept and "reattach" in kept
    fresh = start("other")                                   # nonce 가 다른 옛 로그는 새로 만든다
    assert fresh.splitlines()[0].startswith("[launch-set] nonce=abc") and "이전 와쳐의 종료 기록" not in fresh


@needs_new_shell
def test_watcher_argument_validation(tmp_path):
    """#20: --interval 0·비숫자가 검증 없이 통과해 PID 감시 루프가 CPU 를 태우던 것 / --eval-timeout-h 형식."""
    base = ["bash", str(SCRIPT_DIR / "train-watcher.sh"), "--pid", "1", "--log", str(tmp_path / "x.log"), "--done-regex", "x", "--eval-cmd", "true", "--no-notify"]
    for bad in (["--interval", "0"], ["--interval", "abc"], ["--timeout-h", "x"], ["--eval-timeout-h", "-1"], ["--eval-timeout-h", "1.2.3"]):
        r = subprocess.run([*base, *bad], check=False, capture_output=True, text=True, timeout=20)
        assert r.returncode == 64, bad


@needs_new_shell
def test_watcher_marker_scope_eval_timeout_signal_and_early_exit(tmp_path):
    """#17 eval 시간 초과(6, eval 은 안 죽임) · #18 재사용 로그의 옛 마커 무시 · #19 TERM 으로 죽을 때 종료 훅(7) · #20 PID 가 먼저 끝난 학습의 --done-log 마커."""
    done_log = tmp_path / "early.log"
    done_log.write_text("TRAIN_DONE (와쳐보다 먼저 끝난 학습)\n")
    gone = subprocess.Popen(["true"])
    gone.wait()                                              # 이미 없는 PID
    time.sleep(3)                                            # 마커 파일 mtime 이 «지금 -2초» 보다 오래되게(옛 코드는 이 조건에서 놓쳤다)
    hook = lambda n: f'echo "$WATCH_EXIT" >> {tmp_path / (n + ".txt")}'
    evalpid = tmp_path / "evalpid.txt"
    procs = {
        "stale": _watch(tmp_path, "stale", "", on_exit=hook("stale"), old_log="TRAIN_DONE (옛 실행)\n"),
        "evto": _watch(tmp_path, "evto", "TRAIN_DONE\n", on_exit=hook("evto"), eval_cmd=f"echo $$ > {evalpid}; sleep 25", extra=("--eval-timeout-h", "0.0004")),
        "term": _watch(tmp_path, "term", "TRAIN_DONE\n", on_exit=hook("term"), sec=15),
        "early": subprocess.Popen(["bash", str(SCRIPT_DIR / "train-watcher.sh"), "--pid", str(gone.pid), "--log", str(tmp_path / "early-run.log"), "--done-regex", "TRAIN_DONE",
                                   "--done-log", str(done_log), "--eval-cmd", "true", "--title", "early", "--interval", "1", "--no-notify", "--on-exit", hook("early")],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=tmp_path),
    }
    time.sleep(2)
    procs["term"].terminate()                                # 와쳐만 TERM(우리가 띄운 시험용 와쳐)
    outs = {k: p.communicate(timeout=90)[0] for k, p in procs.items()}
    rcs = {k: p.returncode for k, p in procs.items()}
    assert rcs == {"stale": 2, "evto": 6, "term": 7, "early": 0}, (rcs, outs)
    got = {n: (tmp_path / f"{n}.txt").read_text().split() for n in ("stale", "evto", "term", "early")}
    assert got == {"stale": ["2"], "evto": ["6"], "term": ["7"], "early": ["0"]}, got
    pid = int(evalpid.read_text())
    os.kill(pid, 0)                                          # eval 은 시간 초과 뒤에도 살아 있다(죽이지 않는다 — 신호 0 은 존재 확인뿐)
    assert "시간 초과" in (tmp_path / "evto.watch-report.md").read_text() and "신호" in (tmp_path / "term.watch-report.md").read_text()


# ── 종단 시험: 가짜 tmux·nvidia-smi 를 PATH 에 두고 launch_queue → launch-set 사본 → 가짜 학습 → 와쳐 사본 → on-exit → 다음 판 ──
FAKE_TMUX = """#!/bin/bash
# 시험용 가짜 tmux: 호출을 기록하고, send-keys 의 명령은 그 세션의 cwd 에서 터미널과 분리해 실행한다.
d="$FAKE_TMUX_DIR"
case "$1" in
  has-session) [ -e "$d/${3#=}.cwd" ] ;;
  new-session)
    shift; name=""; cwd="$PWD"
    while [ $# -gt 0 ]; do case "$1" in -s) name="$2"; shift 2 ;; -c) cwd="$2"; shift 2 ;; *) shift ;; esac; done
    printf '%s\\n' "$cwd" > "$d/$name.cwd"; echo 1 > "$d/$name.next"; echo "new-session $name" >> "$d/calls.log"; echo 0 ;;
  new-window)
    shift; t=""; while [ $# -gt 0 ]; do case "$1" in -t) t="$2"; shift 2 ;; *) shift ;; esac; done
    name="${t#=}"; name="${name%:}"; n="$(cat "$d/$name.next")"; echo $((n + 1)) > "$d/$name.next"
    echo "new-window $name:$n" >> "$d/calls.log"; echo "$n" ;;
  send-keys)
    t="${3#=}"; name="${t%%:*}"; cmd="$4"
    echo "send-keys $t" >> "$d/calls.log"
    ( cd "$(cat "$d/$name.cwd")" && setsid bash -c "$cmd" > "$d/${t/:/-}.out" 2>&1 < /dev/null & ) ;;
esac
"""
FAKE_SMI_E2E = """#!/bin/bash
case "$*" in
  *--query-gpu=index,pci.bus_id,name*) echo "0, 00000000:01:00.0, NVIDIA H100 PCIe, 81920, 512" ;;
  *--query-compute-apps*) : ;;
  *--query-gpu=index,utilization.gpu*) echo "0, 5" ;;
esac
"""


@needs_new_shell
@pytest.mark.skipif(not (os.environ.get("TW_E2E") == "1" and os.environ.get("XDG_RUNTIME_DIR") and os.environ.get("DBUS_SESSION_BUS_ADDRESS") and shutil.which("systemd-run") and shutil.which("flock")),
                    reason="실제 memguard scope(systemd --user)를 2개 만들고 이 호스트에선 끝난 scope 가 «active» 로 남아, 명시 opt-in(TW_E2E=1)일 때만 돈다")
def test_e2e_chain_fake_tmux_and_smi_launches_second_item_when_first_ends(tmp_path):
    home, fakebin, fdir, proj = tmp_path / "home", tmp_path / "fakebin", tmp_path / "fake-tmux", tmp_path / "proj"
    tools = home / ".claude" / "tools" / "train-watcher"
    for d in (tools, home / ".claude" / "tools" / "mem-guard", home / ".claude" / "scripts", fakebin, fdir, proj / ".claude" / "launch-queue", proj / "logs"):
        d.mkdir(parents=True, exist_ok=True)
    for src, name in ((SCRIPT_DIR, "launch-set.sh"), (SCRIPT_DIR, "train-watcher.sh"), (TW_DIR, "launch_queue.py"), (TW_DIR, "placement_table.json")):
        shutil.copy(src / name, tools / name)
    pre = (TW_DIR / "gpu_preflight.py").read_text()
    for old, new in (('"PATH": "/usr/bin:/bin"', f'"PATH": "{fakebin}:/usr/bin:/bin"'),     # 가짜 nvidia-smi 가 잡히게(실제 nvidia-smi 는 부르지 않는다)
                     ('"--sample-sec", type=int, default=60', '"--sample-sec", type=int, default=1'), ('"--cpu-reserve", type=float, default=8.0', '"--cpu-reserve", type=float, default=0.0')):
        assert old in pre, old
        pre = pre.replace(old, new)
    (tools / "gpu_preflight.py").write_text(pre)
    shutil.copy(TW_DIR.parents[1] / "tools" / "mem-guard" / "memguard-run.sh", home / ".claude" / "tools" / "mem-guard" / "memguard-run.sh")
    (home / ".claude" / "scripts" / "claude-notify.sh").write_text(f'echo "$2" >> {tmp_path / "notes.txt"}\n')
    (home / ".claude" / "scripts" / "oversight-append.sh").write_text("exit 0\n")
    for n, body in (("tmux", FAKE_TMUX), ("nvidia-smi", FAKE_SMI_E2E)):
        (fakebin / n).write_text(body)
        (fakebin / n).chmod(0o755)
    (proj / "run.sh").write_text('echo "start $1"\nsleep 26\necho TRAIN_DONE\n')   # launch-set 의 settle 10초 + 와쳐 5초 + verify 가 끝날 때까지 살아 있어야 한다
    (proj / ".claude" / "train.env").write_text("TRAIN_TMUX_PREFIX=e2e\n")
    items = [mk_item(tmp_path, i, argv=["bash", "run.sh", "{GPU}"], log_dir=str(proj / "logs" / i), vram_gb=1, cpu_cores=0.01,
                     memguard_args="--high 1G --max 2G --reserve 1G --swap-max none", watcher_args="--interval 1") for i in ("a1", "a2")]
    qp = proj / ".claude" / "launch-queue" / "q.json"
    qp.write_text(json.dumps({"name": "q", "items": items}, ensure_ascii=False, indent=2))
    env = {**os.environ, "HOME": str(home), "PATH": f"{fakebin}:{os.environ['PATH']}", "FAKE_TMUX_DIR": str(fdir)}
    env.pop("GPU_PREFLIGHT_FAKE", None)
    py = ["/usr/bin/python3", str(tools / "launch_queue.py")]
    assert subprocess.run([*py, "approve", str(qp), "--session", "e2e"], check=False, env=env, capture_output=True, text=True, timeout=60, cwd=proj).returncode == 0
    r = subprocess.run([*py, "start", str(qp), "--gpus", "0"], check=False, env=env, capture_output=True, text=True, timeout=240, cwd=proj)
    assert r.returncode == 0 and "발사: 판 a1" in r.stdout, (r.stdout, r.stderr)
    sp = qp.with_name("q.state.json")
    deadline = time.time() + 240
    st = {}
    while time.time() < deadline:
        st = json.loads(sp.read_text())
        if all(s["status"] == "done" for s in st["items"].values()):
            break
        time.sleep(3)
    assert {k: v["status"] for k, v in st["items"].items()} == {"a1": "done", "a2": "done"}, (st, (fdir / "e2e0-0.out").read_text() if (fdir / "e2e0-0.out").exists() else "")
    calls = [ln.split() for ln in (fdir / "calls.log").read_text().splitlines()]
    assert [c[1] for c in calls if c[0] == "new-session"] == ["e2e0"] and [c[1] for c in calls if c[0] == "new-window"] == ["e2e0:1"]   # 같은 GPU 0 의 둘째 판은 새 세션이 아니라 새 창
    ls2 = json.loads((proj / "logs" / "a2" / "launch-state-e2e0-a2-1.json").read_text())
    assert ls2["queue_item"] == "a2" and ls2["queue_attempt"] == "1"      # 시도 번호가 on-exit 에 결박돼 있다
    assert "WATCH_EXIT=0" in (proj / "logs" / "a1" / "watcher-e2e0-a1-1.log").read_text()
    assert "자동 발사: 판 a2" in (tmp_path / "notes.txt").read_text()
    for _ in range(20):   # a2 의 종료 훅(next)이 상태를 done 으로 적은 직후 maybe_finish 가 queue-finished 를 낸다
        if list(qp.with_name("q.events").glob("*queue-finished*")):
            break
        time.sleep(1)
    assert list(qp.with_name("q.events").glob("*queue-finished*"))


# ───────────── launch-set.sh 심사 시각 점검 보고서(--design-review · intent 옆 .review.md, 2026-10-12) ─────────────
has_design_review = pytest.mark.skipif("--design-review" not in (SCRIPT_DIR / "launch-set.sh").read_text(), reason="launch-set.sh 에 --design-review 가 아직 없음")
DR_WARN = "경고: 심사 시각 점검 보고서 없음("


def _dr_launch(tmp_path, *extra):
    """Run launch-set.sh in a fake HOME whose memguard just execs the command: the run is rejected after start (no memguard scope) and leaves a status=rejected state."""
    home = _fake_home(tmp_path)
    (home / ".claude" / "tools" / "mem-guard" / "memguard-run.sh").write_text('while [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n')
    cmd = ["bash", str(SCRIPT_DIR / "launch-set.sh"), "launch", "--name", "n", "--log", "l.log", "--done-regex", "x", "--eval-cmd", "true",
           "--title", "t", "--expect", "e", "--state", "s.json", "--settle-sec", "1", *extra, "--", "sleep", "3"]
    env = {k: v for k, v in os.environ.items() if k not in ("CUDA_VISIBLE_DEVICES", "GPU_PREFLIGHT_FAKE")}
    return subprocess.run(cmd, check=False, cwd=tmp_path, env={**env, "HOME": str(home)}, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)


def _mk_intent(tmp_path):
    (tmp_path / "intent").mkdir()
    (tmp_path / "intent" / "x.md").write_text("intent\n")


@has_design_review
def test_design_review_next_to_intent_is_found_and_recorded_without_warning(tmp_path):
    import hashlib
    _mk_intent(tmp_path)
    (tmp_path / "intent" / "x.review.md").write_text("review body\n")
    r = _dr_launch(tmp_path, "--intent", "intent/x.md")
    st = json.loads((tmp_path / "s.json").read_text())
    assert r.returncode == 65 and DR_WARN not in r.stderr and DR_WARN not in r.stdout
    assert st["design_review"] == "intent/x.review.md" and st["design_review_sha256"] == hashlib.sha256(b"review body").hexdigest()


@has_design_review
def test_design_review_argument_is_recorded_and_beats_intent_neighbour(tmp_path):
    import hashlib
    _mk_intent(tmp_path)
    (tmp_path / "rv").mkdir()
    (tmp_path / "rv" / "my.review.md").write_text("other review")
    r = _dr_launch(tmp_path, "--intent", "intent/x.md", "--design-review", "rv/my.review.md")
    st = json.loads((tmp_path / "s.json").read_text())
    assert r.returncode == 65 and DR_WARN not in r.stderr
    assert st["design_review"] == "rv/my.review.md" and st["design_review_sha256"] == hashlib.sha256(b"other review").hexdigest()


@has_design_review
def test_design_review_missing_warns_on_stderr_and_launch_proceeds(tmp_path):
    _mk_intent(tmp_path)
    home = _fake_home(tmp_path)
    r = _run_launch_set(tmp_path, home, "--intent", "intent/x.md")
    assert f"{DR_WARN}intent/x.review.md)" in r.stderr and DR_WARN not in r.stdout
    assert r.returncode == 65 and "종료됨" in r.stderr   # 경고 뒤에도 발사 경로가 계속 진행돼 학습 시작 검사까지 갔다(차단 아님)
    r = _run_launch_set(tmp_path, home, "--design-review", "nope.review.md")
    assert f"{DR_WARN}nope.review.md)" in r.stderr and r.returncode == 65


@has_design_review
@pytest.mark.parametrize("explicit", [False, True])
def test_design_review_symlink_is_refused(tmp_path, explicit):
    _mk_intent(tmp_path)
    (tmp_path / "real.md").write_text("r")
    (tmp_path / "intent" / "x.review.md").symlink_to(tmp_path / "real.md")
    extra = ["--intent", "intent/x.md"] + (["--design-review", "intent/x.review.md"] if explicit else [])
    r = _run_launch_set(tmp_path, _fake_home(tmp_path), *extra)
    assert r.returncode == 64 and "링크" in r.stderr and not (tmp_path / "s.json").exists()


@has_design_review
def test_old_state_without_design_review_fields_verifies_and_reattach_does_not_crash(tmp_path):
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"schema": 3, "name": "n", "status": "launched", "host": "other-host", "train_pid": 999999, "watcher_pid": 0, "eval_cmd": "true", "intent": "", "intent_sha256": ""}))
    state.chmod(0o600)
    v = subprocess.run(["bash", str(SCRIPT_DIR / "launch-set.sh"), "verify", str(state)], check=False, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert v.returncode == 1 and "design_review 미기록" in v.stdout and "VERIFY FAIL" in v.stdout   # 끝까지 돌았고 새 항목은 참고(⚠)로만 나온다
    assert "판정에 미포함" in next(ln for ln in v.stdout.splitlines() if "design_review" in ln)
    re_ = subprocess.run(["bash", str(SCRIPT_DIR / "launch-set.sh"), "reattach", str(state), "--confirm-eval", "true"], check=False, cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert re_.returncode == 65 and "host 불일치" in re_.stdout and "unbound" not in re_.stderr
