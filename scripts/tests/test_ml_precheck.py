"""ml_precheck.py 회귀 테스트 (intent/2026-11-24-harness-review-six-items.md W3 성공 기준 2).

실행: uv run --no-project --with pytest python -m pytest scripts/tests/test_ml_precheck.py -q
계약: 점검표 순서대로 `항목 | PASS/FAIL/SKIP | 근거` 한 줄씩, 마지막 줄 RESULT. FAIL 0건이면 exit 0, 아니면 1, 인자 오류는 2.
REF: knowledge/harness/code-history/scripts__tests__test_ml_precheck.py.md
"""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import ml_precheck as mp

CLEAN = "Epoch 0: 100%|##########| 4/4 [00:01<00:00, loss=0.532, v_num=0]\nEpoch 1: 100%|##########| 4/4 [loss=0.41]\n"
NAMES = [name for name, _, _ in mp.CHECKLIST]


def run(capsys, *args):
    code = mp.main(list(args))
    lines = capsys.readouterr().out.strip().split("\n")
    rows = {}
    for line in lines[:-1]:
        name, status, evidence = line.split(" | ", 2)
        rows[name] = (status, evidence)
    return code, rows, lines


def write(tmp_path, text, name="run.log"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_clean_log_passes(tmp_path, capsys):
    code, rows, lines = run(capsys, "--log", write(tmp_path, CLEAN), "--exit-code", "0")
    assert code == 0 and lines[-1] == "RESULT: PASS"
    for item in ("dry-run 통과 여부", "NaN/Inf loss 강제 감지", "exit code 강제 체크", "silent skip 감지"):
        assert rows[item][0] == "PASS", rows[item]


def test_output_order_matches_checklist(tmp_path, capsys):
    _, rows, lines = run(capsys, "--log", write(tmp_path, CLEAN))
    assert list(rows) == NAMES and len(lines) == len(NAMES) + 1


@pytest.mark.parametrize(
    "bad",
    [
        "loss=nan", "val_loss: NaN", "tensor(nan, device='cuda:0')", "x=[1.0, -inf]", "grad_norm=Inf,",
        "Epoch 0: 10%| 1/10 [loss=nan.0, v_num=0]", "Loss is nan, stopping training", "train_loss nan",
        "found nan values in gradients", "Epoch 3 | loss nan | lr 1e-4", "max is -Infinity now", "Loss became NaN.",
    ],
)
def test_nan_inf_as_value_fails(tmp_path, capsys, bad):
    code, rows, lines = run(capsys, "--log", write(tmp_path, f"ok line\nstep 3 {bad}\n"))
    status, evidence = rows["NaN/Inf loss 강제 감지"]
    assert code == 1 and status == "FAIL" and lines[-1] == "RESULT: FAIL"
    assert "run.log:2:" in evidence


def test_nan_inside_word_is_not_a_hit(tmp_path, capsys):
    text = (
        "nan_count=0\nINFO: inference started\nLoading nanoscale model from /data/nan/info.json\nlevel=info mode=infer\nName: Nancy, Information: ok\n"
        "if torch.isnan(loss): raise\nnanmean=0.3 isinf(x)=False\nreading /data/nan.txt and C:\\logs\\nan\\a.csv\n"
        "args: --detect-nan --no-inf-check\nnon-nan rows: 12\nuse torch.nan as fill, nan-count=0\n"
    )
    code, rows, _ = run(capsys, "--log", write(tmp_path, text))
    assert rows["NaN/Inf loss 강제 감지"][0] == "PASS" and code == 0


def test_traceback_fails_dry_run(tmp_path, capsys):
    text = "start\nTraceback (most recent call last):\n  File \"train.py\", line 3\nRuntimeError: boom\n"
    code, rows, _ = run(capsys, "--log", write(tmp_path, text))
    assert code == 1 and rows["dry-run 통과 여부"][0] == "FAIL"
    assert "run.log:2:" in rows["dry-run 통과 여부"][1]
    code, rows, _ = run(capsys, "--log", write(tmp_path, "torch.cuda.OutOfMemoryError: CUDA out of memory\n", "oom.log"))
    assert code == 1 and rows["dry-run 통과 여부"][0] == "FAIL"


def test_exit_code_one_fails_even_with_clean_log(tmp_path, capsys):
    code, rows, _ = run(capsys, "--log", write(tmp_path, CLEAN), "--exit-code", "1")
    assert code == 1 and rows["exit code 강제 체크"][0] == "FAIL"
    code, rows, _ = run(capsys, "--log", write(tmp_path, CLEAN + "exit:2\n", "b.log"))
    assert code == 1 and rows["exit code 강제 체크"][0] == "FAIL" and "b.log:3:" in rows["exit code 강제 체크"][1]


def test_exit_zero_does_not_hide_nan(tmp_path, capsys):
    code, rows, _ = run(capsys, "--log", write(tmp_path, "loss=nan\nexit:0\n"), "--exit-code", "0")
    assert code == 1 and rows["exit code 강제 체크"][0] == "PASS" and rows["NaN/Inf loss 강제 감지"][0] == "FAIL"


@pytest.mark.parametrize("line", ["Trainer: 0 batches", "Epoch 0: 0it [00:00, ?it/s]", "Warning: LR scheduler is empty"])
def test_silent_skip_patterns_fail(tmp_path, capsys, line):
    code, rows, _ = run(capsys, "--log", write(tmp_path, f"a\n{line}\n"))
    assert code == 1 and rows["silent skip 감지"][0] == "FAIL"


def test_silent_skip_does_not_match_larger_numbers(tmp_path, capsys):
    code, rows, _ = run(capsys, "--log", write(tmp_path, "10 batches\n0.5 batches\nEpoch 0: 10it\n"))
    assert code == 0 and rows["silent skip 감지"][0] == "PASS"


def test_cr_progress_lines_keep_newline_numbering(tmp_path, capsys):
    text = "first\nEpoch 0: 50%|#| loss=0.5\rEpoch 0: 100%|#| loss=nan\nlast\n"
    _, rows, _ = run(capsys, "--log", write(tmp_path, text))
    assert rows["NaN/Inf loss 강제 감지"][0] == "FAIL" and "run.log:2:" in rows["NaN/Inf loss 강제 감지"][1]


def test_no_inputs_is_argument_error(capsys):
    with pytest.raises(SystemExit) as e:
        mp.main([])
    assert e.value.code == 2
    assert mp.main(["--log", "/nonexistent/none.log"]) == 2


def test_log_is_required(tmp_path, capsys):
    for args in (["--exit-code", "0"], ["--config", write(tmp_path, "home = /usr/bin\n", "x.cfg")]):
        with pytest.raises(SystemExit) as e:
            mp.main(args)
        assert e.value.code == 2
    assert "RESULT" not in capsys.readouterr().out


@pytest.mark.parametrize("text", ["", "   \n\t\n\n"])
def test_empty_log_fails_dry_run(tmp_path, capsys, text):
    code, rows, _ = run(capsys, "--log", write(tmp_path, text), "--exit-code", "0")
    assert code == 1 and rows["dry-run 통과 여부"][0] == "FAIL" and "빈 로그" in rows["dry-run 통과 여부"][1]


@pytest.mark.parametrize("line", ["[rank0]: RuntimeError: boom", "2025-01-01 12:00:00 torch.cuda.OutOfMemoryError: x", "[ERROR] step failed", "2025 ERROR: bad", "12:00 - ERROR - bad", "CRITICAL shutting down", "FATAL: oom"])
def test_error_forms_with_prefix_and_level_fail(tmp_path, capsys, line):
    code, rows, _ = run(capsys, "--log", write(tmp_path, f"ok\n{line}\n"))
    assert code == 1 and rows["dry-run 통과 여부"][0] == "FAIL" and "run.log:2:" in rows["dry-run 통과 여부"][1]


def test_metric_names_and_lowercase_error_are_not_errors(tmp_path, capsys):
    text = "error_rate=0.1\nval_error: 0.2\nERROR_RATE=0.3\nwe saw an error in the docs but recovered\nErrorRate: 0.4\n"
    code, rows, _ = run(capsys, "--log", write(tmp_path, text))
    assert rows["dry-run 통과 여부"][0] == "PASS" and code == 0


def test_secrets_are_masked_in_evidence(tmp_path, capsys):
    text = "loss=nan Authorization: Bearer abcDEF123 token=tok_999 api_key=K-777 password=hunter2 sk-ABCDEFGH12345\n"
    _, rows, _ = run(capsys, "--log", write(tmp_path, text))
    evidence = rows["NaN/Inf loss 강제 감지"][1]
    for secret in ("abcDEF123", "tok_999", "K-777", "hunter2", "sk-ABCDEFGH12345"):
        assert secret not in evidence
    assert "***" in evidence and "loss=nan" in evidence


def test_oversized_log_is_refused(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(mp, "MAX_LOG_BYTES", 10)
    assert mp.main(["--log", write(tmp_path, "x" * 100)]) == 2
    io = capsys.readouterr()
    assert "너무 큰 로그" in io.err and "끝부분을 잘라 넘기라" in io.err and io.out == ""


def test_skip_items_never_make_result_fail(tmp_path, capsys):
    code, rows, lines = run(capsys, "--log", write(tmp_path, CLEAN), "--exit-code", "0")
    skips = [n for n, (s, _) in rows.items() if s == "SKIP"]
    assert {"파라미터 수 확인(torchinfo·thop)", "checkpoint 경로 충돌 없음", "재현성 체크리스트(seed·환경 기록)"} <= set(skips)
    assert all(rows[n][1].startswith("기계 판정 불가:") for n in skips)
    assert code == 0 and lines[-1] == "RESULT: PASS"


def test_pyvenv_home_judged(tmp_path, capsys):
    ok = write(tmp_path, "home = /home/u/.local/share/uv/python/cpython-3.12-linux/bin\n", "ok.cfg")
    bad = write(tmp_path, "home = /usr/bin\n", "bad.cfg")
    other = write(tmp_path, "lr: 0.1\n", "train.yaml")
    log = write(tmp_path, CLEAN)
    code, rows, _ = run(capsys, "--log", log, "--config", ok)
    assert code == 0 and rows["pyvenv.cfg home 이 uv 관리 파이썬"][0] == "PASS"
    code, rows, _ = run(capsys, "--log", log, "--config", bad)
    assert code == 1 and rows["pyvenv.cfg home 이 uv 관리 파이썬"][0] == "FAIL"
    code, rows, _ = run(capsys, "--log", log, "--config", other)
    assert code == 0 and rows["pyvenv.cfg home 이 uv 관리 파이썬"][0] == "SKIP"


def test_cli_subprocess_exit_codes(tmp_path):
    script = str(SCRIPTS / "ml_precheck.py")
    clean = write(tmp_path, CLEAN)
    nan = write(tmp_path, "loss=nan\n", "nan.log")
    assert subprocess.run([sys.executable, script, "--log", clean], capture_output=True, check=False).returncode == 0
    p = subprocess.run([sys.executable, script, "--log", nan], capture_output=True, text=True, check=False)
    assert p.returncode == 1 and p.stdout.strip().split("\n")[-1] == "RESULT: FAIL"
    assert subprocess.run([sys.executable, script], capture_output=True, check=False).returncode == 2
