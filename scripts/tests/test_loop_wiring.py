"""자기개선 루프 배선 회귀 테스트 (2026-09-14 신설).

대상: candidates-append.sh(대장 단일 쓰기 경로·동시 갱신) · pattern-detect.sh(T40 후보 기록) ·
      correction-detect.sh(T12 후보 기록) · prompt-log.sh(보관 길이·skip) ·
      agent-spawn-log.sh(post 실패 신호 → t41-append.sh) · t41-subagent-stop.sh(비동기 소집 결과) ·
      t41-append.sh(history + 후보 대장 + 역할 귀속·10분 중복) · oversight-append.sh(6열·어휘) ·
      harness-usage-check.sh(경보 7종의 발화·비발화).

격리: 매 케이스마다 임시 HOME 을 만들고 그 안에 .claude/{_evolve,_audit,_usage,agents} 를 짓고
      scripts/ 는 실제 폴더로 심볼릭 링크한다. 스크립트들이 전부 $HOME/.claude 를 기준으로 읽고 쓰므로
      HOME 만 바꾸면 실제 원장(_evolve/candidates.tsv·_audit/*)을 건드리지 않는다
      (test_bash_write_check.py 의 HOME 치환 격리와 같은 방식).

실행: python3 ~/.claude/scripts/tests/test_loop_wiring.py → 실패 0 이면 exit 0
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
CANDIDATE_HEADER = "id\tsource\t생성일\tbench_id\tstatus\t요약\n"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def make_home(tmp):
    """임시 HOME 뼈대 — 실제 원장 대신 여기로 쓰이게 한다."""
    home = Path(tmp)
    claude = home / ".claude"
    for d in ("_evolve", "_audit", "_usage", "agents"):
        (claude / d).mkdir(parents=True, exist_ok=True)
    (claude / "scripts").symlink_to(SCRIPTS)
    (claude / "agents" / "coder.md").write_text("# coder\n", encoding="utf-8")
    (claude / "_audit" / "history.md").write_text("# history\n", encoding="utf-8")
    return home


def run(args, home, cwd=None):
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(args, capture_output=True, text=True, env=env,
                          cwd=cwd or str(SCRIPTS.parent), input=None, check=False)


def run_hook(args, home, payload, cwd=None):
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(args, capture_output=True, text=True, env=env,
                          cwd=cwd or str(SCRIPTS.parent), input=json.dumps(payload), check=False)


def cand_rows(home):
    f = home / ".claude/_evolve/candidates.tsv"
    if not f.exists():
        return []
    return [ln for ln in f.read_text(encoding="utf-8").splitlines()
            if ln and not ln.startswith("id\t")]


def write_prompts(home, prompts):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lines = [json.dumps({"ts": ts, "cwd": "/x", "prompt": p}, ensure_ascii=False) for p in prompts]
    (home / ".claude/_evolve/prompts.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── 0) candidates-append.sh : 대장의 단일 쓰기 경로 (동시 갱신 유실 회귀 — 2026-09-14 재감사 B1)
def test_candidates_append():
    helper = str(SCRIPTS / "candidates-append.sh")

    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        env = dict(os.environ, HOME=str(home))
        # 10병렬 — 종전 cp→mv 판에서는 여기서 8행이 사라졌다(재감사 실증). 유실 0이 합격선이다.
        procs = [subprocess.Popen(["bash", helper, "T41", f"동시 신호 {i}"],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for i in range(10)]
        outs = [p.communicate() for p in procs]
        rows = cand_rows(home)
        check("candidates-append: 10병렬 유실 0", len(rows) == 10, f"{len(rows)}행")
        ids = sorted(r.split("\t")[0] for r in rows)
        stamp = time.strftime("%Y%m%d")
        want = [f"T41-{stamp}-{i:02d}" for i in range(1, 11)]
        check("candidates-append: id 연번 1~10", ids == want, str(ids))
        check("candidates-append: 병렬 전원 rc 0", all(p.returncode == 0 for p in procs),
              str([p.returncode for p in procs]))
        check("candidates-append: 병렬 stderr 없음", all(e == "" for _, e in outs), str(outs)[:200])
        check("candidates-append: 헤더 1줄 유지",
              (home / ".claude/_evolve/candidates.tsv").read_text(encoding="utf-8")
              .count("id\tsource") == 1, "")

    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        r1 = run(["bash", helper, "T40", "같은 요약"], home)
        r2 = run(["bash", helper, "T40", "같은 요약"], home)
        check("candidates-append: 추가 시 rc 0 + id 출력",
              r1.returncode == 0 and r1.stdout.strip().startswith("T40-"), r1.stdout)
        check("candidates-append: 중복은 rc 3", r2.returncode == 3, str(r2.returncode))
        check("candidates-append: 중복이면 무기록", len(cand_rows(home)) == 1, str(cand_rows(home)))
        r3 = run(["bash", helper, "T40", "승인 대기 후보", "pending-approval"], home)
        check("candidates-append: pending 외 status 인자는 무기록",
              len(cand_rows(home)) == 1, str(cand_rows(home)))
        check("candidates-append: pending 외 status 인자 rc 1 (전이는 set)",
              r3.returncode == 1 and "pending 만" in r3.stderr, f"{r3.returncode} {r3.stderr[:120]}")
        r3 = run(["bash", helper, "T40", "승인 대기 후보", "pending"], home)
        r3s = run(["bash", helper, "set", r3.stdout.strip(), "pending-approval"], home)
        check("candidates-append: pending 으로 넣고 set 으로 pending-approval 전이",
              r3.returncode == 0 and r3s.returncode == 0 and cand_rows(home)[-1].split("\t")[4] == "pending-approval",
              f"{r3.returncode} {r3s.returncode} {cand_rows(home)[-1]}")
        r4 = run(["bash", helper, "T40"], home)
        check("candidates-append: 인자 부족은 rc 1 + stderr",
              r4.returncode == 1 and r4.stderr.strip() != "", f"{r4.returncode} {r4.stderr[:120]}")


# ── 1) pattern-detect.sh : T40 후보 기록 + 중복 방지
def test_pattern_detect():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        write_prompts(home, ["토큰 사용량 점검"] * 4 + ["오늘 날씨"])
        r1 = run(["bash", str(SCRIPTS / "pattern-detect.sh"), "3"], home)
        rows = cand_rows(home)
        check("pattern-detect: 기존 stdout 유지", "토큰 사용량 점검" in r1.stdout, r1.stdout.strip())
        check("pattern-detect: 후보 1행 기록", len(rows) == 1, str(rows))
        if rows:
            f = rows[0].split("\t")
            check("pattern-detect: 스키마 7열(note 열 2026-10-17)", len(f) == 7, str(f))
            check("pattern-detect: source=T40", f[1] == "T40", str(f))
            check("pattern-detect: status=pending", f[4] == "pending", str(f))
            check("pattern-detect: bench_id=-", f[3] == "-", str(f))
            check("pattern-detect: id 형식", f[0].startswith("T40-") and len(f[0]) == 15, f[0])
            check("pattern-detect: 요약 ×N", f[5].endswith("×4"), f[5])
        run(["bash", str(SCRIPTS / "pattern-detect.sh"), "3"], home)
        check("pattern-detect: 재실행 중복 없음", len(cand_rows(home)) == 1, str(cand_rows(home)))

    with tempfile.TemporaryDirectory() as tmp:
        # ㅎ 계열(U+D558 이상) 회귀 — 이 서버 grep 3.7 의 `.` 가 «하»·«학»·«한» 을 못 맞혀,
        # 절단 단계에서 줄이 통째로 사라지거나 그 글자 앞에서 잘렸다 (2026-09-14).
        home = make_home(tmp)
        write_prompts(home, ["학습 로그 확인 후 정리"] * 4)
        run(["bash", str(SCRIPTS / "pattern-detect.sh"), "3"], home)
        rows = cand_rows(home)
        check("pattern-detect: ㅎ 계열 글자도 온전히 절단",
              len(rows) == 1 and rows[0].split("\t")[5].startswith("학습 로그 확인"), str(rows))

    with tempfile.TemporaryDirectory() as tmp:
        # 기계 프롬프트(예약 점검 · 측정 회차 · 훅 알림)는 반복 요청으로 세지 않는다 (2026-11-12 T40 미판정 3건)
        home = make_home(tmp)
        write_prompts(home, ["[예약 점검 · 0a1b2c3d] 대기 목록 안전망 확인"] * 4
                      + ["[측정 회차 run-238] 아래 task 블록의 과제를 수행하십시오"] * 4
                      + ["effort-eval 측정 회차 check-I1 입니다. 바로 진행해 주십시오"] * 4
                      + ["[하네스 변경 알림 · 회신 불요] 새 커밋이 생겼습니다"] * 4)
        r = run(["bash", str(SCRIPTS / "pattern-detect.sh"), "3"], home)
        check("pattern-detect: 기계 프롬프트는 세지 않음", cand_rows(home) == [] and r.stdout.strip() == "",
              f"{cand_rows(home)} / {r.stdout[:120]}")


# ── 2) correction-detect.sh : 교정 정규식 6종 + 중복 방지
CORRECTION_CASES = [
    ("하지 마", "그렇게 하지 마세요"),
    ("앞으로는", "앞으로는 파일을 먼저 읽으세요"),
    ("왜 ~했", "왜 그걸 먼저 했나요"),
    ("잘못", "그 판단은 잘못됐습니다"),
    ("다시 ~해", "처음부터 다시 해주세요"),
    ("말라고", "그건 쓰지 말라고 했습니다"),
    # 2026-09-14 추가 4종 — learner.md:11 의 룰 업데이트 표지와 같은 목록
    ("매번", "매번 표를 먼저 보여주세요"),
    ("항상", "항상 존댓말로 보고하세요"),
    ("다시는", "다시는 그 경로를 쓰지 마세요"),
    ("앞으로도", "앞으로도 같은 형식을 유지하세요"),
]

# «다시 …해» 재요청형 — 교정이 아니므로 후보로 세지 않는다(일상 지시가 7일 경보를 채우는 것 방지)
RETRY_CASES = [
    "결과를 다시 출력해주세요",
    "현황을 다시 보고해주세요",
    "그 파일을 다시 확인해주세요",
]


def test_correction_detect():
    for label, prompt in CORRECTION_CASES:
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp)
            write_prompts(home, [prompt])
            run(["bash", str(SCRIPTS / "correction-detect.sh")], home)
            rows = cand_rows(home)
            ok = len(rows) == 1 and rows[0].split("\t")[1] == "T12"
            check(f"correction-detect: 정규식 {label} 검출", ok, str(rows))

    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        write_prompts(home, ["학습 상태를 알려주세요", "결과 표로 정리해 주세요"])
        r = run(["bash", str(SCRIPTS / "correction-detect.sh")], home)
        check("correction-detect: 비교정 발화 무시", cand_rows(home) == [], str(cand_rows(home)))
        check("correction-detect: 0건이면 무출력", r.stdout.strip() == "", r.stdout)

    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        write_prompts(home, RETRY_CASES)
        run(["bash", str(SCRIPTS / "correction-detect.sh")], home)
        check("correction-detect: «다시 …해» 재요청형 제외", cand_rows(home) == [], str(cand_rows(home)))

    n_cases = len(CORRECTION_CASES)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        write_prompts(home, [p for _, p in CORRECTION_CASES])
        r1 = run(["bash", str(SCRIPTS / "correction-detect.sh")], home)
        n1 = len(cand_rows(home))
        check(f"correction-detect: {n_cases}종 동시 기록", n1 == n_cases, str(n1))
        check("correction-detect: 건수 1줄 출력", f"{n_cases}건" in r1.stdout, r1.stdout.strip())
        run(["bash", str(SCRIPTS / "correction-detect.sh")], home)
        check("correction-detect: 재실행 중복 없음", len(cand_rows(home)) == n_cases,
              str(len(cand_rows(home))))
        check("correction-detect: exit 0", r1.returncode == 0, str(r1.returncode))

    with tempfile.TemporaryDirectory() as tmp:  # 로그 부재에서도 죽지 않는다(세션 시작 차단 금지)
        home = make_home(tmp)
        r = run(["bash", str(SCRIPTS / "correction-detect.sh")], home)
        check("correction-detect: 로그 없어도 exit 0", r.returncode == 0, r.stderr[:120])


# ── 2b) prompt-log.sh : 보관 길이 2000자 + 비인간 프롬프트 skip (2026-09-14 재감사 §3)
def prompt_rows(home):
    f = home / ".claude/_evolve/prompts.jsonl"
    if not f.exists():
        return []
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln]


def test_prompt_log():
    script = str(SCRIPTS / "prompt-log.sh")
    skips = ["<task-notification>x</task-notification>",
             "<teammate-message>x</teammate-message>",
             "<cross-session-message from=\"peer\">x</cross-session-message>",
             "<local-command-stdout>x</local-command-stdout>",
             "[SYSTEM NOTIFICATION] 백그라운드 잡 완료"]
    for p in skips:
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp)
            r = run_hook(["bash", script], home, {"prompt": p})
            check(f"prompt-log: skip «{p[:22]}»", prompt_rows(home) == [], str(prompt_rows(home)))
            check("prompt-log: skip 시 exit 0", r.returncode == 0, str(r.returncode))

    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        # 2,500자 — 200자 시절엔 뒤쪽 문장이 통째로 잘려 APPROVED 인용 검사·T12 탐지가 못 봤다.
        long_prompt = "가" * 2400 + " 앞으로는 이렇게 하지 마세요"
        run_hook(["bash", script], home, {"prompt": long_prompt})
        rows = prompt_rows(home)
        check("prompt-log: 1줄 기록", len(rows) == 1, str(len(rows)))
        if rows:
            check("prompt-log: 2000자 보관", len(rows[0]["prompt"]) == 2000, str(len(rows[0]["prompt"])))
            check("prompt-log: 200자 뒤 문장도 남음", "가" * 2000 == rows[0]["prompt"], "")

    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        # 긴 프롬프트라도 pattern-detect 의 빈도 키는 앞 200자 — 꼬리만 다른 3건이 한 묶음이어야 한다.
        base = "토큰 사용량 점검" + "가" * 300
        write_prompts(home, [base + " 꼬리" + t for t in ("가", "나", "다", "라")])
        r = run(["bash", str(SCRIPTS / "pattern-detect.sh"), "3"], home)
        check("pattern-detect: 빈도 키는 앞 200자(꼬리 차이 무시)", "×4" in "".join(cand_rows(home)),
              f"{r.stdout[:80]} / {cand_rows(home)}")


# ── 3) agent-spawn-log.sh : post 실패 신호 → t41-append 호출
def spawn_case(home, phase, stype, response):
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": stype, "description": "d"},
               "tool_response": response}
    return run_hook(["bash", str(SCRIPTS / "agent-spawn-log.sh"), phase], home, payload)


def history_t41(home):
    return [ln for ln in (home / ".claude/_audit/history.md").read_text(encoding="utf-8").splitlines()
            if "T41:" in ln]


def test_spawn_log():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        r = spawn_case(home, "post", "coder", "RESULT: FAIL 검증 3건 불일치")
        t41 = history_t41(home)
        check("spawn-log: post FAIL → T41 기록", len(t41) == 1 and "coder/결과 실패" in t41[0], str(t41))
        check("spawn-log: exit 0 유지", r.returncode == 0, str(r.returncode))
        check("spawn-log: 소집 로그도 남음",
              (home / ".claude/_audit/agent-spawn.log").exists(), "")

    with tempfile.TemporaryDirectory() as tmp:  # 객체 응답도 문자열화해 본다
        home = make_home(tmp)
        spawn_case(home, "post", "coder", {"content": [{"text": "BLOCKED 권한 부족"}]})
        check("spawn-log: 객체 응답 BLOCKED 검출", len(history_t41(home)) == 1, str(history_t41(home)))

    with tempfile.TemporaryDirectory() as tmp:  # general-purpose 는 agents/ 파일이 없다 → 허용 목록 확장분
        home = make_home(tmp)
        spawn_case(home, "post", "general-purpose", "NEEDS_CONTEXT 입력 부족")
        t41 = history_t41(home)
        check("spawn-log: general-purpose 도 기록",
              len(t41) == 1 and "general-purpose/범위 준수" in t41[0], str(t41))

    with tempfile.TemporaryDirectory() as tmp:  # 성공 소집엔 아무것도 하지 않는다
        home = make_home(tmp)
        spawn_case(home, "post", "coder", "요청대로 3개 파일을 수정했습니다. 검증 통과")
        check("spawn-log: 성공 소집 무기록", history_t41(home) == [], str(history_t41(home)))

    with tempfile.TemporaryDirectory() as tmp:  # pre 단계는 결과가 없다 → 기록 금지
        home = make_home(tmp)
        spawn_case(home, "pre", "coder", "FAIL")
        check("spawn-log: pre 단계 무기록", history_t41(home) == [], str(history_t41(home)))

    # 오탐 2건 회귀 (2026-09-14 실사고) — 비동기 즉시 응답·느슨한 한국어 단어
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        spawn_case(home, "post", "qa",
                   "Async agent launched successfully.\nagentId: abc123\n프롬프트 원문: "
                   "판정이 RESULT: FAIL 이면 사유를 적어라\nBLOCKED 면 블로커를 적어라")
        check("spawn-log: 비동기 소집 즉시 응답은 무기록", history_t41(home) == [], str(history_t41(home)))

    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        spawn_case(home, "post", "coder", "테스트 55건 통과, 실패 스위트: 0, 반려 없음")
        check("spawn-log: 성공 문장 속 «실패» 무기록", history_t41(home) == [], str(history_t41(home)))

    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        spawn_case(home, "post", "coder", "문장 가운데의 RESULT: FAIL 언급은 신호가 아니다")
        check("spawn-log: 행 중간 RESULT: FAIL 무기록", history_t41(home) == [], str(history_t41(home)))

    # 2026-10-01 P6 검수: t41-subagent-stop.sh 와 같은 판정 — 행두 «FAIL 0건»·RESULT: DONE 보고는 신호가 아니다(수정 전에는 둘 다 T41 로 기록)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        spawn_case(home, "post", "coder", "검증 결과\nFAIL 0건\nRESULT: DONE")
        check("spawn-log: 행두 «FAIL 0건» + RESULT: DONE 무기록", history_t41(home) == [], str(history_t41(home)))

    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        spawn_case(home, "post", "coder", "시험\nFAIL 0건 통과")
        check("spawn-log: RESULT 줄 없이도 «FAIL 0건» 무기록", history_t41(home) == [], str(history_t41(home)))

    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        spawn_case(home, "post", "coder", "요약 3줄\nRESULT: FAIL 계획 대비 2건 누락\n끝")
        t41 = history_t41(home)
        check("spawn-log: 행 앞 고정 RESULT: FAIL 기록",
              len(t41) == 1 and "coder/결과 실패" in t41[0], str(t41))


# ── 3b) t41-subagent-stop.sh : 비동기 소집의 진짜 결과(마지막 assistant 메시지)로 판정
def write_transcript(path, texts):
    lines = []
    for t in texts:
        lines.append(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}))
        lines.append(json.dumps({"type": "assistant",
                                 "message": {"role": "assistant",
                                             "content": [{"type": "text", "text": t}]}},
                                ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_subagent_stop():
    script = str(SCRIPTS / "t41-subagent-stop.sh")

    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        tp = Path(tmp) / "agent.jsonl"
        write_transcript(tp, ["중간 경과입니다", "요약 3줄\nRESULT: FAIL 근거 파일 부재\n끝"])
        r = run_hook(["bash", script], home,
                     {"hook_event_name": "SubagentStop", "subagent_type": "coder",
                      "agent_transcript_path": str(tp)})
        t41 = history_t41(home)
        check("subagent-stop: 마지막 답의 RESULT: FAIL 기록",
              len(t41) == 1 and "coder/결과 실패" in t41[0], str(t41))
        check("subagent-stop: exit 0", r.returncode == 0, r.stderr[:120])

    with tempfile.TemporaryDirectory() as tmp:  # agent_transcript_path 부재 → transcript_path 폴백
        home = make_home(tmp)
        (home / ".claude/agents/qa.md").write_text("# qa\n", encoding="utf-8")
        tp = Path(tmp) / "session.jsonl"
        write_transcript(tp, ["STATUS: BLOCKED 권한 부족"])
        run_hook(["bash", script], home,
                 {"hook_event_name": "SubagentStop", "subagent_type": "qa",
                  "transcript_path": str(tp)})
        t41 = history_t41(home)
        check("subagent-stop: transcript_path 폴백",
              len(t41) == 1 and "qa/범위 준수" in t41[0], str(t41))

    with tempfile.TemporaryDirectory() as tmp:  # 성공 답은 무기록
        home = make_home(tmp)
        tp = Path(tmp) / "agent.jsonl"
        write_transcript(tp, ["RESULT: FAIL 였던 중간 상태", "수정 완료, 실패 스위트: 0"])
        run_hook(["bash", script], home,
                 {"hook_event_name": "SubagentStop", "subagent_type": "coder",
                  "agent_transcript_path": str(tp)})
        check("subagent-stop: 마지막 답이 성공이면 무기록", history_t41(home) == [], str(history_t41(home)))

    with tempfile.TemporaryDirectory() as tmp:  # 경로가 없어도 세션을 막지 않는다
        home = make_home(tmp)
        r = run_hook(["bash", script], home,
                     {"hook_event_name": "SubagentStop", "transcript_path": "/nope/x.jsonl"})
        check("subagent-stop: 경로 부재에도 exit 0", r.returncode == 0, r.stderr[:120])
        check("subagent-stop: 경로 부재면 무기록", history_t41(home) == [], str(history_t41(home)))


# ── 3c) t41-append.sh : history + 후보 대장 동시 기록, 요약 중복 차단
def test_t41_append():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        args = ["bash", str(SCRIPTS / "t41-append.sh"), "coder", "구현 정확성",
                "RESULT: FAIL 계획 대비 2건 누락"]
        r = run(args, home)
        rows = cand_rows(home)
        check("t41-append: rc 0", r.returncode == 0, r.stderr[:160])
        check("t41-append: history 1줄", len(history_t41(home)) == 1, str(history_t41(home)))
        check("t41-append: 후보 1행", len(rows) == 1, str(rows))
        if rows:
            f = rows[0].split("\t")
            check("t41-append: 스키마 7열(note 열 2026-10-17)", len(f) == 7, str(f))
            check("t41-append: source=T41", f[1] == "T41", str(f))
            check("t41-append: status=pending", f[4] == "pending", str(f))
            check("t41-append: bench_id=-", f[3] == "-", str(f))
            check("t41-append: id 형식", f[0].startswith("T41-") and len(f[0]) == 15, f[0])
            check("t41-append: 요약 role/dim 접두", f[5].startswith("coder/구현 정확성: "), f[5])
        run(args, home)
        check("t41-append: 같은 요약 중복 없음", len(cand_rows(home)) == 1, str(cand_rows(home)))
        run(["bash", str(SCRIPTS / "t41-append.sh"), "coder", "범위 준수", "BLOCKED 권한 부족"], home)
        check("t41-append: 다른 신호는 새 행", len(cand_rows(home)) == 2, str(cand_rows(home)))


# ── 3d) t41-append.sh 자동 모드: 역할 귀속 매핑 + 10분 이중 기록 억제 (2026-09-14 재감사 §3)
def test_t41_auto_mode():
    cases = [
        # (신호를 낸 subagent_type, 신호, 기대 축) — agent-eval §1 신호표 그대로.
        ("qa", "RESULT: FAIL 검증 2건 불일치", "coder/구현 정확성"),      # 검증자 FAIL → 만든 쪽
        ("reviewer", "판정: REJECT 설계와 불일치", "coder/구현 정확성"),
        ("scout", "BLOCKED 대상 경로 없음", "scout/범위 준수"),           # 막힌 건 맡은 쪽 문제
        ("qa", "NEEDS_CONTEXT 입력 부족", "qa/범위 준수"),
        ("coder", "RESULT: FAIL 계획 대비 2건 누락", "coder/결과 실패"),  # 그 밖은 자기 자신
    ]
    for stype, signal, axis in cases:
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp)
            for extra in ("qa", "reviewer", "scout"):
                (home / f".claude/agents/{extra}.md").write_text(f"# {extra}\n", encoding="utf-8")
            r = run(["bash", str(SCRIPTS / "t41-append.sh"), "--from", stype, "--signal", signal], home)
            t41 = history_t41(home)
            check(f"t41-auto: {stype} «{signal[:12]}» → {axis}",
                  len(t41) == 1 and axis in t41[0], f"{t41} rc={r.returncode} {r.stderr[:120]}")

    with tempfile.TemporaryDirectory() as tmp:  # 인자 형식이 틀리면 조용히 넘어가지 않는다
        home = make_home(tmp)
        r = run(["bash", str(SCRIPTS / "t41-append.sh"), "--from", "coder"], home)
        check("t41-auto: 인자 부족 거부", r.returncode == 2, str(r.returncode))

    with tempfile.TemporaryDirectory() as tmp:  # 동기 소집은 두 훅이 같은 결과를 본다 → 10분 억제
        home = make_home(tmp)
        args = ["bash", str(SCRIPTS / "t41-append.sh"), "--from", "coder",
                "--signal", "RESULT: FAIL 같은 신호"]
        run(args, home)
        run(args, home)
        check("t41-auto: 10분 안 같은 신호는 history 1줄", len(history_t41(home)) == 1,
              str(history_t41(home)))
        # 억제 장부의 시각을 11분 전으로 되돌리면 다시 기록돼야 한다 — 영구 차단이 아니라 창 기반이다.
        recent = home / ".claude/_usage/t41-recent.tsv"
        old = "\n".join(f"{int(ln.split(chr(9))[0]) - 660}\t{ln.split(chr(9))[1]}"
                        for ln in recent.read_text(encoding="utf-8").splitlines() if ln)
        recent.write_text(old + "\n", encoding="utf-8")
        run(args, home)
        check("t41-auto: 10분 밖이면 다시 기록", len(history_t41(home)) == 2, str(history_t41(home)))

    # 같은 신호 10병렬 — 잠금 없던 판은 «읽고 비우고 다시 쓰기» 가 엇갈려 history 3~4줄을 남겼다
    # (2026-09-14 재감사 D0). 판정·기록이 한 임계구역이면 1줄이 합격선이다.
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        env = dict(os.environ, HOME=str(home))
        procs = [subprocess.Popen(["bash", str(SCRIPTS / "t41-append.sh"), "--from", "coder",
                                   "--signal", "RESULT: FAIL 동시 같은 신호"],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(10)]
        for p in procs:
            p.communicate()
        check("t41-auto: 같은 신호 10병렬 → history 1줄", len(history_t41(home)) == 1,
              str(history_t41(home)))
        check("t41-auto: 10병렬 전원 rc 0", all(p.returncode == 0 for p in procs),
              str([p.returncode for p in procs]))
        check("t41-auto: 10병렬 후보 대장 1행", len(cand_rows(home)) == 1, str(cand_rows(home)))


# ── 4) oversight-append.sh : 6열·어휘 검증
def ov_rows(home):
    f = home / ".claude/_audit/oversight.tsv"
    return f.read_text(encoding="utf-8").splitlines() if f.exists() else []


def test_oversight_append():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        work = Path(tmp) / "notarepo"
        work.mkdir()
        r = run(["bash", str(SCRIPTS / "oversight-append.sh"), "commit", "abc1234 fix: x",
                 "사용자 지시 «커밋해»"], home, cwd=str(work))
        rows = ov_rows(home)
        check("oversight-append: 1행 append", len(rows) == 1, str(rows))
        if rows:
            f = rows[0].split("\t")
            check("oversight-append: 6열", len(f) == 6, str(f))
            check("oversight-append: 게이트 열", f[2] == "commit", str(f))
            check("oversight-append: 주체 기본 main", f[5] == "main", str(f))
            # 저장소 밖 cwd 는 harness 가 아니라 none (2026-10-01 감사 P6)
            check("oversight-append: 저장소 밖 cwd 는 none", f[1] == "none", str(f))
            check("oversight-append: 일시 형식", len(f[0]) == 16 and f[0][4] == "-", f[0])
        check("oversight-append: rc 0", r.returncode == 0, r.stderr[:120])

        r2 = run(["bash", str(SCRIPTS / "oversight-append.sh"), "finding", "x", "y"], home, cwd=str(work))
        check("oversight-append: 어휘 밖 게이트 거부", r2.returncode == 2, str(r2.returncode))
        check("oversight-append: 거부 시 무기록", len(ov_rows(home)) == 1, str(ov_rows(home)))

        r3 = run(["bash", str(SCRIPTS / "oversight-append.sh"), "launch", "a\tb", "c\nd", "qa"],
                 home, cwd=str(work))
        last = ov_rows(home)[-1].split("\t")
        check("oversight-append: 탭·개행 살균", len(last) == 6 and last[3] == "a b", str(last))
        check("oversight-append: 주체 인자 반영", last[5] == "qa", str(last))
        check("oversight-append: rc 0(살균 케이스)", r3.returncode == 0, r3.stderr[:120])

        r4 = run(["bash", str(SCRIPTS / "oversight-append.sh"), "commit"], home, cwd=str(work))
        check("oversight-append: 인자 부족 거부", r4.returncode == 2, str(r4.returncode))

        repo = Path(tmp) / "proj"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(repo), capture_output=True, check=False)
        run(["bash", str(SCRIPTS / "oversight-append.sh"), "publish", "페이지 1", "근거"],
            home, cwd=str(repo))
        check("oversight-append: 저장소 이름 기록", ov_rows(home)[-1].split("\t")[1] == "proj",
              ov_rows(home)[-1])

        # 하네스 저장소($HOME/.claude 의 실경로) 안에서는 harness
        subprocess.run(["git", "init", "-q"], cwd=str(home / ".claude"), capture_output=True, check=False)
        run(["bash", str(SCRIPTS / "oversight-append.sh"), "audit", "하네스 점검", "근거"],
            home, cwd=str(home / ".claude"))
        check("oversight-append: 하네스 안은 harness", ov_rows(home)[-1].split("\t")[1] == "harness",
              ov_rows(home)[-1])


# ── 5) harness-usage-check.sh : 경보 6종 발화·비발화
def usage_out(home):
    return run(["bash", str(SCRIPTS / "harness-usage-check.sh")], home).stdout


def days_ago(n):
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - n * 86400))


def test_usage_check():
    # ① CANDIDATES_MISSING / ② CANDIDATES_EMPTY / CANDIDATES_PENDING
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        out = usage_out(home)
        check("usage: CANDIDATES_MISSING 발화", "CANDIDATES_MISSING" in out, out)

        cand = home / ".claude/_evolve/candidates.tsv"
        cand.write_text(CANDIDATE_HEADER, encoding="utf-8")
        out = usage_out(home)
        check("usage: 빈 대장 → CANDIDATES_EMPTY", "CANDIDATES_EMPTY" in out, out)
        check("usage: 빈 대장이면 MISSING 아님", "CANDIDATES_MISSING" not in out, out)

        cand.write_text(CANDIDATE_HEADER
                        # note(7열) 가 있는 행은 SessionStart 자동 만료(2026-10-17)에서 제외된다 — 7일 초과 집계를 시험하려면 note 가 필요하다
                        + f"T40-x-01\tT40\t{days_ago(9)}\t-\tpending\t오래된 후보\t검토중\n"
                        + f"T12-x-01\tT12\t{days_ago(1)}\t-\tpending\t새 후보\n"
                        + f"T40-x-02\tT40\t{days_ago(30)}\t-\tdone\t처리된 후보\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: CANDIDATES_PENDING 건수",
              "CANDIDATES_PENDING: 2건(신규 2 · 벤치 대기 0 · 승인 대기 0 · 7일 초과 1건 · T12 1·T40 1·T41 0)" in out, out)
        check("usage: 채워진 대장이면 EMPTY 아님", "CANDIDATES_EMPTY" not in out, out)

        # 미결 어휘 3종을 모두 센다 (재감사 B2) — 스킬이 상태를 올리면 사라지던 회귀.
        cand.write_text(CANDIDATE_HEADER
                        + f"T40-x-01\tT40\t{days_ago(9)}\t-\tpending\t신규\t검토중\n"
                        + f"T12-x-01\tT12\t{days_ago(9)}\tb1\tpending-bench\t벤치 대기\n"
                        + f"T41-x-01\tT41\t{days_ago(1)}\tb2\tpending-approval\t승인 대기\n"
                        + f"T40-x-02\tT40\t{days_ago(9)}\t-\taccepted\t채택됨\n"
                        + f"T40-x-03\tT40\t{days_ago(9)}\t-\trejected\t기각됨\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: 미결 3종 합산·내역 표시",
              "CANDIDATES_PENDING: 3건(신규 1 · 벤치 대기 1 · 승인 대기 1 · 7일 초과 2건 · T12 1·T40 1·T41 1)" in out, out)
        check("usage: accepted·rejected 는 미결 아님", "5건(" not in out, out)

    # ③ T41_SILENT
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        today = time.strftime("%Y-%m-%dT%H:%M:%S+09:00")
        log = "".join(f"{today}\tpost\tcoder\t-\tsonnet\td\n" for _ in range(30))
        (home / ".claude/_audit/agent-spawn.log").write_text(log, encoding="utf-8")
        out = usage_out(home)
        check("usage: T41_SILENT 발화", "T41_SILENT" in out, out)

        (home / ".claude/_audit/history.md").write_text(
            f"# history\n- {days_ago(1)} T41: coder/구현 정확성 — FAIL 신호\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: T41 기록 있으면 비발화", "T41_SILENT" not in out, out)

        (home / ".claude/_audit/history.md").write_text(
            f"# history\n- {days_ago(20)} T41: coder/구현 정확성 — 옛 기록\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: 7일 밖 T41 은 무효", "T41_SILENT" in out, out)

        (home / ".claude/_audit/agent-spawn.log").write_text(
            "".join(f"{today}\tpost\tcoder\t-\tsonnet\td\n" for _ in range(5)), encoding="utf-8")
        (home / ".claude/_audit/history.md").write_text("# history\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: 소집 30건 미만이면 비발화", "T41_SILENT" not in out, out)

    # ③b T41_REPEAT — 같은 role/dim 3회+ (최근 30일 창)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        hist = home / ".claude/_audit/history.md"
        two = "".join(f"- {days_ago(i)} T41: coder/구현 정확성 — RESULT: FAIL\n" for i in (1, 2))
        hist.write_text("# history\n" + two, encoding="utf-8")
        out = usage_out(home)
        check("usage: T41 2회면 REPEAT 비발화", "T41_REPEAT" not in out, out)

        hist.write_text("# history\n" + two
                        + f"- {days_ago(3)} T41: coder/구현 정확성 — RESULT: FAIL\n"
                        + f"- {days_ago(1)} T41: qa/범위 준수 — BLOCKED\n", encoding="utf-8")
        out = usage_out(home)
        # 축 이름에 공백이 있어도 통째로 나와야 한다 — «coder/구현» 으로 잘리면 축이 갈라진다.
        check("usage: T41 3회면 REPEAT 발화", "T41_REPEAT: coder/구현 정확성 ×3" in out, out)
        check("usage: 3회 미만 축은 목록 제외", "qa/범위 준수" not in out, out)

        hist.write_text("# history\n" + "".join(
            f"- {days_ago(40 + i)} T41: coder/구현 정확성 — RESULT: FAIL\n" for i in range(3)),
            encoding="utf-8")
        out = usage_out(home)
        check("usage: 30일 창 밖 3회는 비발화", "T41_REPEAT" not in out, out)

    # ④ BENCH_PENDING
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        claude = home / ".claude"
        subprocess.run(["git", "init", "-q"], cwd=str(claude), capture_output=True, check=False)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(claude), capture_output=True, check=False)
        subprocess.run(["git", "config", "user.name", "t"], cwd=str(claude), capture_output=True, check=False)
        (claude / "rules").mkdir(exist_ok=True)
        (claude / "rules" / "x.md").write_text("a\n", encoding="utf-8")
        old = f"{days_ago(20)}T10:00:00"
        env = dict(os.environ, GIT_AUTHOR_DATE=old, GIT_COMMITTER_DATE=old)
        subprocess.run(["git", "add", "rules/x.md"], cwd=str(claude), capture_output=True, check=False)
        subprocess.run(["git", "commit", "-q", "-m", "rule"], cwd=str(claude), capture_output=True, env=env, check=False)

        bench = claude / "_usage/bench-last"
        bench.touch()
        old_ts = time.time() - 40 * 86400
        os.utime(bench, (old_ts, old_ts))
        out = usage_out(home)
        check("usage: BENCH_PENDING 발화(규칙 변경 20일 경과)", "BENCH_PENDING" in out, out)

        os.utime(bench, None)  # bench 를 방금 돌린 상태 → 이후 규칙 변경 없음
        out = usage_out(home)
        check("usage: 최신 bench 면 비발화", "BENCH_PENDING" not in out, out)

    # ⑤ AUDIT_STALE
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        (home / ".claude/_audit/history.md").write_text(
            f"# history\n\n### {days_ago(40)} 감사\n본문\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: AUDIT_STALE 발화(40일)", "AUDIT_STALE" in out, out)

        (home / ".claude/_audit/history.md").write_text(
            f"# history\n\n### {days_ago(2)} 감사\n본문\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: 최근 ### 절이면 비발화", "AUDIT_STALE" not in out and "AUDIT_NEVER" not in out, out)

        # 감사가 아닌 날짜 절(수리·다이어트)은 감사 시계를 되돌리지 않는다 (재감사 §3).
        (home / ".claude/_audit/history.md").write_text(
            f"# history\n\n### {days_ago(40)} 자기개선 루프 감사\n본문\n"
            f"\n### {days_ago(1)} 자기개선 루프 일괄 수리\n본문\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: 비감사 절은 감사 시계 갱신 안 함", "AUDIT_STALE" in out, out)

        (home / ".claude/_audit/history.md").write_text(
            f"# history\n\n### {days_ago(40)} 루프 감사\n본문\n"
            f"\n### {days_ago(3)} 전수 점검\n본문\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: «점검» 절은 감사로 인정", "AUDIT_STALE" not in out, out)

    # ⑥ OVERSIGHT_FORMAT
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        ov = home / ".claude/_audit/oversight.tsv"
        ov.write_text("2026-09-14 10:00\tharness\tcommit\t대상\t근거\tmain\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: 정상 원장이면 비발화", "OVERSIGHT_FORMAT" not in out, out)

        ov.write_text("2026-09-14 10:00\tharness\tcommit\t대상\t근거\tmain\n"
                      "2026-09-14 11:00\tharness\tcommit\t대상\t근거\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: 5열 행 → 열 수 경보 + 행 번호", "OVERSIGHT_FORMAT(열 수 1행)" in out and "행 2" in out, out)

        ov.write_text("2026-09-14 10:00\tharness\tcommit\t대상\t근거\tmain\n"
                      "2026-09-14 11:00\tharness\tfinding\t대상\t근거\tmain\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: 어휘 밖 게이트 경보", "OVERSIGHT_FORMAT(게이트 어휘 1행)" in out and "행 2" in out, out)

        ov.write_text("2026-09-13 09:00\tharness\tgit-commit\t대상\t근거\tmain\n"
                      "2026-09-14 12:00\tharness\tcommit\t대상\t근거\tmain\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: 2026-09-13 행의 구 어휘는 비발화", "OVERSIGHT_FORMAT" not in out, out)

        ov.write_text("2026-09-13 09:00\tharness\tgit-commit\t대상\t근거\tmain\n"
                      "2026-09-14 12:00\tharness\tfinding\t대상\t근거\tmain\n", encoding="utf-8")
        out = usage_out(home)
        check("usage: 2026-09-14 이후 행의 어휘 밖 게이트는 발화",
              "OVERSIGHT_FORMAT(게이트 어휘 1행)" in out and "행 2" in out, out)


# ── 6) oversight-fix-5col.py : dry-run 은 파일을 바꾸지 않는다
def test_fix_5col():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        ov = home / ".claude/_audit/oversight.tsv"
        body = ("a\tb\tcommit\td\te\tmain\n" "a\tb\tcommit\td\te\n")
        ov.write_text(body, encoding="utf-8")
        r = run(["python3", str(SCRIPTS / "oversight-fix-5col.py")], home)
        check("fix-5col: dry-run 대상 행 보고", "대상 1행: [2]" in r.stdout, r.stdout)
        check("fix-5col: dry-run 무변경", ov.read_text(encoding="utf-8") == body, ov.read_text(encoding="utf-8"))
        r2 = run(["python3", str(SCRIPTS / "oversight-fix-5col.py"), "--apply"], home)
        rows = ov.read_text(encoding="utf-8").splitlines()
        check("fix-5col: --apply 6열화", all(len(x.split("\t")) == 6 for x in rows), str(rows))
        check("fix-5col: 채운 값 main", rows[1].endswith("\tmain"), rows[1])
        check("fix-5col: 다른 행 불변", rows[0] == "a\tb\tcommit\td\te\tmain", rows[0])
        check("fix-5col: rc 0", r2.returncode == 0, r2.stderr[:120])


# ── 7) 2026-10-01 감사 P6 수정분 (기대값은 지적된 사고·규칙 문면에서 만들었다)
def test_p6_correction_detect():
    # grep 3.7 의 `.` 가 U+D558 이상 글자(«확»·«한»)를 못 맞혀 아래 두 교정이 0건이었다(실측)
    for p in ("왜 확인 안 했어", "다시 한번 제대로 해"):
        with tempfile.TemporaryDirectory() as tmp:
            home = make_home(tmp)
            write_prompts(home, [p])
            run(["bash", str(SCRIPTS / "correction-detect.sh")], home)
            rows = cand_rows(home)
            check(f"p6 correction-detect: «{p}» 검출",
                  len(rows) == 1 and rows[0].split("\t")[1] == "T12", str(rows))


def test_p6_candidates_transitions():
    helper = str(SCRIPTS / "candidates-append.sh")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        cand = home / ".claude/_evolve/candidates.tsv"
        body = (CANDIDATE_HEADER
                + f"T40-x-01\tT40\t{days_ago(9)}\t-\tpending\t오래된 신규\n"
                + f"T12-x-01\tT12\t{days_ago(1)}\t-\tpending\t새 후보\n"
                + f"T40-x-02\tT40\t{days_ago(30)}\tb1\tpending-bench\t벤치 중\n"
                + f"T41-x-01\tT41\t{days_ago(20)}\t-\taccepted\t채택됨\n")
        cand.write_text(body, encoding="utf-8")
        r = run(["bash", helper, "expire", "--older-than-days", "7", "--dry-run"], home)
        check("p6 expire --dry-run: 건수·id 보고, 파일 무변경",
              r.returncode == 0 and "1건" in r.stdout and "T40-x-01" in r.stdout
              and cand.read_text(encoding="utf-8") == body, f"{r.returncode} {r.stdout} {r.stderr[:100]}")
        r = run(["bash", helper, "expire", "--older-than-days", "7"], home)
        st = {x.split("\t")[0]: x.split("\t")[4] for x in cand_rows(home)}
        check("p6 expire: pending 이면서 7일 초과만 expired",
              st == {"T40-x-01": "expired", "T12-x-01": "pending", "T40-x-02": "pending-bench",
                     "T41-x-01": "accepted"} and "1건" in r.stdout, f"{st} {r.stdout}")
        check("p6 expire: 6열 유지·행 수 불변",
              all(len(x.split("\t")) == 6 for x in cand_rows(home)) and len(cand_rows(home)) == 4, "")
        out = usage_out(home)
        check("p6 expire: expired 는 미결 집계에서 빠짐",
              "CANDIDATES_PENDING: 2건(신규 1 · 벤치 대기 1 · 승인 대기 0 · 7일 초과 1건 · T12 1·T40 1·T41 0)" in out, out)
        r = run(["bash", helper, "T40", "오래된 신규"], home)
        rows_now = [x.split("\t") for x in cand_rows(home)]
        same = [x for x in rows_now if x[5] == "오래된 신규"]
        check("p6 expire: 방금 만료된 요약(생성 9일 전)은 37일 이내라 되살아나지 않음(rc 3·무기록)",
              r.returncode == 3 and len(same) == 1 and same[0][4] == "expired", f"{r.returncode} {same}")
        r = run(["bash", helper, "set", "T12-x-01", "rejected"], home)
        st = {x.split("\t")[0]: x.split("\t")[4] for x in cand_rows(home)}
        check("p6 set: 상태 전이", r.returncode == 0 and st["T12-x-01"] == "rejected", f"{r.returncode} {st}")
        check("p6 set: 없는 id rc 1", run(["bash", helper, "set", "nope", "rejected"], home).returncode == 1, "")
        check("p6 set: 어휘 밖 status rc 1", run(["bash", helper, "set", "T12-x-01", "weird"], home).returncode == 1, "")
        check("p6 expire: 일수 누락 rc 1", run(["bash", helper, "expire"], home).returncode == 1, "")

    with tempfile.TemporaryDirectory() as tmp:  # T40 횟수는 중복 키에서 제외
        home = make_home(tmp)
        run(["bash", helper, "T40", "토큰 점검 ×3"], home)
        r = run(["bash", helper, "T40", "토큰 점검 ×5"], home)
        check("p6 T40 횟수 키: 횟수만 다른 요약은 중복(rc 3)", r.returncode == 3 and len(cand_rows(home)) == 1,
              f"{r.returncode} {cand_rows(home)}")
        r = run(["bash", helper, "T40", "토큰 구경 ×5"], home)
        check("p6 T40 횟수 키: 다른 패턴은 새 행", r.returncode == 0 and len(cand_rows(home)) == 2, str(cand_rows(home)))


def test_p6_pattern_detect():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        write_prompts(home, ["해결 방법 정리해줘 진행"] * 3)
        r = run(["bash", str(SCRIPTS / "pattern-detect.sh"), "3"], home)
        check("p6 pattern-detect: 낱말 속 «해» 보존, 어미·단독 기능어만 제거",
              "해결 방법 정리" in r.stdout, r.stdout)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        write_prompts(home, ["토큰 사용량 점검"] * 3)
        run(["bash", str(SCRIPTS / "pattern-detect.sh"), "3"], home)
        write_prompts(home, ["토큰 사용량 점검"] * 5)
        run(["bash", str(SCRIPTS / "pattern-detect.sh"), "3"], home)
        check("p6 pattern-detect: 횟수가 바뀌어도 새 후보 없음", len(cand_rows(home)) == 1, str(cand_rows(home)))


def test_p6_usage_check():
    # ① 점검 스크립트가 색인을 바꾸지 않는다
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        cl = home / ".claude"
        g = lambda *a: subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=t",
                                       "-c", "user.email=t@t", *a], cwd=str(cl), capture_output=True, text=True, check=False)
        g("init", "-q")
        (cl / "settings.json").write_text('{"a": 1}\n', encoding="utf-8")
        g("add", "settings.json")
        g("commit", "-q", "-m", "init")
        (cl / "settings.json").write_text('{"a": 2}\n', encoding="utf-8")
        usage_out(home)
        staged = g("diff", "--cached", "--name-only").stdout.strip()
        check("p6 usage: git add 로 색인을 바꾸지 않음", staged == "", staged)

    # ② 타이머 활성인데 로그 부재 → 경보 (가짜 systemctl 로 «활성» 재현)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        fake = Path(tmp) / "fakebin"
        fake.mkdir()
        (fake / "systemctl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fake / "systemctl").chmod(0o755)
        env = dict(os.environ, HOME=str(home), PATH=f"{fake}:{os.environ['PATH']}")
        out = subprocess.run(["bash", str(SCRIPTS / "harness-usage-check.sh")], capture_output=True,
                             text=True, env=env, cwd=str(SCRIPTS.parent), check=False).stdout
        check("p6 usage: 타이머 활성·로그 부재 → TIMER_SILENT(로그 부재)", "TIMER_SILENT(로그 부재)" in out, out)

    # ③ 구 행(2026-09-14 이전)은 열 수 검사도 제외 (oversight-signature.md)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        (home / ".claude/_audit/oversight.tsv").write_text(
            "2026-09-13 09:00\tharness\tcommit\t대상\t근거\n", encoding="utf-8")
        out = usage_out(home)
        check("p6 usage: 구 행의 5열은 OVERSIGHT_FORMAT 비발화", "OVERSIGHT_FORMAT" not in out, out)

    # ④ 2026-10-01 P6 검수: «분석 정지» 별도 PATTERNS_UNMINED 분기는 CANDIDATES_PENDING 과 겹쳐 매 세션 둘 다 울렸다 — 경보는 CANDIDATES_PENDING 하나다
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        ev = home / ".claude/_evolve"
        (ev / "prompts.jsonl").write_text("{}\n" * 60, encoding="utf-8")
        (ev / "candidates.tsv").write_text(
            CANDIDATE_HEADER + f"T12-x-01\tT12\t{days_ago(1)}\t-\tpending\t새 후보\n", encoding="utf-8")
        (home / ".claude/_usage/pattern-detect-last").write_text("", encoding="utf-8")  # 훅은 방금 돌았다
        out = usage_out(home)
        check("p6 usage: 미결 후보는 CANDIDATES_PENDING 하나로만 울리고 PATTERNS_UNMINED 는 겹치지 않음",
              "CANDIDATES_PENDING" in out and "PATTERNS_UNMINED" not in out, out)


def test_p6_regression_judge_hold():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        (home / ".claude/_bench").mkdir()
        (home / ".claude/_bench/.experiment_active").write_text("", encoding="utf-8")
        rub = Path(tmp) / "rubric.md"
        rub.write_text("규칙", encoding="utf-8")
        rs = Path(tmp) / "ruleset"
        rs.mkdir()
        r = run(["bash", str(SCRIPTS / "regression-judge.sh"), str(rub), str(rs)], home)
        check("p6 regression-judge: 실험 활성 보류는 PASS(0)가 아닌 전용 코드 3",
              r.returncode == 3 and "보류" in r.stdout, f"{r.returncode} {r.stdout}")


def test_post_commit_failure_paths():
    """ci-gate-post-commit.sh 의 실패 경로(2026-10-17 Grok 7차): set·attach-commit 의 exit 5 는 큐로, diff-tree 실패는 큐 없이 별도 경고."""
    stub = ('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$HOME/.claude/_usage/stub-calls"\n'
            'case "$1" in set|attach-commit) exit "${STUB_RC:-5}";; esac\nexit 0\n')
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        claude = home / ".claude"
        for d in ("_evolve", "_usage", "scripts"):
            (claude / d).mkdir(parents=True)
        shutil.copy(SCRIPTS / "ci-gate-post-commit.sh", claude / "scripts/ci-gate-post-commit.sh")
        (claude / "scripts/candidates-append.sh").write_text(stub, encoding="utf-8")
        (claude / "_evolve/candidates.tsv").write_text(
            CANDIDATE_HEADER + "P-1\tT41\t2026-10-10\t-\tpending\t미결 후보\nP-2\tT41\t2026-10-10\t-\taccepted\t선승인 후보\nP-3\tT41\t2026-10-10\t-\tpending\t목록 실패 후보\n", encoding="utf-8")
        repo = Path(tmp) / "repo"
        repo.mkdir()
        genv = dict(os.environ, HOME=str(home), GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")

        def git(*a, env=None):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=str(repo), capture_output=True, text=True, env=env or genv, check=True)

        def commit_with(cid, rel):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(cid, encoding="utf-8")
            git("add", "--", rel)
            git("commit", "-q", "-m", f"fix: Change\n\nCandidate: {cid}\n")
            return git("rev-parse", "--short", "HEAD").stdout.strip()

        git("init", "-q")
        hook = str(claude / "scripts/ci-gate-post-commit.sh")
        queue = claude / "_usage/candidates-attach-retry.tsv"
        calls = claude / "_usage/stub-calls"

        short1 = commit_with("P-1", "rules/a.md")
        r = subprocess.run(["bash", hook], cwd=str(repo), capture_output=True, text=True, env=genv, check=False)
        check("Grok7 4a: set 이 exit 5(저장 실패)면 재시도 큐에 id<TAB>해시·문구에 «대장 저장 실패»·«재시도 큐에 넣음»",
              queue.exists() and f"P-1\t{short1}" in queue.read_text(encoding="utf-8").splitlines() and "대장 저장 실패" in r.stderr and "재시도 큐에 넣음" in r.stderr and r.returncode == 0, f"{r.returncode} {r.stderr}")
        short2 = commit_with("P-2", "rules/b.md")
        r = subprocess.run(["bash", hook], cwd=str(repo), capture_output=True, text=True, env=genv, check=False)
        check("Grok7 4a: attach-commit 이 exit 5 여도 큐에 넣고 «대장 저장 실패» 로 구분",
              f"P-2\t{short2}" in queue.read_text(encoding="utf-8").splitlines() and "대장 저장 실패" in r.stderr and "재시도 큐에 넣음" in r.stderr, f"{queue.read_text(encoding='utf-8')!r} {r.stderr}")

        short3 = commit_with("P-3", "rules/c.md")
        n_calls = len(calls.read_text(encoding="utf-8").splitlines())
        shim = Path(tmp) / "shim"
        shim.mkdir()
        (shim / "git").write_text('#!/bin/bash\ncase " $* " in *" diff-tree "*) exit 128;; esac\nexec /usr/bin/git "$@"\n', encoding="utf-8")
        (shim / "git").chmod(0o755)
        r = subprocess.run(["bash", hook], cwd=str(repo), capture_output=True, text=True, env=dict(genv, PATH=f"{shim}:{os.environ['PATH']}"), check=False)
        check("Grok7 4b: diff-tree 실패 → «변경 파일 목록을 읽지 못함(diff-tree rc=128)» + 수동 안내(set <id> accepted --note commit=<해시>)",
              "변경 파일 목록을 읽지 못함(diff-tree rc=128)" in r.stderr and f"수동: bash scripts/candidates-append.sh set P-3 accepted --note commit={short3}" in r.stderr and r.returncode == 0, f"{r.returncode} {r.stderr}")
        check("Grok8 3a: diff-tree 실패 안내의 set 명령에 --machine 이 붙음(expired 에서도 전이되게)", f"commit={short3} --machine" in r.stderr, r.stderr)
        check("Grok7 4b: «변경 없음» 경고와 구분되고 validate 로 가지 않아 candidates-append 를 부르지 않으며 큐에도 넣지 않음",
              "연결 안 함" not in r.stderr and len(calls.read_text(encoding="utf-8").splitlines()) == n_calls and not any(ln.startswith("P-3\t") for ln in queue.read_text(encoding="utf-8").splitlines()),
              f"{r.stderr} {calls.read_text(encoding='utf-8')!r}")

        # Grok 8차 3a: set 이 큐에도 못 넣는 일반 실패(exit 1)일 때의 수동 안내에도 --machine
        with open(claude / "_evolve/candidates.tsv", "a", encoding="utf-8") as f_:
            f_.write("P-4\tT41\t2026-10-10\t-\tpending\t일반 실패 후보\n")
        short4 = commit_with("P-4", "rules/d.md")
        r = subprocess.run(["bash", hook], cwd=str(repo), capture_output=True, text=True, env=dict(genv, STUB_RC="1"), check=False)
        check("Grok8 3a: set 일반 실패의 수동 안내에도 --machine", f"수동: bash scripts/candidates-append.sh set P-4 accepted --note commit={short4} --machine" in r.stderr, r.stderr)

        # Grok 8차 3b: 이미 accepted 인데 거버넌스 파일 변경이 없으면 attach-commit 을 부르지 않고 이유를 알린다
        n_calls = len(calls.read_text(encoding="utf-8").splitlines())
        commit_with("P-2", "docs/only.md")
        r = subprocess.run(["bash", hook], cwd=str(repo), capture_output=True, text=True, env=genv, check=False)
        check("Grok8 3b: accepted + 문서만 변경 → «후보 P-2 는 accepted 이나 … commit= 을 붙이지 않음» 한 줄·attach-commit 미호출",
              "후보 P-2 는 accepted 이나 이 커밋은 거버넌스 파일 변경이 없어 commit= 을 붙이지 않음" in r.stderr and len(calls.read_text(encoding="utf-8").splitlines()) == n_calls, f"{r.stderr}")

        # Grok 8차 4: 대장이 있는데 읽을 수 없으면 «대장에 id 없음» 으로 돌리지 않는다 — 거버넌스 변경이 있을 때만 큐, 없으면 경고만
        if os.geteuid() != 0:
            ledger = claude / "_evolve/candidates.tsv"
            os.chmod(ledger, 0)
            try:
                short5 = commit_with("P-5", "rules/e.md")
                r5 = subprocess.run(["bash", hook], cwd=str(repo), capture_output=True, text=True, env=genv, check=False)
                commit_with("P-6", "docs/only2.md")
                r6 = subprocess.run(["bash", hook], cwd=str(repo), capture_output=True, text=True, env=genv, check=False)
            finally:
                os.chmod(ledger, 0o644)
            qlines = queue.read_text(encoding="utf-8").splitlines()
            check("Grok8 4: 대장 읽기 실패 + 거버넌스 변경 → 큐에 id<TAB>해시·«대장 읽기 실패»·«대장에 id 없음» 아님",
                  f"P-5\t{short5}" in qlines and "대장 읽기 실패" in r5.stderr and "재시도 큐에 넣음" in r5.stderr and "대장에 id" not in r5.stderr, f"{qlines} {r5.stderr}")
            check("Grok8 4: 대장 읽기 실패 + 거버넌스 변경 없음 → 큐에 넣지 않고 경고만(미검증 채택 방지)",
                  not any(ln.startswith("P-6\t") for ln in qlines) and "대장 읽기 실패" in r6.stderr and "큐에 넣지 않음" in r6.stderr and r6.returncode == 0, f"{qlines} {r6.stderr}")


def test_post_commit_grok9():
    """Grok 9차 8~11: SHORT 하한 7·큰 목록 grep·awk 실패는 일시 실패·큐의 같은 id 는 해시 교체."""
    stub = ('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$HOME/.claude/_usage/stub-calls"\n'
            'case "$1" in set|attach-commit) exit "${STUB_RC:-0}";; esac\nexit 0\n')
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        claude = home / ".claude"
        for d in ("_evolve", "_usage", "scripts"):
            (claude / d).mkdir(parents=True)
        shutil.copy(SCRIPTS / "ci-gate-post-commit.sh", claude / "scripts/ci-gate-post-commit.sh")
        (claude / "scripts/candidates-append.sh").write_text(stub, encoding="utf-8")
        rows = "".join(f"P-{i}\tT41\t2026-10-10\t-\tpending\t후보 {i}\n" for i in (8, 9, 11, 12)) + "P-10\tT41\t2026-10-10\t-\taccepted\t선승인 후보\n"
        (claude / "_evolve/candidates.tsv").write_text(CANDIDATE_HEADER + rows, encoding="utf-8")
        repo = Path(tmp) / "repo"
        repo.mkdir()
        genv = dict(os.environ, HOME=str(home), GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")

        def git(*a, env=None):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=str(repo), capture_output=True, text=True, env=env or genv, check=True)

        def commit_files(cid, rels):
            for rel in rels:
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text(cid, encoding="utf-8")
            git("add", "--", *rels)
            git("commit", "-q", "-m", f"fix: Change\n\nCandidate: {cid}\n")
            return git("rev-parse", "--short=7", "HEAD").stdout.strip()

        def run_hook(extra_env=None, path_shim=None):
            env = dict(genv, **(extra_env or {}))
            if path_shim:
                env["PATH"] = f"{path_shim}:{os.environ['PATH']}"
            return subprocess.run(["bash", str(claude / "scripts/ci-gate-post-commit.sh")], cwd=str(repo), capture_output=True, text=True, env=env, check=False)

        git("init", "-q")
        queue = claude / "_usage/candidates-attach-retry.tsv"
        calls = claude / "_usage/stub-calls"

        # 8: core.abbrev<7 이어도 commit=<해시> 는 7자 이상
        commit_files("P-8", ["rules/s.md"])
        r = run_hook({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.abbrev", "GIT_CONFIG_VALUE_0": "4"})
        last = calls.read_text(encoding="utf-8").splitlines()[-1]
        h = last.split("commit=")[1].split()[0] if "commit=" in last else ""
        check("Grok9 8: core.abbrev=4 여도 SHORT 는 7자 이상(rev-parse --short=7)", last.startswith("set P-8 accepted") and len(h) >= 7, f"{last!r} {r.stderr}")

        # 9: 변경 파일 목록이 64KB 를 넘어도(1,500개 경로) grep 이 조기 종료로 거짓이 되지 않는다
        names = [f"rules-lazy/{'x' * 40}{i:04d}.md" for i in range(1500)]
        commit_files("P-9", names)
        r = run_hook()
        last = calls.read_text(encoding="utf-8").splitlines()[-1]
        check("Grok9 9: 1,500개 경로(≥64KB) 커밋도 pending 후보를 연결(set 호출)·«변경이 없는 커밋» 아님", last.startswith("set P-9 accepted") and "변경이 없는" not in r.stderr, f"{last!r} {r.stderr[:200]}")
        names2 = [f"rules-lazy/{'y' * 40}{i:04d}.md" for i in range(1500)]
        commit_files("P-10", names2)
        r = run_hook()
        last = calls.read_text(encoding="utf-8").splitlines()[-1]
        check("Grok9 9: accepted 후보도 큰 목록에서 attach-commit 호출", last.startswith("attach-commit P-10 "), f"{last!r} {r.stderr[:200]}")

        # 10: 대장이 읽히는데 awk 가 실패하면 «id 없음» 이 아니라 대장 읽기 실패(일시 실패)로 큐에 넣는다
        shim = Path(tmp) / "shim"
        shim.mkdir()
        (shim / "awk").write_text('#!/bin/bash\ncase "$*" in *\'{print $5; exit}\'*) echo "awk: fail" >&2; exit 2;; esac\nexec /usr/bin/awk "$@"\n', encoding="utf-8")
        (shim / "awk").chmod(0o755)
        short11 = commit_files("P-11", ["rules/t.md"])
        r = run_hook(path_shim=str(shim))
        qlines = queue.read_text(encoding="utf-8").splitlines() if queue.exists() else []
        check("Grok9 10: 읽히는 대장에서 awk 가 실패 → «대장 읽기 실패»·큐 적재·«대장에 id 없음» 아님",
              f"P-11\t{short11}" in qlines and "대장 읽기 실패" in r.stderr and "대장에 id" not in r.stderr and "재시도 큐에 넣음" in r.stderr, f"{qlines} {r.stderr}")

        # Grok 10차 1: rev-parse 실패 → 무경고 exit 0 이 아니라 경고(diff-tree 실패와 같은 방식)·candidates-append 미호출·큐 미적재
        (claude / "_evolve/candidates.tsv").write_text((claude / "_evolve/candidates.tsv").read_text(encoding="utf-8") + "P-13\tT41\t2026-10-10\t-\tpending\t해시 실패 후보\n", encoding="utf-8")
        commit_files("P-13", ["rules/w.md"])
        n_calls = len(calls.read_text(encoding="utf-8").splitlines())
        shim2 = Path(tmp) / "shim-revparse"
        shim2.mkdir()
        (shim2 / "git").write_text('#!/bin/bash\ncase " $* " in *" rev-parse "*) exit 128;; esac\nexec /usr/bin/git "$@"\n', encoding="utf-8")
        (shim2 / "git").chmod(0o755)
        r = run_hook(path_shim=str(shim2))
        qlines = queue.read_text(encoding="utf-8").splitlines() if queue.exists() else []
        check("Grok10 1: rev-parse 실패 → «커밋 해시를 읽지 못함(rev-parse rc=128)» + 수동 안내(--machine)·exit 0",
              "커밋 해시를 읽지 못함(rev-parse rc=128)" in r.stderr and "수동: bash scripts/candidates-append.sh set P-13 accepted --note commit=<해시> --machine" in r.stderr and r.returncode == 0, f"{r.returncode} {r.stderr}")
        check("Grok10 1: 이 경우 candidates-append 를 부르지 않고 큐에도 넣지 않음", len(calls.read_text(encoding="utf-8").splitlines()) == n_calls and not any(ln.startswith("P-13\t") for ln in qlines), f"{qlines}")

        # 11: 같은 id 가 이미 큐에 있으면 해시를 새 값으로 교체한다(amend 로 해시가 바뀐 뒤 다시 실패)
        short12a = commit_files("P-12", ["rules/u.md"])
        r = run_hook({"STUB_RC": "5"})
        (repo / "rules/v.md").write_text("v", encoding="utf-8")
        git("add", "--", "rules/v.md")
        git("commit", "--amend", "-q", "--no-edit")
        short12b = git("rev-parse", "--short=7", "HEAD").stdout.strip()
        r = run_hook({"STUB_RC": "5"})
        p12 = [ln for ln in queue.read_text(encoding="utf-8").splitlines() if ln.startswith("P-12\t")]
        check("Grok9 11: amend 로 해시가 바뀐 뒤 다시 실패해도 큐에는 P-12 한 줄·새 해시로 교체", short12a != short12b and p12 == [f"P-12\t{short12b}"], f"{short12a} {short12b} {p12}")

        # Grok 11차 12: 큐 잠금은 잡았으나 쓰기가 실패하면 «큐 잠금 실패» 가 아니라 «큐 쓰기 실패» (큐 파일 자리를 디렉터리로 막아 모의)
        (claude / "_evolve/candidates.tsv").write_text((claude / "_evolve/candidates.tsv").read_text(encoding="utf-8") + "P-14\tT41\t2026-10-10\t-\tpending\t쓰기 실패 후보\n", encoding="utf-8")
        queue.unlink()
        queue.mkdir()
        commit_files("P-14", ["rules/w14.md"])
        r = run_hook({"STUB_RC": "5"})
        check("Grok11 12: 큐 쓰기 실패 → «큐 쓰기 실패»(잠금 실패라고 적지 않음)·수동 안내·exit 0",
              "재시도 큐 기록 실패" in r.stderr and "큐 쓰기 실패" in r.stderr and "큐 잠금 실패" not in r.stderr and "수동: bash scripts/candidates-append.sh set P-14" in r.stderr and r.returncode == 0, f"{r.returncode} {r.stderr}")


for fn in (test_post_commit_grok9, test_post_commit_failure_paths, test_candidates_append, test_pattern_detect, test_correction_detect,
           test_prompt_log, test_spawn_log, test_subagent_stop,
           test_t41_append, test_t41_auto_mode,
           test_oversight_append, test_usage_check, test_fix_5col,
           test_p6_correction_detect, test_p6_candidates_transitions, test_p6_pattern_detect,
           test_p6_usage_check, test_p6_regression_judge_hold):
    fn()

fail = 0
for name, ok, detail in results:
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       실제: {detail[:300]}")
    fail += 0 if ok else 1

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(results)} checks)")
sys.exit(1 if fail else 0)
