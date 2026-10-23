"""띠(AbovePrompt) 서버 줄 캐시를 채운다(2026-10-15, intent/2026-10-15-harness-mods.md 개정 5·6-3).

왜 캐시 1개인가: 세션마다 nvidia-smi·free·df 를 따로 돌리면 세션 수만큼 부하가 늘고, 끊긴 NFS 에서
df 가 D 상태로 쌓인다(검수 researcher 7). 그래서 서버당 파일 1개를 한 갱신자만 채운다. 잠금은 수집기가
직접 `fcntl.flock(LOCK_NB)` 로 잡는다(바깥 `flock -n` 은 캐시 폴더가 아직 없으면 잠금 파일을 못 열어
첫 실행이 영구 실패한다). 잠금을 잡으면 가장 먼저 `server.attempt` 에 시각을 쓰고(mod 가 15초 안엔 다시
부르지 않는다), 10초 넘게 도는 nvidia-smi 가 있으면(멈춘 드라이버, D 상태 누적) GPU·학습 조회를 건너뛰고, 건너뛰거나 실패하면 60초 안의 이전 gpus·train 을 이어 쓴다.
학습 판(개정 8): GPU 위 프로세스의 /proc 에서 판 이름(cgroup memguard 범위)·max_epochs·체크포인트 파일 이름만 읽어 train 에 담는다.
진행 파일(개정 18, 2026-10-22): 판 폴더(연 파일의 폴더 · 명령줄 절대 경로 파일 인자의 폴더)에 band_progress.json 이 있으면 그 done·max 를 앞세운다.
last 칸(개정 19): 진행 파일의 선택 키 last(bool) → 없으면 last.ckpt 이름 또는 판 폴더의 last.pth.
와쳐·세션 작업(개정 11): 판마다 watcher(true/false/null)를, 세션마다 jobs/<jobId>/state.json 의 state·detail 두 값만 job_state·job_detail 로 담는다(나머지 키는 버린다).
df 는 로컬 파일시스템(`-l`)만 본다. 루트 `/` 한 줄은 disk(접힌 띠용)이고, `/dev/` 장치 행마다 disks(장치 이름·SSD/HDD 종류·마운트·총량·여유, 개정 14)를 더 모은다. 세션 파일은 `숫자.json` 만 읽고 name·status·sessionId 만
옮긴다(같은 폴더의 *.key 는 비밀값, 검수 security 6). 화면 문자열은 제어문자·양방향 제어를 지운다.
캐시 폴더는 0700, 파일은 mkstemp(0600)+rename 이다(검수 security 2).
호출: python3 -I band_server_collect.py   (mod 가 인자 배열로 부른다)
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
SESSION_FILE = re.compile(r"\d+\.json")   # fullmatch 로만 쓴다($ 는 끝 줄바꿈 앞에서도 맞는다)
SID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# C0·C1 제어문자 + 줄/문단 구분(U+2028·2029) + 양방향 제어(U+202A~202E, U+2066~2069). 소스에 글자를 직접 넣지 않는다.
BIDI = "".join(chr(c) for c in (0x2028, 0x2029, *range(0x202A, 0x202F), *range(0x2066, 0x206A)))
CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f" + BIDI + "]")
MAX_JSON_BYTES = 1 << 20
# 디스크 장치별 목록(개정 14): 종류는 /sys/block/<디스크>/queue/rotational 로 가른다. 2 GiB 미만 파티션은 뺀다.
SYS_BLOCK = pathlib.Path("/sys/block")
PARTITION_OF = re.compile(r"(?:(nvme\d+n\d+|mmcblk\d+|loop\d+)p\d+|([a-z]+)\d+)")   # sda2 -> sda(그룹 2), nvme0n1p2 -> nvme0n1(그룹 1)
MIN_DISK_BYTES = 2 << 30
MAX_DISKS = 8
KIND_ORDER = {"SSD": 0, "HDD": 1, "?": 2}
DF_ARGS = ["df", "-B1", "-l", "-P", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay", "-x", "efivarfs"]
# 학습 판(개정 8): 캐시에는 이름·최대 에폭·체크포인트 에폭/지표 값만 쓴다. 경로·명령줄 원문은 쓰지 않는다.
RUN_NAME = re.compile(r"memguard-([A-Za-z0-9._-]{1,60})-(\d{1,10})\.scope")
NAME_OK = re.compile(r"[A-Za-z0-9._-]{1,60}")      # 아래 정규식은 모두 fullmatch 또는 \Z 로 끝을 고정한다
METRIC_OK = re.compile(r"[A-Za-z0-9_./-]{1,40}")
MAX_EPOCHS = re.compile(r"max_epochs=(\d{1,6})\Z")
CKPT_NAME = re.compile(r"epoch=(\d{1,6})(?!\d)(.*)\.ckpt\Z")
CKPT_PAIR = re.compile(r"-([^=-][^=]{0,39})=(-?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|inf|nan))", re.IGNORECASE)
LAST_CKPT = re.compile(r"last(-v\d+)?\.ckpt")
UUID_OK = re.compile(r"[A-Za-z0-9-]{1,64}")
FD_SKIP = ("/proc/", "/dev/", "/sys/")
# 끊긴 네트워크 FS 에서 stat·scandir 가 D 상태로 걸리지 않게, 이 종류 위의 경로는 건드리지 않는다(fuse.* 는 전부).
REMOTE_FS = frozenset({"nfs", "nfs4", "cifs", "smb3", "smbfs", "9p", "ceph", "glusterfs", "lustre", "gpfs", "afs"})
MAX_MOUNTS_BYTES = 1 << 20
MAX_PKL_BYTES = 8 << 20   # last.ckpt 안 data.pkl 상한(실측 수십 KB)
PKL_STR_OPS = frozenset({"SHORT_BINUNICODE", "BINUNICODE", "UNICODE", "SHORT_BINSTRING", "BINSTRING"})
PKL_INT_OPS = frozenset({"BININT", "BININT1", "BININT2", "LONG1", "INT"})
PKL_MEMO_OPS = frozenset({"MEMOIZE", "BINPUT", "LONG_BINPUT", "PUT"})
MAX_CKPTS = 20
# 진행 파일 규약(개정 18): 판 전용 폴더의 band_progress.json {"done": 끝낸 에폭 수, "max": 최대 에폭 수}. 4 KiB 상한.
PROGRESS_FILE = "band_progress.json"
MAX_PROGRESS_BYTES = 4096
LAST_PTH = "last.pth"   # 개정 19: detectron2 DetectionCheckpointer 의 재개용 파일 이름
# 와쳐(개정 11): launch-set 판의 러너 pid(cgroup memguard 범위의 끝 숫자)가 train-watcher.sh 의 --pid 인자에 있으면 와쳐가 살아 있다.
WATCHER_SCRIPT = "train-watcher.sh"
MAX_PROCS = 4096
MAX_CMDLINE = 1 << 16
# 세션 작업(개정 11): jobs/<jobId>/state.json 에서 state·detail 두 키만 꺼낸다(나머지 키는 브리지 id·계정 uuid·intent 라 읽고 버린다).
JOBS_DIR = pathlib.Path(os.environ.get("BAND_JOBS_DIR", os.path.expanduser("~/.claude/jobs")))
JOB_ID = re.compile(r"[0-9a-f]{8}")
JOB_STATE = re.compile(r"[a-z_]{1,20}")
MAX_JOB_BYTES = 64 << 10
MAX_DETAIL = 120


def run(argv, timeout=3):
    """Run argv and return stdout, or None on failure/timeout."""
    try:
        p = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def parse_gpus(text):
    """Parse nvidia-smi csv (index,util,used,total) into dicts, or None on garbage."""
    out = []
    for line in (text or "").strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) != 4 or not all(x.isdigit() for x in parts):
            return None
        i, util, used, total = map(int, parts)
        out.append({"i": i, "util": util, "used": used, "total": total})
    return out or None


def parse_mem(text):
    """Parse `free -b` into total/avail bytes."""
    for line in (text or "").splitlines():
        f = line.split()
        if f and f[0] == "Mem:" and len(f) >= 7:
            return {"total": int(f[1]), "avail": int(f[6])}
    return None


def parse_disk(text):
    """Parse `df -B1 -P` into total/avail bytes."""
    lines = (text or "").strip().splitlines()
    if len(lines) < 2:
        return None
    f = lines[1].split()
    if len(f) < 6 or not (f[1].isdigit() and f[3].isdigit()):
        return None
    return {"total": int(f[1]), "avail": int(f[3])}


def clean(s, n=40):
    """Strip control and bidi-control characters and truncate for display."""
    return CTRL.sub("", str(s))[:n]


def disk_kind(name, sys_block=SYS_BLOCK):
    """Return "HDD"/"SSD"/"?" from /sys/block/<disk>/queue/rotational (partition sda2 -> sda, nvme0n1p2 -> nvme0n1)."""
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
    """Parse local `df -B1 -P` rows whose device is under /dev/ into [{dev, kind, mount, total, avail}] (개정 14).

    2 GiB 미만(/boot/efi 류)과 같은 장치의 중복 마운트는 뺀다. 정렬은 SSD -> HDD -> ?, 같은 종류는 dev 이름순, 최대 MAX_DISKS 장치.
    df 가 아예 실패했으면 None, 읽을 장치가 없으면 빈 목록이다."""
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
    """Return True if /proc/<pid> exists."""
    return pathlib.Path(f"/proc/{pid}").exists()


def job_fields(obj):
    """Pick only state (^[a-z_]{1,20}$) and detail (control chars removed, 120 chars) from a job state.json object."""
    if not isinstance(obj, dict):
        return {"job_state": None, "job_detail": None}
    state, detail = obj.get("state"), obj.get("detail")
    state = state if isinstance(state, str) and JOB_STATE.fullmatch(state) else None
    detail = (clean(re.sub(r"[\r\n\t]+", " ", detail), MAX_DETAIL).strip() or None) if isinstance(detail, str) else None
    return {"job_state": state, "job_detail": detail}


def read_job_state(jobs_dir, job_id):
    """Read jobs/<job_id>/state.json (no symlinks, regular file, <=64KB) and return job_fields; unreadable -> all None."""
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
    except (OSError, ValueError, RecursionError):  # 깊게 중첩된 JSON 도 수집기를 멈추지 않게(2026-10-16 qa)
        return none


def read_sessions(d, alive=_alive, jobs_dir=None):
    """Read live session registrations (sid, name, status, and the job's state/detail only) from numeric .json files."""
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
        if not SID.fullmatch(sid) or not isinstance(pid, int) or not alive(pid):
            continue
        job = obj.get("jobId")
        out.append({"sid": sid, "name": clean(obj.get("name", "")), "status": clean(obj.get("status", ""), 12),
                    # 잡 id(8자리 16진)만: 띠의 세션 «제거» 버튼이 `claude rm <잡 id>` 에 쓴다(개정 20). 형식이 아니면 null.
                    "job": job if isinstance(job, str) and JOB_ID.fullmatch(job) else None,
                    **read_job_state(JOBS_DIR if jobs_dir is None else jobs_dir, job)})
    return out


def _elapsed(pid):
    """Seconds since pid started (from /proc/<pid>/stat starttime), or 0.0 if unreadable."""
    try:
        stat_text = pathlib.Path(f"/proc/{int(pid)}/stat").read_text()
        start = int(stat_text.rsplit(")", 1)[1].split()[19]) / os.sysconf("SC_CLK_TCK")
        return float(pathlib.Path("/proc/uptime").read_text().split()[0]) - start
    except (OSError, ValueError, IndexError):
        return 0.0


def nvidia_smi_stuck(limit=10):
    """Return True if this user has an nvidia-smi running longer than limit seconds (hung driver)."""
    out = run(["pgrep", "-u", str(os.getuid()), "-x", "nvidia-smi"])
    return any(_elapsed(p) > limit for p in (out or "").split() if p.isdigit())


def previous_gpus(now, max_age=60):
    """Return (gpus, gpus_ts) from the last cache if the gpus themselves are within max_age seconds, else None."""
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
    """Parse `nvidia-smi --query-compute-apps=pid,gpu_uuid` csv into (pid, uuid) pairs; garbage lines are skipped."""
    out = []
    for line in (text or "").strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) == 2 and parts[0].isdigit() and UUID_OK.fullmatch(parts[1]):
            out.append((int(parts[0]), parts[1]))
    return out


def parse_gpu_uuids(text):
    """Parse `nvidia-smi --query-gpu=index,uuid` csv into {uuid: index}; garbage lines are skipped."""
    out = {}
    for line in (text or "").strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) == 2 and parts[0].isdigit() and UUID_OK.fullmatch(parts[1]):
            out[parts[1]] = int(parts[0])
    return out


def run_name_from_cgroup(text):
    """Return the run name from a memguard-<name>-<pid>.scope cgroup line, or None."""
    m = RUN_NAME.search(text or "")
    return m.group(1) if m else None


def runner_pid_from_cgroup(text):
    """Return the runner pid from a memguard-<name>-<pid>.scope cgroup line, or None."""
    m = RUN_NAME.search(text or "")
    return int(m.group(2)) if m else None


def watcher_pids_from_cmdline(args):
    """Return the numeric `--pid N` values of a train-watcher.sh command line (args after the script), else []."""
    idx = next((i for i, a in enumerate(args) if os.path.basename(a) == WATCHER_SCRIPT), None)
    if idx is None:
        return []
    rest = args[idx + 1:]
    return [int(v) for a, v in itertools.pairwise(rest) if a == "--pid" and v.isdigit() and len(v) <= 10]


def read_watcher_pids():
    """Scan this user's /proc once (<=4096 processes) and return the set of pids that live train-watcher.sh processes watch."""
    found, uid = set(), os.getuid()
    try:
        names = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return found
    seen = 0  # 상한은 이 사용자 프로세스 수에 건다(먼저 자르면 새 pid 의 와쳐를 놓쳐 거짓 «와쳐✗» 가 난다, 2026-10-16 qa)
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
    """Return the basename of the first *.py argument (same charset, 60 chars), or None."""
    for a in args:
        if a.endswith(".py"):
            b = os.path.basename(a)[:60]
            if NAME_OK.fullmatch(b):
                return b
    return None


def max_epochs_from_cmdline(args):
    """Return the last max_epochs=N argument value, or None."""
    found = None
    for a in args:
        m = MAX_EPOCHS.search(a)
        if m:
            found = int(m.group(1))
    return found


def parse_ckpt_names(names):
    """Parse checkpoint file names into (metric, ckpts[{epoch,value}], last); keeps the 20 highest epochs."""
    found = []  # (epoch, metric name or None, value or None)
    for n in names:
        m = CKPT_NAME.search(n)
        if not m:
            continue
        name = val = None
        for pair in CKPT_PAIR.finditer(m.group(2)):   # Lightning 기본 `{epoch}-{step}` 의 step·epoch 쌍은 지표가 아니다
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
    """Parse /proc/self/mounts into [(mountpoint, fstype)], longest mountpoint first."""
    out = []
    for line in (text or "").splitlines():
        f = line.split()
        if len(f) >= 3:
            out.append((re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), f[1]), f[2]))
    return sorted(out, key=lambda x: -len(x[0]))


def read_mounts():
    """Read /proc/self/mounts once (size-capped), or None if unreadable."""
    try:
        with open("/proc/self/mounts", "rb") as f:
            return parse_mounts(f.read(MAX_MOUNTS_BYTES).decode("utf-8", "replace"))
    except OSError:
        return None


def is_local_path(path, mounts):
    """True if path's filesystem (longest mountpoint prefix) is not a network/fuse one; unknown mounts -> False."""
    if mounts is None:
        return False
    for mp, fs in mounts:
        if mp == "/" or path == mp or path.startswith(mp.rstrip("/") + "/"):
            return fs not in REMOTE_FS and not fs.startswith("fuse.")
    return True


def _read_proc(pid, name, limit):
    """Read at most limit bytes of /proc/<pid>/<name> as text, or '' if unreadable."""
    try:
        with open(f"/proc/{pid}/{name}", "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def _fd_dirs(pid, mounts):
    """Sorted local folders of pid's open regular files (at most 256 fds looked at)."""
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
                continue   # readlink 는 커널 안에서 끝나지만 stat 은 원격 FS 에서 멈출 수 있어 종류를 먼저 본다
            if not stat.S_ISREG(os.stat(f"{base}/{fd}").st_mode):
                continue
        except OSError:
            continue
        dirs.add(os.path.dirname(target))
    return sorted(dirs)


def _local_real(path, mounts, hops=0):
    """Resolve an absolute path one component at a time, staying on local filesystems; None if any step leaves them.

    is_local_path 는 문자열만 보므로, 경로 중간의 심볼릭 링크가 NFS 를 가리키면(예: run/checkpoints → /nfs/ckpt) 그 뒤 stat·open 이
    끊긴 NFS 에서 D 상태로 멈출 수 있다(qa 2026-10-22). 그래서 조각마다 «로컬인가» 를 먼저 보고 lstat 하며, 링크를 만나면 readlink
    결과를 다시 처음부터 같은 방식으로 푼다(16회 상한). 돌려주는 경로는 모든 조각이 링크 아닌 로컬 항목이다."""
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
    """Folders of absolute local regular-file arguments (e.g. a run's spec.json), first 64 args only.

    진행 파일 규약(개정 18): 로그를 여러 판이 같이 쓰는 상위 폴더에 두는 판은 «연 파일의 폴더» 만으로 판 폴더를 못 찾는다
    (2026-10-22 실측: 명령줄에 판 전용 폴더의 spec.json 경로만 있었다). 그래서 명령줄의 절대 경로 파일 인자의
    폴더도 본다. 경로 문자열로 원격 FS 를 먼저 거르고(stat 이 끊긴 NFS 에서 멈추지 않게), 심볼릭 링크는 따르지 않는다."""
    dirs = set()
    for a in args[:64]:
        if not a.startswith("/") or a.startswith(FD_SKIP) or len(a) > 4096 or not is_local_path(a, mounts):
            continue
        real = _local_real(a, mounts)   # 경로 중간의 링크도 로컬 안에서만 따라간다(원격으로 넘어가면 버린다)
        if real is None or real.startswith(FD_SKIP):
            continue
        try:
            if stat.S_ISREG(os.lstat(real).st_mode):
                dirs.add(os.path.dirname(real))
        except OSError:
            continue
    return sorted(dirs)


def read_progress(dirs, mounts):
    """(done, max, last) from the first valid band_progress.json in dirs (or their checkpoints/), else None.

    last(개정 19, 2026-10-22 사용자 결정 «둘 다»): 선택 키 "last" 가 참·거짓(bool)이면 그 값, 없거나 bool 이 아니면 None(이름 판정으로 넘김).

    규약(개정 18, 2026-10-22 사용자 결정 «진행 파일 규약»): 학습 코드가 판 전용 폴더에 {"done": 끝낸 에폭 수, "max": 최대 에폭 수}
    를 쓴다. Lightning 이 아닌 판(자체 프레임워크·detectron2)도 띠에 «9/13에폭» 이 보이게 하려는 것이다. 다른 판이 쓴 파일을
    읽을 수 있어 신뢰하지 않는다: 로컬 경로만, 심볼릭 링크·FIFO 거부(O_NOFOLLOW·O_NONBLOCK 후 일반 파일 확인), 4 KiB 상한,
    정수(불 제외) 0 <= done <= max, 1 <= max <= 100000 만 받는다. 어긋나면 그 파일은 없는 것으로 본다."""
    for d in dirs:
        for c in (d, os.path.join(d, "checkpoints")):
            # 폴더 경로의 링크(예: checkpoints → NFS)는 로컬 안에서만 푼다. 파일 자체 링크는 O_NOFOLLOW 가 막는다.
            # 남은 위험(security 2026-10-22, 허용): 검사와 open 사이에 같은 사용자가 폴더 조각을 NFS 링크로 바꾸면 open 이 멈출 수 있다.
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
                # 일반 파일이고 이 사용자 것만 받는다(누구나 쓰는 폴더가 인자 폴더가 될 때 남이 심은 파일 거부, security 2026-10-22)
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
                # 깊게 중첩된 JSON 은 RecursionError(RuntimeError 계열)를 낸다. 잡지 않으면 수집기 전체가 죽어 모든 세션의 띠가 멈춘다(security 2026-10-22).
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
    """True if a run folder in dirs (or its checkpoints/) holds a regular last.pth (detectron2 DetectionCheckpointer).

    개정 19(2026-10-22 사용자 결정 «둘 다»): 진행 파일에 last 키가 없을 때 last.ckpt 이름 판정에 더해 last.pth 도 «last 있음» 으로 본다.
    파일은 열지 않고 lstat 로 일반 파일인지만 본다(수백 MB 체크포인트를 읽지 않는다). 폴더 경로는 _local_real 로 로컬 안에서만 푼다."""
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
                # 이 사용자 것인 일반 파일만(공용 폴더에 남이 둔 last.pth 로 «last» 가 붙지 않게, qa 2026-10-22)
                if stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid():
                    return True
            except OSError:
                continue
    return False


def _ckpt_folder(pid, mounts):
    """(folder, names of *.ckpt files) of the first local folder (or its checkpoints/) holding one of pid's open regular files."""
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
    """Path of last.ckpt, else the newest-mtime last-v<N>.ckpt in folder (already checked local), else None."""
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
    """Completed epochs (saved 'epoch' + 1) from a Lightning ckpt zip, or None. The pickle is only walked with
    pickletools.genops (opcode listing), never loaded, so no code runs; size/compression are bounded first."""
    try:
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.endswith("/data.pkl") or n == "data.pkl"), None)
            info = z.getinfo(name) if name else None
            if info is None or info.file_size > MAX_PKL_BYTES or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                return None
            with z.open(info) as f:
                data = f.read(MAX_PKL_BYTES + 1)   # 헤더가 거짓이어도 이 이상은 풀지 않는다
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
    except Exception:  # noqa: BLE001  손상된 pickle 은 무엇이든 «모름»(None)으로 본다 — 실행은 하지 않고 opcode 만 훑는다
        return None
    return None


def read_run(pid, mounts):
    """Read one training process (name, max/done epochs, ckpt info) from /proc; unknown fields stay None/[]."""
    args = _read_proc(pid, "cmdline", 1 << 16).split("\0")
    cgroup = _read_proc(pid, "cgroup", 4096)
    name = run_name_from_cgroup(cgroup) or script_name_from_cmdline(args) or "?"
    folder, names = _ckpt_folder(pid, mounts)
    metric, ckpts, last = parse_ckpt_names(names)
    path = pick_last_ckpt(folder, names)
    max_epochs = max_epochs_from_cmdline(args)
    done = done_epochs_from_ckpt(path) if path else None
    # 진행 파일(개정 18)이 있으면 그 값을 앞세운다: 학습 코드가 직접 밝힌 값이라 명령줄·체크포인트 추정보다 정확하다.
    run_dirs = _fd_dirs(pid, mounts) + _arg_dirs(args, mounts)
    prog = read_progress(run_dirs, mounts)
    if prog:
        done, max_epochs = prog[0], prog[1]
    # last 칸(개정 19): 진행 파일의 last(bool)가 있으면 그 값, 없으면 last.ckpt 이름 또는 판 폴더의 last.pth.
    if prog and prog[2] is not None:
        last = prog[2]
    elif not last:
        last = has_last_pth(run_dirs, mounts)
    return {"name": name, "max_epochs": max_epochs, "done": done,
            "metric": metric, "ckpts": ckpts, "last": last, "runner_pid": runner_pid_from_cgroup(cgroup)}


def collect_train():
    """List running training runs per GPU (merged by gpu+name), or None if nvidia-smi could not be queried."""
    apps = run(["nvidia-smi", "--query-compute-apps=pid,gpu_uuid", "--format=csv,noheader"])
    uuids = run(["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"])
    if apps is None or uuids is None:
        return None
    idx, runs, merged, mounts = parse_gpu_uuids(uuids), {}, {}, read_mounts()   # 마운트 표는 수집 1회당 한 번만 읽는다
    watchers = read_watcher_pids()                                              # /proc 훑기도 수집 1회당 한 번
    for pid, uuid in parse_compute_apps(apps):
        if uuid not in idx:
            continue
        if pid not in runs:
            runs[pid] = read_run(pid, mounts)
            rp = runs[pid].pop("runner_pid", None)   # 캐시에는 러너 pid 를 쓰지 않고 와쳐 여부(true/false/null)만 쓴다
            runs[pid]["watcher"] = None if rp is None else rp in watchers
        r = runs[pid]
        cur = merged.setdefault((idx[uuid], r["name"]), {"gpu": idx[uuid], **r})
        for k in ("max_epochs", "done", "metric", "watcher"):
            cur[k] = cur[k] if cur[k] is not None else r[k]
        if not cur["ckpts"]:
            cur["ckpts"] = r["ckpts"]
        # 개정 19: last.pth 판정은 체크포인트 이름 목록과 따로 참이 될 수 있다. DDP 처럼 같은 판 프로세스가 여럿이면 한쪽이라도
        # last 를 봤으면 «있음» 으로 남긴다(뒤 프로세스의 False 가 앞의 True 를 덮지 않게, qa 2026-10-22).
        cur["last"] = bool(cur["last"]) or bool(r["last"])
    return [merged[k] for k in sorted(merged)]


def previous_train(now, max_age=60):
    """Return (train, train_ts) from the last cache if train itself is within max_age seconds, else None."""
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
    """Gather the server band data (None per field on failure; gpus and train carry over up to 60s)."""
    now = time.time()
    stuck = nvidia_smi_stuck()
    gpus = None if stuck else parse_gpus(run(
        ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"]))
    gpus_ts = now
    train = None if gpus is None else collect_train()   # GPU 조회가 실패·시간 초과면 학습 조회도 건너뛴다(멈춘 드라이버에 또 묻지 않는다)
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
        "mem": parse_mem(run(["free", "-b"])),
        "disk": parse_disk(run(["df", "-B1", "-l", "-P", "/"])),
        "disks": parse_disks(run(DF_ARGS)),
        "sessions": read_sessions(SESS_DIR),
    }


def write_atomic(path, obj):
    """Write JSON via mkstemp (0600) in the same dir + rename so readers never see a partial file."""
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
    """Take the lock, stamp the attempt time first, then refresh the cache."""
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
