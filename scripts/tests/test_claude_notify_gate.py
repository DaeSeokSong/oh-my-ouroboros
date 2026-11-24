"""claude-notify.sh 최종 판별 게이트 회귀 테스트.

정본: ~/.claude/intent/2026-09-26-ntfy-final-only.md
드라이런(CLAUDE_NOTIFY_DRYRUN=1)으로 실제 발송 없이 판정만 검사한다.
REF: knowledge/harness/code-history/scripts__tests__test_claude_notify_gate.py.md
"""

import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "claude-notify.sh"

_ISO_HOME_TMP = tempfile.TemporaryDirectory()
ISO_HOME = Path(_ISO_HOME_TMP.name)

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def write_transcript(path, texts):
    lines = []
    for t in texts:
        lines.append(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}))
        lines.append(json.dumps({"type": "assistant",
                                 "message": {"role": "assistant",
                                             "content": [{"type": "text", "text": t}]}},
                                ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_notify(job_dir, payload, args=None, home=ISO_HOME, extra_env=None):
    env = dict(os.environ, CLAUDE_NOTIFY_DRYRUN="1")
    env.pop("CODE_EARN_BACKGROUND_CHILD", None)
    env.pop("CLAUDE_NOTIFY_SKIP", None)
    if job_dir is None:
        env.pop("CLAUDE_JOB_DIR", None)
    else:
        env["CLAUDE_JOB_DIR"] = job_dir
    if home is not None:
        env["HOME"] = str(home)
        env.pop("CLAUDE_HOME", None)
    if extra_env:
        env.update(extra_env)
    cmd = ["bash", str(SCRIPT)] + (args or ["TestProj", "기본 요약"])
    stdin_text = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
    return subprocess.run(cmd, capture_output=True, text=True, env=env,
                          input=stdin_text, cwd=str(SCRIPT.parent), check=False)


def write_transcript_raw(path, assistant_contents):
    lines = []
    for content in assistant_contents:
        lines.append(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}))
        lines.append(json.dumps({"type": "assistant",
                                 "message": {"role": "assistant", "content": content}},
                                ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_case1_result():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["작업을 마쳤습니다.\nresult: 3개 파일 수정 완료, 테스트 통과"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("case1: rc 0", r.returncode == 0, r.stderr[:160])
        check("case1: NOTIFY default white_check_mark",
              r.stdout.strip() == "NOTIFY\tdefault\twhite_check_mark\tresult: 3개 파일 수정 완료, 테스트 통과",
              r.stdout)


def test_case2_no_marker():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["작업 진행 중입니다"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("case2: rc 0", r.returncode == 0, r.stderr[:160])
        check("case2: SKIP", r.stdout.strip() == "SKIP", r.stdout)


def test_case3_needs_input():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["확인 필요\nneeds input: GPU 배정을 알려주세요"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("case3: NOTIFY high question",
              r.stdout.strip() == "NOTIFY\thigh\tquestion\tneeds input: GPU 배정을 알려주세요", r.stdout)


def test_case4_failed():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["failed: 검증 3건 불일치"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("case4: NOTIFY default x",
              r.stdout.strip() == "NOTIFY\tdefault\tx\tfailed: 검증 3건 불일치", r.stdout)


def test_case5_notification_event():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["작업 진행 중입니다"])
        r = run_notify(tmp, {"hook_event_name": "Notification",
                             "notification_type": "permission_prompt",
                             "transcript_path": str(tp)})
        check("case5: NOTIFY default (게이트 미적용)",
              r.stdout.strip() == "NOTIFY\tdefault\twhite_check_mark\t기본 요약", r.stdout)


def test_case6_not_job():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["작업 진행 중입니다"])
        r = run_notify(None, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("case6: NOTIFY default (잡 아님)",
              r.stdout.strip() == "NOTIFY\tdefault\twhite_check_mark\t기본 요약", r.stdout)


def test_case7_broken_transcript():
    with tempfile.TemporaryDirectory() as tmp:
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": "/nope/x.jsonl"})
        check("case7: NOTIFY default (fail-open)",
              r.stdout.strip() == "NOTIFY\tdefault\twhite_check_mark\t기본 요약", r.stdout)


def test_truncation_utf8():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        tail = "가" * 250
        write_transcript(tp, [f"result: {tail}"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        parts = r.stdout.rstrip("\n").split("\t", 3)
        check("truncate: NOTIFY 형식 4필드", len(parts) == 4, r.stdout)
        if len(parts) == 4:
            msg = parts[3]
            check("truncate: 200자로 절단", len(msg) == 200, f"len={len(msg)}")
            check("truncate: 깨진 바이트 없음(치환문자 없음)", "�" not in msg, msg[-10:])
            check("truncate: 접두 result 보존", msg.startswith("result: "), msg[:20])


def test_marker_in_earlier_message_only():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["result: 예전 표지", "정상 진행 중"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("earlier-only marker: SKIP", r.stdout.strip() == "SKIP", r.stdout)


def test_add1_tool_only_skip():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript_raw(tp, [[{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("add1: SKIP (도구 호출만)", r.stdout.strip() == "SKIP", r.stdout)


def test_add2_string_content():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript_raw(tp, ["result: 완료"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("add2: NOTIFY result (문자열 content)",
              r.stdout.strip() == "NOTIFY\tdefault\twhite_check_mark\tresult: 완료", r.stdout)


def test_add3_uppercase_only_skip():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["RESULT: FAIL target=coder"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("add3: SKIP (대문자 RESULT: 는 표지 아님)", r.stdout.strip() == "SKIP", r.stdout)


def test_add4_priority_failed_over_result():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["result: 절반 완료\nfailed: 나머지 3건 불일치"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("add4: NOTIFY failed (result보다 우선)",
              r.stdout.strip() == "NOTIFY\tdefault\tx\tfailed: 나머지 3건 불일치", r.stdout)


def test_add5_leading_space_needs_input():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["  needs input: 확인"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("add5: NOTIFY high question (행두 공백)",
              r.stdout.strip() == "NOTIFY\thigh\tquestion\tneeds input: 확인", r.stdout)


def test_add6_fenced_skip():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["설명입니다\n```\nresult: x\n```\n끝"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("add6: SKIP (펜스 안 표지 제외)", r.stdout.strip() == "SKIP", r.stdout)


def test_add7_quoted_skip():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["> result: 인용"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("add7: SKIP (인용줄 표지 제외)", r.stdout.strip() == "SKIP", r.stdout)


def test_add8_secret_masking():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        # NEVER: 가짜 비밀값을 파일 원문에 «이름=sk-…» 꼴로 두지 않는다. 실행 시 이어 붙여 만든다(그 꼴이 있으면 전송 사전검사가 막는다)
        ft = "sk-" + "abcdefghijklmnop"
        write_transcript(tp, ["result: 완료 tok" + "en=" + ft])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        out = r.stdout.strip()
        check("add8: <masked> 포함", "<masked>" in out, out)
        check("add8: 원문 토큰 미노출", ft not in out, out)


def test_add9_notify_skip_env():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["result: 완료"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)},
                       extra_env={"CLAUDE_NOTIFY_SKIP": "1"})
        check("add9: rc 0", r.returncode == 0, r.stderr[:160])
        check("add9: stdout 빈 값", r.stdout == "", repr(r.stdout))


def test_add10_missing_hook_event():
    with tempfile.TemporaryDirectory() as tmp:
        r = run_notify(tmp, {})
        check("add10: NOTIFY default (hook_event_name 없음)",
              r.stdout.strip() == "NOTIFY\tdefault\twhite_check_mark\t기본 요약", r.stdout)


def test_add11_masking_all_patterns():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        # NEVER: 가짜 토큰의 패턴을 파일 원문에 두지 않는다. 실행 시 이어 붙인다(원문에 있으면 커밋 훅의 시크릿 탐지가 막는다)
        p1 = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
        p2 = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz"
        p3 = "Bea" + "rer " + "abcdefghijklmnopqrstuv"
        p4 = "0123456789abcdef" * 2
        write_transcript(tp, [f"result: a {p1} b {p2} c {p3} d {p4} 끝"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        body = r.stdout.strip().split("\t")[-1] if r.stdout.strip() else ""
        check("add11: AKIA·ghp_·Bearer·hex32 전부 <masked>",
              body.count("<masked>") == 4 and "AKIA" not in body and "ghp_" not in body
              and "abcdefghijklmnopqrstuv" not in body and "0123456789abcdef0123456789abcdef" not in body
              and body.endswith("끝"), r.stdout)


def test_add12_same_kind_last_line():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["result: 첫째\n본문\nresult: 둘째"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("add12: 동종 result 두 줄이면 마지막 줄",
              r.stdout.strip() == "NOTIFY\tdefault\twhite_check_mark\tresult: 둘째", r.stdout)


def test_add13_slow_jq_fail_open():
    import time
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["result: 느린 jq"])
        fake = os.path.join(tmp, "bin")
        os.makedirs(fake)
        real_jq = subprocess.run(["bash", "-c", "command -v jq"], capture_output=True, text=True, check=False).stdout.strip()
        with open(os.path.join(fake, "jq"), "w") as f:
            f.write("#!/bin/bash\nfor a in \"$@\"; do [ \"$a\" = \"-rs\" ] && sleep 6; done\nexec " + real_jq + " \"$@\"\n")
        os.chmod(os.path.join(fake, "jq"), 0o755)
        t0 = time.time()
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp)},
                       extra_env={"PATH": fake + os.pathsep + os.environ.get("PATH", "")})
        dt = time.time() - t0
        check("add13: 느린 jq → timeout 4 안에 fail-open NOTIFY 기본",
              r.stdout.strip() == "NOTIFY\tdefault\twhite_check_mark\t기본 요약" and dt < 6.0,
              f"{r.stdout!r} dt={dt:.1f}s")


def test_add14_open_stdin_pipe():
    import time
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, CLAUDE_NOTIFY_DRYRUN="1", CLAUDE_JOB_DIR=tmp, HOME=str(ISO_HOME))
        env.pop("CLAUDE_HOME", None)
        t0 = time.time()
        p = subprocess.Popen(["bash", str(SCRIPT), "TestProj", "기본 요약"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            out, _ = p.communicate(timeout=5)
            dt = time.time() - t0
            check("add14: 열린 빈 stdin → 2초 timeout 뒤 기본 NOTIFY",
                  out.strip() == "NOTIFY\tdefault\twhite_check_mark\t기본 요약" and dt < 5.0, f"{out!r} dt={dt:.1f}s")
        except subprocess.TimeoutExpired:
            p.kill()
            check("add14: 열린 빈 stdin → 2초 timeout 뒤 기본 NOTIFY", False, "5초 넘게 멈춤")


def stop_with_field(tp, text):
    return {"hook_event_name": "Stop", "transcript_path": str(tp), "last_assistant_message": text}


def test_lam1_race_transcript_unflushed():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript_raw(tp, [[{"type": "thinking", "thinking": "정리 중"},
                                  {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]])
        r = run_notify(tmp, stop_with_field(tp, "마쳤습니다.\nresult: 경합 수정 완료"))
        check("lam1: NOTIFY result (transcript 미flush, 필드 사용)",
              r.stdout.strip() == "NOTIFY\tdefault\twhite_check_mark\tresult: 경합 수정 완료", r.stdout)


def test_lam2_field_wins_over_transcript():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["result: transcript 쪽 표지"])
        r = run_notify(tmp, stop_with_field(tp, "아직 진행 중입니다"))
        check("lam2: SKIP (필드 우선)", r.stdout.strip() == "SKIP", r.stdout)


def test_lam3_field_fenced_skip():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["result: transcript 쪽 표지"])
        r = run_notify(tmp, stop_with_field(tp, "예시입니다\n```\nresult: x\n```\n끝"))
        check("lam3: SKIP (필드 펜스 안 표지 제외)", r.stdout.strip() == "SKIP", r.stdout)


def test_lam4_field_absent_uses_transcript():
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp) / "t.jsonl"
        write_transcript(tp, ["result: transcript 폴백"])
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": str(tp),
                             "last_assistant_message": ""})
        check("lam4: NOTIFY result (빈 필드 → transcript 폴백)",
              r.stdout.strip() == "NOTIFY\tdefault\twhite_check_mark\tresult: transcript 폴백", r.stdout)


def test_lam5_field_needs_input():
    with tempfile.TemporaryDirectory() as tmp:
        r = run_notify(tmp, {"hook_event_name": "Stop", "transcript_path": "/nope/x.jsonl",
                             "last_assistant_message": "확인 필요\nneeds input: 어느 GPU 입니까"})
        check("lam5: NOTIFY high question (필드, transcript 없어도)",
              r.stdout.strip() == "NOTIFY\thigh\tquestion\tneeds input: 어느 GPU 입니까", r.stdout)


for fn in (test_lam1_race_transcript_unflushed, test_lam2_field_wins_over_transcript,
           test_lam3_field_fenced_skip, test_lam4_field_absent_uses_transcript,
           test_lam5_field_needs_input):
    fn()


for fn in (test_case1_result, test_case2_no_marker, test_case3_needs_input, test_case4_failed,
           test_case5_notification_event, test_case6_not_job, test_case7_broken_transcript,
           test_truncation_utf8, test_marker_in_earlier_message_only,
           test_add1_tool_only_skip, test_add2_string_content, test_add3_uppercase_only_skip,
           test_add4_priority_failed_over_result, test_add5_leading_space_needs_input,
           test_add6_fenced_skip, test_add7_quoted_skip, test_add8_secret_masking,
           test_add9_notify_skip_env, test_add10_missing_hook_event,
           test_add11_masking_all_patterns, test_add12_same_kind_last_line,
           test_add13_slow_jq_fail_open, test_add14_open_stdin_pipe):
    fn()


USAGE_SCRIPT = SCRIPT.parent / "harness-usage-check.sh"
TEST_DAY = "20260926"


def make_fake_curl(root):
    bindir = root / "bin"
    bindir.mkdir()
    fake = bindir / "curl"
    fake.write_text(
        '#!/bin/bash\n'
        'out=""\n'
        'data=""\n'
        'title=""\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  case "$1" in\n'
        '    -o) out="$2"; shift 2 ;;\n'
        '    -K) cfg=$(cat); shift 2 ;;\n'
        '    -w|--max-time) shift 2 ;;\n'
        '    *) shift ;;\n'
        '  esac\n'
        'done\n'
        'data=$(printf "%s\\n" "$cfg" | sed -n \'s/^data-raw = "\\(.*\\)"$/\\1/p\' | sed \'s/\\\\\\(.\\)/\\1/g\')\n'
        'title=$(printf "%s\\n" "$cfg" | sed -n \'s/^header = "Title: \\(.*\\)"$/\\1/p\' | sed \'s/\\\\\\(.\\)/\\1/g\')\n'
        'printf "x\\n" >> "$FAKE_CURL_CALLS"\n'
        'printf "%s" "$data" > "$FAKE_CURL_LAST_D"\n'
        'printf "%s" "$title" > "$FAKE_CURL_LAST_TITLE"\n'
        'printf "%s" "$FAKE_CURL_BODY" > "$out"\n'  # NEVER: ${VAR:-{}} 꼴로 쓰지 않는다. 첫 } 에서 확장이 끝나 JSON 이 깨진다(main 실측)
        'printf "%s %s" "${FAKE_CURL_HTTP:-200}" "${FAKE_CURL_TIME:-0.001}"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bindir


def real_env(root, job=None, extra=None):
    bindir = make_fake_curl(root)
    env = dict(os.environ)
    for key in ("CLAUDE_HOME", "CLAUDE_NOTIFY_DRYRUN", "CLAUDE_NOTIFY_SKIP",
                "CODE_EARN_BACKGROUND_CHILD", "CLAUDE_JOB_DIR", "NTFY_DAILY_CAP",
                "NTFY_RESERVE", "NTFY_DAY", "TMUX", "DISPLAY"):
        env.pop(key, None)
    env.update({
        "HOME": str(root),
        "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""),
        "USER_NTFY_TOPIC": "test-topic",
        "NTFY_DAY": TEST_DAY,
        "FAKE_CURL_CALLS": str(root / "curl-calls"),
        "FAKE_CURL_LAST_D": str(root / "curl-last-d"),
        "FAKE_CURL_LAST_TITLE": str(root / "curl-last-title"),
        "FAKE_CURL_BODY": "{}",
        "FAKE_CURL_HTTP": "200",
        "FAKE_CURL_TIME": "0.001",
    })
    if job is not None:
        env["CLAUDE_JOB_DIR"] = str(job)
    if extra:
        env.update(extra)
    return env


def real_run(env, payload=None, args=None, stdin_text=None):
    if stdin_text is None:
        stdin_text = json.dumps(
            payload if payload is not None else {"hook_event_name": "Stop"},
            ensure_ascii=False,
        )
    return subprocess.run(
        ["bash", str(SCRIPT)] + (args or ["TestProj", "작업 완료"]),
        input=stdin_text,
        capture_output=True, text=True, env=env, cwd=str(SCRIPT.parent), check=False,
    )


def usage(root):
    path = root / ".claude" / "_usage"
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_count(root, value):
    (usage(root) / f"ntfy-{TEST_DAY}.count").write_text(str(value) + "\n", encoding="utf-8")


def count(root):
    path = usage(root) / f"ntfy-{TEST_DAY}.count"
    return int(path.read_text().strip()) if path.exists() else None


def calls(root):
    path = root / "curl-calls"
    return len(path.read_text().splitlines()) if path.exists() else 0


def log_rows(root):
    path = root / ".claude" / "_audit" / "ntfy-send.tsv"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def queue_rows(root):
    path = usage(root) / "ntfy-queue.tsv"
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line] if path.exists() else []


def add_queue(root, kind="needs_input", msg="needs input: 옛",
              ts="2026-09-25T00:00:00Z", session="old", tries=0):
    row = "\t".join((ts, session, kind, "high",
                     "question", "[old: TestProj]", msg, str(tries)))
    path = usage(root) / "ntfy-queue.tsv"
    with path.open("a", encoding="utf-8") as out:
        out.write(row + "\n")


def final_payload(root, text="result: 끝"):
    tp = root / "t.jsonl"
    write_transcript(tp, [text])
    return {"hook_event_name": "Stop", "transcript_path": str(tp),
            "session_id": "test_session"}


def test_b1():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root)
        set_count(root, 159)
        r = real_run(env)
        check("B1", r.returncode == 0 and calls(root) == 1 and count(root) == 160
              and not queue_rows(root)
              and any("\troutine\t200\t" in row and row.endswith("\tsent")
                      for row in log_rows(root)), r.stderr)


def test_b2():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root)
        set_count(root, 160)
        real_run(env)
        check("B2", calls(root) == 0 and count(root) == 160
              and any(row.endswith("\tbudget_skip") for row in log_rows(root)))


def test_b3():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, job=root)
        set_count(root, 160)
        r = real_run(env, final_payload(root))
        check("B3", calls(root) == 1 and count(root) == 161 and "NOTIFY" not in r.stdout
              and any("\tfinal\t200\t" in row for row in log_rows(root)), r.stdout)


def test_b4():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, job=root)
        set_count(root, 200)
        real_run(env, final_payload(root))
        check("B4", calls(root) == 0 and len(queue_rows(root)) == 1
              and "result: 끝" in queue_rows(root)[0]
              and any(row.endswith("\tqueued") for row in log_rows(root)))


def test_b5():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root)
        set_count(root, 160)
        real_run(env, args=["Claude", "권한 승인 필요"])
        check("B5", calls(root) == 1 and count(root) == 161
              and any("\tpermission\t200\t" in row for row in log_rows(root)))


def test_b6():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, job=root)
        (usage(root) / f"ntfy-{TEST_DAY}.halt").touch()
        real_run(env, final_payload(root, "failed: 검증 실패"))
        check("B6", calls(root) == 0 and len(queue_rows(root)) == 1
              and "failed: 검증 실패" in queue_rows(root)[0])


def test_b7():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, job=root, extra={
            "FAKE_CURL_HTTP": "429",
            "FAKE_CURL_BODY": '{"code":42908}',
        })
        set_count(root, 10)
        real_run(env, final_payload(root, "result: q"))
        check("B7", (usage(root) / f"ntfy-{TEST_DAY}.halt").exists()
              and count(root) == 11 and len(queue_rows(root)) == 1
              and "result: q" in queue_rows(root)[0])


def test_b8():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root)
        set_count(root, 0)
        add_queue(root)
        real_run(env)
        last = (root / "curl-last-d").read_text(encoding="utf-8")
        check("B8", calls(root) == 1 and last == "needs input: 옛"
              and not queue_rows(root) and count(root) == 1
              and any(row.endswith("\tflush_sent") for row in log_rows(root)))


def test_b9():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root)
        set_count(root, 0)
        add_queue(root)
        (usage(root) / "ntfy-20260925.halt").touch()
        real_run(env)
        check("B9", calls(root) == 1 and count(root) == 1 and not queue_rows(root))


def test_b10():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tpc = "hidden-" + "topic-xyz"  # NEVER: 이름·값에 secret 을 쓰지 않는다. 전송 사전검사가 자격증명으로 본다
        env = real_env(root, job=root, extra={"USER_NTFY_TOPIC": tpc})
        set_count(root, 160)
        real_run(env, final_payload(root))
        audit = "\n".join(log_rows(root))
        state = "\n".join(p.read_text(encoding="utf-8") for p in usage(root).glob("ntfy-*")
                          if p.is_file() and p.suffix in (".count", ".halt", ".tsv"))
        check("B10", tpc not in audit and tpc not in state)


def test_b11():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, job=root, extra={"CLAUDE_NOTIFY_DRYRUN": "1"})
        r = real_run(env, final_payload(root))
        check("B11", r.stdout.strip() == "NOTIFY\tdefault\twhite_check_mark\tresult: 끝"
              and count(root) is None and calls(root) == 0, r.stdout)


def test_b12():
    for trial in range(5):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = real_env(root, job=root)
            set_count(root, 199)
            payload = json.dumps(final_payload(root), ensure_ascii=False)
            cmd = ["bash", str(SCRIPT), "TestProj", "작업 완료"]
            p1 = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=env, cwd=str(SCRIPT.parent))
            p2 = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=env, cwd=str(SCRIPT.parent))
            gate = threading.Barrier(3)

            def feed(process, gate=gate, payload=payload):
                gate.wait()
                process.stdin.write(payload)
                process.stdin.close()
                process.stdin = None

            t1 = threading.Thread(target=feed, args=(p1,))
            t2 = threading.Thread(target=feed, args=(p2,))
            t1.start()
            t2.start()
            gate.wait()
            t1.join()
            t2.join()
            p1.communicate(timeout=10)
            p2.communicate(timeout=10)
            check(f"B12 run {trial + 1}",
                  calls(root) == 1 and count(root) == 200 and len(queue_rows(root)) == 1)


def test_b13():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, job=root)
        set_count(root, 160)
        (usage(root) / f"ntfy-{TEST_DAY}.failopen").write_text("5\n", encoding="utf-8")
        real_run(env, {"hook_event_name": "Stop", "transcript_path": "/nope/x.jsonl"})
        check("B13", calls(root) == 0 and count(root) == 160
              and any(row.endswith("\tbudget_skip") for row in log_rows(root)))


def test_b14():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, extra={"CLAUDE_NOTIFY_SKIP": "1"})
        add_queue(root)
        path = usage(root) / "ntfy-queue.tsv"
        before = path.read_bytes()
        r = real_run(env)
        check("B14", r.returncode == 0 and r.stdout == ""
              and path.read_bytes() == before and calls(root) == 0)


def test_b15():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root)
        (usage(root) / f"ntfy-{TEST_DAY}.halt").touch()
        present = subprocess.run(["bash", str(USAGE_SCRIPT)], capture_output=True,
                                 text=True, env=env, cwd=str(SCRIPT.parent), check=False)
        (usage(root) / f"ntfy-{TEST_DAY}.halt").unlink()
        absent = subprocess.run(["bash", str(USAGE_SCRIPT)], capture_output=True,
                                text=True, env=env, cwd=str(SCRIPT.parent), check=False)
        check("B15", "NTFY_QUOTA:" in present.stdout
              and "NTFY_QUOTA:" not in absent.stdout)


def test_b16():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, job=root)
        set_count(root, 160)
        add_queue(root, kind="final", msg="result: 옛")
        real_run(env, args=["train-watcher", "학습 완료"], stdin_text="")
        rows = queue_rows(root)
        check("B16", (any("\tdirect\t" in row and "학습 완료" in row for row in rows)
                      or ((root / "curl-last-d").exists()
                          and (root / "curl-last-d").read_text(encoding="utf-8") == "학습 완료"))
              and not any("\tdirect\t" in row and row.endswith("\tbudget_skip")
                          for row in log_rows(root)))


def test_b17():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, job=root)
        set_count(root, 200)
        add_queue(root, kind="final", msg="result: 가장 오래됨",
                  ts="2026-09-01T00:00:00Z", session="oldest")
        for i in range(29):
            add_queue(root, kind="permission", msg=f"권한 {i}",
                      ts=f"2026-09-20T00:00:{i:02d}Z", session=f"p{i}")
        real_run(env, final_payload(root, "result: 새"))
        rows = queue_rows(root)
        check("B17", len(rows) == 30 and not any("가장 오래됨" in row for row in rows)
              and any("result: 새" in row for row in rows)
              and any("\toldest\tfinal\t" in row and row.endswith("\tqueue_drop")
                      for row in log_rows(root)))


def test_b18():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root)
        set_count(root, 200)
        for i in range(30):
            add_queue(root, kind="permission", msg=f"권한 {i}",
                      ts=f"2026-09-20T00:00:{i:02d}Z", session=f"p{i}")
        real_run(env, args=["Claude", "권한 승인 필요"])
        rows = queue_rows(root)
        check("B18", len(rows) == 30 and not any("\tp0\tpermission\t" in row for row in rows)
              and any("\tp0\tpermission\t" in row and row.endswith("\tqueue_drop")
                      for row in log_rows(root)))


def test_b19():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root)
        set_count(root, 0)
        (usage(root) / "ntfy-queue.tsv").write_text("잡음 줄\n", encoding="utf-8")
        real_run(env)
        check("B19", calls(root) == 1 and count(root) == 1 and not queue_rows(root)
              and any("\tinvalid\t" in row and row.endswith("\tqueue_drop")
                      for row in log_rows(root)))


def test_b20():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, job=root)
        (usage(root) / f"ntfy-{TEST_DAY}.halt").touch()
        (usage(root) / "ntfy-budget.lock").mkdir()
        real_run(env, final_payload(root))
        # WHY: 잠금 실패분은 큐 파일이 아니라 .spill 에 쌓인다(2026-10-01 감사 D4: 큐 전체 교체에 덮이지 않게)
        spill = usage(root) / "ntfy-queue.tsv.spill"
        spilled = spill.read_text(encoding="utf-8").splitlines() if spill.exists() else []
        check("B20", calls(root) == 0 and queue_rows(root) == [] and len(spilled) == 1
              and "result: 끝" in spilled[0])
        (usage(root) / "ntfy-budget.lock").rmdir()
        (usage(root) / f"ntfy-{TEST_DAY}.halt").unlink()
        set_count(root, 200)
        add_queue(root, kind="permission", msg="권한 대기", ts="2026-09-25T00:00:00Z", session="p")
        real_run(env, args=["Claude", "아무거나"], stdin_text="")
        merged = queue_rows(root)
        check("B20 병합", not spill.exists() and any("result: 끝" in row for row in merged)
              and any("권한 대기" in row for row in merged), str(merged))


def test_b21():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, job=root, extra={
            "FAKE_CURL_HTTP": "429",
            "FAKE_CURL_BODY": "{}",
        })
        set_count(root, 10)
        real_run(env, final_payload(root))
        check("B21", calls(root) == 1 and count(root) == 10
              and len(queue_rows(root)) == 1
              and any(row.endswith("\trate_requeue") for row in log_rows(root)))


def test_b22():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, extra={"FAKE_CURL_HTTP": "500"})
        set_count(root, 0)
        add_queue(root, kind="final", msg="result: 재실패", tries=1)
        real_run(env)
        rows = queue_rows(root)
        check("B22", calls(root) == 1 and count(root) == 0 and len(rows) >= 1
              and any("result: 재실패" in row and row.split("\t")[7] == "1" for row in rows)
              and not any(row.endswith("\tretry_drop") for row in log_rows(root)))
        add_queue(root, kind="final", msg="result: 옛줄", ts="2026-09-24T00:00:00Z", tries=2)
        real_run(env, args=["Claude", "아무거나"], stdin_text="")
        check("B22 옛줄", any(row.endswith("\tretry_drop") for row in log_rows(root))
              and not any("result: 옛줄" in row for row in queue_rows(root)))


def test_b23():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root, job=root)
        set_count(root, 0)
        add_queue(root, kind="final", msg="result: 대기")
        tp = root / "skip.jsonl"
        write_transcript(tp, ["진행 중"])
        real_run(env, {"hook_event_name": "Stop", "transcript_path": str(tp)})
        check("B23", calls(root) == 1 and count(root) == 1 and not queue_rows(root)
              and (root / "curl-last-d").read_text(encoding="utf-8") == "result: 대기")


def test_b24():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = real_env(root)
        real_run(env, args=["제목\n삽입", "학습 완료"], stdin_text="")
        title = (root / "curl-last-title").read_text(encoding="utf-8")
        check("B24", calls(root) == 1 and "\n" not in title
              and title.startswith("Title: ") is False and "제목삽입" in title, title)


for fn in (test_b1, test_b2, test_b3, test_b4, test_b5, test_b6, test_b7, test_b8,
           test_b9, test_b10, test_b11, test_b12, test_b13, test_b14, test_b15,
           test_b16, test_b17, test_b18, test_b19, test_b20, test_b21, test_b22,
           test_b23, test_b24):
    fn()

fail = 0
for name, ok, detail in results:
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       실제: {detail[:300]}")
    fail += 0 if ok else 1

import sys

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(results)} cases)")
sys.exit(1 if fail else 0)
