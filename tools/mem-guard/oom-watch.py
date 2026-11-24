"""oom-watch.py — memguard scope 안의 프로세스가 메모리·swap 초과로 «실제로» 죽었을 때만 알림 줄을 낸다.

mem-watch.sh(cron 매분)가 부르고, 표준출력의 각 줄을 ntfy 로 보낸다. 알림이 없으면 아무것도 출력하지 않는다.

■ 판정 근거 (판단 근거 이식)
  cgroup v2 memory.events 의 두 카운터를 비교한다(커널 문서 Documentation/admin-guide/cgroup-v2.rst).
    oom       = 이 cgroup 이 «자기» 한도(MemoryMax, swap 상한 포함)에 닿아 할당이 실패하려던 횟수
    oom_kill  = 이 cgroup 소속 프로세스가 «어떤» OOM killer 에든 죽은 횟수
  → oom_kill 증가 + oom 증가 = 판 자기 한도 초과(개별).  oom_kill 증가 + oom 그대로 = 호스트 전체 고갈.
  09-29 시험 스코프(64M 상자에 200M)에서 개별 초과는 oom 1·oom_kill 1 로 실측했다. 전체 고갈은
  재현하지 않았다(위험). memory.swap.events 의 max 는 판 swap 상한 도달, fail 은 swap 할당 실패(대개 전체 swap 고갈).
  커널 로그를 읽을 수 있으면(adm·systemd-journal 그룹) «oom-kill:constraint=» 줄이 정본이다:
  CONSTRAINT_MEMCG = cgroup 한도(개별), CONSTRAINT_NONE = 호스트 전체. 희생 프로세스 이름·pid 도 거기서 확정한다.
  systemd-oomd 의 압력 종료는 카운터가 움직이지 않는다. 시스템 저널(같은 그룹 필요)의 systemd-oomd 줄로만 보인다.

■ 죽은 프로세스 식별
  카운터에는 이름이 없다. 매 실행마다 scope 의 프로세스 목록(pid·명령·RSS)을 상태 파일에 적어 두고,
  oom_kill 이 늘면 직전 목록에서 사라진 pid 를 후보로 낸다. 커널 로그가 있으면 그쪽이 우선이다.
  본 학습이 죽어 scope 가 --collect 로 걷히면 카운터가 사라진다. 그때는 사용자 저널의
  «A process of this unit has been killed by the OOM killer.» 줄과 마지막 목록으로 알린다.

첫 실행(상태 파일 없음)은 기준선만 적고 알리지 않는다. 실패해도 exit 0 (cron 안전).
REF: knowledge/harness/code-history/tools__mem-guard__oom-watch.py.md
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

GIB_KB = 1024 * 1024
KILL = "💀"
USER_OOM_RX = re.compile(r"(memguard-[^\s:]+\.scope): A process of this unit has been killed by the OOM killer")
KERNEL_OOM_RX = re.compile(r"oom-kill:constraint=(\w+),.*?oom_memcg=([^,]*),task_memcg=([^,]*),task=([^,]*),pid=(\d+)")
KERNEL_RSS_RX = re.compile(r"Killed process (\d+) \(([^)]*)\).*?anon-rss:(\d+)kB")
OOMD_RX = re.compile(r"systemd-oomd\[\d+\]: Killed (\S+) due to (.*)$")


def scope_label(unit: str) -> str:
    s = unit.removeprefix("memguard-")
    s = s.removesuffix(".scope")
    return re.sub(r"-\d+$", "", s)


def gib(kb: float) -> str:
    return f"{kb / GIB_KB:.1f}"


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def _kv(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("-").isdigit():
            out[parts[0]] = int(parts[1])
    return out


def _limit_kb(v: str):
    return None if (not v or v == "max") else int(v) // 1024


def read_scopes(base: Path) -> dict:
    scopes = {}
    for d in sorted(base.glob("memguard-*.scope")):
        pids = _read(d / "cgroup.procs").split()
        if not pids:
            continue
        ev, sev = _kv(_read(d / "memory.events")), _kv(_read(d / "memory.swap.events"))
        procs = {}
        for pid in pids:
            cmd = _read(Path(f"/proc/{pid}/cmdline")).replace("\x00", " ").strip()
            st = _kv(_read(Path(f"/proc/{pid}/status")).replace("kB", "").replace(":", ""))
            if cmd:
                procs[pid] = {"cmd": cmd[:80], "rss_kb": st.get("VmRSS", 0)}
        scopes[d.name] = {
            "oom": ev.get("oom", 0), "oom_kill": ev.get("oom_kill", 0),
            "swap_ev_max": sev.get("max", 0), "swap_fail": sev.get("fail", 0),
            "mem_kb": int(_read(d / "memory.current") or 0) // 1024,
            "mem_max_kb": _limit_kb(_read(d / "memory.max")),
            "swap_kb": int(_read(d / "memory.swap.current") or 0) // 1024,
            "swap_max_kb": _limit_kb(_read(d / "memory.swap.max")),
            "procs": procs,
        }
    return scopes


def host_swap() -> tuple[int, int]:
    mi = _kv(_read(Path("/proc/meminfo")).replace("kB", "").replace(":", ""))
    total = mi.get("SwapTotal", 0)
    return total - mi.get("SwapFree", 0), total


def _journal(args: list[str], since: float) -> list[str]:
    try:
        r = subprocess.run(["journalctl", *args, "-q", "--no-pager", "-o", "short-unix", "--since", f"@{int(since)}"],
                           capture_output=True, text=True, timeout=15, check=False)
        return r.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []


def parse_kernel(lines: list[str]) -> list[dict]:
    rss = {m.group(1): int(m.group(3)) for m in map(KERNEL_RSS_RX.search, lines) if m}
    events = []
    for line in lines:
        m = KERNEL_OOM_RX.search(line)
        if m:
            ts = line.split(" ", 1)[0]
            constraint, oom_memcg, task_memcg, task, pid = m.groups()
            events.append({"key": f"k{ts}:{pid}", "constraint": constraint, "oom_memcg": oom_memcg,
                           "task_memcg": task_memcg, "task": task, "pid": pid, "rss_kb": rss.get(pid, 0)})
    return events


def parse_oomd(lines: list[str]) -> list[dict]:
    out = []
    for line in lines:
        m = OOMD_RX.search(line)
        if m:
            out.append({"key": f"d{line.split(' ', 1)[0]}:{m.group(1)}", "path": m.group(1), "why": m.group(2)})
    return out


def parse_user_oom(lines: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in lines:
        m = USER_OOM_RX.search(line)
        if m:
            out.setdefault(m.group(1), []).append(f"u{line.split(' ', 1)[0]}:{m.group(1)}")
    return out


def swap_text(s: dict, host_used: int, host_total: int, fail_delta: int, max_delta: int) -> str:
    if s.get("swap_max_kb") is None:
        own = f"판 {gib(s['swap_kb'])}GiB(상한 없음)"
    else:
        hit = " 상한 도달" if (max_delta > 0 or s["swap_kb"] >= s["swap_max_kb"] * 0.98) else ""
        own = f"판 {gib(s['swap_kb'])}/{gib(s['swap_max_kb'])}GiB{hit}"
    pct = round(100 * host_used / host_total) if host_total else 0
    full = " 고갈" if (pct >= 99 or fail_delta > 0) else ""
    return f"swap: {own} · 전체 {pct}%{full}"


def victims_text(prev_procs: dict, cur_procs: dict, kev: dict | None) -> str:
    if kev:
        return f"죽은 프로세스: pid {kev['pid']} {kev['task']} (RSS {gib(kev['rss_kb'])}GiB, 커널 로그)"
    gone = [(pid, p) for pid, p in prev_procs.items() if pid not in cur_procs]
    if not gone:
        return "죽은 프로세스: 확인 불가(직전 목록과 차이 없음)"
    # NEVER: 명령줄 인자(경로 · 옵션)를 알림에 싣지 않는다. 알림은 공개 서버로 나간다(2026-10-01 감사 D5).
    parts = [f"pid {pid} {os.path.basename(p['cmd'].split(' ', 1)[0])} (RSS {gib(p['rss_kb'])}GiB)"
             for pid, p in gone[:3]]
    more = f" 외 {len(gone) - 3}개" if len(gone) > 3 else ""
    return "죽은 프로세스 후보: " + "; ".join(parts) + more


def kind_text(constraint: str | None, oom_delta: int | None) -> str:
    if constraint == "CONSTRAINT_MEMCG":
        return "개별 한도 초과(판 MemoryMax·swap 상한)"
    if constraint == "CONSTRAINT_NONE":
        return "호스트 전체 메모리·swap 고갈"
    if oom_delta is None:
        return "개별·전체 구분 불가(scope 소멸, 커널 로그 없음)"
    return "개별 한도 초과(판 MemoryMax·swap 상한)" if oom_delta > 0 else "호스트 전체 메모리·swap 고갈"


def build_alerts(host: str, prev: dict, cur: dict, user_oom: dict, kernel: list, oomd: list,
                 swap_host: tuple[int, int], seen: set) -> list[str]:
    used, total = swap_host
    alerts = []
    user_oom = {u: [k for k in ks if k not in seen] for u, ks in user_oom.items()}
    user_oom = {u: ks for u, ks in user_oom.items() if ks}
    kernel = [k for k in kernel if k["key"] not in seen]
    by_scope = {}
    for k in kernel:
        unit = k["task_memcg"].rsplit("/", 1)[-1]
        by_scope.setdefault(unit, []).append(k)

    for unit in user_oom:
        if unit not in prev:
            prev = {**prev, unit: {"oom": 0, "oom_kill": 0, "swap_ev_max": 0, "swap_fail": 0, "mem_kb": 0,
                                   "mem_max_kb": None, "swap_kb": 0, "swap_max_kb": None, "procs": {}}}
    for unit, p in prev.items():
        c = cur.get(unit)
        kevs = by_scope.pop(unit, [])
        ukeys = user_oom.get(unit, [])
        seen.update(ukeys)
        if c is not None:
            kill_d, oom_d = c["oom_kill"] - p["oom_kill"], c["oom"] - p["oom"]
            if kill_d <= 0 and not kevs:
                continue
            s, fail_d, smax_d = c, c["swap_fail"] - p["swap_fail"], c["swap_ev_max"] - p["swap_ev_max"]
            n = max(kill_d, len(kevs))
        else:
            if not ukeys and not kevs:
                continue
            oom_d, s, fail_d, smax_d, n = None, p, 0, 0, max(1, len(kevs), len(ukeys))
        kev = kevs[0] if kevs else None
        kind = kind_text(kev["constraint"] if kev else None, oom_d)
        mem = f"판 메모리 {gib(s['mem_kb'])}/{gib(s['mem_max_kb']) if s['mem_max_kb'] else '∞'}GiB"
        alerts.append(f"{KILL} [{host}] OOM 종료 {n}건: {scope_label(unit)} · {kind} · "
                      f"{victims_text(p['procs'], (c or {}).get('procs', {}), kev)} · {mem} · "
                      f"{swap_text(s, used, total, fail_d, smax_d)}")
        seen.update(k["key"] for k in kevs)

    for unit, kevs in by_scope.items():
        for k in kevs:
            alerts.append(f"{KILL} [{host}] OOM 종료(memguard 밖): pid {k['pid']} {k['task']} "
                          f"(RSS {gib(k['rss_kb'])}GiB) · {kind_text(k['constraint'], None)} · cgroup {unit} · "
                          f"swap: 전체 {round(100 * used / total) if total else 0}%")
            seen.add(k["key"])

    for d in oomd:
        if d["key"] in seen:
            continue
        unit = d["path"].rstrip("/").rsplit("/", 1)[-1]
        alerts.append(f"{KILL} [{host}] systemd-oomd 압력 종료: {scope_label(unit)} · 메모리 압력 한도 초과"
                      f"(swap·한도 초과 아님) · {d['why'][:120]}")
        seen.add(d["key"])
    return alerts


def main() -> int:
    uid = os.getuid()
    base = Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice")
    state_path = Path(os.environ.get("OOMWATCH_STATE", Path(__file__).with_name("oom-watch.state")))
    now = time.time()
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = None
    cur = read_scopes(base)
    alerts = []
    if state:
        since = state.get("ts", now) - 5                   # WHY: 겹치는 5초는 seen 키로 중복 제거
        seen = set(state.get("seen", []))
        alerts = build_alerts(os.uname().nodename, state.get("scopes", {}), cur,
                              parse_user_oom(_journal(["--user"], since)),
                              parse_kernel(_journal(["-k"], since)),
                              parse_oomd(_journal(["-t", "systemd-oomd"], since)),
                              host_swap(), seen)
    else:
        seen = set()
    try:
        state_path.write_text(json.dumps({"ts": now, "scopes": cur, "seen": sorted(seen)[-300:]}, ensure_ascii=False))
    except OSError:
        pass
    for a in alerts:
        print(a)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"oom-watch 오류: {e}", file=sys.stderr)
        sys.exit(0)
