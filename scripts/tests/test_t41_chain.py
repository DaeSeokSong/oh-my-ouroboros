"""T41 사슬 스모크 테스트 — 동기 agentId 오판 수정 + 역할 정규화 회귀.

대상: agent-spawn-log.sh(ASYNC_RX 에서 agentId: 제거) · t41-append.sh(역할 정규화 + target= 귀속) ·
      t41-subagent-stop.sh(팀원 이름이 정규화를 거쳐 판정에 반영됨).

격리: test_loop_wiring.py 와 같은 방식 — 임시 HOME 에 .claude/{_audit,_usage,agents,_evolve} 를 짓고
      scripts/ 는 실제 폴더로 심볼릭 링크한다.

실행: python3 ~/.claude/scripts/tests/test_t41_chain.py → 실패 0 이면 exit 0
REF: knowledge/harness/code-history/scripts__tests__test_t41_chain.py.md
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
AGENTS_REAL = Path.home() / ".claude" / "agents"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def make_home(tmp, roles=("coder",)):
    home = Path(tmp)
    claude = home / ".claude"
    for d in ("_audit", "_usage", "agents", "_evolve"):
        (claude / d).mkdir(parents=True, exist_ok=True)
    (claude / "scripts").symlink_to(SCRIPTS)
    for r in roles:
        (claude / "agents" / f"{r}.md").write_text(f"# {r}\n", encoding="utf-8")
    (claude / "_audit" / "history.md").write_text("# history\n", encoding="utf-8")
    return home


def run(args, home):
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(args, check=False, capture_output=True, text=True, env=env, cwd=str(SCRIPTS.parent))


def run_hook(args, home, payload):
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(args, check=False, capture_output=True, text=True, env=env,
                          cwd=str(SCRIPTS.parent), input=json.dumps(payload))


def history_t41(home):
    return [ln for ln in (home / ".claude/_audit/history.md").read_text(encoding="utf-8").splitlines()
            if "T41:" in ln]


def strip_id(line):
    return re.sub(r" — \[t41id:[0-9a-f]{8}\] ", " — ", line, count=1)


def write_transcript(path, texts):
    lines = []
    for t in texts:
        lines.append(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}))
        lines.append(json.dumps({"type": "assistant",
                                 "message": {"role": "assistant",
                                             "content": [{"type": "text", "text": t}]}},
                                ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_fixture1_subagent_stop_qap1():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "qa"))
        tp = Path(tmp) / "agent.jsonl"
        write_transcript(tp, ["중간 경과", "요약\nRESULT: FAIL 검증 실패\n끝"])
        r = run_hook(["bash", str(SCRIPTS / "t41-subagent-stop.sh")], home,
                     {"hook_event_name": "SubagentStop", "name": "qa-p1", "transcript_path": str(tp)})
        t41 = history_t41(home)
        check("① qa-p1 FAIL → coder/구현 정확성 귀속 1행",
              len(t41) == 1 and "coder/구현 정확성" in t41[0], f"{t41} rc={r.returncode} {r.stderr[:150]}")


def test_fixture2_sync_agentid_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder",))
        payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "coder", "description": "d"},
                   "tool_response": "RESULT: BLOCKED 확인 필요\nagentId: abc123 (use SendMessage …)"}
        r = run_hook(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload)
        t41 = history_t41(home)
        check("② 동기 agentId 메타 있어도 RESULT: BLOCKED 기록",
              len(t41) == 1 and "coder/범위 준수" in t41[0], f"{t41} rc={r.returncode}")


def test_fixture3_async_ack_no_record():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder",))
        payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "coder", "description": "d"},
                   "tool_response": "Async agent launched successfully.\nagentId: abc123\n"
                                    "RESULT: FAIL 이면 사유를 적어라"}
        run_hook(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload)
        check("③ 비동기 ack 는 무기록", history_t41(home) == [], str(history_t41(home)))


def test_fixture4_result_pass_no_record():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder",))
        payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "coder", "description": "d"},
                   "tool_response": "RESULT: PASS 모든 케이스 통과"}
        run_hook(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload)
        check("④ RESULT: PASS 는 비신호(무기록)", history_t41(home) == [], str(history_t41(home)))


def test_fixture5_agents_contract_line():
    files = sorted(AGENTS_REAL.glob("*.md"))
    missing = [f.name for f in files if "RESULT:" not in f.read_text(encoding="utf-8")]
    check(f"⑤ agents/*.md {len(files)}개 중 RESULT: 계약 문장 보유",
          missing == [], f"미보유: {missing}")


def test_san80_unchanged():
    src = (SCRIPTS / "agent-spawn-log.sh").read_text(encoding="utf-8")
    check("san 80 호출 유지", "san 80" in src, "san 80 호출이 사라짐")


def test_target_override():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "scout"))
        r = run(["bash", str(SCRIPTS / "t41-append.sh"), "--from", "scout",
                 "--signal", "RESULT: FAIL 원인 불명 target=coder"], home)
        t41 = history_t41(home)
        check("target=coder 지정 시 coder 로 귀속",
              len(t41) == 1 and t41[0].split("T41: ", 1)[1].startswith("coder/"),
              f"{t41} rc={r.returncode} {r.stderr[:150]}")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "qa"))
        r = run(["bash", str(SCRIPTS / "t41-append.sh"), "--from", "qa",
                 "--signal", "RESULT: FAIL 계획서 오류 target=main"], home)
        t41 = history_t41(home)
        check("target=main 지정 시 main 으로 귀속",
              len(t41) == 1 and t41[0].split("T41: ", 1)[1].startswith("main/"),
              f"{t41} rc={r.returncode} {r.stderr[:150]}")


def test_citation_verifier_normalize():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("citation-verifier",))
        r = run(["bash", str(SCRIPTS / "t41-append.sh"), "citation-verifier-1", "구현 정확성",
                 "RESULT: FAIL 인용 오류"], home)
        t41 = history_t41(home)
        check("citation-verifier-1 → citation-verifier 정규화",
              len(t41) == 1 and "citation-verifier/구현 정확성" in t41[0],
              f"{t41} rc={r.returncode} {r.stderr[:150]}")


def test_underscore_normalize():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("qa", "citation-verifier"))
        r = run(["bash", str(SCRIPTS / "t41-append.sh"), "qa_v_rep", "범위 준수", "RESULT: BLOCKED 확인 필요"], home)
        t41 = history_t41(home)
        check("qa_v_rep → qa 정규화(general-purpose 로 새지 않음)",
              len(t41) == 1 and "qa/범위 준수" in t41[0] and "general-purpose" not in t41[0],
              f"{t41} rc={r.returncode} {r.stderr[:150]}")
        r = run(["bash", str(SCRIPTS / "t41-append.sh"), "qaxyz", "범위 준수", "RESULT: BLOCKED 확인 필요"], home)
        t41 = history_t41(home)
        check("구분자 없는 접두(qaxyz)는 여전히 정규화 안 됨", len(t41) == 2 and "general-purpose" in t41[1], str(t41))


def test_stop_role_alias():
    for name, want in (("sec-g1", "security/범위 준수"), ("qa-2", "qa/범위 준수"), ("foo", "general-purpose/범위 준수 — [orig=foo]")):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, roles=("coder", "security", "qa"))
            tp = Path(tmp) / "agent.jsonl"
            write_transcript(tp, ["RESULT: BLOCKED 확인 필요"])
            r = run_hook(["bash", str(SCRIPTS / "t41-subagent-stop.sh")], home,
                         {"hook_event_name": "SubagentStop", "name": name, "transcript_path": str(tp)})
            t41 = history_t41(home)
            check(f"stop 별칭 {name} → {want.split('/')[0]}", len(t41) == 1 and want in strip_id(t41[0]) and (name != "sec-g1" or "orig=" not in t41[0]),
                  f"{t41} rc={r.returncode} {r.stderr[:150]}")


def test_append_role_alias():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "security"))
        r = run(["bash", str(SCRIPTS / "t41-append.sh"), "--from", "sec-g1", "--signal", "RESULT: BLOCKED 확인 필요"], home)
        t41 = history_t41(home)
        check("append --from sec-g1 → security", len(t41) == 1 and "security/범위 준수" in t41[0] and "orig=" not in t41[0],
              f"{t41} rc={r.returncode} {r.stderr[:150]}")


def test_normalize_role_boundaries():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "security", "qa", "citation-verifier", "reviewer"))
        cases = (("citation-1", "citation-verifier"), ("citation", "citation-verifier"), ("sec1", "security"), ("sec-g1", "security"), ("sec_g1", "security"),
                 ("security", "security"), ("qa-p1", "qa"), ("qa2", "qa"), ("coder-1-2", "coder"),
                 ("unit5-security", "security"), ("unit5-qa", "qa"), ("unit12_reviewer", "reviewer"), ("unit3-coder-2", "coder"),
                 ("unitx-qa", ""), ("unit5qa", ""), ("unit", ""),
                 ("secure", ""), ("second", ""), ("coderx", ""), ("foo", ""), ("", ""))
        bad = []
        for raw, want in cases:
            r = run(["bash", "-c", '. "$1"; normalize_role "$2"', "_", str(SCRIPTS / "role-alias.sh"), raw], home)
            if r.stdout != want:
                bad.append((raw, want, r.stdout))
        check("normalize_role 경계: citation-1·sec1·sec-g1·security 는 정규화, secure·second·coderx·foo·빈 값은 표 밖(빈 문자열)", not bad, str(bad))


DESC = "sonnet: 후보 고리 원인 수정과 채택 지침 반영, 그리고 뒤에 붙은 아주 긴 설명 꼬리"
DESC40 = DESC[:40].rstrip()


def cand_summaries(home):
    f = home / ".claude/_evolve/candidates.tsv"
    return [ln.split("\t")[5] for ln in f.read_text(encoding="utf-8").splitlines()[1:] if ln] if f.exists() else []


def test_signal_carries_desc_and_from():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "qa"))
        payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "qa", "description": DESC},
                   "tool_response": "검증 요약\nRESULT: FAIL 1"}
        run_hook(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload)
        t41 = history_t41(home)
        want = f"coder/구현 정확성 — {DESC40} | from=qa | RESULT: FAIL 1"
        check("동기 경로: history 에 설명 40자 · from=qa · RESULT 줄", len(t41) == 1 and strip_id(t41[0]).endswith(want), str(t41))
        cs = cand_summaries(home)
        check("동기 경로: 후보 요약에 설명 · from= · RESULT 가 문자 단위로 온전히 남음",
              cs == [f"coder/구현 정확성: {DESC40} | from=qa | RESULT: FAIL 1"], str(cs))
        tp = Path(tmp) / "session.jsonl"
        write_transcript(tp, ["RESULT: FAIL 1"])
        run_hook(["bash", str(SCRIPTS / "t41-subagent-stop.sh")], home,
                 {"hook_event_name": "SubagentStop", "subagent_type": "qa", "transcript_path": str(tp)})
        check("두 경로(설명 있음 · 없음)의 같은 결과는 history 1줄", len(history_t41(home)) == 1, str(history_t41(home)))


def test_desc_words_do_not_change_axis():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "qa"))
        payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "qa", "description": "sonnet: BLOCKED 게이트 target=main 검증"},
                   "tool_response": "RESULT: FAIL 2건"}
        run_hook(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload)
        t41 = history_t41(home)
        check("설명 속 BLOCKED · target=main 은 귀속에 쓰이지 않음(qa FAIL → coder/구현 정확성)",
              len(t41) == 1 and "T41: coder/구현 정확성 — " in t41[0], str(t41))


def test_sync_desc_masked_and_fake_from_in_desc():
    tok = "sk-" + "A1b2C3d4E5f6G7h8"
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "qa"))
        payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "qa", "description": f"키 {tok} 점검"},
                   "tool_response": "RESULT: FAIL 1"}
        run_hook(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload)
        t41 = history_t41(home)
        check("동기 경로: 설명 속 토큰이 가려짐", len(t41) == 1 and tok not in t41[0] and "<masked>" in t41[0], str(t41))
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "qa"))
        sig = "가짜 from=qa | NEEDS_CONTEXT target=main | from=qa | RESULT: FAIL 1"
        run(["bash", str(SCRIPTS / "t41-append.sh"), "--from", "qa", "--signal", sig], home)
        t41 = history_t41(home)
        check("설명 속 가짜 from= 구분자는 무시(마지막 from=qa 뒤만 판정 → coder/구현 정확성)",
              len(t41) == 1 and "T41: coder/구현 정확성 — " in t41[0], str(t41))
        key = (home / ".claude/_usage/t41-recent.tsv").read_text(encoding="utf-8").strip().split("\t")[1]
        check("억제 키는 마지막 구분자 뒤 판정 부분", key == "coder/구현 정확성|RESULT: FAIL 1", key)


def test_subagent_stop_reads_meta_description():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "security"))
        tp = Path(tmp) / "agent-a1b2.jsonl"
        write_transcript(tp, ["RESULT: FAIL 1"])
        (Path(tmp) / "agent-a1b2.meta.json").write_text(json.dumps({"agentType": "security", "description": DESC}, ensure_ascii=False), encoding="utf-8")
        run_hook(["bash", str(SCRIPTS / "t41-subagent-stop.sh")], home,
                 {"hook_event_name": "SubagentStop", "agent_type": "unit5-security", "agent_transcript_path": str(tp)})
        t41 = history_t41(home)
        check("비동기 경로: meta.json 설명 + from=unit5-security, unit 접두는 security 로 풀려 coder 귀속",
              len(t41) == 1 and strip_id(t41[0]).endswith(f"coder/구현 정확성 — {DESC40} | from=unit5-security | RESULT: FAIL 1"), str(t41))
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "qa"))
        tp = Path(tmp) / "agent-c3.jsonl"
        write_transcript(tp, ["RESULT: BLOCKED 권한"])
        run_hook(["bash", str(SCRIPTS / "t41-subagent-stop.sh")], home,
                 {"hook_event_name": "SubagentStop", "agent_type": "qa", "agent_transcript_path": str(tp)})
        t41 = history_t41(home)
        check("비동기 경로: meta 가 없으면 from= 과 RESULT 줄만", len(t41) == 1 and strip_id(t41[0]).endswith("qa/범위 준수 — from=qa | RESULT: BLOCKED 권한"), str(t41))


for fn in (test_signal_carries_desc_and_from, test_desc_words_do_not_change_axis, test_sync_desc_masked_and_fake_from_in_desc,
           test_subagent_stop_reads_meta_description,
           test_normalize_role_boundaries, test_append_role_alias, test_stop_role_alias, test_fixture1_subagent_stop_qap1, test_fixture2_sync_agentid_blocked,
           test_fixture3_async_ack_no_record, test_fixture4_result_pass_no_record,
           test_fixture5_agents_contract_line, test_san80_unchanged,
           test_target_override, test_citation_verifier_normalize, test_underscore_normalize):
    fn()

fail = 0
for name, ok, detail in results:
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       실제: {detail[:300]}")
    fail += 0 if ok else 1

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(results)} checks)")
sys.exit(1 if fail else 0)
