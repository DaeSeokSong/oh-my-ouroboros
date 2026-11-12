#!/usr/bin/env python3
"""train-launch-warn.sh 탐지 범위 회귀 테스트 (2026-09-14 신설).

왜: 이 훅의 정규식은 `train.py`·`run_trains?.py` 리터럴이라 실제 진입점(`train_demo.py`)과
    모듈·런처 실행(`python -m pkg.train`·`torchrun … train`·`lightning … fit`)에 경고조차 뜨지 않았다
    (_audit/loop-audit-20260914.md §3). 범위를 넓힌 뒤에는 반대로 `pretrain.py`·`train_log.txt` 류
    접두·비진입점 오탐이 문제가 되므로, 발사 8종 HIT 과 오탐 miss 를 함께 고정한다.
    2026-09-14 재감사: 읽기 명령(grep·cat·git log 등)으로 진입점을 **보기만** 해도 경고가 떴다 —
    첫 토큰이 읽기 명령이면 발사가 아니므로 miss 3종을 더 고정한다.

훅 성격: 경고만 — 어떤 경우에도 차단하지 않는다(exit 0, 권한 결정 JSON 미출력). 그 성질도 함께 본다.

실행: python3 ~/.claude/scripts/tests/test_train_launch_warn.py → 실패 0 이면 exit 0
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "train-launch-warn.sh"
MARK = "[학습 발사 감지"

HITS = [
    ("train.py 직접", "uv run python train.py --config a.yaml"),
    ("train_demo.py 진입점", "uv run python tools/train_demo.py trainer.max_epochs=40"),
    ("python -m 모듈", "python -m exp.train --gpu 0"),
    ("torchrun", "torchrun --nproc_per_node=2 train_seg.py --res 640"),
    ("run_trains.py", "python run_trains.py --arm b"),
    ("tmux send-keys 인용 안", 'tmux send-keys -t exp-demo1 "uv run python tools/train_demo.py" Enter'),
    ("lightning CLI fit", "lightning run model fit --config configs/demo.yaml"),
    ("python3 -m 하위 모듈", "python3 -m pkg.sub.train_loop --seed 1"),
]

MISSES = [
    ("pretrain.py 접두", "python pretrain.py --stage 1"),
    ("train_log.txt 로그", "tail -n 50 outputs/train_log.txt"),
    ("retrain_notes.py 접두", "python retrain_notes.py --dry-run"),
    # 2026-09-14 재감사 — 학습 파일을 **읽기만** 하는 명령에 발사 경고가 뜨던 오탐
    ("grep 로 진입점 검색", "grep -rn train_demo.py tools/"),
    ("cat 로 진입점 열람", "cat tools/train_demo.py"),
    ("git log 로 진입점 이력", "git log --oneline -5 -- tools/train_demo.py"),
]

results = []


def run(cmd):
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    return subprocess.run(["bash", str(SCRIPT)], check=False, capture_output=True, text=True,
                          input=json.dumps(payload))


def check(name, ok, detail=""):
    results.append((name, ok, detail))


for label, cmd in HITS:
    r = run(cmd)
    check(f"HIT {label}", MARK in r.stdout, r.stdout.strip()[:200])
    check(f"HIT {label}: exit 0", r.returncode == 0, str(r.returncode))
    check(f"HIT {label}: 권한 결정 미출력", "permissionDecision" not in r.stdout, r.stdout[:200])

# 2026-10-01 감사: 평문 stdout 은 모델에 가지 않는다 — PreToolUse additionalContext JSON 이어야 경고가 닿는다.
r = run(HITS[0][1])
try:
    out = json.loads(r.stdout)["hookSpecificOutput"]
    ok = out.get("hookEventName") == "PreToolUse" and MARK in out.get("additionalContext", "")
except Exception:  # noqa: BLE001  # any parse failure means the hook output is malformed, so the check fails
    out, ok = {}, False
check("HIT 경고는 hookSpecificOutput.additionalContext JSON 으로 출력", ok, r.stdout[:200])

for label, cmd in MISSES:
    r = run(cmd)
    check(f"MISS {label}", MARK not in r.stdout, r.stdout.strip()[:200])
    check(f"MISS {label}: exit 0", r.returncode == 0, str(r.returncode))

fail = 0
for name, ok, detail in results:
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       실제: {detail[:300]}")
    fail += 0 if ok else 1

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(results)} checks)")
sys.exit(1 if fail else 0)
