# 컨텍스트 관리 규칙

> **로드 시점**: compact 또는 clear 실행 전, 장기 세션 운영 시

## 자동 compact

### autocompact 발동 조건 (2026-07-19 근원 규명·수정)

`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=75`는 **단독으로는 1M 컨텍스트 창 세션(예: 로컬 Opus 4.8/Fable 5)에서 무효**다 — 공식 env-vars 문서 실측 확인. 원문 취지: 1M 컨텍스트 창 세션(예: 로컬 Opus 4.8) 등에서는 override 값과 무관하게 "대화가 모델 context limit에 도달할 때" autocompact가 발동한다. override가 실제로 임계를 낮추려면 **`CLAUDE_CODE_AUTO_COMPACT_WINDOW`를 함께 설정**해야 한다 — 이 변수가 statusline `used_percentage`의 분모(denominator)를 모델 실제 윈도우에서 분리해, override의 % 계산이 그 분모 기준으로 동작하게 만든다.

- **현재 설정 (settings.json `env`)**: `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=75` + `CLAUDE_CODE_AUTO_COMPACT_WINDOW=1000000` → 분모 1M 고정 → 75%가 **statusline 750K(=75%)** 에서 발동. 이전에는 window 변수 부재로 override=75가 **줄곧 무효**였고, 그래서 이 세션이 86%까지도 미발동이었음(실측). 이 조합으로 수정.
- override는 임계를 **낮추기만** 가능(높일 수 없음). override 단독 발동은 200K 컨텍스트 창 모델(예: Sonnet 4.6/Opus 4.6)·클라우드 세션 한정 — 1M 컨텍스트 창 세션(예: 로컬 Opus 4.8/Fable 5)은 window 변수 필수.
- **정합 조건**: "statusline 75% = compact"가 성립하려면 window 값이 statusline이 쓰는 분모와 같아야 한다. statusline(claudenews HUD)이 다른 분모를 쓰면 발동점이 어긋난다 — 다음 장기 세션에서 statusline 75% 근처 미발동 시 이 값을 재점검.

- `~/.claude/CLAUDE.md`의 Compact Instructions 섹션 기준 적용

## § 1M Context 세션 입력 토큰 관리 (MANDATORY)

> 현재 모델이 `[1m]` suffix가 붙은 1M context 변형일 때(버전 무관), 입력 토큰 누적 200K 돌파 시 Extra usage 과금 미활성 상태면 API 에러 발생. autocompact 발동 조건 자체는 위 § 자동 compact 참조(override 단독 무효 → `CLAUDE_CODE_AUTO_COMPACT_WINDOW` 필요). 발동하더라도 대용량 단일 반환은 순간적으로 임계를 넘길 수 있으므로 아래로 별도 방어한다.

### ⚠️ `[1m]` 세션 — autocompact보다 200K 에러가 먼저 터질 위험

`[1m]` 변형은 200K를 넘겨 1M 영역에 진입할 수 있으나, Extra usage 미활성 시 200K 경계에서 API 에러가 autocompact 발동보다 **먼저** 터질 수 있다:
- window를 1M로 두면 statusline 분모가 1M이 되어 75% 발동점이 **750K로 밀린다** — 200K Extra-usage 경계보다 뒤이므로, Extra usage가 없으면 compact 발동 전에 에러가 먼저 난다. **`[1m]` + Extra usage 미활성 머신에서는 `CLAUDE_CODE_AUTO_COMPACT_WINDOW`를 `200000`으로 낮춰** 200K 전에 compact가 돌게 하거나, 아래 실시간 추적 수단을 병행한다. settings.local.json(없으면 settings.json)의 model 값에 `[1m]` 이 없으면 이 경합에 해당하지 않으므로 window=1M 을 유지한다.
- **autocompact만 믿고 장기 세션 운영 금지** — 반드시 아래 실시간 추적 수단 병행

### 실시간 추적 수단 (MANDATORY)

autocompact 미발동 리스크를 상쇄하기 위해 아래 수단을 병행한다:

| 수단 | 용도 | 사용 시점 |
|------|------|----------|
| `/context` 슬래시 커맨드 | 현재 세션 토큰 사용량 실측 조회 (**주 수단**) | 장기 작업 시작 전 / subagent spawn 전 / 대용량 Read·Write 전 / 주기적 점검 |
| StatusLine 표시 | ⚠️ 현재 settings.json statusLine은 claudenews HUD(`~/.claude/hud/claudenews-hud.mjs`)가 점유 — ctx % **미표시**. ctx % 상시 표시가 필요하면 대체 statusline `~/.claude/scripts/statusline-context.sh`로 statusLine 필드를 교체 (claudenews HUD와 동시 사용 불가) | claudenews 미사용 머신에서만 교체 권장 |
| `/compact` 수동 선행 | 임계 근접 시 사전 압축 | 150K 추정 돌파 + 대용량 작업 예정 시 |

**MANDATORY 체크포인트** (⚠️ `/context`·`/compact`는 슬래시 커맨드 = **사용자만 실행** — Claude는 자동 실행 불가, § 자가 트리거 한계). Claude는 아래 시점에 사용자에게 `/context` 실행을 **요청**하고 결과를 받아 판단):
- 장기 세션 진입 후 첫 대용량 작업(Read/Write 100줄+ 또는 subagent 3개+) 전 → 사용자에게 `/context` 요청해 현재 상태 확인
- `/context` 실측 150K(15%) 돌파 시 → 사용자에게 "/compact 선행 권장" 1줄 보고 — 현 statusline은 ctx %를 표시하지 않으므로 StatusLine 감시에 의존 금지
- 180K+ 도달 감지 → memory-write.md Step 1~6 + Mem0 T02 + handover.md 강제 + 사용자에게 `/compact` 즉시 요청

### 모델 식별

세션 시작 시 settings.local.json(없으면 settings.json)의 model 값 확인(시스템 프롬프트의 표시 ID 는 `[1m]` 접미를 보여 주지 않는다):
- `[1m]` suffix 포함 → "1M 세션"으로 분류, 아래 임계 관리 발동
- 컨텍스트 창 1M(비-`[1m]`이어도 실제 창이 1M) → override 단독 무효, `CLAUDE_CODE_AUTO_COMPACT_WINDOW` 필요 (예: 로컬 Opus 4.8/Fable 5) (§ 자동 compact)
- 컨텍스트 창 200K 경계 모델·클라우드 세션 → override 단독으로 75% 발동 (예: Sonnet 4.6/Opus 4.6)

### 입력 누적 임계 관리

| 임계점 | 상황 | 조치 |
|--------|------|------|
| ~150K | 정상 범위 | 감시만 |
| 150~180K | 위험 영역 진입 | 다음 큰 도구 호출(≥10KB 반환) 전 compact 선행 권장 |
| 180K+ | 1M 진입 임박 | memory-write.md Step 1~6 + Mem0 T02 + handover.md + /compact 강제 실행 |
| 200K+ | 1M 영역 진입 | Extra usage 없으면 API 에러. 진입 전 방어가 유일한 해결책 |

### 1M 진입 에러 복구 프로토콜

"Extra usage is required for 1M context" 에러 발생 시:

1. 사용자에게 1줄 보고: "main 입력 누적 200K 초과 — 1M 진입. compact 필요"
2. 현재 미기록 합의·작업 상태를 즉시 short-term에 append (memory-write.md Step 1~6)
3. Mem0 T02 세션 상태 저장 (MANDATORY)
4. short-term/handover.md 작성
5. 사용자에게 /compact 또는 /model 전환 요청
6. compact 완료 후 작업 재개

### 대안 경로

1M 영역 진입을 피할 수 없는 경우 사용자에게 아래 3가지 제시:
- `/compact` 실행 (무료, main 압축)
- `/model` 표준 컨텍스트 모델로 전환 (무료, 1M 요구 제거)
- `/extra-usage` 활성화 (추가 과금)

### 자가 트리거 한계

`/compact` 등 슬래시 커맨드는 **사용자만 실행 가능** — Claude는 자동 실행 불가. Claude가 할 수 있는 것은 "사용자에게 요청 보고"까지. 따라서 180K+ 도달 감지 시 Claude는 다음 도구 호출을 **중단하고** 사용자에게 `/compact` 실행 요청 + 승인 대기한다.

(2026-04-19 1M 가드레일 신설)

## /compact 수동 사용 권장 시점
아래 조건 중 하나라도 해당하면 작업 전 수동 compact 권장:
1. 하나의 실험/태스크가 완전히 끝나고 다음 태스크로 전환 시
2. teammate 팀 해산 직후 (팀 결과 요약 보존 필요)
3. 컨텍스트 70%+ 상태에서 장기 세션 지속 예정인 경우
4. **긴 코드/스크립트 생성 전 컨텍스트 50%+ 상태** (TikZ, matplotlib, LaTeX 등 100줄+)
5. 수동 실행 시 반드시 지시 명시: `/compact 실험 config와 수정 내역 보존, 도구 출력 요약`

**Phase 경계 위생 (2026-08-06 이식 — 출처: mattpocock/skills `ask-matt`, MIT)**: 작업 phase가 끝날 때마다 용량과 무관하게 ①그냥 이어가기 ②/clear ③handover 후 새 세션 ④subagent 위임 ⑤/compact 5택을 의식적으로 고른다 — 원문 요지: "이어가기가 정답인 경우가 가장 적다". 75% 트리거(용량 기준)의 보완 축(작업 경계 기준).

### /discuss 활성 중 compaction 주의 (MANDATORY)

`/discuss` 진행 중 compaction이 발생하면 tmux pane이 소멸하거나 subagent 컨텍스트가 손실될 수 있다.

```
/discuss 활성 + 컨텍스트 70%+ 감지 시:
  → 현재 Round 완료까지 대기 (Round 도중 compaction 금지)
  → Round 완료 → discuss-state.md에 결과 저장 확인
  → 저장 완료 후 compact 실행
  → 재개 시: discuss-state.md 로드 → 다음 Round 진행
```

- Round 도중 compaction: 해당 Round 의견 손실 → discuss-state.md에 저장된 마지막 Round부터 재시작
- compact 직전 저장 지시: `/compact discuss-state.md 보존, 이전 라운드 기록 유지`

### compact 직전 필수 절차 (MANDATORY)
`rules-lazy/memory-write.md` § "Compact / Clear 전 필수 절차" 참조 (Step 1~6 순서 준수)

### § Mem0 세션 복구 안전망 (MANDATORY — compact/continuation 시 자동 실행)

#### Step 2.5 — compact 전 Mem0 백업 (memory-write.md Step 1~6 사이에 삽입)

compact 실행 직전 반드시 Mem0에 세션 상태를 저장한다 → `mem0-auto.md` T02 참조

```
compact 직전 필수 절차 (순서 준수):
  Step 1~2: 미기록 합의 기록 (기존)
  Step 2.5: Mem0 백업 (MANDATORY — 스킵 금지)
    → mem0-auto.md T02 실행: 진행률+활성 결정+config+TODO 포함
    → Mem0 불가 시: mcp-fallback-mem0.md § Mem0 Fallback 적용 (handover.md만으로 진행)
  Step 3~6: handover.md 작성 + 만료 정리 + compact (기존)
```

> 자동 compact 는 이 순서를 밟을 턴 없이 발동할 수 있다. PreCompact 훅 `scripts/precompact-handover-check.sh` 가 cwd 저장소의 `short-term/handover.md` 가 60분을 넘으면 경고 한 줄을 낸다(차단 없음 — compact 를 막으면 세션이 진행 불능이 된다).

#### Step 7 — 세션 시작 시 Mem0 Smart Retrieval 3축 복원

새 세션 또는 continuation 시작 시 3축 검색으로 이전 맥락을 복원한다 → `mem0-auto.md` T03 참조

```
세션 시작 시 복원 절차:
  1. handover.md 읽기 (존재 시)
  2. Mem0 3축 검색 (MANDATORY):
     History: search_memories(query="세션 상태 이전 작업 진행률", filters={"metadata": {"category": "context"}})
     Current: search_memories(query="활성 결정 합의 config", filters={"metadata": {"category": "decision"}})
     Future:  search_memories(query="다음 단계 TODO 예정 작업", filters={"metadata": {"category": "context"}})
  3. handover.md + Mem0 결과 교차 확인
  4. 충돌 시: Mem0(더 상세) 우선, 사용자에게 차이점 보고
```

- handover.md + Mem0 이중 안전망: 둘 중 하나만 있어도 복구 가능
- Mem0 불가 시: handover.md 단독 복구 + mcp-fallback-mem0.md § Mem0 Fallback 적용

### main이 75%를 감지한 경로에서 강제. 자동 발동은 PreCompact 경고만 (MANDATORY)

> **핵심**: main이 75%를 감지했을 때 Mem0 백업이 누락되면 다음 세션에서 복구 불가능한 컨텍스트 소실이 발생한다. 아래 순서를 **예외 없이** 준수한다. 자동 발동은 PreCompact 경고만 낸다.

#### 강제 순서 (위반 시 compact 실행 금지)

```
컨텍스트 75% 도달 감지
  → 사용자에게 1줄 알림: "75% 도달 — Mem0 백업 + handover.md 작성 후 compact 실행합니다"
  → Step A: mem0-auto.md T02 실행 (세션 상태 Mem0 add_memory)
            - 필수 포함: 진행률, 활성 결정, 사용 중 config, 미완료 TODO, 다음 시작점
            - 실행 주체: Haiku 위임 가능 (단순 Write)
  → Step B: memory-write.md § Compact / Clear 전 필수 절차 Step 1~6 실행
            - Step 3 handover.md 작성 완료 확인 필수
  → Step C: compact 실행 (**사용자가 `/compact` 실행** — 슬래시 커맨드는 Claude 자동 실행 불가, § 자가 트리거 한계. Claude는 Step A·B 완료 후 사용자에게 실행 요청)
```

#### 위반 금지 사항

- Step A(Mem0 백업)를 생략하고 compact 실행 — 금지
- Step B(handover.md 작성)를 생략하고 compact 실행 — 금지
- "컨텍스트가 빠듯해서 스킵"이라는 이유로 Mem0 백업 건너뛰기 — 금지
  (백업은 Mem0 add_memory 1회 호출 — 수백 토큰 규모이며 compact 실패보다 비용이 훨씬 낮음)

#### MCP 불가 시 예외 처리

- Mem0 MCP 미연결 → `rules-lazy/mcp-fallback-mem0.md` 적용 → handover.md + long-term 파일 기록으로 이중 백업 → compact 진행
- handover.md Write 실패 (권한·경로 오류) → 사용자에게 보고 후 수동 대응 지시 수신 → compact 보류

#### 컨텍스트 임계 초과 긴급 상황

컨텍스트 > 95% 돌파 시에만 Step A/B 병행 실패해도 compact 진행 허용 (응답 중단 방지). 이 경우:
- 사용자에게 "긴급 compact 진행 — 백업 일부 누락 가능성 있음" 보고
- 다음 세션 시작 시 `mem0-auto.md` T03 3축 검색 + handover.md 복구 시도
- 복구 실패 항목은 사용자에게 명시적으로 보고

#### 검증 체크리스트 (compact 직후 자기 점검)

- [ ] Mem0에 category="context" + source="compact_handover" 항목 신규 저장 확인
- [ ] short-term/handover.md 갱신 일자가 오늘로 기록됨
- [ ] 7일 만료 항목이 아카이브로 이동됨(SessionStart 정리 스크립트)
- [ ] MEMORY.md 인덱스 최근 갱신일 업데이트됨

### 긴 출력 생성 전 compact 흐름 (MANDATORY)
```
컨텍스트 체크 → 50%+ 이면 compact 선행 → 코드 생성 (Write 도구) → 실행 명령서 보고
```
- compact 없이 긴 코드를 응답 텍스트에 출력하면 토큰 한도 초과로 응답 중단 위험
- Write 도구로 파일 저장 시에도 컨텍스트가 높으면 compact 후 진행

## 세션 Continuation 시작 시 토큰 관리 (MANDATORY)

이전 세션이 컨텍스트 초과로 중단되어 auto-summary와 함께 재개될 때:

1. **즉시 작업 재개 금지** — system-reminder 로드만으로 이미 30~50% 소모 가능
2. **대용량 Write 예정 시** (≥200줄): summary 수신 직후 `/compact` 실행 후 작업 시작
   - `/compact` 지시: `"이전 세션 Current Work / Pending Tasks 핵심만 보존, 도구 출력 전체 제거"`
3. **재읽기 금지**: system-reminder에 이미 포함된 파일 내용 → Read 재호출 금지, 내용 그대로 재활용
4. **탐색 최소화**: 이미 파악된 파일 경로·코드 섹션은 재탐색 금지, 메모·summary에서 활용

### Continuation 판단 흐름
```
Continuation 세션 시작
  → 예정 작업 확인 (summary "Pending Tasks" 참조)
  → Write ≥200줄 예정?
      YES → /compact 선행 후 Write
      NO  → 바로 작업 재개 (불필요한 파일 읽기 없이)
```

## API 에러 방지 — 작업 세분화 규칙 (MANDATORY)

### 대용량 작업 분리 (응답 1개 = 대용량 산출 1개)
아래 **대용량 산출 작업**이 한 응답에 겹칠 때만 별도 응답으로 분리한다 (목적: 응답 토큰 한도 초과·API 에러 방지):
1. 100줄+ 파일 작성 (Write 도구)
2. 장시간 컴파일/빌드 실행 (Bash 도구)
3. 대량 QA 검수 (Agent 도구)
4. Confluence 업로드 (MCP 도구)

> 금지 예시: 한 응답에서 100줄+ Write + 컴파일 + 대량 QA 동시 실행
> **적용 제외 (정상 패턴 — 분리 불필요)**: 경량 오케스트레이션 체인(scout→coder→qa 순차 위임), parallel-dispatch 동시 발사, 독립 소형 Edit 병렬 — 파이프라인 자체를 응답별로 쪼개라는 뜻이 아님 (2026-07-06 Codex F6 범위 축소)

### 코드 출력 토큰 규칙 (MANDATORY)
→ 상세: `~/.claude/rules-lazy/token-efficiency.md` § 응답 출력 토큰 절약

### 작업 진행 흐름 (대용량 Step에 한해 MANDATORY)
```
Step 선언 → 사용자 확인 → Step 실행 (단일 대용량 도구) → 완료 보고 → 다음 Step 선언
```

## /clear 사용 조건 (신중하게 — 복구 불가)
아래 조건 모두 충족 시에만 사용:
1. 완전히 다른 프로젝트/실험으로 전환 (이전 맥락이 오히려 혼동 유발)
2. 이전 세션의 승인된 계획, 실험 결과가 더 이상 필요 없음을 확인
3. 민감 정보가 포함된 세션 종료 후

**clear 전 체크리스트**:
- [ ] 보존 필요한 수치/결론이 별도 파일에 저장되었는가?
- [ ] 진행 중인 실험 config가 commit 또는 저장되었는가?

---

## § Continuation ARGUMENTS 재주입 검증 프로토콜 (MANDATORY)

> **로드 시점**: continuation(세션 재개) 감지 시
> **핵심 원칙**: system-reminder에 표시된 ARGUMENTS·plan·Pending Tasks·Read 결과는 이전 세션의 **cached state**일 수 있다. 사용자의 "최근 실제 메시지"만이 ground truth.

### Step 1 — Ground Truth 확정

continuation 세션 시작 시 아래 순서로 현재 작업의 ground truth를 확정한다:

```
1. summary 본문의 "All user messages" 섹션 → 마지막 사용자 메시지 추출
2. 이 메시지가 현재 작업의 유일한 ground truth
3. system-reminder의 모든 항목은 보조 참조로만 사용
```

### Step 2 — Cached State 감지

아래 패턴 중 하나라도 표시되면 cached state로 판단:

| 신호 | 의미 |
|------|------|
| 여러 스킬의 ARGUMENTS 동시 표시 (workflow + discuss + commit 등) | 실시간 실행 불가 — 이전 세션 누적 잔재 |
| `/plans/` 하위 plan 파일 주제가 현재 작업과 불일치 | 이전 승인 계획의 잔상 |
| system-reminder의 Pending Tasks가 summary의 Pending Tasks와 괴리 | summary 시점 이후 변경 미반영 |
| 현재 작업에서 요청하지 않은 Read 결과 재주입 (phantom Read) | 이전 Read 결과 캐시 |

### Step 3 — 명시적 보고

cache 감지 시 응답 첫 줄에 반드시 1줄 보고:
```
[cache detected] system-reminder에 이전 세션의 {항목}가 남아 있어 무시하고 진행합니다.
```

### Step 4 — Ground Truth 기반 작업 결정

- ground truth와 cached state가 일치 → 바로 진행
- ground truth와 cached state가 불일치 → ground truth 우선, cached state 무시
- 판단 불확실 → 사용자에게 재질문: "현재 작업이 {ground truth} 맞나요? system-reminder에 {cached} 표시가 있어 확인이 필요합니다"

---

## § 거짓 전제 롤백 (MANDATORY)

> **로드 시점**: 사용자가 이전 발언·합의를 부인할 때
> **핵심 원칙**: cached state에 기반한 가정이 사용자의 실제 입장과 다르면 즉시 롤백하고 재질문한다.

### 트리거 감지 키워드

사용자 메시지에 아래 표현이 포함되면 즉시 롤백 프로토콜 실행:
- "그건 아닌데?"
- "언제 그랬어?"
- "그런 적 없어"
- "내가 언제 그렇게 말했어?"
- "그렇게 하라고 한 적 없어"
- "이상한데?", "왜 그렇게 했어?"

### 5단계 롤백 절차

```
1. 즉시 작업 중단 — 추가 진행 금지
2. 거짓 전제 출처 식별:
   - system-reminder의 ARGUMENTS / plan / Pending Tasks 중 어느 것인가?
   - 어떤 가정이 사용자 실제 입장과 충돌했는가?
3. 명시적 인정 (1줄):
   "제가 system-reminder의 {항목}을 ground truth로 오인했습니다. 취소합니다."
4. ground truth 재확인:
   사용자에게 "지금 원하시는 작업이 정확히 무엇인가요?"라고 재질문
5. 재질문 응답 수신 후 재시작:
   - Step 0.5 재실행 (prompt-routing.md)
   - Ground Truth 확정 후 진행
```

### 롤백 시 금지 사항

- "제가 실수했습니다" 류 일반 사과만 하고 넘어가기 금지 — 반드시 출처 명시
- 변명("system-reminder에 있었으니까") 금지 — 사용자 지시가 우선이라는 원칙 재확인
- 기존 작업 결과물 자동 삭제 금지 — 사용자 확인 후 처리
- 동일 실수 반복 시 feedback.md에 기록 → learner.md 트리거

---

## 도메인 전환 자동 compact 트리거 (planner 제안 B 적용 — MANDATORY)

> **목적**: 한 세션에서 코드 → 서칭 → 문서 등 작업 도메인이 바뀔 때 이전 도메인의 상세 결과가 다음 도메인에서 불필요하므로, 도메인 전환 시 자동 compact를 권장한다.

### 도메인 분류

| 도메인 | 키워드·트리거 |
|--------|------------|
| **code** | 코드 수정/작성, coder/scout/qa 위임 |
| **research** | 논문 검색, paper-read, researcher/searcher 위임 |
| **docs** | Confluence/Jira 작업, docs/confluence 위임 |
| **discuss** | /discuss 토론, planner+researcher teammate |
| **experiment** | wandb·Phase·실험 설계, experiment 스킬 |
| **git** | gitops 작업, /commit 스킬 |

### 전환 감지

직전 작업이 도메인 X였고, 새 사용자 요청이 도메인 Y(X ≠ Y)이면 도메인 전환으로 판정.

### 트리거 동작 (MANDATORY)

전환 감지 시 사용자에게 1줄 알림 + compact 권장:
```
[도메인 전환 감지: {X} → {Y}] 이전 도메인의 상세 결과는 {X}-handover에 보존됩니다. compact 권장.
```

### 자동 vs 수동
- 컨텍스트 60%+ 도달 + 도메인 전환 감지 → **자동 compact** 권장 (사용자 알림 후 진행)
- 컨텍스트 60% 미만 + 도메인 전환 감지 → **수동 알림만** (사용자 결정)

---

## Subagent 반환 누적 추정 (수동 휴리스틱)

subagent 반환이 세션 내 20회를 넘어가면 compact를 권장한다(35회+ 강력 권장). 자동 카운터는 미배선(2026-07-10 정합화 — 구 MANDATORY 표기는 실행 수단 없는 선언이라 폐지)이며, 실질 방어는 subagent 반환 1,500자 상한(`agent-routing-mcp.md`)과 75% autocompact이 담당한다.
