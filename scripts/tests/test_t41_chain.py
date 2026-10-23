"""T41 사슬 스모크 테스트 — 동기 agentId 오판 수정 + 역할 정규화 회귀 (2026-09-26 신설).

대상: agent-spawn-log.sh(ASYNC_RX 에서 agentId: 제거) · t41-append.sh(역할 정규화 + target= 귀속) ·
      t41-subagent-stop.sh(팀원 이름이 정규화를 거쳐 판정에 반영됨).

격리: test_loop_wiring.py 와 같은 방식 — 임시 HOME 에 .claude/{_audit,_usage,agents,_evolve} 를 짓고
      scripts/ 는 실제 폴더로 심볼릭 링크한다.

실행: python3 ~/.claude/scripts/tests/test_t41_chain.py → 실패 0 이면 exit 0
"""

import json
import os
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


def write_transcript(path, texts):
    lines = []
    for t in texts:
        lines.append(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}))
        lines.append(json.dumps({"type": "assistant",
                                 "message": {"role": "assistant",
                                             "content": [{"type": "text", "text": t}]}},
                                ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── 픽스처 ① SubagentStop: name=qa-p1, 마지막 블록 RESULT: FAIL → 정규화 후 현행 귀속(coder)
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


# ── 픽스처 ② 동기 tool_response(agentId 메타 동반) RESULT: BLOCKED → 1행
def test_fixture2_sync_agentid_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder",))
        payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "coder", "description": "d"},
                   "tool_response": "RESULT: BLOCKED 확인 필요\nagentId: abc123 (use SendMessage …)"}
        r = run_hook(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload)
        t41 = history_t41(home)
        check("② 동기 agentId 메타 있어도 RESULT: BLOCKED 기록",
              len(t41) == 1 and "coder/범위 준수" in t41[0], f"{t41} rc={r.returncode}")


# ── 픽스처 ③ 비동기 ack(세 문구 있음) → 0행
def test_fixture3_async_ack_no_record():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder",))
        payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "coder", "description": "d"},
                   "tool_response": "Async agent launched successfully.\nagentId: abc123\n"
                                    "RESULT: FAIL 이면 사유를 적어라"}
        run_hook(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload)
        check("③ 비동기 ack 는 무기록", history_t41(home) == [], str(history_t41(home)))


# ── 픽스처 ④ 마지막 블록 RESULT: PASS → 0행 (DONE 을 정규식에 넣는 회귀 방지)
def test_fixture4_result_pass_no_record():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder",))
        payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "coder", "description": "d"},
                   "tool_response": "RESULT: PASS 모든 케이스 통과"}
        run_hook(["bash", str(SCRIPTS / "agent-spawn-log.sh"), "post"], home, payload)
        check("④ RESULT: PASS 는 비신호(무기록)", history_t41(home) == [], str(history_t41(home)))


# ── 픽스처 ⑤ agents/*.md 전부에 RESULT: 계약 문장 존재 (실제 ~/.claude/agents, 패키지 B 대기)
def test_fixture5_agents_contract_line():
    files = sorted(AGENTS_REAL.glob("*.md"))
    missing = [f.name for f in files if "RESULT:" not in f.read_text(encoding="utf-8")]
    check(f"⑤ agents/*.md {len(files)}개 중 RESULT: 계약 문장 보유",
          missing == [], f"미보유: {missing}")


# ── 추가 어서션: san 80 절단 불변
def test_san80_unchanged():
    src = (SCRIPTS / "agent-spawn-log.sh").read_text(encoding="utf-8")
    check("san 80 호출 유지", "san 80" in src, "san 80 호출이 사라짐")


# ── 추가 어서션: target=coder 명시 귀속
def test_target_override():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "scout"))
        r = run(["bash", str(SCRIPTS / "t41-append.sh"), "--from", "scout",
                 "--signal", "RESULT: FAIL 원인 불명 target=coder"], home)
        t41 = history_t41(home)
        check("target=coder 지정 시 coder 로 귀속",
              len(t41) == 1 and t41[0].split("T41: ", 1)[1].startswith("coder/"),
              f"{t41} rc={r.returncode} {r.stderr[:150]}")
    # target=main 은 agents/ 파일이 없어도 main 으로 귀속돼야 한다(09-26 첫 실기록 오귀속 재발 방지)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "qa"))
        r = run(["bash", str(SCRIPTS / "t41-append.sh"), "--from", "qa",
                 "--signal", "RESULT: FAIL 계획서 오류 target=main"], home)
        t41 = history_t41(home)
        check("target=main 지정 시 main 으로 귀속",
              len(t41) == 1 and t41[0].split("T41: ", 1)[1].startswith("main/"),
              f"{t41} rc={r.returncode} {r.stderr[:150]}")


# ── 추가 어서션: citation-verifier-1 → citation-verifier 정규화 (첫 조각 규칙 기각 반례)
def test_citation_verifier_normalize():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("citation-verifier",))
        r = run(["bash", str(SCRIPTS / "t41-append.sh"), "citation-verifier-1", "구현 정확성",
                 "RESULT: FAIL 인용 오류"], home)
        t41 = history_t41(home)
        check("citation-verifier-1 → citation-verifier 정규화",
              len(t41) == 1 and "citation-verifier/구현 정확성" in t41[0],
              f"{t41} rc={r.returncode} {r.stderr[:150]}")


# ── 2026-10-17 G2: 구분자 `_` 도 `-` 와 같이 정규화 (qa_v_rep → qa)
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


# ── 2026-10-17: SubagentStop 역할 별칭 표 (sec-g1→security, qa-2→qa, foo→foo 그대로)
def test_stop_role_alias():
    # foo 는 표 밖이라 훅이 그대로(foo) 넘기고, 뒤단 t41-append.sh 가 agents/ 에 없는 이름을 general-purpose + [orig=foo] 로 남긴다
    for name, want in (("sec-g1", "security/범위 준수"), ("qa-2", "qa/범위 준수"), ("foo", "general-purpose/범위 준수 — [orig=foo]")):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp, roles=("coder", "security", "qa"))
            tp = Path(tmp) / "agent.jsonl"
            write_transcript(tp, ["RESULT: BLOCKED 확인 필요"])
            r = run_hook(["bash", str(SCRIPTS / "t41-subagent-stop.sh")], home,
                         {"hook_event_name": "SubagentStop", "name": name, "transcript_path": str(tp)})
            t41 = history_t41(home)
            check(f"stop 별칭 {name} → {want.split('/')[0]}", len(t41) == 1 and want in t41[0] and (name != "sec-g1" or "orig=" not in t41[0]),
                  f"{t41} rc={r.returncode} {r.stderr[:150]}")


# ── 2026-10-17: t41-append.sh 를 직접 부르는 경로도 같은 별칭 표(--from sec-g1 → security)
def test_append_role_alias():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "security"))
        r = run(["bash", str(SCRIPTS / "t41-append.sh"), "--from", "sec-g1", "--signal", "RESULT: BLOCKED 확인 필요"], home)
        t41 = history_t41(home)
        check("append --from sec-g1 → security", len(t41) == 1 and "security/범위 준수" in t41[0] and "orig=" not in t41[0],
              f"{t41} rc={r.returncode} {r.stderr[:150]}")


# ── 2026-10-17 검수팀: role-alias.sh normalize_role 경계 값 (줄임말 접두는 끝·`-`·`_`·숫자 앞에서만 인정, 표 밖 이름은 빈 문자열)
def test_normalize_role_boundaries():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, roles=("coder", "security", "qa", "citation-verifier"))
        cases = (("citation-1", "citation-verifier"), ("citation", "citation-verifier"), ("sec1", "security"), ("sec-g1", "security"), ("sec_g1", "security"),
                 ("security", "security"), ("qa-p1", "qa"), ("qa2", "qa"), ("coder-1-2", "coder"),
                 ("secure", ""), ("second", ""), ("coderx", ""), ("foo", ""), ("", ""))
        bad = []
        for raw, want in cases:
            r = run(["bash", "-c", '. "$1"; normalize_role "$2"', "_", str(SCRIPTS / "role-alias.sh"), raw], home)
            if r.stdout != want:
                bad.append((raw, want, r.stdout))
        check("normalize_role 경계: citation-1·sec1·sec-g1·security 는 정규화, secure·second·coderx·foo·빈 값은 표 밖(빈 문자열)", not bad, str(bad))


for fn in (test_normalize_role_boundaries, test_append_role_alias, test_stop_role_alias, test_fixture1_subagent_stop_qap1, test_fixture2_sync_agentid_blocked,
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
