---
description: "Use when: Confluence 연구 기록 페이지 생성·수정 시. 4단계 계층(전체→연도→월→일자) 순차 업데이트. '연구 기록', '실험 기록', '연구 노트' 키워드."
model: sonnet
---

# Confluence 연구 기록 작성 규칙

> **스킬 경계**: 연구 활동 기록 전용 (서사 형식 강제). 일반 Confluence 페이지는 `/confluence`, 워크플로우 설계는 `/workflow` 사용.

> **프로젝트 양식 우선 (2026-07-20)**: 작성 전 `rules-lazy/doc-format-registry.md` 조회 — 프로젝트 등록 양식(예: project-C `research-note.md`)이 있으면 그 골격·escaping이 우선하고, 본 스킬의 4단계 계층·7답 서사 원칙은 그 위에 겹쳐 적용한다.

---

## 핵심 원칙 (MANDATORY)

모든 연구 기록 페이지는 단순 changelog가 아닌 **논리적 연구 서사(research narrative)** 형태로 작성한다.

독자가 아래 7가지에 답할 수 있어야 한다:
1. **계기**: 무엇이 촉발했는가? (선행 한계, 관찰, 외부 요인)
2. **이유/목적**: 왜 이 방향이며, 무엇을 검증하는가? (가설, 기대 효과)
3. **무엇을/어떻게**: 누가, 언제, 어디서, 무엇을, 어떻게 했는가?
4. **의의/결과**: 어떤 결과이며, 그 의미는? (수치 + 의의)
5. **분석**: 왜 이런 결과인가? (인과 메커니즘)
6. **결론**: 가설이 지지/반박되었는가? 확정 결정은?
7. **향후**: 다음에 무엇을 왜 할 것인가?

---

## 페이지 계층 구조 (4단계 — MANDATORY)

```
{프로젝트} 연구 기록          ← Level 1: 전체 (개요 + 아키텍처 변천사 + 일자별 요약 표)
  └─ {프로젝트} {YYYY}       ← Level 2: 연도 (연간 흐름 + 핵심 성과 + 일자별 표)
       └─ {프로젝트} {YYYY}년 {MM}월  ← Level 3: 월 (월간 요약 + 일자별 표)
            └─ {YYYY-MM-DD} | {주제}   ← Level 4: 일자별 (전체 서사)
```

**네이밍 규칙**:

| 레벨 | 형식 | 예시 |
|------|------|------|
| Level 1 | `{프로젝트} 연구 기록` | TexRoRA 연구 기록 |
| Level 2 | `{프로젝트} {YYYY}` | TexRoRA 2026 |
| Level 3 | `{프로젝트} {YYYY}년 {MM}월` | TexRoRA 2026년 3월 |
| Level 4 | `{YYYY-MM-DD} \| {주제 요약}` | 2026-03-30 \| XAI 교차 분석 → v3-c 확정 |

> 연속 작업: `{YYYY-MM-DD} ~ {MM-DD}` 형식 허용

---

## 업데이트 흐름 (MANDATORY)

순서: Level 4 → Level 3 → Level 2 → Level 1 순차 업데이트.

```
Step 1. Level 4 — 전체 서사 형식 작성
Step 2. Level 3 — 일자별 기록 표 행 추가/수정 + 월간 요약 갱신
Step 3. Level 2 — 일자별 기록 표 행 추가/수정 + 핵심 성과 갱신 (해당 시)
Step 4. Level 1 — 일자별 연구 기록 표 행 추가/수정 + 아키텍처 변천사 갱신 (해당 시)
```

### § Mem0 연구 기록 자동 채우기

Level 4 페이지 생성 시 해당 날짜 활동을 Mem0에서 자동 수집:
→ mem0-auto.md T03 참조 (날짜 필터 + category별 순차 검색)
수집 항목을 초안에 자동 포함 → 사용자 확인 후 반영.

---

### 페이지 탐색 및 생성 규칙

```
해당 레벨 페이지 존재?
  YES → getConfluencePage 읽기 → updateConfluencePage
  NO  → 부모 페이지 하위에 createConfluencePage
(도구 접두: mcp__claude_ai_Atlassian__)
```

| 레벨 | 부모 페이지 | 이모지 |
|------|-----------|--------|
| Level 4 | Level 3 (월) | 🧪 |
| Level 3 | Level 2 (연도) | 📅 |
| Level 2 | Level 1 (전체) | 📆 |
| Level 1 | 사용자 지정 (이미 존재 전제) | 📚 |

**페이지 이모지 (MANDATORY)**: `createConfluencePage` 시 `emoji` 파라미터 필수. `updateConfluencePage` 시 기존 이모지 없으면 추가. 사용자 지정 이모지 최우선.

**중간 레벨 부재 시**: Level 4 생성 시 Level 3 없으면 Level 3부터 순차 생성.

---

## 각 레벨별 업데이트 내용

**Level 4**: 전체 서사 형식 적용 (아래 § 페이지 구조 형식).
**Level 3**: 월간 흐름 요약(3~5문장) + 일자별 기록 표 행 추가. 형식: `| {날짜} | {1줄 요약} | {핵심 수치 또는 "해당 없음"} |`
**Level 2**: 연구 흐름 요약 + 핵심 성과 표 + 일자별 기록 표.
**Level 1**: 아키텍처 변천사(새 버전 탄생 시) + 일자별 연구 기록 표 + 한계·후속 방향.

**표 행 추가 규칙**: 동일 날짜 → 수정(행 교체). 새 날짜 → 추가(시간 순서). 진행 중: `**🔶 진행 중**` → 완료 시 수치로 교체.

---

## 페이지 구조 형식 (Level 4 — MANDATORY)

섹션명은 맥락에 맞게 변형 가능. 순서와 목적 유지.

```markdown
## 1. 계기 (Background)
- 이전 단계 한계·미해결 질문·외부 요인
- 선행 실험 결과 참조 시 날짜·링크 포함

---

## 2. 이유/목적 (Why & Purpose)
- 핵심 가설: "~이면 ~일 것이다" 형태 명시
- 이 방향 선택 이유 + 기대 효과

---

## 3. 무엇을/어떻게 했는가 (What & How)
- 표, config 변경 사항, 코드 스니펫 포함
- 누가(담당자/에이전트), 언제(날짜), 어디서(환경/GPU) 명시
- "어떻게"보다 "왜 이 방식"에 집중

---

## 4. 의의/결과 (Results & Significance)
- 핵심 지표 수치 필수 (공란 금지)
- WandB run URL, 체크포인트 경로 포함
- 진행 중: **🔶 진행 중** 표기
- 의의: 가설 지지/반박 여부 + 프로젝트 내 위치

---

## 5. 분석 (Analysis)
- 예상과 달랐다면 왜 달랐는가
- 어떤 메커니즘이 결과를 만들었는가
- 핵심 인사이트 **bold** 처리

---

## 6. 결론 (Conclusion)
- 가설 판정: 지지됨 / 반박됨 / 부분적 지지 (명확히 판정)
- 확정 결정 사항 bullet 나열
- 마일스톤 연결: "이로써 Phase N의 ~단계 완료"

---

## 7. 향후 방향 (Future Direction)
- "~이기 때문에 ~를 한다" 형태
- 계획 변경 시 변경 이유 명시
- Go/NoGo 조건 수치 기준 포함 (해당 시)
```

---

## 수식 표현 규칙 (LaTeX Math for Confluence — MANDATORY)

**수식 플러그인**: LaTeX Math for Confluence 사용.
**매크로명 하드코딩 금지**: 첫 사용 시 기존 수식 포함 페이지 storage format에서 `ac:name` 값 확인 → `long-term/feedback.md`에 기록 → 이후 참조.

### ★확정: your-company wiki LaTeX inline 매크로 (실측 2026-07-08, MCP createConfluencePage/updateConfluencePage용)

- **inline 매크로 = Forge 앱 `latex-math-inline`** (Stiltsoft `mathinline`/`com.atlassian.macro.core` 아님 — 그건 "확장 로드 오류"남). HTML+ 형식:
  ```
  <span data-type="inline-extension" data-extension-key="90117453-3cec-45bc-9ac2-5a6b76f0375b/da350fb4-aa69-4acb-8f14-b6eaa7d05c18/static/latex-math-inline" data-extension-type="com.atlassian.ecosystem" data-parameters="{&quot;layout&quot;:&quot;inlineExtension&quot;,&quot;guestParams&quot;:{&quot;body&quot;:&quot;<FORMULA>&quot;,&quot;alignment&quot;:&quot;center&quot;},&quot;localId&quot;:&quot;<고유id>&quot;}">LaTex Math Inline</span>
  ```
- **★escaping (핵심)**: `<FORMULA>`는 **자연 LaTeX(백슬래시 1개)를 타이핑 시 `\\`(2개)로** 씀 → MCP가 HTML속성 JSON 1회 언이스케이프 → 저장 `\`(1개) → MathJax 정상. 예 `\mathbf{W}` = `\\mathbf{W}`로 입력. ⚠️ `\\\\`(4개)는 저장 `\\`(2개)=MathJax가 literal 처리해 **명령 사라짐(깨짐)** — 금지. contentFormat=html 왕복도 동일(2개 입력). 정상 실측: REDESIGN-PC(1658847234), 실험1(1715896322 v4), 측정지표(1724907555 v6, 2026-07-18 스크린샷 렌더 확인).
- **⚠️ read-back 백슬래시 수는 correctness 지표 아님 (2026-07-18 검증)**: getConfluencePage(html)로 다시 읽으면 스팬 body가 4개(또는 페이지별 16개)로 과이스케이프돼 보이지만 이는 **직렬화 표현일 뿐**이고 실제 MathJax는 정상 렌더. 페이지마다 read-back 백슬래시 수가 달라도 **당황 말 것** — 입력은 항상 2개(`\\`) 규칙 고정, 렌더 확인은 read-back 카운트가 아니라 실제 화면(사용자 스크린샷)으로.
- **★모든 수식·수학 표현은 매번 `latex-math-inline`으로 렌더한다 (2026-07-18 사용자 지시 — 유니코드/코드 텍스트 대체 금지).** 등식·행렬·연산(예: `Q = U Vᵀ`, `M = U Σ Vᵀ`, `aligned(f)=(f−μ_s)@M+μ_t`)·기호 모두 위 inline 매크로 사용. 산문 속 단발 변수 언급("가중치 W" 같은 서술)까지 강제하진 않되 **수식·등식으로 쓰이는 순간 latex-inline 필수**(과거 `Q=UVᵀ`를 코드텍스트로 넣던 관행 폐기). escaping은 위 ★escaping 규칙 준수. block은 `mathblock`(extension-key=mathblock, com.atlassian.macro.core).

| 구분 | 사용 조건 |
|------|----------|
| 인라인 | 문장 내 변수·짧은 표현 (15자 이내) |
| 블록 | 독립된 수식 정의·유도 |

**수식 필수 포함 조건**:

| 상황 | 필수 여부 |
|------|----------|
| Loss function 정의/변경 | 필수 |
| Learning rate schedule | 필수 |
| 모델 파라미터 수 계산 | 필수 |
| 새 정규화/활성화 함수 도입 | 필수 |
| 표준 아키텍처 언급 (변경 없음) | 불필요 |
| 단순 config 값 변경 | 불필요 |

**표기 일관성 (MANDATORY)**: 변수명은 논문(`docs/paper/`)과 동일. 벡터 `\mathbf{x}`, 행렬 `\mathbf{W}`, 손실 `\mathcal{L}`, 기대값 `\mathbb{E}`.

**코드-수식 대응표 (MANDATORY)**: 수식 첫 등장 섹션에 포함:
```markdown
| 수식 기호 | 코드 변수명 | 설명 |
|----------|-----------|------|
| \alpha   | lr        | 학습률 |
```

---

## 이미지/다이어그램 삽입 규칙

**필수 삽입 조건**:

| 상황 | 필수 여부 |
|------|----------|
| 아키텍처 변경 | 필수 |
| 학습 곡선 | 필수 |
| Ablation 결과 비교 (3개+) | 필수 |
| 단일 실험 수치 보고 | 불필요 |

**형식**: PNG(차트/스크린샷) / SVG(다이어그램). 해상도: 최소 150 DPI. 최대 너비: 800px.
**파일명**: `{YYYY-MM-DD}_{내용요약}.png`

**캡션 (MANDATORY)**: 이미지 바로 아래 이탤릭체. 포함 필수: (1) 무엇을 보여주는지, (2) 핵심 관찰점. Figure 번호는 페이지 내 순차 부여.

**WandB 스크린샷 사용 시 run URL 함께 기록 (MANDATORY)**

---

## 에이전트 준수 체크리스트 (MANDATORY)

### 작성 전
- [ ] 4단계 계층 페이지 존재 여부 확인
- [ ] 수식 필수 포함 조건 해당 확인 → 해당 시 LaTeX 블록 준비
- [ ] 이미지 필수 삽입 조건 해당 확인 → 해당 시 첨부 파일 준비

### 작성 중
- [ ] Level 4 서사 7개 섹션 순서 준수
- [ ] 수식 포함 시 코드-수식 대응표 작성
- [ ] WandB 차트 사용 시 run URL 기재

### 작성 후
- [ ] 4단계 순차 업데이트 완료 (Level 4→3→2→1)
- [ ] 상위 레벨 표에 행 추가/수정 완료

### 에이전트별 역할

| 에이전트 | 역할 | Confluence MCP |
|----------|------|----------------|
| **docs** | 페이지 생성·수정 실행 | O |
| **researcher** | 초안 작성 → docs 위임 | X → docs 위임 필수 |
| **main** | 직접 작성 또는 docs 소집 | O |

---

## 진행 중 항목 표기

```
**🔶 진행 중** — [실험 설정 요약]. 결과 대기.
**Go 조건**: [수치 기준]
**Go 시**: [다음 단계]
```

---

## 작성 금지 패턴

| 금지 | 대안 |
|------|------|
| 커밋 목록만 나열 | 각 커밋의 결정 이유 포함 |
| "~를 추가했다" (수동 나열) | "~이 필요했기 때문에 ~를 추가했다" |
| 수치 없는 결과 섹션 | WandB 링크 또는 N/A + 이유 |
| 후속 방향만 있고 이유 없음 | "~이기 때문에" 항상 포함 |
| 일자별만 수정하고 상위 미갱신 | 4단계 순차 업데이트 필수 |
| **하네스 내부 내용 노출 (MANDATORY 제외)** | 에이전트명(planner/researcher/coder/searcher/scout/qa)·/discuss·/workflow·subagent·teammate·spawn·Ralph Loop·SKILL_DEPTH·tmux(bi/bi2/bi3)·watcher·Claude/Codex·회의록/long-term 경로 등 **하네스 내부 용어를 컨플에 하나도 넣지 않는다** → 도메인 용어로 일반화(설계/비판/구현/문헌/검증 관점·다관점 검토 등). status 매크로는 도메인 콘텐츠라 허용 (2026-07-18 사용자 지시) |

---

## 적용 예외

- 단순 config 변경 기록 → Level 4만 수정, 상위는 표 행 추가만
- 코드 정리/주석 추가만 → Level 4만 수정, 상위 생략 가능
- 위 경우도 "왜" 섹션 1~2문장 권장

---

## /confluence 스킬 연동

- `/confluence` 스킬로 페이지 생성·수정 시 이 형식 기본 적용
- docs 에이전트 위임 시 이 스킬 내용을 프롬프트에 명시
- 4단계 업데이트의 수정 전 3단계 확인(docs.md § 페이지 수정 전 의무 확인 MANDATORY — Confluence 쓰기=외부 발신 게이트)은 **Level 1에서 캐스케이드 전체를 한 번에 고지·승인**받아 수행한다: "이 갱신이 함께 건드리는 상위 페이지(Level 2 월 / Level 3 연 / Level 4 인덱스) 목록"을 승인 시 함께 제시. Level 2~4는 그 **승인 범위 안에서** 진행하며 레벨마다 재확인은 생략 — 단 **승인 없는 Confluence 쓰기는 없다**(무단 진행 금지, 주권 게이트 유지)

## § QMD (.qmd) 연구 기록 변환

> **상세**: `agents/docs.md` § Quarto Markdown (.qmd) 처리 참조
> **목적**: 연구 기록은 `.qmd`의 핵심 시나리오 — 코드 실행 결과 + Figure + 해석을 단일 파일로 통합

### 활용 시나리오 (4단계 계층 모두 적용 가능)
- 일자 페이지: 당일 실험 결과를 `.qmd`로 작성 → quarto render → Confluence 업로드
- 월/연도 페이지: 집계 표를 `.qmd` python 청크로 자동 생성

### 권장 구조 (`outputs/research-records/{YYYY-MM-DD}.qmd`)
```yaml
---
title: "{YYYY-MM-DD} 연구 기록"
format: confluence
---
```
+ 실험 동기 본문 + python 청크(결과 자동 호출) + 해석 + 후속 계획

### 일반 .md 워크플로우와의 호환
- 기존 직접 작성(.md) 흐름은 그대로 유지
- `.qmd` 제공 시에만 docs 에이전트 quarto 흐름 진입

### 의존성
quarto CLI — docs 에이전트가 사전 점검
