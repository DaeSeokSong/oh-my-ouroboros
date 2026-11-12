# Mem0 호출 템플릿 (T01~T41)

> **로드 시점**: 자동 — `rules/mem0-auto.md` §2 트리거 발화 시 해당 T번호 템플릿 참조
> **연관 파일**: `rules/mem0-auto.md` (마스터 테이블), `rules-lazy/mem0-fields.md` (카테고리별 필드 카탈로그)
> **핵심 원칙**: 모든 템플릿은 mem0-auto.md §1 metadata 컨벤션(text 서두에 날짜 + [프로젝트명] 강제) 준수
> **저장 금지 내용 (D5, 2026-10-01)**: Mem0 는 외부 SaaS 라 어떤 템플릿의 `text` 에도 자격증명·환자 식별자·DICOM UID 를 넣지 않는다. 사용자 원문을 인용해야 하는데 그 안에 들어 있으면 가린 뒤 넣는다(출구별 금지 표: `rules-lazy/untrusted-quarantine.md` §7).

---

## §3 호출 템플릿 (T01~T41)

OPTIONAL 트리거(T05·T13~T37)는 MANDATORY와 동일한 호출 패턴을 사용한다. T05·T13~T37 의 마스터 표와 템플릿은 이 파일(아래 § OPTIONAL 트리거 마스터 테이블)이 정본이며 `rules/mem0-auto.md` 에는 없다.
> 카테고리별 필수 필드는 `rules-lazy/mem0-fields.md` §3.0 참조. 누락 금지.

---

**T01 — 사용자 합의 저장**
```
add_memory(
  text="[YYYY-MM-DD] [프로젝트명] 합의: [결정 내용]. 근거: [사유 1~2줄]",
  metadata={"category": "decision", "source": "memory-write"}
)
```

**T02 — compact 전 세션 상태 백업 (MANDATORY — 스킵 금지)**

compact 실행 직전 반드시 현재 세션 상태를 Mem0에 저장한다. handover.md와 이중 안전망 구성.

```
# 1. 기존 세션 상태 검색 → 중복 시 update_memory ([프로젝트] prefix 필수 — mem0-conventions §B 크로스 오염 방지)
search_memories(query="[프로젝트] 세션 상태 현재 작업 진행률", filters={"metadata": {"category": "context"}}, limit=3)

# 2. 유사 항목 있으면 update, 없으면 add
add_memory(
  text="세션 상태 [YYYY-MM-DD] [프로젝트]: 현재 작업=[작업명], 진행률=[N%], 활성 결정=[핵심 결정 요약], 사용 중 config=[주요 config 키=값], 미완료 TODO=[항목], 다음 시작점=[설명]",
  metadata={"category": "context", "source": "compact_handover"}
)
```

> 저장 내용 필수 포함: 진행률, 활성 결정, 사용 중 config 값, 미완료 TODO, 다음 시작점

**T03 — 세션 시작 시 Smart Retrieval 3축 복원 (MANDATORY)**

새 세션 또는 continuation 시작 시 3축 검색으로 이전 맥락을 복원한다.

**훅 주입분 판정·조치 매핑 (2026-07-28 mem0-auto §2 T03 셀에서 이관 — 내용 동일)**
- **반복 패턴 감지**: SessionStart 훅이 `pattern-detect.sh 3` 결과를 자동 주입(2026-07-16 하드 훅화). 모델은 주입 후보의 **판정만** — T40 검색 대조 → 3회+ 시 스킬화/편입/룰화 제안, 이미 스킬로 커버되면 불요 판정.
- **인프라 사용 점검**: 훅이 `harness-usage-check.sh` 출력을 자동 주입. 이상 항목별 조치 — 감사 초과→/harness-audit 제안 / 타이머 미활성→3택 게이트(`rules-lazy/code-graph.md` §8, 주력 1서버만 활성) / push 백로그·마이닝 정지·bench 대기→해당 제안. "USAGE OK"면 조치 불요, 직접 실행 금지 항목은 제안만. 미배선 서버 폴백·배선법: `config/hooks/README.md`.
- **스킵** (정본은 `rules/mem0-auto.md` T03 셀, 여기는 상세): 단순 질문·단발 대화면 첫 작업성 요청 시점으로 연기(작업성 요청의 정의 정본은 CLAUDE.md 원칙 3.5: 도구 호출·파일 변경·실험·커밋·외부 전송이 함의된 요청. 사실 질문·의견만은 비작업성)

```
# 1. History — 이전 세션 상태 + 과거 결정
search_memories(query="[프로젝트] 세션 상태 이전 작업 진행률 TODO", filters={"metadata": {"category": "context"}}, limit=3)

# 2. Current — 활성 결정 + 현재 config
search_memories(query="[프로젝트] 활성 결정 합의 config 설정 아키텍처", filters={"metadata": {"category": "decision"}}, limit=5)

# 3. Future — 과거 QA 실패 · 코드 관례 (T03 의 셋째 범주는 code_pattern, 정본 rules/mem0-auto.md T03)
search_memories(query="[프로젝트] QA 실패 코드 관례 패턴", filters={"metadata": {"category": "code_pattern"}}, limit=3)
```

> handover.md와 Mem0 결과 교차 확인. 충돌 시 현재 파일·사용자 확인 우선(Mem0 는 advisory, 정본 `rules/mem0-auto.md` §1.5).

**T04 — QA FAIL 이력 저장 (avoidance_rubric 형식 — RubricEM 차용)**

> **목적**: 단순 저장이 아니라 *재사용 가능한 회피 가이드*로 distillation. 다음 작업 시 search로 자동 로드되어 coder spawn prompt에 주입.
> **근거**: RubricEM (Li et al. 2026, arxiv 2605.10899) — reflection meta-policy의 trajectory distillation 메타 아이디어 차용.

```
add_memory(
  text="[YYYY-MM-DD] [프로젝트명] QA FAIL distillation: [파일]:[함수] — failure_type=[버킷], pattern=[패턴 이름], trigger_signature=[발현 조건], avoidance_rubric=[1) check_X, 2) check_Y, 3) check_Z], fixed=[수정 내용]",
  metadata={
    "category": "code_pattern",
    "source": "qa-process",
    "failure_type": "[버킷: logic|shape|type|import|config|race|num-precision|기타]",
    "pattern": "[패턴 이름]",
    "trigger_signature": "[발현 조건]",
    "avoidance_rubric": "[1) ..., 2) ..., 3) ...]"
  }
)
```

#### 필드 정의

| 필드 | 의미 | 예시 |
|------|------|------|
| `failure_type` | 실패 **버킷**(군집 키) — 반복 실패 유형 집계·빈도 분석용 | `logic`, `shape`, `type`, `import`, `config`, `race`, `num-precision` |
| `pattern` | 짧은 식별자 (kebab-case) | `tensor-shape-mismatch`, `zero-division-loss` |
| `trigger_signature` (T04 필수) | 어떤 코드 시그니처에서 재발 가능한지 | `unsqueeze + matmul`, `softmax + divide` |
| `avoidance_rubric` (T04 필수) | 다음에 회피하기 위한 사전 체크 항목 (3-5개) | `1) shape 사전 print, 2) broadcast 규칙 확인, 3) 차원 명시화` |

> **필수 필드**: `avoidance_rubric` 과 `trigger_signature` 는 T04 의 필수 필드다. 둘 중 하나라도 없으면 T04 가 아니라 일반 code_pattern 으로 저장한다.

> **루브릭형 유지 (2026-08-18 검증)**: fixed 필드는 "무엇을 왜 고쳤나"가 정본 — 완전 수정본 전문 동봉은 **유일해 태스크**(재현 버그 수정 등 정답이 하나인 경우)에 한정한다. 근거: 개방형 태스크에서 루브릭 피드백이 정답 제공보다 우월(FinEvo-Bench + CFT arXiv 2501.17703, citation-verifier 교차 검증 — 단 유일해 태스크는 역전 가능).

#### 자동 재로드 흐름

다음 코드 수정 작업 시:
```
# coder spawn 직전 main이 자동 검색
search_memories(
  query="[현재 작업 모듈] [현재 코드 시그니처] avoidance_rubric",
  filters={"metadata": {"category": "code_pattern"}},
  limit=3
)
# 결과의 avoidance_rubric 필드를 coder spawn prompt 서두에 주입:
# "[과거 회피 rubric] 본 작업에서 아래 항목 사전 체크하세요: {avoidance_rubric}"
```

#### 버킷 집계 (failure-bucketing — learn-from-feedback 연계)

같은 `failure_type`이 **3회+ 누적** 시 → 빈도 높은 버킷부터 룰 후보화(`/learn-from-feedback`). 개별 실패가 아닌 **유형 단위**로 회귀를 잡는다 (awesome-evals §9 Cline/Replit failure-bucketing hill-climbing 사례).

#### 단순 저장 (구버전) 호환

avoidance_rubric을 도출하기 어려운 단순 실패 (오타·import 누락 등)는 기존 형식 유지 가능:
```
add_memory(
  text="QA 실패 [YYYY-MM-DD]: [파일]:[함수] — 원인: [원인], 수정: [내용]",
  metadata={"category": "code_pattern", "source": "qa-process"}
)
```

**T05 — QA 이슈 재발 의심 시 과거 이슈 검색 (OPTIONAL)**
사용 시점: QA 단계에서 이전 이슈 재발 의심 시, 또는 사용자가 명시적으로 "과거 이슈 확인해"라고 요청할 때.
매 코드 수정 전 자동 실행하지 않는다 — 컨텍스트 재충전 속도를 줄이기 위함.
```
search_memories(query="[모듈명] QA", filters={"metadata": {"category": "code_pattern"}}, limit=5)
```

**T06 — discuss 완료 후 저장**
```
add_memory(
  text="discuss [YYYY-MM-DD] [주제]: 핵심 합의=[합의 내용]. 근거=[근거]. 반대 의견=[있으면]",
  metadata={"category": "discuss", "source": "discuss"}
)
```

**T07 — discuss 시작 전 다중 검색 (3회 순차 — 3팀 Round 2 합의)**

> 기존 5채널 순차 → 2채널 병합 + 단독 = 3회로 축소. Mem0 filter OR 미지원으로 카테고리 병합은 쿼리 키워드 확장으로 대체.

```
# 1회차: discuss + decision 병합 (discuss 이력 + 관련 합의 결정 동시 포함 쿼리)
#   ⚠️ filter는 discuss 카테고리만 정확 매칭 — decision 카테고리 항목은 키워드("결정 decision") best-effort 회수(filter OR 미지원의 의도적 트레이드오프, `mem0-conventions.md` §D 작업 유형별 검색 프로파일 참조). 결정 이력이 핵심이면 T01 decision 단독 검색 병행.
search_memories(query="[프로젝트][주제] 토론 합의 결정 이전 discuss decision", filters={"metadata": {"category": "discuss"}}, limit=5)

# 2회차: experiment + paper 병합 (실험 결과 + 논문 근거 동시 포함 쿼리)
#   ⚠️ filter는 experiment만 정확 매칭 — paper 카테고리는 키워드 best-effort. 논문 근거가 핵심이면 T09 paper 단독 병행.
search_memories(query="[프로젝트][주제] 실험 결과 논문 베이스라인 수식 experiment paper", filters={"metadata": {"category": "experiment"}}, limit=5)

# 3회차: feedback 단독 유지
search_memories(query="[주제]", filters={"metadata": {"category": "feedback"}}, limit=3)
```

#### T07 부분 실패 허용 (3팀 Round 2 합의)

3회 순차 호출 중 일부 실패 시:
- 실패 채널은 skip, 성공 채널 결과만 병합하여 사용
- 결과 서두에 `[partial: 2/3 채널 — feedback 실패]` 형식으로 누락 채널 명시
- `/discuss` 진행 조건: 최소 1채널 성공 시 진행, 전체 실패 시만 중단
- 실패 채널은 `mcp-fallback-mem0.md` Grep fallback으로 보강 시도

**T08 — 논문 리뷰 완료 후 저장**
```
add_memory(
  text="논문 [YYYY-MM-DD]: [제목] ([arXiv ID]). 핵심: [2~3줄 요약]. 관련 수식: [있으면]. 활용 가능성: [평가]",
  metadata={"category": "paper", "source": "paper-read"}
)
```

**T09 — paper-read 시작 전 기존 논문 확인**
```
search_memories(query="[논문 주제 키워드]", filters={"metadata": {"category": "paper"}}, limit=5)
```

**T10 — experiment Phase 완료 후 저장**
```
add_memory(
  text="실험 결과 [YYYY-MM-DD] [프로젝트] Phase [N]: acc=[정확값]%, loss=[정확값], lr=[정확값], batch=[정확값]. 특이사항: [있으면]",
  metadata={"category": "experiment", "source": "experiment"}
)
```

**T11 — experiment Stage A 전 다중 검색 (4회 순차)**
```
search_memories(query="[실험 주제]", filters={"metadata": {"category": "experiment"}}, limit=5)
search_memories(query="[실험 주제]", filters={"metadata": {"category": "paper"}}, limit=5)
search_memories(query="[실험 주제]", filters={"metadata": {"category": "decision"}}, limit=5)
search_memories(query="[실험 주제]", filters={"metadata": {"category": "discuss"}}, limit=3)
```

**T12 — 사용자 교정 저장 및 반복 여부 확인**
```
# ruleset_sha 취득: git -C ~/.claude rev-parse --short HEAD (실패 시 'nogit')
add_memory(
  text="[event:{event_id}] 사용자 교정 [YYYY-MM-DD] [프로젝트]: [교정 내용]. task_input=[현재 작업 요약 1줄]. ruleset_snapshot=<git short-sha>",
  metadata={"category": "feedback", "source": "learner", "ruleset_sha": "<git short-sha>"}
)
search_memories(query="[교정 내용]", filters={"metadata": {"category": "feedback"}}, limit=5)
# 결과 3회+ → learner.md 규칙 업데이트 제안 트리거 (문턱 정본: rules/mem0-auto.md §2 T12)
# 3회 판정의 입력은 로컬 빈도(pattern-detect.sh)와 Mem0 검색 이력 둘이고 같은 event_id 는 1건으로 합친다 (skills/learn-from-feedback/SKILL.md § 실행 순서 1·3)
# 선례: T04의 multi-field metadata(pattern/trigger_signature/avoidance_rubric) 구조 차용 — preference-gated 자가진화의 regression suite 전방계측용
```

- 교정 발화는 `~/.claude/scripts/correction-detect.sh` 가 T12 후보로 기계 기록한다(2026-11-10 `rules/mem0-auto.md` §2 비고에서 이관).

**T13 — 리팩토링 패턴 적용 완료**
```
add_memory(
  text="리팩토링 패턴 [YYYY-MM-DD] [프로젝트]: [모듈]. 패턴: [네이밍/구조/함수 시그니처]. 적용 이유: [근거]",
  metadata={"category": "code_pattern", "source": "coding-conventions"}
)
```

**T14 — 프로젝트 경로 확정**
```
add_memory(
  text="프로젝트 경로 [YYYY-MM-DD] [프로젝트]: 임시 폴더=[경로], 목표 폴더=[경로]",
  metadata={"category": "code_pattern", "source": "code-execution"}
)
```

**T15 — Figure 스타일 확정**
```
add_memory(
  text="Figure 스타일 [YYYY-MM-DD] [프로젝트]: 도구=[TikZ/matplotlib], 색상 팔레트=[지정], 폰트=[지정], 크기=[지정]",
  metadata={"category": "code_pattern", "source": "figure"}
)
```

**T16 — neuro-explain 완성**
```
add_memory(
  text="neuro-explain [YYYY-MM-DD] [프로젝트]: 메커니즘=[도파민/세로토닌/...]. 쉬운 설명=[1줄]. 예시=[1줄]. 비유=[1줄]",
  metadata={"category": "code_pattern", "source": "neuro-explain"}
)
```

**T17 — background task 실패**
```
add_memory(
  text="Background task 실패 [YYYY-MM-DD] [프로젝트]: 명령=[명령], 원인=[경로/import/인자/로직/메모리/권한], 해결=[수정 내용]",
  metadata={"category": "code_pattern", "source": "background-task"}
)
```

**T18 — 수식-코드-논문 불일치 해결**
```
add_memory(
  text="불일치 해결 [YYYY-MM-DD] [프로젝트]: [모듈]. 수식 vs 코드 vs 논문 충돌점=[설명]. 해결=[어느 것을 정답으로 채택]",
  metadata={"category": "code_pattern", "source": "cross-watch"}
)
```

**T19 — 워크플로우 패턴 완료**
```
add_memory(
  text="워크플로우 [YYYY-MM-DD] [프로젝트]: Phase 구분=[N개], 팀 구성=[에이전트 목록], 분기 조건=[Go/NoGo 기준]",
  metadata={"category": "code_pattern", "source": "workflow"}
)
```

**T20 — 프롬프트 구체화 완료**
```
add_memory(
  text="프롬프트 구체화 [YYYY-MM-DD]: 원래 요청=[원문]. 구체화 결과=[해석]. 사용자 승인 여부=[Y/N]",
  metadata={"category": "feedback", "source": "prompt-routing"}
)
```

- 다음 유사 요청 시 검색으로 재질문 없이 즉시 해석을 제안한다: "이전에 '{구체화 결과}'로 해석했습니다. 동일하게 진행할까요?" (2026-11-10 `rules/prompt-routing.md` Step 1.5 에서 이관)

**T21 — citation-verifier 검증 완료 후 저장**
```
add_memory(
  text="citation-verifier 검증 YYYY-MM-DD [프로젝트명] invoker=[에이전트]: 제목='[논문제목]' (저자=[Author], 연도=[Year], DOI=[DOI]). 목적=[본문 인용/SOTA 베이스라인/철회 확인/paper-read 후속/토론 근거]. verdict=[허용/경고/금지]. supporting=[N], contrasting=[M], mentioning=[K]. retracted=[true/false]. confidence=[high/med/low]. fulltext_coverage=[high/partial/abstract-only]. actual_use=PENDING. location=(미정). status=pending_review. updated_at=YYYY-MM-DD. 요약=[한 줄 판단 근거]",
  metadata={"category": "paper", "source": "citation-verifier"}
)
```
> 상세 로그는 `rules-lazy/citation-verification-log.md` 규칙대로 `docs/citation-verifications.md` 에 append.
> 대조 모드만 돌았으면 supporting·contrasting 자리에 `대조=[일치 수]/[항목 수]` 를 쓴다(2026-11-10, 디베이트는 논쟁적 인용만).

**T22 — searcher 검색 완료 후 핵심 결과 저장**
```
add_memory(
  text="검색 결과 [YYYY-MM-DD] [주제]: 핵심 발견=[요약 2~3줄]. 출처=[URL/DOI]. 정확도=[높음/중간/낮음]",
  metadata={"category": "decision", "source": "searcher"}
)
```

**T23 — 에이전트 간 설계 합의 저장**
```
add_memory(
  text="에이전트 합의 [YYYY-MM-DD] [주제]: 합의=[합의 내용]. 참여=[에이전트 목록]. 근거=[핵심 근거]",
  metadata={"category": "decision", "source": "agent-consensus"}
)
```

**T24 — 사용자 환경/도구 선호 저장** (§C-2 provenance 적용 — 근거 원문 인용 필수, 추론분은 `(추정)`)
```
add_memory(
  text="환경 선호 {YYYY-MM-DD}: [도구/환경 선택 내용]. 이유: [사유]. 근거: 사용자 원문 \"[발화 인용 1구절]\" (추론으로 보탠 부분은 (추정) 태그, 근거 없는 필드는 미기록)",
  metadata={"category": "feedback", "source": "env-preference"}
)
```

> **공통 필드**: T21과 동일한 5W1H + 사용 추적 필드 사용 (citation-verifier 반환 구조 기준)

**T25~T28 — citation-verifier 검증 저장 (공통 템플릿 — 4 변형은 아래 표)**
```
# 1. citation-verifier subagent 소집: doi="{DOI 또는 논문 제목}"
#    → verdict(허용/경고/금지)·retracted·supporting/contrasting/mentioning·confidence 수신
# 2. 결과를 T21로 저장:
add_memory(
  text="citation-verifier {맥락} {YYYY-MM-DD} [프로젝트명]: [논문 제목] (DOI:[DOI]). {변형 필드}. supporting=[N], contrasting=[M]. retracted=[true/false]. verdict=[허용/경고/금지]. confidence=[high/med/low]",
  metadata={"category": "paper", "source": "citation-verifier"}
)
```
> 상세 로그는 `rules-lazy/citation-verification-log.md` 규칙대로 `docs/citation-verifications.md` 에 append.

| T | 트리거·맥락 | 변형 필드 (text에 추가) |
|---|---|---|
| T25 | 논문 인용 직전 사전 검증 | 인용 의도: [본문/실험/발표] |
| T26 | /paper-read(T08 저장) 직후 stance 검증 | mentioning=[K], fulltext_coverage=[high/partial/abstract-only] |
| T27 | /experiment Stage A — SOTA·베이스라인 채택 직전 | 용도: SOTA/베이스라인 |
| T28 | retraction/corrigendum/erratum 키워드 감지 → 철회게이트(Crossref+OpenAlex, Retraction Watch 내장) 최우선 | 의심 트리거, editorial_notices=[상세/없음], 처리: [인용 금지/대체 논문 탐색] |

**T29 — Confluence 페이지 작업 완료 저장**
```
add_memory(
  text="Confluence [YYYY-MM-DD] [프로젝트명]: 페이지 [제목] [생성/수정]. URL: [URL]. Space: [space key]. 주요 변경: [1~2줄]",
  metadata={"category": "context", "source": "confluence-update"}
)
```

**T30 — Jira 이슈 작업 완료 저장**
```
add_memory(
  text="Jira [YYYY-MM-DD] [프로젝트명]: 이슈 [KEY-NNN] [작업 유형: 코멘트/상태변경/생성]. 제목: [제목]. 상태: [before → after]. 내용: [요약]",
  metadata={"category": "context", "source": "jira-update"}
)
```

**T31 — Figure 생성 완료 저장**
```
add_memory(
  text="Figure [YYYY-MM-DD] [프로젝트명]: [파일명] 생성. 유형: [TikZ/matplotlib]. 용도: [논문/슬라이드/Confluence]. 크기: [WxH]. 스크립트 경로: [경로]. 사용 데이터: [출처]",
  metadata={"category": "code_pattern", "source": "figure-gen"}
)
```

**T32 — git commit 완료 저장**
```
add_memory(
  text="Commit [YYYY-MM-DD] [프로젝트명]: [commit hash] [type: subject]. 변경 파일: [N개]. 분할 기준: [기능별/레이어별]. Jira: [KEY 또는 없음]",
  metadata={"category": "context", "source": "git-commit"}
)
```

**T33 — Ralph Wiggum 루프 완료 저장**
```
add_memory(
  text="QA Ralph Wiggum [YYYY-MM-DD] [프로젝트명]: [파일:함수]. 반복 N=[횟수]. 최종 결과: [PASS/위임]. 수정 이력: [각 라운드 요약]",
  metadata={"category": "code_pattern", "source": "qa-ralph"}
)
```

**T34~T36 — 논문 사용 상태 update (공통 템플릿 — 3 변형은 아래 표)**
```
# 1. 기존 citation-verifier 검증 항목 ID 조회
results = search_memories(query="[논문 제목 또는 DOI]", filters={"metadata": {"category": "paper"}}, limit=3)

# 2. 해당 memory_id에 update — 원래 검증 필드(날짜·제목·목적·verdict·수치·retracted·confidence)는 그대로 두고 아래 3필드+updated_at+요약만 변형
update_memory(
  memory_id="[기존 ID]",
  text="citation-verifier 검증 결과 [원래 날짜] [프로젝트명] invoker=[에이전트]: (…원래 검증 필드 유지…). actual_use={표}. location={표}. status={표}. updated_at=[오늘 YYYY-MM-DD]. 요약=[한 줄]"
)
```

| T | 시점 | actual_use | location | status | 요약 내용 |
|---|---|---|---|---|---|
| T34 | 코드에 실제 구현됨 | YES | 파일:라인 | implemented | 구현 요약 |
| T35 | 논문·발표에 인용됨 | YES | docs/paper/sec3.tex·pptx 등 | cited | 인용 컨텍스트 |
| T36 | 사용 기각·보류 결정 | NO | (미사용) | rejected 또는 on_hold | 기각·보류 사유 |

**T37 — 기간별 메모리 조회 (주간 회고 등 — 3팀 Round 2 합의)**

> 트리거 키워드: "주간 회고", "스프린트 정리", "기간 집계", "최근 N일 실험 결과"
> `get_memories` 기본은 `limit=10`(`rules/mem0-auto.md` §1.3)이다. 아래 `limit=50` 은 사용자가 기간 집계를 명시 요청한 경우의 예외 값이다.

```
get_memories(
  filters={"AND": [
    {"created_at": {"gte": "YYYY-MM-DD"}},
    {"metadata": {"category": "experiment"}}
  ]},
  limit=50
)
```

결정 사항도 함께 조회 시:
```
get_memories(
  filters={"AND": [
    {"created_at": {"gte": "YYYY-MM-DD"}},
    {"metadata": {"category": "decision"}}
  ]},
  limit=50
)
```

**T38 — 실험/디버깅 음성 결과 분석 저장**

> **트리거**: experiment Phase 음성 확정 시 (fix-then-retest 후에도 음성) / 인프라 실패 확정 시
> **T10과 함께 실행** — T10이 raw 수치 저장, T38은 메커니즘 분석·교훈 저장

```
# 실험 음성 결과 (fix-then-retest 후에도 음성)
add_memory(
  text="[YYYY-MM-DD] [프로젝트명] [FAILURE] [실험명]: 무엇을=[목표], 어떻게=[config·시드·방법], 결과=[정확값 + baseline 대비 Δ], 왜실패=[메커니즘 해석]. fix-then-retest=[구현결함 의심 여부 / 보정 시도 내용 / 보정 후 결과(robust 음성 or confound 해소)]. 회피 포인트=[다음 실험에서 같은 실패 방지할 핵심 조건]",
  metadata={"category": "experiment", "source": "failure-analysis", "result_type": "negative"}
)

# 인프라/구현 실패 (GPU 충돌·경로·race condition 등)
add_memory(
  text="[YYYY-MM-DD] [프로젝트명] [INFRA-FAILURE] [실패 패턴명]: 무엇을=[상황], 어떻게=[발생 조건], 결과=[실패 양상], 왜=[근본 원인]. 해결=[fix 내용]. 재발방지=[구체 조건·설정]",
  metadata={"category": "code_pattern", "source": "failure-analysis", "result_type": "infra"}
)
```

> fix-then-retest 원칙: 음성 결과는 구현/하이퍼 결함 confound 가능성을 1회 보정 테스트로 확인 후 결론. 보정해도 음성 → robust 음성. 보정 후 양성 → 원래 confound였음.

**T39 — 실험/작업 양성 결과 분석 저장**

> **트리거**: experiment Phase 양성 확정 시 (gate 기준 충족) / 주요 작업 성공 완료 시
> **T10과 함께 실행** — T10이 raw 수치 저장, T39는 성공 메커니즘·재현 레시피 저장

```
add_memory(
  text="[YYYY-MM-DD] [프로젝트명] [SUCCESS] [실험명]: 무엇을=[목표], 어떻게=[config·시드·방법], 결과=[정확값 + baseline 대비 Δ + gate 기준 PASS 여부], 왜성공=[메커니즘 해석]. 재현 레시피=[핵심 config·조건 — 다음 실험에서 반드시 유지해야 할 것]. 검증 자산=[이 결과를 기반으로 다음 실험에서 의존 가능한 베이스라인 여부]",
  metadata={"category": "experiment", "source": "success-analysis", "result_type": "positive"}
)
```

> 검증 자산 기록 원칙: 성공 결과가 다음 실험의 베이스라인·의존 조건이 되는지 명시. "검증 자산 O" → 후속 실험에서 이 config를 fixed로 사용 가능.

---

**T40 — 사용자 반복 행동 패턴 저장 (자가진화)**

> **목적**: 교정(T12)이 아닌 **중립적 반복 패턴**(주기적 요청·작업방식·발화)을 캡처해, 3회+ 누적 시 learn-from-feedback이 스킬화/편입/룰화를 제안하도록 전방계측.
> **T12와 구분**: T12=교정("이렇게 하지마"), T40=반복 습관("또 이걸 시킴" — 부정 아님).

```
add_memory(
  text="[YYYY-MM-DD] [claude-global] 반복 패턴: pattern_type=[repeat-request|workflow|phrasing], 내용=[요청/작업방식 요약], 맥락=[언제 반복되나]",
  metadata={"category": "feedback", "source": "pattern-detect", "pattern_type": "[repeat-request|workflow|phrasing]"}
)
```

- 저장 후 동일 pattern_type 검색 → **3회+** 발견 시 learn-from-feedback에 "스킬화/편입/룰화" 제안 트리거.
- 후보는 `~/.claude/scripts/pattern-detect.sh` 가 `_evolve/candidates.tsv` 에 기계 기록한다(2026-11-10 `rules/mem0-auto.md` §2 비고에서 이관).
- 산출물 선택: 단순 행동규칙 → 룰 / 재사용 절차·명령묶음 → 스킬 신설(quick-skill) / 기존 스킬 인접 → 편입 (`learner.md § 반복 패턴 → 산출물 3택`).

---

**T41 — 에이전트 약점 저장 (eval-driven 자가진화)**

> **목적**: 작업 실패/재작업 신호(`agent-eval.md` §1)를 에이전트별 약점으로 축적. 3회+ 시 `agents/{name}.md` 개선 제안.
> **T04와 구분**: T04=코드 QA FAIL(코드 패턴), T41=에이전트 행동 약점(역할 차원).

```
add_memory(
  text="[event:{event_id}] [YYYY-MM-DD] [claude-global] 에이전트 약점: agent=[coder|qa|searcher|...], dimension=[eval 차원], signal=[판정 신호], detail=[무엇이 부족], task=[작업 요약]",
  metadata={"category": "code_pattern", "source": "agent-eval", "agent_role": "[에이전트]", "weakness_dim": "[차원]"}
)
```

- 신호(agent-eval §1): **사용자 직접 재작업 지시·부정피드백**("다시 해"·"이거 아니야") / qa FAIL / 재작업≥2 / status BLOCKED / main 반려 / citation contrasting / 게이트 미달.
- 동일 `agent_role` + `weakness_dim` **3회+** → learn-from-feedback이 `agents/{agent}.md` 개선 제안.
- 파일 기록은 `bash ~/.claude/scripts/t41-append.sh <role> <dim> "<signal>"` 로 한다. 계수는 `grep -c 'T41:' _audit/history.md` 다(2026-11-10 `rules/mem0-auto.md` §2 비고에서 이관).

---

## OPTIONAL 트리거 마스터 테이블 (T05, T13~T37)

> **상위 파일**: `~/.claude/rules/mem0-auto.md` §2 — MANDATORY 표는 그곳에 유지
> **본 파일에는 호출 템플릿 본문 + OPTIONAL 트리거 표 통합**

| # | 이벤트 | 작업 | category | source |
|---|--------|------|----------|--------|
| T05 | QA 이슈 재발 의심 시 (정의는 본 파일 T05 하나뿐, 매 수정 전 자동 실행 아님) | search | code_pattern | — |
| T13 | 리팩토링 패턴 적용 완료 | add | code_pattern | coding-conventions |
| T14 | 프로젝트 경로 확정 | add | code_pattern | code-execution |
| T15 | Figure 스타일 확정 | add | code_pattern | figure |
| T16 | neuro-explain 완성 | add | code_pattern | neuro-explain |
| T17 | background task 실패 | add | code_pattern | background-task |
| T18 | 수식-코드-논문 불일치 해결 | add | code_pattern | cross-watch |
| T19 | 워크플로우 패턴 완료 | add | code_pattern | workflow |
| T20 | 프롬프트 구체화 완료 | add | feedback | prompt-routing |
| T21 | citation-verifier 검증 완료 (T25~T28 MANDATORY 실행 시 필수 저장) | add | paper | citation-verifier |
| T22 | searcher 검색 완료 (핵심 결과) | add | decision | searcher |
| T23 | 에이전트 간 설계 합의 도출 | add | decision | agent-consensus |
| T24 | 사용자 환경/도구 선호 감지 | add | feedback | env-preference |
| T25 | 논문 인용 직전 (본문·실험·발표 자료에서 언급) | citation-verifier[대조] 소집(논쟁적 인용만 디베이트) → verdict 수신 → T21 저장 | paper | citation-verifier |
| T26 | /paper-read 리뷰 완료 후 (T08과 연동) | citation-verifier[대조](논쟁적 인용만 stance 디베이트) → verdict 수신 → T21 저장 | paper | citation-verifier |
| T27 | SOTA/베이스라인 논문 선정 시 (/experiment Stage A) | citation-verifier 검증 → verdict 수신 → T21 저장 | paper | citation-verifier |
| T28 | 철회 논문 의심 패턴 감지 (retraction/corrigendum/erratum 키워드) | citation-verifier 철회게이트(Crossref+OpenAlex) 확인 → T21 저장 | paper | citation-verifier |
| T29 | main(게시 뒤, docs 는 메모리 연결 없음): Confluence 페이지 생성/수정 완료 | add | context | confluence-update |
| T30 | main: Jira 이슈 코멘트/상태 변경 완료 | add | context | jira-update |
| T31 | figure 스킬: Figure 생성 완료 | add | code_pattern | figure-gen |
| T32 | gitops: commit 완료 | add | context | git-commit |
| T33 | qa: Ralph Wiggum 루프 완료 (N회 반복) | add | code_pattern | qa-ralph |
| T34 | 논문이 코드에 실제 구현됨 (함수·클래스·config 추가) | update_memory | paper | citation-verifier |
| T35 | 논문이 논문·발표에 인용됨 (tex/pptx/md 포함) | update_memory | paper | citation-verifier |
| T36 | 논문 사용 기각·보류 결정 | update_memory | paper | citation-verifier |
| T37 | 주간 회고 / 스프린트 종료 / 기간별 집계 요청 | get_memories | experiment, decision | period-review |
> T38~T41 은 MANDATORY 이며 마스터 표는 `rules/mem0-auto.md` §2 하나뿐이다. 호출 템플릿 본문은 위 §3 에 있다.
