"""Stop hook check: block a final report whose "needs input:" line asks a choice without a decision popup.

Why (2026-10-28 user quote, a training session): «팝업 안 떴어 왜이래 피드백 보내고 다시 띄워». The session asked the user to choose
(table sign-off, baseline arm) only through the "needs input:" line of the final report, two turns in a row. It repeated the
2026-10-23 incident (model/effort asked as plain text). CLAUDE.md 7.5 already says every choice goes through the decision
popup (mcp__decision-popup__ask), but nothing stopped the text route. Decision N1 (user, 2026-10-28): block, and let a line
marked "(결정 아님)" through. Intent: intent/2026-10-28-needs-input-popup-gate.md.

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
"""
import json
import re
import sys

TAIL_LINES = 4000
TAIL_BYTES = 16 * 1024 * 1024
POPUP_TOOLS = ("mcp__decision-popup__ask", "AskUserQuestion")  # AskUserQuestion: mobile mode basis (2026-10-29)
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
    """Return the text blocks of the last assistant entry in the transcript tail, or ''."""
    last = ""
    for obj in read_tail(path):
        if obj.get("type") != "assistant":
            continue
        content = (obj.get("message") or {}).get("content")
        if isinstance(content, list):
            last = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return last


def read_tail(path):
    """Return parsed JSONL objects from the last TAIL_LINES lines (at most TAIL_BYTES bytes); bad lines are skipped."""
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
    """Return needs-input lines found outside code fences."""
    found, in_fence = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and TARGET.match(line):
            found.append(line)
    return found


def blocks_of(obj):
    """Return the content blocks of a transcript entry (a plain string becomes one text block)."""
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def has_popup_basis(objs):
    """True if a successful (or not yet answered) popup call follows the last confirm message."""
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
    """Read the Stop hook JSON from stdin and print a block decision when needs input lacks a popup basis."""
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
        return  # no readable transcript to judge from: fail-open
    print(json.dumps({"decision": "block", "reason": REASON}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001, S110  # fail-open: a Stop hook must not trap the session on its own error
        pass
    sys.exit(0)
