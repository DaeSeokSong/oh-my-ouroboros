"""PreToolUse hook: check that an Agent spawn prompt carries the five required elements (spawn prompt 5요소).

Rule source: rules-lazy/agent-routing-mcp.md § Spawn prompt 5요소 강제 (intent/2026-11-24-harness-review-six-items.md W4).
Registration (user does it): settings.json PreToolUse, matcher `Agent|Task`,
command `python3 $HOME/.claude/scripts/agent-prompt-gate.py`.

What it checks: for a subagent_type in the config `roster` (the agent table of rules/agent-routing.md), each element
of `markers` counts as present when one of its fixed strings sits in a LABEL POSITION (case-insensitive): at the start
of a line after nothing but spaces (tab, ideographic space and NBSP included), the decoration characters `# - * > [` and
backtick, and list numbers such as `1.` or `2)` followed by a space; then optionally one closing backtick, followed by the
end of the line, `:`, `)`, `]`, `**` or a space plus `(`. Fixed
strings, not regexes, so the config cannot widen the check by accident.
Types listed in `exempt_user_request` (read-only scouts) do not need the user_request element.
Types outside the roster (general-purpose, plugin types such as `codex:...`, `fork`) pass and are logged as `skip`.
The `[SKILL_DEPTH: N]` marker is logged only, never a reason to deny.

Modes (config `mode`): observe = always pass with no output, only a TSV row. enforce = deny when an element is missing,
the reason names the missing elements and the rule source. Switching to enforce is a user decision after the day-7
false-positive table (`--report --days 7`), never automatic (user decision R4).

Failure policy (availability first): a broken hook (config missing, broken JSON, wrong shape, any exception) passes in
BOTH modes and logs a row with verdict `error`.
REF: knowledge/harness/code-todo.md CT-001

Config fields `registered` (YYYY-MM-DD, filled by main at registration) and `report_7d_done` (bool) are bookkeeping
for the future day-7 / day-30 session-start alarm; this hook ignores them (missing or any type is fine).

Log: ~/.claude/_audit/agent-prompt-gate.tsv (HOME based so tests can redirect it; no test-only variables on purpose,
since a variable that moves the log is itself a way to hide it). Columns: time · session(8) · type · mode · missing
elements (comma list or -) · SKILL_DEPTH (yes|no) · verdict (ok|miss|deny|skip|error). The prompt body is never written
here (prompt bodies go to _audit/agent-prompts/ through agent-spawn-log.sh, masked). When the file exceeds 2 MB the
older half is dropped under an exclusive lock. Config is read next to this script (../config/agent-prompt-gate.json).

Report: `python3 agent-prompt-gate.py --report [--days 7]` prints a GFM table of calls and missing counts per type.
REF: knowledge/harness/code-history/scripts__agent-prompt-gate.py.md
"""
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

# WHY: hooks run system python3 3.10 (datetime.UTC is 3.11+)
UTC = timezone.utc  # noqa: UP017
HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(HARNESS, "config", "agent-prompt-gate.json")
TSV_REL = ".claude/_audit/agent-prompt-gate.tsv"
TSV_MAX = 2 * 1024 * 1024
CANON = "rules-lazy/agent-routing-mcp.md § Spawn prompt 5요소 강제"
ELEMENTS = ("objective", "user_request", "tools_sources", "output_format", "task_boundary")
LABELS = {"objective": "목표(objective)", "user_request": "사용자 지시 원문", "tools_sources": "도구 · 자료(tools/sources)",
          "output_format": "출력 형식(output_format)", "task_boundary": "경계(task_boundary)"}
DEPTH_RX = re.compile(r"\[SKILL_DEPTH:\s*\d+\]")
SAFE_RX = re.compile(r"[^A-Za-z0-9_.:-]")
MAX_DAYS = 3650
COUNTS = ("calls", "checked", "missed", *ELEMENTS, "nodepth", "skip", "error")


def tsv_path() -> str:
    return os.path.join(os.path.expanduser("~"), TSV_REL)


def load_config() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)

    def strs(v):
        return isinstance(v, list) and all(isinstance(x, str) and x for x in v)

    if not isinstance(cfg, dict) or cfg.get("mode") not in ("observe", "enforce"):
        raise ValueError("mode must be observe or enforce")
    markers = cfg.get("markers")
    if not isinstance(markers, dict) or any(not strs(markers.get(e)) or not markers[e] for e in ELEMENTS):
        raise ValueError("markers must list fixed strings for every element")
    if not strs(cfg.get("roster")) or not cfg["roster"] or not strs(cfg.get("exempt_user_request")):
        raise ValueError("roster and exempt_user_request must be string lists")
    return cfg


def has_marker(prompt: str, marker: str) -> bool:
    sp = "[ \t　 ]"
    rx = (r"^(?:[ \t　 #*>\[`-]|\d+[.)]" + sp + ")*" + re.escape(marker)
          + r"`?(?=\r?$|[:)\]]|\*\*|" + sp + r"\()")
    return re.search(rx, prompt, re.IGNORECASE | re.MULTILINE) is not None


def missing_elements(prompt: str, sub: str, cfg: dict) -> list:
    need = [e for e in ELEMENTS if not (e == "user_request" and sub in cfg["exempt_user_request"])]
    return [e for e in need if not any(has_marker(prompt, m) for m in cfg["markers"][e])]


def log_row(sid: str, sub: str, mode: str, missing: str, depth: str, verdict: str) -> None:
    row = "\t".join((datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
                     sid, sub, mode, missing, depth, verdict)) + "\n"
    try:
        path = tsv_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+b") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            if os.fstat(f.fileno()).st_size > TSV_MAX:
                f.seek(0)
                data = f.read()
                tail = data[len(data) // 2:]
                tail = tail[tail.find(b"\n") + 1:] if b"\n" in tail else b""
                f.truncate(0)
                f.write(tail)
            f.write(row.encode("utf-8"))
    except Exception:  # noqa: BLE001, S110
        pass


def deny(reason: str) -> None:
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                  "permissionDecisionReason": reason}}
    print(json.dumps(out, ensure_ascii=False))


def gate() -> int:
    sid, sub, mode = "-", "-", "-"
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict) or data.get("tool_name") not in ("Agent", "Task"):
            return 0
        sid = SAFE_RX.sub("", str(data.get("session_id") or ""))[:8] or "-"
        ti = data.get("tool_input") or {}
        raw_sub = ti.get("subagent_type") or "general-purpose"
        prompt = ti.get("prompt") or ""
        if not isinstance(raw_sub, str) or not isinstance(prompt, str):
            raise TypeError("unexpected field type")
        sub = SAFE_RX.sub("", raw_sub)[:64] or "-"
        cfg = load_config()
        mode = cfg["mode"]
        depth = "yes" if DEPTH_RX.search(prompt) else "no"
        if raw_sub not in cfg["roster"]:
            log_row(sid, sub, mode, "-", depth, "skip")
            return 0
        miss = missing_elements(prompt, raw_sub, cfg)
        verdict = "ok" if not miss else ("deny" if mode == "enforce" else "miss")
        log_row(sid, sub, mode, ",".join(miss) or "-", depth, verdict)
    except Exception as exc:  # noqa: BLE001
        log_row(sid, sub, mode, type(exc).__name__, "-", "error")
        return 0
    if verdict == "deny":
        names = ", ".join(LABELS[e] for e in miss)
        deny(f"spawn prompt 필수 요소가 빠졌습니다: {names}. 표지 문자열과 면제 규칙은 정본 {CANON} 을 보십시오.")
    return 0


def report(days: int) -> int:
    since = datetime.now(UTC) - timedelta(days=days)
    stats = {}
    try:
        with open(tsv_path(), encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    for ln in lines:
        c = ln.split("\t")
        if len(c) != 7:
            continue
        try:
            ts = datetime.fromisoformat(c[0])
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts < since:
            continue
        # NEVER: drop this re-filter; the TSV is outside the trust boundary (forged or control text).
        typ = SAFE_RX.sub("", c[2])[:64] or "-"
        s = stats.setdefault(typ, {k: 0 for k in COUNTS})
        s["calls"] += 1
        if c[6] in ("error", "skip"):
            s[c[6]] += 1
            continue
        s["checked"] += 1
        s["missed"] += c[4] != "-"
        s["nodepth"] += c[5] == "no"
        for e in c[4].split(","):
            if e in ELEMENTS:
                s[e] += 1
    print(f"최근 {days}일 agent-prompt-gate 기록 ({tsv_path()})")
    print()
    print("| 타입 | 호출 수 | 검사 대상(skip · error 제외) | 누락 호출(enforce 였다면 거부) | "
          + " | ".join(f"{e} 누락" for e in ELEMENTS) + " | SKILL_DEPTH 없음 | 표 밖(skip) | 훅 오류 |")
    print("|" + "---|" * (len(ELEMENTS) + 7))
    total = {k: 0 for k in COUNTS}
    for t in sorted(stats):
        s = stats[t]
        for k in total:
            total[k] += s[k]
    for name, s in [*((t, stats[t]) for t in sorted(stats)), ("합계", total)]:
        print(f"| {name} | {s['calls']} | {s['checked']} | {s['missed']} | " + " | ".join(str(s[e]) for e in ELEMENTS)
              + f" | {s['nodepth']} | {s['skip']} | {s['error']} |")
    print()
    print("miss 는 표지 기준이라 실제 누락의 하한이다. 지시문 본문은 `_audit/agent-prompts/<날짜>/<시각>-<세션 8자>-<타입>` 에서"
          " 시각 · 세션 · 타입으로 찾는다.")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--report":
        days = 7
        if len(args) == 3 and args[1] == "--days" and args[2].isascii() and args[2].isdigit() and 1 <= int(args[2]) <= MAX_DAYS:
            days = int(args[2])
        elif len(args) != 1:
            print(f"사용법: agent-prompt-gate.py --report [--days N]  (N 은 1 ~ {MAX_DAYS})", file=sys.stderr)
            return 2
        return report(days)
    return gate()


if __name__ == "__main__":
    sys.exit(main())
