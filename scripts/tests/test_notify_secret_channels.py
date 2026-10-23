#!/usr/bin/env python3
"""알림 본문 통제·시크릿 채널 회귀 시험 (2026-10-01 감사 묶음 D 신설).

대상: claude-notify.sh(마스킹 한 곳·curl 인자 비노출·잠금 실패 spill), mem-watch.sh(claude-notify 경유),
      tavily-usage-fetch.sh(키 비노출), prompt-log.sh(600), t41-subagent-stop.sh(RESULT 우선·마스킹).
실제 네트워크·실제 ~/.claude 를 쓰지 않는다: HOME 은 임시 폴더, PATH 앞에 가짜 curl(받은 인자·표준입력을 파일에 적는다).
알림 주제·가짜 토큰은 시험용 값이며 실행 시 이어 붙여 만든다(파일 원문에 패턴이 있으면 시크릿 탐지가 막는다).
실행: python3 scripts/tests/test_notify_secret_channels.py (pytest 로도 수집된다). D_SCRIPTS·D_TOOLS 로 대상 사본을 바꿀 수 있다.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(os.environ.get("D_SCRIPTS", Path(__file__).resolve().parent.parent))
TOOLS = Path(os.environ.get("D_TOOLS", SCRIPTS.parent / "tools"))
NOTIFY = SCRIPTS / "claude-notify.sh"
FLUSH = SCRIPTS / "ntfy-flush.sh"
DAY = "20261001"
TOPIC = "topic-" + "zq81xk"  # 가짜 주제

# 가짜 토큰(이어 붙여 만든다)
T_ANT = "sk-" + "ant-api03-" + "ABCDEFGHIJKLMNOP"
T_PROJ = "sk-" + "proj-" + "abcdefghij1234567890"
T_TAVILY = "tv" + "ly-" + "dev-ABCDEFGH12345678"
T_GH = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz0123456789"
T_SLACK = "xo" + "xb-" + "123456789-abcdefghijkl"
T_MEM0 = "m" + "0-" + "abcdefghij1234567890"
T_ATLAS = "AT" + "ATT" + "3xFfGF0abcdefghijklmnopq"
UID = "1.2.840.113619.2.55.3.604688119.971.1234567890.123"
ALL_TOKENS = [T_ANT, T_PROJ, T_TAVILY, T_GH, T_SLACK, T_MEM0, T_ATLAS, UID]


def make_root(tmp, topic=True):
    """가짜 curl 이 든 임시 HOME 과 환경. curl 은 인자(argv.log)·표준입력(stdin.log)·본문(data.log)을 적는다."""
    root = Path(tmp)
    bindir = root / "bin"
    bindir.mkdir()
    fake = bindir / "curl"
    fake.write_text(
        '#!/bin/bash\n'
        'printf "%s\\n" "$*" >> "$FAKE_LOG/argv.log"\n'
        'out=""; cfg=""\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  case "$1" in\n'
        '    -o) out="$2"; shift 2 ;;\n'
        '    -K) cfg=$(cat); shift 2 ;;\n'
        '    -w|--max-time) shift 2 ;;\n'
        '    *) shift ;;\n'
        '  esac\n'
        'done\n'
        'printf "%s\\n" "$cfg" >> "$FAKE_LOG/stdin.log"\n'
        'printf "%s\\n" "$cfg" | sed -n \'s/^data-raw = "\\(.*\\)"$/\\1/p\' >> "$FAKE_LOG/data.log"\n'
        'if [ -n "$out" ]; then printf "{}" > "$out"; printf "200 0.001"; else printf "%s" "$FAKE_STDOUT"; fi\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    logs = root / "fakelog"
    logs.mkdir()
    env = dict(os.environ)
    for key in ("CLAUDE_HOME", "CLAUDE_NOTIFY_DRYRUN", "CLAUDE_NOTIFY_SKIP", "CODE_EARN_BACKGROUND_CHILD",
                "CLAUDE_JOB_DIR", "NTFY_DAILY_CAP", "NTFY_RESERVE", "CLAUDE_NOTIFY_FLUSH_ONLY",
                "USER_NTFY_TOPIC", "ALERT_WEBHOOK_URL", "TMUX", "DISPLAY", "XDG_CACHE_HOME"):
        env.pop(key, None)
    env.update({"HOME": str(root), "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""),
                "NTFY_DAY": DAY, "FAKE_LOG": str(logs)})
    if topic:
        env["USER_NTFY_TOPIC"] = TOPIC
    (root / ".claude" / "_usage").mkdir(parents=True)
    return root, env


def log(root, name):
    path = root / "fakelog" / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def run(args, env, stdin=subprocess.DEVNULL, input_text=None, cwd="/"):
    kwargs = {"input": input_text} if input_text is not None else {"stdin": stdin}
    return subprocess.run(args, env=env, cwd=cwd, capture_output=True, text=True, timeout=60, **kwargs)


def direct(env, text):
    return run(["bash", str(NOTIFY), "Proj", text], env)


def queue_path(root):
    return root / ".claude" / "_usage" / "ntfy-queue.tsv"


def test_direct_path_masks_every_token_kind():
    # 수정 전: 직접 호출 본문은 마스킹 없이 그대로 나갔다(표지 줄 경로만 마스킹).
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        direct(env, "점검 " + " / ".join(ALL_TOKENS) + " 끝")
        data = log(root, "data.log")
        assert data.strip(), "curl 이 호출되지 않았다"
        for tok in ALL_TOKENS:
            assert tok not in data, tok
        assert data.count("<masked>") == len(ALL_TOKENS), data
        assert data.strip().endswith("끝")


def test_direct_path_truncates_and_single_line():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        direct(env, "가" * 300 + "\n둘째 줄")
        data = log(root, "data.log").strip()
        assert len(data) == 200 and "\n" not in data


def test_queued_and_flushed_text_is_masked_even_if_hand_written_raw():
    # 큐 파일에 마스킹 없이 적힌 줄(옛 버전·수작업)도 재발송 직전 한 함수를 지난다.
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        row = "\t".join(("2026-09-30T00:00:00Z", "s", "final", "default", "tag", "[t: P]", "큐 " + T_ANT + " " + UID, "0"))
        queue_path(root).write_text(row + "\n", encoding="utf-8")
        run(["bash", str(FLUSH)], env)
        data = log(root, "data.log")
        assert data.strip() and T_ANT not in data and UID not in data and "<masked>" in data, data


def test_marker_path_masks_new_token_kinds():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        tp = root / "t.jsonl"
        text = "result: 완료 " + T_TAVILY + " " + T_SLACK + " " + UID
        tp.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}},
                                 ensure_ascii=False) + "\n", encoding="utf-8")
        env["CLAUDE_JOB_DIR"] = str(root)
        run(["bash", str(NOTIFY), "J", "x"], env,
            input_text=json.dumps({"hook_event_name": "Stop", "transcript_path": str(tp), "session_id": "s1"}))
        data = log(root, "data.log")
        assert data.count("<masked>") == 3 and T_TAVILY not in data and T_SLACK not in data, data


def test_curl_argv_carries_no_topic_title_or_body():
    # 수정 전: 주제 URL·헤더·본문이 curl 명령줄 인자였다(프로세스 목록에 보인다).
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        direct(env, "비밀스러운본문")
        argv = log(root, "argv.log")
        assert argv.strip(), "curl 이 호출되지 않았다"
        for needle in (TOPIC, "ntfy.sh", "Title", "Priority", "Tags", "비밀스러운본문", "://"):
            assert needle not in argv, (needle, argv)
        stdin = log(root, "stdin.log")
        assert TOPIC in stdin and 'header = "Title: ' in stdin and "비밀스러운본문" in stdin


def test_body_starting_with_at_sign_is_not_a_file_read():
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        direct(env, "@/etc/hostname")
        stdin = log(root, "stdin.log")
        assert 'data-raw = "@/etc/hostname"' in stdin and "\ndata = " not in "\n" + stdin


def test_lock_failure_spills_and_next_holder_merges():
    # 수정 전: 잠금 실패분이 큐 파일에 바로 append 돼 다른 프로세스의 큐 전체 교체에 덮일 수 있었다.
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        usage = root / ".claude" / "_usage"
        (usage / f"ntfy-{DAY}.halt").touch()
        (usage / "ntfy-budget.lock").mkdir()  # 잠금 파일 자리를 디렉터리로 막아 잠금 실패를 만든다
        direct(env, "스필 대상")
        spill = usage / "ntfy-queue.tsv.spill"
        assert spill.exists() and "스필 대상" in spill.read_text(encoding="utf-8")
        assert not queue_path(root).exists()
        (usage / "ntfy-budget.lock").rmdir()
        (usage / f"ntfy-{DAY}.halt").write_text("")  # halt 중이라 배송은 안 되고 병합만 일어난다
        direct(env, "다음 호출")
        merged = queue_path(root).read_text(encoding="utf-8")
        assert not spill.exists() and "스필 대상" in merged and "다음 호출" in merged, merged


def test_mem_watch_goes_through_claude_notify_without_webhook_url():
    # 수정 전: ALERT_WEBHOOK_URL 로 직접 curl(URL 이 인자). 이제 URL 변수는 쓰지 않고 claude-notify 를 지난다.
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        env.update({"CRIT_AVAIL_GB": "100000000", "MEMWATCH_LOG": str(root / "mw.log"),
                    "MEMWATCH_STATE": str(root / "mw.state"), "OOMWATCH_STATE": str(root / "oom.state"),
                    "ALERT_WEBHOOK_URL": "https://example.invalid/hook-" + "zz9"})
        r = run(["bash", str(TOOLS / "mem-guard" / "mem-watch.sh")], env)
        assert r.returncode == 0
        argv = log(root, "argv.log")
        assert argv.strip() and "hook-zz9" not in argv and "example.invalid" not in argv and TOPIC not in argv, argv
        assert TOPIC in log(root, "stdin.log") and "mem-watch" in log(root, "data.log")
        log_rows = (root / ".claude" / "_audit" / "ntfy-send.tsv").read_text(encoding="utf-8")
        assert "\tdirect\t" in log_rows, log_rows


def test_tavily_key_not_in_curl_argv():
    # 수정 전: -H "Authorization: Bearer <키>" 인자.
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        key = "tv" + "ly-" + "KEYKEYKEY12345678"
        (root / ".claude" / "mcp-secrets.env").write_text(f"TAVILY_API_KEY={key}\n", encoding="utf-8")
        env.update({"XDG_CACHE_HOME": str(root / "cache"),
                    "FAKE_STDOUT": '{"account": {"plan_usage": 3, "plan_limit": 10}}'})
        r = run(["bash", str(SCRIPTS / "tavily-usage-fetch.sh")], env)
        assert r.returncode == 0, r.stderr
        argv = log(root, "argv.log")
        assert argv.strip() and key not in argv and "Bearer" not in argv, argv
        assert f"Bearer {key}" in log(root, "stdin.log")
        assert (root / "cache" / "coralline" / "tavily-usage").read_text().strip() == "3 10"


def prompt_payload(text):
    return json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": text})


def test_prompt_log_is_private_for_new_and_existing_files():
    # 수정 전: 664 로 만들어지고 기존 664 파일은 그대로였다.
    with tempfile.TemporaryDirectory() as tmp:
        root, env = make_root(tmp)
        for key in ("CLAUDE_PROMPT_LOG_SKIP",):
            env.pop(key, None)
        log_path = root / ".claude" / "_evolve" / "prompts.jsonl"
        r = run(["bash", str(SCRIPTS / "prompt-log.sh")], env, input_text=prompt_payload("첫 프롬프트"))
        assert r.returncode == 0 and log_path.exists()
        assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
        log_path.chmod(0o664)
        run(["bash", str(SCRIPTS / "prompt-log.sh")], env, input_text=prompt_payload("둘째 프롬프트"))
        assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
        assert len(log_path.read_text(encoding="utf-8").splitlines()) == 2


def t41_home(tmp):
    home = Path(tmp)
    claude = home / ".claude"
    for d in ("_audit", "_usage", "agents", "_evolve"):
        (claude / d).mkdir(parents=True, exist_ok=True)
    (claude / "scripts").symlink_to(SCRIPTS)
    (claude / "agents" / "coder.md").write_text("# coder\n", encoding="utf-8")
    (claude / "_audit" / "history.md").write_text("# history\n", encoding="utf-8")
    return home


def t41_rows(home, last_text):
    tp = home / "agent.jsonl"
    tp.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": last_text}]}},
                             ensure_ascii=False) + "\n", encoding="utf-8")
    env = dict(os.environ, HOME=str(home))
    subprocess.run(["bash", str(SCRIPTS / "t41-subagent-stop.sh")], env=env, cwd=str(SCRIPTS.parent), text=True,
                   input=json.dumps({"hook_event_name": "SubagentStop", "name": "coder", "agent_transcript_path": str(tp)}),
                   capture_output=True, timeout=60)
    hist = (home / ".claude" / "_audit" / "history.md").read_text(encoding="utf-8")
    return [ln for ln in hist.splitlines() if "T41:" in ln]


def test_t41_result_line_wins_and_zero_fail_is_not_a_signal():
    # 수정 전: 행두 «FAIL 0건» 이 정규식에 맞아 약점 신호로 기록됐다.
    with tempfile.TemporaryDirectory() as tmp:
        assert t41_rows(t41_home(tmp), "검증 결과\nFAIL 0건\nRESULT: DONE") == []
    with tempfile.TemporaryDirectory() as tmp:
        assert t41_rows(t41_home(tmp), "요약\nFAIL 3건 있었으나 모두 수정됨\nRESULT: DONE") == [], "RESULT 줄이 우선"
    with tempfile.TemporaryDirectory() as tmp:
        assert t41_rows(t41_home(tmp), "시험\nFAIL 0건 통과") == [], "RESULT 줄 없이도 0건은 신호가 아니다"
    with tempfile.TemporaryDirectory() as tmp:
        rows = t41_rows(t41_home(tmp), "시험\nRESULT: FAIL 검증 실패")
        assert len(rows) == 1 and "RESULT: FAIL" in rows[0]
    with tempfile.TemporaryDirectory() as tmp:
        rows = t41_rows(t41_home(tmp), "BLOCKED: 권한 없음")
        assert len(rows) == 1, "RESULT 줄이 없는 단독 BLOCKED 는 여전히 신호"


def test_t41_free_text_is_masked_and_cut_to_80():
    with tempfile.TemporaryDirectory() as tmp:
        rows = t41_rows(t41_home(tmp), "RESULT: FAIL 키 " + T_ANT + " 환자 " + UID + " " + "가" * 200)
        assert len(rows) == 1
        assert T_ANT not in rows[0] and UID not in rows[0] and "<masked>" in rows[0]
        assert "가" * 81 not in rows[0]


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"OK   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001 — 실패 사유를 그대로 보여 준다
            failed += 1
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {str(exc)[:300]}")
    print(f"\n{'ALL PASS' if failed == 0 else f'FAIL {failed}'} ({len(TESTS)} cases)")
    sys.exit(1 if failed else 0)
