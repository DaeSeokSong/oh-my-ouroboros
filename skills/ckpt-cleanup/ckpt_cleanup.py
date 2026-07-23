#!/usr/bin/env python3
"""ckpt-cleanup — 학습 사이클 종료 후 체크포인트 3계층 분류 + 삭제 계획 산출.

설계 근거 (판단근거 이식 — 세션이 바뀌어도 이 파일만으로 재현):
- 이 스크립트는 **절대 삭제하지 않는다**. scan(분류표 출력)과 --emit-plan(계획 JSON +
  purge 셸 스크립트 산출)까지만 수행한다. rm은 산출된 purge_ckpts_*.sh를 사용자가
  검토 후 직접 실행 — 파괴 명령은 AI 검증 예외에 해당하지 않는다(code-execution.md).
- 분류 신호는 wandb의 run state(crashed/failed/killed)와 wandb-cleanup 스킬이 부여한
  3계층 태그(keep/ambiguous/무태그)만 쓴다. 파일명 epoch 파싱 같은 로컬 휴리스틱은
  프로젝트 종속이라 자동 분류에 쓰지 않는다 — 매칭 실패는 전부 HOLD(사용자 판단).
- --assume-cleaned: wandb-cleanup 완료를 전제로 "매칭됐으나 무태그" run을 비유의미
  (DELETE 후보)로 간주. 전제가 없으면 켜지 말 것 — 무태그가 곧 비유의미라는 보장이
  없어 오분류한다.
- 삭제 단위 기본값은 ckpt 파일(run 디렉토리에 log·config가 남을 수 있다). 디렉토리째
  삭제는 --purge-run-dir 명시 시만.

사용:
  python3 ckpt_cleanup.py --root outputs/ \
    [--ext .ckpt .pth .pt .safetensors .bin] \
    [--wandb-entity E --wandb-project P] [--assume-cleaned] \
    [--emit-plan] [--out-dir DIR] [--purge-run-dir]
"""

import argparse
import json
import os
import stat
import sys
import time
from collections import defaultdict
from pathlib import Path

CKPT_DIR_NAMES = {"checkpoints", "checkpoint", "ckpt", "ckpts", "weights"}
FAILED_STATES = {"crashed", "failed", "killed"}
SKIP_DIRS = {".git", "wandb", "__pycache__", "node_modules", ".venv", "venv"}


def human(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if nbytes < 1024 or unit == "TB":
            return f"{nbytes:.1f}{unit}" if unit != "B" else f"{nbytes}B"
        nbytes /= 1024
    return f"{nbytes:.1f}TB"


def discover(root: Path, exts: set):
    """root 하위 ckpt 파일을 run 디렉토리 단위로 그룹핑."""
    groups = defaultdict(list)  # run_dir(Path) -> [file Path]
    symlinks = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() not in exts:
                continue
            if p.is_symlink():
                symlinks.append(str(p))
                continue
            parent = p.parent
            run_dir = parent.parent if parent.name.lower() in CKPT_DIR_NAMES else parent
            if run_dir == root.parent:
                run_dir = parent
            groups[run_dir].append(p)
    return groups, symlinks


def fetch_wandb_runs(entity: str, project: str):
    """wandb run 목록 조회 (read-only). 실패 시 None — 전량 HOLD로 강등."""
    try:
        import wandb  # noqa: 지연 import — 미설치 환경에서도 인벤토리 모드는 동작

        api = wandb.Api(timeout=60)
        runs = api.runs(f"{entity}/{project}", per_page=500)
        return [
            {"id": r.id, "name": r.name, "state": r.state, "tags": list(r.tags or [])}
            for r in runs
        ]
    except Exception as e:  # 네트워크/인증/미설치 — 이유 불문 인벤토리 모드
        print(f"[warn] wandb 조회 실패 → 전량 HOLD(인벤토리 모드): {e}", file=sys.stderr)
        return None


def match_run(dir_name: str, wandb_runs):
    """정확 일치 → 부분 포함(양방향) 순. 다중 매치는 미매칭 취급(오분류 방지)."""
    exact = [r for r in wandb_runs if r["name"] == dir_name]
    if len(exact) == 1:
        return exact[0]
    partial = [
        r for r in wandb_runs if r["name"] and (r["name"] in dir_name or dir_name in r["name"])
    ]
    return partial[0] if len(partial) == 1 else None


def classify(run, assume_cleaned: bool):
    if run is None:
        return "HOLD", "unmatched"
    tags = {t.lower() for t in run["tags"]}
    if "keep" in tags:
        return "KEEP", "tag:keep"
    if run["state"] in FAILED_STATES:
        return "DELETE", f"state:{run['state']}"
    if "aborted" in tags:
        return "DELETE", "tag:ABORTED"
    if "ambiguous" in tags:
        return "HOLD", "tag:ambiguous"
    if assume_cleaned:
        return "DELETE", "untagged(assume-cleaned)"
    return "HOLD", "untagged"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="스캔 루트 (예: outputs/, save_path)")
    ap.add_argument("--ext", nargs="+", default=[".ckpt", ".pth", ".pt", ".safetensors", ".bin"])
    ap.add_argument("--wandb-entity")
    ap.add_argument("--wandb-project")
    ap.add_argument("--assume-cleaned", action="store_true",
                    help="wandb-cleanup 완료 전제 — 매칭+무태그 run을 DELETE 후보로")
    ap.add_argument("--emit-plan", action="store_true",
                    help="계획 JSON + purge 셸 스크립트 산출 (파일 쓰기 — 사용자 직접 실행용)")
    ap.add_argument("--out-dir", default=".", help="--emit-plan 산출물 저장 위치")
    ap.add_argument("--purge-run-dir", action="store_true",
                    help="파일 단위 대신 run 디렉토리째 삭제 명령 산출 (기본: 파일 단위)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"[error] root가 디렉토리가 아님: {root}")
    exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in args.ext}

    groups, symlinks = discover(root, exts)
    if not groups:
        print(f"체크포인트 없음: {root} (ext={sorted(exts)})")
        return

    wandb_runs = None
    if args.wandb_entity and args.wandb_project:
        wandb_runs = fetch_wandb_runs(args.wandb_entity, args.wandb_project)

    rows, tier_bytes = [], defaultdict(int)
    for run_dir in sorted(groups):
        files = groups[run_dir]
        size = sum(f.stat().st_size for f in files)
        run = match_run(run_dir.name, wandb_runs) if wandb_runs else None
        tier, reason = classify(run, args.assume_cleaned) if wandb_runs else ("HOLD", "no-wandb")
        tier_bytes[tier] += size
        rows.append({
            "run_dir": str(run_dir), "n_files": len(files), "bytes": size,
            "tier": tier, "reason": reason,
            "wandb_run": run["name"] if run else None,
            "files": sorted(str(f) for f in files),
        })

    w = max(len(Path(r["run_dir"]).name) for r in rows)
    print(f"\n=== ckpt-cleanup scan: {root} ===")
    for r in rows:
        print(f"  [{r['tier']:6}] {Path(r['run_dir']).name:<{w}}  "
              f"{r['n_files']:3}개 {human(r['bytes']):>9}  ({r['reason']})")
    matched = sum(1 for r in rows if r["wandb_run"]) if wandb_runs else 0
    print(f"\n  집계: KEEP {human(tier_bytes['KEEP'])} / "
          f"DELETE후보 {human(tier_bytes['DELETE'])} / HOLD {human(tier_bytes['HOLD'])}")
    if wandb_runs is not None:
        rate = matched / len(rows) * 100
        print(f"  wandb 매칭률: {matched}/{len(rows)} ({rate:.0f}%)"
              + ("  ⚠️ 50% 미만 — 분류 신뢰 불가, 사용자 보고 필요" if rate < 50 else ""))
    if symlinks:
        print(f"  ⚠️ 심볼릭 링크 {len(symlinks)}개 제외됨 — 삭제 대상이 원본이면 링크가 깨진다")

    if not args.emit_plan:
        print("\n(계획 산출은 --emit-plan — 파일 쓰기를 수반하므로 사용자 승인 하에)")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    plan_path = out / f"ckpt_cleanup_plan_{ts}.json"
    plan_path.write_text(json.dumps({
        "root": str(root), "generated_at": ts, "assume_cleaned": args.assume_cleaned,
        "symlinks_excluded": symlinks, "rows": rows,
    }, indent=2, ensure_ascii=False))

    delete_rows = [r for r in rows if r["tier"] == "DELETE"]
    sh_path = out / f"purge_ckpts_{ts}.sh"
    lines = ["#!/usr/bin/env bash",
             "# ckpt-cleanup 삭제 계획 — 반드시 내용을 검토한 뒤 직접 실행하십시오.",
             f"# 근거: {plan_path.name} / 회수 예상: {human(tier_bytes['DELETE'])}",
             "set -euo pipefail", ""]
    for r in delete_rows:
        lines.append(f"# {Path(r['run_dir']).name} — {r['reason']}, {human(r['bytes'])}")
        if args.purge_run_dir:
            lines.append(f"rm -rf {json.dumps(r['run_dir'])}")
        else:
            lines.extend(f"rm -f {json.dumps(f)}" for f in r["files"])
        lines.append("")
    sh_path.write_text("\n".join(lines))
    sh_path.chmod(sh_path.stat().st_mode | stat.S_IXUSR)

    print(f"\n산출: {plan_path}\n      {sh_path} (DELETE {len(delete_rows)}건, "
          f"{human(tier_bytes['DELETE'])})\n실행은 검토 후 사용자 직접: bash {sh_path}")


if __name__ == "__main__":
    main()
