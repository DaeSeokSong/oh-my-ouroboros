"""agent_usage_report.py 회귀 시험: 종류별 · 쌍 · 순서쌍 · model 분포 · 턴당 분포 · 도구 정의 수 · 창 · 본문 비노출 · 공용 함수 재사용.

실행: uv run --no-project --with pytest python -m pytest scripts/tests/test_agent_usage_report.py -q -p no:cacheprovider
REF: knowledge/harness/code-history/scripts__tests__test_agent_usage_report.py.md
"""
import json
import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent_usage_report as aur
import rule_reduction_metrics as rrm

UNTIL = "2026-11-24T00:00:00+09:00"
SECRETS = ("projSecretName", "sess-secret-1", "SECRET PROMPT BODY", "secret description text")


def j(d):
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def human(uid, ts):
    return {"type": "user", "uuid": uid, "timestamp": ts, "origin": {"kind": "human"}, "message": {"role": "user", "content": "hi"}}


def calls(uid, *specs):
    blocks = []
    for i, (tool, typ, model) in enumerate(specs):
        inp = {"description": "secret description text", "prompt": "SECRET PROMPT BODY"}
        if typ is not None:
            inp["subagent_type"] = typ
        if model is not None:
            inp["model"] = model
        blocks.append({"type": "tool_use", "id": f"{uid}-{i}", "name": tool, "input": inp})
    return {"type": "assistant", "uuid": uid, "timestamp": "2026-11-20T00:00:00.000Z",
            "message": {"role": "assistant", "model": "m", "content": blocks, "usage": {"input_tokens": 1}}}


def shape(n):
    return {"type": "api-request-shape", "timestamp": "2026-11-20T00:00:00.000Z",
            "shape": {"system": [], "tools": [{"name": f"t{i}", "description": "d", "input_schema": {}} for i in range(n)]}}


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    d = h / "projects/projSecretName"
    d.mkdir(parents=True)
    s1 = [calls("pre", ("Agent", "scout", None)),
          shape(3),
          human("h1", "2026-11-20T00:00:00.000Z"),
          calls("c1", ("Agent", "coder", "sonnet"), ("Agent", "qa", "sonnet"), ("Agent", "coder", "opus")),
          human("h2", "2026-10-01T00:00:00.000Z"),
          calls("c2", ("Task", "scout", "haiku"), ("Agent", "coder", None)),
          human("h3", "2026-11-21T00:00:00.000Z"),
          shape(5),
          human("h4", "2026-11-22T00:00:00.000Z"),
          calls("c4", ("Agent", "qa", None), ("Agent", "qa", None), ("Agent", "evil type/../x<>", "so nnet!"),
                ("Agent", None, None), ("Agent", "coder", "")),
          human("h5", "2026-05-01T00:00:00.000Z"),
          calls("c5", ("Agent", "coder", None)),
          calls("c1", ("Agent", "coder", "sonnet"))]
    (d / "sess-secret-1.jsonl").write_text("".join(j(e) + "\n" for e in s1), encoding="utf-8")
    (d / "s2.jsonl").write_text("".join(j(e) + "\n" for e in [human("x1", "2026-11-23T00:00:00.000Z"), calls("x2", ("Agent", "scout", "haiku"))]),
                                encoding="utf-8")
    return h


def run(capsys, *args):
    rc = aur.main(list(args))
    out = capsys.readouterr()
    return rc, out.out, out.err


def section(out, title):
    lines = out.split(title, 1)[1].split("\n## ", 1)[0].splitlines()
    return [[c.strip() for c in ln.strip("|").split(" | ")] for ln in lines if ln.startswith("| ") and not ln.startswith("|---")][1:]


def test_report_tables(home, capsys):
    rc, out, err = run(capsys, "--since", "2026-08-26T00:00:00+09:00", "--until", UNTIL, "--home", str(home))
    assert rc == 0, err
    assert "창 안 턴 5 · Agent · Task 호출 11 · 세션(창 안 턴이 있는) 2" in out
    assert "첫 사람 글 앞 호출(시각을 정할 수 없어 표에서 뺌) 1" in out and "중복 항목 1" in out
    t1 = section(out, "## 1.")
    assert t1[0] == ["coder", "3", "4", "4"]
    assert ["qa", "3", "3", "3"] in t1 and ["scout", "1", "2", "2"] in t1
    assert ["eviltype..x", "1", "1", "1"] in t1 and ["(지정 없음)", "1", "1", "1"] in t1
    t2 = section(out, "## 2.")
    assert ["coder", "qa", "2"] in t2 and ["coder", "scout", "1"] in t2
    t3 = section(out, "## 3.")
    assert ["coder", "qa", "1"] in t3 and ["qa", "coder", "1"] in t3 and ["qa", "qa", "1"] in t3 and ["scout", "coder", "1"] in t3
    t4 = {r[0]: r for r in section(out, "## 4.")}
    assert t4["coder"][1:] == ["4", "50.0%", "(인자 없음) 2 · opus 1 · sonnet 1"]
    assert t4["eviltype..x"][3] == "sonnet 1"
    t5 = {r[0]: r[1] for r in section(out, "## 5.")}
    assert t5 == {"0": "1", "1": "1", "2 ~ 3": "2", "4 이상": "1"}
    t6 = section(out, "## 6.")
    assert t6 == [["1", "5", "5", "5", "5", "5", "1"]]
    for s in SECRETS:
        assert s not in out and s not in err


def test_window_30_90_and_default(home, capsys):
    rc, out, _ = run(capsys, "--until", UNTIL, "--home", str(home))
    assert rc == 0 and "창 안 턴 5" in out
    rc, out, _ = run(capsys, "--since", "2026-11-21T00:00:00+09:00", "--until", UNTIL, "--home", str(home))
    assert "창 안 턴 3 · Agent · Task 호출 6" in out


def test_no_shape_records(tmp_path, capsys):
    h = tmp_path / "h"
    (h / "projects/p").mkdir(parents=True)
    (h / "projects/p/s.jsonl").write_text(j(human("a", "2026-11-20T00:00:00.000Z")) + "\n", encoding="utf-8")
    rc, out, _ = run(capsys, "--until", UNTIL, "--home", str(h))
    assert rc == 0 and "기록에 없음" in out and "| 0 | 1 | 100.0% |" in out


def test_reuses_shared_reader():
    assert aur.rrm is rrm and aur.rrm.iter_events is rrm.iter_events


@pytest.mark.parametrize("args", [["--since", "2026-11-01T00:00:00"], ["--since", UNTIL, "--until", "2026-11-01T00:00:00+09:00"], ["--bogus"]])
def test_bad_args(home, capsys, args):
    assert run(capsys, *args, "--home", str(home))[0] == 2


def test_unexpected_exception(home, capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("SECRET PROMPT BODY")

    monkeypatch.setattr(aur, "scan", boom)
    rc, out, err = run(capsys, "--until", UNTIL, "--home", str(home))
    assert rc == 2 and "RuntimeError" in err and "SECRET" not in err and out == ""


def test_writes_nothing(home, capsys):
    before = sorted(home.rglob("*"))
    assert run(capsys, "--until", UNTIL, "--home", str(home))[0] == 0
    assert sorted(home.rglob("*")) == before


def test_row_and_cell_caps(home, capsys, monkeypatch):
    monkeypatch.setattr(rrm, "MAX_ROWS", 2)
    monkeypatch.setattr(aur, "MAX_CELL_ITEMS", 1)
    rc, out, _ = run(capsys, "--since", "2026-08-26T00:00:00+09:00", "--until", UNTIL, "--home", str(home))
    assert rc == 0
    t1 = section(out, "## 1.")
    assert [x[0] for x in t1] == ["coder", "qa", "그 밖 3종 합계"] and t1[2][1:] == ["3", "4", "4"]
    t4 = {x[0]: x for x in section(out, "## 4.")}
    assert set(t4) == {"coder", "qa", "그 밖 3종 합계"} and t4["coder"][3] == "(인자 없음) 2 · 그 밖 2종 2"


def test_deep_and_big_lines_do_not_crash(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(rrm, "MAX_LINE_BYTES", 300_000)
    h = tmp_path / "h"
    (h / "projects/p").mkdir(parents=True)
    lines = [j(human("a", "2026-11-20T00:00:00.000Z")),
             '{"type":"assistant","x":' + "[" * 100_000 + "]" * 100_000 + "}",
             j(calls("b", ("Agent", "x" * 400_000, None))),
             j(calls("c", ("Agent", "qa", None)))]
    (h / "projects/p/s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rc, out, err = run(capsys, "--until", UNTIL, "--home", str(h))
    assert rc == 0, err
    assert "깨진 줄 1 · 큰 줄(읽지 않음) 1" in out and "Agent · Task 호출 1 ·" in out
