# 즉시 메모리 기록 규칙 (Immediate Memory Write)

> **로드 시점**: 항상 (모든 대화에 적용 — 자동 트리거)
> **핵심 원칙**: 합의된 결정은 그 즉시 `short-term/decisions.md`에 기록한다. compact 이후에도 복구할 수 없는 합의 소실은 용납되지 않는다.

## 메모리 구조 (short-term / long-term 분리)

| 경로 (short-term root = `~/.claude/projects/-home-user-workspace/memory/`. SessionStart 정리(prune)는 이 고정 루트와 cwd 기반 현재 프로젝트 폴더 둘 다 대상) | 용도 | 만료 |
|------|------|------|
| `short-term/decisions.md` | 합의 결정 이력 | 7일 |
| `short-term/handover.md` | 세션 인수인계 | compact 시 덮어쓰기 |
| `${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/<프로젝트>/` | 프로젝트별 영구 노트. 주제 파일(`architecture.md`·`experiments.md`·`hyperparams.md`·`feedback.md` 등)은 그 프로젝트에 실제로 있는 것만 쓰고, 없으면 새로 만든다. 파일 수·이름은 프로젝트마다 다르다 | 영구 |
| `${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/<프로젝트>/meetings/` | discuss 회의록 + _workspace | 영구 |
| `${LONG_TERM_ROOT:-~/workspace/_data/workspaces/user/.claude/long-term}/papers/` · `research/` | 논문 리뷰 · 리서치 리포트(프로젝트와 무관한 공용 폴더) | 영구 |

> 이 표가 long-term 목적지의 단일 정본이다. `mcp-fallback-mem0.md`·`memory-promotion.md` 의 «long-term/xxx.md» 는 이 표의 `<프로젝트>/` 아래 주제 파일을 가리킨다.

---

## 자동 메모리 색인 MEMORY.md 상한 160줄 (2026-09-08 사용자 결정, 2026-10-17 60줄에서 160줄로)

경로는 `~/.claude/projects/-home-user-workspace/memory/MEMORY.md` 이고 **상한은 160줄**이다. 넘으면 종료된 항목을 목차 노트 한 줄로 묶는다. 현재 프로젝트 MEMORY.md 가 160줄을 넘으면 SessionStart 점검(`harness-usage-check.sh`)이 `MEMORY_INDEX_LONG` 경보를 낸다. 이 색인은 세션마다 통째로 컨텍스트에 올라가므로 줄 수가 곧 상시 비용이며, 종료된 실험의 수치까지 남으면 살아 있는 제약이 그 사이에 묻힌다.

| 항목 | 처리 |
|------|------|
| 종료된 사이클의 결과·수치·페이지 ID | `~/.claude/knowledge/<프로젝트>/` 노트로 이관하고 색인 줄 삭제 |
| 피드백·사용자 속성·살아 있는 제약·미결 항목 | 색인에 유지 |

새 항목을 넣어 160줄을 넘기면 **가장 오래된 종료 실험 항목부터** 이관한다. 순서는 knowledge 노트를 먼저 만들고 내용을 대조한 뒤 색인 줄을 지우는 것이다. 판정이 애매하면 유지 쪽에 둔다.

---

## 즉시 기록 트리거 (MANDATORY — 아래 상황 발생 시 다음 응답 전에 반드시 Write 실행)

| 트리거 상황 | 기록 대상 | 기록 위치 |
|------------|-----------|-----------|
| 사용자가 실험 설계/순서에 합의 | 실험 명칭, config, dataset, 실행 순서 | `short-term/handover.md` |
| 사용자가 데이터셋 추가/변경/제거 확정 | 변경 전후 dataset 목록 + 사유 | `short-term/decisions.md` → 승격 제안 |
| 사용자가 아키텍처/하이퍼파라미터 결정 | 파라미터 값, 결정 근거 | `short-term/decisions.md` → 승격 제안 |
| 사용자가 실험 전 사전 검증(precheck) 방식 합의 | 실험 명칭, config, 목적 | `short-term/handover.md` |
| 사용자가 향후 작업 계획 확정 | 작업명, 조건, 순서 | `short-term/handover.md` |
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
4. Mem0 불가 시: mcp-fallback-mem0.md § Mem0 Fallback 적용 (파일 기록만으로 진행 — 스킵 금지)
```

- 파일 기록 실패 시에도 Mem0 저장은 독립 실행
- 7일 만료로 아카이브로 옮겨져도 Mem0에서 `search_memories`로 복구 가능

## 기록 형식

```markdown
- YYYY-MM-DD [프로젝트] [결정 요약]: [구체 내용] — 근거: [사유 1~2줄]
```

줄머리는 `- YYYY-MM-DD` 가 기본이고, 정리 스크립트는 굵게 쓴 `- **YYYY-MM-DD …**` 도 함께 인식한다.

예시:
```markdown
- 2026-03-02 [프로젝트] precheck 합의: Omniglot + Maze × Full+HC ON = 2개 실험 먼저 실행 → 수렴 확인 후 전체 242개 진행
- 2026-03-02 [프로젝트] 데이터셋 교체: MNIST → Omniglot (964-way, part-whole hierarchy 검증에 더 적합)
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
Step 4. 7일 만료 항목은 SessionStart 정리 스크립트가 이동하므로 수동 삭제 없음
Step 5. MEMORY.md 인덱스 항목 수 + 최근 갱신일 업데이트
Step 6. 기록 완료 확인 후 compact/clear 실행
```

> ⚠️ Step 3 (handover.md 작성) 완료 전 compact/clear 실행 절대 금지

### handover.md 규칙
- compact/clear 직전에 작성 (현재 작업 상태, 미완료 TODO, 다음 세션 시작점)
- 다음 세션 시작 시 읽고 소비 → 새 compact 시 **덮어쓰기** (append 금지)
- **최대 50줄** 가이드라인
- **민감정보 스크럽 (MANDATORY)**: API 키·비밀번호·PII는 기록 전 제거 — git 추적 파일이라 유출 경로가 된다 (출처: mattpocock/skills `handoff`, MIT)
- **다음 세션 제안 스킬 1줄** 포함: 재개 시 어떤 스킬·라우팅으로 이어갈지 (동 출처)
- **기억상실 자가검증**: 저장 전 "기억이 전부 사라진 채 이 문서만 보고 깨어나도 끊김 없이 이어갈 수 있는가"를 재독으로 점검, 아니면 보강 (아이디어 출처: alexknowshtml/claude-skills `pause` — 무라이선스 레포라 원문 비복제·재작성)

### 보관할 대화 컨텍스트 범위

compact/clear 전에 아래 내용을 해당 파일에 요약·보관:

| 보관 대상 | 기록 위치 |
|----------|-----------|
| 합의된 실험 설계 변경 | `short-term/decisions.md` |
| 데이터셋·config 결정 | `short-term/decisions.md` → 승격 제안 |
| 코드 수정 요약 | `short-term/handover.md` |
| Go/NoGo 분기 조건 | `short-term/decisions.md` |
| 미완료 TODO | `short-term/handover.md` |
| 현재 작업 상태 | `short-term/handover.md` |

---

## 7일 보관 정책 (short-term/decisions.md 자동 만료)

### 보관 기간

- `short-term/decisions.md`: 기록 날짜로부터 **7일간 보관**, 지나면 같은 폴더 `decisions-archive.md` 로 **이동**(삭제하지 않는다)
- 이동은 `scripts/decisions-prune.sh` 가 SessionStart 점검 안에서 하루 1회 한다. 모델은 줄을 직접 지우지 않는다
- `long-term/` 파일: 영구 보관 (만료 스캔 제외)
- 승격 대상(미반영 코드 변경 결정·진행 중 실험 config·논문 마감 합의)은 이동 전에 `memory-promotion.md` 로 승격을 제안한다

### 수동 정리를 요청받았을 때

사용자가 «메모리 정리해»라고 하면 `bash scripts/decisions-prune.sh <memory 폴더>` 를 안내하고 이동 건수를 1줄로 보고한다. 아카이브 파일은 필요할 때 Grep 으로 되살린다.

---

## 기록 우선순위 (compact 임박 시)

컨텍스트 70% 이상 도달 시 미기록 합의 사항 전체 스캔 → 즉시 일괄 기록 후 compact 실행:
```
1. 대화에서 합의된 미기록 결정 목록 추출
2. short-term/decisions.md에 일괄 기록 (Write 도구)
3. 승격 트리거 해당 항목 일괄 승격 제안
4. short-term/handover.md 작성
5. (7일 만료 항목은 SessionStart 정리 스크립트 소관, 수동 삭제 없음)
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
