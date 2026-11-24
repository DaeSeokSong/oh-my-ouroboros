#!/usr/bin/env python3
# ruff: noqa: EXE001, UP017, PLW1510, PLR0133 — pre-existing lines left untouched (2026-11-22: existing tests must not change); system python3 3.10 has no datetime.UTC
"""confluence_publish_approve.py 회귀 테스트 (임시 HOME·가짜 세션 기록 — 실제 _audit·실제 세션 기록은 건드리지 않는다).

실행: python3 ~/.claude/scripts/tests/test_confluence_publish_approve.py → 실패 0 이면 exit 0

■ 케이스 (plan 개정 1 «문서·시험»): 승인 없음·다른 보기·자유 입력·sidechain 기록·subagents 폴더 기록·결박 안 된 tool_result·
  질문 줄 형식 오류·대상/알림/버전 설명 불일치·1시간 지남·미래 시각 → 불통. 정상 통과·재사용 불통·여러 페이지 한 질문 → 페이지별 소모·
  한 AskUserQuestion 의 여러 질문 각각 판정·큰 파일 끝 읽기·동시 소모·새 페이지·페이지 ID 정규화·stamp 폐지.
REF: knowledge/harness/code-history/scripts__tests__test_confluence_publish_approve.py.md
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "confluence_publish_approve.py"
sys.path.insert(0, str(TOOL.parent))
TMP_HOME = Path(tempfile.mkdtemp(prefix="publish-approve-home-"))
PROJ = TMP_HOME / ".claude/projects/p"
PROJ.mkdir(parents=True)
ENV = {**os.environ, "HOME": str(TMP_HOME)}
AUDIT = TMP_HOME / ".claude/_audit/publish-approval"
TAG = uuid.uuid4().hex[:8]
fail = 0
_n = 0
OK_LABEL = "게시 승인"


def iso(delta_s=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def page_line(pages="2001", notify="notify", msg="실험 결과 추가"):
    return f"게시 승인 요청 · page={pages} · 알림={notify} · 버전 설명=«{msg}»"


def new_line(space="S1", parent="P1", title="새 페이지 제목"):
    return f"게시 승인 요청 · new · space={space} · parent={parent} · 제목=«{title}»"


def ask(questions, answers, ts_ans=None, ts_ask=None, sidechain=False, session="s1", sub=False, bind=True, file=None):
    global _n
    _n += 1
    tuid = f"toolu_{TAG}_{_n}"
    path = file or ((PROJ / session / "subagents" / "agent-x.jsonl") if sub else (PROJ / f"{session}.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    qs = [{"question": q, "header": "승인", "options": [{"label": lb, "description": "d"} for lb in labels]} for q, labels in questions]
    use = {"type": "assistant", "isSidechain": sidechain, "timestamp": ts_ask or iso(-5),
           "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "AskUserQuestion", "id": tuid, "input": {"questions": qs}}]}}
    res = {"type": "user", "isSidechain": sidechain, "timestamp": ts_ans or iso(),
           "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tuid if bind else tuid + "x", "content": "ok"}]},
           "toolUseResult": {"questions": qs, "answers": answers, "annotations": {}}}
    with open(path, "a", encoding="utf-8") as f:
        f.write(dumps(use) + "\n" + dumps(res) + "\n")
    return tuid


def dumps(rec):
    return json.dumps(rec, ensure_ascii=False, separators=(",", ":"))


def raw(session, *recs):
    path = PROJ / f"{session}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        for r in recs:
            f.write(dumps(r) + "\n")


def queued(prompt, origin=None, mode="prompt"):
    a = {"type": "queued_command", "prompt": prompt, "commandMode": mode}
    if origin is not None:
        a["origin"] = origin
    return {"type": "attachment", "isSidechain": False, "timestamp": iso(), "attachment": a}


def turn(kind, ts, **extra):
    return {"type": kind, "isSidechain": False, "timestamp": ts, "message": {"role": kind, "content": extra.pop("content", [])}, **extra}


def approve(line, answer=OK_LABEL, labels=(OK_LABEL, "취소"), pre="아래 게시를 승인하시겠습니까?\n", post="\n문의는 채팅으로.", **kw):
    q = f"{pre}{line}{post}"
    return ask([(q, list(labels))], {q: answer}, **kw)


def run(*args, env=None):
    r = subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env or ENV)
    try:
        return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return r.returncode, {"ok": None, "reason": r.stdout + r.stderr}


def check_page(page, notify="notify", msg="실험 결과 추가", consume=False):
    return run("check", *(["--consume"] if consume else []), "--page", page, "--notify", notify, "--message", msg)


def expect(name, cond, detail=""):
    global fail
    fail += 0 if cond else 1
    print(f"{'OK ' if cond else 'FAIL'} {name}{'' if cond else f' (detail: {detail})'}")


def blocked(name, rc_o, hint=None):
    rc, o = rc_o
    expect(name, rc == 1 and o["ok"] is False and (hint is None or hint in o["reason"]), o)


try:
    blocked("승인 기록이 없음(projects 폴더 비어 있음) → 불통(승인 줄 원문 포함)", check_page("1001"), "게시 승인 요청 · page=1001")
    expect("불통 사유에 AskUserQuestion 안내", "AskUserQuestion" in check_page("1001")[1]["reason"])

    approve(page_line("1002"), answer="취소")
    blocked("다른 보기(취소)를 고름 → 불통", check_page("1002"))
    approve(page_line("1003"), answer="그냥 바꿔주세요")
    blocked("자유 입력 답 → 불통", check_page("1003"))
    approve(page_line("1004"), labels=("승인합니다", "취소"), answer="승인합니다")
    blocked("보기에 «게시 승인» 라벨이 없음 → 불통", check_page("1004"))
    approve(page_line("1005"), sidechain=True)
    blocked("sidechain 기록의 승인 → 불통", check_page("1005"))
    approve(page_line("1006"), sub=True)
    blocked("subagents 폴더 기록의 승인 → 불통", check_page("1006"))
    approve(page_line("1007"), bind=False)
    blocked("tool_use id 와 결박 안 된 tool_result → 불통", check_page("1007"))
    approve("게시 승인 요청 page=1008 알림=notify 버전 설명=실험 결과 추가")
    blocked("질문 줄 형식 오류 → 불통", check_page("1008"))
    approve(page_line("1009") + "\n" + page_line("1010"))
    blocked("승인 줄이 두 줄 → 불통", check_page("1009"))
    approve(page_line("abc"))
    blocked("승인 줄의 페이지 ID 가 숫자 아님 → 불통", check_page("1011"))
    approve(page_line("1012", notify="notify"))
    blocked("알림 불일치 → 불통", check_page("1012", notify="quiet"), "알림=quiet")
    blocked("버전 설명 불일치 → 불통", check_page("1012", msg="다른 설명"))
    blocked("대상(다른 페이지) 불일치 → 불통", check_page("1013"))
    approve(page_line("1014"), ts_ans=iso(-7200), ts_ask=iso(-7300))
    blocked("답한 지 1시간 지남 → 불통", check_page("1014"))
    approve(page_line("1015"), ts_ans=iso(600))
    blocked("미래 시각 → 불통", check_page("1015"))
    approve(page_line("1016"), ts_ans="2026-10-07T12:00:00")
    blocked("시간대 없는 시각 → 불통", check_page("1016"))
    q = page_line("1017")
    ask([(q, [OK_LABEL, "취소"])], {"다른 질문": OK_LABEL})
    blocked("answers 키가 질문 문자열과 다름 → 불통", check_page("1017"))

    approve(page_line("2001"))
    rc, o = check_page("2001")
    expect("정상 → 통과(소모 없음)", rc == 0 and o["ok"], o)
    rc, o = check_page("2001", msg="  실험 결과 추가  ")
    expect("버전 설명 앞뒤 공백은 무시", rc == 0 and o["ok"], o)
    rc, o = check_page("2001", consume=True)
    expect("consume: 정상 통과", rc == 0 and o["ok"], o)
    ledger = (AUDIT / "used.tsv").read_text(encoding="utf-8").splitlines()
    expect("장부 한 줄(tool_use_id·대상·시각)", len(ledger) == 1 and ledger[0].split("\t")[1] == "page:2001" and len(ledger[0].split("\t")) == 3, ledger)
    blocked("consume 뒤 재사용 → 불통", check_page("2001", consume=True), "이미")
    blocked("소모 뒤 소모 없는 check 도 불통", check_page("2001"), "이미")
    approve(page_line("2001"))
    rc, o = check_page("2001", consume=True)
    expect("같은 대상에 새 승인 질문 → 다시 통과", rc == 0 and o["ok"], o)
    expect("장부 파일 0600·폴더 0700", (AUDIT / "used.tsv").stat().st_mode & 0o777 == 0o600 and AUDIT.stat().st_mode & 0o777 == 0o700)

    approve(page_line("2002"), ts_ans=iso(-1200))
    t_new = approve(page_line("2002"), ts_ans=iso(-60))
    check_page("2002", consume=True)
    used = (AUDIT / "used.tsv").read_text(encoding="utf-8")
    expect("승인이 여럿이면 가장 최근 것을 먼저 소모", f"{t_new}\tpage:2002" in used, used)
    rc, o = check_page("2002", consume=True)
    expect("남은 오래된 승인으로 한 번 더 통과", rc == 0, o)
    blocked("승인 둘 다 소모 → 불통", check_page("2002", consume=True))

    approve(page_line("3001,3002", notify="quiet", msg="여러 페이지"))
    rc, o = check_page("3001", notify="quiet", msg="여러 페이지", consume=True)
    expect("여러 페이지: 첫째 소모 통과", rc == 0, o)
    blocked("여러 페이지: 첫째 재사용 → 불통", check_page("3001", notify="quiet", msg="여러 페이지", consume=True))
    rc, o = check_page("3002", notify="quiet", msg="여러 페이지", consume=True)
    expect("여러 페이지: 하나 소모 뒤에도 다른 하나는 통과", rc == 0 and o["ok"], o)
    blocked("여러 페이지: 목록에 없는 페이지 → 불통", check_page("3003", notify="quiet", msg="여러 페이지"))

    qa, qb, qc = ("A 게시\n" + page_line("4001"), "B 게시\n" + page_line("4002"), "C 게시\n" + page_line("4003"))
    ask([(qa, [OK_LABEL, "취소"]), (qb, [OK_LABEL, "취소"]), (qc, [OK_LABEL, "취소"])], {qa: OK_LABEL, qb: "취소", qc: OK_LABEL})
    rc_a, _ = check_page("4001")
    rc_b, _ = check_page("4002")
    rc_c, _ = check_page("4003")
    expect("여러 질문: 승인한 것만 통과(A 통과·B 불통·C 통과)", (rc_a, rc_b, rc_c) == (0, 1, 0), (rc_a, rc_b, rc_c))

    approve(new_line())
    rc, o = run("check", "--new", "--space", "S1", "--parent", "P1", "--title", "새 페이지 제목")
    expect("새 페이지: 정상", rc == 0 and o["ok"], o)
    blocked("새 페이지: 제목 불일치 → 불통", run("check", "--new", "--space", "S1", "--parent", "P1", "--title", "다른 제목"))
    blocked("새 페이지: 공간 불일치 → 불통", run("check", "--new", "--space", "S2", "--parent", "P1", "--title", "새 페이지 제목"))
    blocked("새 페이지: 부모 불일치 → 불통", run("check", "--new", "--space", "S1", "--parent", "P9", "--title", "새 페이지 제목"))
    rc, o = run("check", "--consume", "--new", "--space", "S1", "--parent", "P1", "--title", "새 페이지 제목")
    rc2, _ = run("check", "--new", "--space", "S1", "--parent", "P1", "--title", "새 페이지 제목")
    expect("새 페이지: 소모 뒤 재사용 불통", rc == 0 and rc2 == 1, (o, rc2))
    approve(new_line(parent="없음", title="루트 페이지"))
    rc, o = run("check", "--new", "--space", "S1", "--parent", "", "--title", "루트 페이지")
    expect("새 페이지: parent=없음 은 빈 부모와 같다", rc == 0 and o["ok"], o)
    approve(page_line("4501"))
    blocked("page 줄 승인으로는 새 페이지 불가", run("check", "--new", "--space", "S1", "--parent", "P1", "--title", "4501"))

    approve(page_line("00123"))
    rc, o = check_page("123")
    expect("페이지 ID: 승인 줄 00123 ↔ 호출 123 같은 키", rc == 0 and o["ok"], o)
    rc, o = check_page("0123")
    expect("페이지 ID: 호출 0123 도 같은 키", rc == 0 and o["ok"], o)
    for bad in ("abc", "https://x.atlassian.net/wiki/x/AbC", "12a", "0", "000", "-5", "1 2"):
        rc, o = check_page(bad)
        expect(f"페이지 ID: {bad!r} → 거부", rc != 0 and not o["ok"], o)
    expect("페이지 ID: 숫자 아님 사유에 «숫자 페이지 ID»", "숫자 페이지 ID" in check_page("tiny", consume=True)[1]["reason"])

    big = PROJ / "big.jsonl"
    with open(big, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "assistant", "isSidechain": False, "timestamp": iso(-30 * 3600), "x": "a" * 30_000_000}) + "\n")
    approve(page_line("5001"), file=big)
    rc, o = check_page("5001", consume=True)
    expect("큰 파일(앞쪽 30MB 줄): 끝 읽기로 승인 발견", rc == 0 and o["ok"], o)
    big.unlink()

    import confluence_publish_approve as cpa
    sample = TMP_HOME / "sample.jsonl"
    for body in (b"a\nbb\nccc\n", b"a\nbb\nccc", b"\n\nx\n\n", b"only", b"1234567890123456789\nz\n"):
        sample.write_bytes(body)
        for chunk in (1, 2, 3, 7, 1 << 20):
            cpa.CHUNK = chunk
            got = list(cpa._reverse_lines(sample))
            want = [ln for ln in reversed(body.split(b"\n")) if ln]
            if got != want:
                expect(f"거꾸로 읽기 {body!r} chunk={chunk}", False, (got, want))
                break
        else:
            expect(f"거꾸로 읽기 {body!r}: 모든 청크 크기에서 줄 단위 일치", True)
    cpa.CHUNK = 1 << 20

    approve(page_line("9001"))
    procs = [subprocess.Popen([sys.executable, str(TOOL), "check", "--consume", "--page", "9001", "--notify", "notify",
                               "--message", "실험 결과 추가"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=ENV)
             for _ in range(8)]
    outs = [p.communicate()[0] for p in procs]
    oks = sum(1 for p in procs if p.returncode == 0)
    ledger_n = sum(1 for ln in (AUDIT / "used.tsv").read_text(encoding="utf-8").splitlines() if "\tpage:9001\t" in ln)
    expect("동시 소모: 8개 프로세스 중 정확히 하나만 ok·장부 한 줄", oks == 1 and ledger_n == 1, (oks, ledger_n, outs))

    stale_ts = iso(-2 * 86400)
    approve(page_line("6001"), session="r1")
    raw("r1", {"type": "queue-operation", "operation": "dequeue", "timestamp": stale_ts, "sessionId": "x"})
    rc, o = check_page("6001")
    expect("승인 뒤 2일 묵은 queue-operation 줄이 있어도 통과", rc == 0 and o["ok"], o)
    approve(page_line("6002"), session="r2")
    raw("r2", {"type": "file-history-snapshot", "messageId": "m", "snapshot": {"timestamp": stale_ts}, "timestamp": stale_ts})
    rc, o = check_page("6002")
    expect("승인 뒤 오래된 file-history-snapshot 줄이 있어도 통과", rc == 0 and o["ok"], o)
    approve(page_line("6003"), session="r3")
    raw("r3", *[{"type": "queue-operation", "timestamp": stale_ts} for _ in range(5)], turn("assistant", iso(-5)))
    rc, o = check_page("6003")
    expect("오래된 queue-operation 이 여러 줄 연속이어도 통과", rc == 0 and o["ok"], o)
    approve(page_line("6004"), session="r4")
    raw("r4", turn("assistant", stale_ts), turn("user", stale_ts))
    rc, o = check_page("6004")
    expect("오래된 user·assistant 줄이 2줄 연속이면 계속 읽어 통과", rc == 0 and o["ok"], o)
    approve(page_line("6005"), session="r5")
    raw("r5", turn("assistant", stale_ts), turn("user", stale_ts), turn("assistant", stale_ts))
    blocked("오래된 user·assistant 줄 3줄 연속 뒤(파일 앞쪽)의 승인은 읽지 않아 불통", check_page("6005"))
    approve(page_line("6006"), session="r6", ts_ans=iso(-7200), ts_ask=iso(-7300))
    blocked("승인 답이 1시간 밖(2시간 전)이면 불통(compact 형식 기록)", check_page("6006"))
    spaced = PROJ / "r7.jsonl"
    spaced.write_text("".join(json.dumps(turn("assistant", stale_ts), ensure_ascii=False) + "\n" for _ in range(3)), encoding="utf-8")
    import confluence_publish_approve as cpa
    os.environ["HOME"] = str(TMP_HOME)
    kinds = [cpa._line_meta(ln) for ln in cpa._reverse_lines(spaced)]
    expect("공백 있는 JSON(\"timestamp\": \"…\") 도 timestamp·type 을 읽음", all(k == "assistant" and h for k, h in kinds) and len(kinds) == 3, kinds)
    spaced.unlink()

    bigfile = PROJ / "r8.jsonl"
    with open(bigfile, "w", encoding="utf-8") as f:
        for _ in range(40):
            f.write(dumps(turn("assistant", stale_ts, content=[{"type": "text", "text": "x" * 500_000}])) + "\n")
    approve(page_line("6008"), file=bigfile)
    total = [0]
    orig_rev = cpa._reverse_lines

    def counting(path):
        for ln in orig_rev(path):
            total[0] += len(ln)
            yield ln
    cpa._reverse_lines = counting
    t0 = time.time()
    found = cpa.find_approval("page:6008", "notify", "실험 결과 추가")
    elapsed = time.time() - t0
    cpa._reverse_lines = orig_rev
    expect("큰 파일: 승인을 찾고 오래된 3줄에서 멈춤(읽은 바이트 < 3MB, 파일은 20MB)",
           len(found) == 1 and total[0] < 3_000_000 < 20_000_000 <= bigfile.stat().st_size, (len(found), total[0], elapsed))
    bigfile.unlink()

    human_cases = {
        "7001": ("문자열 본문", turn("user", iso(), content="잠깐 보류해 주세요")),
        "7002": ("텍스트 블록", turn("user", iso(), content=[{"type": "text", "text": "내용 바꿔서 다시 해줘"}])),
        "7003": ("슬래시 명령 인자", turn("user", iso(), content="<command-name>/x</command-name><command-args>보류해 주세요</command-args>")),
        "7004": ("origin 이 human", turn("user", iso(), content="변경 요청", origin={"kind": "human"})),
        "7005": ("턴 진행 중 친 메시지(queued_command, origin human)", queued("잠깐 게시 보류해", origin={"kind": "human"})),
        "7006": ("queued_command, origin 없음", queued("잠깐 게시 보류해")),
        "7009": ("queued_command 본문이 블록 목록(이미지 동반)", queued([{"type": "text", "text": "잠깐 게시 보류해"}], origin={"kind": "human"})),
        "7007": ("붙여넣기(<pasted_content)", turn("user", iso(), content="<pasted_content>보류 요청 본문</pasted_content>")),
        "7008": ("queued_command 붙여넣기", queued("<pasted_content>보류</pasted_content>", origin={"kind": "human"})),
    }
    for page, (label, rec) in human_cases.items():
        approve(page_line(page), session=f"h{page}")
        raw(f"h{page}", rec)
        blocked(f"승인 뒤 사람 메시지({label}) → 불통", check_page(page))
    approve(page_line("7010"), session="h7010")
    raw("h7010", turn("user", iso(-3500), content="먼저 한 말"))
    approve(page_line("7011"), session="h7011")
    rc, o = check_page("7011")
    expect("사람 메시지가 승인보다 앞에 있으면 통과", rc == 0 and o["ok"], o)
    nonhuman = {
        "7020": ("도구 결과", turn("user", iso(), content=[{"type": "tool_result", "tool_use_id": "x", "content": "결과"}])),
        "7021": ("system-reminder 주입", turn("user", iso(), content="<system-reminder>알림</system-reminder>")),
        "7022": ("task-notification", turn("user", iso(), content="완료됨", origin={"kind": "task-notification"})),
        "7023": ("isMeta 스킬 본문", turn("user", iso(), content="Base directory for this skill: /x", isMeta=True)),
        "7024": ("compact 요약", turn("user", iso(), content="요약입니다", isCompactSummary=True)),
        "7025": ("피어 메시지", turn("user", iso(), content="Another Claude session sent a message: 안녕")),
        "7026": ("subagent 전달문", turn("user", iso(), content="[Subagent hand-back] 결과")),
        "7027": ("인터럽트 안내", turn("user", iso(), content="[Request interrupted by user]")),
        "7028": ("sidechain 사용자 줄", {**turn("user", iso(), content="서브에이전트 글"), "isSidechain": True}),
        "7029": ("인자 없는 슬래시 명령", turn("user", iso(), content="<command-name>/x</command-name><command-args></command-args>")),
        "7030": ("assistant 줄", turn("assistant", iso(), content=[{"type": "text", "text": "알겠습니다"}])),
        "7031": ("queued_command(origin task-notification)", queued("완료됨", origin={"kind": "task-notification"})),
        "7032": ("queued_command(origin 없음, commandMode task-notification)", queued("<task-notification>\n<task-id>x</task-id>", mode="task-notification")),
        "7033": ("queued_command(origin peer)", queued("[Subagent hand-back] 결과", origin={"kind": "peer", "from": "a1"})),
        "7034": ("sidechain queued_command", {**queued("보류해", origin={"kind": "human"}), "isSidechain": True}),
        "7035": ("<local-command-stdout 주입", turn("user", iso(), content="<local-command-stdout>ok</local-command-stdout>")),
        "7036": ("<task-notification 주입(user 줄)", turn("user", iso(), content="<task-notification>끝</task-notification>")),
        "7037": ("queued_command 의 <system-reminder 주입", queued("<system-reminder>x</system-reminder>")),
    }
    for page, (label, rec) in nonhuman.items():
        approve(page_line(page), session=f"n{page}")
        raw(f"n{page}", rec)
        rc, o = check_page(page)
        expect(f"승인 뒤 {label}만 있으면 통과", rc == 0 and o["ok"], o)

    approve(new_line(title="탭\t제목"))
    blocked("새 페이지 제목에 탭 → 거부", run("check", "--new", "--space", "S1", "--parent", "P1", "--title", "탭\t제목"), "제어문자")
    approve(new_line(title="줄\n바꿈"))
    blocked("새 페이지 제목에 개행 → 거부", run("check", "--new", "--space", "S1", "--parent", "P1", "--title", "줄\n바꿈"), "제어문자")
    blocked("새 페이지 제목 끝 개행 → 거부(strip 으로 숨기지 못함)", run("check", "--new", "--space", "S1", "--parent", "P1", "--title", "끝 개행\n"), "제어문자")
    approve(new_line(space="S\t1"))
    blocked("space 에 탭 → 거부", run("check", "--new", "--space", "S\t1", "--parent", "P1", "--title", "새 페이지 제목"), "제어문자")
    approve(page_line("7101", msg="설명 하나"))
    blocked("버전 설명에 개행 → 거부", check_page("7101", msg="설명\n하나"), "제어문자")
    blocked("버전 설명에 탭 → 거부", check_page("7101", msg="설명\t하나"), "제어문자")
    r = subprocess.run([sys.executable, str(TOOL), "question", "--page", "7", "--notify", "quiet", "--message", "가\n나"],
                       capture_output=True, text=True, env=ENV)
    expect("question 도 제어문자 거부", r.returncode == 1 and "제어문자" in r.stdout, r)

    r = subprocess.run([sys.executable, str(TOOL), "stamp", "--quote", "x", "--page", "1"], capture_output=True, text=True, env=ENV)
    expect("stamp → exit 2·AskUserQuestion 안내·승인 줄 형식", r.returncode == 2 and "AskUserQuestion" in r.stderr and "게시 승인 요청 · page=" in r.stderr, r)
    r = subprocess.run([sys.executable, str(TOOL), "question", "--page", "7", "--page", "008", "--notify", "quiet", "--message", "설명"],
                       capture_output=True, text=True, env=ENV)
    expect("question: 승인 줄·권장 보기 출력, 쓰기 없음", r.returncode == 0 and page_line("7,8", "quiet", "설명") in r.stdout and "게시 승인" in r.stdout, r)
    r = subprocess.run([sys.executable, str(TOOL), "question", "--new", "--space", "S", "--parent", "", "--title", "T"],
                       capture_output=True, text=True, env=ENV)
    expect("question --new: parent 비면 «없음»", r.returncode == 0 and new_line("S", "없음", "T") in r.stdout, r)
    rc, _ = run("check", "--page", "7001")
    expect("사용 오류: notify·message 없이 check → 거부", rc != 0)
    rc, o = run("check", "--cwd", "/tmp", "--page", "2001", "--notify", "notify", "--message", "x")
    expect("--cwd 는 받되 무시(하위 호환): 사용 오류가 아니라 불통 JSON", rc == 1 and o["ok"] is False, o)
    expect("승인 질문이 만든 기록 외에는 스탬프 파일이 만들어지지 않음", not list(AUDIT.glob("*.json")))

    MSG = "실험 결과 추가"

    def chg(page, *extra, consume=False, msg=MSG):
        return run("check", *(["--consume"] if consume else []), "--page", page, "--notify", "notify", "--message", msg, *extra)

    def question(*extra):
        return subprocess.run([sys.executable, str(TOOL), "question", *extra], check=False, capture_output=True, text=True, env=ENV)

    expect("기존 꼴 승인 줄 생성은 종전과 글자까지 같음",
           cpa.approval_line(["page:7", "page:8"], "quiet", "설명") == page_line("7,8", "quiet", "설명")
           and cpa.approval_line(["page:7"], "quiet", "설명", None, None) == page_line("7", "quiet", "설명"))
    L_T, L_P, L_TP = (page_line("8001") + " · 새 제목=«새 이름»", page_line("8002") + " · 새 부모=456",
                      page_line("8003") + " · 새 제목=«새 이름» · 새 부모=456")
    r = question("--page", "8001", "--notify", "notify", "--message", MSG, "--set-title", "  새 이름 ")
    expect("question: 제목만 → 새 제목 필드", r.returncode == 0 and L_T in r.stdout.splitlines(), r)
    r = question("--page", "8002", "--notify", "notify", "--message", MSG, "--set-parent", "0456")
    expect("question: 부모만 → 새 부모 필드(앞자리 0 제거)", r.returncode == 0 and L_P in r.stdout.splitlines(), r)
    r = question("--page", "8003", "--notify", "notify", "--message", MSG, "--set-title", "새 이름", "--set-parent", "456")
    expect("question: 둘 다 → 새 제목 다음 새 부모 순서", r.returncode == 0 and L_TP in r.stdout.splitlines(), r)
    for line, want in ((L_T, ("새 이름", None)), (L_P, (None, "456")), (L_TP, ("새 이름", "456")), (page_line("8004"), (None, None))):
        ap = cpa.parse_approval_line(line)
        back = ap and cpa.approval_line(ap["keys"], ap["notify"], ap["message"], ap["title"], ap["parent"])
        expect(f"생성 · 해석 왕복: {line[-30:]}", ap is not None and (ap["title"], ap["parent"]) == want and back == line, (ap, back))

    approve(L_T)
    approve(L_P)
    approve(L_TP)
    rc, o = chg("8001", "--set-title", "새 이름", consume=True)
    expect("제목 변경 승인: 통과 · 소모", rc == 0 and o["ok"], o)
    expect("제목 변경 소모 장부 키는 그대로 page:<ID>", "\tpage:8001\t" in (AUDIT / "used.tsv").read_text(encoding="utf-8"))
    blocked("제목 변경 승인 재사용 → 불통", chg("8001", "--set-title", "새 이름", consume=True), "이미")
    rc, o = chg("8002", "--set-parent", "456")
    expect("이동 승인: 통과", rc == 0 and o["ok"], o)
    rc, o = chg("8003", "--set-title", "새 이름", "--set-parent", "456")
    expect("제목 + 이동 승인: 통과", rc == 0 and o["ok"], o)
    blocked("새 제목 불일치 → 불통", chg("8003", "--set-title", "다른 이름", "--set-parent", "456"))
    blocked("새 부모 불일치 → 불통", chg("8003", "--set-title", "새 이름", "--set-parent", "457"))
    blocked("둘 다 든 승인으로 제목만 → 불통", chg("8003", "--set-title", "새 이름"))
    blocked("둘 다 든 승인으로 이동만 → 불통", chg("8003", "--set-parent", "456"))

    for page, tail in (("8101", " · 새 제목=«새 이름»"), ("8102", " · 새 부모=456"), ("8103", " · 새 제목=«새 이름» · 새 부모=456")):
        approve(page_line(page) + tail)
        blocked(f"8-a: 필드 든 승인({tail.strip()[:12]}…) → 훅 꼴 check(필드 없음) 불통",
                run("check", f"--page={page}", "--notify=notify", f"--message={MSG}"), "게시 승인 기록 없음")
    gate = TOOL.parent / "skeleton-gate.sh"
    if shutil.which("jq") and shutil.which("python3") and shutil.which("timeout"):
        def hook_reason(pid):
            inp = json.dumps({"tool_name": "mcp__x__updateConfluencePage",
                              "tool_input": {"pageId": pid, "versionMessage": MSG, "body": "<h1>x</h1>", "contentFormat": "html"}})
            r = subprocess.run(["bash", str(gate)], check=False, input=inp, capture_output=True, text=True, env=ENV)
            try:
                return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
            except (ValueError, KeyError):
                return r.stdout + r.stderr
        approve(page_line("8104"))
        approve(page_line("8105") + " · 새 제목=«새 이름»")
        r1, r2 = hook_reason("8104"), hook_reason("8105")
        expect("8-a 훅 대조군: 필드 없는 승인은 승인 검사를 지나 다음 관문(골격 스탬프)에서 막힘", "골격" in r1 and "게시 승인 기록 없음" not in r1, r1)
        expect("8-a 실제 훅(skeleton-gate.sh 무수정): 새 제목이 든 승인은 MCP 경로에서 «승인 기록 없음»", "게시 승인 기록 없음" in r2, r2)
    else:
        expect("8-a 실제 훅 시험: jq · python3 · timeout 이 있어야 함", False, "missing tool")

    approve(page_line("8201"))
    blocked("8-b: 필드 없는 승인 → 제목 변경 불통", chg("8201", "--set-title", "새 이름"))
    blocked("8-b: 필드 없는 승인 → 이동 불통", chg("8201", "--set-parent", "456"))
    rc, o = chg("8201")
    expect("8-b 대조군: 같은 승인으로 필드 없는 호출은 통과", rc == 0 and o["ok"], o)

    amb_msg = "a» · 새 제목=«X"
    expect("8-c 전제: 두 호출의 승인 줄 글자가 같음", page_line("8301", msg=amb_msg) == page_line("8301", msg="a") + " · 새 제목=«X»")
    approve(page_line("8301", msg="a") + " · 새 제목=«X»")
    blocked("8-c: 표지가 든 버전 설명의 치환 호출 → 거부(두 가지로 읽힘)", chg("8301", msg=amb_msg), "두 가지로")
    rc, o = chg("8301", "--set-title", "X", msg="a")
    expect("8-c: 같은 줄은 «버전 설명 a + 새 제목 X» 호출에만 통과", rc == 0 and o["ok"], o)
    ap = cpa.parse_approval_line(page_line("8301", msg="a") + " · 새 제목=«X»")
    expect("8-c: 해석은 하나(버전 설명 a · 새 제목 X)", ap and (ap["message"], ap["title"]) == ("a", "X"), ap)
    blocked("8-c: 표지가 든 새 제목 → 거부", chg("8301", "--set-title", "b» · 새 제목=«c", msg="a"), "두 가지로")
    expect("8-c: 새 제목 표지가 두 번인 줄 → 해석 불가",
           cpa.parse_approval_line(page_line("8302", msg="a") + " · 새 제목=«b» · 새 제목=«c»") is None)
    expect("8-c: 버전 설명에 새 부모 표지가 든 줄 → 해석 불가", cpa.parse_approval_line(page_line("8303", msg="a» · 새 부모=5")) is None)
    blocked("8-c: 새 부모 표지가 든 버전 설명 → 거부", check_page("8303", msg="a» · 새 부모=5"), "두 가지로")
    r = question("--page", "8303", "--notify", "notify", "--message", amb_msg)
    expect("8-c: question 도 표지 든 버전 설명 거부", r.returncode == 1 and "두 가지로" in r.stdout, r)

    multi = page_line("8401,8402") + " · 새 제목=«X»"
    expect("9: 여러 페이지 + 새 제목 줄 → 해석 불가", cpa.parse_approval_line(multi) is None)
    approve(multi)
    blocked("9: 여러 페이지 + 새 제목 승인 → 불통", chg("8401", "--set-title", "X"))
    for bad_tail in (" · 새 부모=abc", " · 새 부모=0", " · 새 부모=5 · 새 제목=«X»", " · 새 제목=«  »"):
        expect(f"9: 잘못된 새 필드{bad_tail!r} → 해석 불가", cpa.parse_approval_line(page_line("8403") + bad_tail) is None)
    blocked("9: --set-parent 숫자 아님 → 거부", chg("8403", "--set-parent", "abc"), "숫자 페이지 ID")
    blocked("9: --set-title 공백만 → 거부", chg("8403", "--set-title", "   "), "비어")
    blocked("9: --set-title 제어문자 → 거부", chg("8403", "--set-title", "가\t나"), "제어문자")
    approve(page_line("8405") + " · 새 부모=0456")
    rc, o = chg("8405", "--set-parent", "456")
    expect("9: 승인 줄 새 부모 0456 ↔ 호출 456 같은 값", rc == 0 and o["ok"], o)
    r = question("--page", "1", "--page", "2", "--notify", "notify", "--message", MSG, "--set-title", "X")
    expect("9: question 여러 페이지 + --set-title → 사용 오류", r.returncode == 2, r)
    r = question("--new", "--space", "S", "--title", "T", "--set-parent", "5")
    expect("9: question --new + --set-parent → 사용 오류(새 페이지 만들기와 구별)", r.returncode == 2, r)
    blocked("9: check() 직접 호출 — 새 페이지 대상 + 새 제목 → 거부",
            (1 if not cpa.check(cpa.new_key("S", "P", "T"), title="X")[0] else 0, {"ok": False, "reason": ""}))

    for bad in (chr(0x202E) + "뒤집힘", "폭" + chr(0x200B) + "없음", chr(0x2066) + "격리"):
        r = question("--page", "8501", "--notify", "notify", "--message", MSG, "--set-title", bad)
        expect(f"보이지 않는 글자 {bad!r}: question 거부", r.returncode == 1 and "보이지 않는 글자" in r.stdout, r)
        approve(page_line("8501") + f" · 새 제목=«{bad}»")
        blocked(f"보이지 않는 글자 {bad!r}: check 거부", chg("8501", "--set-title", bad), "보이지 않는 글자")
        expect(f"보이지 않는 글자 {bad!r}: 승인 줄 해석 불가", cpa.parse_approval_line(page_line("8501") + f" · 새 제목=«{bad}»") is None)
    good = "새 «이름» Name 2"
    r = question("--page", "8502", "--notify", "notify", "--message", MSG, "--set-title", good)
    expect("일반 한글 · 영문 · «» 제목: question 통과", r.returncode == 0 and (page_line("8502") + f" · 새 제목=«{good}»") in r.stdout, r)
    approve(page_line("8502") + f" · 새 제목=«{good}»")
    rc, o = chg("8502", "--set-title", good)
    expect("일반 한글 · 영문 · «» 제목: check 통과", rc == 0 and o["ok"], o)

    COLON = "«:»"
    clash1, clash2 = new_line("1", "5:판1", "결과"), new_line("1:5", "없음", "x")
    expect("«:» 충돌 줄 1(부모에 «:») → 해석 불가", cpa.parse_approval_line(clash1) is None)
    expect("«:» 충돌 줄 2(공간에 «:») → 해석 불가", cpa.parse_approval_line(clash2) is None)
    approve(clash1)
    approve(clash2)
    blocked("«:» 충돌 1: 부모 5:판1 승인이 (1, 5, 판1:결과) 호출에 통과하지 않음",
            run("check", "--new", "--space", "1", "--parent", "5", "--title", "판1:결과"))
    blocked("«:» 충돌 2: 공간 1:5 승인이 (1, 5, :x) 호출에 통과하지 않음",
            run("check", "--new", "--space", "1", "--parent", "5", "--title", ":x"))
    blocked("check --new: 부모에 «:» → 거부(훅 꼴)", run("check", "--new", "--space=1", "--parent=5:판1", "--title=결과"), COLON)
    blocked("check --new: 공간에 «:» → 거부", run("check", "--new", "--space", "1:5", "--title", "x"), COLON)
    r = subprocess.run([sys.executable, str(TOOL), "question", "--new", "--space", "1:5", "--title", "x"],
                       check=False, capture_output=True, text=True, env=ENV)
    expect("question --new: 공간에 «:» → 오류", r.returncode == 1 and COLON in r.stdout, r)
    r = subprocess.run([sys.executable, str(TOOL), "question", "--new", "--space", "1", "--parent", "5:판1", "--title", "x"],
                       check=False, capture_output=True, text=True, env=ENV)
    expect("question --new: 부모에 «:» → 오류", r.returncode == 1 and COLON in r.stdout, r)
    try:
        cpa.check_and_consume_new("1", "5:판1", "결과")
        expect("check_and_consume_new: 부모에 «:» → 종료", False)
    except SystemExit as e:
        expect("check_and_consume_new: 부모에 «:» → 종료(사유 포함)", COLON in str(e.code), e.code)
    approve(new_line("S1", "P1", "판1: 결과 · 비교"))
    rc, o = run("check", "--new", "--space", "S1", "--parent", "P1", "--title", "판1: 결과 · 비교")
    expect("제목에 «:» 가 든 정상 새 페이지 줄 → 통과", rc == 0 and o["ok"], o)
    ap = cpa.parse_approval_line(new_line("S1", "P1", "판1: 결과"))
    expect("제목에 «:» 가 든 줄의 키는 종전과 같음", ap and ap["keys"] == ["new:S1:P1:판1: 결과"], ap)

    expect("is_approval_question: 새 필드 든 승인 질문 인정",
           cpa.is_approval_question({"questions": [{"question": "확인\n" + L_TP, "options": [{"label": OK_LABEL}, {"label": "취소"}]}]}))
finally:
    shutil.rmtree(TMP_HOME, ignore_errors=True)

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'}")
sys.exit(1 if fail else 0)
