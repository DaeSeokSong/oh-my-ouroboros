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
4.7. **보안 민감 diff → /security-review 제안** (2026-07-31): diff에 인증·인가 로직, 외부 입력 처리(파싱·쿼리·경로 조립), 신규 의존성 추가, 네트워크 경계 변경 중 하나라도 포함되면 커밋 전 빌트인 `/security-review` 1회를 **제안**(강제 아님, 무료·경량·diff 한정). 해당 없으면 침묵 통과.
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
> **하네스 `feat:` 커밋은 `Intent:` 줄 필수 (2026-09-06)**: CLAUDE.md·rules·rules-lazy·skills·agents·scripts·tools·config·settings.json 을 바꾸는 `feat:` 커밋은 본문에 `Intent: intent/YYYY-MM-DD-<slug>.md` 줄을 두고 그 파일이 stage 되었거나 추적 중이어야 한다. **`fix:`·`refactor:` 커밋도 rules·rules-lazy·agents·skills·scripts·tools·config 에 새 파일(신설)이 있으면 같은 `Intent:` 줄이 필요하다**(2026-09-14 — 타입만 바꿔 구조를 신설하는 우회 차단, 기존 파일 수정만이면 대상 아님). Jira 접두(`ABC-630 feat: …`)는 `scripts/ci-gate-commit-msg.sh`(commit-msg 훅)가 벗겨낸 뒤 타입을 판별한다. 훅이 없으면 차단한다.
>
> **선택 트레일러 `Candidate: <id>` (2026-10-17, 학습 후보 연결)**: 사용자가 «커밋해» 지시에 후보 id 를 **적었을 때만** 본문 끝에 `Candidate: <id>` 줄을 넣는다(후보와 무관하다고 밝힌 경우 `Candidate: none`). 모델이 대장을 보고 임의로 고르거나 끼워 넣지 않는다. 형식은 id 한 토큰이며 타입과 무관하다. commit-msg 훅이 id 존재·미결 상태·stage 의 규칙 경로(agents·rules·rules-lazy·skills·CLAUDE.md) 변경을 확인해 **어긋나면 경고만** 하고(커밋은 막지 않음), post-commit 훅(`scripts/ci-gate-post-commit.sh`)이 통과한 건을 `set <id> accepted --note commit=<해시>` 로 대장에 잇는다. AI 트레일러 금지(Co-Authored-By 등)와는 별개이며 이 줄은 AI 흔적이 아니다.

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
연결할 Jira 이슈 번호가 있으신가요? (예: ABC-630, ABC-631)
없으면 생략합니다.
```

- 예시의 `ABC` 자리는 그 프로젝트의 이슈 키 접두다. 사용자가 준 이슈 번호를 그대로 쓴다.
- 이슈 있음: `ABC-630 feat: Subject` (이슈 번호를 메시지 맨 앞에 스페이스로 구분)
- 이슈 여러 개: `ABC-630 ABC-631 fix: Subject`
- 이슈 없음: 생략

형식 예시:
```
ABC-630 feat: Add stratified split v2

ABC-630 ABC-631 fix: Fix device inconsistency in inferencer
```

> Jira 접두가 붙어도 `Intent:` 판정은 그대로 적용된다 — commit-msg 훅이 제목 앞 이슈 접두를 벗겨낸 뒤 `feat:`·`fix:`·`refactor:` 타입을 판별한다(§ 위 하네스 `feat:` 커밋 안내).

## Footer

- 이슈 참조: `close #1233` (main 병합 시 이슈 자동 닫힘)

## Jira 댓글 자동 기록 (MANDATORY)

> **생략 조건**: `~/.claude/env-config`에 `CONFLUENCE_MCP=false`이면 이 섹션 전체 생략

아래 중 하나 해당 시 해당 Jira 이슈에 작업 내용 요약 댓글 추가:
- AI가 한 작업 단위가 완전히 끝났다고 판단한 시점
- 사용자가 특정 Jira 이슈에 "기록해줘" 요청 시

댓글 형식 규칙 (기준 표본: 2026-10-01 사용자 결정으로 고른 댓글 하나, 이슈 · 댓글 번호는 `knowledge/harness/rules-project-server-history-2026-11-10.md` § commit. 종전 «10줄 이내 · 날짜 머리줄 4줄 틀»은 폐지):
- 본문은 목록만 쓴다. 목록 밖 문단, 날짜 머리줄, 보고용 머리말(«무엇을:»·«왜:»·«어떻게:»)을 붙이지 않는다.
- 표는 허용한다(목록 아래 참고 표, 머리 줄 + 구분 줄 GFM 꼴, 2026-11-06 사용자 지시).
- 최상위는 번호 목록이고 항목 하나가 주제 하나다(문제 이름이나 한 일을 한 줄로). 주제가 하나여도 번호 목록으로 쓴다.
- 주제 아래는 글머리이고, 해당하는 줄만 이 순서로 둔다.
  - 원인: 왜 생겼는지
  - 수정: 무엇을 어떻게 바꿨는지 (이유가 필요하면 하위 글머리 «이유: …»)
  - 확인 또는 결과: 시험·재실행 수치 (분모·날짜 포함)
  - 정리 페이지: Confluence 페이지 인라인 카드
  - 커밋: 해시 7자와 괄호 설명. 예) 커밋: 9e531bb (코드·테스트), 142d5d0 (문서)
- 한 줄이면 «수정: 내용», 여러 줄이면 라벨만 쓰고 하위 글머리로 내린다.
- 문체는 개조식(«~였음»·«~남김»)과 쉬운 말. 수치는 분모와 함께 쓴다.
- 그림은 그 그림을 설명하는 글머리 바로 아래에 둔다.
- 줄 수: 주제마다 필요한 줄만 쓴다(상한 없음).
- 작성·수정은 `~/.claude/scripts/jira_comment.py` 로만 한다(프로젝트 cwd 에서도 실행되도록 절대형). preview 출력을 사용자에게 보이고 승인받은 뒤 post·update 한다.

본문 파일 예(마크다운, 스크립트가 ADF 로 바꾼다):
```
1. 입력 검증이 실패해도 오류 없이 다른 방식으로 계산하던 문제
   * 원인
     * 예외가 나거나 폭이 0 이하이면 오류를 내지 않고 예비 경로로 계산했음
   * 수정: 엄격 모드에서는 예비 경로 없이 바로 오류를 냄
     * 이유: 측정 기준이 달라 다른 방식 값과 섞이면 안 됨
   * 확인: 단위 테스트 8건 통과, ABC-962 63장 재실행에서 응답 동일
   * 정리 페이지: https://<사이트>/wiki/spaces/DR/pages/<ID>
   * 커밋: 9e531bb (코드·테스트), 142d5d0 (문서)
```

왜 형식을 표본에 묶었나(2026-10-01 실사고): 한 이슈의 댓글이 compact 뒤 남은 옛 스킬 사본(4줄 틀)만 보고 쓰여 머리말 «무엇을: · 왜: · 어떻게:» 이 붙었고 미리보기 승인 없이 게시됐다. 그래서 이 절을 `scripts/jira_comment.py preview` 가 실행 때마다 원문 그대로 찍는다(이 절을 고치면 출력도 바뀐다). 절 제목 «## Jira 댓글 자동 기록»은 스크립트가 찾는 표지라 바꾸지 않는다.

### Jira 댓글 쓰기·고치기 = REST (MANDATORY, 2026-09-29 사용자 지시 · 실측)

**도구**: `~/.claude/scripts/jira_comment.py`(2026-10-01). `get`(구조 조회) · `preview`(형식 절 + 미리보기 + 스탬프) · `post` · `update`(`--body-file`, 이미지가 든 댓글용 `--patches`, 새 그림을 넣는 `--figures`) · `attach`(이슈 파일 첨부, 8번). 미리보기와 다른 본문·그림·파일은 게시되지 않는다. 즉석 curl·python 으로 직접 호출하지 않는다. 회신(6번, GraphQL)만 아직 스크립트 밖이다.

댓글 작성·수정은 MCP `addCommentToJiraIssue` 가 아니라 REST 스크립트로 한다. 본문(ADF JSON)은 모델이 출력하지 않고 스크립트가 만든다. Confluence 의 `skills/confluence/SKILL.md` §10-1 과 같은 이유다(본문이 모델을 거치면 잘리거나 바뀐다).

1. **엔드포인트**: 작성 `POST /rest/api/3/issue/{키}/comment`, 수정 `PUT /rest/api/3/issue/{키}/comment/{id}?notifyUsers=false`. 자격증명은 Confluence REST 와 같은 `~/.atlassian_token` 이다(명령줄·대화에 토큰을 쓰지 않는다).
2. **게시 전 승인**: 본문 미리보기를 사용자에게 보이고 승인받은 뒤 게시한다. 수정은 `notifyUsers=false` 로 알림을 끈다.
3. **게시 후 대조**: 재조회(GET)해서 카드 수·문구를 기계 대조한다.
4. **이미지가 든 댓글 수정**: GET 한 ADF 를 통째로 받아 해당 텍스트 노드만 치환하고 `mediaSingle`·`media` 노드는 건드리지 않는다. 수정 전후 media id 집합이 같은지 확인한다(실측: 8개 동일). 마크다운으로 갱신하면 이미지가 유실될 수 있다.
5. **Confluence 페이지 링크**: URL 문자열이 아니라 인라인 카드로 건다. `{"type":"inlineCard","attrs":{"url":"<페이지 URL>"}}`
6. **회신(대댓글) = GraphQL** (2026-09-29 시험 성공): MCP `addCommentToJiraIssue` 에는 부모 인자가 없고 추가 인자도 받지 않는다. 공개 REST v3 명세에도 부모 필드가 없다. 회신은 GraphQL 게이트웨이(`https://<사이트>/gateway/api/graphql`, 같은 `~/.atlassian_token` Basic 인증)로 만든다.
   - 호출: `mutation <이름> { jira { addComment(input: {issueId: <이슈 ARI>, threadParentId: "<부모 댓글 숫자 id>", content: {version: 1, jsonValue: <ADF doc>}}) { success errors { message } comment { ... on JiraPlatformComment { commentId threadParentId webUrl } } } } }`
   - 이슈 ARI 는 `ari:cloud:jira:<cloudId>:issue/<이슈 숫자 id>` 이고, cloudId 는 `GET https://<사이트>/_edge/tenant_info` 로 얻는다. 오퍼레이션 이름이 없으면 게이트웨이가 거부한다.
   - 확인: 응답의 `threadParentId` 와 부모의 `childComments` 를 되읽는다(`childComments` 는 루트 댓글에서만 조회된다). REST v3 도 읽을 때는 회신에 `parentId` 필드를 붙여 준다(명세 미기재). REST 로 `parentId` 를 줘서 만들 수 있는지는 시험하지 않았다.
   - 실측: 기준 표본 댓글 아래 시험 회신 생성, 되읽기와 사용자 화면 확인(번호는 위 경위 노트 § commit).
   - 기존 최상위 댓글을 회신으로 옮기는 API 는 없다. 옮기기 = 원본 ADF 백업 → 같은 ADF 로 회신 게시 → 새 회신과 원본 ADF 를 `localId` 제외 기계 대조(글자 수·노드·media id) → 일치할 때만 원본 삭제. 작성 시각은 새 시각이 되고 작성자는 토큰 소유자가 된다(09-29 실측: 32106 → 32108).
   - 새 댓글로 몰래 대체하지 않는다. 회신 본문도 게시 전 미리보기 승인(2번)을 거친다.
7. **새 이미지 넣기 = 도구의 `--figures` (REST 확인 2026-09-29, 도구화 2026-10-13)**: 사용자가 끌어다 놓지 않아도 된다. 별도 스크립트를 짜지 않는다(위 «즉석 호출 금지» 가 그림에도 적용된다).
   - 쓰는 법: 그림 목록 JSON `[{"anchor": "문단 첫머리 글귀", "file": "fig1.png"}]` 을 그림과 같은 `.scratch` 아래 폴더에 만든다(목록이 `.scratch` 밖에 있으면 거부) → `preview --issue 키 --comment-id ID --figures 목록.json` → 미리보기를 사용자에게 보이고 승인받는다 → `update --issue 키 --comment-id ID --figures 목록.json`. 새 댓글은 글을 먼저 `post` 한 뒤 그 댓글에 넣는다.
   - 넣는 자리: anchor 로 시작하는 문단이 댓글에 정확히 하나일 때 그 문단 바로 뒤(최상위 문단 또는 글머리 안 문단). 이미 그림이 붙어 있으면 넣지 않는다.
   - 그림 교체(2026-10-14): 목록 항목에 `"replace": true` 를 붙이면 그 자리 문단 바로 뒤의 옛 그림을 새 그림으로 바꾼다. 글자도 함께 고칠 때는 `--patches 치환.json --figures 그림.json` 을 같이 준다(preview·update 모두). 치환이 먼저 적용되고 자리 문단은 치환 뒤 글로 찾는다. 교체는 그림만 바꾸고 옛 그림 블록의 설명 글·배치는 유지한다(미리보기에 옛 그림 id 와 설명 글이 찍힌다). 옛 첨부는 이슈에 남는다.
   - 보장: 미리보기는 Jira 에 아무것도 올리지 않는다. 승인한 파일 내용(해시)과 그때의 댓글 상태에서만 게시된다. 글자·인라인 카드는 그대로이고 그림만 늘어난다. 수정 전 본문은 백업되고 알림은 꺼진다.
   - 제한: PNG 만, 파일은 목록 JSON 이 있는 폴더 안의 것만(미리보기에 실제 경로가 찍힌다. 민감 영상 등 엉뚱한 파일이 올라가지 않게 경로를 확인한다). 올라가는 첨부 이름에는 내용 해시 앞자리가 붙고, 그 이름의 첨부가 이미 있으면 다시 올리지 않는다.
   - 도구가 하는 일(판단 근거): 1) `POST /rest/api/3/issue/{키}/attachments`(multipart, 헤더 `X-Atlassian-Token: no-check`)로 첨부 id 를 받는다 2) `GET /rest/api/3/attachment/content/{첨부id}` 를 리다이렉트 없이 불러 303 Location 주소 안의 미디어 UUID 를 꺼낸다(첨부 메타데이터에는 UUID 가 없고 `?redirect=false` 는 파일 본문을 돌려준다) 3) `mediaSingle > media(type file · id UUID · collection "" · width · height · alt)` 를 넣어 댓글을 고친다 4) 되읽어 대조한다.
   - 렌더는 API 로 알 수 없으니 게시 뒤 사용자 화면 확인을 받는다. 댓글을 지워도 첨부는 이슈에 남는다.
   - 실측: 한 이슈의 기존 이미지 3건에서 Location UUID 와 media id 가 모두 일치했다. 새 첨부를 넣은 댓글은 사용자 화면에서 그림이 보였다. 2026-10-13 다른 이슈 댓글에 그림 5장(도구화 전 임시 스크립트, 되읽기 대조 통과). 이슈 · 첨부 · 댓글 번호는 위 경위 노트 § commit.
8. **이슈 파일 첨부 = 도구의 `attach` (2026-10-14)**: CSV 같은 일반 파일을 이슈에 붙일 때도 별도 스크립트를 짜지 않는다.
   - 쓰는 법: 올릴 파일을 `.scratch` 아래 폴더에 두고 같은 폴더에 목록 JSON `[{"file": "list.csv"}]` 을 만든다(민감 자료 폴더에서 바로 올리지 않는다, 목록이 `.scratch` 밖이면 거부) → `preview --issue 키 --attach 목록.json` → 미리보기를 사용자에게 보이고 승인받는다 → `attach --issue 키 --attach 목록.json`. 댓글에서 그 파일을 언급하려면 첨부 뒤 댓글을 따로 `post` 한다.
   - 미리보기: 파일마다 실제 경로·크기·해시·올라갈 이름이 찍힌다. CSV·TSV 는 첫 줄(120자)과 줄 수·열 수, JSON 은 최상위 키, TXT 는 첫 줄이 찍히고, 환자 식별로 보이는 열 이름(이름·생년·주민·등록번호·patient·mrn 등)이 있으면 경고가 붙는다. 그림·PDF 는 내용 단서가 없으니 경로로 확인한다.
   - 제한: csv · tsv · txt · json · pdf · png · jpg · jpeg 만, 파일당 50MiB·합계 100MiB, 한 번에 10개, 빈 파일 거부, 목록 JSON 폴더 안의 파일만. 압축 파일은 속을 볼 수 없어 받지 않는다. 올라가는 이름에는 내용 해시 앞 12자가 붙고, 그 이름·크기의 첨부가 이미 있으면 다시 올리지 않는다.
   - 보장: 미리보기는 Jira 에 아무것도 올리지 않는다. 승인한 파일 내용에서만 올라간다. 올린 뒤 이슈 첨부 목록을 다시 읽어 확인한다. 첨부를 지우거나 바꾸는 기능은 없다.
   - 이슈 본문(description) 에 넣는 경우는 시험하지 않았다. REST 로 만든 본문 그림이 회색 자리표시로 보인다는 보고(JRACLOUD-97869)가 있으니 본문은 게시 뒤 화면 확인을 꼭 받는다.

### 감시 서명 (커밋 직후)

커밋을 마친 직후 `bash ~/.claude/scripts/oversight-append.sh commit "<커밋 해시·요지>" "<사용자 승인 근거>"` 로 감시 서명 원장에 1줄 남긴다(`rules-lazy/oversight-signature.md`).

### § Mem0 커밋 일관성

#### 커밋 패턴 저장
커밋 완료 시: → `rules-lazy/mem0-templates.md` T32 참조(T13 은 리팩토링 패턴 저장이라 커밋용이 아니다)

#### QA 이력 연결
QA 이슈 재발 의심 시 커밋 대상 파일의 과거 QA 이슈 검색: → mem0-templates.md T05 참조

---

## 이슈 완료 처리

> **생략 조건**: `~/.claude/env-config`에 `CONFLUENCE_MCP=false`이면 이 섹션 전체 생략

사용자가 "완료됐어" / "Done으로 바꿔" 요청 시:

1. 기존 댓글 조회 (`getJiraIssue` + comment_limit 최대) → 작업 이력 파악
2. 이슈 description 보강 안 작성 — 댓글 핵심 내용 추출. **보강 전/후 본문 미리보기를 사용자에게 보이고 승인받은 뒤에만** 반영한다
3. Done 전환 → 위 승인 뒤에만. `getTransitionsForJiraIssue`로 transition ID 조회 후 `transitionJiraIssue` 실행

처리 순서: 댓글 조회 → description 보강안 미리보기 → 사용자 승인 → description 반영 → 상태 Done 전환 → 사용자 보고
