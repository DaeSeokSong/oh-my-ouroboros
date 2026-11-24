"""Summarise the W14 harness logs under ~/.claude/_usage (intent/2026-11-24-harness-review-six-items.md 개정 2 W14).

Usage: python3 -I scripts/harness_log_report.py [--days N] [--home PATH]
  --days N  the last N calendar days including today, chosen by file name YYYY-MM-DD.tsv (default 7)
  --home    home folder whose .claude is read (default: the current user's home)
Exit code: 0 (2 for bad arguments). Reads only, writes nothing. Prints counts and names only.
Tables:
  1) hooks (hook-runs): event · hook · calls · deny · error · killed · ms median · p95 · max
  2) tools (tool-use): tool · calls · failures
  3) rule files never read in the window: .md under rules · rules-lazy · skills · agents · knowledge · doc-formats and CLAUDE.md
     of the harness root (~/.claude resolved), minus the paths seen in rule-reads (read and loaded:<reason>)
  4) agents (agent-runs stop lines): agent_type · runs · input · output · cache_read · cache_write tokens · ms median · max,
     then mismatches joined by agent_id with launch lines:
       model  observed (transcript message.model) vs expected (launch model argument, else model: of agents/<type>.md);
              an alias (opus · sonnet · haiku) matches when it occurs in the observed id, inherit is not compared
       effort observed (transcript effort field) vs expected (launch effort argument, else effort: of agents/<type>.md)
       launches that passed both an effort argument and a name argument
  Expected values are computed from the call arguments and the definition files; observed values come from the logs.
Input check: the log files are excluded from the write-boundary check (scripts/spawn-tree.sh), so a line not written by the
  loggers may be there. Every line must match SPEC for its folder (agent-runs: by its kind): exact column count, name columns
  only [A-Za-z0-9_.:-] within the logger's length cap, numbers 1-12 ASCII digits (or - where the logger writes -), fixed words
  for verdict · ok · how · status. Any other line is dropped and counted as «형식 밖 줄 N건» under its table. The rule-reads
  path is only compared with file names found on disk and is never printed.
Limits: p95 is nearest-rank. Stop lines without a launch line (agents started by Claude Code itself or before logging began)
  are compared with the definition file only.
"""
import argparse
import collections
import datetime
import math
import os
import re
import statistics
from pathlib import Path

RULE_DIRS = ("rules", "rules-lazy", "skills", "agents", "knowledge", "doc-formats")
DAY = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})\.tsv")
ALIASES = ("opus", "sonnet", "haiku")
NUM = re.compile(r"[0-9]{1,12}")


def _spec(*cols: str) -> list[re.Pattern]:
    return [re.compile(c) for c in cols]


def _name(n: int) -> str:
    return rf"[A-Za-z0-9_.:-]{{1,{n}}}"


# REF: column caps are the loggers' own — scripts/hook-deny-wrap.sh runlog (8 · 8 · 40 · 64 · 128), scripts/usage-log.sh
# (tool 128, how 40, launch columns 64), scripts/usage_log_agent.py (agent_id · type 64, model 128, effort 16).
TIME = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{4}"
NUMD = r"[0-9]{1,12}|-"
SPEC = {
    "hook-runs": _spec(TIME, _name(8), _name(8), _name(40), _name(64), _name(128), r"[0-9]{1,12}",
                       "pass|deny|error|killed", NUMD),
    "tool-use": _spec(TIME, _name(8), _name(8), _name(128), "[01]", NUMD),
    "rule-reads": _spec(TIME, _name(8), _name(8), "read|loaded:" + _name(40), r"[^\x00-\x1f\x7f]{1,1024}"),
    "launch": _spec(TIME, _name(8), _name(8), "launch", _name(64), _name(64), _name(64), _name(64), "[01-]"),
    "stop": _spec(TIME, _name(8), _name(8), "stop", _name(64), _name(64), _name(128), _name(16), NUMD, NUMD, NUMD, NUMD,
                  NUMD, "DONE|DONE_WITH_CONCERNS|NEEDS_CONTEXT|BLOCKED|PASS|FAIL|other|none"),
}


def rows(base: Path, folder: str, days: int) -> tuple[list[list[str]], int]:
    first = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    out, bad = [], 0
    d = base / folder
    if not d.is_dir():
        return out, bad
    for f in sorted(d.iterdir()):
        m = DAY.fullmatch(f.name)
        if not m or m.group(1) < first or f.is_symlink() or not f.is_file():
            continue
        with open(f, encoding="utf-8", errors="replace", newline="\n") as fh:
            for ln in fh:
                r = ln.rstrip("\n").split("\t")
                spec = SPEC.get(r[3] if folder == "agent-runs" and len(r) > 3 else folder)
                if spec and len(r) == len(spec) and all(p.fullmatch(v) for p, v in zip(spec, r)):
                    out.append(r)
                else:
                    bad += 1
    return out, bad


def dropped(n: int) -> None:
    print(f"형식 밖 줄 {n}건\n")


def dist(ms: list[int]) -> tuple[str, str, str]:
    if not ms:
        return "-", "-", "-"
    s = sorted(ms)
    return str(int(statistics.median(s))), str(s[math.ceil(0.95 * len(s)) - 1]), str(s[-1])


def num(v: str) -> int | None:
    return int(v) if NUM.fullmatch(v) else None


def table(head: list[str], body: list[list]) -> None:
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for r in body:
        print("| " + " | ".join(str(x) for x in r) + " |")
    print()


def definition(root: Path, kind: str) -> dict[str, str]:
    f = root / "agents" / f"{kind}.md"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", kind) or not f.is_file():
        return {}
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0] != "---":
        return {}
    out = {}
    for ln in lines[1:]:
        if ln == "---":
            break
        k, sep, v = ln.partition(":")
        if sep and k in ("model", "effort"):
            out[k] = v.strip()
    return out


def model_ok(expected: str, observed: str) -> bool:
    if expected in ALIASES:
        return expected in observed
    return observed.startswith(expected)


def hooks_table(base: Path, days: int) -> None:
    agg = collections.defaultdict(lambda: {"n": 0, "deny": 0, "error": 0, "killed": 0, "ms": []})
    good, bad = rows(base, "hook-runs", days)
    for r in good:
        a = agg[(r[3], r[4])]
        a["n"] += 1
        if r[7] in ("deny", "error", "killed"):
            a[r[7]] += 1
        if num(r[8]) is not None:
            a["ms"].append(num(r[8]))
    print(f"## 1) 훅 실행 (hook-runs, {sum(a['n'] for a in agg.values())}줄)\n")
    body = [[ev, hk, a["n"], a["deny"], a["error"], a["killed"], *dist(a["ms"])]
            for (ev, hk), a in sorted(agg.items(), key=lambda x: (-x[1]["n"], x[0]))]
    table(["event", "hook", "호출", "거부", "오류", "killed", "ms 중앙값", "ms p95", "ms 최대"], body)
    dropped(bad)


def tools_table(base: Path, days: int) -> None:
    agg = collections.defaultdict(lambda: [0, 0])
    good, bad = rows(base, "tool-use", days)
    for r in good:
        agg[r[3]][0] += 1
        agg[r[3]][1] += r[4] == "0"
    print(f"## 2) 도구 사용 (tool-use, {sum(v[0] for v in agg.values())}줄)\n")
    table(["tool", "호출", "실패"], [[t, n, f] for t, (n, f) in sorted(agg.items(), key=lambda x: (-x[1][0], x[0]))])
    dropped(bad)


def rules_table(base: Path, root: Path, days: int) -> None:
    good, bad = rows(base, "rule-reads", days)
    seen = {r[4] for r in good}
    files = {"CLAUDE.md"} if (root / "CLAUDE.md").is_file() else set()
    for top in RULE_DIRS:
        for dirpath, _, names in os.walk(root / top):
            files |= {os.path.relpath(os.path.join(dirpath, n), root) for n in names if n.endswith(".md")}
    unread = sorted(files - seen)
    print(f"## 3) 기간 안에 한 번도 읽히지 않은 규칙 파일 ({len(unread)} / {len(files)}개, 읽힌 경로 {len(seen)}개)\n")
    count = collections.Counter(p.split("/")[0] if "/" in p else p for p in unread)
    table(["폴더", "안 읽힘"], sorted(count.items()))
    for p in unread:
        print(f"- {p}")
    print()
    dropped(bad)


def agents_table(base: Path, root: Path, days: int) -> None:
    launches, stops = {}, []
    good, bad = rows(base, "agent-runs", days)
    for r in good:
        if r[3] == "launch":
            launches[r[4]] = {"type": r[5], "model": r[6], "effort": r[7], "name": r[8]}
        else:
            stops.append(r)
    agg = collections.defaultdict(lambda: {"n": 0, "tok": [0, 0, 0, 0], "ms": []})
    model_bad, effort_bad = collections.Counter(), collections.Counter()
    for r in stops:
        lau = launches.get(r[4], {})
        kind = r[5] if r[5] != "-" else lau.get("type", "-")
        a = agg[kind]
        a["n"] += 1
        a["tok"] = [x + (num(v) or 0) for x, v in zip(a["tok"], r[8:12])]
        if num(r[12]) is not None:
            a["ms"].append(num(r[12]))
        dfn = definition(root, kind)
        want_model = lau.get("model") if lau.get("model", "-") != "-" else dfn.get("model", "-")
        want_effort = lau.get("effort") if lau.get("effort", "-") != "-" else dfn.get("effort", "-")
        if want_model not in ("-", "", "inherit") and r[6] != "-" and not model_ok(want_model, r[6]):
            model_bad[(kind, want_model, r[6])] += 1
        if want_effort not in ("-", "") and r[7] != "-" and want_effort != r[7]:
            effort_bad[(kind, want_effort, r[7])] += 1
    both = collections.Counter(v["type"] for v in launches.values() if v["effort"] != "-" and v["name"] == "1")
    print(f"## 4) 서브 에이전트 (agent-runs, 실행 {len(stops)} · 소집 {len(launches)})\n")
    body = [[k, a["n"], *a["tok"], *dist(a["ms"])[::2]] for k, a in sorted(agg.items(), key=lambda x: (-x[1]["n"], x[0]))]
    table(["agent_type", "실행", "input", "output", "cache_read", "cache_write", "ms 중앙값", "ms 최대"], body)
    print("model 불일치(관측 = 서브 에이전트 기록의 message.model, 기대 = 호출 인자 또는 정의 파일):\n")
    table(["agent_type", "기대", "관측", "건수"], [[*k, n] for k, n in sorted(model_bad.items())])
    print("effort 불일치(관측 = 서브 에이전트 기록의 effort 칸, 기대 = 호출 인자 또는 정의 파일):\n")
    table(["agent_type", "기대", "관측", "건수"], [[*k, n] for k, n in sorted(effort_bad.items())])
    print("effort 인자와 name 인자가 함께 온 소집:\n")
    table(["subagent_type", "건수"], sorted(both.items()))
    dropped(bad)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--home", default=str(Path.home()))
    a = ap.parse_args()
    if a.days < 1:
        ap.error("--days 는 1 이상")
    root = Path(os.path.realpath(Path(a.home) / ".claude"))
    base = Path(a.home) / ".claude" / "_usage"
    print(f"# 하네스 기록 요약 (최근 {a.days}일, {base})\n")
    hooks_table(base, a.days)
    tools_table(base, a.days)
    rules_table(base, root, a.days)
    agents_table(base, root, a.days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
