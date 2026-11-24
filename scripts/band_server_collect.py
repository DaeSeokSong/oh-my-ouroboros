"""띠(AbovePrompt) 서버 줄 캐시를 채운다(intent/2026-10-15-harness-mods.md).

서버당 파일 1개를 한 갱신자만 채운다. 잠금은 수집기가 직접 `fcntl.flock(LOCK_NB)` 로 잡는다.
캐시 폴더는 0700, 파일은 mkstemp(0600)+rename 이다.
쓰는 파일(캐시 폴더):
  server.attempt  잠금을 잡으면 가장 먼저 시각을 쓴다(mod 가 15초 안엔 다시 부르지 않는다).
  server.inflight run() 이 자식을 Popen 으로 띄워 pid 와 실행 파일 이름을 적고, 끝나면 지운다(타임아웃 뒤 kill 이 안 먹으면 남긴다).
  server.watched  와쳐를 본 러너 기억 {"boot_id", "pids": {"<pid>": starttime}}. 띠가 읽는 server.json 에는 pid 를 넣지 않는다.
`_cache/band/off` 파일이 있으면(`touch` 로 켜고 `rm` 으로 끈다) main 이 잠금·attempt·하위 프로세스 없이 곧바로 끝난다. 내용은 읽지 않는다.
세션 파일은 `숫자.json` 만 읽고 name·status·sessionId 만 옮긴다(같은 폴더의 *.key 는 비밀값).
호출: python3 -I band_server_collect.py   (mod 가 인자 배열로 부른다)
REF: knowledge/harness/code-history/scripts__band_server_collect.py.md
"""
import collections
import fcntl
import itertools
import json
import math
import os
import pathlib
import pickletools
import re
import stat
import subprocess
import tempfile
import time
import zipfile

CACHE_DIR = pathlib.Path(os.environ.get("BAND_CACHE_DIR", os.path.expanduser("~/.claude/_cache/band")))
SESS_DIR = pathlib.Path(os.environ.get("BAND_SESSIONS_DIR", os.path.expanduser("~/.claude/sessions")))
SESSION_FILE = re.compile(r"\d+\.json")   # NEVER: fullmatch 밖의 꼴로 쓰지 않는다($ 는 끝 줄바꿈 앞에서도 맞는다)
SID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# NEVER: 소스에 이 글자들(C0·C1 제어문자 + 줄/문단 구분(U+2028·2029) + 양방향 제어(U+202A~202E, U+2066~2069))을 직접 넣지 않는다.
BIDI = "".join(chr(c) for c in (0x2028, 0x2029, *range(0x202A, 0x202F), *range(0x2066, 0x206A)))
CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f" + BIDI + "]")
MAX_JSON_BYTES = 1 << 20
SYS_BLOCK = pathlib.Path("/sys/block")
PARTITION_OF = re.compile(r"(?:(nvme\d+n\d+|mmcblk\d+|loop\d+)p\d+|([a-z]+)\d+)")
MIN_DISK_BYTES = 2 << 30
MAX_DISKS = 8
KIND_ORDER = {"SSD": 0, "HDD": 1, "?": 2}
DF_ARGS = ["df", "-B1", "-l", "-P", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay", "-x", "efivarfs"]
# NEVER: 캐시에 경로·명령줄 원문을 쓰지 않는다(이름·최대 에폭·체크포인트 에폭/지표 값만 쓴다).
RUN_NAME = re.compile(r"memguard-([A-Za-z0-9._-]{1,60})-(\d{1,10})\.scope")
NAME_OK = re.compile(r"[A-Za-z0-9._-]{1,60}")      # NEVER: 아래 정규식을 fullmatch 또는 \Z 의 끝 고정 없이 쓰지 않는다
METRIC_OK = re.compile(r"[A-Za-z0-9_./-]{1,40}")
MAX_EPOCHS = re.compile(r"max_epochs=(\d{1,6})\Z")
CKPT_NAME = re.compile(r"epoch=(\d{1,6})(?!\d)(.*)\.ckpt\Z")
CKPT_PAIR = re.compile(r"-([^=-][^=]{0,39})=(-?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|inf|nan))", re.IGNORECASE)
LAST_CKPT = re.compile(r"last(-v\d+)?\.ckpt")
UUID_OK = re.compile(r"[A-Za-z0-9-]{1,64}")
FD_SKIP = ("/proc/", "/dev/", "/sys/")
# NEVER: 이 종류 위의 경로(fuse.* 는 전부)는 건드리지 않는다(끊긴 네트워크 FS 에서 stat·scandir 가 D 상태로 걸린다).
REMOTE_FS = frozenset({"nfs", "nfs4", "cifs", "smb3", "smbfs", "9p", "ceph", "glusterfs", "lustre", "gpfs", "afs"})
MAX_MOUNTS_BYTES = 1 << 20
MAX_PKL_BYTES = 8 << 20
PKL_STR_OPS = frozenset({"SHORT_BINUNICODE", "BINUNICODE", "UNICODE", "SHORT_BINSTRING", "BINSTRING"})
PKL_INT_OPS = frozenset({"BININT", "BININT1", "BININT2", "LONG1", "INT"})
PKL_MEMO_OPS = frozenset({"MEMOIZE", "BINPUT", "LONG_BINPUT", "PUT"})
MAX_CKPTS = 20
# REF: rules-lazy/background-task.md (band_progress.json 진행 파일 규약)
PROGRESS_FILE = "band_progress.json"
MAX_PROGRESS_BYTES = 4096
LAST_PTH = "last.pth"
WATCHER_SCRIPT = "train-watcher.sh"
MAX_PROCS = 4096
MAX_CMDLINE = 1 << 16
MAX_STATE_FILES = 128
MAX_STATE_BYTES = 1 << 16
MAX_ROOT_HOPS = 12
MAX_SCAN_ENTRIES = 8192
MAX_STATE_DEPTH = 3   # WHY: .scratch/<잡>/launch/<판>/launch-state-*.json 까지(2026-11-12 qa 실측: project-C 판)
# NEVER: 띠가 읽는 server.json 에 pid 를 넣지 않는다(러너 기억은 server.watched 에만 둔다).
WATCHED_FILE = "server.watched"
MAX_WATCHED = 256
MAX_WATCHED_BYTES = 1 << 16
# NEVER: jobs/<jobId>/state.json 에서 state·detail 말고 다른 키를 옮기지 않는다(나머지 키는 브리지 id·계정 uuid·intent).
JOBS_DIR = pathlib.Path(os.environ.get("BAND_JOBS_DIR", os.path.expanduser("~/.claude/jobs")))
JOB_ID = re.compile(r"[0-9a-f]{8}")
JOB_STATE = re.compile(r"[a-z_]{1,20}")
MAX_JOB_BYTES = 64 << 10
MAX_DETAIL = 120


INFLIGHT_COMMS = frozenset({"nvidia-smi", "free", "df"})


def set_inflight(pid, comm):
    try:
        write_atomic(CACHE_DIR / "server.inflight", {"pid": pid, "comm": comm})
    except OSError:
        pass


def clear_inflight():
    try:
        os.unlink(CACHE_DIR / "server.inflight")
    except OSError:
        pass


def inflight_stuck():
    # NEVER: cmdline·status 를 읽지 않는다(comm 파일은 태스크 이름뿐이라 D 상태 프로세스도 안 갇힌다).
    try:
        with open(CACHE_DIR / "server.inflight") as f:
            rec = json.loads(f.read(4096))
        pid, comm = rec["pid"], rec["comm"]
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return False
    # NEVER: INFLIGHT_COMMS 밖의 comm 을 받지 않는다(다른 살아 있는 프로세스(예: systemd)를 가리키는 기록이 수집을 영구히 멈추지 않게).
    if not isinstance(pid, int) or isinstance(pid, bool) or comm not in INFLIGHT_COMMS:
        return False
    return _read_proc(pid, "comm", 32).strip() == comm


def run(argv, timeout=3, env=None):
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    except OSError:
        return None
    set_inflight(p.pid, os.path.basename(argv[0])[:15])
    try:
        try:
            out, _ = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            try:
                p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                return None
            clear_inflight()
            return None
        clear_inflight()
        return out if p.returncode == 0 else None
    finally:
        p.stdout.close()


MIB = 1 << 20
NA = "[N/A]"


def parse_gpus(text, mem=None):
    out = []
    for line in (text or "").strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) != 4 or not all(x.isdigit() for x in parts[:2]):
            return None
        i, util = int(parts[0]), int(parts[1])
        if parts[2] == NA and parts[3] == NA:
            if not mem:
                return None
            out.append({"i": i, "util": util, "used": (mem["total"] - mem["avail"]) // MIB, "total": mem["total"] // MIB,
                        "unified": True})
            continue
        if not (parts[2].isdigit() and parts[3].isdigit()):
            return None
        out.append({"i": i, "util": util, "used": int(parts[2]), "total": int(parts[3])})
    return out or None


def parse_mem(text):
    for line in (text or "").splitlines():
        f = line.split()
        if f and f[0] == "Mem:" and len(f) >= 7:
            return {"total": int(f[1]), "avail": int(f[6])}
    return None


def parse_meminfo(text):
    found = {}
    for line in (text or "").splitlines():
        f = line.split()
        if len(f) >= 2 and f[0] in ("MemTotal:", "MemAvailable:") and f[1].isdigit():
            found[f[0]] = int(f[1]) * 1024
    if "MemTotal:" in found and "MemAvailable:" in found and found["MemTotal:"] > 0:
        return {"total": found["MemTotal:"], "avail": found["MemAvailable:"]}
    return None


def read_mem():
    # WHY: /proc/meminfo 를 먼저 읽는다(2026-10-16 실측: ko_KR 로케일에서 `free` 첫 열이 «메모리:» 라 `Mem:` 파싱이 비어 띠에 «조회 실패» 가 났다).
    try:
        with open("/proc/meminfo") as f:
            mem = parse_meminfo(f.read(1 << 16))
    except OSError:
        mem = None
    return mem or parse_mem(run(["free", "-b"], env={**os.environ, "LC_ALL": "C"}))


def parse_disk(text):
    lines = (text or "").strip().splitlines()
    if len(lines) < 2:
        return None
    f = lines[1].split()
    if len(f) < 6 or not (f[1].isdigit() and f[3].isdigit()):
        return None
    return {"total": int(f[1]), "avail": int(f[3])}


def clean(s, n=40):
    return CTRL.sub("", str(s))[:n]


def disk_kind(name, sys_block=SYS_BLOCK):
    m = PARTITION_OF.fullmatch(name)
    for cand in ((name, m.group(1) or m.group(2)) if m else (name,)):
        try:
            with open(sys_block / cand / "queue" / "rotational") as f:
                v = f.read(8).strip()
        except OSError:
            continue
        if v in ("0", "1"):
            return "HDD" if v == "1" else "SSD"
    return "?"


def parse_disks(text, sys_block=SYS_BLOCK):
    lines = (text or "").strip().splitlines()
    if len(lines) < 2:
        return None
    seen, out = set(), []
    for line in lines[1:]:
        f = line.split(None, 5)
        if len(f) < 6 or not f[0].startswith("/dev/") or not (f[1].isdigit() and f[3].isdigit()):
            continue
        total, avail = int(f[1]), int(f[3])
        name = clean(os.path.basename(f[0]), 24)
        if total < MIN_DISK_BYTES or not name or name in seen:
            continue
        seen.add(name)
        out.append({"dev": name, "kind": disk_kind(name, sys_block), "mount": clean(f[5], 40), "total": total, "avail": avail})
    out.sort(key=lambda d: (KIND_ORDER[d["kind"]], d["dev"]))
    return out[:MAX_DISKS]


def _alive(pid):
    return pathlib.Path(f"/proc/{pid}").exists()


def job_fields(obj):
    if not isinstance(obj, dict):
        return {"job_state": None, "job_detail": None}
    state, detail = obj.get("state"), obj.get("detail")
    state = state if isinstance(state, str) and JOB_STATE.fullmatch(state) else None
    detail = (clean(re.sub(r"[\r\n\t]+", " ", detail), MAX_DETAIL).strip() or None) if isinstance(detail, str) else None
    return {"job_state": state, "job_detail": detail}


def read_job_state(jobs_dir, job_id):
    none = {"job_state": None, "job_detail": None}
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        return none
    d = pathlib.Path(jobs_dir) / job_id
    try:
        if not stat.S_ISDIR(d.lstat().st_mode):
            return none
        fd = os.open(d / "state.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return none
            data = os.read(fd, MAX_JOB_BYTES + 1)
        finally:
            os.close(fd)
        if len(data) > MAX_JOB_BYTES:
            return none
        return job_fields(json.loads(data))
    except (OSError, ValueError, RecursionError):  # WHY: 깊게 중첩된 JSON 도 수집기를 멈추지 않게(2026-10-16 qa)
        return none


def read_sessions(d, alive=_alive, jobs_dir=None):
    out = []
    try:
        names = sorted(p.name for p in pathlib.Path(d).iterdir())
    except OSError:
        return None
    for name in names:
        if not SESSION_FILE.fullmatch(name):
            continue
        path = pathlib.Path(d) / name
        try:
            st = path.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_JSON_BYTES:
                continue
            obj = json.loads(path.read_text())
        except (OSError, ValueError, RecursionError):
            continue
        if not isinstance(obj, dict):
            continue
        sid, pid = str(obj.get("sessionId", "")), obj.get("pid")
        # WHY: spare=true(데몬 예비 세션, 입력 전)는 claude agents 화면처럼 숨긴다(2026-11-06 사용자 지적)
        if obj.get("spare") is True or not SID.fullmatch(sid) or not isinstance(pid, int) or not alive(pid):
            continue
        job = obj.get("jobId")
        out.append({"sid": sid, "name": clean(obj.get("name", "")), "status": clean(obj.get("status", ""), 12),
                    "job": job if isinstance(job, str) and JOB_ID.fullmatch(job) else None,
                    **read_job_state(JOBS_DIR if jobs_dir is None else jobs_dir, job)})
    return out


def _elapsed(pid):
    try:
        stat_text = pathlib.Path(f"/proc/{int(pid)}/stat").read_text()
        start = int(stat_text.rsplit(")", 1)[1].split()[19]) / os.sysconf("SC_CLK_TCK")
        return float(pathlib.Path("/proc/uptime").read_text().split()[0]) - start
    except (OSError, ValueError, IndexError):
        return 0.0


def nvidia_smi_pids():
    # NEVER: pgrep 자식을 띄우지 않는다(2026-10-26 실측: 멈춘 nvidia-smi 의 /proc 을 읽다 갇힌 pgrep 약 63개가 D 상태로 쌓였다).
    uid = os.getuid()
    try:
        names = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return []
    out = []
    for n in names:
        try:
            if os.stat(f"/proc/{n}").st_uid != uid:
                continue
        except OSError:
            continue
        if _read_proc(n, "comm", 32).strip() == "nvidia-smi":
            out.append(int(n))
    return out


LOOP_FLAG = re.compile(r"(?:-l(?:ms)?|--loop(?:-ms)?)(?:=\d+)?|-l(?:ms)?\d+")


def _is_loop_mode(pid):
    args = _read_proc(pid, "cmdline", MAX_CMDLINE).split("\0")[1:]
    if any(LOOP_FLAG.fullmatch(a) for a in args):
        return True
    return next((a for a in args if a and not a.startswith("-")), "") in ("dmon", "pmon")


def _is_d_state(pid):
    fields = _read_proc(pid, "stat", 4096).rsplit(")", 1)
    return len(fields) == 2 and fields[1].split()[:1] == ["D"]


def nvidia_smi_stuck(limit=10):
    # WHY: 반복 감시(-l·-lms·--loop·--loop-ms·dmon·pmon)는 빼고, D 상태면 cmdline 을 읽지 않고 곧바로 멈춤으로 본다
    # (사용자 결정 2026-10-28, 실험 스크립트의 -lms 500 감시가 띠를 지웠다).
    return any(_is_d_state(p) or (_elapsed(p) > limit and not _is_loop_mode(p)) for p in nvidia_smi_pids())


def previous_gpus(now, max_age=60):
    try:
        with open(CACHE_DIR / "server.json") as f:
            prev = json.loads(f.read(MAX_JSON_BYTES))
        gts = prev.get("gpus_ts", prev.get("ts"))
        if isinstance(prev["gpus"], list) and isinstance(gts, (int, float)) and 0 <= now - gts <= max_age:
            return prev["gpus"], gts
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    return None


def parse_compute_apps(text):
    out = []
    for line in (text or "").strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) == 2 and parts[0].isdigit() and UUID_OK.fullmatch(parts[1]):
            out.append((int(parts[0]), parts[1]))
    return out


def parse_gpu_uuids(text):
    out = {}
    for line in (text or "").strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) == 2 and parts[0].isdigit() and UUID_OK.fullmatch(parts[1]):
            out[parts[1]] = int(parts[0])
    return out


def run_name_from_cgroup(text):
    m = RUN_NAME.search(text or "")
    return m.group(1) if m else None


def runner_pid_from_cgroup(text):
    m = RUN_NAME.search(text or "")
    return int(m.group(2)) if m else None


def watcher_pids_from_cmdline(args):
    idx = next((i for i, a in enumerate(args) if os.path.basename(a) == WATCHER_SCRIPT), None)
    if idx is None:
        return []
    rest = args[idx + 1:]
    return [int(v) for a, v in itertools.pairwise(rest) if a == "--pid" and v.isdigit() and len(v) <= 10]


def read_watcher_pids():
    found, uid = set(), os.getuid()
    try:
        names = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return found
    seen = 0  # WHY: 상한은 이 사용자 프로세스 수에 건다(먼저 자르면 새 pid 의 와쳐를 놓쳐 거짓 «와쳐✗» 가 난다, 2026-10-16 qa)
    for n in names:
        try:
            if os.stat(f"/proc/{n}").st_uid != uid:
                continue
        except OSError:
            continue
        seen += 1
        if seen > MAX_PROCS:
            break
        found.update(watcher_pids_from_cmdline(_read_proc(n, "cmdline", MAX_CMDLINE).split("\0")))
    return found


def script_name_from_cmdline(args):
    for a in args:
        if a.endswith(".py"):
            b = os.path.basename(a)[:60]
            if NAME_OK.fullmatch(b):
                return b
    return None


def max_epochs_from_cmdline(args):
    found = None
    for a in args:
        m = MAX_EPOCHS.search(a)
        if m:
            found = int(m.group(1))
    return found


def parse_ckpt_names(names):
    found = []
    for n in names:
        m = CKPT_NAME.search(n)
        if not m:
            continue
        name = val = None
        for pair in CKPT_PAIR.finditer(m.group(2)):
            if pair.group(1).lower() in ("step", "epoch") or not METRIC_OK.fullmatch(pair.group(1)):
                continue
            v = float(pair.group(2))
            if math.isfinite(v):
                name, val = pair.group(1), v
            break
        found.append((int(m.group(1)), name, val))
    counts = collections.Counter(n for _, n, _ in found if n)
    metric = max(counts, key=lambda k: (counts[k], k)) if counts else None
    by_epoch = {}
    for e, n, v in found:
        v = v if n == metric else None
        if e not in by_epoch or (by_epoch[e] is None and v is not None):
            by_epoch[e] = v
    ckpts = [{"epoch": e, "value": by_epoch[e]} for e in sorted(by_epoch)[-MAX_CKPTS:]]
    return metric, ckpts, any(LAST_CKPT.fullmatch(n) for n in names)


def parse_mounts(text):
    out = []
    for line in (text or "").splitlines():
        f = line.split()
        if len(f) >= 3:
            out.append((re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), f[1]), f[2]))
    return sorted(out, key=lambda x: -len(x[0]))


def read_mounts():
    try:
        with open("/proc/self/mounts", "rb") as f:
            return parse_mounts(f.read(MAX_MOUNTS_BYTES).decode("utf-8", "replace"))
    except OSError:
        return None


def is_local_path(path, mounts):
    if mounts is None:
        return False
    for mp, fs in mounts:
        if mp == "/" or path == mp or path.startswith(mp.rstrip("/") + "/"):
            return fs not in REMOTE_FS and not fs.startswith("fuse.")
    return True


def _read_proc(pid, name, limit):
    try:
        with open(f"/proc/{pid}/{name}", "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def _fd_dirs(pid, mounts):
    base = f"/proc/{pid}/fd"
    try:
        fds = os.listdir(base)[:256]
    except OSError:
        return []
    dirs = set()
    for fd in fds:
        try:
            target = os.readlink(f"{base}/{fd}")
            if not target.startswith("/") or target.startswith(FD_SKIP) or not is_local_path(target, mounts):
                continue   # NEVER: 종류를 보기 전에 stat 하지 않는다(readlink 는 커널 안에서 끝나지만 stat 은 원격 FS 에서 멈출 수 있다)
            if not stat.S_ISREG(os.stat(f"{base}/{fd}").st_mode):
                continue
        except OSError:
            continue
        dirs.add(os.path.dirname(target))
    return sorted(dirs)


def _local_real(path, mounts, hops=0):
    # WHY: is_local_path 는 문자열만 보므로, 경로 중간의 심볼릭 링크가 NFS 를 가리키면(예: run/checkpoints → /nfs/ckpt) 그 뒤 stat·open 이
    # 끊긴 NFS 에서 D 상태로 멈출 수 있다(qa 2026-10-22).
    if hops > 16 or not path.startswith("/"):
        return None
    parts = [p for p in path.split("/") if p not in ("", ".")]
    cur = "/"
    for i, p in enumerate(parts):
        if p == "..":
            cur = os.path.dirname(cur) or "/"
            continue
        nxt = os.path.join(cur, p)
        if not is_local_path(nxt, mounts):
            return None
        try:
            st = os.lstat(nxt)
        except OSError:
            return None
        if stat.S_ISLNK(st.st_mode):
            try:
                t = os.readlink(nxt)
            except OSError:
                return None
            base = t if t.startswith("/") else os.path.join(cur, t)
            return _local_real("/".join([base, *parts[i + 1:]]), mounts, hops + 1)
        cur = nxt
    return cur


def _arg_dirs(args, mounts):
    # WHY: 로그를 여러 판이 같이 쓰는 상위 폴더에 두는 판은 «연 파일의 폴더» 만으로 판 폴더를 못 찾는다
    # (2026-10-22 실측: 명령줄에 판 전용 폴더의 spec.json 경로만 있었다).
    dirs = set()
    for a in args[:64]:
        if not a.startswith("/") or a.startswith(FD_SKIP) or len(a) > 4096 or not is_local_path(a, mounts):
            continue
        real = _local_real(a, mounts)
        if real is None or real.startswith(FD_SKIP):
            continue
        try:
            if stat.S_ISREG(os.lstat(real).st_mode):
                dirs.add(os.path.dirname(real))
        except OSError:
            continue
    return sorted(dirs)


def read_progress(dirs, mounts):
    # REF: rules-lazy/background-task.md (band_progress.json 진행 파일 규약, 이 함수가 정본으로 지목된다)
    for d in dirs:
        for c in (d, os.path.join(d, "checkpoints")):
            # WHY: 남은 위험(security 2026-10-22, 허용): 검사와 open 사이에 같은 사용자가 폴더 조각을 NFS 링크로 바꾸면 open 이 멈출 수 있다.
            rc = _local_real(c, mounts)
            if rc is None:
                continue
            p = os.path.join(rc, PROGRESS_FILE)
            if not is_local_path(p, mounts):
                continue
            try:
                fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            except OSError:
                continue
            try:
                st = os.fstat(fd)
                # WHY: 일반 파일이고 이 사용자 것만 받는다(누구나 쓰는 폴더가 인자 폴더가 될 때 남이 심은 파일 거부, security 2026-10-22)
                if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
                    continue
                raw = os.read(fd, MAX_PROGRESS_BYTES + 1)
            except OSError:
                continue
            finally:
                os.close(fd)
            if len(raw) > MAX_PROGRESS_BYTES or raw.lstrip()[:1] != b"{":
                continue
            try:
                obj = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                # WHY: 깊게 중첩된 JSON 은 RecursionError(RuntimeError 계열)를 낸다. 잡지 않으면 수집기 전체가 죽어 모든 세션의 띠가 멈춘다(security 2026-10-22).
                continue
            if not isinstance(obj, dict):
                continue
            done, mx = obj.get("done"), obj.get("max")
            if not all(isinstance(v, int) and not isinstance(v, bool) for v in (done, mx)):
                continue
            if 1 <= mx <= 100000 and 0 <= done <= mx:
                last = obj.get("last")
                return done, mx, last if isinstance(last, bool) else None
    return None


def has_last_pth(dirs, mounts):
    # NEVER: last.pth 를 열지 않는다(lstat 로 일반 파일인지만 본다, 수백 MB 체크포인트를 읽지 않는다).
    for d in dirs:
        for c in (d, os.path.join(d, "checkpoints")):
            rc = _local_real(c, mounts)
            if rc is None:
                continue
            p = os.path.join(rc, LAST_PTH)
            if not is_local_path(p, mounts):
                continue
            try:
                st = os.lstat(p)
                # WHY: 이 사용자 것인 일반 파일만(공용 폴더에 남이 둔 last.pth 로 «last» 가 붙지 않게, qa 2026-10-22)
                if stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid():
                    return True
            except OSError:
                continue
    return False


def _ckpt_folder(pid, mounts):
    for d in _fd_dirs(pid, mounts):
        for c in (d, os.path.join(d, "checkpoints")):
            if not is_local_path(c, mounts) or os.path.islink(c):
                continue
            try:
                with os.scandir(c) as it:
                    names = [e.name for _, e in zip(range(500), it) if e.name.endswith(".ckpt") and e.is_file(follow_symlinks=False)]
            except OSError:
                continue
            if names:
                return c, names
    return None, []


def pick_last_ckpt(folder, names):
    if folder is None:
        return None
    if "last.ckpt" in names:
        return os.path.join(folder, "last.ckpt")
    best, best_m = None, -1.0
    for n in names:
        if n != "last.ckpt" and LAST_CKPT.fullmatch(n):
            try:
                m = os.stat(os.path.join(folder, n)).st_mtime
            except OSError:
                continue
            if m > best_m:
                best, best_m = n, m
    return os.path.join(folder, best) if best else None


def done_epochs_from_ckpt(path):
    # NEVER: pickle 을 load 하지 않는다(pickletools.genops 로 opcode 만 훑어 코드가 돌지 않게 한다).
    try:
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.endswith("/data.pkl") or n == "data.pkl"), None)
            info = z.getinfo(name) if name else None
            if info is None or info.file_size > MAX_PKL_BYTES or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                return None
            with z.open(info) as f:
                data = f.read(MAX_PKL_BYTES + 1)
        if len(data) > MAX_PKL_BYTES:
            return None
        want = False
        for op, arg, _pos in pickletools.genops(data):
            if want:
                if op.name in PKL_INT_OPS and isinstance(arg, int) and not isinstance(arg, bool):
                    return arg + 1 if 0 <= arg < 100000 else None
                if op.name not in PKL_MEMO_OPS:
                    return None
            elif op.name in PKL_STR_OPS and arg == "epoch":
                want = True
    except Exception:  # noqa: BLE001
        return None
    return None


def read_run(pid, mounts):
    args = _read_proc(pid, "cmdline", 1 << 16).split("\0")
    cgroup = _read_proc(pid, "cgroup", 4096)
    name = run_name_from_cgroup(cgroup) or script_name_from_cmdline(args) or "?"
    folder, names = _ckpt_folder(pid, mounts)
    metric, ckpts, last = parse_ckpt_names(names)
    path = pick_last_ckpt(folder, names)
    max_epochs = max_epochs_from_cmdline(args)
    done = done_epochs_from_ckpt(path) if path else None
    run_dirs = _fd_dirs(pid, mounts) + _arg_dirs(args, mounts)
    prog = read_progress(run_dirs, mounts)
    if prog:
        done, max_epochs = prog[0], prog[1]
    if prog and prog[2] is not None:
        last = prog[2]
    elif not last:
        last = has_last_pth(run_dirs, mounts)
    return {"name": name, "max_epochs": max_epochs, "done": done,
            "metric": metric, "ckpts": ckpts, "last": last, "runner_pid": runner_pid_from_cgroup(cgroup)}


def project_dirs_of(pid, mounts):
    try:
        cur = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return []
    if not os.path.isabs(cur) or not is_local_path(cur, mounts):
        return []
    dirs = [cur]
    for _ in range(MAX_ROOT_HOPS):
        if os.path.lexists(os.path.join(cur, ".git")):
            return dirs
        parent = os.path.dirname(cur)
        if parent == cur or not is_local_path(parent, mounts):
            break
        cur = parent
        dirs.append(cur)
    return dirs[:1]


def _state_candidates(scratch, mounts):
    out, queue, seen, scanned = [], collections.deque([(scratch, 0)]), set(), 0
    while queue:
        d, depth = queue.popleft()
        real = os.path.realpath(d)
        if real in seen or not is_local_path(real, mounts):
            continue   # WHY: 심볼릭 링크가 가리키는 실제 경로도 로컬이어야 한다(security 2026-11-12): 끊긴 NFS 에서 scandir 이 걸리지 않게
        seen.add(real)
        try:
            with os.scandir(real) as it:
                for e in it:
                    scanned += 1
                    if scanned > MAX_SCAN_ENTRIES:
                        return out
                    if e.name.startswith("launch-state-") and e.name.endswith(".json"):
                        st = e.stat(follow_symlinks=False)
                        if stat.S_ISREG(st.st_mode) and st.st_size <= MAX_STATE_BYTES:
                            out.append((st.st_mtime, os.path.join(real, e.name)))
                    elif depth < MAX_STATE_DEPTH and e.is_dir():
                        queue.append((os.path.join(real, e.name), depth + 1))
        except OSError:
            continue
    return out


def read_json_file(path, limit=MAX_STATE_BYTES):
    # WHY: The except is deliberately broad (security 2026-11-12): json.loads raises RecursionError on deeply nested input and
    # must only cost this one file, never the whole collector.
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        with open(path, "rb") as f:
            return json.loads(f.read(limit + 1).decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


def launch_state_runners(dirs, boot_id, mounts, boot_start=None):
    # WHY: `--state` may point anywhere (2026-11-12 qa: 4 of 6 live runs did not use `.scratch/launch/`), so every directory
    # from the runner cwd up to the git root is tried at depth 0..3 under `.scratch`.
    cands = []
    for d in dirs:
        cands += _state_candidates(os.path.join(d, ".scratch"), mounts)
    if boot_start is not None:
        cands = [c for c in cands if c[0] >= boot_start]
    runners = set()
    for _, path in sorted(cands, reverse=True)[:MAX_STATE_FILES]:
        obj = read_json_file(path)
        if isinstance(obj, dict) and boot_id and obj.get("boot_id") == boot_id:
            scope = obj.get("train_scope")
            pid = runner_pid_from_cgroup(scope if isinstance(scope, str) else None)
            if pid is not None:
                runners.add(pid)
    return runners


def _starttime(pid):
    try:
        return int(_read_proc(pid, "stat", 4096).rsplit(")", 1)[1].split()[19])
    except (ValueError, IndexError):
        return None


def load_watched(path, boot_id):
    # WHY: no process-side marker identifies a launch-set run, so every pid ever seen under a live train-watcher.sh is
    # remembered with its starttime (2026-11-12 qa).
    obj = read_json_file(path, MAX_WATCHED_BYTES)
    out = {}
    if isinstance(obj, dict) and boot_id and obj.get("boot_id") == boot_id and isinstance(obj.get("pids"), dict):
        for k, v in list(obj["pids"].items())[:MAX_WATCHED]:
            if k.isdigit() and len(k) <= 10 and isinstance(v, int) and _starttime(int(k)) == v:
                out[int(k)] = v
    return out


def save_watched(path, boot_id, entries):
    try:
        write_atomic(pathlib.Path(path), {"boot_id": boot_id, "pids": {str(k): v for k, v in sorted(entries.items())[:MAX_WATCHED]}})
    except (OSError, ValueError):
        pass


def read_boot_id():
    try:
        with open("/proc/sys/kernel/random/boot_id", "rb") as f:
            return f.read(128).decode("utf-8", "replace").strip() or None
    except OSError:
        return None


def read_boot_start():
    try:
        return time.time() - float(pathlib.Path("/proc/uptime").read_text().split()[0]) - 5
    except (OSError, ValueError, IndexError):
        return None


def watcher_state(rp, watchers, launched):
    # WHY: False is narrowed to launch-set runs (2026-11-12 report from another session): memguard-wrapped runs that
    # were not started through launch-set.sh (e.g. eval jobs) have a runner pid but never get a watcher.
    if rp is None:
        return None
    if rp in watchers:
        return True
    return False if launched(rp) else None


def collect_train():
    apps = run(["nvidia-smi", "--query-compute-apps=pid,gpu_uuid", "--format=csv,noheader"])
    uuids = run(["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"])
    if apps is None or uuids is None:
        return None
    idx, runs, merged, mounts = parse_gpu_uuids(uuids), {}, {}, read_mounts()
    watchers = read_watcher_pids()
    boot_id, by_dirs = read_boot_id(), {}
    wpath = CACHE_DIR / WATCHED_FILE
    loaded = load_watched(wpath, boot_id)
    remembered = dict(loaded)
    for w in watchers:
        st = _starttime(w)
        if st is not None:
            remembered[w] = st
    if boot_id and remembered != loaded:
        save_watched(wpath, boot_id, remembered)

    def launched(rp):
        if rp in remembered:
            return True
        dirs = tuple(project_dirs_of(rp, mounts))
        if not dirs:
            return False
        if dirs not in by_dirs:
            by_dirs[dirs] = launch_state_runners(dirs, boot_id, mounts, read_boot_start())
        return rp in by_dirs[dirs]

    for pid, uuid in parse_compute_apps(apps):
        if uuid not in idx:
            continue
        if pid not in runs:
            runs[pid] = read_run(pid, mounts)
            rp = runs[pid].pop("runner_pid", None)   # NEVER: 캐시에 러너 pid 를 쓰지 않는다(와쳐 여부 true/false/null 만 쓴다)
            runs[pid]["watcher"] = watcher_state(rp, watchers, launched)
        r = runs[pid]
        cur = merged.setdefault((idx[uuid], r["name"]), {"gpu": idx[uuid], **r})
        for k in ("max_epochs", "done", "metric", "watcher"):
            cur[k] = cur[k] if cur[k] is not None else r[k]
        if not cur["ckpts"]:
            cur["ckpts"] = r["ckpts"]
        # WHY: 개정 19: last.pth 판정은 체크포인트 이름 목록과 따로 참이 될 수 있다. DDP 처럼 같은 판 프로세스가 여럿이면 한쪽이라도
        # last 를 봤으면 «있음» 으로 남긴다(뒤 프로세스의 False 가 앞의 True 를 덮지 않게, qa 2026-10-22).
        cur["last"] = bool(cur["last"]) or bool(r["last"])
    return [merged[k] for k in sorted(merged)]


def previous_train(now, max_age=60):
    try:
        with open(CACHE_DIR / "server.json") as f:
            prev = json.loads(f.read(MAX_JSON_BYTES))
        tts = prev["train_ts"]
        if isinstance(prev["train"], list) and isinstance(tts, (int, float)) and 0 <= now - tts <= max_age:
            return prev["train"], tts
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    return None


def collect():
    now = time.time()
    if inflight_stuck():   # NEVER: 앞 회차 자식이 아직 살아 있으면(D 상태) 하위 프로세스를 띄우지 않는다(쌓임을 1개로 묶는다)
        pg, pt = previous_gpus(now), previous_train(now)
        return {"ts": now, "gpus": pg[0] if pg else None, "gpus_ts": pg[1] if pg else now,
                "train": pt[0] if pt else None, "train_ts": pt[1] if pt else now,
                "mem": None, "disk": None, "disks": None, "sessions": read_sessions(SESS_DIR), "stuck": True}
    mem = read_mem()
    stuck = nvidia_smi_stuck()
    gpus = None if stuck else parse_gpus(run(
        ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]), mem)
    gpus_ts = now
    train = None if gpus is None else collect_train()   # NEVER: GPU 조회가 실패·시간 초과면 학습 조회를 하지 않는다(멈춘 드라이버에 또 묻지 않는다)
    train_ts = now
    prev = previous_gpus(now) if gpus is None else None
    if prev:
        gpus, gpus_ts = prev
    prev = previous_train(now) if train is None else None
    if prev:
        train, train_ts = prev
    return {
        "ts": now,
        "gpus": gpus,
        "gpus_ts": gpus_ts,
        "train": train,
        "train_ts": train_ts,
        "mem": mem,
        "disk": parse_disk(run(["df", "-B1", "-l", "-P", "/"])),
        "disks": parse_disks(run(DF_ARGS)),
        "sessions": read_sessions(SESS_DIR),
    }


def write_atomic(path, obj):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(obj, ensure_ascii=False))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    if os.path.lexists(CACHE_DIR / "off"):
        return
    CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(CACHE_DIR, 0o700)
    lock = os.open(CACHE_DIR / "server.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    write_atomic(CACHE_DIR / "server.attempt", {"ts": time.time()})
    write_atomic(CACHE_DIR / "server.json", collect())


if __name__ == "__main__":
    main()
