---
description: "Use when: 새 규칙(rule), 스킬(skill), 에이전트(agent)를 빠르게 정의할 때. '/quick-skill rule/skill/agent' 형식."
model: sonnet
---

# /quick-skill — 규칙·스킬·에이전트 빠른 생성 워크플로우

> ⚠️ eval/benchmark 기반 심층 생성은 `/skill-creator` (Anthropic 공식 plugin) 사용

## /quick-skill vs /skill-creator 선택 기준

| 상황 | 사용 스킬 |
|------|---------|
| 빠른 초안, 간단한 구조, 10분 내 완성 | `/quick-skill` (이 파일) |
| eval/benchmark 기반 품질 측정 필요 | `/skill-creator` |
| 생성된 스킬을 수치로 검증하고 싶을 때 | `/skill-creator` |
| 하네스에 정식 등재 예정인 스킬 | `/skill-creator` → `/harness-bench`로 Before/After 측정 |

**`/skill-creator` 설치** (미설치 시 1회 실행):
```bash
npx skills add anthropics/skills --skill skill-creator
```

> 설치 후 `/skill-creator`로 직접 호출 가능. `/quick-skill`은 설치 불필요 (이 파일이 곧 스킬).

---

새 **규칙(rule)**, **스킬(skill)**, **에이전트(agent)** 정의를 대화형으로 생성합니다.

인자: `$ARGUMENTS` — `rule` / `skill` / `agent` 중 하나 (생략 시 사용자에게 선택 요청)

---

## 흐름

### Step 0 — 유형 결정

`$ARGUMENTS`가 없으면:

```
어떤 유형을 만들까요?
1. rule  — 행동 지침/프로세스 규칙 (rules/*.md)
2. skill — 슬래시 커맨드 워크플로우 (skills/{name}/SKILL.md — 동명 commands/ wrapper 금지, 아래 참조)
3. agent — 전문 서브에이전트 프롬프트 (agents/*.md)
```

---

### Step 1 — 정보 수집 (유형별)

#### rule 유형
```
새 규칙 생성을 위해 아래 정보를 알려주세요:

1. 규칙 이름 (파일명에 사용, 예: code-review, deploy-check)
2. 로드 시점: 언제 이 규칙이 트리거되어야 하나요?
3. 핵심 목적: 이 규칙이 해결할 문제나 보장할 품질은?
4. 필수 체크리스트 항목 (있으면): 순서대로 나열해 주세요
5. 생략/예외 조건: 언제 이 규칙을 건너뛰어도 되나요?
6. CLAUDE.md 연동 위치: 어느 섹션에 참조를 추가할까요?
```

#### skill 유형
```
새 스킬 생성을 위해 아래 정보를 알려주세요:

1. 스킬 이름 (슬래시 커맨드명, 예: /review-pr, /deploy)
2. 한 줄 설명: 이 스킬이 하는 일을 한 문장으로
3. 인자($ARGUMENTS): 받아야 할 파라미터가 있나요?
4. 실행 단계: 이 스킬이 순서대로 수행할 작업 목록
5. 에이전트 활용: 어떤 에이전트(scout/coder/qa 등)를 사용하나요?
6. 산출물: 완료 후 사용자에게 무엇을 보여줘야 하나요?
7. 자동 제안 트리거: 어떤 상황에서 이 스킬을 추천해야 하나요?
```

#### agent 유형
> 신설 전에 `rules-lazy/agent-routing-mcp.md` § 에이전트를 따로 두는 기준 의 네 가지(맥락 격리 · 도구 권한 분리 · 병렬 실행 · 모델 단가) 가운데 어느 것에 해당하는지 적는다. 해당이 없으면 스킬로 만든다.

```
새 에이전트 생성을 위해 아래 정보를 알려주세요:

1. 에이전트 이름 (파일명, 예: reviewer, optimizer)
2. 전문 역할: 이 에이전트가 담당할 도메인/기능
3. 사용 모델: haiku / sonnet / opus 중 (기본: sonnet)
4. 핵심 도구: 이 에이전트가 주로 사용할 도구 목록
5. 입력 형식: 이 에이전트에게 어떤 정보를 전달해야 하나요?
6. 출력 형식: 어떤 결과물을 반환해야 하나요?
7. 라우팅 테이블 위치: CLAUDE.md 라우팅 테이블 어느 우선순위에 추가할까요?
```

---

### Step 2 — 초안 생성

수집된 정보로 파일 초안 생성 (현행 구조 기준 — 구세대 `rules/`·`commands/` 직행 금지):

> **작성 스타일 게이트 (2026-07-09, Fable 5 공식 가이드 이식)**: **원칙형 1줄 우선** — "무엇을 왜"를 담은 짧은 원칙으로 쓰고, 동작별 열거·금지 목록은 **실제 실패 사례가 있을 때만** 그 사례와 함께 추가한다. 열거가 3항목을 넘으면 "이걸 원칙 1줄로 못 줄이는 이유"를 자문할 것 — 최신 모델은 짧은 의도 지시를 더 잘 따르며, 과잉 열거는 출력 품질을 떨어뜨린다.

> **재현 절차는 스크립트로 (2026-11-24 사용자 지시)**: 같은 입력이면 같은 결과가 나와야 하는 절차(점검표 · 형식 검사 · 대조 · 집계 · 커밋 절차)는 스킬 본문에 글로만 적지 않고 스크립트로 만든다. 스킬 본문에는 그 스크립트를 부르는 명령과 «출력 원문을 인용한다» 는 의무만 적는다. 판단이 필요한 절차는 글로 둔다. 예: `scripts/ontology-commit.sh`.

- **rule**: `~/.claude/rules-lazy/{name}.md` **기본** — `# 제목` + `> **로드 시점**: ...` 형식. always-on(`rules/`)은 매 턴 적용이 필수인 경우만 — 상시 로드 예산(CLAUDE.md·`rules/*.md` 합계 75,000B)은 커밋 시 `scripts/ci-gate-commit.sh` 가 검사하며 초과는 경고만 하고 커밋은 막지 않는다(2026-10-01 사용자 지시, learner.md § Zero-Sum)
- **skill**: `~/.claude/skills/{name}/SKILL.md` **표준** — frontmatter(`description`, `model`) + 본문. **스킬 자체가 `/{name}` 슬래시 진입점 제공 — 동명 `commands/` wrapper 추가 금지** (중복 등재 재발 방지, 2026-07-15 전수 제거)
- **agent**: `~/.claude/agents/{name}.md` — YAML frontmatter (`name`, `description`, `model`(별칭), `effort`(머리에 고정, 근거 `rules-lazy/model-assignment-rules.md` §9), `tools`, 필요 시 `mcpServers`·`disallowedTools`) + 프롬프트 본문. 본문 말미에 최종 보고 계약(행두 `RESULT: <값>` 한 줄, 정본 `agents/coder.md` § 수정 완료 후)을 둔다
- **신설 커밋의 Intent**: `rules/`·`rules-lazy/`·`agents/`·`skills/`·`scripts/`·`tools/`·`config/` 에 새 파일을 넣는 커밋은 타입(`feat:`·`fix:`·`refactor:`)과 무관하게 본문에 `Intent: intent/YYYY-MM-DD-<slug>.md` 줄이 필요하다(commit-msg 훅이 차단, `skills/commit/SKILL.md`). 비자명하면 신설 전에 `/intent` 를 순차로 먼저 거친다

초안 완료 후:
```
초안을 생성했습니다: {파일 경로}

수정할 내용이 있으면 말씀해 주세요.
없으면 Step 3 (CLAUDE.md 연동)으로 진행합니다.
```

---

### Step 3 — CLAUDE.md 연동

유형별 연동 위치:

| 유형 | 연동 위치 | 연동 형식 |
|------|---------|---------|
| rule | CLAUDE.md 관련 섹션(lazy 참조) 또는 모(母) 룰 파일 | `- 상세: \`~/.claude/rules-lazy/{name}.md\`` |
| skill | `rules/prompt-routing.md` Step 2 트리거 매핑(상세: prompt-routing-recommend.md) | `\| 감지 상황 \| /{name} \|` 행 추가 |
| agent | `rules/agent-routing.md` 에이전트 목록·라우팅 테이블 + **파생 카탈로그 동기화**: AGENTS.md·RULES.md·CLAUDE.md 에이전트 수 | 행 추가 + 카운트 갱신 (감사 반복 결함 #2 방지) |

사용자 승인 후 Edit 도구로 CLAUDE.md 수정.

---

### Step 4 — 결정 기록

합의된 내용을 즉시 `short-term/decisions.md`에 기록 (`memory-write.md` 규칙 준수 — MEMORY.md는 인덱스 전용, 콘텐츠 기록 금지):

```markdown
- **[날짜] {유형} 생성**: {이름} — 목적: {한 줄 설명}
```

---

### 완료 보고

```
✅ {유형} 생성 완료:
- 파일: {경로}
- CLAUDE.md 연동: {위치}
- 트리거 조건: {언제 활성화되는지}
```
