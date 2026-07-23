# 즉시 메모리 기록 규칙 (Immediate Memory Write)

> **로드 시점**: 항상 (모든 대화에 적용 — 자동 트리거)
> **핵심 원칙**: 합의된 결정은 그 즉시 `short-term/decisions.md`에 기록한다. compact 이후에도 복구할 수 없는 합의 소실은 용납되지 않는다.

## 메모리 구조 (short-term / long-term 분리)

| 경로 (short-term root = `~/.claude/projects/-home-user--claude/memory/`) | 용도 | 만료 |
|------|------|------|
| `short-term/decisions.md` | 합의 결정 이력 | 7일 |
| `short-term/progress.md` | Phase 진행 + TODO | 7일 |
| `short-term/handover.md` | 세션 인수인계 | compact 시 덮어쓰기 |
| `${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/architecture.md` | 아키텍처 결정 | 영구 |
| `${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/experiments.md` | 실험 결과 수치 | 영구 |
| `${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/datasets.md` | 데이터셋 확정 | 영구 |
| `${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/hyperparams.md` | 하이퍼파라미터 | 영구 |
| `${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/feedback.md` | 사용자 교정·도구·환경 결정 | 영구 |
| `${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/{project}/meetings/` | discuss 회의록 + _workspace | 영구 |

---

## 즉시 기록 트리거 (MANDATORY — 아래 상황 발생 시 다음 응답 전에 반드시 Write 실행)

| 트리거 상황 | 기록 대상 | 기록 위치 |
|------------|-----------|-----------|
| 사용자가 실험 설계/순서에 합의 | 실험 명칭, config, dataset, 실행 순서 | `short-term/progress.md` |
| 사용자가 데이터셋 추가/변경/제거 확정 | 변경 전후 dataset 목록 + 사유 | `short-term/decisions.md` → 승격 제안 |
| 사용자가 아키텍처/하이퍼파라미터 결정 | 파라미터 값, 결정 근거 | `short-term/decisions.md` → 승격 제안 |
| 사용자가 실험 전 사전 검증(precheck) 방식 합의 | 실험 명칭, config, 목적 | `short-term/progress.md` |
| 사용자가 향후 작업 계획 확정 | 작업명, 조건, 순서 | `short-term/progress.md §TODO` |
| 분기 조건(Go/NoGo) 합의 | 조건 수치, 판단 기준 | `short-term/decisions.md` |

### § Mem0 병렬 저장 (MANDATORY)

즉시 기록 트리거 발생 시, 파일 기록과 **동시에** Mem0에도 저장한다.
→ `~/.claude/rules/mem0-auto.md` T01 참조

실행 절차:
```
1. ToolSearch("select:mcp__mem0__add_memory,mcp__mem0__search_memories") — 세션당 1회
2. 중복 검색: search_memories(query="[결정 키워드]", filters={"metadata": {"category": "decision"}}, limit=3)
3. 유사 항목 존재 → update_memory(memory_id="[기존 ID]", text="[갱신 내용]")
   미존재 → add_memory(text="[날짜] [프로젝트] 합의: [내용]", metadata={"category": "decision", "source": "memory-write"})
4. Mem0 불가 시: mcp-fallback.md § Mem0 Fallback 적용 (파일 기록만으로 진행 — 스킵 금지)
```

- 파일 기록 실패 시에도 Mem0 저장은 독립 실행
- 7일 만료로 파일에서 삭제되어도 Mem0에서 `search_memories`로 복구 가능

## 기록 형식

```markdown
- **[날짜] [결정 요약]**: [구체 내용] — 근거: [사유 1~2줄]
```

예시:
```markdown
- **2026-03-02 precheck 합의**: Omniglot + Maze × Full+HC ON = 2개 실험 먼저 실행 → 수렴 확인 후 전체 242개 진행
- **2026-03-02 데이터셋 교체**: MNIST → Omniglot (964-way, part-whole hierarchy 검증에 더 적합)
```

## 기록 실패 방지 절차

1. **사용자 합의 감지**: "~하기로 했잖아", "~로 결정", "~로 가자", "알겠어" 등 확정 발언 탐지
2. **즉시 Write 실행**: 다음 도구 호출이나 긴 응답 생성 전에 먼저 해당 단기 파일 업데이트
3. **기록 확인 멘트**: "short-term/decisions.md에 기록했습니다." — 사용자에게 기록 완료 알림 (짧게)

---

## 단기→장기 승격(Promotion) 절차

상세: `~/.claude/rules-lazy/memory-promotion.md`

---

## 행동 교정 → 규칙 업데이트 제안 (Learner)

상세: `~/.claude/rules-lazy/learner.md`

---

## Compact / Clear 전 필수 절차 (MANDATORY)

### 실행 전 체크리스트 (순서 준수)

compact 또는 clear 명령 실행 **직전**에 반드시 아래 순서로 실행:

```
Step 1. 현재 대화에서 미기록 합의/결정 사항 전체 스캔
Step 2. short-term/decisions.md에 날짜 포함하여 일괄 기록 (Write 도구)
         → 승격 트리거 해당 항목은 일괄 승격 제안 테이블 제시
Step 3. short-term/handover.md 작성 (현재 작업 상태, 미완료 TODO)
Step 4. 7일 만료 항목 정리 (short-term/decisions.md만 스캔)
Step 5. MEMORY.md 인덱스 항목 수 + 최근 갱신일 업데이트
Step 6. 기록 완료 확인 후 compact/clear 실행
```

> ⚠️ Step 3 (handover.md 작성) 완료 전 compact/clear 실행 절대 금지

### handover.md 규칙
- compact/clear 직전에 작성 (현재 작업 상태, 미완료 TODO, 다음 세션 시작점)
- 다음 세션 시작 시 읽고 소비 → 새 compact 시 **덮어쓰기** (append 금지)
- **최대 50줄** 가이드라인

### 보관할 대화 컨텍스트 범위

compact/clear 전에 아래 내용을 해당 파일에 요약·보관:

| 보관 대상 | 기록 위치 |
|----------|-----------|
| 합의된 실험 설계 변경 | `short-term/decisions.md` |
| 데이터셋·config 결정 | `short-term/decisions.md` → 승격 제안 |
| 코드 수정 요약 | `short-term/handover.md` |
| Go/NoGo 분기 조건 | `short-term/decisions.md` |
| 미완료 TODO | `short-term/progress.md §TODO` |
| 현재 작업 상태 | `short-term/handover.md` |

---

## 7일 보관 정책 (short-term/decisions.md 자동 만료)

### 보관 기간

- `short-term/decisions.md`: 기록 날짜로부터 **7일간 보관**
- 7일 경과 항목: 삭제 (단, 아직 미완료인 TODO는 완료 시까지 보관 유지)
- `long-term/` 파일: 영구 보관 (만료 스캔 제외)

### 만료 항목 삭제 기준

```
현재 날짜 - 항목 날짜 > 7일 → 삭제 대상 (short-term/decisions.md만 해당)
```

단, 아래 항목은 7일 경과 후에도 **영구 보관**:
- 아직 반영되지 않은 코드 변경 결정
- 실험 진행 중인 config·하이퍼파라미터
- 논문 제출 관련 마감/합의 내용
- "영구 보관" 또는 "삭제 금지" 명시된 항목

### 삭제 절차

```
1. short-term/decisions.md 읽기 (long-term/ 파일 스캔 금지)
2. 각 항목 날짜 파싱 → (현재 날짜 - 항목 날짜) 계산
3. 7일 초과 항목 중 영구 보관 조건 해당 여부 확인
4. 조건 미해당 시 해당 줄 삭제 (Edit 도구)
5. 삭제 내역 사용자에게 1줄 보고: "7일 만료 항목 N건 삭제"
6. MEMORY.md 인덱스 항목 수 업데이트
```

### 만료 처리 시점

아래 중 하나 발생 시 만료 항목 스캔 후 삭제:
1. 새 대화 세션 시작 시 (MEMORY.md 로드 직후)
2. compact 실행 전 Step 1~4와 함께 처리
3. 사용자가 "메모리 정리해"라고 요청 시

---

## 기록 우선순위 (compact 임박 시)

컨텍스트 70% 이상 도달 시 미기록 합의 사항 전체 스캔 → 즉시 일괄 기록 후 compact 실행:
```
1. 대화에서 합의된 미기록 결정 목록 추출
2. short-term/decisions.md에 일괄 기록 (Write 도구)
3. 승격 트리거 해당 항목 일괄 승격 제안
4. short-term/handover.md 작성
5. 7일 만료 항목 정리
6. compact 실행 ("실험 config·합의 결정 보존" 지시 포함)
```

---

## 금지 사항

- compact 이후 "기억을 못 했습니다"라고 해명하는 상황 — 예방이 우선
- 합의 내용을 응답 텍스트에만 언급하고 파일에는 기록하지 않는 것
- "나중에 기록하겠습니다"라고 미루는 것 — 즉시 기록이 원칙
- compact/clear 전 handover.md 미작성 상태로 실행하는 것
- `long-term/` 파일을 7일 만료 스캔 대상에 포함시키는 것
- 사용자 승인 없이 단기→장기 자동 승격 (자동 승격 설정 미등록 시)
