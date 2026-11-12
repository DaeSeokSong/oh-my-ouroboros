"""ntfy-flush.sh 와 claude-notify.sh 큐 배송 전용 모드 회귀 테스트 (2026-10-01 신설).

실제 네트워크·실제 ~/.claude 를 쓰지 않는다: HOME 을 임시 폴더로 바꾸고 PATH 앞에 가짜 curl 을 둔다.
실행: python3 scripts/tests/test_ntfy_flush.py (pytest 로도 수집된다).
"""

import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
NOTIFY = SCRIPTS / "claude-notify.sh"
FLUSH = SCRIPTS / "ntfy-flush.sh"
DAY = "20261001"


def make_root(tmp):
    """가짜 curl 이 든 임시 HOME 과 그 환경을 돌려준다."""
    root = Path(tmp)
    bindir = root / "bin"
    bindir.mkdir()
    fake = bindir / "curl"
    fake.write_text(
        '#!/bin/bash\n'
        'out=""; data=""\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  case "$1" in\n'
        '    -o) out="$2"; shift 2 ;;\n'
        '    -K) cfg=$(cat); shift 2 ;;\n'
        '    -w|--max-time) shift 2 ;;\n'
        '    *) shift ;;\n'
        '  esac\n'
        'done\n'
        # 본문은 표준입력 설정(-K -)의 data-raw 줄에서 꺼낸다(인자에는 없다)
        'data=$(printf "%s\\n" "$cfg" | sed -n \'s/^data-raw = "\\(.*\\)"$/\\1/p\' | sed \'s/\\\\\\(.\\)/\\1/g\')\n'
        'sleep "${FAKE_CURL_SLEEP:-0}"\n'
        'printf "%s\\n" "$data" >> "$FAKE_CURL_DATA"\n'
        'printf "%s" "${FAKE_CURL_BODY:-{\\}}" > "$out"\n'
        'printf "%s 0.001" "${FAKE_CURL_HTTP:-200}"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = dict(os.environ)
    for key in ("CLAUDE_HOME", "CLAUDE_NOTIFY_DRYRUN", "CLAUDE_NOTIFY_SKIP",
                "CODE_EARN_BACKGROUND_CHILD", "CLAUDE_JOB_DIR", "NTFY_DAILY_CAP",
                "NTFY_RESERVE", "NTFY_FLUSH_MAX", "CLAUDE_NOTIFY_FLUSH_ONLY",
                "USER_NTFY_TOPIC", "TMUX", "DISPLAY"):
        env.pop(key, None)
    env.update({
        "HOME": str(root),
        "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""),
        "NTFY_DAY": DAY,
        "FAKE_CURL_DATA": str(root / "curl-data"),
    })
    (root / ".claude" / "_usage").mkdir(parents=True)
    return root, env


def with_topic(env):
    return dict(env, USER_NTFY_TOPIC="test-topic")


def queue_path(root):
    return root / ".claude" / "_usage" / "ntfy-queue.tsv"


def add_queue(root, msg, kind="final", ts="2026-09-30T00:00:00Z", tries=0):
    prio = {"permission": "default", "needs_input": "high"}.get(kind, "default")
    row = "\t".join((ts, "s", kind, prio, "tag", "[t: P]", msg, str(tries)))
    with queue_path(root).open("a", encoding="utf-8") as out:
        out.write(row + "\n")


def queue_msgs(root):
    path = queue_path(root)
    if not path.exists():
        return []
    return [line.split("\t")[6] for line in path.read_text(encoding="utf-8").splitlines() if line]


def sent_msgs(root):
    path = root / "curl-data"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def send_log(root):
    return root / ".claude" / "_audit" / "ntfy-send.tsv"


def run_flush(env):
    return subprocess.run(["bash", str(FLUSH)], check=False, env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=90)


def test_flush_only_sends_one_without_current_or_bell():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        env = with_topic(dict(env, CLAUDE_NOTIFY_FLUSH_ONLY="1"))
        for i in range(3):
            add_queue(root, f"m{i}", ts=f"2026-09-30T00:00:0{i}Z")
        # 열린 채 비어 있는 표준입력: 읽으려 들면 timeout 2 로 2초가 걸린다.
        proc = subprocess.Popen(["bash", str(NOTIFY), "Proj", "현재 알림"], env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, cwd="/")
        started = time.monotonic()
        out, _ = proc.communicate(timeout=20)
        elapsed = time.monotonic() - started
        assert proc.returncode == 0
        assert elapsed < 1.8, elapsed
        assert "\a" not in out and out == ""
        assert sent_msgs(root) == ["m0"]
        assert queue_msgs(root) == ["m1", "m2"]
        assert "현재 알림" not in "".join(sent_msgs(root)) + "".join(queue_msgs(root))
        rows = send_log(root).read_text(encoding="utf-8").splitlines()
        assert len(rows) == 1 and rows[0].endswith("\tflush_sent"), rows


def test_priority_order_kept():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        add_queue(root, "final-new", "final", "2026-09-30T00:00:09Z")
        add_queue(root, "direct-old", "direct", "2026-09-30T00:00:01Z")
        add_queue(root, "failed", "failed", "2026-09-30T00:00:05Z")
        add_queue(root, "needs", "needs_input", "2026-09-30T00:00:06Z")
        add_queue(root, "perm", "permission", "2026-09-30T00:00:07Z")
        add_queue(root, "final-old", "final", "2026-09-30T00:00:02Z")
        run_flush(with_topic(env))
        assert sent_msgs(root) == ["perm", "needs", "failed", "direct-old", "final-old", "final-new"]
        assert queue_msgs(root) == []


def test_flush_drains_all_and_respects_max():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        for i in range(3):
            add_queue(root, f"m{i}", ts=f"2026-09-30T00:00:0{i}Z")
        r = run_flush(with_topic(env))
        assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
        assert sent_msgs(root) == ["m0", "m1", "m2"] and queue_msgs(root) == []
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        for i in range(3):
            add_queue(root, f"m{i}", ts=f"2026-09-30T00:00:0{i}Z")
        run_flush(with_topic(dict(env, NTFY_FLUSH_MAX="2")))
        assert sent_msgs(root) == ["m0", "m1"] and queue_msgs(root) == ["m2"]


def test_halt_file_blocks_everything():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        add_queue(root, "m0")
        (root / ".claude" / "_usage" / f"ntfy-{DAY}.halt").write_text("")
        r = run_flush(with_topic(env))
        assert r.returncode == 0
        assert sent_msgs(root) == [] and queue_msgs(root) == ["m0"]


def test_http_429_stops_after_one_attempt():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        for i in range(3):
            add_queue(root, f"m{i}", ts=f"2026-09-30T00:00:0{i}Z")
        r = run_flush(with_topic(dict(env, FAKE_CURL_HTTP="429")))
        assert r.returncode == 0
        assert len(sent_msgs(root)) == 1
        assert sorted(queue_msgs(root)) == ["m0", "m1", "m2"]


def test_empty_queue_leaves_no_trace():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        env = with_topic(env)
        assert run_flush(env).returncode == 0
        r = subprocess.run(["bash", str(NOTIFY)], check=False, env=dict(env, CLAUDE_NOTIFY_FLUSH_ONLY="1"),
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, cwd="/")
        assert r.returncode == 0
        assert sent_msgs(root) == [] and not send_log(root).exists()
        queue_path(root).write_text("")
        run_flush(env)
        assert sent_msgs(root) == [] and not send_log(root).exists()


def test_no_topic_changes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        for i in range(2):
            add_queue(root, f"m{i}", ts=f"2026-09-30T00:00:0{i}Z")
        r = run_flush(env)
        assert r.returncode == 0
        assert sent_msgs(root) == [] and queue_msgs(root) == ["m0", "m1"]
        assert not send_log(root).exists()


def test_concurrent_flushers_never_double_send():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        env = with_topic(dict(env, FAKE_CURL_SLEEP="0.3"))
        for i in range(5):
            add_queue(root, f"m{i}", ts=f"2026-09-30T00:00:0{i}Z")
        procs = [subprocess.Popen(["bash", str(FLUSH)], env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(2)]
        for p in procs:
            p.communicate(timeout=90)
            assert p.returncode == 0
        sent = sent_msgs(root)
        assert sorted(sent) == [f"m{i}" for i in range(5)], sent
        assert queue_msgs(root) == []


def queue_rows(root):
    path = queue_path(root)
    if not path.exists():
        return []
    return [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines() if line]


def log_tails(root):
    path = send_log(root)
    return [row.split("\t")[-1] for row in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_outage_does_not_burn_retries():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        for i in range(4):
            add_queue(root, f"m{i}", ts=f"2026-09-30T00:00:0{i}Z")
        down = with_topic(dict(env, FAKE_CURL_HTTP="503", NTFY_FLUSH_BACKOFF_SEC="0"))
        for _ in range(5):
            assert run_flush(down).returncode == 0
        rows = queue_rows(root)
        assert sorted(r[6] for r in rows) == ["m0", "m1", "m2", "m3"]
        assert all(r[7] == "0" for r in rows), rows
        assert sorted(r[0] for r in rows) == [f"2026-09-30T00:00:0{i}Z" for i in range(4)]
        assert "retry_drop" not in log_tails(root)
        before = len(sent_msgs(root))
        run_flush(with_topic(dict(env, NTFY_FLUSH_BACKOFF_SEC="0")))
        assert queue_msgs(root) == [] and len(sent_msgs(root)) == before + 4


def test_backoff_after_stall_and_cleared_on_success():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        for i in range(2):
            add_queue(root, f"m{i}", ts=f"2026-09-30T00:00:0{i}Z")
        backoff = root / ".claude" / "_usage" / "ntfy-flush.backoff"
        run_flush(with_topic(dict(env, FAKE_CURL_HTTP="503")))
        assert len(sent_msgs(root)) == 1 and backoff.exists()
        run_flush(with_topic(dict(env, FAKE_CURL_HTTP="503")))
        assert len(sent_msgs(root)) == 1, "backoff 중에는 curl 호출 0회"
        assert log_tails(root).count("rate_requeue") == 1
        old = time.time() - 301
        os.utime(backoff, (old, old))
        run_flush(with_topic(env))
        assert queue_msgs(root) == [] and not backoff.exists()


def fake_scripts(root, body):
    """ntfy-flush.sh 사본 옆에 가짜 claude-notify.sh 를 둔다(호출 횟수 = calls 파일 줄 수)."""
    scripts = root / "scripts"
    scripts.mkdir()
    shutil.copy(FLUSH, scripts / "ntfy-flush.sh")
    (scripts / "claude-notify.sh").write_text(
        '#!/bin/bash\n'
        'echo x >> "$HOME/calls"\n' + body, encoding="utf-8")
    return scripts / "ntfy-flush.sh"


def fake_calls(root):
    path = root / "calls"
    return len(path.read_text().splitlines()) if path.exists() else 0


def run_fake(script, env):
    return subprocess.run(["bash", str(script)], check=False, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60)


def test_timeout_codes_stop_and_back_off():
    for code in (124, 137):
        with tempfile.TemporaryDirectory() as tmp:
            root, env = make_root(tmp)
            for i in range(3):
                add_queue(root, f"m{i}")
            script = fake_scripts(root, f'sed -i 1d "$HOME/.claude/_usage/ntfy-queue.tsv"\nexit {code}\n')
            run_fake(script, env)
            assert fake_calls(root) == 1, code
            assert (root / ".claude" / "_usage" / "ntfy-flush.backoff").exists()
            run_fake(script, env)
            assert fake_calls(root) == 1, "backoff 중 재호출 금지"


def test_flusher_own_halt_check():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        add_queue(root, "m0")
        script = fake_scripts(root, "exit 0\n")
        halt = root / ".claude" / "_usage" / f"ntfy-{DAY}.halt"
        halt.write_text("")
        run_fake(script, env)
        assert fake_calls(root) == 0
        assert not (root / ".claude" / "_usage" / "ntfy-flush.lock").exists()
        halt.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        for i in range(3):
            add_queue(root, f"m{i}")
        # 첫 호출이 줄을 하나 비우고 halt 를 만든다: 루프 안 검사가 두 번째 호출을 막아야 한다.
        script = fake_scripts(
            root, f'sed -i 1d "$HOME/.claude/_usage/ntfy-queue.tsv"\n: > "$HOME/.claude/_usage/ntfy-{DAY}.halt"\nexit 0\n')
        run_fake(script, env)
        assert fake_calls(root) == 1


def test_flusher_own_lock():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        add_queue(root, "m0")
        script = fake_scripts(root, "exit 0\n")
        with open(root / ".claude" / "_usage" / "ntfy-flush.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run_fake(script, env)
        assert fake_calls(root) == 0


def test_hook_path_keeps_line_during_outage():
    # 2026-10-01 감사 D5: 훅 경로도 배송 전용과 같은 기준(재시도 가능 실패는 tries 미증가)이라
    # 장애 중 훅이 여러 번 실패해도 큐 줄이 버려지지 않는다. 수정 전에는 두 번째 실패에 retry_drop.
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        env = with_topic(dict(env, FAKE_CURL_HTTP="503"))
        add_queue(root, "old", ts="2026-09-30T00:00:00Z")

        def hook():
            return subprocess.run(["bash", str(NOTIFY), "Proj", "현재"], check=False, env=env, cwd="/",
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True)

        for _ in range(4):
            hook()
        assert [r[7] for r in queue_rows(root) if r[6] == "old"] == ["0"]
        assert "retry_drop" not in log_tails(root)
        down_removed = with_topic(dict(env, FAKE_CURL_HTTP="200"))
        subprocess.run(["bash", str(NOTIFY), "Proj", "복구"], check=False, env=down_removed, cwd="/",
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
        assert "old" in sent_msgs(root)


def test_flush_ignores_4xx_discard_as_sent():
    # 2026-10-01 감사 D6: 4xx 로 줄이 폐기돼 큐가 줄어도 «발송»이 아니다(발송 로그에 flush_sent 없음).
    # 수정 전에는 줄 수 감소만 봐서 폐기를 발송으로 세고 backoff 파일을 지웠다.
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        for i in range(2):
            add_queue(root, f"m{i}", ts=f"2026-09-30T00:00:0{i}Z")
        backoff = root / ".claude" / "_usage" / "ntfy-flush.backoff"
        backoff.write_text("")
        old = time.time() - 301
        os.utime(backoff, (old, old))
        run_flush(with_topic(dict(env, FAKE_CURL_HTTP="400")))
        assert queue_msgs(root) == []
        assert "flush_sent" not in log_tails(root)
        assert backoff.exists(), "폐기만 있었으니 backoff 를 지우면 안 된다"


def test_flush_counts_spill_lines():
    # 2026-10-01 감사 D4: 잠금 실패분(.spill)이 큐 파일과 별도라도 배송기가 비우고 합쳐 보낸다.
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        row = "2026-09-30T00:00:00Z\ts\tfinal\tdefault\ttag\t[t: P]\tspilled\t0"
        (root / ".claude" / "_usage" / "ntfy-queue.tsv.spill").write_text(row + "\n", encoding="utf-8")
        run_flush(with_topic(env))
        assert sent_msgs(root) == ["spilled"]
        assert not (root / ".claude" / "_usage" / "ntfy-queue.tsv.spill").exists()


RATE_BODY = '{"code":42908}'


def halt_path(root):
    return root / ".claude" / "_usage" / f"ntfy-{DAY}.halt"


def age_halt(root, seconds):
    """halt 파일을 만들고 수정 시각을 seconds 초 전으로 돌린다."""
    halt = halt_path(root)
    halt.write_text("")
    old = time.time() - seconds
    os.utime(halt, (old, old))
    return halt


def run_hook(env, text="현재"):
    return subprocess.run(["bash", str(NOTIFY), "Proj", text], check=False, env=env, cwd="/",
                          stdin=subprocess.DEVNULL, capture_output=True, text=True)


def test_halt_expiry_fresh_halt_blocks_hook():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        age_halt(root, 60)
        run_hook(with_topic(env))
        assert sent_msgs(root) == [] and "queued" in log_tails(root)


def test_halt_expiry_expired_halt_tries_one_and_clears_on_success():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        halt = age_halt(root, 3601)
        run_hook(with_topic(env))
        assert len(sent_msgs(root)) == 1
        assert not halt.exists(), "2xx 성공이면 halt 를 지운다"


def test_halt_expiry_expired_halt_hit_again_refreshes_and_logs_rate_halt():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        halt = age_halt(root, 3601)
        run_hook(with_topic(dict(env, FAKE_CURL_HTTP="429", FAKE_CURL_BODY=RATE_BODY)))
        assert len(sent_msgs(root)) == 1
        assert halt.exists() and time.time() - halt.stat().st_mtime < 60, "halt 갱신"
        rows = [r for r in send_log(root).read_text(encoding="utf-8").splitlines()]
        assert rows[-1].split("\t")[-1] == "rate_halt" and rows[-1].split("\t")[3] == "429"
        run_hook(with_topic(env))  # 갱신된 halt 는 다시 유효: 보내지 않는다
        assert len(sent_msgs(root)) == 1


def test_halt_expiry_zero_keeps_whole_day_halt():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        age_halt(root, 7200)
        run_hook(with_topic(dict(env, NTFY_HALT_RETRY_SEC="0")))
        assert sent_msgs(root) == [] and halt_path(root).exists()


def test_halt_expiry_invalid_value_defaults_to_3600():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        age_halt(root, 3601)
        run_hook(with_topic(dict(env, NTFY_HALT_RETRY_SEC="abc")))
        assert len(sent_msgs(root)) == 1


def test_halt_trial_claim_blocks_second_hook():
    # 만료 직후 훅이 겹쳐도 첫 훅이 시험 권리를 선점해 두 번째는 보내지 않는다(같은 IP 에서 N건 방지).
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        age_halt(root, 3601)
        env = with_topic(dict(env, FAKE_CURL_SLEEP="2", FAKE_CURL_HTTP="429", FAKE_CURL_BODY=RATE_BODY))
        first = subprocess.Popen(["bash", str(NOTIFY), "Proj", "첫째"], env=env, cwd="/",
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        run_hook(env, "둘째")
        first.wait(timeout=30)
        assert len(sent_msgs(root)) == 1
        assert "queued" in log_tails(root)


def test_halt_trial_failure_backdates_halt_for_five_minute_retry():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        halt = age_halt(root, 3601)
        run_hook(with_topic(dict(env, FAKE_CURL_HTTP="000")))
        assert len(sent_msgs(root)) == 1 and halt.exists()
        age = time.time() - halt.stat().st_mtime
        assert 3600 - 300 - 60 < age < 3600 - 300 + 60, age  # 약 5분 뒤 재시험 꼴
        run_hook(with_topic(dict(env, FAKE_CURL_HTTP="000")))
        assert len(sent_msgs(root)) == 1, "되돌린 시각이 아직 유효라 재시도하지 않는다"
        os.utime(halt, (time.time() - 3601, time.time() - 3601))
        run_hook(with_topic(dict(env, FAKE_CURL_HTTP="000")), "셋째")
        assert len(sent_msgs(root)) == 2


def test_normal_day_creates_no_halt_file():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        run_hook(with_topic(env))
        run_hook(with_topic(dict(env, FAKE_CURL_HTTP="000")))
        assert len(sent_msgs(root)) == 2 and not halt_path(root).exists()


def test_halt_expiry_flush_follows_same_rule():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        add_queue(root, "m0")
        age_halt(root, 60)
        run_flush(with_topic(env))
        assert sent_msgs(root) == [] and queue_msgs(root) == ["m0"]
        age_halt(root, 3601)
        run_flush(with_topic(dict(env, NTFY_HALT_RETRY_SEC="0")))
        assert sent_msgs(root) == [], "0 이면 만료 없이 하루 통째"
        run_flush(with_topic(env))
        assert sent_msgs(root) == ["m0"] and not halt_path(root).exists()


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"OK   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001 — 실패 사유를 그대로 보여 준다
            failed += 1
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{'ALL PASS' if failed == 0 else f'FAIL {failed}'} ({len(TESTS)} cases)")
    sys.exit(1 if failed else 0)
