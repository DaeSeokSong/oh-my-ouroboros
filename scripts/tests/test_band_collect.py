# scripts/tests/test_band_collect.py
"""band_server_collect·band_work_collect 의 파싱·판정 시험. 실행: uv run -q --with pytest python -m pytest scripts/tests/test_band_collect.py -q -p no:cacheprovider"""
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import band_server_collect as srv

NVSMI = "0, 0, 14, 46068\n3, 96, 26419, 81559\n"
FREE = ("               total        used        free      shared  buff/cache   available\n"
        "Mem:    269484695552 41851256832 1000 0 2 227633438720\n"
        "Swap:            0           0           0\n")
DF = ("Filesystem 1-blocks Used Available Capacity Mounted on\n"
      "/dev/nvme0n1p2 943804760064 813882097664 129922662400 87% /\n")

def test_parse_gpus():
    assert srv.parse_gpus(NVSMI) == [
        {"i": 0, "util": 0, "used": 14, "total": 46068},
        {"i": 3, "util": 96, "used": 26419, "total": 81559}]

def test_parse_gpus_garbage_is_none():
    assert srv.parse_gpus("NVIDIA-SMI has failed") is None

def test_parse_mem_and_disk():
    assert srv.parse_mem(FREE) == {"total": 269484695552, "avail": 227633438720}
    assert srv.parse_disk(DF) == {"total": 943804760064, "avail": 129922662400}

def test_read_sessions_whitelist_and_clean(tmp_path):
    (tmp_path / "111.json").write_text(json.dumps(
        {"pid": 111, "sessionId": "0c7530cd-4cc9-47a1-9df0-ab9103f6e70d",
         "name": "[exp] Manager\x1b]0;x\x07", "status": "busy", "messagingSocketPath": "/run/x.sock"}))
    (tmp_path / "111.abc.key").write_text("SECRET")
    (tmp_path / "notes.json").write_text("{}")
    got = srv.read_sessions(tmp_path, alive=lambda pid: True)
    assert got == [{"sid": "0c7530cd-4cc9-47a1-9df0-ab9103f6e70d", "name": "[exp] Manager]0;x", "status": "busy",
                    "job": None, "job_state": None, "job_detail": None}]

def test_read_sessions_job_id_only_8_hex(tmp_path):
    # 개정 20: 띠의 «제거» 버튼이 `claude rm <잡 id>` 에 쓰므로 8자리 16진만 싣는다.
    for i, job in enumerate(("0c7530cd", "0c7530cd;rm", "0C7530CD", "0c7530cd\n", 12345678)):
        (tmp_path / f"{100 + i}.json").write_text(json.dumps(
            {"pid": 100 + i, "sessionId": f"0c7530cd-4cc9-47a1-9df0-ab9103f6e7{i:02d}", "name": "n", "status": "idle", "jobId": job}))
    got = srv.read_sessions(tmp_path, alive=lambda pid: True, jobs_dir=tmp_path / "nojobs")
    assert [s["job"] for s in got] == ["0c7530cd", None, None, None, None]

def test_read_sessions_skips_dead(tmp_path):
    (tmp_path / "222.json").write_text(json.dumps({"pid": 222, "sessionId": "a" * 8 + "-0000-0000-0000-" + "0" * 12, "name": "x", "status": "idle"}))
    assert srv.read_sessions(tmp_path, alive=lambda pid: False) == []

import band_work_collect as wrk

PS = ("  100     1 /usr/bin/claude\n"
      "  200   100 bash -c tools/grok-exchange/grok-ask.sh -m fake\n"
      "  210   200 /home/u/.grok/downloads/grok-1.0.46-linux-x86_64 --prompt-file /tmp/p -m grok-4.7 --reasoning-effort high --sandbox strict\n"
      "  300   100 node /x/codex-companion.mjs task\n"
      "  310   300 /usr/lib/node_modules/@openai/codex/bin/codex app-server\n"
      "  400     1 /home/u/.grok/downloads/grok-1.0.46-linux-x86_64 -m other-session --reasoning-effort low\n")

def test_descendants_only_own_tree():
    table = wrk.parse_ps(PS)
    assert sorted(wrk.descendants(table, 100)) == [200, 210, 300, 310]

def test_grok_from_argv_only_grok_binary():
    table = wrk.parse_ps(PS)
    got = wrk.find_grok(table, wrk.descendants(table, 100))
    assert got == [{"model": "grok-4.7", "effort": "high"}]   # 200(bash) 의 '-m fake' 와 400(다른 세션)은 제외

def test_bad_values_rejected():
    assert wrk.safe("grok-4.7") == "grok-4.7"
    assert wrk.safe("x;rm -rf") is None

def test_codex_from_rollout(tmp_path):
    r = tmp_path / "rollout-2026-10-14T17-29-32-x.jsonl"
    r.write_text('{"type":"session_meta"}\n{"type":"turn_context","payload":{"model":"gpt-6.1-sol","effort":"xhigh"}}\n')
    assert wrk.codex_from_rollout(r) == {"model": "gpt-6.1-sol", "effort": "xhigh"}

def test_train_states(tmp_path):
    d = tmp_path / ".scratch" / "job1" / "launch"; d.mkdir(parents=True)
    (d / "launch-state-a.json").write_text(json.dumps({"name": "a", "train_pid": 1, "train_start": "5", "boot_id": "B"}))
    (d / "launch-state-b.json").write_text(json.dumps({"name": "b", "train_pid": 2, "train_start": "9", "boot_id": "B"}))
    st = wrk.train_states(tmp_path, boot_id="B", start_of=lambda pid: {1: "5", 2: "7"}.get(pid), now=None)
    assert st == {"running": ["a"], "ended": ["b"]}


# ---- 검수 반영(2026-10-15) ----
import stat as _stat
import time


def test_clean_strips_bidi_and_line_separators():
    bad = "".join(chr(c) for c in (0x202E, 0x2066, 0x2029, 0x2028, 0x202A, 0x2069, 0x1B, 0x07, 0x85))
    assert srv.clean("a" + bad + "bc") == "abc"

def test_read_sessions_skips_non_dict_symlink_and_oversize(tmp_path):
    sid = "0c7530cd-4cc9-47a1-9df0-ab9103f6e70d"
    (tmp_path / "1.json").write_text("[1,2]")
    (tmp_path / "2.json").write_text(json.dumps({"pid": 2, "sessionId": sid, "name": "x" * 2_000_000}))
    real = tmp_path / "real.txt"; real.write_text(json.dumps({"pid": 3, "sessionId": sid, "name": "link", "status": "busy"}))
    os.symlink(real, tmp_path / "3.json")
    assert srv.read_sessions(tmp_path, alive=lambda pid: True) == []

def _gpu_env(monkeypatch, tmp_path, elapsed, prev_age=None):
    calls = []
    def fake(argv, timeout=3):
        calls.append(argv[0])
        if argv[0] == "pgrep":
            return "123\n"
        return NVSMI if argv[0] == "nvidia-smi" else None
    monkeypatch.setattr(srv, "run", fake)
    monkeypatch.setattr(srv, "_elapsed", lambda pid: elapsed)
    monkeypatch.setattr(srv, "CACHE_DIR", tmp_path)
    if prev_age is not None:
        (tmp_path / "server.json").write_text(json.dumps({"ts": time.time() - prev_age, "gpus": [{"i": 9}]}))
    return calls

def test_collect_queries_gpu_when_nvidia_smi_is_short(monkeypatch, tmp_path):
    calls = _gpu_env(monkeypatch, tmp_path, 2.0)
    out = srv.collect()
    assert "nvidia-smi" in calls and out["gpus"][0]["i"] == 0

def test_collect_skips_stuck_nvidia_smi_and_carries_recent_gpus(monkeypatch, tmp_path):
    calls = _gpu_env(monkeypatch, tmp_path, 15.0, prev_age=30)
    out = srv.collect()
    assert "nvidia-smi" not in calls and out["gpus"] == [{"i": 9}]

def test_collect_drops_gpus_older_than_60s(monkeypatch, tmp_path):
    calls = _gpu_env(monkeypatch, tmp_path, 15.0, prev_age=90)
    out = srv.collect()
    assert "nvidia-smi" not in calls and out["gpus"] is None

def test_main_perms_and_attempt_first(tmp_path, monkeypatch):
    d = tmp_path / "band"; d.mkdir(mode=0o755)
    monkeypatch.setattr(srv, "CACHE_DIR", d)
    seen = {}
    def fake_collect():
        seen["attempt_before_collect"] = (d / "server.attempt").exists()
        return {"ts": 1}
    monkeypatch.setattr(srv, "collect", fake_collect)
    srv.main()
    assert seen["attempt_before_collect"]
    assert _stat.S_IMODE(os.stat(d).st_mode) == 0o700
    for n in ("server.json", "server.attempt"):
        assert _stat.S_IMODE(os.stat(d / n).st_mode) == 0o600
    assert sorted(p.name for p in d.iterdir()) == ["server.attempt", "server.json", "server.lock"]   # 임시 파일 잔재 없음

def test_codex_wrapper_counted_once():
    ps = ("  100     1 /usr/bin/claude\n"
          "  300   100 node /usr/lib/node_modules/@openai/codex/bin/codex app-server\n"
          "  310   300 /usr/lib/node_modules/@openai/codex/vendor/codex-x86_64-unknown-linux-musl/codex/codex-x86_64-unknown-linux-musl app-server\n"
          "  320   100 rg codex src\n")
    table = wrk.parse_ps(ps)
    assert len(wrk.find_codex(table, wrk.descendants(table, 100))) == 1

def test_rollout_path_confined_to_sessions_root(tmp_path):
    root = tmp_path / "sessions"; (root / "d").mkdir(parents=True)
    ok = root / "d" / "rollout-1.jsonl"; ok.write_text("{}")
    other = tmp_path / "rollout-2.jsonl"; other.write_text("{}")
    link = root / "d" / "rollout-3.jsonl"; os.symlink(other, link)
    r = str(root.resolve())
    assert wrk.rollout_path(str(ok), r) == str(ok.resolve())
    assert wrk.rollout_path(str(other), r) is None
    assert wrk.rollout_path(str(link), r) is None            # 링크는 밖으로 풀리므로 거부

def test_codex_from_rollout_rejects_symlink_and_fifo(tmp_path):
    real = tmp_path / "real.jsonl"; real.write_text('{"type":"turn_context","payload":{"model":"m","effort":"low"}}\n')
    os.symlink(real, tmp_path / "rollout-l.jsonl")
    assert wrk.codex_from_rollout(tmp_path / "rollout-l.jsonl") is None
    os.mkfifo(tmp_path / "rollout-f.jsonl")
    assert wrk.codex_from_rollout(tmp_path / "rollout-f.jsonl") is None   # 비정규 파일은 읽지 않고 막히지도 않는다

def test_ended_time_from_log_mtime_not_state_mtime(tmp_path):
    d = tmp_path / ".scratch" / "j" / "launch"; d.mkdir(parents=True)
    log = d / "watcher.log"; log.write_text("x")
    state = d / "launch-state-a.json"
    state.write_text(json.dumps({"name": "a", "train_pid": 1, "train_start": "9", "boot_id": "B", "watcher_log": str(log)}))
    now = time.time()
    os.utime(state, (now - 3 * 86400,) * 2)
    os.utime(log, (now - 3600,) * 2)
    assert wrk.train_states(tmp_path, "B", start_of=lambda pid: None, now=now) == {"running": [], "ended": ["a"]}
    os.utime(log, (now - 3 * 86400,) * 2)                      # 로그도 오래되면 종료 목록에서 빠진다
    assert wrk.train_states(tmp_path, "B", start_of=lambda pid: None, now=now) == {"running": [], "ended": []}

def test_ended_time_ignores_symlink_log_and_falls_back(tmp_path):
    d = tmp_path / ".scratch" / "j" / "launch"; d.mkdir(parents=True)
    fresh = d / "fresh.log"; fresh.write_text("x")
    link = d / "link.log"; os.symlink(fresh, link)
    state = d / "launch-state-a.json"
    state.write_text(json.dumps({"name": "a", "watcher_log": str(link), "train_log": str(d / "none.log")}))
    now = time.time()
    os.utime(state, (now - 3 * 86400,) * 2)
    assert wrk.train_states(tmp_path, "B", start_of=lambda pid: None, now=now)["ended"] == []

def test_train_name_fallback_and_non_dict(tmp_path):
    d = tmp_path / ".scratch" / "j" / "launch"; d.mkdir(parents=True)
    (d / "launch-state-bad name;x.json").write_text(json.dumps({"name": "bad;name"}))
    (d / "launch-state-list.json").write_text("[1]")
    st = wrk.train_states(tmp_path, "B", start_of=lambda pid: None)
    assert st == {"running": [], "ended": ["?"]}

def test_git_root_walks_up_without_git_binary(tmp_path):
    (tmp_path / ".git").mkdir()
    deep = tmp_path / "a" / "b"; deep.mkdir(parents=True)
    assert wrk.git_root(str(deep)) == str(tmp_path)


# ---- 재검수 잔여(2026-10-15) ----
def test_codex_from_rollout_skips_non_dict_lines(tmp_path):
    r = tmp_path / "rollout-a.jsonl"
    r.write_text('{"type":"turn_context","payload":{"model":"gpt-6.1-sol","effort":"low"}}\n'
                 '{"type":"turn_context","payload":"text"}\n'
                 '[]\n'
                 '{"type":"turn_context","payload":[1]}\n')
    assert wrk.codex_from_rollout(r) == {"model": "gpt-6.1-sol", "effort": "low"}   # 뒤쪽 비정상 줄은 건너뛰고 앞의 유효 줄
    only_bad = tmp_path / "rollout-b.jsonl"
    only_bad.write_text('"turn_context"\n[]\n{"type":"turn_context","payload":"s"}\n')
    assert wrk.codex_from_rollout(only_bad) is None

def test_codex_exe_regex_is_strict():
    ps = ("  100     1 /usr/bin/claude\n"
          "  110   100 /usr/bin/codexx app-server\n"
          "  120   100 /usr/bin/codex2 app-server\n"
          "  130   100 node /x/codex-companion task\n"
          "  140   100 /x/codex-companion task\n")
    table = wrk.parse_ps(ps)
    assert wrk.find_codex(table, wrk.descendants(table, 100)) == []
    ok = wrk.parse_ps("  100     1 claude\n  200   100 /v/codex-aarch64-unknown-linux-musl exec\n  210   100 codex exec\n")
    assert len(wrk.find_codex(ok, wrk.descendants(ok, 100))) == 2

def test_train_name_from_filename_when_state_has_no_name(tmp_path):
    d = tmp_path / ".scratch" / "j" / "launch"; d.mkdir(parents=True)
    (d / "launch-state-exp-a1.json").write_text(json.dumps({"train_pid": 1, "train_start": "5", "boot_id": "B"}))
    st = wrk.train_states(tmp_path, "B", start_of=lambda pid: "5")
    assert st == {"running": ["exp-a1"], "ended": []}


# ---- 학습 판(개정 8, 2026-10-15) ----
def test_parse_compute_apps_and_uuids():
    assert srv.parse_compute_apps("2731686, GPU-aaaa-1111\n713717, GPU-bbbb-2222\n") == [(2731686, "GPU-aaaa-1111"), (713717, "GPU-bbbb-2222")]
    assert srv.parse_compute_apps("") == [] and srv.parse_compute_apps(None) == []
    assert srv.parse_compute_apps("No devices were found\nx, y\n12, bad uuid!\n1,2,3\n") == []
    assert srv.parse_gpu_uuids("3, GPU-aaaa-1111\n4, GPU-bbbb-2222\n") == {"GPU-aaaa-1111": 3, "GPU-bbbb-2222": 4}
    assert srv.parse_gpu_uuids("garbage\n\n") == {}

def test_run_name_from_cgroup():
    cg = "0::/user.slice/user-1000.slice/memguard-exp-r72-2731642.scope\n"
    assert srv.run_name_from_cgroup(cg) == "exp-r72"
    assert srv.run_name_from_cgroup("0::/user.slice/session-3.scope\n") is None
    assert srv.run_name_from_cgroup("0::/memguard-bad name;x-12.scope") is None   # 이상한 글자
    assert srv.run_name_from_cgroup("0::/memguard-" + "a" * 70 + "-12.scope") is None   # 60자 초과

def test_cmdline_helpers():
    args = ["python", "-m", "x", "++model.epoch.max_epochs=30", "train.py", "++model.epoch.max_epochs=60"]
    assert srv.max_epochs_from_cmdline(args) == 60                    # 여러 개면 마지막
    assert srv.max_epochs_from_cmdline(["python", "a.py"]) is None
    assert srv.max_epochs_from_cmdline(["max_epochs=abc"]) is None
    assert srv.script_name_from_cmdline(["python", "/x/y/train_mtl.py", "--a"]) == "train_mtl.py"
    assert srv.script_name_from_cmdline(["python", "/x/bad name.py"]) is None
    assert srv.script_name_from_cmdline(["bash", "-c"]) is None

def test_parse_ckpt_names_real_examples():
    names = ["best-epoch=0004-val_gated_tri_mean=-0.2779.ckpt", "best-epoch=0009-val_gated_tri_mean=-0.2345.ckpt",
             "best-epoch=0014-val_gated_tri_mean=-0.2247.ckpt", "last.ckpt", "notes.txt"]
    metric, ckpts, last = srv.parse_ckpt_names(names)
    assert metric == "val_gated_tri_mean" and last is True
    assert ckpts == [{"epoch": 4, "value": -0.2779}, {"epoch": 9, "value": -0.2345}, {"epoch": 14, "value": -0.2247}]

def test_parse_ckpt_names_edge_cases():
    assert srv.parse_ckpt_names([]) == (None, [], False)
    assert srv.parse_ckpt_names(["last.ckpt"]) == (None, [], True)
    m, c, _ = srv.parse_ckpt_names(["epoch=7.ckpt"])                     # 이름 없는 epoch → value null
    assert m is None and c == [{"epoch": 7, "value": None}]
    # 다른 지표 섞임: 가장 많이 나온 이름만 값을 담고 나머지 파일은 value null
    m, c, _ = srv.parse_ckpt_names(["epoch=0001-a=0.5.ckpt", "epoch=0002-a=0.6.ckpt", "epoch=0003-b=9.0.ckpt"])
    assert m == "a" and c == [{"epoch": 1, "value": 0.5}, {"epoch": 2, "value": 0.6}, {"epoch": 3, "value": None}]
    # nan·inf 는 값에서 배제
    m, c, _ = srv.parse_ckpt_names(["epoch=0001-a=nan.ckpt", "epoch=0002-a=inf.ckpt", "epoch=0003-a=1.5-v1.ckpt"])
    assert m == "a" and c == [{"epoch": 1, "value": None}, {"epoch": 2, "value": None}, {"epoch": 3, "value": 1.5}]
    # 21개 이상이면 높은 에폭 20개만, 오름차순
    m, c, _ = srv.parse_ckpt_names([f"epoch={i:04d}-a={i}.0.ckpt" for i in range(30)])
    assert len(c) == 20 and c[0]["epoch"] == 10 and c[-1]["epoch"] == 29

def test_ckpt_names_from_fd_folder(tmp_path, monkeypatch):
    run = tmp_path / "run"; (run / "checkpoints").mkdir(parents=True)
    (run / "checkpoints" / "last.ckpt").write_text("x")
    (run / "checkpoints" / "best-epoch=0003-v=1.0.ckpt").write_text("x")
    log = run / "train.log"; log.write_text("x")
    fdd = tmp_path / "fd"; fdd.mkdir()
    os.symlink(log, fdd / "5")
    os.symlink("/dev/null", fdd / "6")
    os.symlink("socket:[123]", fdd / "7")
    real_listdir, real_readlink, real_stat = os.listdir, os.readlink, os.stat
    monkeypatch.setattr(srv.os, "listdir", lambda p: real_listdir(fdd) if str(p).endswith("/fd") else real_listdir(p))
    monkeypatch.setattr(srv.os, "readlink", lambda p: real_readlink(fdd / pathlib.Path(p).name))
    monkeypatch.setattr(srv.os, "stat", lambda p: real_stat(fdd / pathlib.Path(p).name))
    folder, names = srv._ckpt_folder(1, [("/", "ext4")])
    assert folder == str(run / "checkpoints") and sorted(names) == ["best-epoch=0003-v=1.0.ckpt", "last.ckpt"]
    # 원격 FS 위 폴더는 stat·scandir 하지 않는다: 호출되면 실패하는 함수로 바꿔 증명한다
    def boom(*a, **k): raise AssertionError("touched a remote path")
    monkeypatch.setattr(srv.os, "stat", boom)
    monkeypatch.setattr(srv.os, "scandir", boom)
    assert srv._ckpt_folder(1, [(str(tmp_path), "nfs4"), ("/", "ext4")]) == (None, [])
    assert srv._ckpt_folder(1, None) == (None, [])                                # 마운트 표를 못 읽으면 아무것도 건드리지 않는다

def test_mounts_remote_detection():
    text = ("/dev/sda1 / ext4 rw 0 0\nserver:/x /data nfs4 rw 0 0\nsrv:/y /data/local\\040dir ext4 rw 0 0\n"
            "sshfs#u@h: /mnt/s fuse.sshfs rw 0 0\nnone /mnt/ok tmpfs rw 0 0\n//h/s /mnt/w cifs rw 0 0\n")
    m = srv.parse_mounts(text)
    assert srv.is_local_path("/home/u/run/a.log", m)
    assert not srv.is_local_path("/data/run/a.log", m) and not srv.is_local_path("/data", m)
    assert srv.is_local_path("/data/local dir/x", m)                       # 더 긴 마운트(8진수 이스케이프 해제)가 이긴다
    assert srv.is_local_path("/database/x", m)                             # 접두 문자열이 아니라 경로 경계
    assert not srv.is_local_path("/mnt/s/x", m) and not srv.is_local_path("/mnt/w/x", m)
    assert srv.is_local_path("/mnt/ok/x", m)
    assert not srv.is_local_path("/x", None)

def test_validation_regexes_reject_trailing_newline():
    assert srv.script_name_from_cmdline(["a.py\n"]) is None
    assert srv.max_epochs_from_cmdline(["max_epochs=5\n"]) is None
    assert srv.parse_ckpt_names(["epoch=1-a=1.0.ckpt\n"]) == (None, [], False)

def test_ckpt_metric_skips_step_and_epoch_pairs():
    m, c, _ = srv.parse_ckpt_names(["epoch=0014-step=123-val_x=-0.1.ckpt"])
    assert m == "val_x" and c == [{"epoch": 14, "value": -0.1}]
    m, c, _ = srv.parse_ckpt_names(["epoch=0002-step=9.ckpt"])            # step 만 있으면 지표 없음
    assert m is None and c == [{"epoch": 2, "value": None}]

def test_last_ckpt_variants():
    assert srv.parse_ckpt_names(["last-v1.ckpt"])[2] is True
    assert srv.parse_ckpt_names(["last-v12.ckpt"])[2] is True
    assert srv.parse_ckpt_names(["last-x.ckpt", "mylast.ckpt", "last.ckpt.bak"])[2] is False

def test_collect_train_merges_ddp_and_sorts(monkeypatch):
    out = {"--query-compute-apps=pid,gpu_uuid": "11, U3\n12, U3\n13, U4\n99, UX\n", "--query-gpu=index,uuid": "3, U3\n4, U4\n"}
    monkeypatch.setattr(srv, "run", lambda argv, timeout=3: out[argv[1]])
    runs = {11: {"name": "exp-a", "max_epochs": None, "done": None, "metric": None, "ckpts": [], "last": False},
            12: {"name": "exp-a", "max_epochs": 60, "done": 17, "metric": "m", "ckpts": [{"epoch": 1, "value": 0.5}], "last": True},
            13: {"name": "b", "max_epochs": 5, "done": None, "metric": None, "ckpts": [], "last": False}}
    reads = []
    monkeypatch.setattr(srv, "read_mounts", list)
    monkeypatch.setattr(srv, "read_watcher_pids", lambda: set())
    monkeypatch.setattr(srv, "read_run", lambda pid, mounts: reads.append(pid) or dict(runs[pid]))
    got = srv.collect_train()
    assert got == [{"gpu": 3, "name": "exp-a", "max_epochs": 60, "done": 17, "metric": "m", "ckpts": [{"epoch": 1, "value": 0.5}], "last": True, "watcher": None},
                   {"gpu": 4, "name": "b", "max_epochs": 5, "done": None, "metric": None, "ckpts": [], "last": False, "watcher": None}]
    assert sorted(reads) == [11, 12, 13]                                   # pid 마다 /proc 은 한 번만 읽는다
    monkeypatch.setattr(srv, "run", lambda argv, timeout=3: None)
    assert srv.collect_train() is None

import pickle
import zipfile


def _ckpt_zip(path, obj=None, member="archive/data.pkl", raw=None, compression=zipfile.ZIP_STORED):
    data = raw if raw is not None else pickle.dumps(obj, protocol=2)
    with zipfile.ZipFile(path, "w", compression) as z:
        z.writestr(member, data)
        z.writestr("archive/version", "3\n")
    return path

def test_done_epochs_from_ckpt(tmp_path):
    state = {"state_dict": {"a": 1}, "epoch": 16, "global_step": 4777}
    assert srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "a.ckpt", state)) == 17
    assert srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "b.ckpt", state, compression=zipfile.ZIP_DEFLATED)) == 17
    assert srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "c.ckpt", state, member="data.pkl")) == 17
    assert srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "d.ckpt", {"epoch": 0})) == 1
    assert srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "e.ckpt", {"epoch": 300})) == 301   # BININT2 도 읽는다

def test_done_epochs_from_ckpt_rejects_bad_input(tmp_path):
    assert srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "n.ckpt", {"global_step": 5})) is None          # epoch 없음
    assert srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "s.ckpt", {"epoch": "x"})) is None              # 정수가 아님
    assert srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "r.ckpt", {"epoch": 100000})) is None           # 범위 밖
    assert srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "g.ckpt", raw=b"not a pickle at all")) is None
    assert srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "m.ckpt", {"epoch": 1}, member="archive/other.pkl")) is None
    (tmp_path / "plain.ckpt").write_bytes(b"x" * 100)
    assert srv.done_epochs_from_ckpt(tmp_path / "plain.ckpt") is None                                      # zip 아님
    assert srv.done_epochs_from_ckpt(tmp_path / "missing.ckpt") is None
    big = pickle.dumps({"blob": b"0" * (srv.MAX_PKL_BYTES + 10), "epoch": 3}, protocol=2)
    assert srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "big.ckpt", raw=big)) is None                    # 8 MiB 초과
    odd = _ckpt_zip(tmp_path / "bz.ckpt", {"epoch": 3}, compression=zipfile.ZIP_BZIP2)
    assert srv.done_epochs_from_ckpt(odd) is None                                                          # 허용 압축 방식 밖

def test_done_epochs_never_executes_pickle(tmp_path):
    class Boom:
        def __reduce__(self):
            return (os.system, ("touch " + str(tmp_path / "pwned"),))
    raw = pickle.dumps({"x": Boom(), "epoch": 4}, protocol=2)
    srv.done_epochs_from_ckpt(_ckpt_zip(tmp_path / "evil.ckpt", raw=raw))
    assert not (tmp_path / "pwned").exists()

def test_pick_last_ckpt(tmp_path):
    for n, m in (("last-v1.ckpt", 100), ("last-v2.ckpt", 200), ("last-v10.ckpt", 150), ("last-x.ckpt", 999), ("best-epoch=1.ckpt", 999)):
        (tmp_path / n).write_text("x"); os.utime(tmp_path / n, (m, m))
    names = os.listdir(tmp_path)
    assert srv.pick_last_ckpt(str(tmp_path), names) == str(tmp_path / "last-v2.ckpt")          # last.ckpt 가 없으면 가장 새 last-v<N>
    (tmp_path / "last.ckpt").write_text("x"); os.utime(tmp_path / "last.ckpt", (1, 1))
    assert srv.pick_last_ckpt(str(tmp_path), os.listdir(tmp_path)) == str(tmp_path / "last.ckpt")   # 있으면 오래돼도 last.ckpt
    assert srv.pick_last_ckpt(str(tmp_path), ["best-epoch=1.ckpt"]) is None
    assert srv.pick_last_ckpt(None, ["last.ckpt"]) is None

def test_read_run_reads_done_from_last_ckpt(tmp_path, monkeypatch):
    ck = tmp_path / "checkpoints"; ck.mkdir()
    _ckpt_zip(ck / "last.ckpt", {"epoch": 16, "global_step": 4777})
    (ck / "best-epoch=0014-v=-0.2.ckpt").write_text("x")
    monkeypatch.setattr(srv, "_ckpt_folder", lambda pid, mounts: (str(ck), os.listdir(ck)))
    monkeypatch.setattr(srv, "_fd_dirs", lambda pid, mounts: [])               # 실제 /proc/1/fd 에 기대지 않는다
    monkeypatch.setattr(srv, "_read_proc", lambda pid, name, limit: "")
    r = srv.read_run(1, [])
    assert r["done"] == 17 and r["metric"] == "v" and r["last"] is True

# ── 진행 파일 규약(개정 18, 2026-10-22 사용자 결정): 판 폴더의 band_progress.json {"done", "max"} ──
LOCAL = [("/", "ext4")]

def test_read_progress_valid_and_checkpoints_subfolder(tmp_path):
    (tmp_path / "band_progress.json").write_text(json.dumps({"done": 9, "max": 13}))
    assert srv.read_progress([str(tmp_path)], LOCAL) == (9, 13, None)
    sub = tmp_path / "b"; (sub / "checkpoints").mkdir(parents=True)
    (sub / "checkpoints" / "band_progress.json").write_text('{"done": 0, "max": 60}')
    assert srv.read_progress([str(sub)], LOCAL) == (0, 60, None)

def test_read_progress_rejects_bad_files(tmp_path):
    cases = {
        "a": '{"done": 14, "max": 13}',           # done > max
        "b": '{"done": true, "max": 13}',          # 불은 정수가 아니다
        "c": '{"done": 1.5, "max": 13}',
        "d": '{"done": 1, "max": 0}',
        "e": '{"done": 1, "max": 100001}',
        "f": '[1, 2]',
        "g": 'not json',
        "h": json.dumps({"done": 1, "max": 2, "pad": "x" * 5000}),   # 4 KiB 초과
        "i": "[" * 2000 + "]" * 2000,                                  # 깊은 중첩: 수집기가 죽지 않는다
        "j": '{"a":' + "[" * 2000 + "]" * 2000 + "}",                  # «{» 로 시작, 4 KiB 안, 중첩 2001단(RecursionError 경로)
    }
    for k, body in cases.items():
        d = tmp_path / k; d.mkdir(); (d / "band_progress.json").write_text(body)
        assert srv.read_progress([str(d)], LOCAL) is None, k
    real = tmp_path / "real.json"; real.write_text('{"done": 1, "max": 2}')
    ln = tmp_path / "ln"; ln.mkdir(); (ln / "band_progress.json").symlink_to(real)
    assert srv.read_progress([str(ln)], LOCAL) is None                       # 심볼릭 링크는 따르지 않는다
    fifo = tmp_path / "fifo"; fifo.mkdir(); os.mkfifo(fifo / "band_progress.json")
    assert srv.read_progress([str(fifo)], LOCAL) is None                     # FIFO 에서 멈추지 않는다
    ok = tmp_path / "ok"; ok.mkdir(); (ok / "band_progress.json").write_text('{"done": 3, "max": 5}')
    assert srv.read_progress([str(ok)], [(str(tmp_path), "nfs4"), ("/", "ext4")]) is None   # 원격 FS 는 건드리지 않는다
    assert srv.read_progress([str(ok)], None) is None

def test_read_progress_rejects_other_users_file(tmp_path, monkeypatch):
    (tmp_path / "band_progress.json").write_text('{"done": 3, "max": 5}')
    assert srv.read_progress([str(tmp_path)], LOCAL) == (3, 5, None)
    monkeypatch.setattr(os, "getuid", lambda: os.stat(tmp_path).st_uid + 1)   # 파일 소유자가 이 사용자가 아니면
    assert srv.read_progress([str(tmp_path)], LOCAL) is None

def test_arg_dirs_dotdot_cannot_escape_into_remote(tmp_path):
    remote = tmp_path / "mnt" / "nfs" / "run"; remote.mkdir(parents=True)
    (remote / "spec.json").write_text("{}")
    a = str(tmp_path / "home" / "x") + "/../../mnt/nfs/run/spec.json"
    (tmp_path / "home" / "x").mkdir(parents=True)
    assert srv._arg_dirs([a], [(str(tmp_path / "mnt" / "nfs"), "nfs4"), ("/", "ext4")]) == []
    assert srv._arg_dirs([a], LOCAL) == [str(remote)]                          # 로컬이면 .. 를 풀어 실제 폴더를 쓴다

def test_progress_never_follows_folder_links_into_remote(tmp_path, monkeypatch):
    remote = tmp_path / "nfsmnt"; remote.mkdir()
    (remote / "band_progress.json").write_text('{"done": 1, "max": 2}')
    run = tmp_path / "run"; run.mkdir()
    (run / "checkpoints").symlink_to(remote)                                   # run/checkpoints → 원격
    spec_dir = tmp_path / "specs"; spec_dir.symlink_to(remote)                 # 인자 경로 중간 링크 → 원격
    mounts = [(str(remote), "nfs4"), ("/", "ext4")]
    touched = []
    real_lstat, real_open = os.lstat, os.open
    def guard_lstat(p, *a, **k):
        if str(p).startswith(str(remote)):
            touched.append(p)
        return real_lstat(p, *a, **k)
    def guard_open(p, *a, **k):
        if str(p).startswith(str(remote)):
            touched.append(p)
        return real_open(p, *a, **k)
    monkeypatch.setattr(os, "lstat", guard_lstat)
    monkeypatch.setattr(os, "open", guard_open)
    assert srv.read_progress([str(run)], mounts) is None
    assert srv._arg_dirs([str(spec_dir / "band_progress.json")], mounts) == []
    assert touched == []                                                       # 원격 쪽은 stat·open 하지 않는다
    local = tmp_path / "local"; local.mkdir(); (local / "band_progress.json").write_text('{"done": 4, "max": 9}')
    run2 = tmp_path / "run2"; run2.mkdir(); (run2 / "checkpoints").symlink_to(local)
    assert srv.read_progress([str(run2)], mounts) == (4, 9, None)                    # 로컬로 가는 폴더 링크는 따라간다

def test_arg_dirs_only_absolute_local_files(tmp_path):
    spec = tmp_path / "run" / "spec.json"; spec.parent.mkdir(); spec.write_text("{}")
    link = tmp_path / "link.json"; link.symlink_to(spec)
    args = ["/usr/bin/python", "train.py", str(spec), str(tmp_path / "missing.json"), str(link), str(tmp_path), "--lr=0.1"]
    got = srv._arg_dirs(args, LOCAL)
    assert str(spec.parent) in got and str(tmp_path) not in got            # 링크·폴더 인자·없는 파일은 빼고 파일 인자 폴더만
    assert srv._arg_dirs([str(spec)], [(str(tmp_path), "nfs"), ("/", "ext4")]) == []

def test_read_run_prefers_progress_file_from_arg_folder(tmp_path, monkeypatch):
    run = tmp_path / "run-g5"; run.mkdir()
    (run / "spec.json").write_text("{}")
    (run / "band_progress.json").write_text('{"done": 9, "max": 13}')
    monkeypatch.setattr(srv, "_read_proc", lambda pid, name, limit: ("python\0rev6_heads.py\0" + str(run / "spec.json") + "\0max_epochs=60") if name == "cmdline" else "")
    monkeypatch.setattr(srv, "_ckpt_folder", lambda pid, mounts: (None, []))
    monkeypatch.setattr(srv, "_fd_dirs", lambda pid, mounts: [])
    r = srv.read_run(1, LOCAL)
    assert (r["done"], r["max_epochs"]) == (9, 13)                           # 진행 파일이 명령줄 max_epochs=60 보다 앞선다
    (run / "band_progress.json").unlink()
    r = srv.read_run(1, LOCAL)
    assert (r["done"], r["max_epochs"]) == (None, 60)                        # 없으면 종전대로

# ── last 칸(개정 19, 2026-10-22 사용자 결정 «둘 다»): 진행 파일 last(bool) → 없으면 last.ckpt 이름 · last.pth ──
def test_read_progress_last_key(tmp_path):
    for body, want in (('{"done": 1, "max": 2, "last": true}', True), ('{"done": 1, "max": 2, "last": false}', False),
                       ('{"done": 1, "max": 2, "last": "yes"}', None), ('{"done": 1, "max": 2, "last": 1}', None),
                       ('{"done": 1, "max": 2}', None)):
        (tmp_path / "band_progress.json").write_text(body)
        assert srv.read_progress([str(tmp_path)], LOCAL) == (1, 2, want), body

def test_has_last_pth(tmp_path):
    run = tmp_path / "run"; run.mkdir()
    assert srv.has_last_pth([str(run)], LOCAL) is False
    (run / "last.pth").write_bytes(b"x")
    assert srv.has_last_pth([str(run)], LOCAL) is True
    sub = tmp_path / "sub"; (sub / "checkpoints").mkdir(parents=True); (sub / "checkpoints" / "last.pth").write_bytes(b"x")
    assert srv.has_last_pth([str(sub)], LOCAL) is True
    ln = tmp_path / "ln"; ln.mkdir(); (ln / "last.pth").symlink_to(run / "last.pth")
    assert srv.has_last_pth([str(ln)], LOCAL) is False                        # 링크는 last 로 치지 않는다
    dirp = tmp_path / "dirp"; (dirp / "last.pth").mkdir(parents=True)
    assert srv.has_last_pth([str(dirp)], LOCAL) is False                      # 폴더는 아니다
    assert srv.has_last_pth([str(run)], [(str(tmp_path), "nfs4"), ("/", "ext4")]) is False   # 원격은 보지 않는다

def test_has_last_pth_rejects_other_users_file(tmp_path, monkeypatch):
    (tmp_path / "last.pth").write_bytes(b"x")
    monkeypatch.setattr(os, "getuid", lambda: os.stat(tmp_path).st_uid + 1)
    assert srv.has_last_pth([str(tmp_path)], LOCAL) is False

def test_collect_train_merge_keeps_last_true(monkeypatch):
    runs = {1: {"name": "r", "max_epochs": 13, "done": 9, "metric": None, "ckpts": [], "last": True, "runner_pid": None},
            2: {"name": "r", "max_epochs": 13, "done": 9, "metric": None, "ckpts": [], "last": False, "runner_pid": None}}
    monkeypatch.setattr(srv, "run", lambda argv, timeout=3: "1, U0\n2, U0\n" if "--query-compute-apps=pid,gpu_uuid" in argv else "5, U0\n")
    monkeypatch.setattr(srv, "read_run", lambda pid, mounts: dict(runs[pid]))
    monkeypatch.setattr(srv, "read_mounts", lambda: [("/", "ext4")])
    monkeypatch.setattr(srv, "read_watcher_pids", lambda: set())
    out = srv.collect_train()
    assert len(out) == 1 and out[0]["last"] is True                           # DDP 뒤 프로세스의 False 가 앞의 True 를 덮지 않는다

def _run_with(monkeypatch, run, files):
    for name, body in files.items():
        (run / name).write_bytes(body if isinstance(body, bytes) else body.encode())
    monkeypatch.setattr(srv, "_read_proc", lambda pid, name, limit: ("python\0head_runner.py\0" + str(run / "spec.json")) if name == "cmdline" else "")
    monkeypatch.setattr(srv, "_ckpt_folder", lambda pid, mounts: (None, []))
    monkeypatch.setattr(srv, "_fd_dirs", lambda pid, mounts: [])
    return srv.read_run(1, LOCAL)

def test_read_run_last_from_pth_and_progress_key(tmp_path, monkeypatch):
    run = tmp_path / "r1"; run.mkdir()
    r = _run_with(monkeypatch, run, {"spec.json": "{}", "last.pth": b"x", "band_progress.json": '{"done": 9, "max": 13}'})
    assert r["last"] is True and (r["done"], r["max_epochs"]) == (9, 13)        # 키 없음 → last.pth 로 판정
    run2 = tmp_path / "r2"; run2.mkdir()
    r = _run_with(monkeypatch, run2, {"spec.json": "{}", "last.pth": b"x", "band_progress.json": '{"done": 9, "max": 13, "last": false}'})
    assert r["last"] is False                                                  # 키가 있으면 키가 이긴다
    run3 = tmp_path / "r3"; run3.mkdir()
    r = _run_with(monkeypatch, run3, {"spec.json": "{}", "band_progress.json": '{"done": 1, "max": 2, "last": true}'})
    assert r["last"] is True                                                   # 파일 없이 키만으로
    run4 = tmp_path / "r4"; run4.mkdir()
    r = _run_with(monkeypatch, run4, {"spec.json": "{}"})
    assert r["last"] is False                                                  # 아무것도 없으면 «last 없음»

def test_collect_skips_train_queries_when_gpu_query_fails(monkeypatch, tmp_path):
    calls = []
    def fake(argv, timeout=3):
        calls.append(argv[1] if argv[0] == "nvidia-smi" else argv[0])
    monkeypatch.setattr(srv, "run", fake)
    monkeypatch.setattr(srv, "nvidia_smi_stuck", lambda limit=10: False)
    monkeypatch.setattr(srv, "CACHE_DIR", tmp_path)
    (tmp_path / "server.json").write_text(json.dumps({"ts": 1, "gpus": [{"i": 1}], "gpus_ts": time.time() - 20,
                                                      "train": [{"gpu": 1}], "train_ts": time.time() - 20}))
    out = srv.collect()
    assert [c for c in calls if c.startswith("--query")] == ["--query-gpu=index,utilization.gpu,memory.used,memory.total"]
    assert out["gpus"] == [{"i": 1}] and out["train"] == [{"gpu": 1}]

def test_collect_carries_recent_train_when_stuck(monkeypatch, tmp_path):
    calls = _gpu_env(monkeypatch, tmp_path, 15.0)
    (tmp_path / "server.json").write_text(json.dumps({"ts": time.time() - 30, "gpus": [], "train": [{"gpu": 1}], "train_ts": time.time() - 30}))
    assert srv.collect()["train"] == [{"gpu": 1}] and "nvidia-smi" not in calls
    (tmp_path / "server.json").write_text(json.dumps({"ts": 1, "gpus": [], "train": [{"gpu": 1}], "train_ts": time.time() - 90}))
    assert srv.collect()["train"] is None


# ---- 와쳐 · 세션 작업(개정 11, 2026-10-16) ----
def test_runner_pid_from_cgroup():
    assert srv.runner_pid_from_cgroup("0::/user.slice/memguard-exp-r72-2731642.scope\n") == 2731642
    assert srv.runner_pid_from_cgroup("0::/user.slice/session-3.scope\n") is None
    assert srv.runner_pid_from_cgroup("0::/memguard-bad name;x-12.scope") is None
    assert srv.runner_pid_from_cgroup(None) is None

def test_watcher_pids_from_cmdline():
    w = "/home/u/.claude/tools/train-watcher/train-watcher.sh"
    assert srv.watcher_pids_from_cmdline(["bash", w, "--pid", "2731642", "--log", "/x"]) == [2731642]
    assert srv.watcher_pids_from_cmdline(["bash", w, "--pid=2731642"]) == []                  # 등호 꼴은 와쳐가 받지 않는다
    assert srv.watcher_pids_from_cmdline(["bash", w, "--pid", "12a"]) == []                    # 숫자 아님
    assert srv.watcher_pids_from_cmdline(["bash", w, "--pid", "-5"]) == []
    assert srv.watcher_pids_from_cmdline(["bash", w, "--pid", "1" * 11]) == []                 # 자릿수 상한
    assert srv.watcher_pids_from_cmdline(["bash", "other.sh", "--pid", "7"]) == []             # 와쳐 스크립트가 아님
    assert srv.watcher_pids_from_cmdline(["zsh", "-c", "x train-watcher.sh --pid 7"]) == []    # 긴 문자열 한 덩어리는 아님
    assert srv.watcher_pids_from_cmdline(["bash", "--pid", "9", w]) == []                      # 스크립트 앞의 인자는 무시
    assert srv.watcher_pids_from_cmdline([]) == []

def test_collect_train_watcher_three_values(monkeypatch):
    out = {"--query-compute-apps=pid,gpu_uuid": "11, U3\n12, U4\n13, U5\n", "--query-gpu=index,uuid": "3, U3\n4, U4\n5, U5\n"}
    monkeypatch.setattr(srv, "run", lambda argv, timeout=3: out[argv[1]])
    base = {"max_epochs": None, "done": None, "metric": None, "ckpts": [], "last": False}
    runs = {11: {**base, "name": "a", "runner_pid": 100}, 12: {**base, "name": "b", "runner_pid": 200}, 13: {**base, "name": "c", "runner_pid": None}}
    monkeypatch.setattr(srv, "read_mounts", list)
    monkeypatch.setattr(srv, "read_watcher_pids", lambda: {100})
    monkeypatch.setattr(srv, "read_run", lambda pid, mounts: dict(runs[pid]))
    got = srv.collect_train()
    assert [(r["name"], r["watcher"]) for r in got] == [("a", True), ("b", False), ("c", None)]
    assert all("runner_pid" not in r for r in got)                                              # 러너 pid 는 캐시에 쓰지 않는다

def test_read_watcher_pids_only_own_user_processes(monkeypatch):
    w = "/t/train-watcher.sh"
    procs = {"10": ("--pid\0" + "77", os.getuid()), "11": ("--pid\0" + "88", os.getuid() + 1), "x": ("", 0)}
    monkeypatch.setattr(srv.os, "listdir", lambda p: list(procs))
    monkeypatch.setattr(srv.os, "stat", lambda p: type("S", (), {"st_uid": procs[str(p).split("/")[2]][1]})())
    monkeypatch.setattr(srv, "_read_proc", lambda pid, name, limit: "bash\0" + w + "\0" + procs[pid][0])
    assert srv.read_watcher_pids() == {77}                                                      # 다른 사용자(11)는 건너뜀

JOB_ID = "0c7530cd"

def test_job_fields_keeps_only_state_and_detail():
    obj = {"state": "working", "detail": "추론 결과 확인", "intent": "SECRET", "bridgeOwnerAccountUuid": "u", "sessionId": "s"}
    got = srv.job_fields(obj)
    assert got == {"job_state": "working", "job_detail": "추론 결과 확인"}
    assert "SECRET" not in json.dumps(got) and "bridge" not in json.dumps(got)

def test_job_fields_cleans_and_truncates():
    got = srv.job_fields({"state": "needs_input", "detail": "a\x1b]0;x\x07b\nc" + "z" * 200})
    assert got["job_detail"].startswith("a]0;xb c") and len(got["job_detail"]) == 120 and "\x1b" not in got["job_detail"]
    assert srv.job_fields({"state": "Working!", "detail": 5}) == {"job_state": None, "job_detail": None}
    assert srv.job_fields({"state": "x" * 21})["job_state"] is None
    assert srv.job_fields({"detail": "  "})["job_detail"] is None
    assert srv.job_fields([1]) == {"job_state": None, "job_detail": None}

def _job(tmp_path, job_id=JOB_ID, body=None):
    d = tmp_path / "jobs" / job_id; d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps(body or {"state": "working", "detail": "d", "intent": "SECRET"}))
    return tmp_path / "jobs"

def test_read_job_state_rejects_bad_ids_symlinks_and_size(tmp_path):
    jobs = _job(tmp_path)
    assert srv.read_job_state(jobs, JOB_ID) == {"job_state": "working", "job_detail": "d"}
    none = {"job_state": None, "job_detail": None}
    for bad in ("../x", "0C7530CD", "0c7530c", "0c7530cdd", "0c7530cd\n", None, 5):
        assert srv.read_job_state(jobs, bad) == none
    real = tmp_path / "real.json"; real.write_text(json.dumps({"state": "working"}))
    d2 = jobs / "aaaaaaaa"; d2.mkdir(); os.symlink(real, d2 / "state.json")                    # state.json 이 링크
    assert srv.read_job_state(jobs, "aaaaaaaa") == none
    os.symlink(jobs / JOB_ID, jobs / "bbbbbbbb")                                                # 작업 폴더가 링크
    assert srv.read_job_state(jobs, "bbbbbbbb") == none
    d3 = jobs / "cccccccc"; d3.mkdir(); (d3 / "state.json").write_text(json.dumps({"state": "working", "pad": "x" * 70000}))
    assert srv.read_job_state(jobs, "cccccccc") == none                                         # 64KB 초과
    d4 = jobs / "dddddddd"; d4.mkdir(); (d4 / "state.json").write_text("{not json")
    assert srv.read_job_state(jobs, "dddddddd") == none
    assert srv.read_job_state(jobs, "eeeeeeee") == none                                         # 없는 작업

def test_read_sessions_attaches_job_state(tmp_path):
    jobs = _job(tmp_path)
    sid = "0c7530cd-4cc9-47a1-9df0-ab9103f6e70d"
    sess = tmp_path / "sess"; sess.mkdir()
    (sess / "1.json").write_text(json.dumps({"pid": 1, "sessionId": sid, "name": "n", "status": "shell", "jobId": JOB_ID}))
    (sess / "2.json").write_text(json.dumps({"pid": 2, "sessionId": sid, "name": "m", "status": "idle", "jobId": "../../etc"}))
    got = srv.read_sessions(sess, alive=lambda pid: True, jobs_dir=jobs)
    assert got == [{"sid": sid, "name": "n", "status": "shell", "job": JOB_ID, "job_state": "working", "job_detail": "d"},
                   {"sid": sid, "name": "m", "status": "idle", "job": None, "job_state": None, "job_detail": None}]
    assert "SECRET" not in json.dumps(got)                                                      # intent 등 다른 키는 캐시로 가지 않는다


# ---- 개정 14: 디스크 장치별 목록 ----
GIB = 1 << 30
DF_HEAD = "Filesystem 1-blocks Used Available Capacity Mounted on\n"

def _sys_block(root, rot):
    """rot: {디스크 이름: '0'|'1'} 로 /sys/block/<이름>/queue/rotational 흉내."""
    for name, v in rot.items():
        q = root / name / "queue"; q.mkdir(parents=True)
        (q / "rotational").write_text(v + "\n")
    return root

def test_parse_disks_classifies_sorts_and_drops_small(tmp_path):
    sysb = _sys_block(tmp_path, {"sda": "0", "sdd": "0", "sdb": "1", "sdc": "1", "nvme0n1": "0"})
    df = DF_HEAD + (
        f"/dev/sdc {4000 * GIB} {1000 * GIB} {3000 * GIB} 25% /mnt/Data1\n"
        f"/dev/sda2 {900 * GIB} {800 * GIB} {100 * GIB} 89% /\n"
        f"/dev/sda1 {512 << 20} 1 {500 << 20} 1% /boot/efi\n"                  # 2 GiB 미만 -> 제외
        f"/dev/sdb {4000 * GIB} {1000 * GIB} {3000 * GIB} 25% /mnt/Data0\n"
        f"/dev/sdd {3600 * GIB} {2700 * GIB} {903 * GIB} 75% /mnt/ssd\n"
        f"/dev/nvme0n1p2 {500 * GIB} {100 * GIB} {400 * GIB} 20% /mnt/nv\n"   # 파티션 -> nvme0n1
        f"/dev/sde {100 * GIB} {1 * GIB} {99 * GIB} 1% /mnt/unknown\n"         # sys 정보 없음 -> ?
        f"tmpfs {10 * GIB} 0 {10 * GIB} 0% /run\n")                            # /dev/ 아님 -> 제외
    got = srv.parse_disks(df, sysb)
    assert [(d["dev"], d["kind"], d["mount"]) for d in got] == [
        ("nvme0n1p2", "SSD", "/mnt/nv"), ("sda2", "SSD", "/"), ("sdd", "SSD", "/mnt/ssd"),
        ("sdb", "HDD", "/mnt/Data0"), ("sdc", "HDD", "/mnt/Data1"), ("sde", "?", "/mnt/unknown")]
    assert got[2]["total"] == 3600 * GIB and got[2]["avail"] == 903 * GIB

def test_parse_disks_cap_dedup_and_clean(tmp_path):
    sysb = _sys_block(tmp_path, {"sdz": "0"})
    rows = "".join(f"/dev/sd{c} {10 * GIB} 1 {5 * GIB} 1% /m{c}\n" for c in "abcdefghij")           # 10장치 -> 8 상한
    assert len(srv.parse_disks(DF_HEAD + rows, sysb)) == 8
    df = DF_HEAD + (f"/dev/sdz {10 * GIB} 1 {5 * GIB} 1% /a b\x1b]0;x\x07\n"                       # 마운트에 공백·제어문자
                    f"/dev/sdz {10 * GIB} 1 {5 * GIB} 1% /dup\n")                                  # 같은 장치 중복 -> 첫 줄만
    got = srv.parse_disks(df, sysb)
    assert len(got) == 1 and got[0]["mount"] == "/a b]0;x"

def test_parse_disks_failure_is_none_and_no_dev_is_empty(tmp_path):
    assert srv.parse_disks(None, tmp_path) is None
    assert srv.parse_disks("", tmp_path) is None
    assert srv.parse_disks(DF_HEAD + f"tmpfs {10 * GIB} 0 {10 * GIB} 0% /run\n", tmp_path) == []

def test_disk_kind_partition_names(tmp_path):
    sysb = _sys_block(tmp_path, {"sda": "1", "nvme0n1": "0", "mmcblk0": "0"})
    assert srv.disk_kind("sda2", sysb) == "HDD" and srv.disk_kind("sda", sysb) == "HDD"
    assert srv.disk_kind("nvme0n1p2", sysb) == "SSD" and srv.disk_kind("mmcblk0p1", sysb) == "SSD"
    assert srv.disk_kind("vg-root", sysb) == "?" and srv.disk_kind("sdq1", sysb) == "?"
    (sysb / "sdx" / "queue").mkdir(parents=True)
    (sysb / "sdx" / "queue" / "rotational").write_text("junk")
    assert srv.disk_kind("sdx", sysb) == "?"                                                         # 0·1 이 아니면 ?

def test_collect_has_disks_key_and_keeps_root_disk(monkeypatch, tmp_path):
    _gpu_env(monkeypatch, tmp_path, 2.0)
    seen = []
    base = srv.run
    def fake(argv, timeout=3):
        seen.append(argv)
        return DF if argv[:2] == ["df", "-B1"] and argv[-1] == "/" else base(argv, timeout)
    monkeypatch.setattr(srv, "run", fake)
    out = srv.collect()
    assert out["disk"] == {"total": 943804760064, "avail": 129922662400}                              # 접힌 띠용 루트 디스크는 그대로
    assert "disks" in out and any(a[:2] == ["df", "-B1"] and "-x" in a for a in seen)


# ---- 개정 22(2026-10-23): 할 일 개수·진행/남은 제목 ----
def _task(folder, n, status, subject):
    (folder / f"{n}.json").write_text(json.dumps({"id": str(n), "subject": subject, "status": status, "blocks": [], "blockedBy": []}))

def test_todos_counts_and_items(tmp_path):
    sid = "0c7530cd-4cc9-47a1-9df0-ab9103f6e70d"
    f = tmp_path / "session-0c7530cd"; f.mkdir()
    for i in range(1, 33):
        _task(f, i, "completed", f"done {i}")
    _task(f, 33, "pending", "open a")
    _task(f, 34, "in_progress", "doing a")
    _task(f, 35, "pending", "open b" + chr(0x202E) + chr(0x200B) + chr(0x1B) + "!")
    _task(f, 36, "in_progress", "doing b")
    (f / ".lock").write_text("")
    (f / "37.json").write_text("{bad")
    _task(f, 38, "deleted", "unknown state")
    got = wrk.todos(sid, tmp_path)
    assert (got["done"], got["doing"], got["open"]) == (32, 2, 2)
    assert [x["subject"] for x in got["items"]] == ["doing a", "doing b", "open a", "open b!"]   # 진행 먼저, 번호 순, 정화
    assert [x["state"] for x in got["items"]] == ["doing", "doing", "open", "open"]

def test_todos_none_without_folder_or_bad_sid(tmp_path):
    assert wrk.todos("0c7530cd-4cc9-47a1-9df0-ab9103f6e70d", tmp_path) is None
    assert wrk.todos("../etc", tmp_path) is None
    assert wrk.todos(None, tmp_path) is None

def test_todos_skips_symlink_and_oversize(tmp_path):
    sid = "0c7530cd-4cc9-47a1-9df0-ab9103f6e70d"
    f = tmp_path / "session-0c7530cd"; f.mkdir()
    real = tmp_path / "real.json"; real.write_text(json.dumps({"status": "pending", "subject": "link"}))
    (f / "1.json").symlink_to(real)
    (f / "2.json").write_text(json.dumps({"status": "pending", "subject": "x" * 70000}))
    _task(f, 3, "pending", "ok")
    got = wrk.todos(sid, tmp_path)
    assert got["open"] == 1 and [x["subject"] for x in got["items"]] == ["ok"]


def test_todos_doing_kept_when_many_open_before_it(tmp_path):
    sid = "0c7530cd-4cc9-47a1-9df0-ab9103f6e70d"
    f = tmp_path / "session-0c7530cd"; f.mkdir()
    for i in range(1, 14):
        _task(f, i, "pending", f"open {i}")
    _task(f, 14, "in_progress", "late doing")
    (f / "15.json").write_text(json.dumps({"status": ["pending"], "subject": "list status"}))
    (f / "16.json").write_text("[" * 100000 + "]" * 100000)
    got = wrk.todos(sid, tmp_path)
    assert (got["doing"], got["open"]) == (1, 13)
    assert got["items"][0] == {"state": "doing", "subject": "late doing"}      # 앞 번호의 남은 항목이 많아도 진행 항목이 첫 줄(qa 2026-10-23)
    assert len(got["items"]) == wrk.MAX_TODO_ITEMS

def test_strip_ranges_match_band_model():
    src = (pathlib.Path(__file__).resolve().parents[2] / "mods/harness-mod/hooks/band/model.js").read_text(encoding="utf-8")
    import re as _re
    block = _re.search(r"export const STRIP_RANGES = \[(.*?)\]\n", src, _re.DOTALL).group(1)
    js = sorted((int(a, 16), int(b, 16)) for a, b in _re.findall(r"\[0x([0-9a-f]+), 0x([0-9a-f]+)\]", block))
    assert js == sorted(wrk._STRIP_RANGES)                                      # 수집기와 띠의 정화 집합이 같다(security 2026-10-23)
    hidden = "".join(chr(c) for c in (0xAD, 0x2061, 0x206A, 0xFE0F, 0xE0041, 0x3164))
    assert wrk.strip_text("a" + hidden + "b") == "ab"
