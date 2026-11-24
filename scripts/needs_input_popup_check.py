"""Stop hook check: block a final report whose "needs input:" line asks a choice without a decision popup.

Intent: intent/2026-10-28-needs-input-popup-gate.md.

Rule: outside code fences, a line that starts (after leading spaces and bold marks) with "needs input:" (case-insensitive)
is a target. No target -> pass. Every target has "(결정 아님)" -> pass (auth/access/run requests are not choices).
Otherwise the transcript tail must show a popup basis: after the LAST user entry containing "[결정 팝업 확인]" there is an
assistant tool_use named mcp__decision-popup__ask (or AskUserQuestion in mobile mode, 2026-10-29) whose tool_result is not is_error and lacks "입력 오류". A tool_result not yet
written (race with the Stop hook) counts as success. No confirm message at all -> search the whole tail window.
Why the open-popup exception: a turn may legitimately end with a popup still waiting for an answer, then write needs input.
Remaining gap: if the user closes a popup without answering, no confirm message follows, so a later needs input passes
(only within the tail window below).

Fail-open: every exception passes silently (a hook bug must never trap the session). Transcript content is never printed.
Run: python3 -I scripts/needs_input_popup_check.py < stop-hook-input.json
REF: knowledge/harness/code-history/scripts__needs_input_popup_check.py.md
"""
import json
import re
import sys

TAIL_LINES = 4000
TAIL_BYTES = 16 * 1024 * 1024
POPUP_TOOLS = ("mcp__decision-popup__ask", "AskUserQuestion")
CONFIRM = "[결정 팝업 확인]"
NOT_DECISION = "(결정 아님)"
TARGET = re.compile(r"^\s*(?:\*+\s*)*needs input:", re.IGNORECASE)
REASON = (
    "최종 보고의 needs input 줄이 사용자에게 무언가를 고르게 하는데, 이 턴에 결정 팝업(mcp__decision-popup__ask)을 띄운 "
    "기록도 답을 기다리는 팝업도 없습니다. 선택을 묻는 것이면 지금 결정 팝업으로(모바일 모드면 AskUserQuestion 으로) 띄우고 턴을 끝내십시오. "
    "인증 · 접근 · 실행처럼 고를 것이 없는 요청이면 needs input 줄에 «(결정 아님)» 을 붙여 다시 쓰십시오. "
    "근거: CLAUDE.md 7.5, 사용자 결정 2026-10-28."
)


def last_message_from_transcript(path):
    last = ""
    for obj in read_tail(path):
        if obj.get("type") != "assistant":
            continue
        content = (obj.get("message") or {}).get("content")
        if isinstance(content, list):
            last = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return last


def read_tail(path):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        raw = f.read()
    lines = raw.decode("utf-8", errors="replace").splitlines()[-TAIL_LINES:]
    objs = []
    for line in lines:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            objs.append(obj)
    return objs


def find_target_lines(text):
    found, in_fence = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and TARGET.match(line):
            found.append(line)
    return found


def blocks_of(obj):
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def has_popup_basis(objs):
    start = 0
    for i, obj in enumerate(objs):
        if obj.get("type") == "user" and any(
            b.get("type") == "text" and CONFIRM in str(b.get("text", "")) for b in blocks_of(obj)
        ):
            start = i + 1
    use_ids, results = [], {}
    for obj in objs[start:]:
        if obj.get("type") not in ("assistant", "user"):
            continue
        for b in blocks_of(obj):
            if obj["type"] == "assistant" and b.get("type") == "tool_use" and b.get("name") in POPUP_TOOLS:
                use_ids.append(b.get("id"))
            elif obj["type"] == "user" and b.get("type") == "tool_result":
                bad = bool(b.get("is_error")) or "입력 오류" in json.dumps(b.get("content", ""), ensure_ascii=False)
                results[b.get("tool_use_id")] = not bad
    return any(results.get(uid, True) for uid in use_ids)


def main():
    data = json.load(sys.stdin)
    if data.get("hook_event_name") != "Stop" or data.get("stop_hook_active"):
        return
    path = data.get("transcript_path")
    text = data.get("last_assistant_message") or ""
    if not text.strip() and path:
        text = last_message_from_transcript(path)
    targets = [ln for ln in find_target_lines(text) if NOT_DECISION not in ln]
    if not targets:
        return
    objs = read_tail(path) if path else []
    if not objs or has_popup_basis(objs):
        return
    print(json.dumps({"decision": "block", "reason": REASON}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001, S110
        pass
    sys.exit(0)
