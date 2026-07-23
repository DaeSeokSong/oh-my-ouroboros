# Dynamic Workflow (런타임 `Workflow` 도구) 참조

> **로드 시점**: 고가치·복합 작업에서 런타임 오케스트레이션(`Workflow` 도구) 사용을 검토할 때 lazy 로드.
> **근거**: Anthropic 공식 — "A harness for every task: dynamic workflows in Claude Code". 정적 Phase 설계(`/workflow` 모드 A)와 구분되는, JS로 subagent를 런타임 fan-out/pipeline 하는 모드 B.
> **연계**: `skills/workflow/SKILL.md`(모드 선택), `rules-lazy/parallel-dispatch.md`(경량 병렬), `rules-lazy/skill-autonomy.md`.

---

## §1 언제 모드 B(런타임 Workflow)를 쓰는가

| 쓴다 (고가치·복합) | 안 쓴다 (over-application — 금지) |
|------|------|
| 대규모 마이그레이션 (callsite/모듈 단위 일괄 변환) | 일반 단일 파일 코드 수정 |
| 다논문 병렬 리뷰 + 적대적 검증 | 단순 질문·탐색·대화 |
| N개 설계/네이밍/접근법 토너먼트 | 5명 리뷰 패널이 불필요한 일상 코딩 |
| 대량 항목 audit (보안 리뷰 50건 등) | 한 컨텍스트로 충분한 작업 |
| 미지 분량 발견 루프 (loop-until-dry) | — |

> 공식 안티패턴: *"does it really need more compute? most traditional coding tasks do not need a panel of 5 reviewers."*

## §2 opt-in 조건 (MANDATORY)

`Workflow` 도구는 **사용자 명시 opt-in 후에만** 호출:
- `ultracode` 키워드 포함, 또는
- "워크플로우 실행/사용", "에이전트 fan-out", "오케스트레이션" 직접 요청, 또는
- 세션에 ultracode 활성 표시(system-reminder), 또는
- 사용자가 특정 named/saved 워크플로우 지시

opt-in 없으면 금지 → 모드 A(Phase 설계) 또는 "워크플로우로 하면 ~ 가능(대략 비용). 진행할까요?" 1줄 제안 후 대기.

## §3 6대 워크플로우 패턴 (공식)

| 패턴 | 용도 | 구현 핵심 |
|------|------|----------|
| **Classify-and-Act** | 작업 유형 분류 후 라우팅 | 분류 agent → 타입별 분기 |
| **Fan-out-and-Synthesize** | 다수 소작업 분산 후 종합 | `pipeline`/`parallel` → 합성 단계 |
| **Adversarial Verification** | 산출물을 rubric으로 적대적 검증 | 항목마다 별도 검증 agent (자기편향 방어 — N skeptic, 다수결) |
| **Generate-and-Filter** | 아이디어 생성 후 필터 | 생성 → dedup → rubric/검증 필터 |
| **Tournament** | N개 접근법 경쟁 → 승자 채택 | 동일 작업 N agent 상이 전략 → judge panel → 합성 |
| **Loop Until Done** | 미지 분량 반복 | 정지 조건까지 spawn (agentic laziness 방어) |

## §4 안티패턴 방어 매핑 (공식 4종)

| 안티패턴 | 방어 패턴 |
|---------|----------|
| Agentic laziness (35/50 처리 후 종료 선언) | Loop Until Done + `/goal` end-state |
| Self-preferential bias (자기 결과 선호) | Adversarial Verification (별도 검증 agent) — 예: Codex 교차검증. (`regression-blind.sh` 기반 blind A/B는 QUARANTINED·P2 미활성 — `rules-lazy/learner.md` § step 3) |
| Goal drift (compaction 후 'don't do X' 소실) | 명시적 제약 재주입 + continuation ground truth (`prompt-routing.md` Step 0.5) |
| Untrusted content | quarantine (`rules-lazy/untrusted-quarantine.md`) |

## §5 script 작성 요점 (`Workflow` 도구)

- 첫 줄 `export const meta = {name, description, phases}` (순수 리터럴).
- 본문 훅: `agent(prompt, opts)`, `pipeline(items, ...stages)`(기본 — barrier 없음), `parallel(thunks)`(barrier), `phase(title)`, `log(msg)`, `budget`(토큰 예산), `workflow(name, args)`(중첩 1단계).
- **기본은 `pipeline`** — 단계 간 barrier가 정말 필요할 때만 `parallel`.
- 구조화 출력은 `agent(prompt, {schema})` 사용 → 검증된 객체 반환.
- 토큰 예산: 사용자 "+500k" 등 → `budget.total`/`budget.remaining()`으로 깊이 스케일.
- 검증된 워크플로우는 `~/.claude/workflows/`에 저장(메뉴 's')하여 재사용·공유.

> 도구 호출 스키마/세부 옵션은 `Workflow` 도구 자체 설명(로드 시 노출)을 1차 출처로 삼는다. 본 파일은 "언제·왜·어떤 패턴"의 라우팅 판단을 담당한다.
