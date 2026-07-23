# 프롬프트 전처리 상세 (prompt-routing 보조)

> **로드 시점**: `rules/prompt-routing.md`(always-on)의 해당 Step을 실제 수행하며 상세 절차가 필요할 때 lazy 로드.
> **모(母) 파일**: `~/.claude/rules/prompt-routing.md` (always-on — 트리거·MANDATORY 문장·테이블)
> 이 파일은 절차의 상세 단계만 담는다. "언제/무엇을"은 prompt-routing.md에 있다.

---

## Step 0.5 상세 — Ground Truth 확정 절차

> prompt-routing.md Step 0.5의 트리거·Cache 감지 테이블·명시 보고는 always-on. 아래는 확정 절차 상세.

```
1. summary 본문의 "All user messages" 섹션에서 **마지막 사용자 메시지** 추출
   → 이것이 ground truth (최신 directive)
2. system-reminder에 표시된 항목들을 "cached state"로 분류:
   - ARGUMENTS: 이전 세션의 마지막 스킬 호출 잔재
   - plan 파일: 이전 세션의 승인된 계획 (현재 작업과 무관할 수 있음)
   - Pending Tasks: summary 생성 시점 기준이므로 사용자 최근 메시지가 우선
   - phantom Read: 이전 세션에서 읽은 파일 결과 재주입
3. ground truth 기반으로 현재 작업 확정 → cached state는 참조만
```

---

## Step 1.5 상세 — subagent 작업명 모델 접두사 (MANDATORY)

Agent 도구 호출 시 `description` 필드에 **모델명 소문자 접두사**를 반드시 포함한다.
하단 상태줄에서 어떤 모델이 작업 중인지 즉시 식별 가능하게 한다.

```
description: "sonnet: Modify 4 files"      ← Sonnet subagent
description: "haiku: Find related files"    ← Haiku subagent
description: "opus: Design architecture"    ← Opus subagent (researcher 등)
```

- 형식: `"{모델}: {작업 설명 3-5단어}"`
- **접두사는 실제 `model` 파라미터 값과 반드시 일치** — 불일치 시 거짓 표시 (예: description `haiku:` + model `sonnet` 금지)
- Opus subagent도 포함 (researcher 등 opus로 spawn하는 경우)
- 결과 보고 시에도 모델명 포함: `"sonnet: 수정 완료. 변경 파일 3개."`, `"haiku: 탐색 완료. 관련 함수 3건."`

---

## Step 1.7 상세 — 반복 요청 전처리 생략

> prompt-routing.md Step 1.7의 원칙·MANDATORY 1줄 보고는 always-on. 아래는 판정 상세.

### 자동 생략 조건 (모두 충족 시)

| 조건 | 기준 |
|------|------|
| 동일 세션 | 현재 conversation 내 |
| 직전 N회 동일 패턴 | 최근 3회 요청이 동일 동사·대상·범위 |
| 사용자 명시 거부 없음 | "다시 확인해" / "재질문해" 등 명시 없음 |
| 위험도 낮음 | 파일 변경 3개 이하, 신규 파일 없음, 사용자 합의 영역 없음 |

> 반복 패턴 3회+ 감지 시 `/loop` 스킬 제안 (비용 표 출력 후 사용자 결정). 상세: `rules-lazy/loop-auto.md`.

### 생략 형식

```
[전처리 생략 — 직전 N회 동일 패턴]
이전 요청과 동일하게 진행: {추정 작업 1줄}
→ 즉시 위임: {모델}/{에이전트}
```

### 생략 거부 — 강제 전체 전처리

다음 중 하나 해당 시 생략 불가, Step 0~1.5 전체 실행:
- 사용자 명시: "처음부터 다시", "전체 검토", "다시 분석"
- 도메인 전환 감지 (코드 → 서칭 → 문서 등)
- compact 직후 (이전 패턴 정보 손실)
- 파일 변경 4개 이상 또는 신규 파일 작성
- 신규 모호성 감지 — 반복 패턴이라도 이번 요청이 Step 1 MANDATORY 표에 해당하면 Step 1 우선 (prompt-routing.md § 판정 요약과 동일 기준)
