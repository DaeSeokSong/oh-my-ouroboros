---
name: intent
description: "Use when: 비자명 작업(실험·기능·하네스 feat) 착수 전 «의뢰서» intent.md 작성·교정·커밋. '/intent', '의뢰서', '왜 하는지부터 적자', /experiment Stage 0, /workflow 설계 전, /solve 메타프롬프트 승인 뒤. 플레이북 5항목+전제 1항목, 커밋이 다음 단계(plan.md)를 발화."
---

# /intent — 의뢰서(intent.md) 작성·교정·커밋 (2026-09-06 사용자 지시)

> **출처**: Anthropic AI-Native SDLC Playbook(2026-08, https://claude.com/blog/the-ai-native-sdlc-playbook · https://academy.claude.com/courses/ai-native-sdlc-playbook/capture-intent). 발안자가 Claude와 브레인스토밍한 결과를 **자기 말로 적은 proto-spec**이며, 제품 소유자가 교정한 뒤 커밋하고, 승인된 intent.md 가 다음 단계(spec·plan)를 발화한다. 이 스킬은 플레이북이 말한 «템플릿을 skill 로 인코딩»에 해당한다.
>
> **판단 근거 (왜 이 하네스에 필요한가)**: 하네스에는 계획 산출물(superpowers `writing-plans` → `docs/superpowers/plans/`)과 검수(qa 계획-대비 검수)는 있었지만, 그 앞의 «무엇을·왜·어떤 제약으로»를 사용자가 교정해 커밋하는 산출물이 없었다. 3줄 요약·/solve 메타프롬프트·/workflow Phase 설계는 전부 채팅이나 Mem0에 머물러 세션이 끊기면 사라지고, 발사 명령서·PR이 대조할 대상이 없었다. 2026-09-01 컨버터 실사고(기획은 «백본 1개 → 컨버터 → 헤드들»인데 직전 baseline 의 백본 6개 분리형을 말없이 상속해 7판 28 GPU시간을 학습)가 정확히 이 공백에서 났다. 그래서 «전제(상속·재사용·기본값 선택)»를 플레이북 5항목에 더한 6번째 항목으로 둔다.

## 언제 쓰나 (트리거)

| 상황 | 진입 |
|---|---|
| `/experiment` 진입 | Stage 0 = intent.md 커밋(Stage A 이전). `skills/experiment/SKILL.md` 코드 완성 트랙 표 |
| `/workflow` 자동 트리거(teammate·3+ 단계·조건부 분기) | Phase 설계 전에 intent.md 경로가 있어야 한다. 없으면 이 스킬 먼저 |
| `/solve` 메타프롬프트 모드 | 사용자가 승인한 [작업 프롬프트 vN]을 intent.md 로 저장·커밋(채팅은 요약본, 파일이 정본) |
| 하네스 `feat:` 커밋 | 규칙·스킬·에이전트·스크립트·settings 를 바꾸는 `feat:` 커밋은 `Intent:` 줄이 없으면 commit-msg 훅(`scripts/ci-gate-commit-msg.sh`)이 막는다 |
| 사용자 발화 | «의뢰서 적자», «왜 하는지부터», «/intent» |

**비자명의 판정**: 결과가 되돌리기 어렵거나(학습 발사·데이터 변경·외부 게시), 구조를 새로 정하거나(아키텍처·규칙 신설), 3단계 이상이거나, 다른 산출물을 상속·재사용해 시작하는 작업. 오타·경로·문구 수정과 단순 질문은 해당 없음(`fix:`·`refactor:` 커밋은 rules·rules-lazy·agents·skills·scripts·tools·config 에 **새 핵심 파일이 없을 때만** 면제 — 신설이 있으면 commit-msg 훅이 `Intent:` 줄을 요구한다, `skills/commit/SKILL.md`).

## 절차

```
Step 1 브레인스토밍 ──▶ Step 2 초안(템플릿 6항목) ──▶ Step 3 사용자 교정 ──▶ Step 4 커밋 ──▶ Step 5 체인
   (분석가 질문)           intent/YYYY-MM-DD-<slug>.md      (사용자 손)        «커밋해» 지시     plan.md 발화·게이트 대조
```

### Step 1 — 브레인스토밍 (분석가가 묻는 것만)
사용자가 자기 말로 문제를 설명하면 Claude 는 범위·영향받는 사람과 시스템·제약·성공 기준·범위 밖을 묻는다. **사실 확인은 에이전트 몫**(코드·문서·검색으로 답이 나오는 것은 묻지 않는다), **판단 질문만 되묻기 1~2문항**(`rules-lazy/decision-sovereignty.md` 규칙 2, 추천·유도 금지). 다중 해석은 전부 드러내되 답은 사용자가 만든다. 범위·제약 갈래가 결과를 바꾸는 결정 항목이면 `rules-lazy/answer-detail.md` § 문제·선택지 보고 형식(선택지 표)으로 제시하고, 면제는 단순 사실 확인·기존 선택 확인·규칙 2 되묻기(결정 항목을 올린 뒤의 고도화 1~2문항)뿐이다(2026-09-15). 요청이 `rules/prompt-routing.md` Step 1 모호 패턴에 걸린 비자명 작업이면 질문은 `/solve` § 메타프롬프트 모드의 인터뷰 모드로 한 번에 하나씩 한다(2026-11-24).

### Step 2 — 초안
`skills/intent/templates/intent.md` 6항목으로 쓴다. 파일 위치는 **작업 대상 저장소의 `intent/YYYY-MM-DD-<slug>.md`**(플레이북 권고: 코드 옆에 두어 커밋 SHA 로 묶는다. 하네스 변경은 `~/.claude/intent/`). 모노레포는 프로젝트 하위 `intent/`, 여러 저장소에 걸치면 그때만 전용 저장소.

| 항목 | 담는 것 |
|---|---|
| 1 문제 | 지금 무엇이 안 되나·누가 어디서 겪나. 사용자 원문 인용 1개 이상 |
| 2 제안 결과 | 무엇이 «된 것»인가. **성공 기준은 검증 가능한 문장**(수치·명령·파일). 필수 소절 `### 범위 밖`: 하지 않기로 한 것(없으면 «없음» 과 까닭) |
| 3 영향 사용자·시스템 | 사람·저장소·모듈·데이터·외부 서비스 |
| 4 제약 | 하면 안 되는 것·지켜야 할 규칙·예산·기한·실행 분리(발사·push 는 사용자) |
| 5 열린 질문 | 아직 못 정한 것. 정해지면 이 절을 갱신하고 결정 이력을 남긴다 |
| 6 **전제** | 기존 판에서 **상속**하는 구조, **재사용**하는 산출물, 사용자가 말하지 않아 내가 고른 **기본값**. 「이 선택이 달라지면 결과가 달라지는가」가 판별. 3줄 요약의 「왜」 줄이 이 절의 요약본이다(2026-09-08 형식 개정) |

머리에는 `상태: 초안 | 교정됨 | 승인(커밋 SHA) | 폐기`, `발안자`, `연결: plan.md 경로 · Jira 키 · 관련 intent` 를 둔다.

초안을 쓰면 `uv run python3 ~/.claude/scripts/intent_check.py <파일>` 의 출력 원문을 보고에 인용한다(필수 절 여섯 개 · 2절의 `### 범위 밖` 소절 · 머리의 `상태:` 줄 판정, 출력 끝 `RESULT: PASS|FAIL`). 새로 stage 된 의뢰서가 FAIL 이면 커밋 훅이 경고만 낸다(차단 아님). 2026-11-24 이전 의뢰서는 범위 밖 소절이 없어 FAIL 이 정상이다.

### Step 3 — 사용자 교정
초안을 그대로 승인받지 않는다. 사용자가 틀린 이해를 고치고 열린 질문을 닫는다. 수렴은 아래 «의도 확인 3단» 으로 확인한다(/solve 0단계 3번과 같은 절차).
1. **되읽기**: 의도를 한 문장으로 되읽는다.
2. **명시적 확인**: 사용자가 그 문장이 맞다고 답해야 확인이다. 침묵 · 다른 화제의 답 · 무엇에 대한 것인지 불분명한 «응» 은 확인으로 치지 않고 같은 문장을 다시 묻는다.
3. **프로브 질문 1회**: «이 이해가 틀렸다면 어디가 가장 틀렸겠습니까» 꼴로 틀린 곳을 찾게 하는 질문을 한 번 던진다(추천 · 유도 금지). 고칠 곳이 나오면 1로 돌아가고 없다고 답하면 Step 4 로 간다.

### Step 4 — 커밋
교정이 끝나면 사용자가 «커밋해»로 지시할 때 커밋한다(커밋 실행 규칙은 `skills/commit/SKILL.md`). 메시지는 `docs: Add intent for <slug>`. **커밋이 곧 다음 단계의 트리거**이며 커밋 SHA 가 승인 증거다. 이후 내용이 바뀌면 절을 지우지 않고 `## 개정 N (날짜)` 절을 덧붙인다(감사 추적).

### Step 5 — 체인과 게이트
- **plan**: 승인된 intent.md 를 입력으로 `superpowers:writing-plans`(저장 `docs/superpowers/plans/YYYY-MM-DD-<slug>.md`)가 plan.md 를 만든다. 계획 머리에 intent 경로와 SHA 를 적는다. 기준은 플레이북 그대로 «대화를 못 본 엔지니어가 계획만으로 구현할 수 있을 때까지». 심문은 «무엇이 깨질 수 있나·가장 위험한 단계·버린 대안».
- **spec**: 설계서(SRS)는 **항상 선택**이다. 사용자에게 보이는 기능 · 인터페이스를 새로 만드는 작업처럼 명세가 도움이 될 때 main 이 «설계서를 쓸까요» 를 한 번 묻는다. 쓰기로 하면 `skills/intent/templates/spec.md` 양식으로 의뢰서와 같은 폴더에 `spec.md`(또는 프로젝트의 `docs/superpowers/specs/`)를 쓰고, `uv run python3 ~/.claude/scripts/spec_check.py <파일>` 의 출력 원문을 보고에 인용한다(절 구성 · FR/NFR 추적표 · 검증 요구 판정, 출력 끝 `RESULT: PASS|FAIL`).
- **대조하는 게이트**: 1) 하네스 `feat:` 커밋(및 새 핵심 파일이 있는 `fix:`·`refactor:`) → commit-msg 훅이 `Intent: intent/….md` 줄과 파일 실재를 요구(차단) 2) 학습 발사 → `launch-set.sh launch --intent <경로>`가 state 에 경로·sha256 을 기록하고 `verify` 가 표시한다(경고 항목, 진행 중 세션을 깨지 않기 위해 차단 아님) 3) qa 계획-대비 검수(`rules-lazy/qa-process.md`)는 plan 뿐 아니라 intent 의 성공 기준·제약과도 대조한다 4) 3줄 요약의 「왜」 줄은 intent 6항목을 가리킨다(2026-09-08 형식 개정).

## 금지·경계
- intent.md 에 정답처럼 보이는 구현 세부(파일·함수 순서)를 쓰지 않는다. 그건 plan.md 몫이다.
- intent.md 는 미공개 아이디어라 외부 모델 전송 등급 2~3 이다(`rules-lazy/untrusted-quarantine.md` § 외부 모델 전송 등급). 익명화 없이 Grok·Codex 에 보내지 않는다.
- 사용자가 교정하지 않은 초안을 «승인됨»으로 표시하지 않는다(자기선언 금지, 원칙 6).

## 관련 정본
`rules-lazy/pre-work-summary.md`(3줄 요약) · `skills/solve/SKILL.md` § 메타프롬프트 모드 · `skills/workflow/SKILL.md` · `skills/experiment/SKILL.md` · `scripts/ci-gate-commit-msg.sh` · `tools/train-watcher/launch-set.sh --intent`
