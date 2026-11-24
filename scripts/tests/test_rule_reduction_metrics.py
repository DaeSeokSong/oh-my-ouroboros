"""rule_reduction_metrics.py 회귀 시험: 사람 글 판정 · 턴 · M1 ~ M7 · 이득 · 창 · 하네스 기록 · 본문 비노출 · 쓰기 가드 · 방어.

실행: uv run --no-project --with pytest python -m pytest scripts/tests/test_rule_reduction_metrics.py -q -p no:cacheprovider
REF: knowledge/harness/code-history/scripts__tests__test_rule_reduction_metrics.py.md
"""
import json
import os
import stat
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rule_reduction_metrics as rrm

POPUP, ASK = rrm.POPUP, rrm.ASK
SINCE, UNTIL = "2026-11-17T00:00:00+09:00", "2026-11-24T00:00:00+09:00"
SECRETS = ("projA-secret-name", "sess-aaaa-1111", "do X secret prompt", "/home/secret/cwd", "추가 요청 비밀")


def j(d) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def user(uid, text, ts="2026-11-20T01:00:00.000Z", **kw):
    return {"type": "user", "uuid": uid, "timestamp": ts, "isSidechain": False, "cwd": "/home/secret/cwd",
            "message": {"role": "user", "content": text}, **kw}


def result(uid, tid, content="ok", is_error=False):
    return {"type": "user", "uuid": uid, "timestamp": "2026-11-20T01:00:01.000Z", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": content, "is_error": is_error}]}}


def asst(uid, *blocks, usage=None, **kw):
    m = {"role": "assistant", "model": kw.pop("model", "claude-x"), "content": list(blocks),
         "usage": usage or {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}
    return {"type": "assistant", "uuid": uid, "timestamp": "2026-11-20T01:00:02.000Z", "isSidechain": False, "message": m, **kw}


def text(t):
    return {"type": "text", "text": t}


def tool(tid, name, inp=None):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp or {}}


def write_session(home, proj, sid, entries, mtime=None):
    d = home / "projects" / proj
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{sid}.jsonl"
    p.write_text("".join((e if isinstance(e, str) else j(e)) + "\n" for e in entries), encoding="utf-8")
    if mtime:
        t = datetime.fromisoformat(mtime).timestamp()
        os.utime(p, (t, t))
    return p


def main_session():
    first = asst("a0", text("API Error"), model="<synthetic>", isApiErrorMessage=True,
                 usage={"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})
    a1 = asst("a1", text("[이해] 무엇을: x"), tool("t1", "Bash", {"command": "ls"}),
              usage={"input_tokens": 10, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 5})
    return [
        {"type": "mode", "mode": "x"},
        user("u1", "do X secret prompt", origin={"kind": "human"}),
        first, a1,
        j(a1),
        '{"type":"user","uuid":"zz", broken',
        "{broken json without type marker",
        result("r1", "t1"),
        user("u2", "<task-notification>done</task-notification>", origin={"kind": "task-notification"}),
        asst("a2", text("결과 ① 이고 `②` 와\n```\n③\n```\n수식 $\\frac{a}{b}$ 와 $5 그리고 $10")),
        user("u3", "질문입니다"),
        asst("a3", text("답입니다")),
        user("u4", "[결정 팝업 확인]\n- 1) 고름", origin={"kind": "plugin", "name": "decision-popup"}),
        user("u5", "<command-name>/commit</command-name><command-args></command-args>"),
        asst("a5", text("작업합니다"), tool("t5", POPUP, {"items": [{"title": "A (추천)"}]}),
             tool("t6", POPUP, {"recommended": True, "items": [{"title": "B"}]}),
             tool("t7", ASK, {"questions": [{"options": [{"label": "Go (Recommended)"}]}]}),
             tool("t8", "Agent", {"description": "sonnet: x", "model": "sonnet", "prompt": "[SKILL_DEPTH: 0] go"}),
             tool("t9", "Agent", {"description": "opus: y", "model": "sonnet", "prompt": "go"}),
             tool("t10", "Task", {"description": "plain z", "prompt": "[SKILL_DEPTH: 1]"}),
             tool("t11", "Agent", {"description": "haiku: w", "prompt": "go"})),
        asst("a5s", tool("t12", ASK, {"q": "추천"}), isSidechain=True),
        result("r5", "t5", "PreToolUse:Bash hook error: [쓰기 차단] 파일 쓰기", is_error=True),
        result("r6", "t6", "PreToolUse:Edit hook error: [!!<bad>] x", is_error=True),
        user("u6", "<weird-tag>x</weird-tag>"),
        {"type": "attachment", "uuid": "q1", "timestamp": "2026-11-20T01:05:00.000Z",
         "attachment": {"type": "queued_command", "commandMode": "prompt", "origin": {"kind": "human"}, "prompt": "추가 요청 비밀"}},
        user("u7", "추가 요청 비밀", origin={"kind": "human"}),
        asst("a7", text("[이해] 무엇을: y"), tool("t13", "Bash", {"command": "pwd"})),
        user("u8", "Another Claude session sent a message: hi"),
    ]


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    for sub in ("_audit", "_evolve", "_usage"):
        (h / sub).mkdir(parents=True)
    write_session(h, "projA-secret-name", "sess-aaaa-1111", main_session())
    write_session(h, "projB", "s2", [user("b1", "hello", ts="2026-11-21T00:00:00.000Z"), asst("b2", text("작업"), tool("bt", "Bash"))])
    write_session(h, "projB", "s-old-start", [user("c1", "old", ts="2026-11-10T00:00:00.000Z"), asst("c2", tool("ct", "Bash"))])
    write_session(h, "projB", "s-old-mtime", [user("d1", "x", ts="2026-11-20T00:00:00.000Z")], mtime="2026-11-10T00:00:00+09:00")
    write_session(h, "projB", "s-after", [user("e1", "x", ts="2026-11-24T00:00:00.000+09:00")])
    (h / "_audit/plan-confirm-gate.tsv").write_text(
        "2026-11-18T01:00:00.123+00:00\tsid\tWrite\t등록 전 시작 세션이라 막지 않음: 확정 없이 바꾸는 호출(direct)\n"
        "2026-11-18T02:00:00+00:00\tsid\tBash\t등록 전 시작 세션이라 막지 않음: 판정 불가(대화 기록의 형식을 알아볼 수 없습니다)\n"
        "2026-11-25T01:00:00+00:00\tsid\tWrite\t등록 전 시작 세션이라 막지 않음: 확정 없이 바꾸는 호출(final)\n", encoding="utf-8")
    (h / "_audit/hook-deny.tsv").write_text("2026-11-18T10:00:00+0900\tabcd1234\tmain\tbash-write-check\tBash\t1\n"
                                            "2026-11-18T10:00:00+0900\tabcd1234\tmain\tevil|<x>\tBash\t1\n"
                                            "2026-11-25T10:00:00+0900\tabcd1234\tmain\tbash-write-check\tBash\t1\n", encoding="utf-8")
    (h / "_evolve/prompts.jsonl").write_text("".join(j({"ts": t, "cwd": "/home/secret/cwd", "prompt": "do X secret prompt"}) + "\n" for t in
                                                     ("2026-11-18T00:00:00Z", "2026-11-19T00:00:00Z", "2026-11-20T00:00:00Z", "2026-11-25T00:00:00Z"))
                                             + "{bad\n", encoding="utf-8")
    (h / "_evolve/candidates.tsv").write_text("id\tsource\t생성일\tbench_id\tstatus\t요약\tnote\n"
                                              "c1\tT12\t2026-11-20\t\tpending\ts\t\nc2\tT12\t2026-11-25\t\tpending\ts\t\n"
                                              "c3\tT40\t2026-11-20\t\tpending\ts\t\n", encoding="utf-8")
    (h / "_audit/history.md").write_text("# h\n- 2026-11-20 T41: coder/x — sig\n- 2026-11-10 T41: coder/x — sig\n- 2026-11-20 T12: no\n", encoding="utf-8")
    (h / "_audit/agent-spawn.log").write_text("2026-11-20T10:00:00+09:00\tpost\tcoder\t-\tsonnet\td\n"
                                              "2026-11-20T10:00:01+09:00\tpost\tqa\t-\tsonnet\td\n"
                                              "2026-11-20T10:00:00+09:00\tpre\tcoder\t-\tsonnet\td\n"
                                              "2026-11-25T10:00:00+09:00\tpost\tcoder\t-\tsonnet\td\n", encoding="utf-8")
    return h


def run(capsys, *args):
    rc = rrm.main(list(args))
    out = capsys.readouterr()
    return rc, out.out, out.err


def rows(out):
    res = {}
    for ln in out.splitlines():
        if ln.startswith("| ") and not ln.startswith(("| 지표", "| 프로젝트", "|---")):
            c = [x.strip() for x in ln.strip("|").split(" | ")]
            res[c[0]] = c[1:]
    return res


@pytest.mark.parametrize(("entry", "want"), [
    (user("x", "hi", origin={"kind": "human"}), "human"),
    (user("x", "hi"), "human"),
    (user("x", "<command-name>/x</command-name>"), "human"),
    (user("x", "<pasted_content>a</pasted_content>", origin={"kind": "human"}), "human"),
    (user("x", "<bash-input>ls</bash-input>"), "human"),
    (user("x", [{"type": "image"}]), "human"),
    (user("x", "hi", isMeta=True), "other"),
    (user("x", "summary", isCompactSummary=True), "other"),
    (user("x", "hi", origin={"kind": "task-notification"}), "other"),
    (user("x", "hi", origin={"body": "[Subagent hand-back] r"}), "other"),
    (user("x", "hi", origin={"kind": "plugin", "name": "decision-popup"}), "other"),
    (user("x", "[Request interrupted by user]"), "other"),
    (user("x", "<local-command-stdout>x</local-command-stdout>"), "other"),
    (user("x", "<system-reminder>x</system-reminder>"), "other"),
    (user("x", "a <cross-session-message from=x>"), "other"),
    (user("x", "   "), "other"),
    (user("x", "<new-tag>x</new-tag>"), "unknown"),
])
def test_classify_user(entry, want):
    assert rrm.classify_user(entry) == want


def test_full_report(home, capsys):
    rc, out, err = run(capsys, "--since", SINCE, "--until", UNTIL, "--label", "t1", "--home", str(home))
    assert rc == 0, err
    r = rows(out)
    assert "세션(고른 턴이 있는) 2 · 프로젝트 2 · 읽은 파일 4 · 창 밖 파일(수정 시각) 1 · 건너뛴 파일 0" in out
    assert "턴: 창 안 5 · --rules-since 로 빠짐 0 · 고른 턴 5 · 재로드 지점(창 안) 세션 시작 2 · compact 0" in out
    assert "compact 가 없어 통째로 빠진 세션 해당 없음(--rules-since 없음)" in out
    assert "깨진 줄 1 · 큰 줄(읽지 않음) 0 · 중복 항목(같은 uuid) 1 · API 오류 대리 항목 1" in out
    assert "분류 불가 user 항목 1" in out
    assert r["M1 [이해] 부착률"][:3] == ["50.0%", "2", "4"]
    assert "첫 tool_use 앞 2" in r["M1 [이해] 부착률"][3] and "고른 턴 5" in r["M1 [이해] 부착률"][3]
    assert r["M2 결정 팝업 추천 혼입"][:3] == ["50.0%", "1", "2"]
    assert r["M2 선택 창 추천 혼입"][:3] == ["100.0%", "1", "1"]
    assert r["M3 원문자 (100턴당)"][:3] == ["20.00", "1", "5"]
    assert r["M3 LaTeX 꼴 (100턴당)"][:3] == ["20.00", "1", "5"]
    assert r["M3 반말 종결 비율"][0] == "미측정(판정기 없음)"
    assert r["M4 계획 확정 경고 direct (작업성 100턴당)"][:3] == ["25.00", "1", "4"]
    assert r["M4 계획 확정 경고 판정 불가 (작업성 100턴당)"][:3] == ["25.00", "1", "4"]
    assert "M4 계획 확정 경고 final (작업성 100턴당)" not in r
    assert r["M4 hook-deny bash-write-check (작업성 100턴당)"][:3] == ["25.00", "1", "4"]
    assert r["M4 hook-deny 기타 (작업성 100턴당)"][:3] == ["25.00", "1", "4"]
    assert r["M4 대화 기록 훅 차단 [쓰기 차단] (작업성 100턴당)"][:3] == ["25.00", "1", "4"]
    assert r["M4 대화 기록 훅 차단 [기타] (작업성 100턴당)"][:3] == ["25.00", "1", "4"]
    assert r["M5 T12 후보 (프롬프트 100개당)"][:3] == ["33.33", "1", "3"]
    assert r["M6 T41 기록 (spawn 100개당)"][:3] == ["50.00", "1", "2"]
    assert r["M7 description 모델 접두 일치"][:3] == ["50.0%", "2", "4"]
    assert "접두 없음 1 · 불일치 1 · 일치 중 model 인자 없음 1" in r["M7 description 모델 접두 일치"][3]
    assert r["M7 [SKILL_DEPTH 포함"][:3] == ["50.0%", "2", "4"]
    assert r["이득 세션 시작 첫 응답 입력 토큰 중앙값"][:3] == ["5.5", "-", "2"]
    assert r["이득 세션 시작 첫 응답 cache 생성 토큰 중앙값"][0] == "500"
    assert r["이득 세션 시작 첫 응답 합계(입력 + cache 생성 + 읽기) 중앙값"][0] == "508"
    assert r["이득 compact 직후 첫 응답 입력 토큰 중앙값"][:3] == ["해당 없음", "-", "0"]
    assert "재로드 경계 미적용" in r["M5 T12 후보 (프롬프트 100개당)"][3] and "재로드 경계 미적용" in r["M6 T41 기록 (spawn 100개당)"][3]
    assert "| P1 | 1 | 4 | 3 | 66.7% | 2/3 | 1 | 1 | 50.0% |" in out
    assert "| P2 | 1 | 1 | 1 | 0.0% | 0/0 | 0 | 0 | 해당 없음 |" in out
    assert "상태: 완전" in out
    for s in SECRETS:
        assert s not in out and s not in err


def test_no_sessions_gives_not_applicable(tmp_path, capsys):
    h = tmp_path / "h"
    (h / "projects").mkdir(parents=True)
    rc, out, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--home", str(h))
    r = rows(out)
    assert rc == 0
    assert r["M1 [이해] 부착률"][0] == "해당 없음" and r["M5 T12 후보 (프롬프트 100개당)"][0] == "해당 없음"
    assert r["이득 세션 시작 첫 응답 입력 토큰 중앙값"][0] == "해당 없음"
    assert "plan-confirm-gate.tsv: 없음" in out and "hook-deny.tsv 없음" in out


def test_links_and_size_cap(home, capsys, monkeypatch):
    target = home / "projects/projB/s2.jsonl"
    os.symlink(target, home / "projects/projB/link.jsonl")
    os.symlink(home / "projects/projB", home / "projects/projLink")
    cap = target.stat().st_size
    monkeypatch.setattr(rrm, "MAX_FILE_BYTES", cap)
    opened = [p for p in (home / "projects").glob("*/*.jsonl")
              if not p.is_symlink() and not p.parent.is_symlink() and p.stat().st_mtime >= datetime.fromisoformat(SINCE).timestamp()]
    big = sum(p.stat().st_size > cap for p in opened)
    rc, out, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--home", str(home))
    assert rc == 0 and big >= 1
    assert f"건너뛴 파일 {big + 1}(까닭: 링크 · 일반 파일 아님 1 · 크기 상한 초과 {big})" in out
    assert "세션(고른 턴이 있는) 1 · 프로젝트 1" in out


def rules_home(tmp_path):
    h = tmp_path / "rh"
    (h / "projects").mkdir(parents=True)

    def turns(prefix, n, day, hour0=0):
        out = []
        for i in range(n):
            out += [user(f"{prefix}u{i}", f"q{i}", ts=f"2026-11-{day}T{hour0 + i:02d}:00:00.000Z"),
                    asst(f"{prefix}a{i}", text("[이해] x"), tool(f"{prefix}t{i}", "Bash"))]
        return out

    boundary = {"type": "system", "subtype": "compact_boundary", "uuid": "xb", "timestamp": "2026-11-19T00:00:00.000Z",
                "compactMetadata": {"trigger": "auto"}}
    summary = user("xs", "This session is being continued from a previous conversation", ts="2026-11-18T23:59:30.000Z", isCompactSummary=True)
    after_usage = asst("xa", text("요약 뒤"), usage={"input_tokens": 7, "cache_creation_input_tokens": 70000, "cache_read_input_tokens": 3})
    write_session(h, "p1", "x", [user("x0", "start", ts="2026-11-10T00:00:00.000Z"), asst("x00", text("a"))]
                  + turns("xo", 3, 18) + [boundary, summary, after_usage] + turns("xn", 5, 20))
    write_session(h, "p1", "y", turns("y", 2, 21))
    write_session(h, "p2", "z", [user("z0", "start", ts="2026-11-15T00:00:00.000Z")] + turns("z", 4, 20))
    return h


def test_rules_since_counts_only_reloaded_turns(tmp_path, capsys):
    h = rules_home(tmp_path)
    rc, out, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--home", str(h))
    assert rc == 0
    assert "턴: 창 안 14 · --rules-since 로 빠짐 0 · 고른 턴 14 · 재로드 지점(창 안) 세션 시작 1 · compact 1" in out
    rc, out, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--rules-since", SINCE, "--home", str(h))
    r = rows(out)
    assert rc == 0
    assert "턴: 창 안 14 · --rules-since 로 빠짐 7 · 고른 턴 7 · 재로드 지점(창 안) 세션 시작 1 · compact 1" in out
    assert "compact 가 없어 통째로 빠진 세션 1" in out
    assert r["M1 [이해] 부착률"][:3] == ["100.0%", "7", "7"]
    assert "세션(고른 턴이 있는) 2 · 프로젝트 1" in out
    assert r["이득 세션 시작 첫 응답 입력 토큰 중앙값"][:3] == ["1", "-", "1"]
    assert r["이득 compact 직후 첫 응답 cache 생성 토큰 중앙값"][:3] == ["70000", "-", "1"]
    rc, out, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--rules-since", "2026-11-19T00:00:01+00:00", "--home", str(h))
    assert "고른 턴 2 ·" in out


def test_summary_without_boundary_is_reload(tmp_path, capsys):
    h = tmp_path / "h"
    (h / "projects").mkdir(parents=True)
    write_session(h, "p", "s", [user("a", "q", ts="2026-11-10T00:00:00.000Z"),
                                user("b", "summary", ts="2026-11-18T00:00:00.000Z", isCompactSummary=True),
                                user("c", "q2", ts="2026-11-18T01:00:00.000Z"), asst("d", tool("t", "Bash"))])
    rc, out, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--rules-since", SINCE, "--home", str(h))
    assert rc == 0 and "고른 턴 1 · 재로드 지점(창 안) 세션 시작 0 · compact 1" in out


def test_time_budget_partial(home, capsys, monkeypatch):
    monkeypatch.setattr(rrm, "TIME_BUDGET_S", -1.0)
    rc, out, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--home", str(home))
    assert rc == 0 and "부분 결과(시간 예산 -1초 초과," in out and "번째 파일에서 멈춤" in out


def test_out_writes_600_and_never_overwrites(home, capsys):
    rc, _, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--label", "base.1", "--home", str(home), "--out")
    f = home / "_audit/rule-reduction/base.1.md"
    assert rc == 0 and f.is_file() and stat.S_IMODE(f.stat().st_mode) == 0o600
    assert f.read_text(encoding="utf-8").startswith("# 상시 규칙 축소 지표: base.1")
    f.write_text("keep", encoding="utf-8")
    rc, _, err = run(capsys, "--since", SINCE, "--until", UNTIL, "--label", "base.1", "--home", str(home), "--out")
    assert rc == 2 and "이미 있어" in err and f.read_text(encoding="utf-8") == "keep"


def test_out_refuses_links(home, capsys, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, home / "_audit/rule-reduction")
    rc, _, err = run(capsys, "--since", SINCE, "--until", UNTIL, "--label", "x", "--home", str(home), "--out")
    assert rc == 2 and "링크" in err and list(outside.iterdir()) == []
    (home / "_audit/rule-reduction").unlink()
    (home / "_audit/rule-reduction").mkdir()
    os.symlink(outside / "victim.md", home / "_audit/rule-reduction/y.md")
    rc, _, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--label", "y", "--home", str(home), "--out")
    assert rc == 2 and not (outside / "victim.md").exists()


def test_out_refuses_linked_audit(tmp_path, capsys):
    h, outside = tmp_path / "h", tmp_path / "outside"
    (h / "projects").mkdir(parents=True)
    outside.mkdir()
    os.symlink(outside, h / "_audit")
    rc, _, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--label", "x", "--home", str(h), "--out")
    assert rc == 2 and list(outside.iterdir()) == []


@pytest.mark.parametrize("label", ["../x", "a/b", "", "x" * 41, "한글", "a b", ".", "..", "base\n"])
def test_bad_label(home, capsys, label):
    rc, _, err = run(capsys, "--since", SINCE, "--until", UNTIL, "--label", label, "--home", str(home), "--out")
    assert rc == 2 and "label" in err
    assert not (home / "_audit/rule-reduction").exists()


@pytest.mark.parametrize(("since", "until"), [("2026-11-17T00:00:00", UNTIL), (UNTIL, SINCE), ("x", UNTIL), (SINCE, None)])
def test_bad_window(home, capsys, since, until):
    args = ["--since", since, "--home", str(home)] + (["--until", until] if until else [])
    assert run(capsys, *args)[0] == 2


def test_mark_window(home, capsys, tmp_path):
    f = home / "_usage/rule-reduction-window"
    rc, _, _ = run(capsys, "--mark-window", "base", "--end", "2026-12-01", "--home", str(home))
    assert rc == 0 and f.read_text(encoding="utf-8") == "base\t2026-12-01\n" and stat.S_IMODE(f.stat().st_mode) == 0o600
    rc, _, _ = run(capsys, "--mark-window", "after", "--end", "2026-12-08", "--home", str(home))
    assert rc == 0 and f.read_text(encoding="utf-8") == "after\t2026-12-08\n"
    for end in ("2026-02-30", "2026/12/01", "", "2026-12-01x"):
        assert run(capsys, "--mark-window", "base", "--end", end, "--home", str(home))[0] == 2
    assert run(capsys, "--mark-window", "../x", "--end", "2026-12-01", "--home", str(home))[0] == 2
    victim = tmp_path / "victim"
    victim.write_text("v", encoding="utf-8")
    f.unlink()
    os.symlink(victim, f)
    assert run(capsys, "--mark-window", "base", "--end", "2026-12-01", "--home", str(home))[0] == 2
    assert victim.read_text(encoding="utf-8") == "v"
    f.unlink()
    os.link(victim, f)
    assert run(capsys, "--mark-window", "base", "--end", "2026-12-01", "--home", str(home))[0] == 2
    assert victim.read_text(encoding="utf-8") == "v"


def test_mark_window_refuses_linked_usage(tmp_path, capsys):
    h, outside = tmp_path / "h", tmp_path / "outside"
    h.mkdir()
    outside.mkdir()
    os.symlink(outside, h / "_usage")
    assert run(capsys, "--mark-window", "base", "--end", "2026-12-01", "--home", str(h))[0] == 2
    assert list(outside.iterdir()) == []


def test_unexpected_exception_exit2_without_details(home, capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("/home/secret/cwd do X secret prompt")

    monkeypatch.setattr(rrm, "scan_harness", boom)
    rc, out, err = run(capsys, "--since", SINCE, "--until", UNTIL, "--home", str(home))
    assert rc == 2 and "RuntimeError" in err and "secret" not in err and out == ""


def test_read_only_without_out(home, capsys):
    before = sorted(p for p in home.rglob("*"))
    assert run(capsys, "--since", SINCE, "--until", UNTIL, "--home", str(home))[0] == 0
    assert sorted(p for p in home.rglob("*")) == before


def bare_home(tmp_path, entries, name="s"):
    h = tmp_path / "bh"
    (h / "projects").mkdir(parents=True, exist_ok=True)
    write_session(h, "p", name, entries)
    return h


def test_big_line_skipped_not_loaded(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(rrm, "MAX_LINE_BYTES", 400)
    big = user("big", "x" * 2000, ts="2026-11-20T00:00:00.000Z")
    h = bare_home(tmp_path, [user("a", "q", ts="2026-11-19T00:00:00.000Z"), asst("b", tool("t", "Bash")), big,
                             user("c", "q2", ts="2026-11-21T00:00:00.000Z")])
    (h / "_evolve").mkdir()
    (h / "_evolve/prompts.jsonl").write_text(j({"ts": "2026-11-20T00:00:00Z", "prompt": "p" * 2000}) + "\n"
                                             + j({"ts": "2026-11-20T00:00:00Z", "prompt": "p"}) + "\n", encoding="utf-8")
    rc, out, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--home", str(h))
    r = rows(out)
    assert rc == 0 and "큰 줄(읽지 않음) 1 · 중복" in out and "고른 턴 2 ·" in out
    assert "하네스 기록:" in out and out.split("하네스 기록:")[1].split("\n")[0].endswith("큰 줄(읽지 않음) 1")
    assert r["M5 T12 후보 (프롬프트 100개당)"][2] == "1"


def test_deep_nesting_is_bad_line_not_crash(tmp_path, capsys):
    deep = '{"type":"user","uuid":"d","x":' + "[" * 100_000 + "]" * 100_000 + "}"
    h = bare_home(tmp_path, [user("a", "q", ts="2026-11-20T00:00:00.000Z"), deep, asst("b", tool("t", "Bash"))])
    (h / "_evolve").mkdir()
    (h / "_evolve/prompts.jsonl").write_text('{"ts":' + "[" * 100_000 + "]" * 100_000 + "}\n", encoding="utf-8")
    rc, out, err = run(capsys, "--since", SINCE, "--until", UNTIL, "--home", str(h))
    assert rc == 0, err
    assert "깨진 줄 1 ·" in out and "하네스 기록: prompts.jsonl" not in out and "· 깨진 줄 1 · 큰 줄" in out
    assert rows(out)["M1 [이해] 부착률"][1:3] == ["0", "1"]


def test_deep_tool_input_and_non_string_fields(tmp_path, capsys):
    nested = "추천"
    for _ in range(900):
        nested = {"k": nested}
    deep_list = "x"
    for _ in range(900):
        deep_list = [deep_list]
    h = bare_home(tmp_path, [user("a", "q", ts="2026-11-20T00:00:00.000Z"),
                             asst("b", tool("t1", ASK, {"q": nested}), tool("t2", "Agent", {"description": "sonnet: x", "prompt": deep_list}),
                                  {"type": "text", "text": deep_list})])
    rc, out, err = run(capsys, "--since", SINCE, "--until", UNTIL, "--home", str(h))
    r = rows(out)
    assert rc == 0, err
    assert r["M2 선택 창 추천 혼입"][:3] == ["100.0%", "1", "1"]
    assert r["M7 [SKILL_DEPTH 포함"][1:3] == ["0", "1"] and "assistant 텍스트 블록 0" in r["M3 원문자 (100턴당)"][3]


def test_usage_values_must_be_int(tmp_path, capsys):
    h = tmp_path / "uh"
    (h / "projects").mkdir(parents=True)
    for sid, usage in (("ok", {"input_tokens": 4, "cache_creation_input_tokens": 40, "cache_read_input_tokens": 1}),
                       ("str", {"input_tokens": "9", "cache_creation_input_tokens": 90}),
                       ("inf", {"input_tokens": float("inf"), "cache_creation_input_tokens": float("nan")}),
                       ("bool", {"input_tokens": True, "cache_creation_input_tokens": 7})):
        write_session(h, "p", sid, [user(f"{sid}u", "q", ts="2026-11-20T00:00:00.000Z"), asst(f"{sid}a", text("x"), usage=usage)])
    rc, out, err = run(capsys, "--since", SINCE, "--until", UNTIL, "--home", str(h))
    r = rows(out)
    assert rc == 0, err
    assert r["이득 세션 시작 첫 응답 입력 토큰 중앙값"][:3] == ["4", "-", "1"]
    assert r["이득 세션 시작 첫 응답 cache 생성 토큰 중앙값"][:3] == ["40", "-", "3"]
    assert r["이득 세션 시작 첫 응답 cache 생성 토큰 중앙값"] [3] == "사분위 23.5 ~ 65"


def test_latex_unclosed_openers_are_linear():
    import time
    t0 = time.perf_counter()
    assert len(rrm.LATEX_RX.findall("\\[" * 100_000)) == 0 and len(rrm.LATEX_RX.findall("\\(" * 100_000)) == 0
    assert time.perf_counter() - t0 < 1.0
    assert len(rrm.LATEX_RX.findall("앞 \\[ x^2 \\] 와 \\( a \\) 와 $\\alpha$")) == 3


def test_row_caps(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(rrm, "MAX_ROWS", 2)
    h = tmp_path / "ch"
    (h / "_audit").mkdir(parents=True)
    tags = ("쓰기 차단", "git 차단", "외부 모델 게이트", "아무 문장이나 적음")
    write_session(h, "pa", "s", [user("au", "q", ts="2026-11-20T00:00:00.000Z"), asst("aa", tool("at", "Bash"))]
                  + [result(f"ar{k}", "at", f"PreToolUse:Bash hook error: [{tag}] x", is_error=True) for k, tag in enumerate(tags)])
    for p in ("pb", "pc"):
        write_session(h, p, "s", [user(f"{p}u", "q", ts="2026-11-20T00:00:00.000Z"), asst(f"{p}a", text("x"))])
    (h / "_audit/plan-confirm-gate.tsv").write_text("".join(f"2026-11-18T01:00:00+00:00\ts\tW\t호출({c})\n" for c in "abcd" for _ in range(1 + "abcd".index(c))),
                                                    encoding="utf-8")
    (h / "_audit/hook-deny.tsv").write_text("2026-11-18T10:00:00+0900\ts\tmain\t/etc/x\tBash\t1\n", encoding="utf-8")
    rc, out, _ = run(capsys, "--since", SINCE, "--until", UNTIL, "--home", str(h))
    r = rows(out)
    assert rc == 0
    assert [k for k in r if k.startswith("M4 계획")] == ["M4 계획 확정 경고 d (작업성 100턴당)", "M4 계획 확정 경고 c (작업성 100턴당)",
                                                       "M4 계획 확정 경고 그 밖 2종 합계 (작업성 100턴당)"]
    assert r["M4 계획 확정 경고 그 밖 2종 합계 (작업성 100턴당)"][1] == "3"
    assert r["M4 hook-deny 기타 (작업성 100턴당)"][1] == "1"
    tags = [k for k in r if k.startswith("M4 대화 기록")]
    assert len(tags) == 3 and tags[-1] == "M4 대화 기록 훅 차단 [그 밖 2종 합계] (작업성 100턴당)"
    assert "아무 문장" not in out
    assert "| 그 밖 1개 합계 | 1 | 1 | 0 |" in out and "| P3 |" not in out
