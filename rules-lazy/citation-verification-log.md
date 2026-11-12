# citation-verifier 검증 이력 로그 + 리포팅 규칙

> **로드 시점**: citation-verifier 검증 완료 후(호출자가 로그 append 시) + 집계 조회 요청 시
> **핵심 원칙**: 2층 구조 — mem0 T21 = 요약·검색(에이전트 회상) / 상세 로그 = evidence 보존·사람 감사(audit)

## 2층 구조 설명

| 층 | 저장 대상 | 주체 | 목적 |
|----|---------|------|------|
| **mem0 T21** | 검증 요약(verdict/supporting/contrasting/철회/confidence) | **main(호출자)** — source metadata=citation-verifier (2026-07-15: verifier 직접 저장 금지) | 에이전트 회상·검색 |
| **상세 로그** | 전체 evidence(스니펫·URL·sources 포함) | **main(호출자)** | 감사 가능한 evidence 보존 |

> **citation-verifier는 verdict 반환만 한다.** 파일 쓰기는 주체가 아니다(untrusted 격리). 호출자(main)가 최종 verdict(대조 또는 종합) 수신 후: 1) mem0 T21 요약 저장 2) 이 규칙에 따라 상세 로그에 append.

---

> **검증 결과 요약 저장은 mem0 T21(source=citation-verifier)이 단일 담당 — 중복 저장 금지.** 철회 2차확인은 citation-verifier 철회 게이트(Crossref+OpenAlex, Retraction Watch 데이터 내장)에 포함.

---

## §1 상세 로그 스키마 (append-only)

### 로그 파일 위치

프로젝트별 append-only 마크다운: `docs/citation-verifications.md`
- 프로젝트 미지정 시: 사용자에게 경로를 질문한 후 append
- 파일이 없으면 첫 append 시 생성 (헤더 포함)

### 검증 1건당 append 형식

```markdown
## [YYYY-MM-DD] {title} ({DOI})

- **verdict**: 허용 | 경고 | 금지
- **mode**: 대조 | 디베이트(대조 + 옹호·회의·종합)
- **claim_check**: 항목마다 «인용 수치·주장 / 원문 위치 / 원문 값 / 일치·불일치·원문에 없음» (대조 모드)
- **supporting / contrasting / mentioning**: N / M / K (표본 N+M+K, 디베이트일 때만. 대조만 했으면 «해당 없음»)
- **retracted**: true | false
- **confidence**: high | med | low
- **fulltext_coverage**: high | partial | abstract-only

### evidence

| stance | citing (제목/DOI) | snippet | url |
|--------|-------------------|---------|-----|
| supporting | [제목] / [DOI] | "[원문 인용 스니펫]" | [url] |
| contrasting | [제목] / [DOI] | "[원문 인용 스니펫]" | [url] |

### sources

- [소스1 URL 또는 API endpoint]
- [소스2]
```

> mem0 T21 요약이 잃는 디테일(스니펫·URL)을 여기서 보존한다. 이 로그는 삭제 없이 append-only로 유지한다.

---

## §2 조회 흐름 (사용자 요청 시)

트리거 키워드: `"citation 검증 이력"`, `"논문 검증 현황"`, `"인용 검증 집계"`

### Step 1 — Mem0 검색

```
search_memories(query="citation-verifier 검증 verdict", filters={"metadata": {"category": "paper"}}, limit=100)
```

`source`가 `citation-verifier`인 항목만 필터. 프로젝트명으로 그룹핑.

### Step 2 — 간략 표 출력 (프로젝트별)

```
## [프로젝트명] citation 검증 이력 (N건)

| # | 날짜       | 논문 (저자, 연도)           | verdict   | confidence |
|---|------------|----------------------------|-----------|------------|
| 1 | YYYY-MM-DD | [제목] ([저자], [연도])    | [verdict] | [confidence] |

### 요약
- 총 검증: N건
- verdict: 허용 N / 경고 N / 금지 N
- ⚠ 주의: 철회(금지) N건, 경고(contrasting ≥ supporting) N건
```

### Step 3 — 크로스 프로젝트 요약 (말미)

```
## 전체 요약

| 프로젝트 | 검증 | 허용 | 경고 | 금지 |
|---------|------|------|------|------|
| [proj1] | N | N | N | N |
| [proj2] | N | N | N | N |
```

### Step 4 — 리포트 추출 질문 (MANDATORY)

간략 표 출력 후 반드시 사용자에게 질문:

```
상세 리포트를 PDF로 추출하시겠어요? (Y/N)
```

고르게 하는 것이므로 결정 팝업이 우선이다(CLAUDE.md 원칙 7.5).

- N → 종료
- Y → Step 5 진행

### Step 5 — 경로 수신 + 리포트 스크립트 생성

```
저장 경로를 알려주세요 (절대 경로).
예: /your/workspace/reports/citation_20260609.pdf
```

사용자가 경로 입력 후:
1. Python 스크립트 생성 (reportlab 기반) — 표준 위치: `~/.claude/scripts/gen_citation_report.py` 또는 프로젝트별 `docs/paper/scripts/gen_citation_report.py`
2. 실행 명령서를 사용자에게 보고:
   ```
   코드 준비 완료: [스크립트 경로]
   실행 명령:
     cd [작업 디렉토리]
     uv run python [스크립트 경로] --output [사용자 지정 PDF 경로]
   ```
3. 사용자가 직접 실행 — AI는 실행하지 않음 (code-execution.md 준수)

---

## §3 표 구조 (PDF 상세 리포트)

### 표지 (1페이지)
- 집계 생성 일시
- 총 검증 건수
- 프로젝트 개수
- verdict별 건수 (허용/경고/금지)

### 본문 — 프로젝트별 섹션

각 프로젝트마다 아래 필드 포함 테이블:

| # | 날짜 | 논문 | DOI | supporting | contrasting | mentioning | retracted | verdict | confidence | fulltext_coverage |

(가로 방향 A3 또는 세로 다단 레이아웃)

### 말미
- 금지(철회/정정) 논문 전체 목록 + 사유
- contrasting ≥ supporting 논문 목록 (경고 항목)

---

## §4 리포트 스크립트 명세

### 필수 라이브러리
- `reportlab` (우선) 또는 `weasyprint` (HTML→PDF)
- `uv add reportlab` (프로젝트 의존성은 `uv add`·`uv sync` 로만 — `rules-lazy/uv-env.md`)

### 스크립트 파일 위치
- 표준 위치: `~/.claude/scripts/gen_citation_report.py` 또는 프로젝트별 `docs/paper/scripts/gen_citation_report.py`
- 실행 예: `uv run python ~/.claude/scripts/gen_citation_report.py --output /path/to/output.pdf`

### 인자
- `--output`: 출력 PDF 절대 경로 (필수)
- `--project`: 특정 프로젝트만 추출 (선택, 기본값=전체)
- `--since`: 시작 날짜 (선택, YYYY-MM-DD)

### 데이터 소스
- mem0 `search_memories(query="citation-verifier 검증 verdict", filters={"metadata": {"category": "paper"}}, limit=100)` 결과 파싱
- 상세 evidence: `docs/citation-verifications.md` 파싱 병합

### 스크립트 범위

| 항목 | 범위 |
|------|------|
| 파일 위치 | `~/.claude/scripts/gen_citation_report.py` (글로벌) 또는 `docs/paper/scripts/gen_citation_report.py` (프로젝트별) |
| 구현 상태 | 구현됨: `~/.claude/scripts/gen_citation_report.py` (머리 주석이 데이터 소스·인자의 정본 — 상세 로그 `docs/citation-verifications.md` + Mem0 REST 병합, 실소스 0건이면 exit 2) |
| 실행 주체 | 사용자 직접 실행 원칙 유지 |

> 이 절의 인자·소스 설명과 스크립트 머리 주석이 다르면 스크립트가 정본이다.

### §4.1 PDF 생성 실패 복구 체크리스트

`uv run python gen_citation_report.py` 실패 시 아래 5항목 순차 확인:

1. **`reportlab` import 오류** → `uv add reportlab` 실행(환경 변경이라 사용자 직접)
2. **데이터 없음** (Mem0 결과 0건) → `search_memories(query="citation-verifier 검증", filters={"metadata": {"category": "paper"}})` 직접 실행 후 수동 확인
3. **인코딩 오류** (UTF-8 미지정) → 스크립트에서 `sys.stdout.reconfigure(encoding='utf-8')` 확인
4. **경로 권한 오류** → 사용자 지정 경로 쓰기 권한 확인 (`ls -la {경로}`)
5. **전부 실패** → CSV fallback (`gen_citation_report.py --output xxx.csv` 지원 추가)

각 항목은 1줄 진단 출력 + 수정 명령 제시. 체크리스트 5항목 초과 금지.

---

## §5 생략 조건

- 이 규칙은 citation-verifier 검증이 발생할 때만 적용
- 집계 조회는 사용자 명시 요청 시에만 실행
- PDF 추출 질문은 간략 표 출력 후 반드시 수행 — 생략 금지
- 검증 0건 시: 집계 표 대신 "검증 이력 없음" 1줄 출력
