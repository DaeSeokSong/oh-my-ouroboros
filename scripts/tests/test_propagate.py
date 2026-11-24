"""하네스 변경 전파(propagate-queue.sh · propagate-gate.sh · toolcall-text-guard.sh 연결) 회귀 시험.

intent/2026-10-21-harness-change-propagation-gate.md 성공 기준 5: «커밋 → 미전파 → 차단», «커밋 → 전파 → 통과»,
«graphify-out 만 바뀐 커밋 → 대기에 안 올라감(차단 없음)» 을 확인한다. intent/2026-11-05-propagate-behavior-files-only.md:
동작 경로 커밋은 적힘 · 기록 경로만 커밋은 안 적힘 · 섞이면 적힘 · 목록 없음이면 적힘 · check-paths 의 미분류/사라진 경로 경고.
같은 intent 개정 3: enqueue 는 held.jsonl 에 보류, release 가 가장 최근 줄 하나만 pending.jsonl 로 내보냄(빈 보류 · 중복 해시 ·
사라진 커밋 · 권한 · 링크인 보류 파일), held 는 건수와 가장 오래된 시각만.
실제 _usage 에 쓰지 않도록 임시 폴더와 PROPAGATE_DIR · PROPAGATE_REPO · PROPAGATE_PATHS · PROPAGATE_AGENTS_JSON 을 쓴다.
`claude agents --json` 은 부르지 않는다.

실행: python3 ~/.claude/scripts/tests/test_propagate.py → 실패 0 이면 exit 0
REF: knowledge/harness/code-history/scripts__tests__test_propagate.py.md
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


def held() -> list[dict]:
    p = QDIR / "held.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


def queue(*args: str, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(QUEUE), *args], check=False, cwd=REPO, capture_output=True, text=True, env=env(**extra))


def ship(path: str, msg: str) -> str:
    h = commit(path, msg)
    enqueue()
    queue("release")
    return h


def gate(payload: dict, script: Path = GATE) -> str:
    r = subprocess.run(["bash", str(script)], check=False, input=json.dumps(payload), capture_output=True, text=True, env=env())
    return r.stdout.strip()


def main() -> int:
    write_list(LIST, ["rules/", "skills/", "settings.json"], ["graphify-out/", "intent/"])
    REPO.mkdir(parents=True)
    git("init", "-q")
    AGENTS.write_text(json.dumps([{"sessionId": SELF, "name": "[Harness] Manager", "id": "a"},
                                  {"sessionId": PEER, "name": "[exp] Manager", "id": "b"}]), encoding="utf-8")

    syn = subprocess.run(["bash", "-n", str(QUEUE)], check=False, capture_output=True, text=True)
    check("전파 스크립트 문법(bash -n)", syn.returncode == 0, syn.stderr)

    h1 = commit("rules/a.md", "feat: rule change")
    r = enqueue()
    rows = held()
    check("규칙 커밋은 보류에 한 줄", len(rows) == 1 and rows[0]["hash"] == h1, f"rc={r.returncode} rows={rows} err={r.stderr}")
    check("보류 중에는 대기 파일에 적지 않음", pending() == [])
    check("author = 커밋한 세션 id", bool(rows) and rows[0]["author"] == SELF)
    check("보류 파일 권한은 이 사용자만(600)", (QDIR / "held.jsonl").stat().st_mode & 0o777 == 0o600,
          oct((QDIR / "held.jsonl").stat().st_mode))
    check("보류 폴더 권한은 이 사용자만(700)", QDIR.stat().st_mode & 0o777 == 0o700, oct(QDIR.stat().st_mode))
    enqueue()
    check("같은 해시는 다시 적지 않음", len(held()) == 1)

    commit("graphify-out/graph.json", "chore(ontology): nightly")
    enqueue()
    check("graphify-out 만 바뀐 커밋은 제외", len(held()) == 1)

    other = ROOT / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=other, check=True)
    (other / "x.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "x.txt"], cwd=other, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--no-verify", "-m", "x"], cwd=other, check=True)
    enqueue(cwd=other)
    check("다른 저장소 커밋은 제외", len(held()) == 1)

    hb = commit("rules/b.md", "fix: another")
    enqueue(CLAUDE_CODE_SESSION_ID="not-a-session")
    check("잘못된 세션 id 는 빈 author", held()[-1]["author"] == "")

    stop = {"hook_event_name": "Stop", "session_id": SELF, "stop_hook_active": False}
    check("보류만 있으면 Stop 통과(대기 파일 없음)", gate(stop) == "")

    t0 = int(time.time())
    r = queue("release")
    rows = pending()
    check("release: 보류 2건 중 가장 최근 한 줄만 대기로", len(rows) == 1 and rows[0]["hash"] == hb, f"{rows} {r.stderr}")
    check("release: 출력은 «보류 N건 → 대기 1줄(<해시>)» 한 줄", r.returncode == 0 and r.stdout.strip() == f"보류 2건 → 대기 1줄({hb})", r.stdout + r.stderr)
    check("release: 출력에 커밋 제목을 싣지 않음", "another" not in r.stdout + r.stderr)
    check("release: 보류 파일을 비움", held() == [] and (QDIR / "held.jsonl").exists())
    check("release: 대기 줄 형식(ts · hash · subject · author, ts 는 내보낸 시각, subject 는 커밋 제목)",
          bool(rows) and list(rows[0]) == ["ts", "hash", "subject", "author"] and rows[0]["ts"] >= t0 and rows[0]["subject"] == "fix: another")
    r = queue("release")
    check("release: 보류 0건이면 알리고 종료 0 · 대기 그대로", r.returncode == 0 and "보류 0건" in r.stdout and len(pending()) == 1, r.stdout + r.stderr)

    h1 = ship("rules/a2.md", "feat: rule change")
    out = gate(stop)
    blocked = json.loads(out) if out else {}
    check("미전파 → 차단", blocked.get("decision") == "block", out)
    check("차단 사유에 받지 못한 세션 이름과 해시", "[exp] Manager" in blocked.get("reason", "") and h1 in blocked.get("reason", ""))
    check("차단 사유에 커밋 제목은 싣지 않음", "rule change" not in blocked.get("reason", ""))

    check("stop_hook_active 면 통과", gate({**stop, "stop_hook_active": True}) == "")
    check("한 번 막은 해시는 다음 Stop 에서 통과", gate(stop) == "", gate(stop))
    check("SubagentStop 통과", gate({**stop, "hook_event_name": "SubagentStop"}) == "")
    check("다른 세션(author 아님)의 Stop 통과", gate({**stop, "session_id": OTHER}) == "")

    h2 = ship("rules/d.md", "feat: acked change")
    bad = subprocess.run(["bash", str(QUEUE), "ack", "nope", h2, "manual"], check=False, capture_output=True, text=True, env=env())
    check("ack 는 잘못된 세션 id 를 거부", bad.returncode != 0)
    ok = subprocess.run(["bash", str(QUEUE), "ack", PEER, h2, "manual"], check=False, capture_output=True, text=True, env=env())
    check("ack manual 기록", ok.returncode == 0, ok.stderr)
    check("전파 확인 → 통과", gate(stop) == "", gate(stop))

    h4 = ship("rules/e.md", "feat: pid check")
    AGENTS.write_text(json.dumps([{"sessionId": SELF, "name": "[Harness] Manager"},
                                  {"sessionId": PEER, "name": "[exp] Manager", "pid": 4194303}]), encoding="utf-8")
    check("끝난 세션만 남으면 통과", gate(stop) == "")
    AGENTS.write_text(json.dumps([{"sessionId": SELF, "name": "[Harness] Manager"},
                                  {"sessionId": PEER, "name": "[exp] Manager", "pid": os.getpid()}]), encoding="utf-8")
    alive = gate(stop)
    check("살아 있는 세션이면 차단", '"block"' in alive and h4 in alive, alive)

    h5 = ship("rules/f.md", "feat: asleep check")
    asleep = QDIR / "asleep" / PEER
    asleep.parent.mkdir(parents=True, exist_ok=True)
    asleep.write_text(f"asleep\t{int(time.time())}\n", encoding="utf-8")
    check("asleep 세션만 남으면 통과", gate(stop) == "")
    asleep.write_text(f"asleep\t{int(time.time()) - 121}\n", encoding="utf-8")
    old = gate(stop)
    check("asleep 표지가 121초 전이면 차단", '"block"' in old and h5 in old, old)

    h3 = ship("skills/c.md", "feat: skill")
    via = gate({**stop, "last_assistant_message": "끝났습니다."}, script=GUARD)
    check("Stop 훅 스크립트를 거친 차단", '"block"' in via and h3 in via, via)

    AGENTS.write_text(json.dumps([{"sessionId": SELF, "name": "[Harness] Manager"}]), encoding="utf-8")
    check("다른 세션이 없으면 통과", gate(stop) == "")

    n0 = len(held())
    commit("intent/x.md", "docs: record only")
    r = enqueue()
    check("기록 경로(intent/)만 바뀐 커밋은 제외", len(held()) == n0 and r.returncode == 0 and "기록용 커밋" in r.stderr, r.stderr)
    h = commit_many(["rules/m.md", "intent/m.md"], "feat: mixed")
    enqueue()
    check("동작+기록이 섞인 커밋은 적힘", len(held()) == n0 + 1 and held()[-1]["hash"] == h)
    h = commit("settings.json", "feat: exact file")
    enqueue()
    check("파일 항목(settings.json)은 정확히 일치하면 적힘", len(held()) == n0 + 2 and held()[-1]["hash"] == h)
    commit("settings.json.bak", "chore: not exact")
    enqueue()
    commit("rules-extra/a.md", "chore: dir needs slash boundary")
    enqueue()
    check("접두만 같은 경로(settings.json.bak · rules-extra/)는 제외", len(held()) == n0 + 2)

    commit("newdir/q.md", "feat: unclassified top dir")
    r = enqueue()
    check("enqueue 끝의 분류 점검이 미분류 경로를 경고", r.returncode == 0 and "'newdir/'" in r.stderr, r.stderr)
    check("미분류 경로만 바뀐 커밋은 동작 아님 → 적지 않음", len(held()) == n0 + 2)
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

    commit("intent/y.md", "docs: record only, no list")
    h = held()[-1]["hash"]
    r = enqueue(PROPAGATE_PATHS=str(ROOT / "none.txt"))
    check("목록 파일이 없으면 기록용 커밋도 적힘 + 경고", len(held()) == n0 + 3 and held()[-1]["hash"] != h and "종전처럼" in r.stderr, r.stderr)
    empty_list = ROOT / "empty.txt"
    write_list(empty_list, [], ["intent/"])
    commit("intent/z.md", "docs: record only, empty behavior")
    enqueue(PROPAGATE_PATHS=str(empty_list))
    check("[behavior] 가 비면 기록용 커밋도 적힘", len(held()) == n0 + 4)

    n1 = len(held())
    git("commit", "-q", "--no-verify", "--allow-empty", "-m", "chore: 모든 세션에 보낼 문장")
    r = enqueue()
    check("빈 커밋은 적지 않음", len(held()) == n1 and "바뀐 파일이 없는" in r.stderr, r.stderr)
    enqueue(PROPAGATE_PATHS=str(ROOT / "none.txt"))
    check("목록이 없어도 빈 커밋은 적지 않음", len(held()) == n1)
    base = git("rev-parse", "--abbrev-ref", "HEAD")
    git("checkout", "-q", "-b", "side")
    commit("rules/side.md", "feat: side rule")
    git("checkout", "-q", base)
    commit("intent/main-side.md", "docs: main record")
    git("merge", "-q", "--no-ff", "--no-verify", "-m", "merge side", "side")
    h = git("rev-parse", "--short=9", "HEAD")
    enqueue()
    check("동작 경로가 바뀐 병합 커밋은 적힘", len(held()) == n1 + 1 and held()[-1]["hash"] == h, str(held()[-1:]))

    rows = held()
    oldest = time.strftime("%Y-%m-%d %H:%M", time.localtime(min(x["ts"] for x in rows)))
    r = queue("held")
    check("held: «건수<TAB>가장 오래된 시각» 만 출력", r.returncode == 0 and r.stdout == f"{len(rows)}\t{oldest}\n", repr(r.stdout) + r.stderr)

    n2 = len(pending())
    keep = commit("rules/v1.md", "feat: kept")
    enqueue()
    gone = commit("rules/v2.md", "feat: rewritten away")
    enqueue()
    git("reset", "-q", "--hard", "HEAD~1")
    r = queue("release")
    check("release: HEAD 의 조상이 아닌 최근 줄은 버리고 그다음 줄을 씀",
          r.returncode == 0 and len(pending()) == n2 + 1 and pending()[-1]["hash"] == keep and gone not in json.dumps(pending())
          and r.stdout.strip() == f"보류 {len(rows) + 2}건 → 대기 1줄({keep})", r.stdout + r.stderr)
    check("held: 비면 0", queue("held").stdout == "0\n")

    dangling = git("commit-tree", git("rev-parse", "HEAD^{tree}"), "-m", "feat: dangling")[:9]
    (QDIR / "held.jsonl").write_text(json.dumps({"ts": 1, "hash": dangling, "subject": "feat: dangling", "author": SELF}) + "\n", encoding="utf-8")
    r = queue("release")
    check("release: 쓸 줄이 없으면 대기에 적지 않고 알림 · 보류를 비움",
          r.returncode == 0 and "쓸 줄 없음" in r.stdout and len(pending()) == n2 + 1 and held() == [], r.stdout + r.stderr)

    (QDIR / "held.jsonl").write_text(json.dumps({"ts": 1, "hash": keep, "subject": "feat: kept", "author": SELF}) + "\n", encoding="utf-8")
    r = queue("release")
    check("release: 대기에 같은 해시가 있으면 더하지 않음 · 보류를 비움",
          r.returncode == 0 and "이미 있음" in r.stdout and len(pending()) == n2 + 1 and held() == [], r.stdout + r.stderr)

    target = ROOT / "elsewhere.jsonl"
    target.write_text(json.dumps({"ts": 1, "hash": keep, "subject": "x", "author": ""}) + "\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    (QDIR / "held.jsonl").unlink()
    (QDIR / "held.jsonl").symlink_to(target)
    commit("rules/link.md", "feat: link target")
    r = enqueue()
    check("링크인 보류 파일: enqueue 는 링크 너머에 쓰지 않음", r.returncode == 0 and target.read_text(encoding="utf-8") == before and "링크" in r.stderr, r.stderr)
    r = queue("release")
    check("링크인 보류 파일: release 는 읽지 않고 종료 1", r.returncode == 1 and len(pending()) == n2 + 1 and target.read_text(encoding="utf-8") == before, r.stdout + r.stderr)
    r = queue("held")
    check("링크인 보류 파일: held 는 읽지 않고 종료 1", r.returncode == 1 and r.stdout == "", r.stdout + r.stderr)
    (QDIR / "held.jsonl").unlink()

    print(f"\n실패 {len(FAILS)}건" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    sys.exit(rc)
