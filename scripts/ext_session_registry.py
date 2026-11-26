"""ext_session_registry.py: Grok · Codex 세션 대장 관리(등록 · 조회 · 맞춤 찾기 · 7일 미사용 삭제).

역할: `~/.claude/_usage/ext-sessions.md`(서버 전용, gitignored)에 Grok · Codex 세션을 한 줄씩 적어 두고,
  같은 맥락의 세션을 다시 찾게 하며, SessionStart(`scripts/exchange-prune.sh` 끝)에서 오래 쓰지 않은 세션을 지운다.
설계 근거: intent/2026-11-26-ext-review-gate-sessions.md · docs/superpowers/plans/2026-11-26-ext-review-gate-sessions.md §3,
  규칙 정본 rules-lazy/codex-model-gate.md §2.3.
사용법:
  python3 -I ext_session_registry.py add --tool {grok,codex} --id X --project P --topic T [--intent PATH] [--plan PATH]
  python3 -I ext_session_registry.py list [--tool T]
  python3 -I ext_session_registry.py match --tool T --project P --topic T [--intent PATH] [--plan PATH]
  python3 -I ext_session_registry.py prune [--days N] [--dry-run]
계약:
  · 대장은 `## Grok` · `## Codex` 두 절의 GFM 표(세션 · 프로젝트 · 주제 · intent · plan · 만든 날 · 마지막 사용), 칸 속 `|` 는 `\\|`.
  · 마지막 사용 = 세션 파일 수정 시각 중 가장 늦은 것. 파일이 하나도 없으면 대장 칸 값.
    Grok: ~/grok-exchange/.sessions/<이름>.id · <이름>.run(안쪽까지) · ~/.grok/sessions/<.run 경로 인코딩>(안쪽까지).
      <이름>.lock 은 마지막 사용 계산에도 삭제에도 쓰지 않는다(잠금 확인에만 연다).
    Codex: ~/.codex/sessions · ~/.codex/archived_sessions 아래 이름에 UUID 가 든 rollout-*.jsonl.
  · prune 은 대장에 있는 세션만 본다. 기한(기본 7일, EXT_SESSION_DAYS 양의 정수)보다 오래되면 Grok 은 파일을 지우고
    Codex 는 `codex delete --force <UUID>`(PATH 의 codex)를 부른다. 디스크에 이미 없으면 행만 지운다. 실패하면 행을 남긴다.
  · 삭제 기록: ~/.claude/_audit/ext-session-prune.log 에 `시각<TAB>도구<TAB>세션<TAB>마지막 사용<TAB>결과`.
  · 시험은 HOME 을 임시 폴더로, PATH 앞에 가짜 codex 를 둔다(시험 전용 환경변수는 두지 않는다).
"""
import argparse
import fcntl
import functools
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

TOOLS = ("grok", "codex")
TITLES = {"grok": "Grok", "codex": "Codex"}
COLS = ("세션", "프로젝트", "주제", "intent", "plan", "만든 날", "마지막 사용")
GROK_NAME = re.compile(r"[A-Za-z0-9_.-]+")
UUID = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
TS_FMT = "%Y-%m-%d %H:%M"
# WHY: SessionStart 훅 timeout 이 20초다(settings.json 의 exchange-prune 훅). 남는 8초는 앞선 교환 폴더 정리와 파이썬 기동
#   몫으로 둔 여유이고 잰 값이 아니다. 12초가 지나면 새 Codex 삭제를 시작하지 않고 남은 것은 다음 SessionStart 에서 지운다.
DEADLINE_SEC = 12
# WHY: codex 한 건이 멈춰도 훅 20초를 넘기지 않도록 한 건의 상한을 둔다. 실제 제한은 min(이 값, DEADLINE_SEC 까지 남은 시간)
#   (최소 1초)이라 마지막 호출도 DEADLINE_SEC 언저리에서 끊긴다. 이 값이 DEADLINE_SEC 보다 작아 한 건이 예산 전부를 쓰지 못한다.
CODEX_TIMEOUT_SEC = 10

HOME = Path.home()
REGISTRY = HOME / ".claude/_usage/ext-sessions.md"
LOG = HOME / ".claude/_audit/ext-session-prune.log"
GROK_SESSIONS = HOME / "grok-exchange/.sessions"
GROK_STORE = HOME / ".grok/sessions"
CODEX_DIRS = (HOME / ".codex/sessions", HOME / ".codex/archived_sessions")


def valid_id(tool, sid):
    return bool((GROK_NAME if tool == "grok" else UUID).fullmatch(sid))


def esc(text):
    return " ".join(str(text).split()).replace("|", "\\|")


def parse_row(line):
    cells = re.split(r"(?<!\\)\|", line.strip())[1:-1]
    return [c.strip().replace("\\|", "|") for c in cells]


def read_rows():
    rows = {t: [] for t in TOOLS}
    if not REGISTRY.exists():
        return rows
    tool = None
    for no, line in enumerate(REGISTRY.read_text(encoding="utf-8").splitlines(), 1):
        head = line.strip()
        if head.startswith("## "):
            tool = {v: k for k, v in TITLES.items()}.get(head[3:].strip())
            continue
        if tool is None or not head.startswith("|"):
            continue
        cells = parse_row(head)
        if len(cells) != len(COLS):
            print(f"ext-session-registry: 대장 {no}번째 줄의 칸이 {len(cells)}개라 건너뜀(다음 쓰기에서 사라짐)",
                  file=sys.stderr)
            continue
        if cells[0] == COLS[0] or set(cells[0]) <= {"-", ":"}:
            continue
        # WHY: rollout 파일 이름은 소문자 UUID 라 대장에 손으로 적은 대문자 행이면 prune 이 파일을 못 찾고
        #   «gone» 으로 행만 지운다(2026-11-26 reviewer 지적). add 의 소문자화와 같게 읽을 때도 맞춘다.
        if tool == "codex" and UUID.fullmatch(cells[0]):
            cells[0] = cells[0].lower()
        rows[tool].append(dict(zip(COLS, cells)))
    return rows


def write_rows(rows):
    out = ["# 외부 모델 세션 대장", "",
           "> scripts/ext_session_registry.py 가 관리한다. 규칙: rules-lazy/codex-model-gate.md §2.3", ""]
    for tool in TOOLS:
        out += [f"## {TITLES[tool]}", "", "| " + " | ".join(COLS) + " |", "|" + "---|" * len(COLS)]
        out += ["| " + " | ".join(esc(r[c]) for c in COLS) + " |" for r in rows[tool]]
        out.append("")
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_name(f".{REGISTRY.name}.tmp.{os.getpid()}")
    tmp.write_text("\n".join(out), encoding="utf-8")
    os.replace(tmp, REGISTRY)


def locked():
    if REGISTRY.is_symlink():
        sys.exit(f"거부: 대장이 심볼릭 링크입니다: {REGISTRY}")
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(REGISTRY.with_name(REGISTRY.name + ".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def newest_mtime(path):
    try:
        best = os.lstat(path).st_mtime
    except FileNotFoundError:
        return 0.0
    if os.path.isdir(path) and not os.path.islink(path):
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                try:
                    best = max(best, os.lstat(os.path.join(root, name)).st_mtime)
                except OSError:
                    pass
    return best


def grok_targets(name):
    run_dir = f"{GROK_SESSIONS}/{name}.run"
    encs = {urllib.parse.quote(run_dir, safe=""), run_dir.replace("/", "%2F")}
    # WHY: <이름>.lock 은 넣지 않는다. 래퍼(grok-ask.sh)의 flock 은 inode 에 걸려, 래퍼가 옛 inode 에서 기다리는 사이
    #   파일을 지우면 다음 래퍼는 새 inode 를 잠가 같은 .run 에서 두 호출이 동시에 돈다(2026-11-26 reviewer 지적).
    #   열기만 해서 mtime 이 바뀌지 않으니 마지막 사용 계산에도 쓸모가 없다.
    # WHY: .id 를 맨 뒤에 둔다. 앞에서 지우다 실패하면 .id 가 남아 래퍼가 «.run 없음» 으로 exit 75 거절하고
    #   조용히 새 세션을 열지 않는다(2026-11-26 reviewer 지적).
    paths = [Path(run_dir)] + [GROK_STORE / enc for enc in sorted(encs)] + [GROK_SESSIONS / f"{name}.id"]
    return [p for p in paths if os.path.lexists(p)]


def codex_targets(uuid):
    found = []
    for d in CODEX_DIRS:
        if d.is_dir() and not d.is_symlink():
            found += [p for p in d.rglob(f"rollout-*{uuid}.jsonl") if p.is_file() and not p.is_symlink()]
    return found


def targets(tool, sid):
    return grok_targets(sid) if tool == "grok" else codex_targets(sid)


def last_used(tool, row):
    paths = targets(tool, row["세션"])
    if paths:
        return max(newest_mtime(p) for p in paths), True
    try:
        return datetime.strptime(row["마지막 사용"], TS_FMT).timestamp(), False
    except ValueError:
        return 0.0, False


def fmt(ts):
    return datetime.fromtimestamp(ts).strftime(TS_FMT)


def safe_grok_path(path):
    # NEVER: 링크이거나 두 세션 뿌리의 바로 아래가 아닌 경로는 지우지 않는다(plan §3 안전 항).
    if path.is_symlink():
        return False
    parent = os.path.realpath(path.parent)
    return parent in (os.path.realpath(GROK_SESSIONS), os.path.realpath(GROK_STORE)) and not os.path.islink(path.parent)


def delete_grok(name):
    lock = GROK_SESSIONS / f"{name}.lock"
    if lock.is_symlink():
        return "refused"
    # WHY: 부분 삭제 뒤 폴더 mtime 이 갱신돼 재시도가 늦어질 수 있음(2026-11-26 reviewer 가설, 미실측).
    fd = None
    if lock.exists():
        fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return "busy"
    try:
        paths = grok_targets(name)
        if not all(safe_grok_path(p) for p in paths):
            return "refused"
        for p in paths:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        return "deleted"
    finally:
        if fd is not None:
            os.close(fd)


@functools.cache
def codex_bin():
    path = shutil.which("codex")
    if not path:
        print("ext-session-registry: codex 가 PATH 에 없어 Codex 세션 정리가 멈춥니다(행은 남김)", file=sys.stderr)
    return path


def delete_codex(uuid, remaining):
    codex = codex_bin()
    if not codex:
        return "failed"
    try:
        subprocess.run([codex, "delete", "--force", uuid], check=False, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, errors="replace", timeout=max(1, min(CODEX_TIMEOUT_SEC, remaining)))
    except subprocess.TimeoutExpired:
        pass
    # WHY: 부모 세션 삭제가 딸린 세션을 먼저 지우면 codex 가 «failed to delete session» 으로 끝난다
    #   (2026-11-26 일괄 삭제 67건, .scratch/9d9904f7/ext-cleanup/purge-1126-095235.log). 파일이 사라졌으면 성공이다.
    #   종료 코드가 0 이어도 파일이 남았으면 실패로 보고 행을 남긴다(2026-11-26 reviewer 지적).
    return "failed" if codex_targets(uuid) else "deleted"


def days_default():
    v = os.environ.get("EXT_SESSION_DAYS", "")
    return int(v) if re.fullmatch(r"[1-9][0-9]*", v) else 7


def positive_int(v):
    if not re.fullmatch(r"[1-9][0-9]*", v):
        raise argparse.ArgumentTypeError("양의 정수만 받습니다")
    return int(v)


def cmd_add(a):
    if a.tool == "codex":
        a.id = a.id.lower()
    if not valid_id(a.tool, a.id):
        sys.exit(f"거부: {a.tool} 세션 형식이 아닙니다(Grok 은 [A-Za-z0-9_.-], Codex 는 UUID): {a.id}")
    fd = locked()
    try:
        rows = read_rows()
        now = fmt(time.time())
        row = next((r for r in rows[a.tool] if r["세션"] == a.id), None)
        if row is None:
            row = {"세션": a.id, "만든 날": now}
            rows[a.tool].append(row)
        row.update({"프로젝트": a.project, "주제": a.topic, "intent": a.intent or row.get("intent", ""),
                    "plan": a.plan or row.get("plan", ""), "마지막 사용": now})
        write_rows(rows)
    finally:
        os.close(fd)
    print(f"등록: {a.tool}\t{a.id}")


def cmd_list(a):
    rows = read_rows()
    for tool in TOOLS if a.tool is None else (a.tool,):
        for r in rows[tool]:
            ts, _ = last_used(tool, r)
            print("\t".join([tool, r["세션"], fmt(ts), r["프로젝트"], r["주제"], r["intent"], r["plan"]]))


def words(text):
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 1}


def cmd_match(a):
    want_docs = {os.path.normpath(p) for p in (a.intent, a.plan) if p}
    want_words = words(a.topic)
    hits = []
    for r in read_rows()[a.tool]:
        if not valid_id(a.tool, r["세션"]) or not targets(a.tool, r["세션"]):
            continue
        # WHY: .run 이 없고 .id 만 남은 Grok 세션(삭제가 중간에 실패한 것)은 래퍼가 exit 75 로 거절하므로 후보로 올리지 않는다(2026-11-26 qa 지적).
        if a.tool == "grok" and not (GROK_SESSIONS / f"{r['세션']}.run").exists():
            continue
        docs ={os.path.normpath(r[k]) for k in ("intent", "plan") if r[k]}
        overlap = len(want_words & words(r["주제"])) if r["프로젝트"] == a.project else 0
        score = (100 if want_docs & docs else 0) + overlap
        if score:
            hits.append((score, last_used(a.tool, r)[0], r))
    for score, ts, r in sorted(hits, key=lambda h: (-h[0], -h[1])):
        print("\t".join([str(score), r["세션"], fmt(ts), r["주제"], r["intent"], r["plan"]]))


def cmd_prune(a):
    if not REGISTRY.exists():
        return
    cutoff = time.time() - a.days * 86400
    start = time.monotonic()
    fd = None if a.dry_run else locked()
    try:
        rows = read_rows()
        changed = False
        log_ok = True
        for tool in TOOLS:
            keep = []
            for r in rows[tool]:
                sid = r["세션"]
                if not valid_id(tool, sid):
                    print(f"ext-session-registry: 형식이 맞지 않아 건너뜀: {tool} {sid}", file=sys.stderr)
                    keep.append(r)
                    continue
                ts = 0.0
                # WHY: 한 행의 권한 오류 · 경합 삭제가 prune 전체를 멈추면 앞서 지운 행이 대장에 남는다(2026-11-26 reviewer 차단 지적).
                try:
                    ts, on_disk = last_used(tool, r)
                    if ts >= cutoff:
                        if on_disk and r["마지막 사용"] != fmt(ts):
                            r["마지막 사용"] = fmt(ts)
                            changed = True
                        keep.append(r)
                        continue
                    if a.dry_run:
                        print(f"[dry-run] {tool}\t{sid}\t{fmt(ts)}\t{'삭제' if on_disk else '행만 제거'}")
                        keep.append(r)
                        continue
                    if not on_disk:
                        result = "gone"
                    elif tool == "grok":
                        result = delete_grok(sid)
                        if result == "refused":
                            print(f"ext-session-registry: grok {sid} 삭제 거부(링크이거나 두 세션 뿌리 밖 경로, 행은 남김)",
                                  file=sys.stderr)
                    else:
                        remaining = DEADLINE_SEC - (time.monotonic() - start)
                        result = delete_codex(sid, remaining) if remaining > 0 else "deferred"
                except OSError as e:
                    print(f"ext-session-registry: {tool} {sid} 처리 실패(행은 남김): {' '.join(str(e).split())}",
                          file=sys.stderr)
                    result = "failed"
                if result in ("deleted", "gone"):
                    changed = True
                else:
                    keep.append(r)
                if result != "deferred" and not a.dry_run and log_ok:
                    # WHY: 기록 실패로 prune 이 멈추면 이미 지운 세션의 행이 대장에 남는다(2026-11-26 reviewer 지적).
                    try:
                        LOG.parent.mkdir(parents=True, exist_ok=True)
                        with LOG.open("a", encoding="utf-8") as f:
                            f.write("\t".join([fmt(time.time()), tool, sid, fmt(ts), result]) + "\n")
                    except OSError as e:
                        print(f"ext-session-registry: 삭제 기록을 쓰지 못함(정리는 계속): {' '.join(str(e).split())}",
                              file=sys.stderr)
                        log_ok = False
            rows[tool] = keep
        if changed and not a.dry_run:
            write_rows(rows)
    finally:
        if fd is not None:
            os.close(fd)


def main():
    p = argparse.ArgumentParser(description="Grok · Codex 세션 대장")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("add", "match"):
        s = sub.add_parser(name)
        s.add_argument("--tool", choices=TOOLS, required=True)
        if name == "add":
            s.add_argument("--id", required=True)
        s.add_argument("--project", required=True)
        s.add_argument("--topic", required=True)
        s.add_argument("--intent", default="")
        s.add_argument("--plan", default="")
    sub.add_parser("list").add_argument("--tool", choices=TOOLS)
    s = sub.add_parser("prune")
    s.add_argument("--days", type=positive_int, default=days_default())
    s.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    {"add": cmd_add, "list": cmd_list, "match": cmd_match, "prune": cmd_prune}[a.cmd](a)


if __name__ == "__main__":
    main()
