#!/usr/bin/env python3
"""gpu_preflight.py — 학습 발사 전 GPU·CPU 여유 검사. launch-set.sh launch 가 부르고, 따로 불러도 된다.

(2026-09-29 사용자 결정: 모든 학습에 적용. 결정1-2) 이미 판이 도는 GPU 는 60초 평균 사용률 70% 이하일 때만,
 결정2-1) 새 판의 --vram-gb·--cpu-cores 를 필수로 받고 없으면 빈 GPU 에만, 결정3-1) 미달이면 거부.)

사용: gpu_preflight.py --gpu 3[,4] [--vram-gb 30] [--cpu-cores 6] [--util-max 70] [--sample-sec 60]
                       [--cpu-reserve 8] [--vram-margin 0.1]
종료 코드: 0 통과 / 76 거부(nvidia-smi 조회 실패·`[N/A]` 값·측정 중 새로 판이 올라온 GPU 포함 — 판정 불능은 통과가 아니라 거부, D3) / 64 인자 오류
측정 뒤에는 점유·VRAM 을 다시 조회해 판정한다(표본 60초 동안 바뀐 상태를 쓰지 않으면 방금 시작한 판의 카드에 겹쳐 올린다).

■ 판정 (판단 근거 이식)
  빈 GPU(계산 프로세스 0개): GPU 쪽은 통과. --cpu-cores 를 주면 CPU 여유만 본다.
  판이 도는 GPU(여러 판 올리기): 아래가 모두 맞아야 통과한다.
    - --vram-gb·--cpu-cores 가 있어야 한다. 새 판 크기를 모르면 VRAM 부족으로 기존 판까지 죽을 수 있다.
    - 빈 VRAM ≥ vram_gb × (1 + vram_margin). 여백은 할당기 조각화와 에폭 경계의 순간 정점 몫이다.
    - 대상 GPU 사용률의 sample_sec 초 평균 ≤ util_max. nvidia-smi 사용률은 «커널이 도는 시간 비율»이라
      SM 점유가 아니다. 70% 이하면 입출력 대기로 GPU 가 비는 시간이 있다는 뜻이고, 그 틈을 새 판이 쓴다.
  CPU: 같은 표본 구간의 /proc/stat 로 잰 빈 논리 코어 ≥ cpu_cores + cpu_reserve.
    예비 코어는 OS·sshd·데이터 로더 순간 정점 몫이다(96 코어 기준 8).
  GPU 번호는 nvidia-smi 번호(PCI 순)다. 학습 쪽이 CUDA_DEVICE_ORDER=PCI_BUS_ID 가 아니면 번호가 다른 카드를 가리킬 수 있다.
  빈 GPU 라도 --vram-gb 를 주면 빈 VRAM ≥ vram_gb × (1 + vram_margin) 을 본다(2026-10-01 대기 목록 자동 발사용:
  VRAM 이 큰 판이 L40S 빈 칸에 들어가 OOM 나지 않게 하고, 들어가는 H100 칸을 기다리게 하려는 것이다).

■ 시험 전용 (GPU_PREFLIGHT_FAKE) — 운영 발사에서는 쓰지 않는다(launch-set.sh 는 이 변수가 있으면 exit 64 로 거부하고, launch_queue.py 의 실제 백엔드는 제거 후 경고한다)
  환경변수에 JSON 파일 경로를 주면 nvidia-smi·/proc/stat 표본 대신 그 파일 값을 쓰고 표본 대기도 건너뛴다.
  {"gpus": {"0": {"name": "L40S", "total_gb": 45, "used_gb": 0.5, "procs": 0}, ...},
   "util": {"3": 40.0},        # 공유 GPU 의 사용률 평균(%). 없는 GPU 는 측정 실패로 취급
   "idle_cores": 90}           # 빈 논리 코어. 생략하면 매우 큰 값
  실제 GPU 는 학습 중이라 대기 목록 도구 시험에 쓸 수 없어 만든 장치다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

REFUSE, ARGERR = 76, 64


def decide(gpus: dict, targets: list[int], util_avg: dict, idle_cores: float | None, a) -> tuple[bool, list[str]]:
    """순수 판정. gpus = {idx: {"name","total_gb","used_gb","procs"}}, util_avg = {idx: 평균%}."""
    ok, msgs = True, []
    for g in targets:
        info = gpus[g]
        free = info["total_gb"] - info["used_gb"]
        if info["procs"] == 0:
            need = None if a.vram_gb is None else a.vram_gb * (1 + a.vram_margin)
            if need is not None and free < need:
                ok = False
                msgs.append(f"GPU{g} {info['name']}: 빈 GPU 이나 빈 VRAM {free:.1f}GB < 필요 {need:.1f}GB (새 판 {a.vram_gb}GB × {1 + a.vram_margin:.2f})")
            else:
                msgs.append(f"GPU{g} {info['name']}: 빈 GPU (빈 VRAM {free:.1f}GB) — 통과")
            continue
        head = f"GPU{g} {info['name']}: 판 {info['procs']}개 가동 중"
        if a.vram_gb is None or a.cpu_cores is None:
            ok = False
            msgs.append(f"{head} — 여러 판 올리기는 --vram-gb 와 --cpu-cores 가 필수입니다(없으면 빈 GPU 에만 발사)")
            continue
        need = a.vram_gb * (1 + a.vram_margin)
        if free < need:
            ok = False
            msgs.append(f"{head} — 빈 VRAM {free:.1f}GB < 필요 {need:.1f}GB (새 판 {a.vram_gb}GB × {1 + a.vram_margin:.2f})")
        else:
            msgs.append(f"{head} — 빈 VRAM {free:.1f}GB ≥ 필요 {need:.1f}GB")
        u = util_avg.get(g)
        if u is None or u > a.util_max:
            ok = False
            msgs.append(f"{head} — 사용률 {a.sample_sec}초 평균 {'측정 실패' if u is None else f'{u:.0f}%'} > 문턱 {a.util_max}%")
        else:
            msgs.append(f"{head} — 사용률 {a.sample_sec}초 평균 {u:.0f}% ≤ 문턱 {a.util_max}%")
    if a.cpu_cores is not None:
        need = a.cpu_cores + a.cpu_reserve
        if idle_cores is None or idle_cores < need:
            ok = False
            msgs.append(f"CPU: 빈 코어 {'측정 실패' if idle_cores is None else f'{idle_cores:.1f}'} < 필요 {need} (새 판 {a.cpu_cores} + 예비 {a.cpu_reserve})")
        else:
            msgs.append(f"CPU: 빈 코어 {idle_cores:.1f} ≥ 필요 {need} (새 판 {a.cpu_cores} + 예비 {a.cpu_reserve})")
    return ok, msgs


class SmiError(RuntimeError):
    """nvidia-smi 조회 실패(실행 불가·종료 코드≠0·시간 초과·값 읽기 실패) — 인자 오류(64)가 아니라 «판정 불능 → 거부(76)» 이다(D3)."""


def _smi(args: list[str]) -> list[list[str]]:
    try:
        r = subprocess.run(["nvidia-smi", *args, "--format=csv,noheader,nounits"], capture_output=True, text=True,
                           timeout=30, env={"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "PATH": "/usr/bin:/bin"})
    except (OSError, subprocess.SubprocessError) as e:
        raise SmiError(f"nvidia-smi 실행 실패 ({args[0]}): {type(e).__name__}: {e}")
    if r.returncode != 0:   # 실패한 조회를 «빈 결과»로 읽으면 점유 프로세스 0개 = 빈 GPU 로 오판해 판이 도는 카드에 올린다
        raise SmiError(f"nvidia-smi 가 종료 코드 {r.returncode} 로 실패 ({args[0]}): {r.stderr.strip()[:200]}")
    return [[x.strip() for x in line.split(",")] for line in r.stdout.strip().splitlines() if line.strip()]


def _num(v: str, conv, what: str):
    """nvidia-smi 값 변환. `[N/A]`·`[Not Supported]` 같은 값은 ValueError 가 아니라 조회 실패(SmiError)로 올린다."""
    try:
        return conv(v)
    except ValueError:
        raise SmiError(f"nvidia-smi 값을 읽을 수 없음: {what}={v!r}")


def _fake() -> dict | None:
    """시험 전용 가짜 상태(헤더 참조). 변수가 없으면 None."""
    path = os.environ.get("GPU_PREFLIGHT_FAKE")
    return json.load(open(path)) if path else None


def read_gpus() -> dict:
    fk = _fake()
    if fk is not None:
        return {int(i): dict(v) for i, v in fk["gpus"].items()}
    gpus, bus2idx = {}, {}
    for row in _smi(["--query-gpu=index,pci.bus_id,name,memory.total,memory.used"]):
        if len(row) != 5:
            raise SmiError(f"nvidia-smi 출력 형식 이상: {row!r}")
        idx, bus, name, total, used = row
        i = _num(idx, int, "index")
        gpus[i] = {"name": name.replace("NVIDIA ", ""), "total_gb": _num(total, int, "memory.total") / 1024,
                   "used_gb": _num(used, int, "memory.used") / 1024, "procs": 0}
        bus2idx[bus] = i
    for row in _smi(["--query-compute-apps=gpu_bus_id,pid"]):
        if row[0] in bus2idx:
            gpus[bus2idx[row[0]]]["procs"] += 1
    return gpus


def _cpu_times() -> tuple[int, int]:
    f = open("/proc/stat").readline().split()[1:]
    v = list(map(int, f))
    return sum(v), v[3] + v[4]                              # 전체, idle+iowait


def sample(targets: list[int], sec: int, want_util: bool) -> tuple[dict, float]:
    fk = _fake()
    if fk is not None:
        return {g: float(fk["util"][str(g)]) for g in targets if str(g) in fk.get("util", {})}, fk.get("idle_cores", 1e9)
    ncpu = sum(1 for line in open("/proc/stat") if line.startswith("cpu") and line[3].isdigit())
    t0, i0 = _cpu_times()
    utils = {g: [] for g in targets}
    end = time.time() + sec
    while time.time() < end:
        if want_util:
            for row in _smi(["--query-gpu=index,utilization.gpu"]):
                if len(row) != 2:   # 2026-10-01 P6 검수: 행 길이 이상은 unpack ValueError 가 아니라 조회 실패(SmiError → 거부 76)
                    raise SmiError(f"nvidia-smi 출력 형식 이상: {row!r}")
                idx, u = row
                if _num(idx, int, "index") in utils:
                    utils[int(idx)].append(_num(u, float, "utilization.gpu"))
        time.sleep(1)
    t1, i1 = _cpu_times()
    idle = ncpu * (i1 - i0) / max(t1 - t0, 1)
    return {g: sum(v) / len(v) for g, v in utils.items() if v}, idle


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="학습 발사 전 GPU·CPU 여유 검사")
    p.add_argument("--gpu", required=True, help="nvidia-smi 번호(PCI 순), 여러 장이면 쉼표")
    p.add_argument("--vram-gb", type=float)
    p.add_argument("--cpu-cores", type=float)
    p.add_argument("--util-max", type=float, default=70.0)
    p.add_argument("--sample-sec", type=int, default=60)
    p.add_argument("--cpu-reserve", type=float, default=8.0)
    p.add_argument("--vram-margin", type=float, default=0.1)
    try:
        a = p.parse_args(argv)
        targets = [int(x) for x in a.gpu.split(",") if x.strip() != ""]
    except (SystemExit, ValueError):
        return ARGERR
    try:
        gpus = read_gpus()
        missing = [g for g in targets if g not in gpus]
        if not targets or missing:
            print(f"[gpu-preflight] 거부: 없는 GPU 번호 {missing or a.gpu}", file=sys.stderr)
            return ARGERR
        shared = [g for g in targets if gpus[g]["procs"] > 0]
        # 표본은 쓸 데가 있을 때만 잰다: CPU 판정이 필요하고, 공유 GPU 면 필수 인자까지 갖춘 경우(없으면 표본 없이 바로 거부).
        need_sample = a.cpu_cores is not None and (not shared or a.vram_gb is not None)
        util_avg, idle = ({}, None)
        if need_sample:
            print(f"[gpu-preflight] {a.sample_sec}초 표본 측정 중 (GPU {','.join(map(str, targets))}, CPU)", file=sys.stderr)
            util_avg, idle = sample(targets, a.sample_sec, want_util=bool(shared))
            # 표본 구간(기본 60초) 동안 다른 판이 올라올 수 있다 — 측정 전에 읽은 점유·VRAM 으로 판정하면 방금 시작한 판의 카드에 겹쳐 올린다. 측정 뒤 다시 조회한다.
            gpus = read_gpus()
            late = [g for g in targets if g in gpus and gpus[g]["procs"] > 0 and g not in shared]
            if late:
                print(f"[gpu-preflight] 거부: 측정 중 새로 판이 올라온 GPU {late} — 사용률 표본이 없어 공유 판정을 할 수 없음(다시 시도)", file=sys.stderr)
                return REFUSE
            if any(g not in gpus for g in targets):
                print(f"[gpu-preflight] 거부: 측정 뒤 GPU 목록에서 {[g for g in targets if g not in gpus]} 가 사라짐", file=sys.stderr)
                return REFUSE
    except SmiError as e:
        print(f"[gpu-preflight] 거부: GPU 조회 실패 — {e} (인자 오류 아님, 판정 불능이라 발사하지 않음)", file=sys.stderr)
        return REFUSE
    ok, msgs = decide(gpus, targets, util_avg, idle, a)
    for m in msgs:
        print(f"[gpu-preflight] {m}", file=sys.stderr)
    print(f"[gpu-preflight] {'PASS' if ok else '거부'}", file=sys.stderr)
    return 0 if ok else REFUSE


if __name__ == "__main__":
    sys.exit(main())
