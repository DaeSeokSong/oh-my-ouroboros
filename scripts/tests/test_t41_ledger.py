"""T41 짧은 id 대장 회귀 테스트.

대상: t41-ledger.sh(add · get · transcript · find-actor · stats) · t41-append.sh(id 를 LINE 에만) ·
      t41-subagent-stop.sh(비동기 경로 환경변수) · agent-spawn-log.sh(동기 경로 보고 에이전트 경로 조립).
시험 1~6: id 형식 · 충돌 재생성 / 행위자 조인 / 경로 검사 종료 코드 / 대장 권한 / 10병렬 / 기존 소비자 호환.

격리: test_t41_chain.py 와 같은 방식 — 임시 HOME 에 .claude/{_audit,_usage,agents,_evolve,projects} 를 짓고
      scripts/ 는 실제 폴더로 심볼릭 링크한다. 무작위 id 충돌과 jq 지연은 PATH 앞에 둔 가짜 od · jq 로 만든다
      (스크립트에 시험용 플래그를 두지 않는다).

실행: python3 ~/.claude/scripts/tests/test_t41_ledger.py → 실패 0 이면 exit 0
REF: knowledge/harness/code-history/scripts__tests__test_t41_ledger.py.md
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
LEDGER_SH = SCRIPTS / "t41-ledger.sh"
ID_TAG = re.compile(r"\[t41id:([0-9a-f]{8})\]")
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def make_home(tmp, roles=("coder", "qa")):
    home = Path(tmp)
    claude = home / ".claude"
    for d in ("_audit", "_usage", "agents", "_evolve", "projects"):
        (claude / d).mkdir(parents=True, exist_ok=True)
    (claude / "scripts").symlink_to(SCRIPTS)
    for r in roles:
        (claude / "agents" / f"{r}.md").write_text(f"# {r}\n", encoding="utf-8")
    (claude / "_audit" / "history.md").write_text("# history\n", encoding="utf-8")
    return home


def env_for(home, path_prefix=None):
    env = dict(os.environ, HOME=str(home))
    for k in ("T41_REPORTER_TP", "T41_SESSION_ID", "T41_PATH_KIND"):
        env.pop(k, None)
    if path_prefix:
        env["PATH"] = f"{path_prefix}:{env['PATH']}"
    return env


def run(args, home, path_prefix=None, payload=None, extra=None):
    env = env_for(home, path_prefix)
    env.update(extra or {})
    return subprocess.run(args, check=False, capture_output=True, text=True, env=env, cwd=str(SCRIPTS.parent),
                          input=None if payload is None else json.dumps(payload, ensure_ascii=False))


def append(home, *args, **kw):
    return run(["bash", str(SCRIPTS / "t41-append.sh"), *args], home, **kw)


def ledger_cmd(home, *args, **kw):
    return run(["bash", str(LEDGER_SH), *args], home, **kw)


def history_t41(home):
    return [ln for ln in (home / ".claude/_audit/history.md").read_text(encoding="utf-8").splitlines() if "T41:" in ln]


def ledger_path(home):
    return home / ".claude/_evolve/t41-ledger.jsonl"


def ledger_rows(home):
    p = ledger_path(home)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x] if p.exists() else []


def write_ledger(home, rows):
    p = ledger_path(home)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def shim(dirpath, name, body):
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / name
    p.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    os.chmod(p, 0o755)
    return dirpath


def iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(epoch))


def write_agent(sub, aid, meta, texts=("작업",), mtime=None, start=None):
    tp = sub / f"agent-{aid}.jsonl"
    lines = []
    for i, t in enumerate(texts):
        u = {"type": "user", "message": {"role": "user", "content": "go"}}
        if i == 0 and start is not None:
            u["timestamp"] = iso(start)
        lines.append(json.dumps(u))
        lines.append(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": t}]}},
                                ensure_ascii=False))
    tp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (sub / f"agent-{aid}.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if mtime is not None:
        os.utime(tp, (mtime, mtime))
    return tp


def make_session(home):
    proj = home / ".claude/projects/p"
    sub = proj / "S" / "subagents"
    sub.mkdir(parents=True)
    sess = proj / "S.jsonl"
    sess.write_text('{"type":"user"}\n', encoding="utf-8")
    return sess, sub


def stop_payload(sess, rtp, role="qa"):
    return {"hook_event_name": "SubagentStop", "agent_type": role, "session_id": "S",
            "transcript_path": str(sess), "agent_transcript_path": str(rtp)}


def test_id():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        r = append(home, "--from", "qa", "--signal", "from=qa | RESULT: FAIL 1")
        t41 = history_t41(home)
        tags = ID_TAG.findall(t41[0]) if t41 else []
        rows = ledger_rows(home)
        check("1 id: 줄에 [t41id:16진 8자] 표기가 정확히 하나", len(t41) == 1 and len(tags) == 1 and t41[0].count("[t41id:") == 1,
              f"{t41} {r.stderr[:200]}")
        check("1 id: 자리는 « — » 바로 뒤", bool(t41) and " — [t41id:" in t41[0] and t41[0].index("[t41id:") == t41[0].index(" — ") + 3, str(t41))
        check("1 id: 대장 id 와 같고 대장은 한 행", len(rows) == 1 and tags and rows[0]["id"] == tags[0], f"{rows} {tags}")
        check("1 id: 대장 칸 11개", bool(rows) and list(rows[0]) == ["id", "ts", "session", "reporter", "actor", "actor_tp", "role",
                                                                    "dim", "path", "gap_s", "n_cand"], str(rows))
        check("1 id: stdout 의 LINE 에도 id", bool(tags) and f"[t41id:{tags[0]}]" in r.stdout, r.stdout)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(Path(tmp) / "h")
        write_ledger(home, [{"id": "deadbeef", "actor_tp": ""}])
        sd = shim(Path(tmp) / "shim", "od", f'n=$(cat "{tmp}/n" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "{tmp}/n"\n'
                                             'if [ "$n" -le 2 ]; then echo " de ad be ef"; else echo " 01 02 03 04"; fi\n')
        append(home, "qa", "범위 준수", "RESULT: BLOCKED x", path_prefix=str(sd))
        t41 = history_t41(home)
        check("1 id: 충돌이면 다시 만든다(deadbeef ×2 → 01020304)", len(t41) == 1 and "[t41id:01020304]" in t41[0]
              and [x["id"] for x in ledger_rows(home)] == ["deadbeef", "01020304"], f"{t41} {ledger_rows(home)}")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(Path(tmp) / "h")
        write_ledger(home, [{"id": "deadbeef", "actor_tp": ""}])
        sd = shim(Path(tmp) / "shim", "od", 'echo " de ad be ef"\n')
        r = append(home, "qa", "범위 준수", "RESULT: BLOCKED y", path_prefix=str(sd))
        t41 = history_t41(home)
        check("1 id: 5회 모두 충돌이면 id 없이 기록하고 stderr 에 남김", r.returncode == 0 and len(t41) == 1 and "[t41id:" not in t41[0]
              and "충돌" in r.stderr and len(ledger_rows(home)) == 1, f"{t41} rc={r.returncode} {r.stderr[:200]}")


def build_join_home(tmp, last_text, coders=True):
    home = make_home(tmp, roles=("coder", "qa", "reviewer"))
    sess, sub = make_session(home)
    t0 = int(time.time()) - 3600
    if coders:
        write_agent(sub, "c0", {"agentType": "coder"}, mtime=t0 - 600)
        write_agent(sub, "c1", {"agentType": "coder-2"}, mtime=t0 - 300)
        write_agent(sub, "c2", {"agentType": "coder"}, mtime=t0 + 100)
    write_agent(sub, "r9", {"agentType": "reviewer"}, mtime=t0 - 10)
    rtp = write_agent(sub, "q1", {"agentType": "qa", "description": "검수"}, texts=("확인", last_text), start=t0)
    return home, sess, rtp, t0


def test_join():
    stop = str(SCRIPTS / "t41-subagent-stop.sh")
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, _ = build_join_home(tmp, "RESULT: FAIL 2건")
        run(["bash", stop], home, payload=stop_payload(sess, rtp))
        rows = ledger_rows(home)
        c1 = os.path.realpath(rtp.parent / "agent-c1.jsonl")
        check("2 조인: qa FAIL → 행위자 coder(가장 최근 ≤ 보고 시작, 별칭 정규화)",
              len(rows) == 1 and rows[0]["actor"] == "agent-c1" and rows[0]["actor_tp"] == c1 and rows[0]["gap_s"] == "300" and rows[0]["n_cand"] == "2"
              and rows[0]["path"] == "async" and rows[0]["session"] == "S" and rows[0]["reporter"] == "agent-q1"
              and rows[0]["role"] == "coder", str(rows))
        tag = ID_TAG.findall(history_t41(home)[0])
        r = ledger_cmd(home, "transcript", tag[0] if tag else "")
        check("2 조인: transcript <id> 가 행위자 경로를 낸다(exit 0)", r.returncode == 0 and r.stdout.strip() == c1, f"{r.returncode} {r.stdout}")
        h = (home / ".claude/_audit/history.md").read_text(encoding="utf-8")
        check("2 조인: history 에 transcript 경로 · 세션 id 가 없다", "subagents" not in h and "agent-c1" not in h and str(home) not in h, h)
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, _ = build_join_home(tmp, "RESULT: BLOCKED 권한")
        run(["bash", stop], home, payload=stop_payload(sess, rtp))
        rows = ledger_rows(home)
        check("2 조인: BLOCKED → 행위자는 보고 에이전트 자신", len(rows) == 1 and rows[0]["actor"] == "agent-q1"
              and rows[0]["actor_tp"] == os.path.realpath(rtp), str(rows))
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, _ = build_join_home(tmp, "RESULT: FAIL 계획 오류 target=main")
        run(["bash", stop], home, payload=stop_payload(sess, rtp))
        rows = ledger_rows(home)
        check("2 조인: target=main → 행위자 빈 칸(id 는 있음)", len(rows) == 1 and rows[0]["role"] == "main" and rows[0]["actor"] == ""
              and rows[0]["actor_tp"] == "" and len(ID_TAG.findall(history_t41(home)[0])) == 1, str(rows))
        r = ledger_cmd(home, "transcript", rows[0]["id"] if rows else "")
        check("2 조인: 행위자 빈 칸이면 transcript exit 2(제외)", r.returncode == 2, str(r.returncode))
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, t0 = build_join_home(tmp, "RESULT: FAIL 1", coders=False)
        write_agent(rtp.parent, "c5", {"agentType": "coder"}, mtime=t0 + 50)
        run(["bash", stop], home, payload=stop_payload(sess, rtp))
        rows = ledger_rows(home)
        check("2 조인: 시각 조건(수정 시각 ≤ 보고 시작)을 못 채우면 빈 칸", len(rows) == 1 and rows[0]["actor"] == "", str(rows))
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, t0 = build_join_home(tmp, "RESULT: FAIL 1", coders=False)
        write_agent(rtp.parent, "tm", {"agentType": "rev-x", "customAgentType": "coder", "name": "rev-x"}, mtime=t0 - 20)
        run(["bash", stop], home, payload=stop_payload(sess, rtp))
        rows = ledger_rows(home)
        check("2 조인: teammate 는 customAgentType 으로 찾는다", len(rows) == 1 and rows[0]["actor"] == "agent-tm", str(rows))
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, _ = build_join_home(tmp, "RESULT: FAIL 1")
        payload = {"tool_name": "Agent", "session_id": "S", "transcript_path": str(sess),
                   "tool_input": {"subagent_type": "qa", "description": "검수"},
                   "tool_response": "검증 요약\nRESULT: FAIL 1\nagentId: q1 (use SendMessage with to: 'q1' to continue this agent)"}
        run(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload=payload)
        rows = ledger_rows(home)
        check("2 조인: 동기 경로(agentId → subagents/agent-<id>.jsonl)도 행위자 coder", len(rows) == 1 and rows[0]["actor"] == "agent-c1"
              and rows[0]["path"] == "sync" and rows[0]["reporter"] == "agent-q1", str(rows))
        run(["bash", str(SCRIPTS / "t41-subagent-stop.sh")], home, payload=stop_payload(sess, rtp))
        check("2 두 훅 순서 post → stop: history 1줄 · 대장 1행", len(history_t41(home)) == 1 and len(ledger_rows(home)) == 1,
              f"{history_t41(home)} {ledger_rows(home)}")
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, _ = build_join_home(tmp, "RESULT: FAIL 1")
        run(["bash", str(SCRIPTS / "t41-subagent-stop.sh")], home, payload=stop_payload(sess, rtp))
        payload = {"tool_name": "Agent", "session_id": "S", "transcript_path": str(sess),
                   "tool_input": {"subagent_type": "qa", "description": "검수"}, "tool_response": "RESULT: FAIL 1\nagentId: q1"}
        run(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload=payload)
        rows = ledger_rows(home)
        check("2 두 훅 순서 stop → post: history 1줄 · 대장 1행(먼저 쓴 async)", len(history_t41(home)) == 1 and len(rows) == 1
              and rows[0]["path"] == "async", f"{history_t41(home)} {rows}")
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, _ = build_join_home(tmp, "RESULT: FAIL 1")
        payload = {"tool_name": "Agent", "session_id": "S", "transcript_path": str(sess),
                   "tool_input": {"subagent_type": "qa"}, "tool_response": {"agentId": "../../x", "content": "RESULT: FAIL 1"}}
        run(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload=payload)
        rows = ledger_rows(home)
        check("2 동기 경로: agentId 에 `/`·`..` 이 있으면 행위자 빈 칸(history 는 기록)", len(rows) == 1 and rows[0]["actor"] == ""
              and rows[0]["reporter"] == "" and len(history_t41(home)) == 1, str(rows))


def test_join_review():
    stop = str(SCRIPTS / "t41-subagent-stop.sh")
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, t0 = build_join_home(tmp, "RESULT: BLOCKED 권한", coders=False)
        write_agent(rtp.parent, "g1", {"agentType": "general-purpose"}, mtime=t0 - 30)
        run(["bash", stop], home, payload=stop_payload(sess, rtp, role="foo"))
        rows = ledger_rows(home)
        check("2 자기 귀속 표지: 표 밖 역할(foo → general-purpose) BLOCKED 는 보고 에이전트 자신",
              len(rows) == 1 and rows[0]["role"] == "general-purpose" and rows[0]["actor"] == "agent-q1" and rows[0]["n_cand"] == "", str(rows))
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, t0 = build_join_home(tmp, "RESULT: FAIL 앞 검수 누락 target=qa", coders=False)
        write_agent(rtp.parent, "q0", {"agentType": "qa"}, mtime=t0 - 40)
        os.utime(rtp, (t0, t0))
        run(["bash", stop], home, payload=stop_payload(sess, rtp))
        rows = ledger_rows(home)
        check("2 자기 귀속 표지: target=<같은 역할> 은 자신이 아니라 앞선 같은 역할 소집", len(rows) == 1 and rows[0]["actor"] == "agent-q0"
              and rows[0]["n_cand"] == "1", str(rows))
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, t0 = build_join_home(tmp, "RESULT: FAIL 1")
        (rtp.parent / "agent-a0.jsonl").write_text("{}\n", encoding="utf-8")
        os.utime(rtp.parent / "agent-a0.jsonl", (t0 - 50, t0 - 50))
        (rtp.parent / "agent-a0.meta.json").write_text('{"agentType": "coder", bad', encoding="utf-8")
        run(["bash", stop], home, payload=stop_payload(sess, rtp))
        rows = ledger_rows(home)
        check("2 깨진 meta 는 그 파일만 건너뛴다(뒤의 coder 를 찾음)", len(rows) == 1 and rows[0]["actor"] == "agent-c1" and rows[0]["n_cand"] == "2",
              str(rows))
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, t0 = build_join_home(tmp, "RESULT: FAIL 1")
        lk = rtp.parent / "agent-c3.jsonl"
        lk.symlink_to(rtp.parent / "agent-c0.jsonl")
        os.utime(lk, (t0 - 5, t0 - 5), follow_symlinks=False)
        (rtp.parent / "agent-c3.meta.json").write_text('{"agentType": "coder"}', encoding="utf-8")
        run(["bash", stop], home, payload=stop_payload(sess, rtp))
        rows = ledger_rows(home)
        check("2 최신 후보가 링크면 빈 칸(옛 후보로 넘어가지 않음), n_cand 는 3", len(rows) == 1 and rows[0]["actor"] == ""
              and rows[0]["n_cand"] == "3", str(rows))


def test_stats_breakdown():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        hist = "# h\n" + "".join(f"- 2026-11-16 T41: coder/구현 정확성 — [t41id:{i}] RESULT: FAIL {i}\n"
                                 for i in ("aaaa0001", "aaaa0002", "aaaa0003", "aaaa0004"))
        (home / ".claude/_audit/history.md").write_text(hist, encoding="utf-8")
        write_ledger(home, [
            {"id": "aaaa0001", "actor": "agent-a", "n_cand": "1", "gap_s": "100"},
            {"id": "aaaa0002", "actor": "agent-b", "n_cand": "3", "gap_s": "2000"},
            {"id": "aaaa0003", "actor": "agent-q", "n_cand": "", "gap_s": ""},
            {"id": "aaaa0004", "actor": "", "n_cand": "0", "gap_s": ""},
            {"id": "ffff0009", "actor": "agent-z", "n_cand": "1", "gap_s": "99999"},
        ])
        out = ledger_cmd(home, "stats").stdout
        check("stats: 분모는 history, 짝 없는 대장 행은 제외(행위자 3/4)", "새 T41 4건 · 짧은 id 4건(100.0%) · 행위자 찾음 3건(짧은 id 중 75.0%)" in out, out)
        check("stats: 단일 1 · 모호 1 · 자기 귀속 1", "단일(n_cand=1) 1 · 모호(n_cand≥2) 1 · 자기 귀속 1" in out, out)
        check("stats: gap_s 10분 이하 1 · 1시간 이하 1 · 1시간 초과 0 · 빈 칸 1", "10분 이하 1 · 1시간 이하 1 · 1시간 초과 0 · 빈 칸 1" in out, out)


def test_paths():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        real_home = base / "realhome"
        home = make_home(real_home)
        p = home / ".claude/projects/p"
        p.mkdir(parents=True)
        out = base / "outside"
        out.mkdir()
        (out / "x.jsonl").write_text("{}\n", encoding="utf-8")
        (home / ".claude/outside").mkdir()
        (home / ".claude/outside/x.jsonl").write_text("{}\n", encoding="utf-8")
        ok = p / "real.jsonl"
        ok.write_text("{}\n", encoding="utf-8")
        (p / "mid").symlink_to(out)
        (p / "end.jsonl").symlink_to(ok)
        (p / "broken.jsonl").symlink_to(p / "nothere.jsonl")
        (p / "x.json").write_text("{}\n", encoding="utf-8")
        (p / "d.jsonl").mkdir()
        noread = p / "noread.jsonl"
        noread.write_text("{}\n", encoding="utf-8")
        os.chmod(noread, 0)
        link_home = base / "homelink"
        link_home.symlink_to(real_home)
        cases = {
            "aaaa0001": (str(ok), 0),
            "aaaa0002": (str(home / ".claude/projects/../outside/x.jsonl"), 4),
            "aaaa0003": (str(p / "mid/x.jsonl"), 4),
            "aaaa0004": (str(p / "end.jsonl"), 4),
            "aaaa0005": (str(p / "broken.jsonl"), 4),
            "aaaa0006": (str(p / "x.json"), 4),
            "aaaa0007": (str(out / "x.jsonl"), 4),
            "aaaa0008": (str(p / "gone.jsonl"), 3),
            "aaaa0009": (str(p / "d.jsonl"), 4),
            "aaaa000a": ("", 2),
            "aaaa000b": (str(link_home / ".claude/projects/p/real.jsonl"), 0),
        }
        if os.geteuid() != 0:
            cases["aaaa000c"] = (str(noread), 4)
        write_ledger(home, [{"id": k, "actor": "agent-x", "actor_tp": v[0]} for k, v in cases.items()])
        names = {"aaaa0001": "정상", "aaaa0002": "`..` 우회", "aaaa0003": "중간 링크", "aaaa0004": "끝 링크", "aaaa0005": "끊긴 링크",
                 "aaaa0006": ".json 이름", "aaaa0007": "접두 밖", "aaaa0008": "삭제된 파일", "aaaa0009": "디렉터리",
                 "aaaa000a": "행위자 빈 칸", "aaaa000b": "링크 HOME 경로로 적힌 정상 파일", "aaaa000c": "읽기 불가"}
        for hm, label in ((home, "실제 HOME"), (link_home, "링크 HOME")):
            bad = []
            for k, (_, want) in cases.items():
                r = ledger_cmd(hm, "transcript", k)
                if r.returncode != want or (want == 0 and r.stdout.strip() != os.path.realpath(ok)):
                    bad.append((names[k], want, r.returncode, r.stdout.strip()))
            check(f"3 경로({label}): 0 정상 · 4 `..`·중간 링크·끝 링크·끊긴 링크·.json·접두 밖·디렉터리·읽기 불가 · 3 삭제 · 2 빈 칸", not bad, str(bad))
        os.chmod(noread, 0o600)
        bad = [(k, ledger_cmd(home, "transcript", k).returncode) for k in ("bbbb0000", "XYZ", "../../etc", "")]
        check("3 경로: 대장에 없는 id · id 꼴이 아닌 값은 exit 2", all(rc == 2 for _, rc in bad), str(bad))
        r = ledger_cmd(home, "get", "aaaa0001")
        check("3 get: 대장 한 줄을 그대로 낸다", r.returncode == 0 and json.loads(r.stdout)["id"] == "aaaa0001", r.stdout)


def test_perms():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        append(home, "qa", "범위 준수", "RESULT: BLOCKED a")
        mode = ledger_path(home).stat().st_mode & 0o777
        check("4 권한: 새 대장은 600", mode == 0o600, oct(mode))
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        ledger_path(home).write_text("", encoding="utf-8")
        os.chmod(ledger_path(home), 0o644)
        r = append(home, "qa", "범위 준수", "RESULT: BLOCKED b")
        t41 = history_t41(home)
        check("4 권한: 644 대장에는 add 거부, history 는 id 없이 1줄", ledger_path(home).read_text(encoding="utf-8") == ""
              and len(t41) == 1 and "[t41id:" not in t41[0] and "권한" in r.stderr and r.returncode == 0, f"{t41} {r.stderr[:200]}")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(Path(tmp) / "h")
        target = Path(tmp) / "victim.txt"
        target.write_text("keep\n", encoding="utf-8")
        os.chmod(target, 0o600)
        ledger_path(home).symlink_to(target)
        r = append(home, "qa", "범위 준수", "RESULT: BLOCKED c")
        t41 = history_t41(home)
        check("4 권한: 링크 대장에는 add 거부(링크 대상 불변), history 는 id 없이 1줄",
              target.read_text(encoding="utf-8") == "keep\n" and len(t41) == 1 and "[t41id:" not in t41[0] and "링크" in r.stderr,
              f"{t41} {r.stderr[:200]}")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(Path(tmp) / "h")
        other = Path(tmp) / "elsewhere"
        other.mkdir()
        shutil.rmtree(home / ".claude/_evolve")
        (home / ".claude/_evolve").symlink_to(other)
        r = append(home, "qa", "범위 준수", "RESULT: BLOCKED e")
        t41 = history_t41(home)
        check("4 권한: _evolve 가 링크면 add 거부(대상에 대장 · 잠금 없음), history 는 id 없이 1줄",
              not (other / "t41-ledger.jsonl").exists() and not (other / "t41-ledger.lock").exists() and len(t41) == 1
              and "[t41id:" not in t41[0] and "_evolve" in r.stderr, f"{t41} {r.stderr[:200]}")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(Path(tmp) / "h")
        sd = shim(Path(tmp) / "shim", "jq", "exit 127\n")
        r = append(home, "qa", "범위 준수", "RESULT: BLOCKED d", path_prefix=str(sd))
        t41 = history_t41(home)
        check("4 안정성: jq 실패면 id 없이 기록, exit 0", r.returncode == 0 and len(t41) == 1 and "[t41id:" not in t41[0], f"{t41} {r.stderr[:200]}")
    with tempfile.TemporaryDirectory() as tmp:
        home, sess, rtp, _ = build_join_home(Path(tmp) / "h", "RESULT: FAIL 1")
        real_jq = shutil.which("jq")
        sd = shim(Path(tmp) / "shim", "jq", f'case "$*" in *customAgentType*) sleep 4 ;; esac\nexec "{real_jq}" "$@"\n')
        t = time.time()
        r = run(["bash", str(SCRIPTS / "t41-subagent-stop.sh")], home, path_prefix=str(sd), payload=stop_payload(sess, rtp))
        el = time.time() - t
        rows = ledger_rows(home)
        check("4 안정성: find-actor 시간 초과면 2초대에 끝나고 행위자 빈 칸 + id 기록",
              el < 3.8 and r.returncode == 0 and len(rows) == 1 and rows[0]["actor"] == "" and len(history_t41(home)) == 1,
              f"{el:.2f}s {rows} {r.stderr[:200]}")


def test_concurrency():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        env = env_for(home)
        procs = [subprocess.Popen(["bash", str(SCRIPTS / "t41-append.sh"), "--from", "qa", "--signal", f"from=qa | RESULT: FAIL n{i}"],
                                  env=env, cwd=str(SCRIPTS.parent), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                 for i in range(10)]
        errs = [p.communicate()[1] for p in procs]
        t41 = history_t41(home)
        ids = [m for ln in t41 for m in ID_TAG.findall(ln)]
        rows = ledger_rows(home)
        check("5 동시성: history 10줄 · id 10종 · JSON 10행 · 대장 id 와 같음",
              len(t41) == 10 and len(set(ids)) == 10 and len(rows) == 10 and {r["id"] for r in rows} == set(ids),
              f"t41={len(t41)} ids={len(set(ids))} rows={len(rows)} {[e for e in errs if e][:2]}")


def usage_env(tmp):
    home = Path(tmp) / "uhome"
    claude = home / ".claude"
    for sub in ("_evolve", "_usage", "_audit", "agents", "scripts", "projects"):
        (claude / sub).mkdir(parents=True)
    for n in ("harness-usage-check.sh", "candidates-append.sh", "decisions-prune.sh", "agent-crosscheck.sh", "role-alias.sh",
              "harness_registry.py"):
        shutil.copy(SCRIPTS / n, claude / "scripts" / n)
    (claude / "config/hosts").mkdir(parents=True)
    (claude / "config/hosts" / f"{socket.gethostname()}.json").write_text(
        '{"paths": {"short_term_root": "~/.claude/projects/-home-user-workspace/memory/"}}', encoding="utf-8")
    (claude / "scripts/agent-crosscheck.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (claude / "_evolve/candidates.tsv").write_text("id\tsource\t생성일\tbench_id\tstatus\t요약\tnote\n", encoding="utf-8")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    (claude / "_evolve/crosscheck.tsv").write_text(f"{now}\tD\t1\t1\t일치\n", encoding="utf-8")
    proj = Path(tmp) / "uproj"
    proj.mkdir()
    return home, proj


def test_compat():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(Path(tmp) / "h")
        for i in range(3):
            append(home, "--from", "qa", "--signal", f"from=qa | RESULT: FAIL r{i}")
        hist = (home / ".claude/_audit/history.md").read_text(encoding="utf-8")
        t41 = history_t41(home)
        check("6 호환: id 붙은 3줄 준비", len(t41) == 3 and all(len(ID_TAG.findall(x)) == 1 for x in t41), str(t41))
        uhome, proj = usage_env(tmp)
        (uhome / ".claude/_audit/history.md").write_text(hist, encoding="utf-8")
        r = subprocess.run(["bash", str(uhome / ".claude/scripts/harness-usage-check.sh")], capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(uhome)), cwd=str(proj), timeout=90, check=False)
        check("6 호환: T41_REPEAT «coder/구현 정확성 ×3» 그대로", "T41_REPEAT: coder/구현 정확성 ×3" in r.stdout, r.stdout[-600:])
        cand = (home / ".claude/_evolve/candidates.tsv").read_text(encoding="utf-8")
        check("6 호환: 후보 요약에 id 가 없다", "t41id" not in cand and cand.count("coder/구현 정확성:") == 3, cand)
        key = (home / ".claude/_usage/t41-recent.tsv").read_text(encoding="utf-8")
        check("6 호환: 10분 억제 키에 id 가 없다", "t41id" not in key, key)
        r = append(home, "--from", "qa", "--signal", "from=qa | RESULT: FAIL r0")
        check("6 호환: 같은 신호는 10분 안 다시 기록 안 함(history · 대장 불변)", len(history_t41(home)) == 3 and len(ledger_rows(home)) == 3
              and "건너뜀" in r.stderr, f"{history_t41(home)} {r.stderr[:200]}")
        src = (SCRIPTS / "spawn-tree.sh").read_text(encoding="utf-8")
        m = re.search(r"history\)\s+printf '%s\\n' \"\$2\" \| grep -qE '([^']+)'", src)
        bad = [ln for ln in t41 if not m or subprocess.run(["grep", "-qE", m.group(1)], input=ln + "\n", text=True, check=False).returncode != 0]
        check("6 호환: spawn-tree.sh history 줄 형식 검사 통과", m is not None and not bad, f"pattern={'ok' if m else 'not found'} bad={bad}")
        r = ledger_cmd(home, "stats")
        check("6 stats: 새 T41 · 짧은 id · 행위자 비율과 보존일을 낸다", r.returncode == 0 and "새 T41 3건 · 짧은 id 3건(100.0%)" in r.stdout
              and "행위자 찾음 0건" in r.stdout and "유효 보존일" in r.stdout, r.stdout + r.stderr)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        r = ledger_cmd(home, "stats", "--since", "2999-01-01")
        check("6 stats: 새 T41 이 0 이면 «새 T41 0건» 만", r.returncode == 0 and r.stdout.startswith("새 T41 0건") and "%" not in r.stdout, r.stdout)
        (home / ".claude/_audit/history.md").write_text("# h\n- 2026-11-16 T41: coder/구현 정확성 — RESULT: FAIL\n", encoding="utf-8")
        r = ledger_cmd(home, "stats")
        check("6 stats: 짧은 id 가 0 이면 «짧은 id 0건» 만", r.stdout.startswith("짧은 id 0건") and "%" not in r.stdout, r.stdout)


def test_context_axes():
    sh = os.environ.get("T41_APPEND_SH") or str(SCRIPTS / "t41-append.sh")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        for dim, sig in (("맥락누락", "재작업 a"), ("맥락 누락", "재작업 b"), ("방향이탈", "재작업 c"), ("방향 이탈", "재작업 d")):
            run(["bash", sh, "coder", dim, sig], home)
        t41 = [re.sub(r"\[t41id:[0-9a-f]{8}\] ", "", ln) for ln in history_t41(home)]
        check("W4 축: 맥락 누락 두 꼴이 같은 축으로", sum(" T41: coder/맥락 누락 — 재작업 " in ln for ln in t41) == 2, str(t41))
        check("W4 축: 방향 이탈 두 꼴이 같은 축으로", sum(" T41: coder/방향 이탈 — 재작업 " in ln for ln in t41) == 2, str(t41))
        check("W4 축: 대장 dim 도 띄어 쓴 이름", sorted({r.get("dim") for r in ledger_rows(home)}) == ["맥락 누락", "방향 이탈"],
              str(ledger_rows(home)))
        r = run(["bash", sh], home)
        check("W4 축: 사용법에 두 축 정의", r.returncode == 2 and "맥락 누락(지시문에 없던 정보" in r.stderr
              and "방향 이탈(지시문에 있었는데" in r.stderr, r.stderr)


ALL_TESTS = (test_id, test_join, test_join_review, test_paths, test_perms, test_concurrency, test_compat, test_stats_breakdown,
             test_context_axes)
# WHY: 인자로 함수 이름을 주면 그것만 돈다(scripts/tests/test_t41_ledger_mutation.py 가 변형마다 해당 시험만 돌리려고 쓴다).
for fn in ALL_TESTS:
    if len(sys.argv) < 2 or fn.__name__ in sys.argv[1:]:
        fn()

fail = 0
for name, ok, detail in results:
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       실제: {detail[:400]}")
    fail += 0 if ok else 1

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(results)} checks)")
sys.exit(1 if fail else 0)
