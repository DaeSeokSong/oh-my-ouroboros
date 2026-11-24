"""tools/train-watcher/gpu_preflight.py 의 순수 판정(decide) 시험. 실제 GPU·/proc 는 건드리지 않는다.

REF: knowledge/harness/code-history/scripts__tests__test_gpu_preflight.py.md
"""
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = Path(__file__).resolve().parents[2] / "tools" / "train-watcher" / "gpu_preflight.py"
spec = importlib.util.spec_from_file_location("gpu_preflight", SRC)
gp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)

GPUS = {
    0: {"name": "L40S", "total_gb": 45.0, "used_gb": 27.0, "procs": 1},
    3: {"name": "H100 PCIe", "total_gb": 80.0, "used_gb": 27.0, "procs": 1},
    4: {"name": "H100 PCIe", "total_gb": 80.0, "used_gb": 0.5, "procs": 0},
}


def args(vram=None, cpu=None):
    return SimpleNamespace(vram_gb=vram, cpu_cores=cpu, util_max=70.0, sample_sec=60, cpu_reserve=8.0, vram_margin=0.1)


def test_empty_gpu_passes_without_sizes():
    ok, msgs = gp.decide(GPUS, [4], {}, None, args())
    assert ok and "빈 GPU" in msgs[0]


def test_shared_gpu_requires_sizes():
    ok, msgs = gp.decide(GPUS, [3], {3: 40.0}, 60.0, args(vram=30))
    assert not ok and "필수" in msgs[0]


def test_shared_h100_passes_when_all_headroom():
    ok, msgs = gp.decide(GPUS, [3], {3: 60.0}, 40.0, args(vram=30, cpu=6))
    assert ok, msgs


def test_shared_gpu_refused_on_high_util():
    ok, msgs = gp.decide(GPUS, [3], {3: 85.0}, 40.0, args(vram=30, cpu=6))
    assert not ok and any("사용률" in m and "> 문턱 70" in m for m in msgs)


def test_shared_l40s_refused_on_vram():
    ok, msgs = gp.decide(GPUS, [0], {0: 50.0}, 40.0, args(vram=27, cpu=6))
    assert not ok and any("빈 VRAM 18.0GB < 필요 29.7GB" in m for m in msgs)


def test_cpu_shortage_refused_even_on_empty_gpu():
    ok, msgs = gp.decide(GPUS, [4], {}, 10.0, args(vram=30, cpu=6))
    assert not ok and any("CPU: 빈 코어 10.0 < 필요 14" in m for m in msgs)


def test_ddp_multi_gpu_each_checked():
    ok, _ = gp.decide(GPUS, [3, 4], {3: 60.0}, 40.0, args(vram=30, cpu=12))
    assert ok
    ok, _ = gp.decide(GPUS, [3, 4], {}, 40.0, args(vram=30, cpu=12))
    assert not ok



FAKE_SMI = """#!/bin/bash
mode="$(cat "$(dirname "$0")/mode")"
case "$*" in
  *--query-gpu=index,pci.bus_id,name*)
    if [ "$mode" = na ]; then echo "0, 00000000:01:00.0, NVIDIA L40S, [N/A], 512"; else echo "0, 00000000:01:00.0, NVIDIA L40S, 46080, 512"; fi ;;
  *--query-compute-apps*)
    case "$mode" in fail) echo "boom" >&2; exit 9 ;; busy|shortrow) echo "00000000:01:00.0, 123" ;; esac ;;
  *--query-gpu=index,utilization.gpu*) if [ "$mode" = shortrow ]; then echo "0"; else echo "0, 10"; fi ;;
esac
"""


@pytest.fixture
def fake_smi(tmp_path, monkeypatch):
    exe = tmp_path / "nvidia-smi"
    exe.write_text(FAKE_SMI)
    exe.chmod(0o755)
    (tmp_path / "mode").write_text("idle")
    real_run = subprocess.run

    def run(cmd, *a, **kw):
        assert cmd[0] == "nvidia-smi", cmd
        return real_run([str(exe), *cmd[1:]], *a, **kw)
    monkeypatch.setattr(gp.subprocess, "run", run)
    monkeypatch.delenv("GPU_PREFLIGHT_FAKE", raising=False)
    return lambda mode: (tmp_path / "mode").write_text(mode)


def test_smi_query_failure_is_refused_not_read_as_empty_gpu(fake_smi, capsys):
    assert gp.main(["--gpu", "0"]) == 0
    fake_smi("fail")
    assert gp.main(["--gpu", "0"]) == gp.REFUSE
    assert "조회 실패" in capsys.readouterr().err


def test_smi_na_value_is_a_query_failure_not_a_crash_or_arg_error(fake_smi, capsys):
    fake_smi("na")
    assert gp.main(["--gpu", "0"]) == gp.REFUSE
    err = capsys.readouterr().err
    assert "읽을 수 없음" in err and "memory.total" in err


def test_smi_short_utilization_row_is_a_query_failure_not_a_crash(fake_smi, capsys):
    fake_smi("shortrow")
    assert gp.main(["--gpu", "0", "--vram-gb", "5", "--cpu-cores", "1", "--sample-sec", "1"]) == gp.REFUSE
    assert "형식 이상" in capsys.readouterr().err


def test_card_taken_by_another_job_during_sampling_is_refused(fake_smi, monkeypatch, capsys):
    def sample_then_job_starts(targets, sec, want_util):
        fake_smi("busy")
        return {}, 1e9
    monkeypatch.setattr(gp, "sample", sample_then_job_starts)
    assert gp.main(["--gpu", "0", "--vram-gb", "5", "--cpu-cores", "1"]) == gp.REFUSE
    assert "측정 중 새로 판이 올라온" in capsys.readouterr().err
    fake_smi("idle")
    monkeypatch.setattr(gp, "sample", lambda t, s, want_util: ({}, 1e9))
    assert gp.main(["--gpu", "0", "--vram-gb", "5", "--cpu-cores", "1"]) == 0
