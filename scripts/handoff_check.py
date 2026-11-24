"""Stop hook check: block a working turn when the session handoff file is missing or stale.

Format and location are defined in rules-lazy/session-handoff.md.
Contract: stdin = Stop hook JSON; prints one {"decision":"block","reason":...} line or nothing.
Fail-open: any error prints nothing so this hook never blocks work by itself.

Review-turn exemption: a turn that ends by asking a Confluence publish-approval question and
waiting for the answer is exempt.
  - exempt only when the LAST tool_use after the last real user message is a publish-approval AskUserQuestion and no
    tool_result with that tool_use id is recorded yet (asked, answer pending). Any later tool_use, an answered question,
    a question from an earlier turn, another tool, or a tool_use without a string id gives no exemption;
  - "publish approval" is whatever confluence_publish_approve.is_approval_question accepts (one valid approval line plus a
    «게시 승인» option); the condition is defined there, not copied here. That module is loaded at most once per run, and only
    when the last tool_use is an AskUserQuestion;
  - any error while judging (module load, odd entry shape) means "not exempt", i.e. the pre-existing behavior.
REF: knowledge/harness/code-history/scripts__handoff_check.py.md
"""
import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import time

TAIL_BYTES = 2 * 1024 * 1024
APPROVE_MODULE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "confluence_publish_approve.py")


def find_root(cwd):
    r = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                       check=False, capture_output=True, text=True, timeout=2)
    if r.returncode == 0 and r.stdout.strip():
        return os.path.realpath(r.stdout.strip())
    home = os.path.realpath(os.path.expanduser("~/.claude"))
    real = os.path.realpath(cwd)
    return home if real == home or real.startswith(home + os.sep) else None


def is_publish_ask(block):
    if block.get("name") != "AskUserQuestion":
        return False
    try:
        spec = importlib.util.spec_from_file_location("confluence_publish_approve", APPROVE_MODULE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return bool(mod.is_approval_question(block.get("input")))
    except Exception:  # noqa: BLE001
        return False


def scan_turn(path):
    answered = set()
    with open(path, "rb") as f:
        size = f.seek(0, os.SEEK_END)
        f.seek(max(0, size - TAIL_BYTES))
        data = f.read()
    lines = data.splitlines()
    if size > TAIL_BYTES and lines:
        lines = lines[1:]
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(e, dict) or e.get("isSidechain"):
            continue
        content = (e.get("message") or {}).get("content")
        if e.get("type") == "assistant" and isinstance(content, list):
            uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            if uses:
                last = uses[-1]
                return True, isinstance(last.get("id"), str) and last["id"] not in answered and is_publish_ask(last)
        elif e.get("type") == "user":
            if isinstance(content, str):
                break
            if isinstance(content, list):
                if any(isinstance(b, dict) and b.get("type") != "tool_result" for b in content):
                    break
                answered.update(b["tool_use_id"] for b in content if isinstance(b, dict) and isinstance(b.get("tool_use_id"), str))
    return False, False


def main():
    inp = json.load(sys.stdin)
    if inp.get("stop_hook_active"):
        return
    sid, cwd, tp = inp.get("session_id"), inp.get("cwd"), inp.get("transcript_path")
    if not (sid and cwd and tp):
        return
    root = find_root(cwd)
    if not root:
        return
    worked, review = scan_turn(tp)
    if not worked or review:
        return
    try:
        limit = int(os.environ.get("HANDOFF_STALE_MIN", "30"))
    except ValueError:
        limit = 30
    path = os.path.join(root, ".scratch", "handoff", str(sid)[:8] + ".md")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) <= limit * 60:
        return
    reason = (f"작업 현황 파일을 갱신하십시오: {path}. 토큰이 떨어져도 Grok 이 이 파일만 보고 이어받을 수 있게 "
              "형식(rules-lazy/session-handoff.md)대로 지금 상태를 적고 끝내십시오.")
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


if __name__ == "__main__":
    with contextlib.suppress(Exception):
        main()
