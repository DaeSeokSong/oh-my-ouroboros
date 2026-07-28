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

Mem0 MCP 도구는 deferred tool이므로 첫 사용 전 반드시 스키마 로드:
```
ToolSearch("select:mcp__mem0__add_memory,mcp__mem0__search_memories,mcp__mem0__get_memories,mcp__mem0__update_memory,mcp__mem0__delete_memory")
```
세션당 1회 실행, 이후 캐싱. 로드 실패 시 → `rules-lazy/mcp-fallback-mem0.md` 적용.

주 사용 6종: `add_memory` / `search_memories`(기본 limit=5) / `get_memories`(filter 필수, 기본 limit=10) / `update_memory` / `delete_memory` / `delete_all_memories`(신중). 파라미터 스키마는 ToolSearch 로드 시 제공되므로 여기 중복 명세하지 않는다 (2026-07-09 표 제거 — deferred loading과 이중 관리 방지). `get_memory`·`list_entities`·`delete_entities`는 드물게 — 필요 시 직접 호출.

---

## §1 metadata 컨벤션

### §1.1 저장 시 표준 구조

```
add_memory(
  text="[YYYY-MM-DD] [프로젝트명] [맥락]: 충분한 자연어 서술",
  metadata={"category": "...", "source": "..."}
)
```

#### 필수 규칙 (MANDATORY)

| 위치 | 항목 | 규칙 |
|------|------|------|
| `text` 서두 | 날짜 | `YYYY-MM-DD` 형식 — 누락 금지 |
| `text` 서두 | 프로젝트명 | cwd 기반 프로젝트명 — 누락 금지 (크로스 오염 방지 핵심) |
| `text` 본문 | 맥락·서술 | 수치/config 포함 시 정확값 원문 명시 (infer=True 손실 방지) |
| `metadata` | `category` | 필수 — §1.2 표준값 7종 중 선택 |
| `metadata` | `source` | 필수 — 호출 주체 (memory-write, qa-process 등) |

#### 상세 (call-time 참조 — `rules-lazy/mem0-conventions.md`)

저장/검색 호출 직전 아래 상세를 lazy 로드한다 (MANDATORY 동작은 유지, 설명만 이전):
- **프로젝트명 식별 규칙** + metadata에 project 필드를 두지 않는 설계 근거 → §A
- **프로젝트 매칭 검색 패턴**: 모든 `search_memories` 쿼리에 `[프로젝트명]` prefix 필수 (크로스 오염 방지) → §B
- **중복 방지**: 저장 전 동일 주제 검색 → 발견 시 `update_memory` 우선 + **update_memory MANDATORY 트리거 4종** (experiment 재실행/논문 재검토/결정 번복/합의 갱신) → §C

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

> **기본 limit 강제**: `search_memories` limit=5, `get_memories` limit=10 + filter 필수 (main 컨텍스트 보호 — `rules-lazy/token-efficiency.md` 참조). 초과 사용 시 명시적 사용자 요청 필요. (2026-04-19 1M 가드레일 신설)

### §1.4 Smart Retrieval 규칙 (모든 search_memories 호출 시 적용)

Mem0에서 메모리를 검색할 때 항상 3축 검색을 수행하여 현재 작업에 관련 있는 정보만 효율적으로 가져온다.

#### 3축 검색 (History / Current / Future)

모든 검색은 3축 병행 — **History**(과거 이력·결정·실패/성공 패턴) / **Current**(현재 작업 직결 맥락·활성 결정) / **Future**(다음 단계·미완 TODO). 쿼리 실행 패턴·관련성 필터·작업 유형별 채널 프로파일: `rules-lazy/mem0-conventions.md` §D (2026-07-28 표→1줄 압축: 쿼리 예시가 §D와 중복)

### §1.5 메모리는 advisory — 현재 코드·공식문서 우선 (MANDATORY)

> 근거: Dual-Brain (sleeplesshan, github.com/sleeplesshan/dual-brain) — *"memory는 advisory context이고, 현재 코드와 공식 문서가 stale memory보다 우선한다."* Claude Code 기본 메모리 가이드와도 일치.

- 검색으로 불러온 메모리는 **참고용(advisory)** 이며 ground truth가 아니다.
- 메모리가 파일·함수·플래그·경로·수치·API를 지목하면 **현재 코드/공식 문서로 재확인한 뒤** 사용 (특히 경로·API·config — 추천·실행 전 존재 여부 검증).
- 현재 코드/문서와 메모리가 충돌하면 **현재 실제(코드·docs)가 우선** → 해당 메모리는 stale로 보고 `update_memory`로 갱신하거나 `번복됨` 표시 (`rules-lazy/mem0-conventions.md` §C).
- 오래되거나 모순된 결정은 long-term archive 또는 만료 처리 (`rules-lazy/memory-promotion.md`).

---

## §2 자동 트리거 마스터 테이블

> 호출 템플릿 본문은 `~/.claude/rules-lazy/mem0-templates.md` 참조 — T번호로 인덱싱

### MANDATORY (T01~T12) — 반드시 실행

| # | 이벤트 | 작업 | category | source | 비고 |
|---|--------|------|----------|--------|------|
| T01 | 사용자 합의 감지 ("~로 결정", "알겠어", "그렇게 하자") | add | decision | memory-write | 즉시 저장 |
| T02 | compact 직전 (MANDATORY — 스킵 금지) | add | context | compact_handover | 진행률+활성 결정+config 포함 |
| T03 | 세션 시작/continuation | search ×3 + pattern-detect + usage-check | context → decision → code_pattern (3축) | — | 3축 복원 + **반복 패턴 감지**(SessionStart 훅이 `pattern-detect.sh 3` 결과를 자동 주입 — 2026-07-16 하드 훅화. 모델은 주입된 후보의 **판정만**: T40 검색 대조 → 3회+ 시 스킬화/편입/룰화 제안, 이미 스킬로 커버되면 불요 판정) + **인프라 사용 점검**(SessionStart 훅이 `harness-usage-check.sh` 출력을 자동 주입 — 모델은 주입된 이상 항목의 조치만: 감사 초과→/harness-audit 제안, 타이머 미활성→3택 게이트(`code-graph.md` §8 — 주력 1서버만 활성), push 백로그·마이닝 정지·bench 대기→해당 제안. "USAGE OK"면 조치 불요, 직접 실행 금지 항목은 제안만. 미배선 서버 폴백·배선법: `config/hooks/README.md`). **스킵 조건**: 단순 질문·단발 대화(작업성 요청 없음)면 생략 — 첫 작업성 요청 시점에 수행 |
| T04 | QA 검증 FAIL 발생 | add | code_pattern | qa-process | 실패 원인·수정 내용 + **avoidance_rubric** 형식 (RubricEM 차용) — 다음 작업 시 search로 자동 로드되어 회피 가이드로 활용. 상세: `rules-lazy/mem0-templates.md` T04 |
| T06 | /discuss 토론 완료 | add | discuss | discuss | 핵심 합의·근거 요약 저장 |
| T07 | /discuss 시작 전 | search ×3 | (discuss+decision 병합쿼리) → (experiment+paper 병합쿼리) → feedback 단독 | — | 3회로 축소 (3팀 Round 2 합의) |
| T08 | /paper-read 리뷰 완료 | add | paper | paper-read | 논문 요약·수식·관련성 저장 |
| T09 | /paper-read 시작 전 | search | paper | — | 기존 논문 이력 확인 |
| T10 | experiment Phase 완료 | add | experiment | experiment | 결과 수치 정확값 포함 |
| T38 | 음성 결과 확정 시 (fix-then-retest 후에도 음성) / 인프라 실패 확정 시 | add | experiment or code_pattern | failure-analysis | T10 직후 실행 — 무엇을→어떻게→결과→왜실패 + fix-then-retest 여부 + 인프라 교훈 |
| T39 | 양성 결과 확정 시 (gate 기준 충족) | add | experiment | success-analysis | T10 직후 실행 — 무엇을→어떻게→결과→왜성공 + 재현 레시피 + 검증 자산 |
| T11 | experiment Stage A 전 | search ×4 | experiment → paper → decision → discuss 순차 | — | 4회 순차 호출 |
| T12 | 사용자 교정 감지 ("이렇게 하지 마", "앞으로는") | add + search | feedback | learner | 저장 후 검색 → **3회+** 발견 시 `/learn-from-feedback` 자동 트리거 (룰 후보 제안) |

### citation-verifier MANDATORY 트리거 조건

아래 상황에서는 반드시 citation-verifier 디베이트를 소집한다:

| 상황 | 이유 |
|------|------|
| 논문을 본문·실험 자료에서 인용하기 직전 | 철회 게이트(Crossref+OpenAlex) + stance 디베이트로 사전 확인 |
| SOTA 수치·베이스라인으로 참조 시 | 철회 게이트(Crossref+OpenAlex) + stance 디베이트로 학계 합의 수준 검증 |
| 도메인 메커니즘 근거로 인용 시 | 철회 게이트(Crossref+OpenAlex) + stance 디베이트로 철회된 근거 논문 방지 |
| 2020년 이전 논문 인용 시 | 철회 게이트(Crossref+OpenAlex) + stance 디베이트로 최근 재현 실패 또는 후속 반박 확인 |

### citation-verifier 호출 흐름

```
논문 인용/참조 의도 감지
  → citation-verifier 디베이트 소집 (철회 게이트 → 옹호+회의 병렬 → 종합)
  → 결과 수신:
      supporting ≥ 3 + contrasting ≤ 1 + 철회 없음 → 인용 허용
      contrasting ≥ supporting → 사용자 경고 후 인용 여부 질문
      철회·정정·EoC 존재 → 인용 금지 + 대체 논문 검색
  → T21에 검증 결과 저장 (source: citation-verifier)
```

### OPTIONAL (T05, T13~T41) — 해당 시 실행 (lazy)

> **상세 표**: `~/.claude/rules-lazy/mem0-templates.md` § OPTIONAL 트리거 마스터 테이블 참조
> 호출 템플릿 본문도 동 파일에 함께 위치하므로 트리거 시 한 번에 lookup 가능.

---

## §3 호출 템플릿 위치

| 영역 | 위치 |
|------|------|
| T01~T41 호출 템플릿 본문 | `~/.claude/rules-lazy/mem0-templates.md` |
| 카테고리별 필드 카탈로그 (decision/experiment/code_pattern/paper/feedback/discuss) | `~/.claude/rules-lazy/mem0-fields.md` §3.0 |
| 필드 조합 템플릿 예시 (모든 필수 필드 포함 실예시) | `~/.claude/rules-lazy/mem0-fields.md` §3.0.1 |

> 트리거 발화 시 위 lazy 파일을 Read 후 해당 T번호 / 카테고리 섹션 참조.

---

## §4 infer 전략

- **기본**: `infer=True` (명시하지 않아도 기본 적용)
- **수치 정밀도 필요 시**: `infer=True` 유지하되 text에 정확값 원문 포함

```
# 수치 포함 예시 — infer=True가 손실하더라도 text에 보존됨
text="2026-04-13 Phase 2 결과: acc=87.3%, loss=0.234, lr=3e-4, batch=128, seed=42"
```

---

## §5 Fallback

이 파일은 fallback 로직을 정의하지 않는다.
MCP 미연결 또는 오류 시: `~/.claude/rules-lazy/mcp-fallback-mem0.md` 적용.
