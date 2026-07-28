# QA 검증 프로세스

> **로드 시점**: 코드 수정이 발생한 모든 작업 완료 직후

## §0 검증 가능한 성공 기준 (Goal-Driven Execution — MANDATORY)

> **로드 시점**: 모든 QA 검증 시작 전
> **상세**: `agents/qa.md` § 검증 가능한 성공 기준 (Goal-Driven Execution) 참조

### QA 시작 전 필수 체크
- [ ] 사용자 요청을 **검증 가능한 형태**로 변환했는가?
- [ ] PASS/FAIL을 **객관적으로** 판단할 수 있는가?
- [ ] multi-step 작업이면 단계마다 verify 정의되었는가?

### 약한 기준 거부
"잘 동작", "정상 작동", "버그 없으면 OK", "성능 좋게" 등 모호 기준은 **거부**하고 main에 재정의 요청.

### multi-step verify 형식
```
1. [Step] {작업} → verify: {객관적 체크}
2. [Step] {작업} → verify: {객관적 체크}
```

## 적용 조건
- 코드 파일(.py, .yaml, .tex 등) 1개 이상 수정/생성/삭제된 경우
- config 값 변경이 발생한 경우

## QA 체크리스트 (순서대로 실행)

### 0. 구조적·수학적 검증 (항상 최우선 — 6-Gate의 "구조" 항목)
- 수식 일치·불변식·알고리즘 구조 검증 — 상세 체크 항목: `agents/qa.md` § 1순위 — 구조적·수학적 검증

### 1. 기획-구현 일치 확인
- 사용자가 승인한 수정 계획과 실제 변경 내용을 항목별로 대조
- 누락된 항목 또는 계획에 없는 추가 변경이 있으면 명시

### 2. 호출부(Call-site) 영향 분석
- 수정된 함수/클래스/config 키를 사용하는 **모든 호출부**를 검색 (Grep)
- 시그니처 변경(인자 추가/삭제/순서), 반환값 변경 시 호출부 동기화 확인
- 미동기화 호출부가 있으면 수정 또는 사용자 보고

### 3. Config-코드-논문 3자 일치
- 변경된 config 키가 코드에서 올바르게 참조되는지 확인
- 논문(`docs/paper/`)에 해당 값이 언급된 경우, 논문 수치와 일치하는지 확인
- 불일치 발견 시 수정 또는 사용자 보고

### 4. Import 검증
- 새로 추가된 import가 실제 사용되는지 확인 (unused import 방지)
- 삭제된 코드에서 사용하던 import가 남아있지 않은지 확인

### 5. 테스트 실행 (해당 시)
- 테스트 파일이 존재하면 관련 테스트 실행
- 실험 코드의 경우 `wandb=disabled` 상태에서 dry-run 가능 여부 확인

**silent failure 방지 (MANDATORY)**:
- [ ] `pytest -q --tb=short` 결과에서 `0 collected`, `no tests ran`, `0 passed in N.NNs` 패턴 검출 시 **즉시 FAIL** 처리 (검증 완료로 오판 ❌)
- [ ] 모든 pytest 실행 후 exit code 명시 (`echo "pytest exit:$?"`) — exit 0 + 0 collected는 FAIL
- [ ] DEPRECATION warning 누적 5+ 시 사용자 알림 (라이브러리 버전 호환성 사전 경고)

### 6. ML 실험 사전 체크 (학습 스크립트 수정 시 — 자동 트리거)
트리거 파일: `run_trains.py`, `train.py`, `config/train.yaml`, `config/task/*.yaml`, `model/` 하위
- [ ] `wandb=disabled trainer.fast_dev_run=true` dry-run 통과 여부
- [ ] 변경된 Hydra config 키가 override 구문과 일치하는지 확인
- [ ] 새 모델/레이어 추가 시 `torchinfo.summary()` 또는 `thop`으로 파라미터 수 확인
- [ ] DeepSpeed / LoRA 설정 변경 시 예상 메모리 vs 실제 GPU 용량 비교
- [ ] checkpoint 경로가 기존 실험과 충돌하지 않는지 확인
- [ ] `/experiment` 스킬 § 재현성 체크리스트 (seed, 환경 기록) 통과 여부

## 종료 조건 선택지 (MANDATORY — qa 진입 직전 main이 사용자에게 출력)

> **목적**: qa·ralph-loop의 종료 기준을 매 호출마다 사용자가 직접 결정 가능. ralph-loop 기본 6-Gate 검증(구 명칭 5-Gate — 구조 검증 추가로 6항목, ralph 진입 판단용 5-Gate와 별개)을 유지하되, 사용자 commands·작업 성격에 따라 유연성 제공. (2026-07-06 agents/qa.md에서 이관 — main 실행 항목이므로 spawn 토큰 절감)
> **적용 시점**: main이 qa 또는 `/ralph-loop` 호출 직전. **선택지 출력 없이 자동 진행 금지**.

### 선택지 형식 (MANDATORY)

```
🎯 QA 종료 조건 선택:

1. **6-Gate 전체 PASS** (기본) — 구조·기획·호출부·Config·Import·테스트 전체 통과
2. **핵심 테스트만 PASS** — lint·format·import warning 무시, business-critical test만 강제
3. **사용자 커스텀 condition** — 자유 텍스트로 condition 입력 (예: "loss < 0.1 and shape match")
4. **max cycles 조정** — 기본 5 cycle, 1~10 범위로 변경 (선택지 1/2/3과 중첩 가능)

→ 어느 옵션으로 진행할까요? (번호 / 자유 텍스트 / 기본값 진행)
```

### 사용자 응답 → condition 변환 규칙

| 응답 | 변환된 condition | max cycles |
|------|----------------|-----------|
| 1 (기본) | 6-Gate 표준 (구조·기획·호출부·Config·Import·테스트 모두 PASS) | 5 |
| 2 | "business-critical test PASS, lint·format·import warning 허용" | 5 |
| 3 + 자유 텍스트 | 사용자 입력 그대로 (검증 가능 형식으로 변환) | 5 |
| 4 + N | 1/2/3 중 재선택 후 max cycles = N | N (1~10) |
| 사용자가 "기본값" 명시 | 1번 적용 | 5 |

### 페르소나 통합 (자동 적용)

qa 페르소나 사전 할당 시: `qa.strict`+옵션1=100% 커버리지·edge case 발굴 / `qa.flexible`+옵션2=warning 허용 확대·빠른 사이클 / `qa.balanced`+옵션1=위험도 기반 차등(기본 추천) — 카탈로그: `rules-lazy/agent-personas.md` § qa

### 변환 후 실행 (2026-07-17 Codex C2 — 플러그인 충돌 제거)

변환된 condition·max cycle N은 **qa spawn prompt 4요소 `objective`에 명시**하고, 루프는 qa/main이 내부 카운터로 구동한다. **`/ralph-loop --condition/--max-cycles` 슬래시 호출 금지** — 동명 플러그인(`--max-iterations`만 지원)으로 새면 무제한 폴백. 상한 강제는 CLI가 아니라 이 파일의 종료 조건(max cycle·동일 실패 3회)이 담당.

### 생략 조건
- 사용자가 명시적 condition 함께 전달 ("qa, 단위 테스트만 PASS될 때까지")
- ralph-loop 재진입 시 (이미 condition 설정됨)

## Ralph Wiggum 루프 (테스트 반복 검증)

> **호출 스킬**: `ralph-loop:ralph-loop` (4-Gate 통과 시 qa 자율 호출)
> **적용 대상**: qa 에이전트 전용
> **비용 모델**: Pro/Max 구독 토큰만 (추가 비용 없음)

### 4 path 의사결정 (parallel-dispatch.md 결정 트리 적용)

루프 진입 → qa 자체 수정 시도 → 외부 도움 필요 시 아래 path 중 선택:

| Path | 메커니즘 | 사용 케이스 |
|------|---------|-----------|
| α — 단일 subagent | `Agent(subagent_type="...", prompt=..., result만 받음)` | 1회성 위임, 합의 불필요 |
| β — teammate | `TeamCreate(lead="qa")` + `Agent(team_name=..., name=...)` | 수정 ↔ 재검증 다회 라운드 |
| γ — parallel-dispatch | 한 turn에 Task N개 동시 호출 | multi-file 독립 수정 |
| δ — hybrid | TeamCreate(qa lead) + parallel-dispatch (coder-1, coder-2 ...) | 독립 수정 + 라운드 결합 |

### Path 선택 가이드

| 상황 | 선택 | 이유 |
|------|-----|------|
| import 오류 1줄 추가 | α | 1회성 |
| 함수 로직 수정 → qa 재검증 ↔ 재수정 가능성 | β | 반복 교환 |
| foo.py·bar.py 독립 수정 | γ | 독립 작업 2개 |
| 라이브러리 API 검색 1회 | α (searcher) | 1회성 |
| coder 2명 + qa 라운드 | δ | 독립 + 라운드 |

### qa 자율 소집권 (MANDATORY)

루프 중 qa는 필요 시 아래 에이전트를 **자율 소집**한다 — **단 소집 실행 주체 전제**: ralph 루프의 teammate 컨텍스트에선 mailbox/SendMessage로 직접 교류, 일반 subagent 컨텍스트(Agent 도구 없음)에선 main에 "coder/searcher/scout 소집 필요" 신호로 반환해 main이 대신 spawn(`rules/agent-routing.md` § "소집"의 실행 주체):

| 소집 대상 | 트리거 조건 | 사용 예시 |
|----------|-----------|---------|
| coder | 로직 변경 필요 (qa 직접 수정 범위 초과) | 함수 동작 변경, 알고리즘 수정 |
| searcher | 외부 자료 필요 (라이브러리 API 변경 등) | "ImportError: ... renamed in v3.0" → 마이그레이션 검색 |
| scout | 추가 호출부·의존성 정찰 필요 | 수정 후 영향 범위 확장 시 |

(planner/designer/docs/gitops/researcher는 자율 소집 ❌ — main 결정 영역)

### 동일 역할 중복 소집

| 역할 | 중복 한도 | 명명 규칙 |
|------|---------|----------|
| coder | ≤ 3개 | `coder-1`, `coder-2`, `coder-3` |
| searcher | ≤ 2개 | `searcher-1`, `searcher-2` |
| scout | ≤ 2개 | `scout-1`, `scout-2` |
| **총 멤버 수** | ≤ 5명 (qa lead 제외) | daemon worker 토큰 폭증 방지 |

### 5-Gate (qa 자율 소집 판단 — ralph 진입 조건)

> 진입 확정 시 main이 **작업 범위 JSON을 등록**한다(`rules-lazy/scope-gate.md` — 미등록이면 게이트는 상시 통과라 보호 효과 없음). 연속 FAIL·회귀로 되돌림이 필요해지면 `rules-lazy/rollback-procedure.md` 절차 적용. (2026-07-10 진입점 신설 — 두 룰 모두 인바운드 0이던 고아)

| Gate | 명칭 | 조건 |
|------|------|------|
| G1 | 화이트리스트 | 소집 대상이 coder/searcher/scout 중 하나 |
| G2 | 필요성 | 소집 없이 현재 루프 진행 불가 |
| G3 | 종료 조건 미충족 | PASS 미달성 + cycle < N(설정된 max cycle, 기본 5) + 무한루프 미감지 |
| G4 | 컨텍스트 < 60% | qa 현재 컨텍스트 사용량이 60% 미만 |
| G5 | 외부 신호 가용 | 테스트 결과·린트·빌드 에러 등 외부 검증 신호 존재 |

## § 외부 신호 의존성 (MANDATORY)

순수 LLM 자기반성만으로는 reasoning 개선이 제한적 (Huang et al. 2023, arXiv:2310.01798).
Ralph 진입 전 반드시 외부 검증 신호가 가용해야 함:

| 신호 유형 | 예시 |
|----------|------|
| 테스트 실행 결과 | pytest exit code, assertion 결과 |
| 린트·타입 체크 | ruff/mypy 출력 |
| 빌드 결과 | 컴파일 에러 메시지 |
| 로그·에러 메시지 | 스택트레이스, 런타임 에러 |

외부 신호 없는 순수 추론 ralph는 금지 — discuss 또는 단발 qa로 대체.
근거: Self-Refine, Reflexion, CRITIC 모두 외부 신호가 효과의 핵심 (NeurIPS 2023, ICLR 2024).

## § 소집 제약 규칙

| 규칙 | 내용 |
|------|------|
| 경량성 | 소집 prompt 200자 이내 |
| 명명 규칙 | `coder-1`, `searcher-2` 등 역할+번호 형식 |
| 중복 한도 | coder ≤ 3, searcher ≤ 2, scout ≤ 2, 총 ≤ 5명 (qa lead 제외) |
| path β/δ 팀 상태 | 동일 루프 내 TeamCreate 1회 + 재활용 강제 |

## § 동일 실패 패턴 감지

| 신호 | 트리거 조건 | 대응 |
|------|------------|------|
| 동일 에러 메시지 2회 연속 | exit code + 첫 줄 동일 | 전략 전환 강제 — coder 추가 소집 또는 접근 변경 |
| 동일 위치·동일 원인 3회 | 파일:줄 + cause 동일 | 즉시 main 에스컬레이션 (cycle 종료) |
| 무한 루프 의심 | 동일 행동 3회 + 결과 변화 없음 | 강제 종료 + Mem0 feedback 저장 |
| LLM 자가 retry 시도 | qa subagent가 같은 subagent 재호출 | **금지** — main 에스컬레이션 |
| API timeout/rate limit | 504/429 수신 | 코드 제어 exponential backoff (2s → 4s → 8s, 최대 3회) |

근거: Reflexion (NeurIPS 2023) — verbal self-reflection trigger criteria.

Ralph 루프 중 설계 결정·아키텍처 합의가 필요해진 경우 → ralph 종료 + /discuss 전환 (teammate 또는 subagent 토론)

### 안전 가드

| 가드 | 조건 |
|------|------|
| path β/δ 사용 조건 | 예상 라운드 ≥ 3 + qa 컨텍스트 < 50% — 미만 시 path α/γ로 격하 |
| TeamDelete 강제 | path β/δ 사용 시 루프 종료 시 반드시 TeamDelete (orphaned 방지) |
| path α/γ 횟수 한도 | 동일 루프 내 ≤ 5회 — 초과 시 main 에스컬레이션 |
| 동일 원인 3회 연속 시 | main 에스컬레이션 (§ 동일 실패 패턴 감지 참조) |

### 소집 형식 (MANDATORY)

```
[qa→{name}] 루프 N회차 / 사유: {1줄} / 요청: {1줄}
```

예시:
```
[qa→coder-2] 루프 2회차 / 사유: foo.py와 bar.py가 독립 / 요청: bar.py:88 ZeroDivisionError 방어 추가
[qa→searcher-1] 루프 3회차 / 사유: numpy 2.0 deprecation / 요청: np.float_ 대체 API 검색
```

### 기존 qa 직접 수정 범위 (보존)
- import 오류, 경로 오타, 변수명 불일치
- 타입 힌트 불일치, 빠진 return문
- 테스트 fixture 설정 오류

### coder 위임 범위 (path α 단일 위임 등)
- 함수 로직/알고리즘 변경
- 모델 아키텍처 수정
- 인터페이스 시그니처 변경

### tracer mode (라우팅 우선순위 2.5)
버그 원인을 단계적으로 추적해야 할 때 사용:
1. 에러 메시지에서 최초 발생 지점(entry point) 식별
2. 호출 스택을 역방향으로 추적하여 원인 컴포넌트 특정
3. 원인 컴포넌트의 입력값·상태·의존성 검사
4. 인과관계 체인 요약 보고 → coder에 수정 의뢰

### ML 실험 코드 제한 (보존)
- 학습 스크립트(`train.py`, `run_trains.py`) 직접 실행은 **사용자 직접 수행 원칙** 유지
- qa의 Ralph Wiggum 루프는 **단위 테스트 및 dry-run** 범위에 한정

### 자동 통신 노트
Ralph 팀 SendMessage 라운드는 **사용자 개입 없이 자동 진행**. 라운드 진행 중 사용자 입력 필요 시 `inputNeededNotifEnabled=true`로 알림 자동 발송. Shift+Down은 선택적 확인용.

---

## 2단계 리뷰 순서 (subagent-driven 차용 — MANDATORY)

> **근거**: superpowers subagent-driven-development — spec 준수와 코드 품질을 분리 검증. spec 충족 후에 품질을 본다(순서 역전 금지).

1. **1차 spec 준수** — 기획-구현 일치(과/소 구현 없음). FAIL이면 여기서 멈추고 coder에 수정 의뢰 (코드 품질 검토 진입 ❌).
2. **2차 코드 품질** — 1차 PASS 후에만. 구조·네이밍·중복·효율.
→ 아래 보고 형식 **2번(기획-구현 일치)=1차 spec 준수**, 나머지(1번 구조·수학, 3번 호출부, 4번 config-코드-논문, 5번 import)=2차 코드 품질에 대응. (1차 FAIL 시 2차 진입 없이 coder 수정 의뢰)

## QA 결과 보고 형식
```
✅ QA 검증 결과:
1. 구조적·수학적 검증: PASS/FAIL (수식·불변식·알고리즘 구조 — agents/qa.md 보고 형식과 동일)
2. 기획-구현 일치: PASS/FAIL (상세)
3. 호출부 영향: PASS/FAIL (영향 N건)
4. Config-코드-논문: PASS/FAIL (상세)
5. Import 검증: PASS/FAIL
6. 테스트: PASS/SKIP/FAIL
7. Ralph Wiggum 루프: N회 반복 / 위임 건수 M건 (해당 시)
```

## § Mem0 QA 이력 관리

#### QA 실패 저장
QA 검증에서 FAIL 항목 발견 시 자동 저장 → `mem0-auto.md` T04 참조
- **에이전트 약점 캡처 (T41)**: qa FAIL은 coder 구현 약점 신호 → main이 T41 저장(agent=coder). 동일 약점 3회+ 시 `coder.md` 개선 제안 (`agent-eval.md`).

#### QA 사전 검색
수정 대상 모듈의 과거 QA 이슈 자동 검색 → `mem0-auto.md` T05 참조
→ 과거 이슈 발견 → "이 모듈에서 이전에 {이슈} 발생. 동일 패턴 주의" 경고

## 생략 조건
- 주석만 변경된 경우 → 체크리스트 1번만 수행
- CLAUDE.md/MEMORY.md 등 설정 파일만 변경 → QA 생략
- 사용자가 "즉시 진행" 요청 시 → QA 요약만 제공 (생략 불가)

## § 계획-대비 검수 (구현 후 검수 게이트 상세 — 2026-07-24 사용자 지시, 2026-07-27 사고 유형별 로스터로 확장, always-on 요약은 agent-routing.md)

coder가 계획된 스펙대로 구현한 뒤, 발사·머지·**결론 확정** 전 "계획대로 정확히 구현됐는가"를 독립 검수팀으로 확인한다.

| 렌즈 | 에이전트(모델) | 확인 |
|------|---------------|------|
| 정찰 | **scout**(haiku) | 실제 파일·함수·배선을 파일:라인 매핑 — 무엇이 구현됐는지 |
| 계획-적합성 | **planner**(opus) | 원 스펙 항목별 대비 누락·추가·변형 대조 → 편차 목록 |
| 비판 감사 | **researcher**(opus) | 버그·오설계·정확성(수식·엣지·회귀)·계획엔 없던 부작용 |
| 지표 신설·변경 검증 | **searcher**(sonnet) + **qa**(sonnet) | 선행 문헌 표준과의 정합(searcher) + 대상 반대방향 조작 시 값이 실제로 변하는지 확인하는 감도 스크립트(qa, `coding-conventions.md` § 지표 감도 검증) |
| 처치·arm 정의 검증 | **qa**(sonnet) | 대조군과 수식상 소거되지 않는지 **수치 반증** — researcher는 tools에 Bash가 없어(`agents/researcher.md:5`) 이 역할을 못 한다 |
| 외부 기법 채택 검증 | **searcher**(sonnet) | 원문 정독 + § 외부 기법 채택 2문항(아래) 통과 여부 확인 |

- **2026-07-27 로스터 확장**: 렌즈는 고정 3인이 아니라 **사고 유형별 로스터**다 — 비자명 구현 일반은 위 3렌즈(정찰/계획-적합성/비판 감사)를 병렬 spawn하고, 지표·처치·외부기법 채택이 걸린 구현은 해당 유형 행을 **추가로** 병렬 spawn한다.
- 흐름: 해당 로스터 병렬 spawn(독립 보고, 4요소 prompt) → main이 원문(파일:라인/수치) 대조 통합 → 편차·결함은 coder 수정 후 **재검수** → PASS 시에만 진행.
- **qa 6-Gate와의 관계 (중복 아님)**: qa의 6-Gate는 **기능·회귀 축**(테스트·호출부·인과), 이 게이트는 **스펙 적합성 축**(계획 대비 누락·변형) — 별개 질문이다. 표준 순서: coder → qa(기능 PASS) → 계획-대비 검수(적합성 PASS) → 발사. 소규모 변경으로 qa 6-Gate가 생략된 경우에도 스펙이 있으면 이 게이트는 독립 적용. 위 로스터에서 qa가 맡는 지표·처치 검증은 **추가 역할**이며 6-Gate를 대체하지 않는다.
- 적용 대상: 계획된 스펙(discuss/workflow/spawn 스펙)이 있는 비자명 구현. **생략**: 단순 1줄 수정·오타·boilerplate·이미 qa 통과한 소변경. 근거: coder 자기검증만으로는 계획 편차(누락 arm·수식 오구현·회귀)를 놓친다 — 독립 검수가 발사·**결론 확정** 전 마지막 방어선.

### 외부 기법 채택 2문항 (main, 채택 결정 전 — always-on 요약: `rules/agent-routing.md` § 검수 게이트)

외부 논문·라이브러리의 기법을 **채택 결정 전** main이 아래 2문항에 답한다. 하나라도 답 못 하면 채택 보류 → 본 검수 게이트(외부 기법 행)로 회부.

| 문항 | 내용 |
|------|------|
| ① 레버 지목 | 이 기법이 인과 사슬의 **어느 변수**를 바꾸는가? "학습 규칙"이라 주장하려면 **어느 항의 gradient/업데이트가 달라지는지 지목**해야 한다 — 못 하면 그것은 학습 규칙이 아니라 목적함수·스케줄 조정이다. |
| ② 부호 정렬 | 이 기법의 목적함수가 최소화/최대화하는 대상이 **우리 목표와 같은 방향**인가? **알려진 실패 모드에 보상하지 않는가**? |

- citation-verifier는 이 게이트에 불참 — 철회·stance 검증은 목적함수 부호 오류를 못 잡아, 이 게이트가 다루는 사고 유형(측정·처치·기법 채택 오류)과 무관하다.
- 근거: 외부 선택(selection) 기법을 학습 규칙 레버로 오분류 — 실체는 selector+역전파 절단이라 credit 할당 불변, 목적함수 부호도 목표와 반대여서 알려진 실패 모드에 점수를 주는 장치였던 실사고 (프로젝트 상세는 공개 미러 비대상 위치로 분리: `~/.claude/knowledge/project-C/mdl-selector-not-learning-rule.md`).
