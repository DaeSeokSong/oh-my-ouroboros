"""ci-gate-commit-msg.sh 회귀 테스트 (자체 완결 — CI_GATE_MSG_TEST seam 사용, 실제 git stage 불필요).

실행: python3 ~/.claude/scripts/tests/test_ci_gate_commit_msg.py → 실패 0 이면 exit 0
CI_GATE_MSG_HOOK 에 훅 경로를 주면 그 사본을 시험한다(수정 전 사본 대조용).
seam 은 CI_GATE_MSG_TEST=1 과 함께 줄 때만 인정된다. 실제 커밋에서 환경변수로 stage 목록을 위조하던 우회를 닫은 결과다.
REF: knowledge/harness/code-history/scripts__tests__test_ci_gate_commit_msg.py.md
"""
import fcntl
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(os.environ.get("CI_GATE_MSG_HOOK") or Path.home() / ".claude/scripts/ci-gate-commit-msg.sh")


def run(msg: str, staged: str, intent_body: str | None = None, seam: bool = True,
        cwd: str | None = None, msg_path: str | None = None, status: str | None = None):
    if msg_path is None:
        with tempfile.NamedTemporaryFile("w", suffix=".msg", delete=False, encoding="utf-8") as f:
            f.write(msg)
            path = f.name
        remove = True
    else:
        Path(msg_path).write_text(msg, encoding="utf-8")
        path, remove = msg_path, False
    env = dict(os.environ, CI_GATE_MSG_TEST_STAGED=staged)
    if seam:
        env["CI_GATE_MSG_TEST"] = "1"
    if intent_body is not None:
        env["CI_GATE_MSG_TEST_INTENT_BODY"] = intent_body
    if status is not None:
        env["CI_GATE_MSG_TEST_STAGED_STATUS"] = status
    r = subprocess.run(["bash", str(HOOK), path], capture_output=True, text=True, env=env, cwd=cwd, check=False)
    if remove:
        os.unlink(path)
    return r.returncode, (r.stdout + r.stderr).strip()


MSG_INTENT = "feat: Add thing\n\nIntent: intent/2026-09-06-x.md\n"
STAGED_INTENT = "skills/x/SKILL.md\nintent/2026-09-06-x.md\n"

CASES = [
    ("feat+핵심+Intent 없음 → 차단", "feat: Add thing\n\nbody\n", "skills/x/SKILL.md\n", 1, None),
    ("feat+핵심+Intent(stage) → 통과", MSG_INTENT, STAGED_INTENT, 0, None),
    ("feat+핵심+Intent(미stage·미추적) → 차단", "feat: Add thing\n\nIntent: intent/2026-01-01-nope.md\n", "skills/x/SKILL.md\n", 1, None),
    ("feat+문서만 → 통과", "feat: Add doc\n\n", "README.md\n", 0, None),
    ("fix+핵심(기존 파일 수정)+Intent 없음 → 통과", "fix: Fix thing\n\n", "scripts/a.sh\n", 0, None, "M\tscripts/a.sh\n"),
    ("chore(ontology) → 통과", "chore(ontology): 자동 갱신\n", "graphify-out/graph.json\n", 0, None),
    ("feat(scope) 형식도 대상 → 차단", "feat(gate): Add\n\n", "rules/x.md\n", 1, None),
    ("주석 줄 뒤 제목·Intent 인식 → 통과", "# comment\nfeat: Add\n\nIntent: intent/2026-09-06-y.md\n# trailing\n", "CLAUDE.md\nintent/2026-09-06-y.md\n", 0, None),
    ("intent 상태 「초안」 → 차단", MSG_INTENT, STAGED_INTENT, 1, "# intent: x\n\n- 상태: 초안(사용자 교정 전)\n"),
    ("intent 상태 「승인」 → 통과", MSG_INTENT, STAGED_INTENT, 0, "# intent: x\n\n- 상태: 승인(2026-09-06)\n"),
    ("Intent 커밋에 graphify-out 혼입 → 차단", MSG_INTENT, STAGED_INTENT + "graphify-out/graph.json\n", 1, None),
    ("온톨로지 단독(Intent 줄 없음) → 통과", "feat: 온톨로지 갱신\n\n", "graphify-out/graph.json\n", 0, None),
    ("feat! 형식도 대상 → 차단", "feat!: Add breaking\n\n", "rules/x.md\n", 1, None),
    ("제목 앞 공백 feat 도 대상 → 차단", " feat: Add\n\n", "rules/x.md\n", 1, None),
    ("feat(scope)! 형식도 대상 → 차단", "feat(gate)!: Add\n\n", "rules/x.md\n", 1, None),
    ("fix+새 스크립트+Intent 없음 → 차단", "fix: Add guard\n\n", "scripts/new-gate.sh\n", 1, None, "A\tscripts/new-gate.sh\n"),
    ("refactor+새 규칙+Intent 없음 → 차단", "refactor: Split rules\n\n", "rules/new.md\n", 1, None, "A\trules/new.md\n"),
    ("fix(scope)+새 에이전트+Intent 없음 → 차단", "fix(agent): Add\n\n", "agents/new.md\n", 1, None, "A\tagents/new.md\n"),
    ("fix+새 스킬+Intent 있음 → 통과", "fix: Add skill\n\nIntent: intent/2026-09-14-x.md\n",
     "skills/new/SKILL.md\nintent/2026-09-14-x.md\n", 0, None, "A\tskills/new/SKILL.md\nA\tintent/2026-09-14-x.md\n"),
    ("refactor+구조 밖 새 파일 → 통과", "refactor: Move doc\n\n", "docs/new.md\n", 0, None, "A\tdocs/new.md\n"),
    ("fix+이름만 바뀐 구조 파일(R) → 통과", "fix: Rename\n\n", "rules/b.md\n", 0, None, "R100\trules/a.md\trules/b.md\n"),
    ("docs+새 규칙 파일 → 통과 (타입 대상 밖)", "docs: Add note\n\n", "rules/new.md\n", 0, None, "A\trules/new.md\n"),
    ("Jira 접두 feat 도 대상 → 차단", "PROJ-1 feat: Add\n\n", "rules/x.md\n", 1, None),
    ("대괄호 Jira 접두 feat 도 대상 → 차단", "[PROJ-1] feat: Add\n\n", "rules/x.md\n", 1, None),
    ("Jira 접두 docs 는 대상 밖 → 통과", "PROJ-1 docs: Add note\n\n", "rules/x.md\n", 0, None),
    ("fix+새 tools 파일+Intent 없음 → 차단", "fix: Add watcher\n\n", "tools/train-watcher/new.sh\n", 1, None, "A\ttools/train-watcher/new.sh\n"),
    ("fix+새 config 파일+Intent 없음 → 차단", "fix: Add unit\n\n", "config/hooks/new.json\n", 1, None, "A\tconfig/hooks/new.json\n"),
    ("feat+config 만+Intent 없음 → 차단", "feat: Add allowlist\n\n", "config/scope-allow.txt\n", 1, None, "A\tconfig/scope-allow.txt\n"),
    ("Intent 경로에 `..` 성분 → 차단", "feat: Add\n\nIntent: intent/../x.md\n", "skills/x/SKILL.md\nintent/../x.md\n", 1, None),
]

fail = 0
total = 0
for case in CASES:
    name, msg, staged, want, body = case[:5]
    status = case[5] if len(case) > 5 else None
    rc, out = run(msg, staged, body, status=status)
    ok = rc == want
    fail += 0 if ok else 1
    total += 1
    print(f"{'OK ' if ok else 'FAIL'} {name}: exit {rc} (기대 {want})" + ("" if ok else f"\n     {out[:200]}"))

with tempfile.TemporaryDirectory() as tmp:
    subprocess.run(["git", "init", "-q", tmp], check=True, capture_output=True)
    SEAM_CASES = [
        ("seam 단독(CI_GATE_MSG_TEST 없음) → 위조 무시, 실제 stage 로 판정", False, None, 0),
        ("seam 두 변수 함께 → 위조 인정, 차단", True, None, 1),
        (".git/ 아래 메시지 파일 → seam 무시, 실제 stage 로 판정", True, str(Path(tmp) / ".git/COMMIT_EDITMSG"), 0),
    ]
    for name, seam, msg_path, want in SEAM_CASES:
        rc, out = run("feat: Add thing\n\nbody\n", "skills/x/SKILL.md\n", seam=seam, cwd=tmp, msg_path=msg_path)
        ok = rc == want
        fail += 0 if ok else 1
        total += 1
        print(f"{'OK ' if ok else 'FAIL'} {name}: exit {rc} (기대 {want})" + ("" if ok else f"\n     {out[:200]}"))

with tempfile.TemporaryDirectory() as tmp:
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    subprocess.run(["git", "init", "-q", tmp], check=True, capture_output=True, env=env)
    for rel in ("rules/한글.md", "scripts/한글.sh", "graphify-out/한글.md", "intent/2026-10-01-k.md"):
        p = Path(tmp) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")
    os.environ.update(env)

    def stage_only(*paths: str) -> None:
        subprocess.run(["git", "rm", "-r", "-q", "--cached", "--ignore-unmatch", "."], cwd=tmp, capture_output=True, env=env, check=False)
        subprocess.run(["git", "add", "--", *paths], cwd=tmp, check=True, capture_output=True, env=env)

    UNICODE_CASES = [
        ("비ASCII 새 rules 경로 feat+Intent 없음 → 차단", "feat: Add\n\nbody\n", ("rules/한글.md",), 1),
        ("비ASCII 새 scripts 경로 fix 신설+Intent 없음 → 차단", "fix: Add\n\nbody\n", ("scripts/한글.sh",), 1),
        ("Intent 커밋에 비ASCII graphify-out 혼입 → 차단", "feat: Add\n\nIntent: intent/2026-10-01-k.md\n", ("graphify-out/한글.md", "intent/2026-10-01-k.md"), 1),
    ]
    for name, msg, paths, want in UNICODE_CASES:
        stage_only(*paths)
        rc, out = run(msg, "", seam=False, cwd=tmp)
        ok = rc == want
        fail += 0 if ok else 1
        total += 1
        print(f"{'OK ' if ok else 'FAIL'} {name}: exit {rc} (기대 {want})" + ("" if ok else f"\n     {out[:200]}"))

POST = Path(HOOK).parent / "ci-gate-post-commit.sh"
CAND_HDR = "id\tsource\t생성일\tbench_id\tstatus\t요약\tnote\n"


def fake_home(tmp: str, rows: list[str]) -> str:
    claude = Path(tmp) / ".claude"
    (claude / "_evolve").mkdir(parents=True)
    (claude / "_usage").mkdir()
    (claude / "scripts").symlink_to(Path(HOOK).parent)
    (claude / "_evolve/candidates.tsv").write_text(CAND_HDR + "".join(r + "\n" for r in rows), encoding="utf-8")
    return tmp


def run_trailer(home: str, msg: str, staged: str):
    with tempfile.NamedTemporaryFile("w", suffix=".msg", delete=False, encoding="utf-8") as f:
        f.write(msg)
        path = f.name
    env = dict(os.environ, HOME=home, CI_GATE_MSG_TEST="1", CI_GATE_MSG_TEST_STAGED=staged)
    r = subprocess.run(["bash", str(HOOK), path], capture_output=True, text=True, env=env, check=False)
    os.unlink(path)
    return r.returncode, r.stdout, r.stderr


with tempfile.TemporaryDirectory() as tmp:
    home = fake_home(tmp, ["T41-1\tT41\t2026-10-10\t-\tpending\tcoder/구현 정확성: FAIL\t",
                           "T41-2\tT41\t2026-10-10\t-\taccepted\t끝난 것\tcommit=abc1234",
                           "T41-8\tT41\t2026-10-10\t-\taccepted\t선승인 후보\t",
                           "T41-9\tT41\t2026-10-10\t-\trejected\t기각된 후보\t",
                           "T41-13\tT41\t2026-10-10\t-\taccepted\t경계 오탐 후보\tprecommit=abc1234"])
    TRAILER_CASES = [
        ("Candidate 유효(미결·rules 변경) → 통과·경고 없음", "docs: Tidy\n\nCandidate: T41-1\n", "rules/x.md\n", None),
        ("Candidate: none → 통과·경고 없음", "docs: Tidy\n\nCandidate: none\n", "README.md\n", None),
        ("Candidate 없음(id 오타) → 통과·경고", "docs: Tidy\n\nCandidate: NOPE-9\n", "rules/x.md\n", "대장에 id"),
        ("Candidate 이미 accepted+commit= 있음(amend·rebase 재실행) → 통과·경고 없음", "docs: Tidy\n\nCandidate: T41-2\n", "rules/x.md\n", None),
        ("Candidate accepted+commit= 있으면 파일과 무관하게 통과·경고 없음", "docs: Tidy\n\nCandidate: T41-2\n", "README.md\n", None),
        ("Candidate 선승인(accepted·commit= 없음)+rules 변경 → 통과·경고 없음(post-commit 이 해시를 붙임)", "docs: Tidy\n\nCandidate: T41-8\n", "rules/x.md\n", None),
        ("Candidate 선승인이라도 agents/rules 변경 없으면 경고", "docs: Tidy\n\nCandidate: T41-8\n", "README.md\n", "변경이 없는 커밋"),
        ("Candidate rejected → 통과·경고", "docs: Tidy\n\nCandidate: T41-9\n", "rules/x.md\n", "rejected"),
        ("Candidate 유효해도 agents/rules 변경 없음 → 통과·경고", "docs: Tidy\n\nCandidate: T41-1\n", "README.md\n", "변경이 없는 커밋"),
        ("feat 의 Candidate 경고는 다른 게이트를 바꾸지 않음(Intent 없음 → 여전히 차단)", "feat: Add\n\nCandidate: NOPE-9\n", "skills/x/SKILL.md\n", "대장에 id"),
        ("id 형식 오류도 경고만", "docs: Tidy\n\nCandidate: ../../etc\n", "rules/x.md\n", "형식"),
    ]
    for name, msg, staged, warn in TRAILER_CASES:
        rc, out, err = run_trailer(home, msg, staged)
        want_rc = 1 if msg.startswith("feat:") else 0
        ok = rc == want_rc and ((warn is None and "Candidate" not in err) or (warn is not None and warn in err and "경고만" in err))
        fail += 0 if ok else 1
        total += 1
        print(f"{'OK ' if ok else 'FAIL'} {name}: exit {rc}" + ("" if ok else f"\n     out={out[:120]} err={err[:200]}"))
    rc, out, err = run_trailer(home, "feat: Add\n\nCandidate: T41-1\nIntent: intent/2026-09-06-x.md\n", STAGED_INTENT)
    ok = rc == 0 and "Candidate" not in err
    fail += 0 if ok else 1
    total += 1
    print(f"{'OK ' if ok else 'FAIL'} feat+Intent+유효 Candidate → 통과: exit {rc}" + ("" if ok else f"\n     {out[:120]} {err[:200]}"))
    for cid, files, want_rc, want_txt in (("T41-8", "rules/x.md\n", 0, "이미 accepted, post-commit 이 해시를 붙임"),
                                          ("T41-2", "README.md\n", 0, "가 있어 유지됨"),
                                          ("T41-8", "README.md\n", 1, "변경이 없는 커밋"),
                                          ("T41-13", "README.md\n", 1, "변경이 없는 커밋"),
                                          ("T41-13", "rules/x.md\n", 0, "post-commit 이 해시를 붙임")):
        r = subprocess.run(["bash", str(POST), "--check", cid], input=files, capture_output=True, text=True, env=dict(os.environ, HOME=home), check=False)
        ok = r.returncode == want_rc and want_txt in r.stdout
        fail += 0 if ok else 1
        total += 1
        print(f"{'OK ' if ok else 'FAIL'} --check {cid} {files.strip()} → exit {want_rc}·사유 «{want_txt}»" + ("" if ok else f"\n     rc={r.returncode} out={r.stdout[:160]}"))

with tempfile.TemporaryDirectory() as tmp:
    home = fake_home(str(Path(tmp) / "home"), ["T41-1\tT41\t2026-10-10\t-\tpending\tcoder/구현 정확성: FAIL\t"])
    repo = Path(tmp) / "repo"
    repo.mkdir()
    genv = dict(os.environ, HOME=home, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=str(repo), capture_output=True, text=True, env=genv, check=False)
    git("init", "-q")
    (repo / "rules").mkdir()
    (repo / "rules/x.md").write_text("a\n", encoding="utf-8")
    git("add", "--", "rules/x.md")
    git("commit", "-q", "-m", "docs: Add rule")
    (repo / "README.md").write_text("r\n", encoding="utf-8")
    git("add", "--", "README.md")
    git("commit", "-q", "-m", "docs: Readme")
    git("rm", "-q", "--", "rules/x.md")
    msgf = Path(tmp) / "msg"
    msgf.write_text("docs: Drop rule\n\nCandidate: T41-1\n", encoding="utf-8")
    r = subprocess.run(["bash", str(HOOK), str(msgf)], cwd=str(repo), capture_output=True, text=True, env=genv, check=False)
    ok = r.returncode == 0 and "Candidate" not in r.stderr
    fail += 0 if ok else 1
    total += 1
    print(f"{'OK ' if ok else 'FAIL'} 삭제만 있는 커밋(rules/x.md 삭제) + 유효 Candidate → 경고 없음(직전 커밋 파일로 오판하지 않음): exit {r.returncode}" + ("" if ok else f"\n     {r.stdout[:120]} {r.stderr[:240]}"))

with tempfile.TemporaryDirectory() as tmp:
    home = fake_home(str(Path(tmp) / "home"), ["T41-1\tT41\t2026-10-10\t-\tpending\tcoder/구현 정확성: FAIL\t",
                                                 "T41-3\tT41\t2026-10-10\t-\tpending-bench\tqa/범위 준수: BLOCKED\t",
                                                 "T41-4\tT41\t2026-10-10\t-\texpired\t만료됨\t"])
    repo = Path(tmp) / "repo"
    hooks = Path(tmp) / "hooks"
    repo.mkdir()
    hooks.mkdir()
    # WHY: 실제 설치는 심볼릭 링크지만 git 은 실행 비트가 없는 훅을 무시한다(스크립트 파일의 +x 는 setup-harness.sh 가 건다).
    # 시험은 실행 비트를 시험 쪽에서 보장하려고 얇은 래퍼를 둔다. $0 이 POST 경로가 되어 SELF_DIR 해석은 같다.
    (hooks / "post-commit").write_text(f'#!/bin/sh\nexec bash "{POST}" "$@"\n', encoding="utf-8")
    os.chmod(hooks / "post-commit", 0o755)
    # WHY: HARNESS_GIT_DIR: attach-commit 이 해시 실재를 확인하는 저장소(기본 $HOME/.claude). 시험의 저장소는 임시 repo 라 그쪽을 가리킨다.
    genv = dict(os.environ, HOME=home, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", HARNESS_GIT_DIR=str(repo))
    git = lambda *a: subprocess.run(["git", "-c", f"core.hooksPath={hooks}", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                    cwd=str(repo), capture_output=True, text=True, env=genv, check=False)
    git("init", "-q")

    def commit(msg: str, rel: str, body: str):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        git("add", "--", rel)
        return git("commit", "-q", "-m", msg)

    def row(cid: str) -> list[str]:
        for line in (Path(home) / ".claude/_evolve/candidates.tsv").read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if f[0] == cid:
                return f + [""] * (7 - len(f))
        return []

    def check_pc(name: str, ok: bool, detail: str = "") -> None:
        global fail, total
        fail += 0 if ok else 1
        total += 1
        print(f"{'OK ' if ok else 'FAIL'} {name}" + ("" if ok else f"\n     {detail[:300]}"))

    r = commit("fix: Tidy rules\n\nCandidate: T41-1\n", "rules/x.md", "a\n")
    short = git("rev-parse", "--short", "HEAD").stdout.strip()
    check_pc("post-commit: rules 변경 + 미결 id → accepted + commit=<해시> note", row("T41-1")[4] == "accepted" and row("T41-1")[6] == f"commit={short}", str(row("T41-1")) + r.stderr)
    r = commit("fix: Tidy rules again\n\nCandidate: T41-1\n", "rules/x.md", "b\n")
    check_pc("post-commit: 이미 accepted 인 id 는 조용히 건너뜀(note 불변·경고 없음)", row("T41-1")[6] == f"commit={short}" and "Candidate" not in r.stderr, str(row("T41-1")) + r.stderr)
    r = commit("docs: Readme\n\nCandidate: T41-3\n", "README.md", "r\n")
    check_pc("post-commit: agents/rules 변경 없는 커밋은 연결 안 함 + 경고 + 커밋은 유지",
             row("T41-3")[4] == "pending-bench" and "연결 안 함" in r.stderr and git("log", "-1", "--format=%s").stdout.strip() == "docs: Readme", str(row("T41-3")) + r.stderr)
    r = commit("fix: Tidy skills\n\nCandidate: T41-4\n", "skills/s/SKILL.md", "s\n")
    short4 = git("rev-parse", "--short", "HEAD").stdout.strip()
    check_pc("post-commit: expired 후보도 agents/rules 계열 변경이면 accepted + commit=<해시> (만료가 검증보다 먼저 끝난 경우)",
             row("T41-4")[4] == "accepted" and row("T41-4")[6] == f"commit={short4}" and r.stderr == "", str(row("T41-4")) + r.stderr)
    with open(Path(home) / ".claude/_evolve/candidates.tsv", "a", encoding="utf-8") as f_:
        f_.write("T41-15\tT41\t2026-10-10\t-\texpired\t만료됨 문서만\t\n")
    r = commit("docs: Readme for expired\n\nCandidate: T41-15\n", "README3.md", "r\n")
    check_pc("post-commit: expired 후보라도 agents/rules 변경이 없으면 연결 안 함 + 경고", row("T41-15")[4] == "expired" and "연결 안 함" in r.stderr, str(row("T41-15")) + r.stderr)
    with open(Path(home) / ".claude/_evolve/candidates.tsv", "a", encoding="utf-8") as f_:
        f_.write("T41-16\tT41\t2026-10-10\t-\trejected\t기각됨\t\n")
    r = commit("fix: Tidy rules for rejected\n\nCandidate: T41-16\n", "rules/rj.md", "r\n")
    check_pc("post-commit: rejected 후보는 계속 연결 안 함 + 경고", row("T41-16")[4] == "rejected" and "상태가 'rejected'" in r.stderr, str(row("T41-16")) + r.stderr)
    r = commit("fix: Tidy agents\n\nCandidate: none\n", "agents/a.md", "a\n")
    check_pc("post-commit: Candidate: none 은 아무 일도 안 함", row("T41-3")[4] == "pending-bench" and r.stderr == "", r.stderr)
    r = commit("fix: Tidy claude\n\nCandidate: NOPE-1\n", "CLAUDE.md", "c\n")
    check_pc("post-commit: 없는 id 는 경고만(커밋 성공)", r.returncode == 0 and "대장에 id" in r.stderr, r.stderr)
    r = commit("fix: Plain\n\nbody\n", "rules/y.md", "y\n")
    check_pc("post-commit: 트레일러 없는 커밋은 무반응", r.stderr == "" and row("T41-3")[4] == "pending-bench", r.stderr)

    cand_path = Path(home) / ".claude/_evolve/candidates.tsv"
    with open(cand_path, "a", encoding="utf-8") as f:
        f.write("T41-5\tT41\t2026-10-10\t-\taccepted\tcoder/구현 정확성: 먼저 승인\t\n")
        f.write("T41-6\tT41\t2026-10-10\t-\taccepted\tqa/범위 준수: 사람 판정 있음\t사람 판정\n")
        f.write("T41-7\tT41\t2026-10-10\t-\tpending\tcoder/구현 정확성: 한글 경로\t\n")
    r = commit("fix: Later commit\n\nCandidate: T41-5\n", "skills/s/later.md", "l\n")
    short5 = git("rev-parse", "--short", "HEAD").stdout.strip()
    check_pc("post-commit: accepted+해시 없음 → 상태 불변·commit=<해시> 만 붙음", row("T41-5")[4] == "accepted" and row("T41-5")[6] == f"commit={short5}", str(row("T41-5")) + r.stderr)
    r = commit("fix: Later commit 2\n\nCandidate: T41-6\n", "skills/s/later2.md", "l\n")
    short6 = git("rev-parse", "--short", "HEAD").stdout.strip()
    check_pc("post-commit: accepted+사람 비고 → '; commit=<해시>' 덧붙임", row("T41-6")[6] == f"사람 판정; commit={short6}", str(row("T41-6")) + r.stderr)
    r = commit("fix: Again\n\nCandidate: T41-5\n", "skills/s/later3.md", "l\n")
    check_pc("post-commit: 이미 commit= 이 있으면 첫 해시 유지", row("T41-5")[6] == f"commit={short5}", str(row("T41-5")))
    r = commit("docs: Readme only\n\nCandidate: T41-6\n", "README2.md", "r\n")
    check_pc("post-commit: accepted 라도 agents/rules 변경 없는 커밋은 해시를 더 붙이지 않음", row("T41-6")[6] == f"사람 판정; commit={short6}", str(row("T41-6")))
    r = commit("fix: 한글 경로 규칙 변경\n\nCandidate: T41-7\n", "rules/한글규칙.md", "k\n")
    short7 = git("rev-parse", "--short", "HEAD").stdout.strip()
    check_pc("post-commit: 한글 파일명 rules 변경 커밋도 연결됨(인용형 경로 회귀)", row("T41-7")[4] == "accepted" and row("T41-7")[6] == f"commit={short7}", str(row("T41-7")) + r.stderr)

    with open(cand_path, "a", encoding="utf-8") as f:
        f.write("T41-10\tT41\t2026-10-10\t-\tpending\tcoder/구현 정확성: 머지 커밋\t\n")
        f.write("T41-11\tT41\t2026-10-10\t-\tpending\tcoder/구현 정확성: 잠금 중\t\n")
    git("checkout", "-q", "-b", "side")
    commit("docs: side change\n", "rules/side.md", "s\n")
    git("checkout", "-q", "-")
    commit("docs: main change\n", "main-only.txt", "m\n")
    git("merge", "--no-ff", "--no-commit", "side")
    r = git("commit", "-q", "-m", "fix: Merge side\n\nCandidate: T41-10\n")
    short10 = git("rev-parse", "--short", "HEAD").stdout.strip()
    check_pc("post-commit: 머지 커밋도 부모별 diff 를 합쳐 rules 변경을 찾아 연결(-m)", row("T41-10")[4] == "accepted" and row("T41-10")[6] == f"commit={short10}", str(row("T41-10")) + r.stderr)

    retry_f = Path(home) / ".claude/_usage/candidates-attach-retry.tsv"
    fd = os.open(str(Path(home) / ".claude/_evolve/candidates.lock"), os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        r = commit("fix: Locked\n\nCandidate: T41-11\n", "rules/locked.md", "l\n")
        short11 = git("rev-parse", "--short", "HEAD").stdout.strip()
        r2 = commit("fix: Locked again\n\nCandidate: T41-11\n", "rules/locked2.md", "l\n")
        short11b = git("rev-parse", "--short", "HEAD").stdout.strip()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    lines = retry_f.read_text(encoding="utf-8").splitlines() if retry_f.exists() else []
    # WHY: 설계 결정(2026-10-17): 큐는 같은 id 의 최신 해시를 든다 — amend·재커밋으로 바뀐 첫 해시는 매달린 커밋이라 연결하면 안 된다.
    check_pc("post-commit: 잠금 실패 → 큐에 'id<TAB>해시' 한 줄(같은 id 의 두 번째 커밋 해시로 교체)·후보는 pending 유지·커밋은 유지",
             lines[:1] == [f"T41-11\t{short11b}"] and short11 != short11b and row("T41-11")[4] == "pending" and "재시도 큐" in r.stderr, f"{lines} {row('T41-11')} {r.stderr}")
    check_pc("post-commit: 같은 id 는 큐에 한 줄(해시는 최신 커밋으로 교체)", len(lines) == 1, str(lines))

    with open(cand_path, "a", encoding="utf-8") as f:
        f.write("T41-14\tT41\t2026-10-10\t-\tpending\tcoder/구현 정확성: flock 없음\t\n")
    nobin = Path(tmp) / "bin-noflock"
    nobin.mkdir()
    for p_ in Path("/usr/bin").iterdir():
        if p_.name != "flock":
            (nobin / p_.name).symlink_to(p_)
    (repo / "rules/noflock.md").write_text("n\n", encoding="utf-8")
    git("add", "--", "rules/noflock.md")
    r = subprocess.run(["git", "-c", f"core.hooksPath={hooks}", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "fix: No flock\n\nCandidate: T41-14\n"],
                       cwd=str(repo), capture_output=True, text=True, env=dict(genv, PATH=str(nobin)), check=False)
    lines = retry_f.read_text(encoding="utf-8").splitlines()
    check_pc("post-commit: flock 없음 → 큐에 쓰지 않고 «잠금 불가: flock 없음»·수동 안내·커밋 유지·«큐에 넣음» 없음",
             not any(ln.startswith("T41-14\t") for ln in lines) and "잠금 불가: flock 없음" in r.stderr and "수동:" in r.stderr and "재시도 큐에 넣음" not in r.stderr
             and r.returncode == 0 and row("T41-14")[4] == "pending", f"{r.returncode} {lines} {r.stderr}")

    with open(cand_path, "a", encoding="utf-8") as f:
        f.write("T41-12\tT41\t2026-10-10\t-\tpending\tcoder/구현 정확성: 큐 잠금 실패\t\n")
    fd1 = os.open(str(Path(home) / ".claude/_evolve/candidates.lock"), os.O_CREAT | os.O_RDWR)
    fd2 = os.open(str(Path(home) / ".claude/_usage/candidates-attach-retry.lock"), os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd1, fcntl.LOCK_EX)
    fcntl.flock(fd2, fcntl.LOCK_EX)
    try:
        r = commit("fix: Locked both\n\nCandidate: T41-12\n", "rules/locked3.md", "l\n")
    finally:
        for f_ in (fd1, fd2):
            fcntl.flock(f_, fcntl.LOCK_UN)
            os.close(f_)
    lines = retry_f.read_text(encoding="utf-8").splitlines()
    check_pc("post-commit: 큐 잠금도 못 잡으면 줄을 잃고 stderr 한 줄·커밋 유지·후보 pending",
             not any(ln.startswith("T41-12\t") for ln in lines) and "재시도 큐 기록 실패 — 연결 누락" in r.stderr and "수동:" in r.stderr
             and "재시도 큐에 넣음" not in r.stderr and r.returncode == 0 and row("T41-12")[4] == "pending"
             and git("log", "-1", "--format=%s").stdout.strip() == "fix: Locked both", f"{lines} {r.stderr}")

with tempfile.TemporaryDirectory() as tmp:
    home = fake_home(str(Path(tmp) / "home"), ["T41-1\tT41\t2026-10-10\t-\tpending\tcoder/구현 정확성: FAIL\t"])
    genv = dict(os.environ, HOME=home, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    for label, rel, want_warn in (("HEAD 에 agents/ 변경", "agents/a.md", False), ("HEAD 에 README 만", "README.md", True)):
        repo = Path(tmp) / ("repo-" + rel.split("/")[0])
        repo.mkdir()
        for args in (["init", "-q"], ["add", "--", "."]):
            if args[0] == "add":
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text("x\n", encoding="utf-8")
            subprocess.run(["git", *args], cwd=str(repo), capture_output=True, env=genv, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c1"], cwd=str(repo), capture_output=True, env=genv, check=True)
        msg = Path(tmp) / "amend.msg"
        msg.write_text("docs: Tidy\n\nCandidate: T41-1\n", encoding="utf-8")
        r = subprocess.run(["bash", str(HOOK), str(msg)], cwd=str(repo), capture_output=True, text=True, env=genv, check=False)
        ok = r.returncode == 0 and (("변경이 없는 커밋" in r.stderr) if want_warn else ("Candidate" not in r.stderr))
        fail += 0 if ok else 1
        total += 1
        print(f"{'OK ' if ok else 'FAIL'} amend(스테이징 0)+{label} → " + ("경고" if want_warn else "경고 없음") + ("" if ok else f"\n     rc={r.returncode} err={r.stderr[:200]}"))

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({total} cases)")
sys.exit(1 if fail else 0)
