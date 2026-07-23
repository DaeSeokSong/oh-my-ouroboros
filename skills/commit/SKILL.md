---
description: "Use when: git commit 전. Jira 이슈 연결, 파일 스테이징, 커밋 메시지 작성 (영어, type: Subject 형식)."
model: sonnet
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
  - mcp__mem0__add_memory
  - mcp__mem0__search_memories
  - mcp__mem0__update_memory
  - mcp__claude_ai_Atlassian__getJiraIssue
  - mcp__claude_ai_Atlassian__getTransitionsForJiraIssue
  - mcp__claude_ai_Atlassian__transitionJiraIssue
  - mcp__claude_ai_Atlassian__addCommentToJiraIssue
---

# Git Commit Workflow

`git commit` 전 반드시 실행하는 스킬.
Jira 이슈 확인 → 파일 스테이징 → 커밋 메시지 작성 → 사용자 승인 흐름을 안내합니다.

## 실행 흐름

1. Jira 이슈 번호 확인 → 메시지 앞에 삽입 여부 결정
2. `git status`로 변경 파일 목록 확인
3. **변경량 판단** → 대량 변경 시 의미 단위 분할 (아래 § 참조)
4. 관련 파일 개별 스테이징 (`git add [파일명]`, `-A` 금지)
4.5. **반복 거부 패턴 대조** (2026-07-21, harness-engineering repository-review 4단계 이식): diff를 과거 거부·교정 이력과 대조 — `search_memories(query="[프로젝트명] 거부 교정 반복 수정", filters={"metadata":{"category":"feedback"}})` + code_pattern(T04 avoidance_rubric) 1회씩. 과거 거부된 패턴이 diff에 재등장하면 커밋 전 사용자에게 지적 (예: 금지된 트레일러·거부된 네이밍·교정받은 표현). 매칭 없으면 침묵 통과 — 소음 금지.
5. 커밋 메시지 초안 작성 (아래 형식 적용)
6. 사용자 검토 후 직접 실행 (AI 직접 실행 금지 — 예외: 명시적 허용 시)

## 대량 변경 시 분할 커밋 (MANDATORY)

변경 파일이 **5개 이상** 또는 diff 라인이 **200줄 이상**이면 의미 단위로 분할하여 순차 커밋한다.

### 분할 기준 (의미 단위)

| 분할 단위 | 예시 |
|----------|------|
| **기능별** | 새 기능 A / 새 기능 B / 버그 수정 |
| **레이어별** | rules 변경 / commands 변경 / settings 변경 |
| **Phase별** | Phase 1 작업 / Phase 2 작업 / Phase 3 작업 |
| **타입별** | refactor 묶음 / feat 묶음 / fix 묶음 |

### 분할 흐름

```
Step 1. git status → 전체 변경 파일 목록 확인
Step 2. 파일들을 의미 단위로 그룹핑 (테이블 형태로 사용자에게 제시)
Step 3. 사용자 승인 후 그룹 순서대로 순차 커밋
         - 각 커밋: git add [그룹 파일들] → git commit -m "..."
         - 다음 그룹으로 넘어가기 전 사용자 확인 (예외: "순차 진행해" 허용 시 자동)
Step 4. 전체 완료 후 git log --oneline -N 으로 커밋 목록 보고
```

### 분할 제안 형식

```
변경 파일이 N개입니다. 아래와 같이 M개 커밋으로 분할하겠습니다:

| # | 커밋 제목 (안) | 파일 |
|---|--------------|------|
| 1 | refactor: ... | rules/A.md, rules/B.md |
| 2 | feat: ...     | commands/C.md |
| 3 | chore: ...    | settings.json |

이 순서로 진행할까요?
```

### 단일 커밋 허용 조건
- 변경 파일 4개 이하 + diff 200줄 이하
- 사용자가 "한 번에 커밋해" 명시
- 모든 변경이 동일 목적에 귀속되는 경우 (예: 오타 일괄 수정)

## 커밋 메시지 형식

```
<type>: <subject>

<body>

<footer>
```

> ⛔ `<type>(<scope>):` 형식 금지 — scope 괄호 사용 금지

## 7가지 기본 규칙

1. 제목과 본문을 빈 행으로 구분
2. 제목은 50글자 이내
3. `<type>: ` 뒤 subject의 첫 글자는 **대문자**로 시작 (예: `feat: Add TOSHIBA exclusion filter`)
4. 제목 끝에 마침표 제외
5. 제목은 명령문 사용 (과거형 금지)
6. 본문의 각 행은 72글자 이내
7. "어떻게"보다 "무엇"과 "왜"를 설명

## 언어 규칙 (MANDATORY)

커밋 메시지(제목·본문·footer)는 **반드시 영어**로만 작성 — 한글 금지

예시: `fix: Pass pred_transforms to MakoDataModule instead of None`

## AI 커밋 행동 규칙 (MANDATORY)

- AI는 기본적으로 `git commit` 명령을 **직접 실행하지 않는다**
- `git add [파일명]` (개별 파일 명시) 수행 후 아래 형식으로 커밋 메시지를 추천
- 사용자가 메시지를 검토·승인한 뒤 **직접** commit을 실행하는 것이 기본 흐름
- **예외**: 사용자가 명시적으로 "커밋 실행해", "커밋해" 등 직접 실행을 허용하면 AI가 실행 가능
- **git push AI 직접 실행 금지** — push는 사용자가 직접 수행 (명시적 허용 시에도 금지)

```
추천 커밋 메시지:
  git commit -m "type: Subject"
```

## Type 종류

| Type | 설명 |
|------|------|
| `feat` | 새로운 기능 |
| `fix` | 버그 수정 |
| `build` | 빌드 파일 수정 |
| `chore` | 자잘한 수정 |
| `ci` | CI 설정 수정 |
| `docs` | 문서 수정 |
| `style` | 코드 스타일/포맷 |
| `refactor` | 코드 리팩토링 |
| `test` | 테스트 코드 수정 |

## Jira 이슈 연결 (MANDATORY)

> **생략 조건**: `~/.claude/env-config`에 `CONFLUENCE_MCP=false`이면 이 섹션 전체 생략 (이슈 질문 안 함)

커밋 메시지 추천 전 Jira 이슈 연결 여부 반드시 확인:

```
연결할 Jira 이슈 번호가 있으신가요? (예: NRS-630, NRS-631)
없으면 생략합니다.
```

- 이슈 있음: `NRS-630 feat: Subject` (이슈 번호를 메시지 맨 앞에 스페이스로 구분)
- 이슈 여러 개: `NRS-630 NRS-631 fix: Subject`
- 이슈 없음: 생략

형식 예시:
```
NRS-630 feat: Add stratified split v2

NRS-630 NRS-631 fix: Fix device inconsistency in inferencer
```

## Footer

- 이슈 참조: `close #1233` (main 병합 시 이슈 자동 닫힘)

## Jira 댓글 자동 기록 (MANDATORY)

> **생략 조건**: `~/.claude/env-config`에 `CONFLUENCE_MCP=false`이면 이 섹션 전체 생략

아래 중 하나 해당 시 해당 Jira 이슈에 작업 내용 요약 댓글 추가:
- AI가 한 작업 단위가 완전히 끝났다고 판단한 시점
- 사용자가 특정 Jira 이슈에 "기록해줘" 요청 시

댓글 형식 규칙:
- 줄 수: 10줄 이내
- 글머리 기호: `*` 사용 (하이픈 `-` 금지)

```
* {날짜} 작업 내역
* {항목 1}
* {항목 2}
* 커밋: {커밋 해시 or 브랜치명}
```

### § Mem0 커밋 일관성

#### 커밋 패턴 저장
커밋 완료 시: → mem0-auto.md T13 참조

#### QA 이력 연결
커밋 대상 파일의 과거 QA 이슈 검색: → mem0-auto.md T05 참조

---

## 이슈 완료 처리

> **생략 조건**: `~/.claude/env-config`에 `CONFLUENCE_MCP=false`이면 이 섹션 전체 생략

사용자가 "완료됐어" / "Done으로 바꿔" 요청 시:

1. 기존 댓글 조회 (`getJiraIssue` + comment_limit 최대) → 작업 이력 파악
2. 이슈 description 보강 — 댓글 핵심 내용 추출하여 업데이트
3. Done 전환 → `getTransitionsForJiraIssue`로 transition ID 조회 후 `transitionJiraIssue` 실행

처리 순서: 댓글 조회 → description 보강 → 상태 Done 전환 → 사용자 보고
