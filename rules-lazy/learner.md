# 행동 교정 → 규칙 업데이트 제안 (Learner)

> **로드 시점**: 사용자 교정 감지 시 (`memory-write.md`에서 참조)
> **목적**: 사용자 교정을 feedback.md 기록에서 그치지 않고, 반복적·전역적 패턴은 실제 rules 파일 수정까지 자동 제안한다.
> **OMC learner 기능 흡수** — Oh-my-claudecode의 learner가 하던 역할을 현재 구조에 통합

## 규칙 업데이트 제안 트리거 (아래 중 하나라도 해당 시)

| 조건 | 예시 |
|------|------|
| 동일 유형 교정이 **세션 내 3회+ 또는 Mem0 검색 결과 크로스 세션 3회+**(정본 `mem0-auto.md` T12) | "또 요약 달았네" (현재) + Mem0 search_memories로 과거 유사 교정 발견 |
| 사용자가 "앞으로는", "매번", "항상", "다시는" 사용 | "앞으로는 표를 먼저 보여줘" |
| 교정 내용이 특정 프로젝트가 아닌 **전역 행동**에 해당 | 말투, 응답 형식, 도구 선택 습관 |
| 교정이 기존 rules 파일 내용과 **명시적으로 충돌** | "qa-process.md에 있는 방식이 틀렸어" |
| **중립적 반복 패턴** — 동일 요청·작업방식·발화 3회+ (교정 아님, T40 연계) | "매번 '토큰 점검해'", 특정 작업 순서 반복 |

### § Mem0 크로스 세션 교정 감지

사용자 교정 발생 시 저장 및 반복 여부 자동 확인 → `mem0-auto.md` T12 참조
- 저장 후 유사 교정 검색: 3건+ 발견 → 규칙 업데이트 제안 트리거
- 2건 이하 → feedback.md 기록만 (기존 흐름)

## 제안 흐름

```
1. 교정 감지 → long-term/feedback.md에 즉시 기록 (기존 승격 흐름과 동일) + `task_input`(현재 작업 요약) 및 `ruleset_sha`(`git -C ~/.claude rev-parse --short HEAD`, 실패 시 'nogit') 함께 캡처 → T12 전방계측 (regression suite 구축용)
2. Learner 트리거 조건 해당 여부 판단
3. 해당하면 → [Tier-1 prefilter] `harness-bench.sh gate {벤치ID}` 호출:
     - exit 0 (Pareto strict improvement): **현재는 step 4(사용자 승인)로 직접 연결** (Tier-2 blind gate 자동 활성화는 P2 — 아래 참조)
     - exit 1 (동점·악화): 사용자에게 묻지 않고 reject buffer로 → §거절 기록 흐름 진행
     - exit 2 (잠정 n<3·metric 누락): REJECT 아님. 레지스트리 상태를 `pending-bench`로 갱신하고 사이클을 더 쌓은 뒤 재판정한다(정본 상태열: `pending`(훅 기록)→`pending-bench`→`pending-approval`→`accepted|rejected`, `skills/learn-from-feedback/SKILL.md` § 채택 게이트)
   ※ Tier-2 blind gate: 비활성(P2), 부록 참조. **현재 운영**: Tier-1 통과 후보는 step 4 **사용자 승인**이 곧 게이트.
4. (Tier-1 통과 후) 사용자에게 규칙 업데이트 제안:

   📝 규칙 업데이트 제안 (Learner):
   | 항목 | 내용 |
   |------|------|
   | 교정 내용 | "[교정 요약 1줄]" |
   | 영향 범위 | 전역 행동 / 특정 에이전트 / 특정 규칙 |
   | 수정 대상 파일 | CLAUDE.md / rules/[파일명].md |
   | 제안 변경 | [기존 규칙 → 새 규칙 diff 요약] |

   rules 파일을 업데이트할까요? (Y/N/내용 수정 후 적용. 고르게 하는 것이므로 결정 팝업이 우선)

5. 사용자 승인 → 해당 rules 파일 직접 Edit
6. 사용자 거부 → feedback.md에만 유지 (규칙 변경 없음)
```

## 반복 패턴 → 산출물 3택 (T40 연계 — 자가진화 확장)

> 교정이 아닌 **중립적 반복 패턴**(T40)이 3회+ 누적되면, 룰뿐 아니라 **스킬화/편입**도 후보로 제안한다.

| 패턴 성격 | 대상 .md | 처리 |
|----------|---------|------|
| 전역 행동(말투·형식·보고) | **CLAUDE.md** | 필수 규칙 보강 제안 |
| 라우팅·전처리·모델배정 | **rules/** | 해당 룰 파일 Edit 제안 |
| 특정 에이전트 약점·행동 (T41) | **agents/{name}.md** | 해당 에이전트 회피 가이드 추가 |
| 재사용 절차·명령 묶음 | **스킬 신설/편입** | `/quick-skill` 또는 기존 SKILL.md |
| 상세 규칙·템플릿 | **rules-lazy/** | 해당 lazy 파일 Edit |

> "자가진화"는 스킬뿐 아니라 **모든 하네스 .md**(rule/agent/CLAUDE.md/rules-lazy)를 대상으로 한다. 모호 시 후보 2~3개 제시 후 사용자 선택.

제안 형식에 "산출물 유형(룰/스킬신설/편입)" 행을 포함하고, 모호 시 2~3 후보를 제시해 사용자가 선택한다. 채택 게이트(harness-bench Tier-1 → blind A/B)는 룰과 동일하게 적용 — **단 Tier-2 blind 자동활성은 P2 미활성, 현재는 Tier-1 통과 후 사용자 승인** (§ 제안 흐름 상태 참조).

### 감지 파이프라인 (3층 — "어떻게 반복을 알아채나")
1. **수집(로컬, 토큰 0)**: UserPromptSubmit hook → `scripts/prompt-log.sh` → `_evolve/prompts.jsonl`에 매 프롬프트 적재
2. **빈도(로컬, 토큰 0)**: `scripts/pattern-detect.sh` → 정규화 후 반복 표면 1차 후보
3. **의미+영속(mem0 보강)**: learn-from-feedback이 1차 후보를 LLM 의미 묶음(표면 다른 같은 의도 통합) → **mem0 T40 저장**(머신·세션 넘어 누적). 로컬 로그의 휘발성·머신별 한계를 mem0가 보강.
> 크로스 세션·크로스 머신 누적은 mem0 T40가 백본 — 여러 서버의 같은 패턴이 통합되어 3회+ 판정.

## feedback.md 기록 vs 규칙 업데이트 구분 기준

| 기준 | feedback.md 기록만 | rules 파일 업데이트 제안 |
|------|-------------------|------------------------|
| 적용 범위 | 이 프로젝트/맥락에서만 | 모든 대화·프로젝트에서 |
| 빈도 | 1회 교정 | 반복 교정 또는 "앞으로는" 발언 |
| 기존 규칙 | 관련 규칙 없음 | 기존 규칙과 충돌하거나 보완 필요 |
| 예시 | "이 실험에서는 wandb 꺼줘" | "응답 끝에 요약 절대 하지 마" |

## 금지 사항
- 사용자 승인 없이 rules 파일 자동 수정
- 1회 교정만으로 즉시 규칙 수정 제안 (트리거 조건 미충족 시 feedback.md 기록으로 갈음)
- CLAUDE.md 필수 규칙 번호(1~14) 삭제 또는 의미 훼손

## 자동 패턴 분석 (Auto Pattern Detection — MANDATORY)

> **목적**: Mem0 feedback 카테고리에서 동일 교정 패턴이 N회 누적되면 룰 후보를 자동 생성한다.
> **트리거**: 세션 시작 시 main 확인(`mem0-auto.md` T03. `_evolve/candidates.tsv`의 미결 3종(pending·pending-bench·pending-approval)을 세어 "[개선 후보 N건 …]"으로 표시) 또는 명시적 호출(`/learn-from-feedback`). 「세션 종료 hook(Stop)」은 셸이라 LLM 미실행이므로 트리거가 아니다(`skills/learn-from-feedback/SKILL.md:21`).

### 트리거 조건
- 동일 교정 패턴 **3회+** 누적 (Mem0 feedback 카테고리)
- 후보가 30일 넘게 판정되지 않음 (주기적 분석. SessionStart 의 `CANDIDATES_UNJUDGED_30D` 경보를 `harness-usage-check.sh` 가 맡는다. `_usage/candidates-reviewed-last` 마커는 사람 판정 `candidates-append.sh set` 만 갱신하고(훅·자동 경로의 `set … --machine` 은 마커를 갱신하지 않는다, 사람 판정만), 미결이 있는데 마커가 30일 넘게 안 바뀌면 `harness-usage-check.sh` 가 이 경보를 낸다. 마커가 아예 없을 때는 가장 이른 미결 생성일이 30일 초과일 때만 낸다)
- 사용자가 `/learn-from-feedback` 직접 호출

### 만료 시계 표 (정본, 2026-10-17)

다른 파일은 이 표를 가리키고 복제하지 않는다.

| 시계 | 기간 | 하는 일 | 집행 지점 |
|---|---|---|---|
| 후보 자동 만료 | 7일 | 생성일이 7일 넘은 `pending`(보호 note 없음. `kw=`·`effect:quiet` 기계 비고는 보호 아님, `effect:recurred` 행은 만료 제외)을 `expired` 로 닫는다. 삭제 없음 | `harness-usage-check.sh` 가 SessionStart 에 `candidates-append.sh expire --older-than-days 7` 호출 |
| 교차검증 신선도 | 7일 | 마지막 `일치` 행이 7일을 넘으면 `stale`. 7일 초과면 `--auto` 를 백그라운드로 실행 | `agent-crosscheck.sh latest` · `harness-usage-check.sh` |
| T41 반복 창 | 30일 | 같은 role/dim 3회+ 이면 `T41_REPEAT` | `harness-usage-check.sh` |
| T41 효과 관찰 | 14일 | 미결 T41 후보 note 에 `effect:quiet n_spawn=X` 또는 `effect:recurred k=Y` 를 쓴다. 판정은 사람 | `harness-usage-check.sh` (미결 T41 후보가 있으면 하루 1회) |
| 벤치 지연 | 14일 | 규칙 변경 첫 커밋 뒤 14일 동안 bench 가 없으면 `BENCH_PENDING` | `harness-usage-check.sh` |
| 감사 | 30일 | 마지막 감사 뒤 30일이면 `AUDIT_STALE` | `harness-usage-check.sh` |

- **후보 «보류»**: 상태 어휘가 아니다. `pending` 행의 사람 비고 `hold: <사유>` 이며 7일 만료 보호를 받는다.
- **`accepted`**: 뜻은 «판정 채택» 이다. 규칙·에이전트 파일에 반영됐다는 증명은 비고 `commit=<해시>` 로 한다(해시 없는 accepted 는 아직 반영 증명이 없다).
- **쓰기 범위**: learner·후보 대장 쓰기는 하네스 안에서만 하며, learner 기록 한정으로 scope-gate 의 전원 허용은 `_evolve/quiz/` 뿐이다(전원 허용 폴더 전체는 `scripts/scope-gate.sh` 헤더. 대장 파일은 스크립트 전용, 그 밖의 하네스 경로는 `[Harness] Manager` 세션 전용).

### 분석 흐름

```
1. Mem0 search_memories(query="[프로젝트] feedback 교정", filters={"metadata": {"category": "feedback"}}, limit=50)
   ※ limit=50은 `mem0-auto.md` §1.3 기본 limit=5의 **의도적 예외** — 패턴 마이닝은 코퍼스 전량이 필요하고, learner는 격리 컨텍스트에서 실행되어 main 컨텍스트를 오염시키지 않음
2. 시간 순 정렬 → 키워드 클러스터링 (간이 — 동의어/유사 표현 묶음)
3. 동일 교정 패턴 N회+ 검출 (예: "한글 보고 누락", "재질문 형식 위반", "추측 실행")
4. 각 패턴별 룰 후보 생성 (위치·텍스트 초안 제안)
5. 사용자 승인 형식으로 출력 (아래 § 룰 후보 출력 형식)
```

### 룰 후보 출력 형식 (MANDATORY)

```
🔍 패턴 발견 (Mem0 feedback 분석 결과):

| # | 패턴 | 누적 횟수 | 첫 발견 | 최근 발견 |
|---|------|----------|--------|--------|
| 1 | "{교정 내용 요약}" | N회 | YYYY-MM-DD | YYYY-MM-DD |

📌 룰 후보:
- 적용 위치: {파일 경로} (예: rules/prompt-routing.md Step 1)
- 추가 텍스트:
  ```
  {3~5줄 텍스트 초안}
  ```
- 영향 범위: always-loaded / lazy / agent spawn 시
- 추정 토큰: +N줄

이 룰을 추가할까요? (Y / 수정 / N)
```

> 위 Y/N 질문은 결정 팝업이 우선이다(CLAUDE.md 원칙 7.5).

### 사용자 승인 후 처리
- **Y** → 적절한 파일에 Edit 후 사용자 보고. **승격 산출물(룰·스킬)에는 근거 실측 사례 포인터(knowledge/·decisions.md·mem0 항목) 1줄을 유지**한다 — 경험을 규칙으로 증류할 때 원 사례를 버리면 손실 병목(lossy abstraction)으로 규칙이 원 경험보다 못해지는 실측(SkillEvolBench arXiv 2605.24117, 2026-08-18 검증)
- **수정** → 사용자 텍스트 반영 후 Edit
- **N** → Mem0에 거절 기록 (재제안 방지)

### 거절 기록 (Mem0 — 재제안 방지)
거절된 룰 후보는 다음 분석 시 제외:
```
add_memory(
  text="[YYYY-MM-DD] [claude-global] 룰 후보 거절: {패턴 요약}. proxy_drop: attempts_delta={A_ATT-B_ATT} interventions_delta={A_INT-B_INT} qa_fail_delta={A_QAF-B_QAF}",
  metadata={"category": "feedback", "source": "learner-rejection", "proxy_drop": "{게이트 metric 악화폭 합산}"}
)
```
`proxy_drop` 필드: 게이트 대상 metric(attempts/interventions/qa_fail)의 악화폭을 정량 기록 → 동일 후보 재발굴 차단 강화.

### Tier-2 (QUARANTINED, P2 미활성)
Kill Switch 점검(T3.2)과 Zero-Sum 토큰 예산 점검(T3.3)은 실행 순서에서 빠져 있다. 본문은 아래 «부록: 비활성 절차» 로 옮겼다.

### 안전장치 (MANDATORY)
- 자동 Edit ❌ — 항상 사용자 승인 필요 (Tier-2 blind 선택이 곧 승인이므로 무인 자동수정 아님 — 예외 신설 ❌)
- 룰 위치 모호 시 후보 위치 2~3개 제시 후 사용자 선택
- 동일 패턴 거절 누적 (3회+) → 영구 제외 마킹
- 분석 결과 0건 시 — 알림 없이 종료

---

## 부록: 비활성 절차

### Tier-2 blind gate 상태 (2026-07-17, 단일 상태 출처)

`regression-blind.sh`는 **QUARANTINED**: blind-by-construction 아님(verdict가 정답 키를 판정자 입력에서 읽음 + trial 순서 셔플 없음, 스크립트 헤더에 재설계 요건 명시). learner 자동 연결 **P2 미활성**. **현재 운영**: Tier-1 통과 후보는 step 4 **사용자 승인**이 곧 게이트이며 Tier-2 스크립트는 미사용이다.

### G5 Kill Switch 점검 (T3.2 — QUARANTINED, 선택적 주기 실행)

P2 미활성(QUARANTINED). 예산은 `ci-gate-commit.sh` 75,000B가 측정만 하고 초과는 경고로 알린다(2026-10-01).
룰셋 장기 안정성 확인이 필요할 때 주기적으로 아래를 실행한다 (자동 롤백 없음 — 판정/제안만):

```
# history_tsv: week<TAB>blind_win_rate<TAB>regression_count (주 단위 누적)
harness-evolve.sh killswitch <history_tsv>
```

- **exit 1 (ROLLBACK 판정)** → 사용자에게 이전 ruleset_sha로의 롤백을 **제안**
  - 실제 롤백은 사용자가 직접 수행: `git -C ~/.claude checkout <sha> -- .`
  - 자동 적용 없음 (불변식 1)
- **exit 2 (INSUFFICIENT)** → 데이터 2주 미만, 충분한 데이터 축적 후 재점검
- **exit 0 (OK)** → 현재 룰셋 유지

### (보류) Zero-Sum 토큰 예산 점검 (T3.3)

P2 미활성(QUARANTINED). 예산은 `ci-gate-commit.sh` 75,000B가 측정만 하고 초과는 경고로 알린다(2026-10-01, 커밋을 막지 않는다).
룰 후보 제안 전 토큰 예산을 확인한다 (자동 제거 없음 — 판정/제안만):

```
# budget_tokens: 허용 토큰 수 / candidate_file: 추가 후보 룰 파일 / rule_file...: 현재 룰 파일 목록
harness-evolve.sh zerosum <budget_tokens> <candidate_file> <rule_file...>
```

- **exit 1 (예산 초과)** → 초과량·제거 권장량 출력 후 사용자에게 제거/병합 후보 제시
  - 제거 대상 자동 선정 없음 — 사용자가 직접 결정 (불변식 1)
  - **예산 위기 반복 시** (여유 < 1,000B 또는 주간 zerosum 경고 2회+): `skills/harness-audit/SKILL.md` § Step 1.5 다이어트 사이클 단독 실행으로 라우팅 (2026-07-28 사용자 결정 C, 임계는 08-10 한도 상향에 비례 재보정)
- **exit 0 (예산 이하)** → 룰 추가 가능 (Tier-1 통과 → 현재는 사용자 승인; Tier-2 자동 blind은 P2 미활성 — § 제안 흐름)
