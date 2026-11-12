# Mem0 호출 컨벤션 상세 (call-time 참조)

> **로드 시점**: `rules/mem0-auto.md`의 트리거가 발화되어 실제 `add_memory`/`search_memories`를 호출하기 직전에만 lazy 로드.
> **모(母) 파일**: `~/.claude/rules/mem0-auto.md` (always-on — 트리거·카테고리·limit 가드)
> 이 파일은 "어떻게 저장/검색하는지"의 상세만 담는다. "언제 하는지"(트리거)는 mem0-auto.md에 있다.

**category 별 기본 저장 주체(`source`)** (2026-11-10 `rules/mem0-auto.md` §1.2 표에서 이관): `decision`=memory-write·discuss / `experiment`=experiment 스킬 / `code_pattern`=qa·coder / `paper`=paper-read 스킬 / `feedback`=learner·prompt-routing / `discuss`=discuss 스킬 / `context`=compact·docs·gitops.

**Smart Retrieval 3축 정의** (같은 날 §1.4 에서 이관): History=과거 이력·결정·실패/성공 패턴 / Current=현재 작업 직결 맥락·활성 결정 / Future=다음 단계·미완 TODO. 실행 패턴은 §D.

---

## §A 프로젝트명 식별 규칙

text 서두의 `[프로젝트명]`은 아래 기준으로 자동 결정한다:

| cwd 패턴 | 프로젝트명 |
|----------|-----------|
| `~/.claude/` 하위 (글로벌 설정 작업) | `claude-global` |
| `~/workspace/{name}/` 하위 | `{name}` (워크스페이스 폴더명) |
| 기타 | 최상위 git 저장소명 또는 cwd 마지막 폴더명 |

> 프로젝트명 누락 시 Mem0 크로스 오염 발생 — 다른 프로젝트 검색 결과가 현재 세션에 노출될 수 있다. text 서두에 반드시 명시한다.

### 설계 근거 (metadata에 project 필드를 두지 않는 이유)

Mem0는 metadata 필드가 증가할수록 검색 정확도가 저하되는 특성이 있다. 또한 metadata 스키마를 확장하면 기존 저장 항목과 호환성이 깨진다. 대신 text 서두에 `[프로젝트명]` 토큰을 강제함으로써:

1. Mem0 내부 임베딩 검색이 프로젝트명을 자연어 맥락으로 활용
2. §B 검색 시 쿼리 prefix로 `"{프로젝트명}"` 포함 → 프로젝트 매칭 자동 수행
3. metadata 스키마 변경 없이 기존 저장 항목과 호환 유지

---

## §B 프로젝트 매칭 검색 패턴 (필수)

다른 프로젝트의 메모리가 현재 세션에 섞이는 것을 방지하기 위해 모든 `search_memories` 호출에 프로젝트명을 쿼리 prefix로 포함한다:

```
# ✅ 올바른 패턴 — 프로젝트명을 쿼리 서두에 포함
search_memories(
  query="[프로젝트명] {검색 키워드}",
  filters={"metadata": {"category": "..."}},
  limit=5
)

# ❌ 금지 패턴 — 프로젝트명 누락 시 타 프로젝트 결과 혼입
search_memories(query="{검색 키워드}", filters={...})
```

크로스 프로젝트 검색이 의도된 경우(전역 feedback 검색 등)에만 프로젝트명을 생략한다. 이 경우에도 `source="learner"` 등 다른 필터로 범위를 좁힌다.

---

## §C 중복 방지 (update_memory 우선)

저장 전 동일 주제 기존 메모리를 검색하여 중복을 방지한다:

```
# 1. 기존 메모리 검색
results = search_memories(query="[저장할 내용 키워드]", filters={"metadata": {"category": "[동일]"}}, limit=3)

# 2. 유사 항목 발견 시 → update_memory
#    미발견 시 → add_memory
if 유사_항목_존재:
    update_memory(memory_id="[기존 ID]", text="[갱신 내용]")
else:
    add_memory(text="...", metadata={...})
```

> 동일 주제를 반복 add하면 검색 시 중복 노이즈 발생. update로 최신 상태 유지.

### update_memory MANDATORY 트리거 (구체 상황 — 3팀 Round 2 합의)

아래 상황은 **반드시** `update_memory` 사용 (`add_memory` 금지):

| 트리거 상황 | 이유 |
|-----------|------|
| 동일 experiment Phase 재실행 (config·dataset 동일, seed만 다름) | 중복 결과 누적 → 검색 시 최신값 불명확 |
| 동일 논문 재검토 (citation-verifier 재검증) | T21 레코드 1개 유지, verdict·supporting/contrasting·retracted만 갱신 |
| 사용자 결정 번복 (이전 decision 취소/수정) | 이전 레코드에 `번복됨` 표시 |
| 에이전트 합의 갱신 (discuss Round N+1에서 변경) | T06 갱신, 새 add 금지 |

절차: `search_memories` → 유사 항목 발견 → `update_memory` (절대 `add` 하지 않음)

---

## §C-2 쓰기 provenance — 사용자 속성·선호·피드백 (MANDATORY, 2026-08-18)

LLM은 개인화 맥락에서 증거 이상으로 사용자 속성을 지어낸다(12모델 전원 35~49%, Personalization Mirage arXiv 2608.04570 + 독립 지지 문헌 — citation-verifier 검증 2026-08-18). 쓰기 시점 방어 3규칙:

1. **근거 동봉**: user·feedback 계열 저장 text에 사용자 원문 인용 1구절(또는 발화 시점)을 포함한다 — "무엇에서 나온 결론인지"가 파일만으로 재현되게.
2. **추론 태그**: 사용자가 말하지 않은 것을 추론해 저장할 땐 `(추정)` 태그를 붙인다 — 추론이 맞을 수도 있으므로 버리지 말고 표시한다.
3. **양식 ≠ 증거**: 템플릿 필드를 채울 근거가 없으면 그 필드는 비우거나 "없음"으로 — task 양식이 요구한다는 사실은 증거가 아니다.

4. **저장 금지 내용 (D5, 2026-10-01)**: Mem0 는 외부 SaaS 라 `text` 에 자격증명·환자 식별자·DICOM UID 를 넣지 않는다. 1번의 사용자 원문 인용에 들어 있으면 그 부분을 가린 뒤 저장한다. 정확한 config·수치는 허용한다(출구별 표: `rules-lazy/untrusted-quarantine.md` §7).
5. **상세 문서 금지 (2026-11-09)**: searcher · scout 상세 문서의 발췌 · 경로 목록은 `text` 에 넣지 않는다. 검증된 결론만 저장한다(정본: `rules-lazy/memory-write.md` § 메모리 구조).

recall 시 `(추정)` 항목은 §1.5 advisory보다 한 단계 더 낮게 취급(사용자 확인 전 단정 금지).

## §C-3 advisory 원칙의 근거·실측 경위 (mem0-auto §1.5 상세)

- 근거: Dual-Brain (sleeplesshan, github.com/sleeplesshan/dual-brain) — *"memory는 advisory context이고, 현재 코드와 공식 문서가 stale memory보다 우선한다."* Claude Code 기본 메모리 가이드와도 일치.
- 이중 저장소(메모리+하네스 파일)에서 한쪽만 읽는 incomplete loading(불완전 로딩)이 축적 이득을 상쇄한다는 실측: FinEvo-Bench, 2026-08-18 검증. 히트가 룰·스킬·knowledge 파일을 지목하면 그 파일도 함께 로드해 대조하는 규칙의 출처.
- 특히 경로·API·config는 추천·실행 전 존재 여부 검증 — stale 경로 추천이 재작업의 주 원인.

## §D Smart Retrieval 상세 (3축 검색 — 관련성 필터 + 프로파일)

> 3축(History/Current/Future) 검색은 MANDATORY (mem0-auto.md §1.4). 아래는 검색 결과 필터링과 작업 유형별 채널 프로파일 상세.

### 검색 실행 패턴

```
# 1. History — 관련 이력
search_memories(query="[대상] 이전 결정 수정 이력 패턴", filters={"metadata": {"category": "[해당]"}}, limit=5)

# 2. Current — 현재 맥락
search_memories(query="[현재 작업] 활성 설정 진행 중", filters={"metadata": {"category": "[해당]"}}, limit=5)

# 3. Future — 다음 계획 (반드시 포함)
search_memories(query="[프로젝트] 다음 단계 TODO 계획 예정", filters={"metadata": {"category": "context"}}, limit=3)
```

> T03(세션 시작 복원)에 한해 셋째 채널은 code_pattern(과거 QA 실패 · 코드 관례)이다(정본: `rules/mem0-auto.md` T03 행, 호출: `rules-lazy/mem0-templates.md` T03).

### 관련성 평가 및 필터링

검색 결과에서 아래 기준으로 관련 없는 항목을 제외한다:

| 제외 조건 | 이유 |
|----------|------|
| 현재 작업 모듈/파일과 무관한 코드 패턴 | 다른 모듈 이력은 노이즈 |
| 6개월+ 이전 실험 결과 (현재 활성 Phase와 무관) | 오래된 수치는 혼란 유발 |
| 이미 long-term/ 파일에 승격 완료된 항목 | 중복 방지 — long-term 파일 직접 참조 |
| 완료/폐기된 TODO | 불필요한 컨텍스트 |

### 작업 유형별 검색 프로파일

| 작업 유형 | History 검색 | Current 검색 | Future 검색 |
|----------|------------|------------|------------|
| **코드 수정** | code_pattern (QA 이슈) | decision (활성 설계) | context (다음 Phase) |
| **실험 실행** | experiment (이전 결과) + paper (관련 논문) | decision (활성 config) | context (다음 실험) |
| **논문 작업** | paper (기존 리뷰) + discuss (관련 토론) | decision (논문 구조) | context (제출 계획) |
| **토론/discuss** | discuss + decision + experiment + paper + feedback (5채널 — T07 은 이를 병합 쿼리 3회로 실행: discuss+decision / experiment+paper / feedback) | decision (활성 결정) | context (후속 작업) |
| **세션 복원** | context (이전 세션 상태) | decision + experiment (최신) | context (미완료 TODO) |
