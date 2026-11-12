---
name: ckpt-cleanup
description: "Use when: 학습 사이클 종료 후 불필요 체크포인트 정리 — wandb 3계층 태그 매칭으로 KEEP/DELETE/HOLD 분류 → purge 스크립트 산출(삭제는 사용자 직접). /wandb-cleanup의 매칭 스킬, 태그 정리 후 실행."
model: sonnet
allowed-tools:
  - Read
  - Bash
  - Write
  - Glob
  - AskUserQuestion
---

# Checkpoint Cleanup (wandb 3계층 연동 ckpt 정리)

학습 사이클이 끝난 뒤 더 이상 필요 없는 체크포인트(실패 run·비유의미 실험·비대표 시드)를 분류해 디스크를 회수한다. `/wandb-cleanup`의 매칭 스킬 — wandb 쪽이 run의 **가시성**을 정리한다면, 이 스킬은 로컬 디스크의 **ckpt 파일**을 정리한다.

## 트리거
"체크포인트 정리", "ckpt 정리", "디스크 정리(학습 산출물)", 학습 사이클 종료 후 정리 게이트(`skills/experiment/SKILL.md` § 학습 사이클 종료 후 정리 게이트)에서 사용자가 선택 시.

> **실행 순서 권장: /wandb-cleanup → /ckpt-cleanup.** 분류 신호가 wandb-cleanup이 부여한 3계층 태그(`keep`/`ambiguous`/무태그)와 run state(crashed/failed)이기 때문 — 태그 정리 전에 실행하면 대부분 HOLD로 분류되어 정리 효과가 없다. wandb 미사용 학습이면 인벤토리 모드(크기·목록 보고)로만 동작하고 분류는 사용자 수동 판단.

## ★안전 원칙 (판단근거 이식 — 이 스킬의 존재 이유와 경계)

1. **스크립트는 절대 삭제하지 않는다** — scan·plan까지만 수행하고 `purge_ckpts_*.sh`(rm 명령 목록)를 산출한다. **실행은 항상 사용자 직접** (`rules/code-execution.md` — rm은 검증 예외에 해당하지 않는 파괴 명령, 복구 불가).
2. **학습 진행 중 프로젝트에서 실행 금지** — 활성 run이 쓰고 있는 ckpt를 삭제 후보로 오분류할 수 있다. 사이클 전체 종료 확인 후에만.
3. **보수적 기본값**: 삭제 단위는 run 디렉토리가 아니라 **ckpt 파일 단위** (run 디렉토리에는 log·config 등 보존 가치 있는 파일이 남을 수 있다). run 디렉토리째 삭제는 `--purge-run-dir` 명시 시만.
4. **불확실은 전부 HOLD**: wandb 매칭 실패(unmatched)·`ambiguous` 태그는 삭제 후보에 넣지 않고 사용자 판단으로 넘긴다. 로컬 휴리스틱(파일명 파싱 등)은 프로젝트 종속이라 자동 분류에 쓰지 않는다.

## 3계층 분류 규칙

| tier | 조건 (wandb 매칭 기준) | 처리 |
|------|----------------------|------|
| **KEEP** | 태그에 `keep` (유의미 실험 대표) | 보존 — purge 스크립트에서 제외 |
| **DELETE 후보** | state ∈ {crashed, failed, killed} 또는 태그 `ABORTED` / (`--assume-cleaned` 시) 매칭됐으나 무태그 = wandb-cleanup의 "나머지" 계층 | purge 스크립트에 포함 (사용자 검토 후 직접 실행) |
| **HOLD** | 태그 `ambiguous` / 매칭 실패(unmatched) / wandb 미연결 | 보류 — 목록만 보고, 사용자 수동 판단 |

분류는 KEEP → HOLD → DELETE 순 첫 일치입니다(`ambiguous` 는 실패 상태여도 HOLD).

`--assume-cleaned`는 **wandb-cleanup 완료를 전제**로 무태그 run을 비유의미로 간주하는 플래그 — wandb-cleanup을 안 돌린 프로젝트에서 켜면 오분류하므로 금지.

## 절차

1. **scan (read-only — AI 직접 실행 가능, 탐색성)**:
   ```bash
   python3 ~/.claude/skills/ckpt-cleanup/ckpt_cleanup.py --root {save_path} \
     --wandb-entity {entity} --wandb-project {project} [--assume-cleaned]
   ```
   run 디렉토리별 ckpt 수·용량·tier 분류표 출력 (파일 쓰기 0).
2. **사용자 검토 (필수)**: KEEP 목록(유의미 대표) 전체 + DELETE 후보 수·회수 예상 용량을 보여주고 승인받는다. KEEP 누락(있어야 할 대표가 DELETE에 있음)이 보이면 즉시 중단 → wandb 태그부터 교정.
3. **plan 산출 (파일 쓰기 수반 — 실행 명령서로 사용자 직접)**: 위 명령에 `--emit-plan` 추가 → `ckpt_cleanup_plan_*.json`(분류 근거 전체) + `purge_ckpts_*.sh`(rm 명령 목록) 생성.
4. **삭제 (사용자 직접)**: 사용자가 `purge_ckpts_*.sh` 내용을 눈으로 확인 후 직접 실행.
5. **확인**: scan 재실행으로 잔여 인벤토리·회수 용량 보고.

## 주의

- settings.json의 `Read(**/*.ckpt)` deny는 **파일 내용 읽기** 차단이다 — 경로 나열·크기 집계(ls/du/스크립트 스캔)는 무관하므로 scan은 정상 동작한다.
- run 디렉토리 ↔ wandb run 매칭은 이름 기반(정확 일치 → 부분 포함) — run name 규칙(`{단계}-{모델}-{변수}-{MMDD}`, experiment 스킬)을 지킨 프로젝트일수록 매칭률이 높다. 매칭률이 낮으면(<50%) 결과를 신뢰하지 말고 사용자에게 보고.
- best/last 등 심볼릭 링크가 삭제 대상 파일을 가리키면 링크가 깨진다 — plan JSON의 `symlinks` 경고 확인.
