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
| 후보 status가 `pending`→`pending-bench`로 바뀐 때(승인 전, `bench/<후보id>` 임시 브랜치) | 신규 룰의 효과 검증 |
| 사용자 "효과 측정해" / "비교해" 명시 | 즉시 |

> **벤치 순환 해소 (2026-09-14 설계 결정)**: Before=`HEAD`(현재 상태)에서 측정 → 변경 적용은 `bench/<후보id>` 임시 브랜치에만 커밋(main 미반영) → After=그 브랜치에서 동일 작업 재실행. main 브랜치 반영은 사용자 승인 뒤(`skills/learn-from-feedback/SKILL.md` § 채택 게이트). 승인 뒤의 커밋 종류·`Intent:` 줄·병합 방식·세션 전파는 같은 파일 § 후보 상태 집합의 «accepted 뒤의 걸음» 을 따른다.

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
bash ~/.claude/scripts/harness-bench.sh before "bench-loss-202605" "attempts=3 interventions=2 qa_fail=1 path=$HOME/.claude/jobs/<job>/qa-report-1.md 시도 3회·개입 2회·QA FAIL 1회 후 통과"
# (파서 요구: 게이트 지표 3종 key=N + 근거 파일 경로. 근거 파일은 ①$HOME 아래 실존·비어있지 않은 일반 파일 ②파일명이 qa-report*.md·*watcher*.log·launch-state-*.json·session*/train*/*eval*.log 형식(또는 `~/.claude/projects/*/`·`jobs/*/` 아래 transcript `*.jsonl`만) ③그 파일 안에 같은 attempts=/interventions=/qa_fail= 토큰이 **숫자 경계로 정확히** 있고 after는 `무관작업개재=Y`도 파일 안에 ④같은 벤치에서 재사용 불가 ⑤ctime이 직전 사이클 기록 이후. 경로는 큰따옴표 안이라 `~`가 안 풀린다 — `$HOME` 또는 절대경로로(6·7라운드))
# ★정직 표기: 이 벤치는 **자기보고 도구**다. 위 결박은 재사용·사후 조작·형식 위반을 막을 뿐, 세션이 QA 리포트 자체를 지어내는 것까지 막지는 못한다 — 지표의 진위는 qa 8항(main 해시 재계산)과 사용자 승인 단계가 책임진다.
```

### 3. 룰/스킬 변경 적용 (`bench/<후보id>` 임시 브랜치에만 — main 미반영)

### 4. After 측정 (변경 후 상태에서 동일 작업 실행)

> **측정 시점 (MANDATORY)**: 변경 직후 같은 맥락에서 재지 말고 **무관 작업 1개 이상을 사이에 둔 뒤** 측정한다 — 같은 맥락 즉시 측정은 효과 과대평가(FinEvo-Bench 교차 배치, 2026-08-18 검증). after 요약에 `무관작업개재=Y` 토큰이 **있어야 기록된다**(스크립트 강제, 2026-08-25 4라운드: `N`이나 누락은 `after`가 exit 3으로 거부하고 `gate`도 After 전 사이클에 Y가 없으면 exit 2). 같은 맥락 즉시 측정분은 애초에 기록하지 않는다.

1. 동일 작업을 변경 **후** 룰로 실행
2. 결과 수집
3. 기록:
```
bash ~/.claude/scripts/harness-bench.sh after "bench-loss-202605" "attempts=1 interventions=0 qa_fail=0 무관작업개재=Y path=$HOME/.claude/jobs/<job>/qa-report-2.md 시도 1회·개입 0회·QA 1회 통과"
# (after 는 '무관작업개재=Y' 토큰까지 필수 — 없으면 exit 3)
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

learner의 룰 후보는 **Tier-1 게이트를 통과한 경우에만 Tier-2로 진입**한다 (설계). **Tier-2 blind 자동활성은 P2 미활성 — 현재 Tier-1 통과 후보는 사용자 승인으로 연결** (`rules-lazy/learner.md` § 제안 흐름).
`harness-bench.sh gate {벤치ID}` 호출 → exit 0(Pareto 개선)이면 후보 status를 `pending-approval`로 갱신하고 **현재는 사용자 승인으로 연결**(Tier-2 blind gate은 QUARANTINED·P2 미활성 — `rules-lazy/learner.md` § 제안 흐름) → **exit 1만** reject buffer(악화·동점). **exit 2(잠정 n<3·metric 누락·무관작업 미표기·근거 파일 결박 실패=evidence/sha 불일치·형식·경계·토큰 재검증 실패)는 reject가 아니라 `pending-bench`** — 사이클을 더 쌓는다(learn-from-feedback Tier-1과 동일 해석, 4라운드 검수로 문면 통일).
사용자가 작업 1회 수행 후 before/after 기록, gate 서브커맨드로 자동 판정.

## 3사이클 반복 — 게이트 배선 (2026-08-25 권장→필수)

룰 변경 후 동일 측정을 3회 반복하여 효과 안정성 확인 (단발 측정 ❌). 매 사이클마다 측정값 누적, 평균 보고(`gate` 는 평균만 계산하고 표준편차는 내지 않는다. 사이클별 원값을 함께 보고해 변동을 보인다).
- **gate가 사이클 수 n을 센다(스크립트 강제, 2026-08-25)**: `before`/`after`는 기록을 덮어쓰지 않고 **사이클로 누적**하며, `gate`는 각 섹션의 사이클 수를 세어 **min(nB, nA) < 3이면 `잠정(n=N)` 라벨과 함께 exit 2(inconclusive)**로 끝낸다 — Tier-1 통과로 취급되지 않는다(사용자 승인 연결 불가, reject buffer도 아님 — 추가 사이클 대기). 판정 값은 각 섹션 **전 사이클의 평균**(마지막 사이클만 좋게 쓰는 조작 차단, 스크립트 `mean_of`와 일치); 어느 사이클이든 게이트 metric이 빠지면 inconclusive. 종전에는 자유 서술 1회 기록 뒤 gate가 exit 0을 낼 수 있었다.
- **원시 근거 첨부(스크립트 강제)**: before/after 요약 문자열에 수치의 출처 경로(`/`가 포함된 토큰: 세션 로그·QA 리포트·watcher.log 등) 1개 이상이 없으면 `harness-bench.sh`가 기록을 거부한다. 같은 시스템이 "시도 3회→1회"를 자기 입력하는 것을 막기 위한 최소 조건.

> **근거 (awesome-evals)**: Anthropic infra-noise 연구 — 동일 작업도 RAM/리소스 제한으로 점수가 **±6pp 변동** → 단발 측정은 노이즈와 구별 불가(3사이클 평균과 사이클별 원값 필수). 결과뿐 아니라 **과정(process-first)**도 측정 대상(시도 흐름·중간 실패).
> **judge 일관성**: 측정 채점도 judge 행위 → `~/.claude/rules-lazy/llm-judge-practices.md`(이진·기준 고정) 준수.

## 안전장치

- 동일 벤치 ID 중복 init 차단
- Before 미기록 상태에서 after 호출 시 별도 경고는 없고, `gate` 가 사이클 수 부족(min(nB, nA) < 3)을 `잠정(n=N)` 으로 표시한다
- 측정 데이터는 `~/.claude/_bench/` 로컬 저장 (Mem0 백업)
