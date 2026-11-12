# 에이전트 eval-driven 자가진화 (판정 → 약점 축적 → 개선)

> **로드 시점**: 에이전트 작업 실패/재작업 신호 감지 시, 또는 세션 시작(T03) 약점 분석 시.
> **목적**: 새 judge를 매번 돌리지 않고, 작업 중 **이미 발생하는 결정론적 실패 신호**를 에이전트별 약점으로 라우팅·축적 → 동일 약점 3회+ 시 해당 `agents/{name}.md` 개선 제안.
> **베이스**: eval-driven — 평가가 개선을 구동. 판정은 `llm-judge-practices.md`(이진·근거·게이밍 방어) 준수.
> **연관**: T40(사용자 반복 패턴 자가진화)과 **평행 구조** — 대상만 "에이전트 출력 약점", 게이트는 동일.

---

## §1 실패/재작업 판정 신호 (토큰 0 — 작업 중 자연 발생 신호 재사용)

| 신호 | → 약점 귀속 에이전트 | 강도 |
|------|------------|------|
| **사용자 직접 재작업 지시·부정 피드백** ("다시 해", "이거 아니야", "그렇게 하는 게 아니라", "왜 이렇게 했어") | 직전 산출 에이전트 | **최강(명시)** |
| qa FAIL (6-Gate / 2단계 1차 spec FAIL) | coder | 강 |
| 재작업 ≥2회 (G-E loop·Ralph cycle·동일 지점 재수정) | coder | 강 |
| coder status = BLOCKED / NEEDS_CONTEXT (훅이 정책대로 막아 끝난 BLOCKED 는 약점으로 세지 않는다. 다만 막힌 뒤 우회를 시도한 흔적이 있으면 센다) | 원인(scout 정찰부족 / planner 설계모호). 단 훅 자동 기록은 낸 에이전트·범위 준수로 귀속하고(§2 아래 «자동 기록의 차원·역할 귀속 규칙») 원인 재귀속은 사람·main 이 수동으로 한다 | 중 |
| main이 결과 반려·재의뢰 | 해당 에이전트 | 중 |
| 사용자 교정(T12)이 에이전트 산출 대상 | 그 에이전트 | 중 |
| citation-verifier contrasting/철회 | searcher / researcher | 중 |
| searcher 객관 게이트 미달(출처<3·1차 부재) | searcher | 중 |
| **과잉 위임** — 사후에 직답·경량 수단으로 충분했음이 자명한 소집(subagent 산출이 main 1턴 직답과 동급, 위임 오버헤드만 발생) | main(위임 판단) | 약 |

> 과잉 위임 축의 근거: Beacon(arXiv 2607.28595) — 도구를 "쓸 줄 아는 것"과 "필요할 때만 쓰는 것"은 다른 능력이며, 대안(직답)이 성공하는 상황의 무거운 수단 사용은 이득 없이 손해만 남긴다는 실측. RL 보상은 이식 불가 — 사후 신호 축만 차용.

> 신호 발생 시(**실패 시에만**) main이 mem0 **T41**에 약점 1건 저장. 성공은 기록 안 함. 별도 평가 단계·매번 judge 없음 = 토큰 0 판정.

> **파일 기록은 기계가 한다 (2026-09-14)**: T41 파일 기록은 `scripts/agent-spawn-log.sh` post(**동기 소집 결과**)와 `scripts/t41-subagent-stop.sh`(**비동기 소집 결과** — SubagentStop 훅이 서브에이전트의 마지막 답을 읽는다)가 훅에서 자동으로 남기고, main 은 훅이 못 본 신호(사용자 재작업 지시·T12 교정·과잉 위임)만 보탠다. 두 훅은 행 앞에 고정된 강형 표기(`RESULT: FAIL`·`STATUS: BLOCKED`·행 첫 `NEEDS_CONTEXT` 등)만 신호로 본다. 느슨한 «실패·재작업·반려»는 «실패 스위트: 0» 같은 성공 문장에도 맞아 제외했고, 비동기 소집의 즉시 응답(«Async agent launched …», 보낸 프롬프트 원문 포함)은 결과가 아니므로 판정에서 건너뛴다(같은 날 실사고: 검수용 qa 소집이 자기 프롬프트의 «RESULT: FAIL» 문구로 T41 을 낳았다).

> **역할 별칭 표(접두 기준, 정본 `scripts/role-alias.sh`, 2026-10-17)**: `sec|security`→security · `qa` · `coder` · `scout` · `searcher` · `planner` · `researcher` · `reviewer` · `docs` · `gitops` · `tutor` · `citation`→citation-verifier.
> 접두 뒤는 끝이거나 `-`·`_`·숫자일 때만 인정하고(`sec-g1`→security, `qa-2`→qa), 표에 없는 이름(`foo`·`dfs-2`)은 그대로 둔다.

### §1.5 집계 규율 (2026-08-25 Codex·Grok 교차감사 반영)
- **중복 계수 차단**: 같은 사건(예: 사용자 교정 1건)이 T12와 T41에 함께 저장될 때는 두 레코드에 같은 `event_id`(`YYYYMMDD-HHMMSS-<4자 랜덤 hex>` — 같은 분의 같은 슬러그가 충돌하던 형식을 교체, 2026-08-25)를 적고, "3회+" 집계는 event_id 기준으로 1회로 센다. **부여 주체는 저장하는 main**: 한 사건에 id는 하나다 — 같은 턴에서 처음 정한 `[event:{id}]`를 T12·T41 양쪽 `add_memory` text 서두에 그대로 재사용한다(사건마다 슬러그를 새로 지으면 중복 제거가 깨진다; `rules-lazy/mem0-templates.md` T12/T41). 종전에는 교정 2건이 4신호로 불어 3회 문턱을 넘을 수 있었다.
- **분모 병기**: "동일 약점 N회"는 같은 기간 그 에이전트의 **소집 횟수를 분모로** 적는다. 분모 정본은 `_audit/agent-spawn.log`의 **`post` 줄**(PostToolUse(Agent) 훅 `scripts/agent-spawn-log.sh post`가 소집 완료마다 `ts·phase·subagent_type·name·model·description` 기록 — `pre` 줄은 실패한 시도까지 포함하므로 분모에 넣지 않는다; 2026-08-25 배선, 서술형 history.md·사용자 프롬프트 로그로는 셀 수 없었다). teammate는 `name` 열로 구분한다. **기간·임계(2026-08-25 확정)**: 창은 "최근 30일 또는 최근 50회 소집 중 먼저 차는 것". **연속** = 최근 5회 소집 중 3회 이상 같은 약점 → §3 개선 제안·구조 전환 게이트 진입. **산발** = 창 안 비율 10% 미만 → 관찰 유지(기록만). 그 사이(10% 이상이나 연속 아님) = 다음 창에서 재평가. 로그가 없는 기간은 "분모 미상"으로 표기하고 즉시 조치하지 않는다. **교차 의무(5라운드 검수)**: 이 로그는 신뢰 경계 밖(훅 외 경로로 행을 넣을 수 있음)이므로 **검출은 경보(로그 계수)가 하되 채택 판정(3회+ 게이트)은 로그 단독으로 내리지 않는다** — `/learn-from-feedback` 실행 순서 1(감지 입력 수집)에서 main이 `bash ~/.claude/scripts/agent-crosscheck.sh`를 실행해 같은 창의 세션 transcript와 대조한 뒤 판정한다(7라운드 렌즈3: 실행 주체·시점 명시). 계수 규칙·판정 임계·기록 파일·"최신 판정"의 정의는 **그 스크립트 헤더만이 정본**이며 이 문단과 `skills/learn-from-feedback/SKILL.md`는 산문으로 복제하지 않는다(8~11라운드: 인라인 두 벌이 창·디렉터리·계수·재귀 깊이·mtime 기준에서 4회 드리프트했고 awk `>=`가 훅에 막혀 main이 실행조차 못 했다. 12라운드 렌즈1: "동일 문자열이어야 한다"는 요구 자체가 위반돼 있었다 — 복제하지 않는 것이 유일한 안정 방법). §3 게이트 진입은 `bash ~/.claude/scripts/agent-crosscheck.sh latest`가 exit 0(`_evolve/crosscheck.tsv` 마지막 기록의 판정 "일치")일 때만이며 **그 `latest: …` 출력 원문을 제안에 인용**한다 — 인용 없는 진입·기록 없는 3회+ 선언은 자기선언으로 무효(13라운드 렌즈3: spawn-tree·evidence-ls·launch-set verify 와 같은 원문 인용 규약).
- **외부 신호 필수**: 내부 판정 신호(main 반려·과잉 위임)만으로는 3회가 차도 후보를 만들지 않는다. 최소 1회는 외부 신호(**§1 최강 신호인 사용자 재작업 지시·부정 피드백**, 사용자 교정 T12, qa FAIL, 테스트 실패, citation-verifier 철회)가 포함돼야 한다(외부 피드백 없는 자기교정 축적 차단 — `/solve` 메타프롬프트 모드의 Huang et al. 2024 근거와 동일).

## §2 에이전트별 eval 차원 (약점 분류 기준)

| 에이전트 | eval 차원 |
|----------|----------|
| coder | 구현 정확성 · 단순성(과잉 X) · 범위 준수(요청 외 변경 X) |
| qa | 검증 철저성 · 게이밍 방어 · 호출부 누락 |
| searcher | 출처 품질 · 1차 출처 · 정확도 표기 |
| scout | 탐색 완전성 · 누락 파일 · 호출부 범위 |
| planner | 타당성 · 다중안 · 검증 가능 기준 |
| researcher | 비판성 · 근거 · 낙관 가정 회피 |
| docs | 형식 준수 · 정확성 |
| gitops | 커밋 규칙 · 파일 명시 |
| citation-verifier | 철회 게이트 · 원문 대조 정확성 · (디베이트 시) 편향 회피 · 균형 |
| tutor | 문항 근거 정확성(notes 인용 일치) · 유형 혼합 준수(숫자·단답 포함) · 정답 누설·전사 방지 · 설명 사다리 준수 · NEEDS_SEARCH 상한 준수 |

> **자동 기록의 차원·역할 귀속 규칙** (코드 `scripts/t41-append.sh --from` 과 일치하며, §1·§2 표와 다르면 이 줄이 우선한다. 위 §2 표의 차원은 사람이 수동 기록할 때의 분류이고 자동 기록은 구현 정확성·범위 준수·결과 실패 3종만 쓴다): qa·reviewer·security의 FAIL/REJECT → 주체 coder·구현 정확성, BLOCKED/NEEDS_CONTEXT → 낸 에이전트·범위 준수, 그 밖 → 자기 자신·결과 실패. 신호에 `target=<역할>` 이 있고 유효 역할이면(main·general-purpose 포함) 위 주체를 그 역할로 덮고 차원은 그대로 둔다. 같은 role/dim/signal은 10분 안 1회만 기록.

## §3 프로세스 (평가 → 축적 → 개선)

1. **판정**: 작업 종료 시 §1 신호 발생 여부 확인 (실패 시에만)
2. **축적**: mem0 T41 저장 (`agent_role` + `weakness_dim` + 신호) + `_audit/history.md`에 `T41: {role}/{dim}` 1줄 append — mem0 외부 저장만으로는 파일 기반 감사가 실행 흔적을 확인할 수 없다 (2026-08-15 감사 사각 교정). 파일 기록은 `bash ~/.claude/scripts/t41-append.sh <role> <dim> "<signal>"` 스크립트로 남기고(훅이 자동 호출하며 같은 스크립트가 `_evolve/candidates.tsv` 에 후보 1행도 적는다) 계수는 `grep -c 'T41:' _audit/history.md` 명령으로 한다.
3. **분석**: `agent_role`별 동일 약점 **3회+** — 검출은 세션 시작의 `T41_REPEAT: <role>/<dim> ×N` 경보(로그 계수, 최근 30일 창, `scripts/harness-usage-check.sh`)가 하고, 채택 판정은 `scripts/agent-crosscheck.sh`로 transcript 대조 후 main이 낸다(§1.5)
4. **개선 제안**: 해당 `agents/{name}.md`에 회피 가이드 추가 제안 (`learner.md § 반복 패턴 → 산출물 3택`)
   - **구조 전환 게이트 (2026-07-13 이식 — EvoPolicyGym, arXiv 2607.02440)**: 같은 약점에 대한 문구·임계값 수정(파라미터 조정)이 2회 무효였으면 3회째는 조정 반복 대신 **구조 변경**(역할 분리·도구 재배정·게이트 신설·에이전트 분할)을 제안 — 잘못된 구조는 조정으로 구제되지 않는다는 실측 근거.
5. **게이트**: harness-bench Tier-1 → (Tier-2 blind A/B은 QUARANTINED·P2 미활성 — 현재 Tier-1 통과 후 사용자 승인, `rules-lazy/learner.md` § 제안 흐름)
6. **반영**: 사용자 승인 시 agent.md Edit
7. **재평가**: 반영 커밋 해시는 대장 note 에 남긴다(커밋 메시지의 `Candidate: <id>` 트레일러가 post-commit 으로 `commit=<해시>` 를 적거나, 스킬이 `candidates-append.sh set <id> accepted --note commit=<해시>`). 미결 T41 후보가 있으면 usage-check 가 하루 1회(`T41_REPEAT` 여부와 무관) 그 후보 note 에 `effect:quiet n_spawn=X` 또는 `effect:recurred k=Y` 를 사실로 적는다(시계는 learner.md 만료 시계 표). `effect:recurred` 비고 행은 7일 만료에서 제외되고, 이미 만료된 후보가 재발하면 생성일이 37일(만료 7일 + 30일) 지난 뒤에 새 행으로 다시 들어온다(2026-10-17 개정 4). accepted 뒤에는 effect 비고를 쓰지 않고 감사의 hit 정의(`skills/harness-audit`)로 넘어간다. **종결은 침묵이 아니라 사람이 남긴 note 기록**이다. 판정은 `/learn-from-feedback` 에서 사람이 하고, 훅은 상태를 바꾸지 않는다(14일 `T41_REPEAT` 무발화여도 자동 종결 없음). `effect:recurred` 면 구조 전환 게이트(4단계)로 올린다. 반영했는데 계속 울리는 축은 «문구를 고쳐 될 일이 아니었다»는 실측 증거다

## §4 안전장치
- 자동 Edit ❌ — 항상 사용자 승인.
- 성공 작업은 기록 안 함 (약점만).
- 동일 약점 거절 3회+ → 영구 제외 마킹.
- 약점 귀속이 모호하면(신호가 여러 에이전트 가능) 2~3 후보 제시 후 사용자 확인.
