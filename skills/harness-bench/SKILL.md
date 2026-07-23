---
name: harness-bench
description: Use when 룰/스킬/agents 파일 변경 후 효과 측정. Before/After 동일 작업 재실행하여 토큰·정확도·횟수 비교. 변경 효과 가시화.
model: haiku
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - mcp__mem0__add_memory
  - mcp__mem0__search_memories
---

# Harness Bench (Before/After 측정)

> **목적**: 시스템 변경(룰/스킬/agents)의 효과를 객관적으로 측정한다. "감으로 좋아진 듯"이 아닌 "수치로 N% 개선" 보고.

## 트리거

| 트리거 | 시점 |
|--------|------|
| 명시적 호출 (`/harness-bench init "..."`) | 측정 시작 |
| learner 자동 룰 추가 직후 | 신규 룰의 효과 검증 |
| 사용자 "효과 측정해" / "비교해" 명시 | 즉시 |

## 사용 흐름

### 1. 초기화
```
bash ~/.claude/scripts/harness-bench.sh init "loss function 수정 작업" "bench-loss-202605"
```
→ `~/.claude/_bench/bench-loss-202605.md` 생성

### 2. Before 측정 (변경 전 상태에서 작업 실행)
1. 동일 작업을 변경 **전** 룰로 실행
2. 결과 수집 (예: QA 통과 여부, 시도 횟수, 사용 토큰, 사용자 개입 횟수)
3. 기록:
```
bash ~/.claude/scripts/harness-bench.sh before "bench-loss-202605" "시도 3회, 사용자 개입 2회, QA FAIL 1회 후 통과"
```

### 3. 룰/스킬 변경 적용

### 4. After 측정 (변경 후 상태에서 동일 작업 실행)
1. 동일 작업을 변경 **후** 룰로 실행
2. 결과 수집
3. 기록:
```
bash ~/.claude/scripts/harness-bench.sh after "bench-loss-202605" "시도 1회, 사용자 개입 0회, QA 1회 통과"
```

### 5. 비교 보고
스크립트가 자동으로 Before/After 차이 stdout 출력.

## 측정 지표 권장 (Anthropic 하네스 강화 루프)

| 지표 | 의미 | 좋은 변화 | Gate 역할 |
|------|------|---------|----------|
| 시도 횟수 (`attempts`) | 작업 완료까지 반복 | 감소 | **게이트 대상** |
| 사용자 개입 (`interventions`) | main 에스컬레이션 횟수 | 감소 | **게이트 대상** |
| QA FAIL (`qa_fail`) | 검증 실패 횟수 | 감소 | **게이트 대상** |
| 사용 토큰 (`tokens`) | 누적 토큰 (대략) | 감소 | **모니터 전용 — 게이트 제외** (Goodhart 차단) |
| 작업 시간 | 시작~완료 시간 | 감소 | 참고 |
| preference-gate 통과율 | gate exit 0 비율 (3사이클 기준) | 증가 | 메타 지표 |
| tier별 후보 수 | Tier-1 통과 / reject 후보 건수 | Tier-1 통과↑ | 메타 지표 |

## Mem0 통합

After 측정 완료 시 `code_pattern` 카테고리에 효과 저장:
```
add_memory(
  text="[YYYY-MM-DD] [claude-global] Harness bench: {벤치ID} — Before({요약}) → After({요약}), 효과: {요약}",
  metadata={"category": "code_pattern", "source": "harness-bench", "gate_verdict": "PASS|FAIL|inconclusive"}
)
```

## learner 통합 (Tier-1 게이트 필수 단계)

learner의 룰 후보는 **Tier-1 게이트를 통과한 경우에만 Tier-2로 진입**한다 (설계). **Tier-2 blind 자동활성은 P2 미활성 — 현재 Tier-1 통과 후보는 사용자 승인으로 연결** (`rules-lazy/learner.md` § step 3).
`harness-bench.sh gate {벤치ID}` 호출 → exit 0(Pareto 개선)이면 **현재는 사용자 승인으로 연결**(Tier-2 blind gate은 QUARANTINED·P2 미활성 — `rules-lazy/learner.md` § step 3) → exit≠0이면 사용자 개입 없이 reject buffer.
사용자가 작업 1회 수행 후 before/after 기록, gate 서브커맨드로 자동 판정.

## Anthropic 권장 — 3사이클 반복

룰 변경 후 동일 측정을 3회 반복하여 효과 안정성 확인 (단발 측정 ❌). 매 사이클마다 측정값 누적, 평균 ± std 보고.

> **근거 (awesome-evals)**: Anthropic infra-noise 연구 — 동일 작업도 RAM/리소스 제한으로 점수가 **±6pp 변동** → 단발 측정은 노이즈와 구별 불가(3사이클 평균±std 필수). 결과뿐 아니라 **과정(process-first)**도 측정 대상(시도 흐름·중간 실패).
> **judge 일관성**: 측정 채점도 judge 행위 → `~/.claude/rules-lazy/llm-judge-practices.md`(이진·기준 고정) 준수.

## 안전장치

- 동일 벤치 ID 중복 init 차단
- Before 미기록 상태에서 after 호출 시 경고
- 측정 데이터는 `~/.claude/_bench/` 로컬 저장 (Mem0 백업)
