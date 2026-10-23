---
description: "Use when: 새 실험 설계, config 수정, dry-run 검증, 실험 결과 분석, 'wandb', 'Phase', 'ablation' 키워드."
model: inherit
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - AskUserQuestion
  - mcp__mem0__add_memory
  - mcp__mem0__search_memories
  - mcp__mem0__update_memory
  - mcp__mem0__get_memories
---

# Experiment Setup

새 실험을 설계하고 실행 준비를 자동화. 재현성 기준, 실험 워크플로우, 결과 분석 절차 내장.

## 실행 흐름

$ARGUMENTS 파싱 후 순서대로(아래 1~7 은 코드 완성 트랙의 준비 걸음이며, 단계 정의와 실험 트랙 진입 조건은 § 실험 워크플로우가 정본이다):

0. intent 확인: `intent/YYYY-MM-DD-<slug>.md` 가 커밋돼 있어야 한다(§ 코드 완성 트랙 Stage 0, 없으면 `/intent` 선행)
1. 실험 유형 확인: `ablation` / `new-feature` / `baseline` / `sweep` / `results`
2. 현재 config (train.yaml, task/*.yaml) 읽기
3. 재현성 체크리스트 적용 (§ 재현성 참조)
4. Hydra config 생성/수정 (config/task/ 하위)
5. wandb run name 규칙 적용: `{단계}-{모델}-{변수}-{MMDD}`
6. dry-run: `wandb=disabled trainer.fast_dev_run=true`. 해당 Stage(A~D)의 완료 기준(§ 코드 완성 트랙 표, Stage B 는 TDD 선택지 포함)을 충족할 때까지 반복
7. 실패 시 에러 분석. Stage D 통과 뒤에만 실행 명령서를 낸다: § Stage D 완료 시 필수(목표 표 선행)와 § 실험 트랙 진입 전 체크리스트를 거쳐 `launch-set.sh launch --intent <경로>` 발사 세트(가드·와쳐·목표 표)로 낸다

이 스킬이 Agent 를 spawn 할 때(qa 검증·tutor·docs 등) prompt 서두에 `[SKILL_DEPTH: 1]` 을 넣는다(discuss 와 같은 표기, `rules/agent-routing.md` § SKILL_DEPTH 전달).

## 실험 유형별 동작

| 유형 | 동작 |
|------|------|
| `ablation` | 변경 변수 1개씩 격리, 동일 seed로 fair comparison config 생성 |
| `new-feature` | 새 모듈 추가, `torchinfo.summary()` / `thop`으로 파라미터 수 확인 |
| `baseline` | best config 기준 재현성 체크 |
| `sweep` | Hydra multirun 설정 생성, 탐색 범위 명시 |
| `results` | wandb URL 기반 결과 분석 스크립트 생성 |

**재현성 자동 삽입**: `seed_everything` 호출 확인 / config `seed` 키 확인 / CUDA·패키지 버전 wandb 기록 확인

**GPU 메모리 예측** (new-feature / sweep 시): `torchinfo.summary()` 또는 `thop`으로 파라미터·FLOPs 확인. DeepSpeed/LoRA 변경 시 예상 메모리 vs 실제 GPU 용량 비교.

---

## § 자가진화 동결 마커 (Stage A 진입 시 MANDATORY)

자가진화 동결 마커 생성: `mkdir -p ~/.claude/_bench && touch ~/.claude/_bench/.experiment_active`
(실험 중 preference-gated 자가진화 Tier-2/slow update 차단 — CLAUDE.md 규칙8 준수)

> **가드 컨벤션**: 자가진화 트리거(regression-blind/slow update)는 서두에서 `[ -f ~/.claude/_bench/.experiment_active ] && { echo '실험 활성 — 진화 보류'; exit 0; }` 로 체크한다.

## § Mem0 Prior 검색 (Stage A 시작 시 MANDATORY)

→ mem0-auto.md T11 참조 (4채널 순차 검색)

prior 결과 있으면: "이전 실험에서 {config}로 {metric}={값} 달성" 표시 → Go/NoGo 판단 반영.

### § Tavily SOTA 검색 + citation-verifier 베이스라인 검증 (Stage A 보강)

→ tavily-auto.md §1 SOTA 쿼리 참조 → "현재 SOTA: {모델}={값} ({출처})" 표시 (searcher가 SOTA 수치 발견)
→ **citation-verifier 베이스라인 검증**: SOTA/베이스라인 논문에 대해 citation-verifier 소집으로 검증(철회게이트+stance)
  - editorialNotices 확인 → 철회/정정 논문 기반 실험 방지
  - supporting/contrasting 비율로 학계 합의 수준 확인
  - 검증 결과 저장: → mem0-templates.md T21 참조

## § Mem0 결과 저장 (Phase 완료 시 MANDATORY)

→ mem0-auto.md T10 참조

---

## § 실험 워크플로우 (코드 완성 → 실험 트랙)

```
코드 완성 트랙 (Stage A~D)
         │
         ▼  ← 이 경계를 넘으면 코드 수정 금지
실험 트랙 (Phase 1~N)
```

- **코드 완성 트랙 중 실험 금지**: dry-run(fast_dev_run=true)만 허용
- **실험 트랙 진입 후 코드 수정 금지**: 버그 발견 시 실험 중단 → 코드 트랙 복귀 → 재검증 후 재진입

### 코드 완성 트랙 (Stage A~D)

| 스테이지 | 내용 | 완료 기준 |
|----------|------|----------|
| **0 · intent** | 의뢰서 `intent/YYYY-MM-DD-<slug>.md` 작성·사용자 교정·커밋(`/intent` — 문제·제안 결과·영향·제약·열린 질문·**전제**). 2026-09-06 사용자 지시 | intent.md 커밋 SHA (Stage A 진입 조건) |
| **0.5 · 심사 시각 점검** | 설계(의뢰서) 확정 뒤 researcher «심사 시각 점검» 1회(citation-verifier 가 공개 심사평 사례 수집). 보고서 `intent/<의뢰서 이름>.review.md`, 판정 «그대로 진행 / 고친 뒤 진행 / 재설계» 는 조언이며 진행 여부는 사용자 결정. 새 실험 차수·새 판 설계마다 적용하고 승인된 설계의 재개·시드 추가·같은 설정 재발사는 면제. 정본 `rules-lazy/design-review-check.md` (2026-10-12) | 보고서 경로·판정·사용자 결정 기록 (Stage A 진입 조건) |
| **A** | 신규 모델 동작 검증 + 버그 수정 | 핵심 dry-run PASS |
| **B** | Ablation용 변형 구현 | 변형 dry-run PASS |
| **C** | Auto/고급 모드 구현 | Auto mode dry-run PASS |
| **D** | 전체 통합 dry-run | 모든 조합 PASS |

### Stage 0~B 설계 점검 항목 (2026-10-17 사용자 지시)

> 근거: 한 설계 사이클에서 관찰된 반복 실패만 항목으로 만들었다. Stage 진입 때 main 이 항목마다 «확인 / 해당 없음» 을 보고에 적는다.

**Stage 0(의뢰서) 진입·교정 중**
- 새 실험은 의뢰서 커밋 전에 브랜치·폴더·실험 이름·문서 트리를 이전 실험과 분리한다(종료된 실험의 트리를 상속하지 않는다).
- 판정 규칙·시드 규칙·체크포인트 선택 규칙·분할을 학습 전에 고정하고, 판정 규칙을 바꾸는 결정은 그 자리에서 «같을 때 통과 확률» 모의로 실현 가능성을 확인한 뒤 확정한다(검사가 떨어질 수 있는지 먼저 본다).
- 보조 판·기준판을 선택지에 올리기 전에 공식 레시피·가중치 존재와 «추가 학습 없이 재현 가능한가» 를 먼저 조사해 사실로 싣고, 재현 절차는 원문 대조 뒤 확정한다. 평가 셋 오염(사전학습 자료 겹침)은 분할 고정 전에 검사한다.
- 결정 선택지 표는 처음부터 «쉬운 설명·예시» 열을 갖추고, 결정은 즉시 decisions.md 에 원문·뜻·기각안·알려진 결함으로 남기며 참조는 라운드 꼬리표로 한다.
- **설계 교정이 쌓일 때마다 «학습이 드는 판 전부» 의 판 수·기간 총량을 판 수 스크립트로 그 자리에서 다시 계산해 보여 준다**(규칙 하나하나는 합리적이어도 곱으로 커진다). 기간은 처리량 가정이 아니라 실측(처리량 정본은 파일로 저장)으로만 약속한다.
- 1단계는 «핵심 질문에 답하는 최소 판» 을 먼저 정의하고 나머지 축은 후속 후보 목록으로 둔다. 축소 직후 «주 판정이 핵심 질문과 같은 명제인가» 를 다시 점검한다.
- 결정 라운드가 길어지면 끝에 정본 «최종 설정 표» 하나로 접어 plan 이 옮길 대상을 하나로 만든다. 문서 게시 시점과 사전 등록 근거(커밋 SHA)가 어디에 남는지도 설계 단계에서 정한다.

**Stage 0.5(심사·외부 검토)**
- 외부 검토 묶음은 결정 기록과 행마다 대조하고, 골격에 «이미 처리한 함정» 을 한 줄씩 적어 오독 지적을 줄인다. 판정 구조는 모의·파일럿 «전에» 외부 검토를 한 번 거치고, 축소안도 «동의 여부» 형태로 다시 보낸다.
- 검토 지적은 매 라운드 «사용자 결정이 필요한 것» 과 «기술 보완» 으로 갈라, 기술 보완은 같은 사이클 승인 범위에서 바로 반영·재확인한다. 심사 지적은 한 번에 쏟지 않고 한두 건씩 제시한다.
- 의뢰서의 환경 사실(«설치됨» 등)은 plan 전에 명령으로 다시 확인하고, 공식 레시피가 가정한 자원(GPU 수·전체 배치)을 의뢰서 단계에서 정한다. 판정 셋 크기를 바꾸면 표본 변동 처리와 시드 수 모의를 함께 다시 본다. 적응형 시드 늘리기와 사전 등록의 충돌은 설계 단계에서 다룬다.

**Stage A/B(자원·발사 전)**
- 동시 실행을 정하기 전에 호스트 RAM·메모리 가드·GPU 예산을 계산한다. RSS 합은 작업자 공유 메모리를 겹쳐 세어 과대이므로 cgroup 메모리로 잡고, 병렬 특징 추출은 프로세스마다 torch 스레드를 묶는다.
- 판정 경로 판을 다른 판보다 먼저 자원에 넣는 «임계 경로 먼저» 순서를 단계 설계 때 정한다(발사기 사이에 우선순위가 없으면 비판정 판이 먼저 자리를 차지한다). 비싼 단계 앞에는 «싸게 일찍 실패를 알리는 판» 을 두고 경보가 뜨면 중단 여부는 사용자에게 올린다.
- 하위 plan 사이 공유 객체(판 기록 등)의 소유·쓰기 규칙을 상위 plan 에 명시한다. 단계 사이 관문은 «자동 중단 하한 + 그 밖은 사용자 결정» 으로 둔다.

### Stage B 진입 시 TDD 선택지 (MANDATORY — Stage B 시작 직후 출력)

Stage B(Ablation용 변형 구현) 시작 시 아래 선택지를 사용자에게 제시한다. **선택 없이 자동 진행 금지**.

```
🔀 Stage B 구현 방식 선택:

1. **일반 구현** (기본) — 코드 작성 후 qa 검증. 빠른 프로토타입에 적합.
2. **TDD 구현** — 테스트 먼저 작성(RED) → 구현(GREEN) → qa 검증(REFACTOR).
   → 권장 시점: Stage A에서 인터페이스가 완전히 확정된 경우
   → 효과: T38(음성 결과) 분석 시 "구현 결함 vs 가설 실패" 구분이 명확해짐

어느 방식으로 진행할까요? (1/2, 기본값: 1)
```

**TDD(2번) 선택 시 Stage B 흐름**:
1. **RED**: `test_{모듈명}.py` 먼저 작성 (아직 구현 없으므로 실패 예상)
   - 테스트 파일 저장 위치: 프로젝트 `tests/` 하위
2. **GREEN**: 실제 모듈 구현 → 테스트 통과
3. **REFACTOR**: qa 에이전트 검증 (Stage B 완료 기준 동일: 변형 dry-run PASS)

> ⚠️ **제약**: 실험 중 리팩토링 금지 원칙(CLAUDE.md 규칙 8) 준수 — REFACTOR 단계는 인터페이스 변경 없는 내부 정리만 허용. 구조 변경 필요 시 Stage A로 복귀.

**일반(1번) 선택 또는 응답 없음**: 기존 흐름 그대로 진행.

**Stage D 완료 시 필수**:
1. dry-run 폴더 전체 삭제: `rm -rf {save_path}/*/train_run_*` (사용자 직접 또는 승인 후)
2. 최종 코드 커밋 + **push 명령 안내** (push는 사용자 직접 — `agents/gitops.md` 원칙)
3. **코드 확정 태그 제안**: `code-freeze-{MMDD}` — 실험 재현 앵커 (`agents/gitops.md` § 태그 규칙, 승인 시 생성). Phase 완료 시에도 `phase{N}-complete` 동일 절차
4. "코드 확정 완료, 실험 트랙 진입합니다" 사용자 보고
5. 실험 트랙의 발사 명령서(및 드라이런 완료 보고)는 `rules-lazy/background-task.md` § 학습 목표 표(run별 목표 한 줄 + 총 건수, 통제 arm은 기준선 명시)를 **먼저** 출력한다 — HARD GATE, 표 없는 명령서는 미완성(2026-08-28)

## § discuss 사전 추천 (실행 전 자동 체크)

| 조건 | 추천 |
|------|------|
| 아키텍처 변경 수반 | ✅ 추천 |
| 생물학적 타당성 검증 필요 | ✅ 추천 |
| 하이퍼파라미터 대폭 변경 | ✅ 추천 |
| 새로운 데이터셋 도입 | ✅ 추천 |
| 단순 config 미세 조정 | ❌ 비추천 |
| 이미 합의된 계획 실행 | ❌ 비추천 |

출력:
```
📋 discuss 사전 추천:
추천 여부: ✅/❌ | 근거: {조건} | 예상 참여자: {에이전트} (추천 시)
discuss를 먼저 진행할까요? (Y/N)
```

### 실험 트랙 진입 전 체크리스트

- [ ] intent.md 승인·커밋 완료(SHA) — 발사 명령서의 `launch-set.sh launch --intent <경로>`가 이 파일을 가리킨다
- [ ] 점검 보고서 경로와 판정, 사용자 결정 기록 완료(`intent/<의뢰서 이름>.review.md`, 정본 `rules-lazy/design-review-check.md`). 면제: 승인된 설계의 재개·시드 추가·같은 설정 재발사. `launch-set.sh` 가 보고서 유무를 state 에 기록하고 없으면 경고한다(차단 아님)
- [ ] Stage D 완료 (모든 dry-run PASS)
- [ ] dry-run 폴더 삭제 완료
- [ ] 최종 코드 커밋 완료
- [ ] `run_trains.py` 실험 목록 작성 완료
- [ ] 재현성 체크리스트 통과

### 실험 중 금지 사항

- 코드 파일(`.py`) 수정 — 어떤 이유로도 금지
- config 값 변경 (실험 설계 변경 = 코드 트랙 복귀 필요)
- 진행 중 실험 강제 중단 후 파라미터 조정 재실행

### 실험 중 버그 발견 시 복귀 절차

1. 실험 중단 → wandb run에 `ABORTED` 태그 + 중단 이유 메모
2. 중단 시점까지의 metric을 experiments.md에 임시 보존
3. **코드 트랙 복귀** → Stage D 재통과 → 실험 트랙 재진입
4. 완료 후 wandb run 태그 `BUG_FIXED` 추가 → 재실험 계획

---

## § 재현성 체크리스트

### 코드 레벨
- [ ] `seed_everything(seed, workers=True)` 호출 확인
- [ ] `torch.backends.cudnn.deterministic = True` 설정
- [ ] DataLoader `num_workers > 0` 시 `worker_init_fn` seed 설정
- [ ] Hydra config에 `seed` 키 명시 + wandb 기록

### 환경 레벨
- [ ] `uv.lock` commit 여부 (의존성 고정)
- [ ] CUDA / cuDNN 버전 wandb config 기록
- [ ] DeepSpeed / PEFT / LoRA 버전 기록
- [ ] **import 버전 검증** (#6 추가 — 잘못된 버전 silent load 방지): 핵심 라이브러리 import 직후 `print(torch.__version__, lightning.__version__)` 명시 — `uv.lock` 외 경로(pip/conda 혼재) 설치 검출

### 실험 명명 (wandb run name)

형식: `{실험단계}-{모델약어}-{주요변수}-{MMDD}`

예시: `s1-evax-lr1e4-0224` (Stage1, EVA-X, lr=1e-4, 2/24)

**결과 보고 기준**: 단일 수치 금지 → **mean ± std (N ≥ 3 runs)** 또는 사용 seed 전체 명시. 논문 테이블 수치는 wandb run URL / config hash로 추적 가능하게 유지.

---

## § 결과 분석 (wandb 기반)

**트리거**: `/experiment results` 또는 wandb URL + 실험 완료 알림 제공 시.

자가진화 동결 해제: `rm -f ~/.claude/_bench/.experiment_active`

**사용자 제공 항목**:
- wandb URL: `https://wandb.ai/{entity}/{project}/runs/{run_id}`
- 체크포인트 경로: `{save_path}/train_run_*/checkpoints/*.ckpt`

### 분석 절차

**Step 1: 결과 추출 스크립트** — `<프로젝트>/.scratch/<세션 id>/analyze_{phase}_{MMDD}.py`

추출: `run.history(keys=[...], pandas=True)` / `run.summary` / `run.config` / best checkpoint 최고 수치
기준: 독립 실행 가능 / run name 파싱: `re.match(r'^(p\d+)-(.+?)-{dataset}-s(\d+)', name)` / `wandb.Api(timeout=60)` 재사용

**Step 2: 체크포인트 교차 검증** — 파일명에서 epoch/top1_acc 추출 → wandb best 수치 비교 → 불일치 시 사용자 보고

**Step 3: 결과 집계 보고**:
```
=== Phase N: {설명} — BEST checkpoint 기준 ===
어댑터              S42        S123       Mean±Std
LoRA              0.XXXX     0.XXXX    0.XXXX±0.XXXX
```

> **설명 형식 (MANDATORY)**: 비교축이 있는 결과 보고·문서화는 `rules-lazy/experiment-result-explanation.md` 순서(전체표 → 축별 분해(이상값 row) → 열/행 해석 → 종합)를 따른다.
> arm 간 차이의 검정·효과 크기·필요 시드 수는 researcher가 `/statistical-analysis`·`/statistical-power`로 낸다(설치 시). 시드 3개 미만 비교는 눈금(val 분해능) 안이라 결론 금지.
> **이해도 확인 (선택 제안, 2026-08-25)**: 결과 집계 보고 말미에 "이 결과 해석을 tutor 퀴즈로 확인할까요?"를 1줄 제안한다(직접 실행 금지). 수락 시 **tutor**(`agents/tutor.md`)가 결과 보고·분석 스크립트 출력을 재료로 3~5문항 루프를 돈다(`skills/paper-read/SKILL.md` Step 7 절차, 저장은 실험 폴더(해당 실험의 기록 폴더 = `docs/experiments/{실험명}/` 또는 config·README가 가리키는 실험 디렉터리, 5라운드 경로 정의) `quiz.md`(문항·라운드 상태) + `quiz-key.md`(정답, main은 채점 직전에만) + `quiz-search.log`(main만 append)). 쓰기 경계 사후 검증은 이 실험 폴더를 재료 폴더로 `agents/tutor.md` § 파일 쓰기 경계(`spawn-tree.sh snapshot`/`check`, `RESULT: PASS` 원문 인용)를 그대로 적용하고, "이해도 확인 완료" 선언은 `agents/tutor.md` § 상호작용 모델 "종료" 항목의 `evidence-ls.sh` 원문 인용 규약을 따른다(9·13라운드: research·discuss와 동일).

**스크립트 실행** (사용자 직접):
```bash
uv run python <프로젝트>/.scratch/<세션 id>/analyze_{phase}_{MMDD}.py
```

**결과 활용**:
1. 공식 수치: wandb `run.history()` 기반 best checkpoint
2. Confluence 업데이트: `/confluence` 스킬
3. 논문 테이블: `docs/paper/` 해당 섹션 수치 업데이트

## § 학습 사이클 종료 후 정리 게이트 (2026-07-20 사용자 지시)

**트리거**: 학습 사이클(Phase의 전체 run)이 모두 종료 확인된 뒤, § 결과 분석 보고까지 완료된 시점. `/loop` 학습 모니터링이 완료로 종료될 때도 동일 (`rules-lazy/loop-auto.md` § 학습 완료 시 정리 게이트).

결과 보고 말미에 아래 질문을 반드시 제시한다 (스킬 자동 제안 원칙 — 질문만, 자동 실행 금지):

```
🧹 학습 사이클 종료 — 정리를 진행할까요? (복수 선택 가능)
  A) /wandb-cleanup — wandb run 3계층 태그 + 눈끄기 정리
  B) /ckpt-cleanup — 실패·비유의미 run 체크포인트 삭제 계획 산출 (삭제 실행은 직접)
  C) 나중에 (이번 세션에서 재질문 안 함)
```

- wandb 미사용 학습이면 B만 제시 (ckpt-cleanup은 인벤토리 모드로 동작).
- 권장 순서 A → B: ckpt-cleanup의 분류 신호가 wandb-cleanup의 3계층 태그(keep/ambiguous/무태그)이기 때문.
- B의 실제 삭제(rm)는 항상 사용자 직접 실행 — 스크립트는 purge 계획 산출까지만 (`skills/ckpt-cleanup/SKILL.md` ★안전 원칙).

## § QMD 변환 (실험 결과 보고서 자동 생성)

> **상세**: `agents/docs.md` § Quarto Markdown (.qmd) 처리 참조
> **트리거**: 실험 완료 후 결과를 `.qmd` 형식으로 정리하면 docs 에이전트가 Confluence/HTML/PDF 자동 생성 가능

### 활용 시나리오
- Phase 완료 후 wandb 분석 결과 + Figure + 결론을 단일 `.qmd`로 통합
- `.qmd` 안에 `python` 청크로 wandb history 호출 → 결과 표 자동 임베드
- docs 에이전트에 `.qmd` 경로 전달 → Confluence 페이지 자동 생성

### 권장 구조 (`outputs/reports/phase{N}.qmd`)
```yaml
---
title: "Phase N 결과"
format: confluence
---
```
+ python 청크(wandb 결과) + matplotlib figure + 해석 본문

### 의존성
quarto CLI 미설치 시 docs 에이전트가 안내 (uv tool install quarto-cli)
