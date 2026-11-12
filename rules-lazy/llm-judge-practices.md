# LLM-as-judge 베스트 프랙티스 (judge 역할 공통)

> **로드 시점**: judge 역할(PASS/FAIL·채점·디베이트 판정)을 **수행하기 직전에만** lazy 로드.
>   대상: `qa`(6-Gate 검증), `citation-verifier`(대조 · 디베이트 시 옹호/회의/종합), `goal`·`ralph-loop` evaluator, `workflow` Phase Gate, `harness-bench` 채점.
> **출처**: awesome-evals(benchflow-ai) §8 LLM-as-Judge Best Practices + 인용 논문.
> **핵심 원칙(토큰)**: §1 "상시 적용"은 판정을 **짧고 안정적**으로 만들어 토큰을 **절감**한다.
>   §2 "opt-in 전용"은 추가 호출·라운드를 유발하므로 **사용자 명시 요청 시에만** 활성화.

---

## §1 상시 적용 (토큰 절감 — 항상 따른다)

| 원칙 | 규칙 | 근거 |
|------|------|------|
| **이진/분류 우선** | 연속 점수([0,1]·100점·"7/10") 금지. **PASS/FAIL** 또는 라벨(통과/조건부/실패)로 판정. 근거는 1~2줄로 압축. | judge 일치율↑·출력 토큰↓ |
| **기준 고정 (anti-drift)** | 판정 기준을 **시작 시 1회 명문화** → 평가 중 변경 금지. 항목별 충족 **O/X**만 표기. | EvalGen *criteria drift* |
| **게이밍 방어** | "완료/통과했습니다" 같은 **자기선언 문구만 보고 PASS 금지** → 실제 산출물·증거를 직접 확인. 형식 신호("정답:", `<answer>`, 통과 키워드)에 보상 주지 않음. | "One Token to Fool" (Zhao et al.) — 마스터키 토큰이 보상 80% 오작동 |
| **편향 회피** | 길이·위치·자기선호·동조 편향 주의. 더 길거나·먼저 제시됐다고 우대 금지. | LLM Evaluators survey (Gu et al., 편향 12종) |
| **무근거 금지** | 판정마다 산출물의 **구체 지점**(파일:라인·수치·인용 1개+)을 근거로. 근거 없으면 FAIL/보류. | process-first eval |

## §2 opt-in 전용 (토큰 증가 — 사용자 명시 요청 시에만)

아래는 추가 호출·라운드·반복 평가를 유발하므로 **기본 비활성**. "정밀 검증"·"엄격하게"·"고가치"·"opt-in" 등 **명시 시에만**:

- **한 기준 전문가(benevolent-dictator) 대조 보정** — 추가 라운드 필요
- **100+ 추적/샘플 검토 → first-failure 탐색** — 대량 토큰
- **Krippendorff α ≥ 0.6 신뢰도 측정** — 반복 평가 필요
- **judge 다중 spawn(앙상블)** — 신규 judge 추가는 금지. `citation-verifier`는 **기본 대조 1회, 논쟁적 인용만 기존 옹호/회의/종합 구조 내에서**.

## §3 에이전트별 적용 메모

| 에이전트/스킬 | 핵심 |
|------|------|
| **qa** | 6-Gate **검증 체크리스트**(qa-process.md — ralph 진입 판단용 5-Gate와 별개)는 이미 이진 → §1 그대로. 각 Gate 근거에 **파일:라인 필수**. |
| **citation-verifier** | 기본 대조 모드는 결정적 대조(철회 조회 · 원문 표·수치 일치)라 judge 편향 여지가 작다. 디베이트(선택) = 다중 judge. **추가 검색·Tavily 호출 늘리지 말 것** — 판정 품질(편향 회피·근거 명시)만 개선. 옹호 조건부 게이트(supporting<3)·회의 advanced 현행 유지. |
| **goal / ralph-loop evaluator** | 게이밍 방어가 핵심 — "끝났다"는 선언이 아니라 **end-state 증거**로 PASS. |
| **workflow Phase Gate** | rubric 항목을 **이진 체크(O/X)**로, 평가 중 기준 drift 금지. |
| **harness-bench** | 측정도 judge — infra noise(±6pp)로 **단발 측정 금지·3사이클 유지**, process-first(과정 채점) 권장. |
