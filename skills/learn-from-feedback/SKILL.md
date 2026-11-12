---
name: learn-from-feedback
description: Use when 사용자 교정 패턴 자동 분석. Mem0 feedback 카테고리 N회+ 누적 시 룰 후보 제안. 명시적 호출 또는 세션 시작(T03) 확인 시 자동 트리거.
model: inherit
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
> **후보 입력은 이제 기계 기록이다**: pattern-detect.sh → T40, correction-detect → T12, spawn-log → t41-append.sh → T41 이 각각 `candidates.tsv`에 `status=pending` 행을 쌓고, 이 스킬은 그 행의 상태만 갱신한다(§ 후보 상태 집합) — 훅이 없는 harness-audit·security 소스만 예외로 이 스킬이 직접 행을 추가한다(§ 실행 순서 3).
> **상세 흐름**: `~/.claude/rules-lazy/learner.md` § 자동 패턴 분석

## 실행 순서

0. **시작 정리(판정 전)**: `bash scripts/candidates-append.sh expire --older-than-days 7` 를 1회 호출한다(SessionStart 가 이미 돌렸으면 0건). exit 4(효과 기록 전이라 만료 보류)면 세션을 다시 시작하거나 잠시 뒤에 다시 호출한다.
1. **감지 입력 수집**:
   - 로컬 빈도(토큰 0): `bash ~/.claude/scripts/pattern-detect.sh 3` → 반복 표면 1차 후보
   - Mem0 이력: feedback 카테고리(T12 교정 + T40 반복 패턴) + code_pattern 카테고리 agent-eval source(T41 에이전트 약점) 각각 검색
   - **harness-audit 결함 항목**(`_audit/history.md`의 최근 감사 FAIL·WARN, source=harness-audit)도 감지 입력에 포함한다 — 종전에는 감사 결과가 개선 루프에 연결되지 않았다(2026-08-25 교차감사 반영)
   - **중복 제거**: 같은 `event_id`를 가진 T12·T41 레코드는 1건으로 합친다(`rules-lazy/agent-eval.md` §1.5)
   - **분모 교차 대조(MANDATORY — 7라운드 렌즈3: 의무만 있고 실행 단계가 없었다)**: T41 약점 집계에 `_audit/agent-spawn.log`의 `post` 수를 분모로 쓰기 전에 main이 `bash ~/.claude/scripts/agent-crosscheck.sh`를 실행한다(`rules-lazy/agent-eval.md` §1.5와 같은 스크립트). 계수 규칙·판정 임계·기록은 **스크립트 헤더가 유일 정본**이라 여기에 복제하지 않는다(12라운드: 산문 두 벌은 4회 드리프트했다). exit 0(일치)일 때만 3회+ 게이트 진입, exit 2(분모 미상·불일치·기록 없음)면 보류. 게이트 진입 직전 `agent-crosscheck.sh latest` exit 0을 재확인하고(2026-10-17: 마지막 일치 행이 7일을 넘으면 `stale` 로 exit 2 이고, SessionStart 가 7일 초과를 보면 `--auto` 로 새 행을 백그라운드에서 만든다) 그 `latest: …` 출력 원문을 후보 제안에 인용한다(인용 없는 진입은 자기선언으로 무효 — 13라운드 렌즈3). 파일 기록은 `bash scripts/t41-append.sh <role> <dim> "<signal>"` 스크립트로 남기고 계수는 `grep -c 'T41:' _audit/history.md` 명령으로 한다.
2. **시간 순 정렬** + 키워드 클러스터링 — pattern-detect 1차 후보를 **LLM 의미 묶음**(표면 다른 같은 의도 통합)
   - 분류 렌즈 6종으로 신호를 훑는다: 마찰점 / 교정 / 반복 패턴 / 발견 / 스킬 갭 / 문서 갭 (아이디어 출처: alexknowshtml/claude-skills `reflect` — 무라이선스 레포라 재작성. 우선순위는 "매일 겪는 마찰 > 있으면 좋은 것")
3. **동일 패턴 3회+ 검출** → 후보 생성 (룰 / 스킬 신설 / 기존 스킬 편입 — T40 자가진화)
   - 교정 패턴 → 룰 후보. 중립적 반복 패턴(요청·작업방식) → `rules-lazy/learner.md § 반복 패턴 → 산출물 3택` 기준으로 룰/스킬신설(quick-skill)/편입 분류
   - **Lt budget**: 한 사이클 후보 수 ≤K개(기본 K=4, 이전 사이클 채택률에 따라 cosine decay floor=2)로 클립 — 후보 과잉 억제
   - **즉시 후보화 예외**: harness-audit·security 렌즈의 **높음 결함**은 "3회+"를 기다리지 않고 1회에 후보로 올린다(보안 FAIL을 반복 문턱에 묶어 두면 영구 방치된다 — 2026-08-25 검수 반영)
4. **사용자 승인 형식 출력** (learner.md § 룰 후보 출력 형식 준수) + **후보 레지스트리 상태 갱신(MANDATORY)**: `~/.claude/_evolve/candidates.tsv`(gitignored, 기기 로컬, 헤더 부재 시 `bash ~/.claude/scripts/setup-harness.sh` 가 만든다)의 기존 행을 찾아 `status`(§ 후보 상태 집합)만 갱신한다 — 새 행 추가는 훅(T12/T40/T41)이 이미 하므로 이 스킬은 하지 않는다(예외: 훅이 없는 audit/security 소스는 위 3단계 즉시 후보화에서 이 스킬이 직접 추가). `bench_id`는 벤치를 시작할 때(`harness-bench.sh init` 호출) 이 스킬이 발급해 `bash ~/.claude/scripts/candidates-append.sh set-bench <후보id> <bench_id>` 로 적는다(pending 계열만). T03의 "[개선 후보 N건 …]" 표시와 7일 경과 판단은 Mem0가 아니라 이 파일을 정본으로 센다(세션을 넘어 N을 셀 정본이 없던 결함 교정)
5. **채택 게이트 (2-tier — 설계)**:
   > **상태 (2026-07-17)**: Tier-2 blind A/B **자동활성은 P2 미활성** (스크립트 인프라는 구현됨, 활성화 전 재설계 필요 — `rules-lazy/learner.md` § 제안 흐름). **현재 운영**: Tier-1(exit 0) 통과 → 아래 Tier-2 대신 **사용자 승인**으로 연결. Tier-2 절차는 부록.
   - **Tier-1**: 후보가 `pending`에서 벤치 대상이 되면 이 스킬이 `harness-bench.sh init`으로 `bench_id`를 발급하고 status를 `pending-bench`로 올린 뒤 `bench/<후보id>` 임시 브랜치에 변경을 적용한다(Before=`HEAD`·After=그 브랜치 — 승인 전 벤치 순환 해소, § 후보 상태 집합). `harness-bench.sh gate <bench_id>` → exit 0이면 status를 `pending-approval`로 올리고 Tier-2 진입. **exit 1만 REJECT**(status=`rejected`). exit 2(잠정 n<3·metric 누락)는 REJECT가 아니라 `pending-bench`로 레지스트리에 유지하고 사이클을 더 쌓는다(2026-08-25 정정 — 종전 "1/2 REJECT"는 벤치 대기 후보를 거절로 만들었다).
   - **Tier-2 blind A/B · slow update · G5 kill switch**: 비활성(P2), 설명 전문은 파일 끝 § 부록: 비활성 절차.
   - **zero-sum 원칙 (범위 확장 2026-08-25)**: 상시 로드 파일(CLAUDE.md·`rules/*.md`)에 바이트를 더하는 **모든 산출**(룰 문장·스킬 포인터·에이전트 목록 행·라우팅 행·사건 회고 문장·HARD GATE 승격문) 전에 토큰 예산을 점검한다. `zerosum` 서브커맨드는 비활성(P2, 부록)이고 집행 지점은 아래 커밋 훅이다. 종전엔 "룰 추가"만 대상이라 스킬 신설·에이전트 증설·회고 문장이 검사 없이 상시 파일을 불렸다.
     → 초과 시 초과량·제거 권장량 출력 + 제거/병합 후보를 사용자에게 제시 (자동 선정 없음). **한도 초과는 경고만 하고 커밋을 막지 않는다**(2026-10-01 사용자 지시: «상시 규칙은 한도 넘어도 돼, 넘으면 그때 최적화 다시 진행». 08-25 의 WARN→FAIL 승격을 번복) — 집행 지점은 커밋 훅 `scripts/ci-gate-commit.sh`(CLAUDE.md·rules/*.md 합계 > 75,000B면 경고 출력, 커밋은 진행)이라 learner 경로든 감사 대응 직접 Edit이든 같은 경고를 탄다. 초과분은 `harness-audit` Step 1.5 다이어트 사이클에서 따로 줄인다. **사전 확인은 증가분을 넣어서**: 현재 합계 + 후보 편집의 추가 바이트가 75,000B 이하인지 Edit 전에 계산한다(합계만 보는 인자 없는 검사는 한도 직전에서 무력). 대상은 실제 상시 주입 파일(CLAUDE.md·`rules/*.md`)이며 AGENTS.md는 주입되지 않으므로 제외(미러 갱신은 정본 편집에 따라옴).
     → 사건 회고·근거·경위는 상시 파일이 아니라 `rules-lazy/`·`knowledge/`에 두고 상시 파일에는 포인터 한 줄만(헌법화 다이어트 자격 규칙 — `knowledge/harness/constitution-diet-rules.md`)
6. **거절 시** → Mem0에 "learner-rejection" source로 기록
7. **반영 후 종결(T41 후보)**: 반영 커밋을 `Candidate:` 트레일러(또는 `set <id> accepted --note commit=<해시>`)로 대장에 남기면 그 후보는 accepted 가 된다. accepted·rejected·expired 는 최종 상태이고 되돌림은 사용자가 대장을 직접 고친다. 아직 미결인 T41 후보의 종결 판정은 **침묵이 아니라 사람이 남긴 note 기록**으로 한다. usage-check 가 미결 T41 후보가 있으면 하루 1회(T41_REPEAT 여부와 무관) 그 후보의 note 에 `effect:quiet n_spawn=X`(같은 역할 최근 14일 소집 수) 또는 `effect:recurred k=Y`(생성일 이후 같은 축 재발 수)를 사실로 적어 두므로, 이 스킬은 그 수치를 보여 주고 사용자가 `set <id> accepted|rejected --note <판정 한 줄>` 로 닫는다(14일 침묵 자동 종결은 없다). effect 비고는 **미결 T41 후보에만** 붙고, accepted 가 된 뒤의 효과 추적은 `skills/harness-audit/SKILL.md` 의 hit 정의가 맡는다.

## 후보 상태 집합 (정본)

| status | 의미 | 전환 주체 |
|---|---|---|
| `pending` | 훅이 만든 원시 후보, 미검토 | pattern-detect·correction-detect·t41-append(훅) |
| `pending-bench` | 벤치 측정 중 — `bench/<후보id>` 임시 브랜치에 변경 적용, main 미반영(승인 전) | 이 스킬이 `bash scripts/candidates-append.sh set <id> pending-bench` (`harness-bench.sh init` 로 `bench_id` 발급 뒤) |
| `pending-approval` | Tier-1 게이트(exit 0) 통과, 사용자 승인 대기 | 이 스킬이 `harness-bench.sh gate` exit 0 을 확인한 뒤 `candidates-append.sh set <id> pending-approval` (gate 는 상태를 바꾸지 않는다) |
| `accepted` | 판정 채택(반영 증명은 비고 `commit=<해시>`) | 이 스킬 `set <id> accepted [--note <텍스트>]`, 또는 커밋 트레일러 `Candidate: <id>` 가 있으면 post-commit 훅이 `--note commit=<해시>` 로 |
| `rejected` | 사용자 거절 또는 Tier-1 exit 1 | 이 스킬 `set <id> rejected [--note <텍스트>]` |
| `expired` | 7일 넘게 `pending` 이던 후보를 닫은 상태(삭제 아님, 최근분 유지, 미결 집계에서 빠짐). **사람 판정·`commit=` 같은 보호 note 가 있는 행은 만료하지 않는다**(검토 중 표시. 기계 비고인 `kw=`·`effect:quiet` 로 시작하는 note 는 보호하지 않아 만료되고, `effect:recurred` 는 만료에서 제외된다) | SessionStart 의 `harness-usage-check.sh` 가 `candidates-append.sh expire --older-than-days 7` 를 자동 호출 (2026-10-17, 수동 `[--dry-run]` 가능) |

> **note 열 (2026-10-17)**: 대장 7번째 열. 요약(중복 판정 키)은 건드리지 않고 처리 기록만 담는다: T12 는 `kw=<교정 키워드>`, 반영 커밋은 `commit=<해시>`, usage-check 가 미결 T41 후보가 있으면 하루 1회 쓰는 `effect:quiet n_spawn=X` · `effect:recurred k=Y`. 쓰는 길은 `set <id> <status> --note <텍스트>`(상태+note 한 잠금 호출) 또는 `set-note <id> <텍스트>`(note 만 교체) 뿐이고 120자로 잘린다. 훅은 `set-note-batch --only-machine` 만 쓰며, 잠금 안에서 비고가 비었거나 `kw=`·`effect:` 로 시작할 때만 갱신한다. 사람이 판정한 기록과 `commit=` 은 훅이 덮어쓰지 않는다.

> **accepted 뒤의 걸음**: 승인은 커밋 지시가 아니다. 사용자가 «커밋해» 라고 하면 `skills/commit/SKILL.md` 로 커밋한다(룰·스킬·에이전트·스크립트를 바꾸는 `feat:` 커밋과 신설을 담은 `fix:`·`refactor:` 커밋은 `Intent:` 줄 필요). `bench/<후보id>` 임시 브랜치의 변경을 main 에 합치는 방식은 사용자에게 확인한다. 커밋 뒤에는 `rules-lazy/peer-session-messages.md` § 하네스 변경 전파에 따라 같은 서버의 다른 세션에 알린다.
>
> **커밋 ↔ 후보 연결 (2026-10-17, 결정 A1)**: 사용자가 «커밋해» 지시에 후보 id 를 적으면 main 이 커밋 메시지 끝에 `Candidate: <id>` 줄을 넣는다(후보와 무관하면 `Candidate: none`). id 를 적지 않았으면 main 이 임의로 넣지 않는다. 훅은 id 존재·미결 상태·규칙 경로(agents·rules·rules-lazy·skills·CLAUDE.md) 변경을 확인하고, 통과하면 post-commit 이 `set <id> accepted --note commit=<해시>` 를 실행한다. 이미 accepted 로 닫은 id 를 나중에 커밋하는 흐름이면 상태는 그대로 두고 비고에 `commit=<해시>` 만 붙인다(기존 비고가 있으면 `; commit=<해시>`). 어긋나면 경고만 하고 커밋은 막지 않으며, 이때는 이 스킬이 `set` 으로 직접 잇는다.

## 트리거 조건

| 조건 | 우선순위 | 처리 |
|------|---------|------|
| 사용자 명시적 호출 (`/learn-from-feedback`) | 높음 | 즉시 실행 |
| 세션 시작(T03) 시 main 확인 | 중간 | SessionStart 훅이 자동 주입하는 `harness-usage-check.sh` 의 `CANDIDATES_PENDING` 경보를 읽어 반복 후보 발견 여부를 판단한다(모델이 `pattern-detect.sh` 를 직접 실행하지 않는다 — `rules/mem0-auto.md` T03). **미반영 후보 표시(MANDATORY, 2026-08-25)**: 승인 대기(Tier-1 PASS) 후보와 **아직 벤치를 못 돈 후보**(잠정 n<3 포함)가 있으면 첫 작업성 응답에 `[개선 후보 N건 — 승인 대기 a·벤치 대기 b — /learn-from-feedback]` 1줄을 반드시 붙인다(기록만 쌓이고 발사가 안 되는 열린 루프 차단; 반영 자체는 여전히 사용자 승인). **digest (2026-10-17 결정 B1, 2026-11-12 개정)**: `CANDIDATES_PENDING` 아래에 하루 1회 미결 후보 5건(id·유형·요약 60자)이 `·` 로 시작하는 줄로 따라온다. 순서는 내용 있는 T41(재발 축 먼저) > T12 > 그 밖(T40·내용 없는 T41)이고 같은 급에서는 오래된 순이며, 미결이 5건을 넘으면 날짜에 따라 회전한다. digest 가 뜬 세션에서 main 은 **첫 작업성 응답의 끝에서 결정 팝업 하나**(`mcp__decision-popup__ask`)로 판정을 묻는다. 후보마다 한 항목을 두고 선택지는 accepted · rejected · 보류 셋이다. 모바일 모드면 같은 내용을 글로 설명하고 AskUserQuestion 으로 묻는다. 답이 오면 accepted · rejected 는 `candidates-append.sh set <id> <상태>` 로, 보류는 상태가 아니라 `candidates-append.sh set-note <id> "hold: 사유"`(만료 보호)로 반영한다(훅은 상태를 바꾸지 않는다) |
| 주기적 (Cron) / 수동 트리거 | 낮음 | **slow update** (T3.1) **P2 미활성**: `scripts/harness-evolve.sh` 가 QUARANTINED 라 실행하지 않는다. 활성 시 이전 vs 현재 룰셋 회귀 점검 → 회귀 발견 시 사용자 경고 |

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
정본은 `~/.claude/_usage/candidates-reviewed-last` 의 mtime(30일 미판정 경보 `CANDIDATES_UNJUDGED_30D` 도 이 마커 기준이며 7일 자동 만료와는 별개)이다. 사람 판정인 `candidates-append.sh set` 만 이 마커를 갱신하고(훅·자동 경로의 `set … --machine` 은 마커를 갱신하지 않는다, 사람 판정만), 자동 만료(`expire`)와 `set-note` 는 «분석» 이 아니라서 갱신하지 않는다(2026-10-17. 종전 «candidates.tsv 의 갱신 시각» 은 훅이 행을 추가할 때마다 바뀌어 기준이 못 됐다). 아래 Mem0 기록은 크로스 머신 백업일 뿐 판정 근거가 아니다(2026-08-25 이중 정본 정리):
```
add_memory(
  text="[YYYY-MM-DD HH:MM] [claude-global] learn-from-feedback 분석 완료 — 검출 N건 / 제안 M건",
  metadata={"category": "context", "source": "learn-from-feedback"}
)
```
이 메모는 크로스 머신 백업이며 30일 미판정 경보 판단에는 쓰지 않는다(정본은 위 `candidates-reviewed-last`).

## 부록: 비활성 절차

> 실행 순서 5단계에서 옮긴 설명 전문이다(삭제 아님). `scripts/harness-evolve.sh` 는 2026-07-17 QUARANTINED 라 아래를 실행 절차로 쓰지 않는다(활성 전 재설계 필요).

- **Tier-2 (blind A/B, P2 미활성)**:
  a. `regression-blind.sh prepare <candidate_edit_file> <work_dir>`
  b. `regression-blind.sh run <work_dir> <suite_file>` 는 사용자가 직접 실행한다.
  c. 사용자 blind 선택 완료 후 `regression-blind.sh verdict <picks_file>`
  d. **verdict ACCEPT(exit 0)** → 채택 (사용자 blind 선택=승인으로 간주) → Edit 실행
  e. **REJECT/INCONCLUSIVE** → 채택 보류, Mem0에 "learner-rejection" source로 기록
- **zero-sum `zerosum` 서브커맨드 (P2 미활성)**: `harness-evolve.sh zerosum` 을 절차로 쓰지 않는다. 집행 지점은 실행 순서 5단계의 커밋 훅 `scripts/ci-gate-commit.sh` 이다.
- **slow update (T3.1, P2 미활성)**: 활성 시 설계는 이전 룰셋(`git -C ~/.claude archive <sha>` 로 복원)과 현재 룰셋을 같은 suite로 돌려 결과를 비교하고 회귀가 나오면 case 목록과 함께 사용자에게 경고하는 흐름이다. 회귀가 없으면 현재 룰셋을 유지한다. 자동 롤백·자동 제거는 어느 경우에도 없다(판정·제안만, 불변식 1).
- **G5 kill switch (주기적 안정성 점검, P2 미활성)**: `killswitch` 도 절차로 쓰지 않는다. 활성 시 설계는 이력 기록에서 ROLLBACK 판정이 나오면 사용자에게 이전 sha 롤백을 제안하는 흐름이다.
