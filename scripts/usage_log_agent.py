"""SubagentStop helper of usage-log.sh: append one agent-runs «stop» line (intent/2026-11-24-harness-review-six-items.md 개정 2 W14).

Usage: printf '%s' "$INPUT" | python3 -I usage_log_agent.py <session8> <caller>   (called by usage-log.sh only)
Exit code: always 0, prints nothing.
Reads: the SubagentStop hook input (agent_id · agent_type · agent_transcript_path · effort.level · last_assistant_message) and the
  subagent transcript. From the transcript only message.model · message.usage numbers · the top-level effort · timestamp are taken;
  message bodies are parsed by json.loads but never copied. The transcript must resolve under ~/.claude/projects/ and end in .jsonl.
Writes: ~/.claude/_usage/agent-runs/YYYY-MM-DD.tsv, no header, mode 600, one os.write per line, opened with
  O_APPEND | O_NOFOLLOW | O_NONBLOCK and kept only if fstat shows a regular file with one hard link.
  stop line: time · session8 · caller · stop · agent_id · agent_type · model · effort · input · output · cache_read · cache_write · ms · status
  model = most frequent message.model of assistant entries (excluding <synthetic>), effort = most frequent top-level effort of
  assistant entries, else the hook input's effort.level. Tokens are summed once per message.id (Claude Code repeats usage on every
  content block of one message). ms = last minus first timestamp in the transcript.
  status = value of the last line-leading «RESULT: <value>» in last_assistant_message if it is in STATUSES, «other» for any other
  value, «none» if absent. No other text of the message is kept.
Limits: Claude Code internal agents may have an empty agent_type (written as -). A missing or unreadable transcript gives - and 0.
  A transcript over FILE_MAX (200MB) is not read: model · tokens · ms are written as - (effort falls back to the hook input).
  A transcript line over LINE_MAX (16MB) is skipped without holding it in memory.
"""
import collections
import contextlib
import datetime
import json
import os
import re
import stat
import sys
import time

STATUSES = {"DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED", "PASS", "FAIL"}
BAD = re.compile(r"[^A-Za-z0-9_.:-]")
RESULT = re.compile(r"^[ \t]*RESULT:[ \t]*([A-Z_]+)\b", re.MULTILINE)
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
# WHY: memory guard asked by the W14 review (2026-11-24): 200MB per transcript, 16MB per line.
FILE_MAX = 200 * 1024 * 1024
LINE_MAX = 16 * 1024 * 1024


def lines(f):
    while raw := f.readline(LINE_MAX + 1):
        if len(raw) <= LINE_MAX:
            yield raw
            continue
        while raw and not raw.endswith(b"\n"):
            raw = f.readline(LINE_MAX + 1)


def clean(v, n=64):
    return BAD.sub("", str(v))[:n] or "-"


def stamp(s):
    if not isinstance(s, str):
        return None
    # WHY: python3 3.10 (this server, /usr/bin/python3) fromisoformat rejects the trailing Z that transcripts use.
    try:
        return datetime.datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return None


def scan(path):
    models, efforts, usage = collections.Counter(), collections.Counter(), {}
    first = last = None
    with open(path, "rb") as f:
        for i, raw in enumerate(lines(f)):
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            t = stamp(e.get("timestamp"))
            if t is not None and t.tzinfo is not None:
                first = t if first is None or t < first else first
                last = t if last is None or t > last else last
            m = e.get("message")
            if e.get("type") != "assistant" or not isinstance(m, dict):
                continue
            if isinstance(m.get("model"), str) and m["model"] != "<synthetic>":
                models[m["model"]] += 1
            if isinstance(e.get("effort"), str):
                efforts[e["effort"]] += 1
            if isinstance(m.get("usage"), dict):
                usage[m.get("id") if isinstance(m.get("id"), str) else f"#{i}"] = m["usage"]
    toks = [sum(u.get(k) for u in usage.values() if isinstance(u.get(k), int)) for k in USAGE_KEYS]
    ms = int((last - first).total_seconds() * 1000) if first is not None else "-"
    model = models.most_common(1)[0][0] if models else "-"
    effort = efforts.most_common(1)[0][0] if efforts else "-"
    return model, effort, toks, ms


def append(line):
    home = os.environ.get("HOME", "")
    if not home.startswith("/") or not os.path.isdir(os.path.join(home, ".claude")):
        return
    d = os.path.join(home, ".claude", "_usage", "agent-runs")
    os.makedirs(d, mode=0o700, exist_ok=True)
    if os.path.islink(d) or not os.path.isdir(d):
        return
    f = os.path.join(d, time.strftime("%Y-%m-%d") + ".tsv")
    fd = os.open(f, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    try:
        st = os.fstat(fd)
        if stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
            os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def main():
    s8, caller = (sys.argv[1:3] + ["-", "main"])[:2]
    d = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    if not isinstance(d, dict):
        return
    model, effort, toks, ms = "-", "-", [0, 0, 0, 0], "-"
    tp = d.get("agent_transcript_path")
    home = os.environ.get("HOME", "")
    if isinstance(tp, str) and tp and home.startswith("/"):
        real = os.path.realpath(tp)
        root = os.path.join(os.path.realpath(os.path.join(home, ".claude")), "projects") + os.sep
        if real.startswith(root) and real.endswith(".jsonl") and os.path.isfile(real):
            if os.path.getsize(real) > FILE_MAX:
                toks = ["-"] * 4
            else:
                model, effort, toks, ms = scan(real)
    if effort == "-" and isinstance(d.get("effort"), dict):
        effort = d["effort"].get("level") or "-"
    status = "none"
    msg = d.get("last_assistant_message")
    hits = RESULT.findall(msg) if isinstance(msg, str) else []
    if hits:
        status = hits[-1] if hits[-1] in STATUSES else "other"
    cols = [time.strftime("%Y-%m-%dT%H:%M:%S%z"), clean(s8, 8), clean(caller, 8), "stop", clean(d.get("agent_id", "")),
            clean(d.get("agent_type", "")), clean(model, 128), clean(effort, 16), *(str(t) for t in toks), str(ms), status]
    append("\t".join(cols)[:4000] + "\n")


if __name__ == "__main__":
    with contextlib.suppress(BaseException):
        main()
    sys.exit(0)
