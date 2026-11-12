"""하네스 변경 전파(propagate-queue.sh · propagate-gate.sh · toolcall-text-guard.sh 연결) 회귀 시험.

intent/2026-10-21-harness-change-propagation-gate.md 성공 기준 5: «커밋 → 미전파 → 차단», «커밋 → 전파 → 통과»,
«graphify-out 만 바뀐 커밋 → 대기에 안 올라감(차단 없음)» 을 확인한다. intent/2026-11-05-propagate-behavior-files-only.md:
동작 경로 커밋은 적힘 · 기록 경로만 커밋은 안 적힘 · 섞이면 적힘 · 목록 없음이면 적힘 · check-paths 의 미분류/사라진 경로 경고.
실제 _usage 에 쓰지 않도록 임시 폴더와 PROPAGATE_DIR · PROPAGATE_REPO · PROPAGATE_PATHS · PROPAGATE_AGENTS_JSON 을 쓴다.
`claude agents --json` 은 부르지 않는다.

실행: python3 ~/.claude/scripts/tests/test_propagate.py → 실패 0 이면 exit 0
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path.home() / ".claude/scripts"
QUEUE = SCRIPTS / "propagate-queue.sh"
GATE = SCRIPTS / "propagate-gate.sh"
GUARD = SCRIPTS / "toolcall-text-guard.sh"

SELF = "11111111-1111-4111-8111-111111111111"
PEER = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"

ROOT = Path(tempfile.mkdtemp(prefix="propagate-test-"))
QDIR = ROOT / "q"
REPO = ROOT / "repo"
AGENTS = ROOT / "agents.json"
LIST = ROOT / "paths.txt"
FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("OK  " if cond else "FAIL") + f"  {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def env(**extra: str) -> dict:
    e = {**os.environ, "PROPAGATE_DIR": str(QDIR), "PROPAGATE_REPO": str(REPO), "PROPAGATE_AGENTS_JSON": str(AGENTS),
         "PROPAGATE_PATHS": str(LIST), "PROPAGATE_WAIT": "0", "CLAUDE_CODE_SESSION_ID": SELF}
    e.update(extra)
    return e


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t"}).stdout.strip()


def commit(path: str, msg: str, repo: Path = REPO) -> str:
    return commit_many([path], msg, repo)


def commit_many(paths: list[str], msg: str, repo: Path = REPO) -> str:
    for path in paths:
        f = repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(msg + "\n", encoding="utf-8")
    run = ["git", "-C", str(repo)]
    ident = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run([*run, "add", "--", *paths], check=True, capture_output=True, env=ident)
    subprocess.run([*run, "commit", "-q", "--no-verify", "-m", msg], check=True, capture_output=True, env=ident)
    return subprocess.run([*run, "rev-parse", "--short=9", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def write_list(path: Path, behavior: list[str], record: list[str]) -> None:
    path.write_text("# test\n[behavior]\n" + "".join(f"{x}\n" for x in behavior) + "\n[record]\n" + "".join(f"{x}\n" for x in record), encoding="utf-8")


def check_paths(repo: Path, listfile: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(QUEUE), "check-paths"], check=False, capture_output=True, text=True,
                          env=env(PROPAGATE_REPO=str(repo), PROPAGATE_PATHS=str(listfile)))


def enqueue(cwd: Path = REPO, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(QUEUE), "enqueue"], check=False, cwd=cwd, capture_output=True, text=True, env=env(**extra))


def pending() -> list[dict]:
    p = QDIR / "pending.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


def gate(payload: dict, script: Path = GATE) -> str:
    r = subprocess.run(["bash", str(script)], check=False, input=json.dumps(payload), capture_output=True, text=True, env=env())
    return r.stdout.strip()


def main() -> int:
    write_list(LIST, ["rules/", "skills/", "settings.json"], ["graphify-out/", "intent/"])
    REPO.mkdir(parents=True)
    git("init", "-q")
    AGENTS.write_text(json.dumps([{"sessionId": SELF, "name": "[Harness] Manager", "id": "a"},
                                  {"sessionId": PEER, "name": "[exp] Manager", "id": "b"}]), encoding="utf-8")

    # 1) 하네스 커밋은 대기에 오르고 커밋한 세션 id 가 author 로 남는다
    h1 = commit("rules/a.md", "feat: rule change")
    r = enqueue()
    rows = pending()
    check("규칙 커밋은 대기에 한 줄", len(rows) == 1 and rows[0]["hash"] == h1, f"rc={r.returncode} rows={rows} err={r.stderr}")
    check("author = 커밋한 세션 id", bool(rows) and rows[0]["author"] == SELF)
    enqueue()
    check("같은 해시는 다시 적지 않음", len(pending()) == 1)

    # 2) graphify-out 만 바뀐 커밋은 대기에 오르지 않는다(G3)
    commit("graphify-out/graph.json", "chore(ontology): nightly")
    enqueue()
    check("graphify-out 만 바뀐 커밋은 제외", len(pending()) == 1)

    # 3) 하네스가 아닌 저장소 커밋은 적지 않는다
    other = ROOT / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=other, check=True)
    (other / "x.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "x.txt"], cwd=other, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--no-verify", "-m", "x"], cwd=other, check=True)
    enqueue(cwd=other)
    check("다른 저장소 커밋은 제외", len(pending()) == 1)

    # 4) 세션 id 가 형식에 안 맞으면 author 는 빈 값
    commit("rules/b.md", "fix: another")
    enqueue(CLAUDE_CODE_SESSION_ID="not-a-session")
    check("잘못된 세션 id 는 빈 author", pending()[-1]["author"] == "")

    stop = {"hook_event_name": "Stop", "session_id": SELF, "stop_hook_active": False}

    # 5) 받음 기록이 없으면 커밋한 세션의 Stop 을 막는다(이름·해시 포함)
    out = gate(stop)
    blocked = json.loads(out) if out else {}
    check("미전파 → 차단", blocked.get("decision") == "block", out)
    check("차단 사유에 받지 못한 세션 이름과 해시", "[exp] Manager" in blocked.get("reason", "") and h1 in blocked.get("reason", ""))
    check("차단 사유에 커밋 제목은 싣지 않음", "rule change" not in blocked.get("reason", ""))

    # 6) 같은 턴 재차단 없음 · 다음 턴도 같은 해시로는 다시 막지 않음(한 번만 차단) · SubagentStop · 다른 세션 통과
    check("stop_hook_active 면 통과", gate({**stop, "stop_hook_active": True}) == "")
    check("한 번 막은 해시는 다음 Stop 에서 통과", gate(stop) == "", gate(stop))
    check("SubagentStop 통과", gate({**stop, "hook_event_name": "SubagentStop"}) == "")
    check("다른 세션(author 아님)의 Stop 통과", gate({**stop, "session_id": OTHER}) == "")

    # 7) ack 명령: 형식 검사, 받음 기록이 있으면 처음부터 통과
    h2 = commit("rules/d.md", "feat: acked change")
    enqueue()
    bad = subprocess.run(["bash", str(QUEUE), "ack", "nope", h2, "manual"], check=False, capture_output=True, text=True, env=env())
    check("ack 는 잘못된 세션 id 를 거부", bad.returncode != 0)
    ok = subprocess.run(["bash", str(QUEUE), "ack", PEER, h2, "manual"], check=False, capture_output=True, text=True, env=env())
    check("ack manual 기록", ok.returncode == 0, ok.stderr)
    check("전파 확인 → 통과", gate(stop) == "", gate(stop))

    # 7-1) 끝난 세션(pid 가 죽음)은 세지 않고, 살아 있는 pid 는 센다
    h4 = commit("rules/e.md", "feat: pid check")
    enqueue()
    AGENTS.write_text(json.dumps([{"sessionId": SELF, "name": "[Harness] Manager"},
                                  {"sessionId": PEER, "name": "[exp] Manager", "pid": 4194303}]), encoding="utf-8")
    check("끝난 세션만 남으면 통과", gate(stop) == "")
    AGENTS.write_text(json.dumps([{"sessionId": SELF, "name": "[Harness] Manager"},
                                  {"sessionId": PEER, "name": "[exp] Manager", "pid": os.getpid()}]), encoding="utf-8")
    alive = gate(stop)
    check("살아 있는 세션이면 차단", '"block"' in alive and h4 in alive, alive)

    # 7-2) 첫 지시 전(asleep 표지 120초 안) 세션만 남으면 통과, 표지가 오래됐으면(121초 전) 종전처럼 차단
    h5 = commit("rules/f.md", "feat: asleep check")
    enqueue()
    asleep = QDIR / "asleep" / PEER
    asleep.parent.mkdir(parents=True, exist_ok=True)
    asleep.write_text(f"asleep\t{int(time.time())}\n", encoding="utf-8")
    check("asleep 세션만 남으면 통과", gate(stop) == "")
    asleep.write_text(f"asleep\t{int(time.time()) - 121}\n", encoding="utf-8")
    old = gate(stop)
    check("asleep 표지가 121초 전이면 차단", '"block"' in old and h5 in old, old)

    # 8) toolcall-text-guard.sh 를 거쳐도 같은 차단이 나온다(연결 확인). 새 커밋을 만들어 받음 기록이 없는 상태를 만든다.
    h3 = commit("skills/c.md", "feat: skill")
    enqueue()
    via = gate({**stop, "last_assistant_message": "끝났습니다."}, script=GUARD)
    check("Stop 훅 스크립트를 거친 차단", '"block"' in via and h3 in via, via)

    # 9) 다른 세션이 하나도 없으면 통과
    AGENTS.write_text(json.dumps([{"sessionId": SELF, "name": "[Harness] Manager"}]), encoding="utf-8")
    check("다른 세션이 없으면 통과", gate(stop) == "")

    # 10) 동작 경로 분류(intent/2026-11-05): 기록 경로만 → 제외, 섞임 → 적힘, 파일 항목은 정확히 일치, 디렉터리 항목은 / 경계
    n0 = len(pending())
    commit("intent/x.md", "docs: record only")
    r = enqueue()
    check("기록 경로(intent/)만 바뀐 커밋은 제외", len(pending()) == n0 and r.returncode == 0 and "기록용 커밋" in r.stderr, r.stderr)
    h = commit_many(["rules/m.md", "intent/m.md"], "feat: mixed")
    enqueue()
    check("동작+기록이 섞인 커밋은 적힘", len(pending()) == n0 + 1 and pending()[-1]["hash"] == h)
    h = commit("settings.json", "feat: exact file")
    enqueue()
    check("파일 항목(settings.json)은 정확히 일치하면 적힘", len(pending()) == n0 + 2 and pending()[-1]["hash"] == h)
    commit("settings.json.bak", "chore: not exact")
    enqueue()
    commit("rules-extra/a.md", "chore: dir needs slash boundary")
    enqueue()
    check("접두만 같은 경로(settings.json.bak · rules-extra/)는 제외", len(pending()) == n0 + 2)

    # 11) 분류 점검: enqueue 가 부르고, 미분류·사라진 경로를 경고하며, 커밋은 막지 않는다
    commit("newdir/q.md", "feat: unclassified top dir")
    r = enqueue()
    check("enqueue 끝의 분류 점검이 미분류 경로를 경고", r.returncode == 0 and "'newdir/'" in r.stderr, r.stderr)
    check("미분류 경로만 바뀐 커밋은 동작 아님 → 적지 않음", len(pending()) == n0 + 2)
    cp = ROOT / "cp"
    cp.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=cp, check=True)
    commit_many(["rules/a.md", "intent/b.md", "README.md"], "init", cp)
    ok_list, stale_list = ROOT / "cp-ok.txt", ROOT / "cp-stale.txt"
    write_list(ok_list, ["rules/"], ["intent/", "README.md"])
    r = check_paths(cp, ok_list)
    check("check-paths: 모두 분류되면 경고 없음", r.returncode == 0 and r.stderr == "", r.stderr)
    commit("newdir/c.md", "feat: new top dir", cp)
    r = check_paths(cp, ok_list)
    check("check-paths: 미분류 최상위 경로 한 줄 경고(종료 0)",
          r.returncode == 0 and "'newdir/'" in r.stderr and "propagate-paths.txt" in r.stderr and r.stderr.count("\n") == 1, r.stderr)
    write_list(stale_list, ["rules/", "ghost/"], ["intent/", "README.md", "newdir/"])
    r = check_paths(cp, stale_list)
    check("check-paths: 목록에 있으나 사라진 경로 한 줄 경고(종료 0)",
          r.returncode == 0 and "'ghost/'" in r.stderr and r.stderr.count("\n") == 1, r.stderr)

    # 12) 목록이 없거나 [behavior] 가 비면 안전하게 적는다(종전 동작) + 경고
    commit("intent/y.md", "docs: record only, no list")
    h = pending()[-1]["hash"]
    r = enqueue(PROPAGATE_PATHS=str(ROOT / "none.txt"))
    check("목록 파일이 없으면 기록용 커밋도 적힘 + 경고", len(pending()) == n0 + 3 and pending()[-1]["hash"] != h and "종전처럼" in r.stderr, r.stderr)
    empty_list = ROOT / "empty.txt"
    write_list(empty_list, [], ["intent/"])
    commit("intent/z.md", "docs: record only, empty behavior")
    enqueue(PROPAGATE_PATHS=str(empty_list))
    check("[behavior] 가 비면 기록용 커밋도 적힘", len(pending()) == n0 + 4)

    print(f"\n실패 {len(FAILS)}건" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    sys.exit(rc)
