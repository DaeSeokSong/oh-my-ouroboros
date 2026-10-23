# Mem0 자동 사용 규칙

> **로드 시점**: 항상 (모든 대화에 적용)
> **핵심 원칙**: Mem0 저장/검색은 자동 트리거 — 사용자 명시 불필요
> **entity scope**: user_id는 MCP 서버가 자동 주입. agent_id/run_id/enable_graph 사용 금지

> **연관 파일 (lazy load)** — 4계층 분리:
> - `~/.claude/rules-lazy/mem0-conventions.md` — 프로젝트명 식별·매칭 검색·중복방지/update_memory 트리거·Smart Retrieval 프로파일 (call-time 상세)
> - `~/.claude/rules-lazy/mem0-templates.md` — T01~T41 호출 템플릿 전체
> - `~/.claude/rules-lazy/mem0-fields.md` — 카테고리별 필드 카탈로그 + 조합 예시
> - 트리거 발화 시 해당 상세/T번호 템플릿/필드 카탈로그를 Read하여 참조
> (이 파일=always-on: 트리거·카테고리·limit 가드만. "어떻게"는 위 lazy 파일이 단일 출처)

---

## §0 MCP 도구 레퍼런스

### ToolSearch 필수

첫 Mem0 호출 전 `ToolSearch("select:mcp__mem0__…")` 1회(세션당 캐싱), 실패·MCP 미연결·오류 시 → `rules-lazy/mcp-fallback-mem0.md` 적용.

주 사용 6종: `add_memory`/`search_memories`/`get_memories`/`update_memory`/`delete_memory`/`delete_all_memories`(신중, limit 기본값은 §1.3). 파라미터 스키마는 ToolSearch 로드 시 제공. `get_memory`·`list_entities`·`delete_entities`는 필요 시 직접 호출.

---

## §1 metadata 컨벤션

### §1.1 저장 시 표준 구조

#### 필수 규칙 (MANDATORY)

| 위치 | 항목 | 규칙 |
|------|------|------|
| `text` 서두 | 날짜 | `YYYY-MM-DD` 형식 — 누락 금지 |
| `text` 서두 | 프로젝트명 | cwd 기반 프로젝트명 — 누락 금지 (크로스 오염 방지 핵심) |
| `text` 본문 | 맥락·서술 | 수치/config 포함 시 정확값 원문 명시 (infer=True 손실 방지) |
| `text` 본문 | 쓰기 provenance | 사용자 속성·선호·피드백 저장 시 근거 원문 인용 동봉, 추론분은 `(추정)` 태그, 근거 없으면 미기록 — 상세: `mem0-conventions.md` §C-2 |
| `metadata` | `category` | 필수 — §1.2 표준값 7종 중 선택 |
| `metadata` | `source` | 필수 — 호출 주체 (memory-write, qa-process 등) |

모든 검색 쿼리는 `[프로젝트명]` prefix 필수(크로스 오염 방지). 프로젝트명 식별(§A)·저장 전 `update_memory` 우선 판정(§C)·provenance(§C-2) 정본: `rules-lazy/mem0-conventions.md`(호출 직전 로드).

### §1.2 category 표준값 (7종)

| category | 용도 | 저장 주체 |
|----------|------|---------|
| `decision` | 합의 결정, 아키텍처, 하이퍼파라미터, 데이터셋 변경 | memory-write, discuss |
| `experiment` | Phase 완료 결과, 수치, 베이스라인 | experiment 스킬 |
| `code_pattern` | QA 실패 이력, 리팩토링 패턴, 코드 컨벤션, 경로 | qa, coder |
| `paper` | 논문 요약, 핵심 수식, 관련성 평가 | paper-read 스킬 |
| `feedback` | 사용자 교정, 도구/환경 결정, 프롬프트 구체화 패턴 | learner, prompt-routing |
| `discuss` | 토론 회의록 요약, 핵심 합의, 근거 | discuss 스킬 |
| `context` | 세션 상태, compact handover, 외부 작업 이력 (Confluence/Jira/Git) | compact, docs, gitops |

### §1.3 검색 시 표준 형식

```
search_memories(query="관련 키워드 자연어", filters={"metadata": {"category": "..."}}, limit=5)
```

- 다중 카테고리 검색: 단일 호출로 다중 카테고리 지정 불가 → N회 순차 호출

> **기본 limit 강제**: `search_memories` limit=5, `get_memories` limit=10 + filter 필수 (main 컨텍스트 보호 — `rules-lazy/token-efficiency.md` 참조). 초과 사용 시 명시적 사용자 요청 필요.

### §1.4 Smart Retrieval 규칙 (모든 search_memories 호출 시 적용)

모든 검색은 3축 병행 — **History**(과거 이력·결정·실패/성공 패턴) / **Current**(현재 작업 직결 맥락·활성 결정) / **Future**(다음 단계·미완 TODO). 쿼리 실행 패턴·관련성 필터·작업 유형별 채널 프로파일: `rules-lazy/mem0-conventions.md` §D

### §1.5 메모리는 advisory — 현재 코드·공식문서 우선 (MANDATORY)

- 검색으로 불러온 메모리는 **참고용(advisory)** 이며 ground truth가 아니다.
- 검색 히트가 하네스 룰·스킬·knowledge 파일을 지목하면 **그 파일도 함께 로드**해 대조(불완전 로딩 방지), 누락 발견 시 해당 메모리에 정본 경로 update.
- 파일·함수·플래그·경로·수치·API 지목 시 **현재 코드/공식 문서로 재확인 후** 사용.
- 충돌 시 **현재 실제(코드·docs)가 우선** → 해당 메모리는 `update_memory` 갱신 또는 `번복됨` 표시(`rules-lazy/mem0-conventions.md` §C). 오래된 결정은 archive(`rules-lazy/memory-promotion.md`).
- 근거·실측 경위: `rules-lazy/mem0-conventions.md` §C-3

---

## §2 자동 트리거 마스터 테이블

> 호출 템플릿 본문은 `~/.claude/rules-lazy/mem0-templates.md` 참조 — T번호로 인덱싱

### MANDATORY 트리거 — 반드시 실행

| # | 이벤트 | 작업 | category | source | 비고 |
|---|--------|------|----------|--------|------|
| T01 | 사용자 합의 감지 ("~로 결정", "알겠어", "그렇게 하자") | add | decision | memory-write | 즉시 저장 |
| T02 | compact 직전 (MANDATORY — 스킵 금지) | add | context | compact_handover | 진행률+활성 결정+config 포함 |
| T03 | 세션 시작/continuation | search ×3 + pattern-detect + usage-check | context → decision → code_pattern (3축) | — | 3축 복원 + 반복 패턴·인프라 점검(모델은 판정·조치 제안만, 직접 실행 금지). **스킵**: 단순 질문·단발 대화면 첫 작업성 요청 시점으로 연기(작업성 요청의 정의: CLAUDE.md 원칙 3.5). 판정 기준·이상 항목별 조치: `rules-lazy/mem0-templates.md` T03 |
| T04 | QA 검증 FAIL 발생 | add | code_pattern | qa-process | 실패 원인·수정 내용 + **avoidance_rubric** 형식, 다음 작업 시 search로 자동 로드. 상세: `rules-lazy/mem0-templates.md` T04 |
| T06 | /discuss 토론 완료 | add | discuss | discuss | 핵심 합의·근거 요약 저장 |
| T07 | /discuss 시작 전 | search ×3 | (discuss+decision 병합쿼리) → (experiment+paper 병합쿼리) → feedback 단독 | — | 3회로 축소 |
| T08 | /paper-read 리뷰 완료 | add | paper | paper-read | 논문 요약·수식·관련성 저장 |
| T09 | /paper-read 시작 전 | search | paper | — | 기존 논문 이력 확인 |
| T10 | experiment Phase 완료 | add | experiment | experiment | 결과 수치 정확값 포함 |
| T38 | 음성 결과 확정 시 (fix-then-retest 후에도 음성) / 인프라 실패 확정 시 | add | experiment or code_pattern | failure-analysis | T10 직후 실행 (형식: templates T38) |
| T39 | 양성 결과 확정 시 (gate 기준 충족) | add | experiment | success-analysis | T10 직후 실행 (형식: templates T39) |
| T11 | experiment Stage A 전 | search ×4 | experiment → paper → decision → discuss 순차 | — | 4회 순차 호출 |
| T12 | 사용자 교정 감지 ("이렇게 하지 마", "앞으로는") | add + search | feedback | learner | 저장 후 검색 → **3회+** 발견 시 `/learn-from-feedback` 자동 트리거 (룰 후보 제안). 이 자동 트리거는 스킬 자동 제안 「질문 먼저」의 명시 예외다(`/solve`와 같은 급). 교정 발화는 `~/.claude/scripts/correction-detect.sh`가 T12 후보로 기계 기록 |
| T40 | 반복 패턴 3회+ (SessionStart pattern-detect 주입) | add + search | feedback | pattern-detect | 후보는 `~/.claude/scripts/pattern-detect.sh`가 `_evolve/candidates.tsv`에 기계 기록, 미결 3종(pending·pending-bench·pending-approval)을 세어 1줄 보고 |
| T41 | 에이전트 작업 실패·재작업 신호 (`rules-lazy/agent-eval.md` §1) | add + search | code_pattern | agent-eval | 파일 기록은 `bash ~/.claude/scripts/t41-append.sh <role> <dim> "<signal>"`. 계수는 `grep -c 'T41:' _audit/history.md` |

### citation-verifier MANDATORY 트리거

4상황(인용 직전·SOTA 참조·메커니즘 근거·2020년 이전) 시 라우팅 3.6 + `rules-lazy/tavily-auto.md` § citation-verifier 검증.

### OPTIONAL (T05, T13~T37) — 해당 시 실행 (lazy)

> **상세 표·호출 템플릿 본문**: `~/.claude/rules-lazy/mem0-templates.md` § OPTIONAL 트리거 마스터 테이블

---

## §4 infer 전략

- **기본**: `infer=True` (명시하지 않아도 기본 적용). 수치는 §1.1 대로 text 에 정확값 원문을 적는다.
