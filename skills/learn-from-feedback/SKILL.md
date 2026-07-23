---
name: learn-from-feedback
description: Use when 사용자 교정 패턴 자동 분석. Mem0 feedback 카테고리 N회+ 누적 시 룰 후보 제안. 명시적 호출 또는 세션 시작(T03) 확인 시 자동 트리거.
model: opus
allowed-tools:
  - Read
  - Edit
  - Glob
  - Grep
  - Agent
  - Bash
  - AskUserQuestion
  - mcp__mem0__add_memory
  - mcp__mem0__search_memories
  - mcp__mem0__update_memory
  - mcp__mem0__get_memories
---

# Learn From Feedback

> **트리거**: 명시적 호출(`/learn-from-feedback`) 또는 세션 시작(T03) 확인 시 자동 — "Stop hook 자동 실행" 표기는 죽은 주장이었음(Stop hook은 셸이라 LLM 미실행, 본문 §비교표가 이미 정정 — 2026-07-16 description·트리거 표기 일치화)
> **상세 흐름**: `~/.claude/rules-lazy/learner.md` § 자동 패턴 분석

## 실행 순서

1. **감지 입력 수집**:
   - 로컬 빈도(토큰 0): `bash ~/.claude/scripts/pattern-detect.sh 3` → 반복 표면 1차 후보
   - Mem0 이력: feedback 카테고리(T12 교정 + T40 반복 패턴) + code_pattern 카테고리 agent-eval source(T41 에이전트 약점) 각각 검색
2. **시간 순 정렬** + 키워드 클러스터링 — pattern-detect 1차 후보를 **LLM 의미 묶음**(표면 다른 같은 의도 통합)
3. **동일 패턴 3회+ 검출** → 후보 생성 (룰 / 스킬 신설 / 기존 스킬 편입 — T40 자가진화)
   - 교정 패턴 → 룰 후보. 중립적 반복 패턴(요청·작업방식) → `rules-lazy/learner.md § 반복 패턴 → 산출물 3택` 기준으로 룰/스킬신설(quick-skill)/편입 분류
   - **Lt budget**: 한 사이클 후보 수 ≤K개(기본 K=4, 이전 사이클 채택률에 따라 cosine decay floor=2)로 클립 — 후보 과잉 억제
4. **사용자 승인 형식 출력** (learner.md § 룰 후보 출력 형식 준수)
5. **채택 게이트 (2-tier — 설계)**:
   > **상태 (2026-07-17)**: Tier-2 blind A/B **자동활성은 P2 미활성** (스크립트 인프라는 구현됨, 활성화 전 재설계 필요 — `rules-lazy/learner.md` § step 3). **현재 운영**: Tier-1(exit 0) 통과 → 아래 Tier-2 대신 **사용자 승인**으로 연결. 아래 Tier-2 절차는 활성화 시 흐름.
   - **Tier-1**: `harness-bench.sh gate <bench_id>` → exit 0이면 Tier-2 진입. exit 1/2이면 REJECT.
   - **Tier-2 (blind A/B — P2 미활성)**:
     a. `regression-blind.sh prepare <candidate_edit_file> <work_dir>`
     b. `regression-blind.sh run <work_dir> <suite_file>` — 사용자가 직접 실행
     c. 사용자 blind 선택 완료 후 `regression-blind.sh verdict <picks_file>`
     d. **verdict ACCEPT(exit 0)** → 채택 (사용자 blind 선택=승인으로 간주) → Edit 실행
     e. **REJECT/INCONCLUSIVE** → 채택 보류, Mem0에 "learner-rejection" source로 기록
   - **zero-sum 원칙**: 룰 추가 전 `harness-evolve.sh zerosum`으로 토큰 예산 점검
     → 초과 시 초과량·제거 권장량 출력 + 제거/병합 후보를 사용자에게 제시 (자동 선정 없음)
   - **slow update (주기 도달 시 — T3.1)**:
     a. `harness-evolve.sh slowupdate-run <prev_ruleset_dir> <curr_ruleset_dir> <suite_file>`
        → prev/curr_results.tsv 생성 (regression-judge.sh 경유)
        ※ prev_ruleset_dir 구성: `git -C ~/.claude archive <sha> | tar -x -C <dir>`
     b. `harness-evolve.sh slowupdate-compare prev_results.tsv curr_results.tsv`
        → 회귀 발견(exit 1) 시 사용자에게 경고 + 회귀 case 목록 제시
        → 회귀 없음(exit 0) 시 현재 룰셋 유지
     c. 자동 롤백·자동 제거 없음 — 판정/제안만 (불변식 1)
   - **G5 kill switch (주기적 안정성 점검)**:
     `harness-evolve.sh killswitch <history_tsv>` → ROLLBACK 판정 시 사용자에게 이전 sha 롤백 제안
6. **거절 시** → Mem0에 "learner-rejection" source로 기록

## 트리거 조건

| 조건 | 우선순위 | 처리 |
|------|---------|------|
| 사용자 명시적 호출 (`/learn-from-feedback`) | 높음 | 즉시 실행 |
| 세션 시작(T03) 시 main 확인 | 중간 | `pattern-detect.sh` 실행 → 반복 후보 발견 시 제안 (Stop hook은 셸이라 LLM 미실행 — 세션 시작 확인으로 현실화) |
| 주기적 (Cron) / 수동 트리거 | 낮음 | **slow update** (T3.1): `harness-evolve.sh slowupdate-run` → `slowupdate-compare`로 이전 vs 현재 룰셋 회귀 점검 → 회귀 발견 시 사용자 경고 |

## 출력 형식

`~/.claude/rules-lazy/learner.md` § 룰 후보 출력 형식 그대로 따름.

## 모델 위임 (model-assignment.md 준수)
- **분석·패턴 추출**: Sonnet — 코드 분석 + 텍스트 생성
- **단순 Mem0 검색·정리**: Haiku 가능
- **룰 후보 텍스트 생성**: Sonnet — 로직 판단 포함

## 안전장치 (MANDATORY)
- 자동 Edit ❌ — 항상 사용자 승인 필요 (blind 선택=승인으로 간주)
- 룰 위치 모호 시 후보 위치 2~3개 제시 후 사용자 선택
- 동일 패턴 거절 3회+ → 영구 제외 마킹
- 분석 결과 0건 시 알림 없이 종료

## 마지막 분석 시점 추적
세션마다 마지막 분석 시각을 Mem0에 기록:
```
add_memory(
  text="[YYYY-MM-DD HH:MM] [claude-global] learn-from-feedback 분석 완료 — 검출 N건 / 제안 M건",
  metadata={"category": "context", "source": "learn-from-feedback"}
)
```
다음 호출 시 이 메모를 검색하여 7일 경과 여부 판단.
