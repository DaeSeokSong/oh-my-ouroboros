"""Report per-skill usage (30/90 days), zero-use skills and oversized SKILL.md bodies as a GFM table.

Inputs: the usage log written by scripts/skill-usage-log.sh (time, session, skill, caller; TSV) and the skills folder
(`<name>/SKILL.md`, `synced/<hash>/<name>/SKILL.md`). Read-only. The log can be forged, so every skill name is
sanitized again here; malformed lines are not counted, only reported. "Passes without the skill?" is NOT measured:
the table only nominates low-use skills (intent/2026-11-24-harness-review-six-items.md W10).

Run: python3 scripts/skill_usage_report.py [--log PATH] [--skills-dir DIR] [--json]
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

BIG = 20000
MAX_LOG_BYTES = 20 * 1024 * 1024
NAME_BAD = re.compile(r"[^A-Za-z0-9_.:-]")


def clean(name):
    return NAME_BAD.sub("", name)[:80]


def scan_skills(skills_dir):
    found = {}
    for p in sorted(skills_dir.rglob("SKILL.md")):
        parts = p.relative_to(skills_dir).parts
        if len(parts) == 2 and parts[0] != "synced":
            name, synced = parts[0], False
        elif len(parts) == 4 and parts[0] == "synced":
            name, synced = parts[2], True
        else:
            continue
        name = clean(name)
        if not name or not p.is_file():
            continue
        if name not in found or not synced:
            found[name] = {"bytes": p.stat().st_size, "synced": synced}
    return found


def read_log(path, now):
    if not path.is_file():
        return None, 0, False
    with path.open("rb") as f:
        raw = f.read(MAX_LOG_BYTES + 1)
    truncated = len(raw) > MAX_LOG_BYTES
    if truncated:
        raw = raw[:MAX_LOG_BYTES].rsplit(b"\n", 1)[0]
    events, broken = [], 0
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.strip() or line.startswith("time\t"):
            continue
        cols = line.split("\t")
        if len(cols) != 4:
            broken += 1
            continue
        try:
            t = datetime.fromisoformat(cols[0])
            if t.tzinfo is None:
                t = t.astimezone()
            future = t - now > timedelta(days=1)
        except (ValueError, OverflowError, OSError):
            broken += 1
            continue
        skill = clean(cols[2])
        if future or not skill:
            broken += 1
            continue
        events.append((t, skill))
    return events, broken, truncated


def build(log, skills_dir, now):
    skills = scan_skills(skills_dir) if skills_dir.is_dir() else {}
    events, broken, truncated = read_log(log, now)
    stats = {}
    for t, s in events or []:
        d = stats.setdefault(s, {"c30": 0, "c90": 0, "last": t})
        age = now - t
        d["c30"] += age <= timedelta(days=30)
        d["c90"] += age <= timedelta(days=90)
        d["last"] = max(d["last"], t)
    rows = []
    for name in sorted(set(skills) | set(stats)):
        st = stats.get(name, {"c30": 0, "c90": 0, "last": None})
        info = skills.get(name)
        marks = []
        if info is None:
            marks.append("기록에만 있음(플러그인 · 내장)")
        else:
            if st["c90"] == 0:
                marks.append("0회(90일)")
            if info["bytes"] > BIG:
                marks.append("20,000B 초과")
            if info["synced"]:
                marks.append("synced")
        rows.append({"skill": name, "calls30": st["c30"], "calls90": st["c90"],
                     "last": st["last"].strftime("%Y-%m-%d") if st["last"] else None,
                     "bytes": info["bytes"] if info else None, "marks": marks})
    rows.sort(key=lambda r: (r["calls90"], -(r["bytes"] if r["bytes"] is not None else -1), r["skill"]))
    first = min((t for t, _ in events), default=None) if events else None
    in_dir = [r for r in rows if r["bytes"] is not None]
    summary = {"skills": len(in_dir), "record_only": len(rows) - len(in_dir),
               "log_present": events is not None, "first_day": first.strftime("%Y-%m-%d") if first else None,
               "log_days": (now - first).days if first else None,
               "zero_90d": sum(r["calls90"] == 0 for r in in_dir),
               "over_20000": sum(r["bytes"] > BIG for r in in_dir), "broken_lines": broken,
               "log_truncated": truncated}
    return rows, summary


def render(rows, s):
    first = s["first_day"] or ("기록 없음" if not s["log_present"] else "없음")
    out = [f"스킬 {s['skills']}개 · 기록 시작일 {first} · 0회(90일) {s['zero_90d']}개 · 20,000B 초과 {s['over_20000']}개"
           + (f" · 기록에만 있음 {s['record_only']}개" if s["record_only"] else "")]
    if not s["log_present"]:
        out.append("기록 없음: 기록 파일이 아직 없어 호출 수를 전부 0 으로 둔다.")
    elif s["log_days"] is None or s["log_days"] < 90:
        n = s["log_days"] if s["log_days"] is not None else 0
        out.append(f"주의: 기록 시작일로부터 {n}일뿐이라 0회는 아직 판단 근거가 약하다.")
    if s["log_truncated"]:
        out.append(f"기록 파일이 너무 커서 앞 {MAX_LOG_BYTES // 1024 // 1024}MB 만 읽음.")
    if s["broken_lines"]:
        out.append(f"깨진 줄 {s['broken_lines']}건은 세지 않았다.")
    out += ["", "| 스킬 | 30일 호출 | 90일 호출 | 마지막 호출일 | 본문 바이트 | 표시 |", "|---|---:|---:|---|---:|---|"]
    for r in rows:
        b = f"{r['bytes']:,}" if r["bytes"] is not None else "-"
        out.append(f"| {r['skill']} | {r['calls30']} | {r['calls90']} | {r['last'] or '-'} | {b} | {', '.join(r['marks'])} |")
    return "\n".join(out)


def main(argv=None):
    root = Path.home() / ".claude"
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log", type=Path, default=root / "_usage" / "skill-usage.tsv")
    ap.add_argument("--skills-dir", type=Path, default=root / "skills")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows, summary = build(a.log, a.skills_dir, datetime.now().astimezone())
    if a.json:
        print(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2))
    else:
        print(render(rows, summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
