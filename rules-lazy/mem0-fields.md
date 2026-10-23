# Mem0 카테고리별 필드 카탈로그

> **로드 시점**: 자동 — `add_memory` 호출 시 카테고리 필드 누락 방지를 위해 참조
> **연관 파일**: `rules/mem0-auto.md` (마스터 테이블), `rules-lazy/mem0-templates.md` (T01~T41 호출 템플릿)
> **핵심 원칙**: `add_memory` text에 아래 카테고리별 필수 필드를 모두 포함. 누락 시 나중에 복구가 불가능하므로 저장 시점에 최대한 구체적으로 기록.

---

## §3.0 카테고리별 필드 카탈로그 (MANDATORY)

### `decision` 카테고리

| 필드 | 필수/선택 | 예시 |
|------|---------|------|
| 날짜 | 필수 | `2026-04-16` |
| 프로젝트명 | 필수 | `claude-global` |
| 결정 요약 | 필수 | `Mem0 프로젝트명 강제화` |
| 결정 내용 상세 | 필수 | `text 서두 [프로젝트명] 토큰 MANDATORY` |
| 근거 | 필수 | `크로스 프로젝트 오염 방지` |
| 영향 범위 | 필수 | `mem0-auto.md §1.1, 모든 add_memory 호출부` |
| 관련 파일/심볼 | 선택 | `rules/mem0-auto.md, rules-lazy/memory-write.md` |
| 관련 이슈/PR | 선택 | `Workflow A Phase 1` |
| 번복 조건 | 선택 | `Mem0 metadata 스키마 변경 시 재검토` |

### `experiment` 카테고리

| 필드 | 필수/선택 | 예시 |
|------|---------|------|
| 날짜 | 필수 | `2026-04-16` |
| 프로젝트명 | 필수 | `my-project` |
| Phase/Stage | 필수 | `Phase 2 / Stage B` |
| 모델 | 필수 | `ResNet50 + LoRA rank=8` |
| 데이터셋 | 필수 | `CIFAR-100 (50K/10K split, seed=42)` |
| Config 전체 | 필수 | `lr=3e-4, batch=128, epochs=100, optimizer=AdamW, weight_decay=1e-4` |
| 시드 | 필수 | `42, 123, 2024 (N=3)` |
| 결과 수치 | 필수 | `val_acc=87.3±0.4%, best_epoch=67, train_loss=0.234` |
| wandb URL | 선택 | `https://wandb.ai/.../runs/xyz123` |
| 베이스라인 비교 | 선택 | `Full FT 88.1% 대비 -0.8% (파라미터 1/50)` |
| 특이 관찰 | 선택 | `epoch 40 이후 val_acc 안정 수렴` |
| 코드 commit hash | 선택 | `b27053f` |

### `code_pattern` 카테고리

| 필드 | 필수/선택 | 예시 |
|------|---------|------|
| 날짜 | 필수 | `2026-04-16` |
| 프로젝트명 | 필수 | `claude-global` |
| 파일 경로 | 필수 | `src/models/core.py:L123` |
| 함수/클래스 | 필수 | `UniversalModel.forward` |
| 패턴 종류 | 필수 | `QA 실패 / 리팩토링 / 컨벤션 / 경로 / 버그` |
| 문제 상황 | 필수 | `call-site 시그니처 불일치 — pred_transforms 누락` |
| 해결 방법 | 필수 | `MakoDataModule 호출부 3곳 동기화` |
| 재발 방지 조건 | 선택 | `QA 체크리스트 2번(call-site 영향) 강제` |
| 관련 테스트 | 선택 | `tests/test_datamodule.py::test_transforms_passed` |
| **`failure_type`** (metadata) | 선택 — T04 distillation | 실패 버킷(군집 키), 반복 실패 유형 집계용: `logic`·`shape`·`type`·`import`·`config`·`race`·`num-precision`·`기타` (`mem0-templates.md` T04 와 같은 뜻) |
| **`pattern`** (metadata) | 선택 — T04 distillation | kebab-case 식별자, 예: `tensor-shape-mismatch`, `zero-division-loss` |
| **`trigger_signature`** (metadata) | T04 필수 (없으면 일반 code_pattern) | 재발 가능 코드 시그니처, 예: `unsqueeze + matmul`, `softmax + divide` |
| **`avoidance_rubric`** (metadata) | T04 필수 (없으면 일반 code_pattern) | 다음 회피용 사전 체크 항목 3-5개, 예: `1) shape 사전 print, 2) broadcast 규칙 확인, 3) 차원 명시화` |

> `pattern` / `trigger_signature` / `avoidance_rubric` 3개 필드는 RubricEM (Li et al. 2026, arxiv 2605.10899)의 reflection distillation 차용. `rules-lazy/mem0-templates.md` T04 참조.

### `paper` 카테고리

| 필드 | 필수/선택 | 예시 |
|------|---------|------|
| 날짜 | 필수 | `2026-04-16` |
| 프로젝트명 | 필수 | `my-project` |
| 논문 제목 | 필수 | `LoRA: Low-Rank Adaptation of Large Language Models` |
| 저자 | 필수 | `Hu et al., 2021` |
| arXiv ID / DOI | 필수 | `arXiv:2106.09685` |
| 핵심 수식 | 필수 | `h = W_0 x + BA x, where B∈R^{d×r}, A∈R^{r×k}` |
| 핵심 결과 | 필수 | `GPT-3 175B 기준 학습 파라미터 10000배 감소, 성능 동등` |
| 관련성 평가 | 필수 | `높음 — 현재 LoRA 어댑터 실험의 이론 근거` |
| 한계/반박 | 선택 | `rank 선택 기준 명확하지 않음` |
| citation-verifier 검증 | 선택 | `verdict=허용, supporting=320, contrasting=12, retracted=false, confidence=high, fulltext_coverage=partial` |
| 인용 부분 | 선택 | `Sec 4.2 Table 2 — WikiSQL rank=2 acc=73.4%` |
| invoker | 필수 (citation-verifier 검증 시) | `searcher / researcher / main-opus` |
| purpose | 필수 (citation-verifier 검증 시) | `본문 인용 / SOTA 베이스라인 / 철회 확인 / paper-read 후속 / 토론 근거` |
| actual_use | 필수 (citation-verifier 검증 시) | `YES / NO / PENDING` |
| location | 필수 (citation-verifier 검증 시) | `src/models/lora.py:L42` 또는 `docs/paper/sec3.tex` 또는 `"테스트 호출만"` |
| status | 필수 (citation-verifier 검증 시) | `pending_review / implemented / cited / rejected / on_hold` |
| updated_at | 필수 (citation-verifier 검증 시) | `YYYY-MM-DD` |
| summary | 필수 (citation-verifier 검증 시) | 한 줄 판단 이유 |

> citation-verifier 검증 외 일반 paper 저장(T08, /paper-read)은 기존 필드(invoker 위 항목)만 사용한다.

### `feedback` 카테고리

| 필드 | 필수/선택 | 예시 |
|------|---------|------|
| 날짜 | 필수 | `2026-04-16` |
| 프로젝트명 | 필수 | `claude-global` (전역이면 claude-global) |
| 교정 내용 | 필수 | `응답 끝에 요약 금지` |
| 발화 원문 | 필수 | `"또 요약 달았네, 필요 없다고 했잖아"` |
| 교정 전 행동 | 필수 | `모든 응답 끝에 "요약:" 섹션 자동 포함` |
| 교정 후 행동 | 필수 | `요약 섹션 제거, 필요 시에만 1~2줄 권장사항` |
| 적용 범위 | 필수 | `전역 / 특정 프로젝트 / 특정 에이전트` |
| 관련 규칙 파일 | 선택 | `rules-lazy/answer-detail.md` |
| learner 트리거 여부 | 선택 | `크로스 세션 3회+ 감지 시 규칙 업데이트 제안 (T12 기준)` |

### `discuss` 카테고리

| 필드 | 필수/선택 | 예시 |
|------|---------|------|
| 날짜 | 필수 | `2026-04-16` |
| 프로젝트명 | 필수 | `my-project` |
| 토론 주제 | 필수 | `LoRA vs Adapter 어댑터 전략 선택` |
| 참여 에이전트 | 필수 | `planner(opus), researcher(opus), coder(sonnet), scout(haiku)` |
| 세분 항목 수 | 필수 | `3 (이론/구현/리소스)` |
| 최종 합의 | 필수 | `LoRA rank=8 채택, Adapter는 ablation 보조로만 사용` |
| 주요 근거 | 필수 | `LoRA 논문 Sec 7.1 — rank=4~8 최적 영역, 파라미터 1/50 절감` |
| 반대 의견 | 필수 | `없음 / 또는 "coder: 메모리 오버헤드 우려 — LoRA도 QKV 병합 시 동일"` |
| 라운드 수 | 선택 | `Round 2 종료 (만장일치)` |
| 회의록 경로 | 선택 | `long-term/my-project/meetings/2026/04/16/lora_vs_adapter/회의록.md` |
| 후속 작업 | 선택 | `Stage B에서 rank 4/8/16 sweep 실행` |

### `context` 카테고리

> 사용 트리거: T02(compact 백업)·T03(세션 복원)·T29/T30/T32(외부 작업 이력 — Confluence/Jira/Git)

| 필드 | 필수/선택 | 예시 |
|------|---------|------|
| 날짜 | 필수 | `2026-07-06` |
| 프로젝트명 | 필수 | `claude-global` |
| 세션 상태/맥락 | 필수 | `하네스 감사 5건 수정 완료, main ahead 16` |
| 진행률·활성 결정 | 필수(T02) | `Phase 2/3, 활성 결정: 6-Gate 개칭` |
| config·수치 원문 | 선택 | `acc=87.3%, lr=3e-4` (정확값 원문 보존) |
| 잔여 작업 | 선택 | `git push (사용자), Codex 교차검증` |
| 외부 산출물 경로 | 선택(T29/T30/T32) | `Confluence 페이지 ID / Jira 이슈 키 / 커밋 해시` |

---

## §3.0.1 필드 조합 템플릿 예시

각 카테고리 필수 필드를 모두 포함한 실제 `add_memory` text 예시:

**decision 예시 (모든 필수 필드 포함)**
```
text="2026-04-16 claude-global 결정: Mem0 프로젝트명 강제화. 내용: text 서두 [프로젝트명] 토큰 MANDATORY, metadata 변경 없음. 근거: 크로스 프로젝트 오염 방지(다른 프로젝트 검색 결과 혼입 차단). 영향 범위: mem0-auto.md §1.1 + 모든 add_memory 호출부. 관련 파일: rules/mem0-auto.md"
```

**experiment 예시 (모든 필수 필드 포함)**
```
text="2026-04-16 my-project Phase 2 Stage B: ResNet50+LoRA(rank=8), CIFAR-100(50K/10K, seed=42/123/2024). Config: lr=3e-4, batch=128, epochs=100, optimizer=AdamW, wd=1e-4. 결과: val_acc=87.3±0.4%, best_epoch=67, train_loss=0.234. wandb: runs/xyz123. 베이스라인: Full FT 88.1% 대비 -0.8%(파라미터 1/50)."
```

**code_pattern 예시 (모든 필수 필드 포함)**
```
text="2026-04-16 claude-global QA 실패: src/models/core.py:L123 UniversalModel.forward. 패턴: call-site 시그니처 불일치. 문제: pred_transforms 인자 None으로 하드코딩, MakoDataModule에서 실제 transform 미전달. 해결: MakoDataModule 호출부 3곳에서 pred_transforms 명시 전달. 재발 방지: QA 체크리스트 2번(call-site 영향) 강제."
```

**paper 예시 (모든 필수 필드 포함)**
```
text="2026-04-16 my-project 논문: LoRA: Low-Rank Adaptation of Large Language Models (Hu et al., 2021, arXiv:2106.09685). 수식: h=W_0 x+BA x, B∈R^{d×r}, A∈R^{r×k}. 결과: GPT-3 175B 기준 학습 파라미터 10000배↓ 성능 동등. 관련성: 높음 — 현재 LoRA 어댑터 실험의 이론 근거. citation-verifier: verdict=허용, supporting=320, contrasting=12, retracted=false, confidence=high, fulltext_coverage=partial. invoker=researcher. purpose=본문 인용. actual_use=YES. location=docs/paper/sec3.tex. status=cited. updated_at=2026-04-16. summary=LoRA 어댑터 이론 근거로 채택."
```

**feedback 예시 (모든 필수 필드 포함)**
```
text="2026-04-16 claude-global 교정: 응답 끝 요약 금지. 원문: '또 요약 달았네, 필요 없다고 했잖아'. 전: 모든 응답 끝에 '요약:' 섹션 자동 포함. 후: 요약 제거, 필요 시에만 1~2줄 권장사항. 범위: 전역."
```

**discuss 예시 (모든 필수 필드 포함)**
```
text="2026-04-16 my-project discuss: LoRA vs Adapter 어댑터 전략. 참여: planner(opus)+researcher(opus)+coder(sonnet)+scout(haiku). 세분 3항목(이론/구현/리소스). 합의: LoRA rank=8 채택, Adapter는 ablation 보조. 근거: LoRA 논문 Sec 7.1 rank=4~8 최적, 파라미터 1/50 절감. 반대: 없음(만장일치 Round 2 종료)."
```
