"""Tests for scripts/skill_usage_report.py (intent/2026-11-24-harness-review-six-items.md W10 성공 기준 2).

Run: uv run --no-project --with pytest python -m pytest scripts/tests/test_skill_usage_report.py -q
REF: knowledge/harness/code-history/scripts__tests__test_skill_usage_report.py.md
"""
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "skill_usage_report.py"
HEADER = "time\tsession\tskill\tcaller\n"


def ago(**kw):
    return (datetime.now().astimezone() - timedelta(**kw)).isoformat(timespec="seconds")


def make_skill(root, rel, size):
    d = root / rel
    d.mkdir(parents=True)
    (d / "SKILL.md").write_bytes(b"x" * size)


def write_log(path, *entries, raw=()):
    path.write_text(HEADER + "".join(f"{t}\tsess0000\t{s}\tmain\n" for t, s in entries) + "".join(raw))


def report(log, skills, *flags):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), "--log", str(log), "--skills-dir", str(skills), *flags],
                          text=True, capture_output=True, check=False, timeout=30)


def as_json(log, skills):
    r = report(log, skills, "--json")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    return {x["skill"]: x for x in d["rows"]}, d["summary"]


@pytest.fixture
def env(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    return tmp_path / "log.tsv", skills


def test_window_boundaries(env):
    log, skills = env
    make_skill(skills, "a", 10)
    write_log(log, (ago(days=29, hours=23), "a"), (ago(days=30, hours=1), "a"), (ago(days=89, hours=23), "a"),
              (ago(days=90, hours=1), "a"))
    rows, _ = as_json(log, skills)
    assert (rows["a"]["calls30"], rows["a"]["calls90"]) == (1, 3)
    assert rows["a"]["last"] == (datetime.now().astimezone() - timedelta(hours=23 + 24 * 29)).strftime("%Y-%m-%d")


def test_zero_mark_and_summary(env):
    log, skills = env
    make_skill(skills, "used", 10)
    make_skill(skills, "old", 10)
    make_skill(skills, "never", 10)
    write_log(log, (ago(days=1), "used"), (ago(days=200), "old"))
    rows, s = as_json(log, skills)
    assert "0회(90일)" not in rows["used"]["marks"]
    assert "0회(90일)" in rows["old"]["marks"] and "0회(90일)" in rows["never"]["marks"]
    assert (s["skills"], s["zero_90d"], s["over_20000"]) == (3, 2, 0)
    assert s["first_day"] == (datetime.now().astimezone() - timedelta(days=200)).strftime("%Y-%m-%d")


def test_size_boundary(env):
    log, skills = env
    make_skill(skills, "exact", 20000)
    make_skill(skills, "over", 20001)
    write_log(log)
    rows, s = as_json(log, skills)
    assert "20,000B 초과" not in rows["exact"]["marks"] and "20,000B 초과" in rows["over"]["marks"]
    assert s["over_20000"] == 1


def test_synced_form_uses_name_only(env):
    log, skills = env
    make_skill(skills, "synced/abc_def/pdf", 5)
    make_skill(skills, "synced/abc_def/deeper/too/far", 5)
    write_log(log, (ago(days=1), "pdf"))
    rows, s = as_json(log, skills)
    assert set(rows) == {"pdf"} and rows["pdf"]["marks"] == ["synced"] and s["skills"] == 1


def test_log_only_name_marked(env):
    log, skills = env
    make_skill(skills, "a", 5)
    write_log(log, (ago(days=1), "plugin:thing"))
    rows, s = as_json(log, skills)
    assert rows["plugin:thing"]["marks"] == ["기록에만 있음(플러그인 · 내장)"] and rows["plugin:thing"]["bytes"] is None
    assert s["skills"] == 1 and s["record_only"] == 1


def test_broken_lines_counted_not_used(env):
    log, skills = env
    make_skill(skills, "a", 5)
    write_log(log, (ago(days=1), "a"), raw=["only\ttwo\n", "bad-time\ts\ta\tmain\n", f"{ago(days=1)}\ts\t$()\tmain\n",
                                           f"{ago(days=1)}\ts\ta\tmain\textra\n"])
    rows, s = as_json(log, skills)
    assert rows["a"]["calls90"] == 1 and s["broken_lines"] == 4
    out = report(log, skills).stdout
    assert "깨진 줄 4건은 세지 않았다" in out


def test_unconvertible_time_is_broken_not_fatal(env):
    log, skills = env
    make_skill(skills, "a", 5)
    write_log(log, (ago(days=1), "a"), raw=["0001-01-01T00:00:00\ts\ta\tmain\n", "0001-01-01T00:00:00+00:00\ts\ta\tmain\n",
                                           "9999-12-31T23:59:59\ts\ta\tmain\n"])
    r = report(log, skills, "--json")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["summary"]["broken_lines"] == 2 and d["rows"][0]["calls90"] == 1

def test_future_lines_over_one_day_are_broken(env):
    log, skills = env
    make_skill(skills, "a", 5)
    write_log(log, (ago(hours=-12), "a"), (ago(days=-2), "a"), (ago(days=-400), "a"))
    rows, s = as_json(log, skills)
    assert rows["a"]["calls30"] == 1 and s["broken_lines"] == 2


def test_oversized_log_reads_only_the_head(env, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("skill_usage_report_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    log, skills = env
    make_skill(skills, "a", 5)
    write_log(log, *[(ago(days=1), "a")] * 20)
    size = log.stat().st_size
    monkeypatch.setattr(mod, "MAX_LOG_BYTES", size // 2)
    rows, s = mod.build(log, skills, datetime.now().astimezone())
    by = {r["skill"]: r for r in rows}
    assert s["log_truncated"] is True and 0 < by["a"]["calls90"] < 20 and s["broken_lines"] == 0
    assert "기록 파일이 너무 커서 앞" in mod.render(rows, s)
    monkeypatch.setattr(mod, "MAX_LOG_BYTES", size)
    rows, s = mod.build(log, skills, datetime.now().astimezone())
    assert s["log_truncated"] is False and rows[0]["calls90"] == 20


def test_no_log_file(env):
    log, skills = env
    make_skill(skills, "a", 5)
    r = report(log, skills)
    assert r.returncode == 0 and "기록 없음" in r.stdout.splitlines()[0]
    rows, s = as_json(log, skills)
    assert rows["a"]["calls90"] == 0 and s["log_present"] is False and s["zero_90d"] == 1


def test_short_history_warning(env):
    log, skills = env
    make_skill(skills, "a", 5)
    write_log(log, (ago(days=10), "a"))
    out = report(log, skills).stdout
    assert "기록 시작일로부터 10일뿐이라 0회는 아직 판단 근거가 약하다" in out
    write_log(log, (ago(days=100), "a"))
    assert "판단 근거가 약하다" not in report(log, skills).stdout


def test_forged_name_sanitized(env):
    log, skills = env
    write_log(log, (ago(days=1), "evil|name\x1b[31m<script>"))
    rows, _ = as_json(log, skills)
    assert list(rows) == ["evilname31mscript"]
    assert "|name" not in report(log, skills).stdout


def test_sort_and_table_shape(env):
    log, skills = env
    make_skill(skills, "small", 10)
    make_skill(skills, "big", 30000)
    make_skill(skills, "busy", 99999)
    write_log(log, (ago(days=1), "busy"))
    out = report(log, skills).stdout.splitlines()
    table = [ln for ln in out if ln.startswith("| ")]
    assert table[0].startswith("| 스킬 |")
    names = [ln.split("|")[1].strip() for ln in table[1:]]
    assert names == ["big", "small", "busy"]
    assert "30,000" in table[1] and "20,000B 초과" in table[1]
