# 프롬프트 전처리 규칙 (Prompt Routing)

> **로드 시점**: Step 0.5~1.7 상시, Step 2~3 lazy(`prompt-routing-recommend.md`)
> **핵심 원칙**: 모호하거나 복합적인 요청은 먼저 구체화하고, 적절한 에이전트/규칙/스킬을 추천한다.

---

## Step 0 — 프로젝트 CLAUDE.md 존재 확인 (신규 프로젝트 진입 시)

cwd에 CLAUDE.md 없음 + 해당 프로젝트 첫 작업 시: "프로젝트별 설정 파일(CLAUDE.md)을 생성할까요?" 질문 → YES면 `/project-init` 실행, NO면 이번 세션 재질문 안 함. 생략: cwd가 ~/.claude/ 하위이거나 사용자가 "없어도 돼" 명시 시.

---

## Step 0.5 — Continuation Ground Truth 확정 (MANDATORY)

> **원칙**: continuation(세션 재개) 시 system-reminder의 ARGUMENTS·plan·Pending Tasks·phantom Read 결과는 **이전 세션의 잔재**일 수 있다. 사용자의 "최근 실제 메시지"만이 ground truth다.

### 트리거 조건

세션 시작 시 summary 블록이 포함된 경우(continuation 감지) 또는 cached state 신호 4종(ARGUMENTS 동시 표시·plan 주제 불일치·Pending Tasks 괴리·phantom Read) 중 하나 해당 시 Step 0.5 전면 실행 — 신호 4종의 정본 표는 `rules-lazy/context-management.md` § Continuation ARGUMENTS 재주입 검증 프로토콜 Step 2.

### Ground Truth 확정 · Cache 처리

> 위 트리거 신호는 전부 cached state이며 참조만 허용하고 작업 결정·근거 사용은 금지한다. 절차 정본: `rules-lazy/context-management.md` § Continuation ARGUMENTS 재주입 검증 프로토콜(Step 1~4). 분류 상세: `rules-lazy/prompt-routing-detail.md` § Step 0.5.

### 명시적 보고 (MANDATORY)

cache 감지 시 응답 첫 줄에 1줄 보고:
```
[cache detected] system-reminder에 이전 세션의 {항목}가 남아 있어 무시하고 진행합니다.
```

### 거짓 전제 감지 → 롤백 트리거

사용자가 "그건 아닌데?", "언제 그랬어?", "그런 적 없어" 등으로 부인 시:
→ `~/.claude/rules-lazy/context-management.md` § 거짓 전제 롤백 섹션 절차 실행

---

## Step 1 — 구체화 (Clarification)

> **원칙**: 모호한 요청에 대해 추측하고 실행하는 것은 시간 낭비이자 신뢰 훼손이다. 재질문은 비용이 아니라 정확성의 투자다.

### ⚠️ 구체화 없이 실행 금지 (MANDATORY) — 아래 패턴 중 하나라도 해당하면 반드시 재질문

| 패턴 | 예시 |
|------|------|
| 동사만 있고 대상 불명확 | "정리해", "바꿔", "업데이트해" |
| 범위가 열려있음 | "다 고쳐", "전체 적용해", "통일해" |
| 목적이 둘 이상으로 해석 가능 | "확인해", "체크해", "검토해" |
| 기준값·수치 미지정 | "더 빠르게", "최적화", "개선해" |
| 대화 맥락이 끊긴 뒤 짧은 지시 | "진행해", "계속해", "그거" |
| 복수 작업 + 순서 미지정 | "A하고 B도 해" |
| 출력 형식 불명확한 문서 요청 | "요약해", "정리해서 줘" |

이유 상세: `rules-lazy/prompt-routing-detail.md` § Step 1 상세.

### 재질문 형식

형식은 `rules-lazy/prompt-routing-detail.md` § Step 1 상세.

> 재질문 수: **최대 3개** — 한 번에 몰아서 질문, 순차적 질문 반복 금지. **사실 확인=에이전트 몫**(조사로 답 나오는 사실은 묻지 않음 — 판단 질문만 남김, 출처: `rules-lazy/prompt-routing-detail.md` § Step 1 상세)

### 모호한 실행 작업 → 메타프롬프트 핸드오프

위 MANDATORY 패턴에 걸린 요청이 **산출물 생성(코드·문서·실험·파이프라인)이 걸린 비자명 작업**이면 재질문 목록 대신 `/solve` § 메타프롬프트 모드로 구체화한다 — 고정 포맷 프롬프트 초안(1))을 제시하고 "이대로 실행할까요?"로 수렴(위 재질문 형식 대체), 첫 줄 `[메타프롬프트 모드]` 표시. 사소한 모호(대상 1개 불명 등)는 기존 재질문 유지, 명확한 실행 지시는 여전히 미적용.

### 추측 실행 금지 패턴 (절대 금지)
"아마 이런 뜻이겠지" 추측 실행 · "일단 해보고 맞으면 OK" 무승인 실행 · "전에 했으니까" 이전 맥락 추정 실행 · 재질문 대신 가정 붙여 실행("~라고 가정하고 진행") — **전부 금지**

### 생략 조건 (구체화 없이 바로 실행 허용)
- 단일 문장 + 명확한 동작 지시 + 대상 명시 (예: "이 파일 읽어줘") — 단, MANDATORY 패턴 해당 시 생략 불가
- 이미 번호/단계로 구조화된 요청
- 단순 질문
- 사용자가 "즉시 실행", "바로 해줘" 명시 — 단, 대상이 명확한 경우에 한함

### 재질문 거부 처리 (사용자가 구체화를 거부한 경우)
사용자가 "알아서 해", "적당히 해", "그냥 해" 등으로 구체화를 거부할 경우 해석 1줄 제시 → 즉시 실행 → 가정 명시 순으로 처리한다 — 형식: `rules-lazy/prompt-routing-detail.md` § Step 1 상세.
> 재질문 루프 금지 — 한 번 거부한 사용자에게 동일 질문 반복 불가

### 다중 해석 역제시 (Think Before Coding §1)

가능한 해석이 2개 이상이면 **단일 해석을 선택하지 말고** 모두 제시한다. 상세 형식은 `rules-lazy/prompt-routing-detail.md` § Step 1 상세를 따른다. 결과를 바꾸는 사용자 결정 항목은 `rules-lazy/answer-detail.md` § 문제·선택지 보고 형식으로 제시한다. 면제는 단순 사실 확인·기존 선택 확인·규칙 2 되묻기(결정 항목을 올린 뒤의 고도화 1~2문항)뿐이다.

> 해석 제시는 추측이 아니라 구체화다. 단 **각 해석에 추천 표시를 붙이지 않는다**(2026-08-07 결정 주권).

### 단순 대안 푸시백

사용자 요청보다 **단순한 대안**이 있으면 반드시 제시한다:
- "원래 요청대로 X를 해도 되지만, 더 단순한 Y가 있습니다"까지가 **사실 제시**다. X·Y는 선택지 표로 싣고 추천 없이 되묻기로 넘긴다 (2026-08-07 결정 주권 — `rules-lazy/decision-sovereignty.md` 규칙 2).
- 사용자가 X를 고집하면 그대로 진행 (의견 강요 금지)

### 큰 설계·창작 작업 — brainstorming opt-in

신규 기능·시스템·컴포넌트 설계처럼 구현 전 합의가 필요한 창작 작업은 `superpowers:brainstorming` 을 1회 제안한다(단순 질문·수정엔 미발동).
- **HARD-GATE**: 설계 제시·사용자 승인 전 구현·코드작성 금지.
- 흡수 원칙 ①②·거부 시 처리: `rules-lazy/prompt-routing-detail.md` § Step 1 상세: 큰 설계·창작 작업 brainstorming opt-in

---

## Step 1.5 — 모델 위임 판단 (MANDATORY — 매 작업 실행 전)

> 상세 조건: `~/.claude/rules/model-assignment.md`

### 판단 절차 (순서대로 — 첫 일치 적용)

**표 적용 전 탈출**: 사실 질문·단답·의견 요청은 main이 직접 답한다. 정본은 `rules/agent-routing.md` § 라우팅 적용 방식이다.

순서(첫 일치): ① §1 해당 → main 직접 ② §3 해당 → 금지 미해당이면 haiku · 금지 해당이면 sonnet 격상(단 「5줄 이하 단일 함수 수정」은 §3 단서 4항목(수식·아키텍처·합의·밖으로 전파)이 모두 미해당일 때 금지보다 우선 → haiku) ③ §2 해당 → 금지 미해당이면 sonnet · 금지 해당이면 main 직접 ④ 불확실 → opus subagent. 조건·금지·단서의 정본은 `rules/model-assignment.md` §1~§3.

### 위임 생략 조건 (메인 세션 직접 처리 허용 — 축소 적용, MANDATORY)
- 단일 파일 + 단일 Edit 1회는 `rules/model-assignment.md` §1 「단일 Edit 예외」 적용
- 이미 subagent 내부에서 실행 중인 작업
- Read/Glob/Grep 단독 1~2회 (탐색 목적, 3회+ 시 scout 위임)

### 위임 판단 보고

위임 계획은 **별도 사전 턴으로 보고하지 않는다**(프롬프트 1회 종속) — **최종 보고에 배정 내역 포함**으로 가시화하고, 사용자 결정이 필요한 위임(고위험·비가역)만 사전 질문한다.

**기본: 약식 보고 (1~2줄)**: 모델·에이전트·이유를 1~2줄로 적는다.

**3개+ 작업 시: 테이블 보고** — `📋 모델 배정:` + 표(컬럼: # | 작업 | 모델 | 에이전트 | 이유)

**메인 세션 직접 처리 항목은 반드시 이유 열에 §1 해당 조건을 명시**한다.

### subagent 작업명 모델 접두사

Agent 호출 시 `description`에 모델명 소문자 접두사 필수 — 형식 `"{모델}: {작업 3-5단어}"` (예: `"sonnet: Modify 4 files"`). 접두사는 실제 `model` 값과 **반드시 일치**. 결과 보고에도 모델명 포함. 예시·세부 → `rules-lazy/prompt-routing-detail.md` § Step 1.5.

### 보고 생략 조건
위임 생략 조건 해당 시(메인 세션 직접 처리) 또는 사용자가 "보고 생략해" 명시 시 보고 불필요.

### § Mem0 구체화 패턴 학습

구체화(Step 1) 완료 후, 사용자가 실제로 의미한 내용을 자동 저장 → `rules-lazy/mem0-templates.md` T20 참조
→ 다음 유사 요청 시 검색으로 재질문 없이 즉시 해석: "이전에 '{구체화 결과}'로 해석했습니다. 동일하게 진행할까요?"

## Step 1.6 — 도구 의존성 게이트

작업이 특정 외부 도구·설정을 전제하는데 부재 감지 시(해당 도구가 필요한 시점에 `command -v` 1회 — 전수 스캔 금지) → **작업 시작 전** 3택 질문: A) 지금 설치·세팅 위임 / B) 사용자 직접(명령서 출력) / C) 사용 안 함(대체 수단 명시). mem0 기록으로 재질문 방지. 서드파티 스킬은 searcher 격리 검토 선행 — 상세: `~/.claude/rules-lazy/tool-dependency-gate.md`

## Step 1.7 — 반복 요청 전처리 생략

- **생략 시 보고 (MANDATORY — 1줄)**: `[전처리 생략 — N회 동일 패턴]` 출력. 침묵 금지 — 사용자 통제 유지.
- **신규 모호성이면 Step 1 우선**: 반복 패턴이라도 이번 요청이 Step 1 MANDATORY 표에 해당하면 구체화 없이 생략 금지.
- 자동 생략 4조건·생략 거부 목록·생략 형식·`/loop` 제안: `rules-lazy/prompt-routing-detail.md` § Step 1.7.

---

## Step 2 ~ 3 — 추천 + 패널 시각화 (lazy)

> **상세**: `rules-lazy/prompt-routing-recommend.md` 참조 (추천 필요 시 lazy 로드)
> 처리 흐름 다이어그램도 동 파일에 포함.
