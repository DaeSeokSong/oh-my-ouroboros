"""띠 작업 줄 데이터: 이 Claude 세션이 띄운 Codex·Grok 작업의 모델·effort 와 현재 저장소의 학습 판.

세션 등록 파일에서 이 세션의 pid 를 찾고 그 자손만 본다.
Grok 은 grok 실행 파일의 인자 `-m`·`--reasoning-effort` 만 읽는다(bash 래퍼의 인자 글자는 제외).
Codex 는 자손 codex 프로세스가 연 rollout 파일의 마지막 turn_context 를 읽는다.
값은 ^[A-Za-z0-9._-]{1,40}$ 만 통과시킨다.
학습 판: 상태 파일에 실행 여부 필드가 없어 train_pid 의 시작 시각과 boot_id 가 모두 맞을 때만 실행 중으로 본다.
할 일: 엔진이 세션마다 ~/.claude/tasks/session-<세션 id 앞 8자리>/<번호>.json 에 두는 할 일의 상태 개수와
진행·남은 항목 제목. 띠가 접고 펴는 «할 일» 묶음을 그린다(엔진의 할 일 목록은 mod 가 다시 그릴 자리가 없어 ctrl+t 로 숨긴다).
정지 스위치·남은 자식 감지: `_cache/band/off` 파일이 있으면 ps 를 부르지 않는다(codex·grok 은 None, todos·train 은 파일 읽기라 그대로).
ps 자식은 Popen 으로 띄워 pid 를 `work_ps.inflight`(세션 공통 파일 하나)에 적고, 시작 시 그 pid 의 /proc/<pid>/comm 이 ps 면 ps 를 부르지 않는다.
세션끼리 기록이 겹치면 한 회차 codex·grok 표시가 빠질 뿐이다.
호출: python3 band_work_collect.py --session-id <uuid> --cwd <절대경로>
REF: knowledge/harness/code-history/scripts__band_work_collect.py.md
"""
import argparse
import json
import os
import pathlib
import re
import stat
import subprocess
import tempfile
import time

CACHE_DIR = pathlib.Path(os.environ.get("BAND_CACHE_DIR", os.path.expanduser("~/.claude/_cache/band")))   # NEVER: scripts/band_server_collect.py 의 규칙과 따로 바꾸지 않는다
SESS_DIR = pathlib.Path(os.environ.get("BAND_SESSIONS_DIR", os.path.expanduser("~/.claude/sessions")))
CODEX_SESSIONS = os.path.realpath(os.environ.get("BAND_CODEX_SESSIONS", os.path.expanduser("~/.codex/sessions")))
TASKS_DIR = pathlib.Path(os.environ.get("BAND_TASKS_DIR", os.path.expanduser("~/.claude/tasks")))
VAL = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
MAX_TASK_BYTES = 1 << 16
MAX_TASK_FILES = 500
MAX_TODO_ITEMS = 12
TODO_STATE = {"completed": "done", "in_progress": "doing", "pending": "open"}
# NEVER: mods/harness-mod/hooks/band/model.js 의 isStripped 와 따로 바꾸지 않는다(같은 집합이다, 시험이 대조).
_STRIP_RANGES = ((0x00, 0x1F), (0x7F, 0x9F), (0x2028, 0x202E), (0x2066, 0x2069), (0x200B, 0x200F), (0x2060, 0x2064), (0xFEFF, 0xFEFF), (0x061C, 0x061C),
                 (0x00AD, 0x00AD), (0x206A, 0x206F), (0xFE00, 0xFE0F), (0xE0000, 0xE007F), (0x3164, 0x3164))
CODEX_EXE = re.compile(r"^codex-(x86_64|aarch64)")
ENDED_WINDOW_S = 24 * 3600
MAX_STATE_BYTES = 1 << 20
LOG_KEYS = ("watcher_log", "train_log", "done_log")


def safe(v):
    return v if isinstance(v, str) and VAL.match(v) else None


def parse_ps(text):
    table = {}
    for line in text.splitlines():
        f = line.split(None, 2)
        if len(f) >= 2 and f[0].isdigit() and f[1].isdigit():
            table[int(f[0])] = (int(f[1]), f[2] if len(f) > 2 else "")
    return table


def descendants(table, root):
    kids = {}
    for pid, (ppid, _) in table.items():
        kids.setdefault(ppid, []).append(pid)
    out, stack = [], [root]
    while stack:
        for c in kids.get(stack.pop(), []):
            out.append(c)
            stack.append(c)
    return out


def _exe(args):
    return os.path.basename(args.split(" ", 1)[0]) if args else ""


def _opt(tokens, name):
    if name in tokens:
        i = tokens.index(name)
        if i + 1 < len(tokens):
            return safe(tokens[i + 1])
    return None


def find_grok(table, pids):
    out = []
    for pid in pids:
        args = table[pid][1]
        exe = _exe(args)
        if exe == "grok" or exe.startswith("grok-"):
            t = args.split()
            out.append({"model": _opt(t, "-m"), "effort": _opt(t, "--reasoning-effort")})
    return out


def codex_from_rollout(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    finally:
        os.close(fd)
    for line in reversed(lines):
        if '"turn_context"' in line:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            p = obj.get("payload") if isinstance(obj, dict) else None
            if not isinstance(p, dict):
                continue
            return {"model": safe(p.get("model")), "effort": safe(p.get("effort"))}
    return None


def rollout_path(target, root=None):
    real = os.path.realpath(target)
    root = root or CODEX_SESSIONS
    return real if real.startswith(root + os.sep) and os.path.basename(real).startswith("rollout-") else None


def find_codex(table, pids):
    out = []
    for pid in pids:
        tokens = table[pid][1].split()
        exe = os.path.basename(tokens[0]) if tokens else ""
        if exe != "codex" and not CODEX_EXE.match(exe):
            continue
        info = None
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                real = rollout_path(os.readlink(f"/proc/{pid}/fd/{fd}"))
                if real:
                    info = codex_from_rollout(real)
        except OSError:
            pass
        out.append(info or {"model": None, "effort": None})
    return out


def _start_of(pid):
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
        return stat.rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def ended_at(obj, state_mtime):
    times = []
    for key in LOG_KEYS:
        p = obj.get(key)
        if isinstance(p, str) and os.path.isabs(p):
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                times.append(st.st_mtime)
    return max(times) if times else state_mtime


def train_states(repo, boot_id, start_of=_start_of, now=None):
    now = now or time.time()
    repo = pathlib.Path(repo)
    files = sorted(set(repo.glob(".scratch/launch/launch-state-*.json")) | set(repo.glob(".scratch/*/launch/launch-state-*.json")))
    running, ended = [], []
    for f in files:
        try:
            st = f.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_STATE_BYTES:
                continue
            obj = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        name = safe(obj.get("name")) or safe(f.stem[len("launch-state-"):][:40]) or "?"
        pid = obj.get("train_pid")
        alive = isinstance(pid, int) and obj.get("boot_id") == boot_id and start_of(pid) == str(obj.get("train_start"))
        if alive:
            running.append(name)
        elif now - ended_at(obj, st.st_mtime) < ENDED_WINDOW_S:
            ended.append(name)
    return {"running": running, "ended": ended}


def strip_text(s):
    return "".join(c for c in s if not any(a <= ord(c) <= b for a, b in _STRIP_RANGES))


def todos(session_id, root=None):
    if not isinstance(session_id, str) or not re.match(r"^[0-9a-f]{8}-", session_id):
        return None
    folder = pathlib.Path(root or TASKS_DIR) / f"session-{session_id[:8]}"
    try:
        st = folder.lstat()
    except OSError:
        return None
    if not stat.S_ISDIR(st.st_mode):
        return None
    counts = {"done": 0, "doing": 0, "open": 0}
    items = []
    try:
        names = sorted((p for p in folder.iterdir() if re.match(r"^\d{1,6}\.json$", p.name)), key=lambda p: int(p.stem))[:MAX_TASK_FILES]
    except OSError:
        return None
    for p in names:
        try:
            fst = p.lstat()
            if not stat.S_ISREG(fst.st_mode) or fst.st_size > MAX_TASK_BYTES:
                continue
            obj = json.loads(p.read_text())
        except (OSError, ValueError, RecursionError):
            continue
        status = obj.get("status") if isinstance(obj, dict) else None
        state = TODO_STATE.get(status) if isinstance(status, str) else None
        if not state:
            continue
        counts[state] += 1
        subject = obj.get("subject")
        if state != "done" and isinstance(subject, str):
            items.append({"state": state, "subject": strip_text(subject)[:120]})
    # WHY: 진행 먼저 · 번호 순으로 세운 뒤 자른다(앞 번호의 남은 항목이 많아도 진행 항목이 빠지지 않게, qa 2026-10-23).
    items.sort(key=lambda x: 0 if x["state"] == "doing" else 1)
    return {**counts, "items": items[:MAX_TODO_ITEMS]}


def own_pid(session_id):
    for p in SESS_DIR.glob("*.json"):
        if not re.match(r"^\d+\.json$", p.name):
            continue
        try:
            st = p.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_STATE_BYTES:
                continue
            obj = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(obj, dict) and obj.get("sessionId") == session_id and isinstance(obj.get("pid"), int):
            return obj["pid"]
    return None


def git_root(cwd):
    cur = os.path.normpath(cwd)
    for _ in range(40):
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent
    return None


def _inflight_path():
    return CACHE_DIR / "work_ps.inflight"


def ps_stuck():
    try:
        with open(_inflight_path()) as f:
            rec = json.loads(f.read(4096))
        pid, comm = rec["pid"], rec["comm"]
        if not isinstance(pid, int) or isinstance(pid, bool) or comm != "ps":
            return False
        with open(f"/proc/{pid}/comm", "rb") as f:
            return f.read(32).decode("utf-8", "replace").strip() == comm
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return False


def _set_inflight(pid):
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, prefix="work_ps.inflight.")
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"pid": pid, "comm": "ps"}))
        os.replace(tmp, _inflight_path())
    except OSError:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _clear_inflight(pid):
    try:
        with open(_inflight_path()) as f:
            if json.loads(f.read(4096)).get("pid") == pid:
                os.unlink(_inflight_path())
    except (OSError, ValueError, AttributeError):
        pass


def run_ps():
    try:
        p = subprocess.Popen(["ps", "-eo", "pid=,ppid=,args="], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return None
    _set_inflight(p.pid)
    try:
        try:
            out, _ = p.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
            try:
                p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                return None
            _clear_inflight(p.pid)
            return None
        _clear_inflight(p.pid)
        return out
    finally:
        p.stdout.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--cwd", required=True)
    a = ap.parse_args()
    out = {"codex": None, "grok": None, "train": None, "todos": todos(a.session_id)}
    pid = own_pid(a.session_id)
    ps = None if os.path.lexists(CACHE_DIR / "off") or ps_stuck() else run_ps()
    if pid and ps:
        table = parse_ps(ps)
        kids = descendants(table, pid)
        out["codex"], out["grok"] = find_codex(table, kids), find_grok(table, kids)
    root = git_root(a.cwd) if os.path.isabs(a.cwd) else None
    if root:
        try:
            boot = pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            out["train"] = train_states(root, boot)
        except OSError:
            pass
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
