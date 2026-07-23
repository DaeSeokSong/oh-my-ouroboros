---
name: wandb-cleanup
description: "Use when: wandb run 대량 정리 — 유의미/애매/비유의미 3계층으로 태그 + 눈끄기(visibility). ★개별 run hide는 personal workspace의 selections.tree 조작 필요(wandb 전역 눈끄기 API 없음). 스크립트: tools/wandb_cleanup/."
model: sonnet
allowed-tools:
  - Read
  - Bash
  - Write
  - Edit
  - AskUserQuestion
---

# wandb Run Cleanup (3계층 태그 + visibility)

wandb 프로젝트의 다수 run을 3계층으로 정리한다 — 유의미 실험 대표만 남기고(visible+태그), 나머지는 눈 끄기(hidden). 실행 스크립트는 repo `tools/wandb_cleanup/`에 보존.

> **스크립트 위치**: 절차의 `tools/wandb_cleanup/` 상대경로는 **이 스킬을 실행하는 프로젝트 repo**의 cwd 기준이다. 스크립트가 아직 그 프로젝트에 없으면, 보유 repo를 탐색(`find ~/workspace -maxdepth 6 -name wandb_3tier_dryrun.py 2>/dev/null`)해 `tools/wandb_cleanup/` 디렉토리를 복사해 온 뒤 `--entity`/`--project`/기둥 태그 매핑(§3계층 규칙)을 프로젝트에 맞게 조정한다 — 핵심 메커니즘(selections.tree·upsertView UPDATE)은 프로젝트 무관.

## 트리거
"wandb 정리", "run 태그 정리", "눈 끄기/숨기기", 프로젝트 run 수백 개 시각 정리 요청. 학습 사이클 종료 시 정리 게이트(`skills/experiment/SKILL.md` § 학습 사이클 종료 후 정리 게이트)에서 사용자 선택 시.

> **매칭 스킬**: 로컬 체크포인트 정리는 `/ckpt-cleanup` — 본 스킬이 부여한 3계층 태그(keep/ambiguous/무태그)를 분류 신호로 소비하므로, 사이클 정리는 wandb-cleanup → ckpt-cleanup 순서 권장.

## ★핵심 메커니즘 (모르면 삽질 반복 — 판단근거 이식)

**wandb에는 "전역 run 눈끄기" API가 없다.** UI 눈 버튼(deactivate)은 workspace **view 단위** 설정으로, view spec의 `section.runSets[0].selections.tree` 리스트에 run_id가 들어있으면 그 view에서 hidden이다(tree = 숨김 목록; `root=1`(all-visible)의 예외 목록).

사용자가 실제 보는 화면 = **personal default workspace** (internal name `nw-nwuser<entity>-w`, "-w" suffix, displayName `"<Name>'s workspace"`).

**함정 2종** (`wandb-workspaces` 라이브러리):
1. `Workspace.from_url()`/`View.from_name()`이 personal default를 못 부른다 — `_url_query_str_to_internal_name`이 항상 "-v" suffix를 만드는데 실제 이름은 "-w"로 끝나 매치 불가.
2. raw spec을 `WorkspaceViewspec.model_validate_json()`으로 파싱하면 UI에서 리사이즈된 fractional `boxHeight`(예 295.71875)를 int로 검증하려다 `ValidationError` 크래시.

**→ 해법 (raw GraphQL 우회, append-only 멱등)**: Workspace/View pydantic 객체를 아예 우회한다. `allViews(viewType="project-view", viewName="nw-nwuser<entity>-w")` 조회 → `json.loads(spec)` → tree에 run_id append(=hidden)/remove(=visible), 그 외 필드는 원본 유지 → `upsertView` mutation에 **원래 view id를 실어** 호출(백엔드 UPDATE, `inserted=False`). id를 비우거나 `save_as_new_view()`를 쓰면 항상 새 view를 INSERT(`nw-xxxxx-v`) → 사용자 기본 화면엔 반영 안 됨(= "API는 성공인데 눈이 안 꺼진" 흔한 실패 원인).

**★검증 규칙**: "API 재로드 시 tree에 run_id 있음"만으로 성공 선언 금지 — 새 view에 저장하면 API 확인은 통과하나 UI엔 안 보인다. **브라우저 육안 확인이 최종 증거**.

## 3계층 규칙
- **유의미 실험 대표**(멀티시드면 대표 1개): 태그 `[keep + 기둥 + 세부]` + visible(tree에서 제외).
- **애매 그룹 대표**(그룹당 1개): 태그 `[기둥 + ambiguous]` + hidden(tree append).
- **나머지**(유의미의 비대표 시드/arm + 비유의미): 태그 `[]` (제거) + hidden.

기둥 태그(experiment 이름 키워드 매핑, 최대 3): **프로젝트별로 정의** — 그 프로젝트의 실험 계열/트랙(도메인 축)을 태그로 매핑, Confluence 하위 페이지 매칭용으로 최소 1개. (스킬이 처음 만들어진 프로젝트의 기둥 예시: biological / efficiency / modularity / transplant / xai — 참고용일 뿐, 실제로는 사용 프로젝트에 맞게 새로 정의한다.)

## § 숨김 vs 삭제 선택 (MANDATORY — AskUserQuestion, 2026-07-23 사용자 지시 신설)

3계층 분류 + dryrun 검토 직후, **apply 전에** 아래 2개를 AskUserQuestion으로 반드시 묻는다. 기본값 = **숨김만**(삭제는 명시적 opt-in). ★삭제는 **되돌리기 불가**(run의 메트릭·config·아티팩트 영구 소멸) — hide(tree append)의 cosmetic·reversible과 근본적으로 다르다.

**Q1. 이번에 대표로 선정되지 않은 run("나머지" tier)을 어떻게?**
- ① 숨김만 (hidden, tree append — 되돌리기 가능) — **기본·권고**
- ② 완전 삭제 (`wandb.Api().run(path).delete()` — 영구)

**Q2. 이미 숨겨진(기존 unvisible) run은?**
- ③ 그대로 둠 — **기본**
- ④ 이참에 삭제 (영구)

**처리 분기**:
- 숨김 선택(①③) → 기존 tag+tree append 흐름 그대로(아래 절차).
- 삭제 선택(②④) → **별도 user-approved 삭제 경로**: 현 스크립트(tag+tree)는 run을 삭제하지 않는다. 삭제 대상 run_id 목록을 임시 스크립트(`wandb.Api().run("<entity>/<project>/<run_id>").delete()`)로 저장 → 삭제 전 **run_id·이름·핵심 메트릭 스냅샷 JSON 백업**(삭제는 원복 불가라 기록만이라도 남긴다) → 사용자 육안 확인 후 **사용자 직접 실행**(wandb 파괴 write = `code-execution.md`의 dry-run 예외에 해당 안 됨, AI 실행 금지).

**가드**: 대표(keep)·ambiguous tier는 삭제 후보에서 **항상 제외** — 삭제는 "나머지" tier와 "기존 hidden" run에만. 삭제 실행 전 삭제 수가 dryrun의 해당 집합 수와 일치하는지 재확인.

**가드 2 — 삭제 실행 시점은 /ckpt-cleanup 완주 후 (매칭 스킬 정합)**: `/ckpt-cleanup`은 wandb run의 state·태그를 **live 조회**해 KEEP/DELETE/HOLD를 분류한다 — run을 먼저 삭제하면 해당 ckpt가 전부 unmatched→HOLD로 빠져 디스크 정리 효과가 사라진다. 삭제 opt-in(②/④) 시 순서: 태그/tree apply → `/ckpt-cleanup` 완주 → 삭제 스크립트 실행(사용자 직접). ckpt-cleanup을 쓰지 않는 프로젝트만 즉시 삭제 가능.

## 실행 경로 (스크립트 없을 때 — URL 기반 경량 경로)

스크립트(`tools/wandb_cleanup/`)가 없거나 새 프로젝트면, 이 경량 경로로 진행한다. **단 wandb run 삭제·수정 등 write 로직은 즉석 실행 금지(code-execution.md) — 임시 스크립트로 저장 후 사용자가 직접 실행**(read-only 조회는 탐색성 실행으로 허용). 영구 스크립트를 `tools/`에 만들지 않을 뿐, write 코드는 임시 폴더(scratchpad)에 파일로 저장해 실행 명령서로 넘긴다:

0. **각 프로젝트의 personal workspace URL을 사용자에게 요청** — 실제 URL로 entity/project/view를 특정해 `from_url`의 -v/-w suffix 함정(§ 함정 2종 #1)을 우회한다. (URL만으로 write가 되는 건 아니고, 사용자가 실제 보는 view를 확실히 특정하는 용도. URL의 `nw=`/`workspace=` 파라미터 → view internal name.)
1. `allViews(viewName="nw-nwuser<entity>-w"` 또는 URL에서 특정된 이름`)`으로 raw spec 조회 → 3계층 분류 + tree 계획을 inline python으로 산출(read-only dryrun, write 0).
2. 사용자 검토(유의미 대표 목록 + 눈끄기 수 — **이 시점에 § 숨김 vs 삭제 선택 Q1·Q2 AskUserQuestion 필수**, 스크립트 경로와 동형) → 승인 후 **mutation 전 백업 저장 (MANDATORY)**: 원본 view spec 전체 + 변경 대상 run들의 현재 태그를 임시 폴더에 JSON으로 저장 — 스크립트 경로의 자동 백업과 동등한 원복 근거로, 이게 없으면 § 되돌리기가 불가능하다 → `json.loads(spec)` → tree append/remove → `upsertView`에 **원래 view id를 실어** UPDATE(inline) → 육안 확인.

## 절차 (스크립트 보유 시)
1. **dryrun**: `.venv/bin/python3 tools/wandb_cleanup/wandb_3tier_dryrun.py` — live 재조회 + 3계층 분류 + 계획 JSON 산출(write 0). 유의미 대표 목록·기둥 분포·tree 계획 검토.
2. **사용자 검토** (MANDATORY): 유의미 대표 전체 목록 + 눈끄기 대상 수를 사용자에게 보여주고 승인받는다. → **이 시점에 § 숨김 vs 삭제 선택(Q1·Q2) AskUserQuestion 필수** — 나머지 tier·기존 hidden run을 숨김만 할지 삭제할지 확정 후 다음 단계.
3. **plan sanity check**: `... wandb_3tier_apply.py --plan` — 태그 변경 대상 수가 dryrun과 일치하는지 확인(write 0).
4. **apply**: `I_UNDERSTAND_THIS_WRITES_TO_WANDB=1 ... wandb_3tier_apply.py --apply` — 태그 + tree 실제 적용. 실행 전 태그/tree 자동 백업 JSON 저장.
5. **육안 확인**: 사용자가 `wandb.ai/<entity>/<project>` 새로고침 → 대표만 visible인지 확인.

개별 run 몇 개만 끄려면: `wandb_hide3_default_workspace.py --run-ids <id...>` (같은 tree-append 방식).

## 되돌리기
apply 시 자동 저장된 `*_tags_backup_before_apply.json` / `*_tree_backup_before_apply.json`(경량 경로는 step 2에서 임시 폴더에 저장한 백업 JSON)으로 원복. tree는 해당 id를 다시 빼고 `upsertView` UPDATE(cosmetic 변경, 데이터/실험 무관).

## 주의 (환경별 · 실행 규칙)
- `--entity`/`--project`/`--view-id`/`--view-internal-name`는 프로젝트마다 다르다 — `allViews`로 personal default view(`nw-nwuser<entity>-w`)의 id를 먼저 조회해 지정.
- 대표 선정 기본 = 그룹 내 최이른 `created_at`. 기둥 매핑 0매치 시 `model.name` 계열로 추론(프로젝트 도메인에 맞춰 보정 필요).
- ★실제 mutation(태그/tree write)은 **사용자 승인 후** 실행 — wandb write는 코드 실행 규칙의 "검증(dry-run/lint/test) 예외"에 해당하지 않는다. dryrun/--plan은 read-only라 자동 실행 가능.
