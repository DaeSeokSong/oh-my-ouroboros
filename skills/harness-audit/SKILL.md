---
name: harness-audit
description: "Use when: 하네스 전체 정밀 점검·감사 — '하네스 점검', '하네스 감사', 'audit' 키워드, 메인 모델 전환 전, 대규모 룰 변경 후, 월 1회 주기 자가진단."
model: inherit
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Agent
  - AskUserQuestion
---

# Harness Audit (하네스 전체 정밀 감사 — self-upgrade 루프)

> **목적**: `~/.claude` 하네스(CLAUDE.md·rules·rules-lazy·agents·skills·scripts) 전체를 재실행 가능한 절차로 정밀 점검한다. **메인 모델이 무엇이든(예: Opus) 하네스 스캐폴딩만으로 최상위급 판단 품질을 유지**하는 것이 목표 — 감사→수정→검증→기록의 self-upgrade 루프를 주기적으로 돌린다.

## 트리거

| 트리거 | 시점 | 범위 |
|--------|------|------|
| "하네스 점검", "하네스 감사", "audit" 키워드 | 즉시 | 요청 범위 |
| 메인 모델 전환 전 | 필수 | **전체 (Step 1~8)** |
| 대규모 룰 변경 직후 | 권장 | 전체 (Step 1~8) |
| 월 1회 주기 (T03 주기 체크가 상기) | 자가진단 | 기계 점검 (Step 1~6, 6.4 메모리 위생·6.5 온톨로지 갱신 포함, 6.5 는 변경량 없으면 스킵) |

> **주기 상기 메커니즘**: 세션 시작 T03에서 `_audit/last-run` 과 `_audit/history.md` 의 감사 절 날짜 중 새 쪽이 30일 초과(또는 부재)면(`harness-usage-check.sh`) main이 사용자에게 /harness-audit 실행을 **제안**한다 (직접 실행 금지 — 스킬 자동 제안 규칙 준수). 감사 완료 시 § 완료 기록이 last-run을 갱신한다.

## 반복 결함 우선 체크 (역대 감사에서 확인된 패턴)

새 감사는 아래 패턴부터 grep 기반으로 훑는다 — 재발 확률이 가장 높다:

| # | 패턴 | 탐지 방법 |
|---|------|----------|
| 1 | **라벨-실체 drift** — 기능 추가 후 명칭·카운트 미갱신 (예: 5-Gate 라벨에 6항목, 에이전트 수 stale) | 숫자 포함 라벨(N-Gate, N개 에이전트) grep → 실체 개수 대조 |
| 2 | **파생 카탈로그 미동기화** — 에이전트/스킬 추가 시 AGENTS.md·RULES.md·CLAUDE.md 카운트·요약 표 누락 | agents/ 파일 수 ↔ 각 카탈로그 표 행 수 대조 |
| 3 | **훅 신설 시 세션 격리·문서화 누락** — 전역 캐시로 subagent↔main 오차단, 차단 복구 절차 룰 부재 | hooks 스크립트의 캐시 키에 session_id 포함 여부 + code-execution.md 문서화 여부 |
| 4 | **MCP 도구명 rename 미추적** — 서버 업데이트로 구식 도구명 잔존 | Step 4 (ToolSearch 대조) |
| 5 | **구축-미사용 rot** — 인프라를 만들고 루프에 정의까지 했는데 실사용 추적이 없어 조용히 썩음 (예: bench 미실행으로 축약 루프 영구 블로킹, 판단 기준의 기준선 미기록으로 실행 불가, **진입 조건이 도달 불가 집합** — 2026-07-23 solve 메타프롬프트 모드: "/solve 트리거∩실행 작업"이 실전 공집합+Step 1 선점으로 신설 2일간 0회 발동 → Step 1 핸드오프 배선으로 교정) | `scripts/harness-usage-check.sh` (T03 자동) + 신규 인프라 추가 시 "cadence-구동이면 신선도 마커, event-구동이면 트리거 배선" 자문 + **트리거 조건은 "어떤 실제 발화가 여기 도달하는가" 반례 시뮬 1회** |
| 6 | **완료 기록-실체 불일치** — 수정을 "완료"로 기록했으나 실제 커밋에 미반영 (예: 07-10 "SessionStart 하드 배선" 기록 vs 실제 최초 커밋은 07-16 — 6일간 훅 부재 무감지) | hit 추적 시 배선·설정류 수정은 `git show HEAD:파일` grep으로 실체 대조 — 기록만 믿지 않는다 |
| 7 | **경로 가드 편측 물리화** — 경로 동등·접두 비교에서 한쪽만 물리화(pwd -P/realpath)해 심링크 서버에서 가드가 상시 실패하거나 우회됨 (07-31·08-07 2회 실사고 — 08-07은 07-31 교정 자체가 편측이라 조건이 반전된 케이스, ad45edfc) | scripts/*.sh에서 pwd -P·realpath 사용처 grep → 각 비교식의 **반대편 항**도 물리화되는지 대조 — 원칙: `knowledge/harness/path-guard-symlink-bypass.md` "양측 물리화" |
| 8 | **이관 시 git 비전파 로컬 배선 소실** — `.git/hooks`·systemd 유닛·플러그인 캐시 등 clone으로 옮겨지지 않는 배선이 새 서버에서 조용히 빠짐 (08-15 실사고: 한 서버에 pre-commit 훅 미설치로 ci-gate-commit이 이관 후 0회 실행 — setup-harness.sh에 설치 로직이 있었는데 실행이 누락) | 서버 이관·신규 셋업 후 감사에서 `ls .git/hooks` + `systemctl --user list-timers` + settings.json 훅이 부르는 스크립트 실재를 대조 — 근본 대책은 이관 체크리스트에 `bash scripts/setup-harness.sh` 실행 명기 |
| 9 | **애매하면 검사 대상에서 빼 버림**: 훅·필터 수정 때 판정이 애매한 입력을 제외 목록에 넣으면 그 자리가 영구 사각이 됨 (2026-10-02 훅 필터 감사 교훈이며 그때 반영하지 못한 분) | 훅·필터를 고친 수정은 «애매하면 검사 대상에 남긴다»(오탐은 경고로 받고 제외하지 않음) 원칙으로 대조 — 제외 정규식·skip 분기를 추가한 diff 가 이 원칙을 깨는지 본다 |

> **MANDATORY 라벨 유지 기준 (2026-07-09 감축 사이클에서 확립)**: 위반 = 실피해(보안·사용자 주권·데이터 손실·비용 폭주·무한 재귀)인 것만 라벨 유지. 스타일·프로세스·권한 부여·효율 지침은 평문으로 — 라벨 남발은 진짜 MANDATORY의 신호 대비를 죽인다(늑대와 양치기). 감사 시 신규 MANDATORY가 이 기준을 통과하는지 확인.

> **수정 분류 + hit 추적 (2026-07-13 이식 — EvoPolicyGym, arXiv 2607.02440)**: 감사의 각 수정을 **구조 신설**(새 룰·스킬·훅·게이트 도입)과 **파라미터 조정**(기존 구조의 임계값·문구·한도 변경)으로 분류해 history.md에 남기고, 다음 감사 Step 1에서 직전 감사 수정들의 hit 여부를 대조한다. **hit 정의(2026-10-17)**: 직전 감사 수정이 커밋에 실재하고(agents·rules 계열을 실제로 바꾼 커밋. 기록만 있고 커밋이 없으면 hit 아님) 같은 결함이 재발하지 않음. 후보 대장 accepted 행의 `commit=` 비고를 `git show --stat <해시>` 로 대조한다. 판정 규칙: **동일 대상이 파라미터 조정 2회 후에도 재발하면 3회째는 구조 재설계로 전환** — 같은 구조 안의 조정은 틀린 메커니즘을 구제하지 못한다는 실측 근거(동 논문: same-topology edit의 구제 성공률이 낮고, 조정은 구조가 이미 맞는 계열일 때만 유효).

## 절차 (Step 1~8)

### Step 1 — 인벤토리·토큰 부하

목적: always-on 규칙 총량과 MANDATORY 밀도를 파악해 약한 모델 준수율 저하 위험을 조기 발견한다.

```bash
cd ~/.claude
echo "=== 디렉토리별 파일 수·크기 ==="
for d in rules rules-lazy agents skills scripts commands; do
  echo "$d: $(find "$d" -type f 2>/dev/null | wc -l) files, $(du -sh "$d" 2>/dev/null | cut -f1)"
done

echo "=== always-on(CLAUDE.md + rules/*.md) 총 바이트 ==="
cat CLAUDE.md rules/*.md 2>/dev/null | wc -c

echo "=== MANDATORY 키워드 밀도 (always-on) ==="
grep -c MANDATORY CLAUDE.md rules/*.md 2>/dev/null
```

판단 기준: always-on 총 바이트·MANDATORY 밀도가 이전 감사 대비 증가 추세이면 경고 — 규칙 수 증가는 약한 모델 준수율 저하와 상관관계가 있다.

> **기준선은 `_audit/history.md`에 매 감사마다 기록 (MANDATORY — 2026-07-09 신설)**: "이전 대비 증가 추세" 판단은 이전 수치가 기록돼 있어야만 실행 가능하다 — 2026-07-09 점검에서 이 판단 기준이 기준선 없이 정의만 돼 있어 실행 불가능했음을 발견(측정치가 대화 로그에만 남고 휘발). 매 감사 완료 기록에 `always-on {N}바이트 / MANDATORY {M}건` 1줄을 포함할 것. 최초 기준선: 2026-07-09 = 67,212바이트 / MANDATORY 56건.

> **스캐폴딩 밀도 = 모델 능력의 함수 — 지금부터 적용 (2026-07-09 사용자 결정으로 즉시 적용 전환)**: Anthropic Fable 5 프롬프팅 가이드 — "이전 모델용 스킬은 과도하게 규범적인 경우가 많으며 출력 품질 저하 — 검토·제거 고려". 사용자 판단: Opus 4.8+도 능력이 충분하므로 미래 지향으로 지금 갱신. 적용 방식(안전 우선): 1) **신규 룰·스킬은 원칙형 1줄 우선** — 동작별 열거는 실제 실패 사례가 있을 때만 추가 (quick-skill에 write-time 게이트) 2) **기존 열거 축약은 Step 1.5 다이어트 사이클로 정례화** (2026-07-28 사용자 결정 C — 후보 기준·게이트 2단은 그쪽이 정본) 3) 축약해도 안 되는 것: 보안 게이트·사용자 주권(승인·push) 규칙 — 이건 모델 능력과 무관한 정책이다.

### Step 1.5 — 정기 다이어트 사이클 (2026-07-28 사용자 결정 C — 위기 대응→정례화)

목적: always-on(한도 75,000B — 2026-08-10 사용자 결정 B, 70,000B 3주 연속 초과 후 상향)을 "신규 룰 때마다 급한 상쇄 트림"이 아니라 정기 사이클로 관리한다. 경위: 2026-07-22~28 한 주에 예산 위기 4회 — 매번 즉석 트림으로 막았으나 압축 여지 소진 추세 → 사용자 결정 C(한도 유지 + 정례 다이어트). 08-10 재차 압축 여지 소진(71,023B, 초과 3연속 누적)으로 한도 자체를 75,000B로 상향(결정 B) — 다이어트 사이클 자체는 유지. **2026-10-01 사용자 지시: 75,000B 는 목표선이지 커밋 차단선이 아니다**(«상시 규칙은 한도 넘어도 돼. 넘으면 그 때 최적화 다시 진행하면 되니까 우선 최대한 규칙을 무조건 지킬 수 있는 거에 집중해»). 필수 규칙은 온전한 문장으로 먼저 넣고, 커밋 게이트(`scripts/ci-gate-commit.sh`)는 초과를 경고만 한다. 초과분은 이 사이클에서 따로 줄이며 같은 커밋에서 급히 깎지 않는다. 2026-10-02 사이클 실행: 76,106B→72,588B→71,600B(무손실, 중복·경위·정본 이관, 2차는 보수적).

**스킬 정리 후보 입력 (2026-11-24, 의뢰서 W10)**: `uv run python3 ~/.claude/scripts/skill_usage_report.py` 의 표(스킬별 30일 · 90일 호출 수 · 0회 스킬 · 20,000B 초과)를 입력으로 본다. 0회는 «지워도 된다» 가 아니라 후보일 뿐이고 기록 기간이 90일 미만이면 판단 근거가 약하다. 실제 삭제 · 병합은 사용자 확인 뒤에만 한다.

**트리거 2종**
- **정기**: 월간 감사 Step 1 측정 직후 항상.
- **위기**: always-on 여유 < 1,000B **또는** 주간 zerosum 경고 2회+ → 이 Step만 단독 실행 (`learner.md` § Zero-Sum에서 라우팅). (여유 임계는 한도 상향에 비례해 500B→1,000B로 재보정 — 2026-08-10)

**후보 선정 우선순위** (2026-07 실측 수확 순 — 각 항목에 실사례 있음)
1. **요약-상세 중복**: always-on 요약이 lazy 상세를 복제 (실측: 전제 실증 줄 822→260B).
2. **동일 불변식 다중 진술**: 3중+ 진술 → 2중 유지 (실측: TeamCreate 금지 3중).
3. **열거형 예시 표**: 원칙 문장이 정본인 표·목록 → 1줄 (실측: 자동 허용 12행→1줄).
4. **경위·날짜 서술**: 룰엔 결론만 — 경위는 decisions/knowledge 소관.
5. **사어**: 인바운드 참조 0 (Step 2 포인터 검사와 연계해 탐지).

**게이트 2단 (bench 부담 현실화)**
- **무손실 압축** (중복 제거·lazy/knowledge 이관·정본 유지 표→1줄 — 의미 변경 0): bench 생략 가능. 커밋 메시지에 "의미 변경 0" 명시, 다음 감사에서 hit 추적(해당 규칙 위반 재발 = 의미 손실 신호 → 복원 검토).
  - **로드 시점 검사**(2026-09-15): 옮기는 문장이 필요한 순간(도구 차단 직후·세션 첫 턴·위임 판단 중·명령서 작성 턴 등)에 lazy를 여는 트리거·포인터가 always-on에 남는가. 남지 않으면 정본이 lazy에 있어도 무손실이 아니다(09-15 다이어트에서 T03 스킵·Read 복구·명세 4종이 이 검사 없이 이관됐다가 복귀).
  - **개정 뒤 잔존 검색**(2026-09-15): 규칙 개정 뒤 구 문구 검색은 어구 grep만이 아니라 정본 파일의 서문(왜 바꾸는가)·규칙 표·자가체크·다른 규칙의 관련 절을 통독한다(09-15 선택지 개정에서 grep이 7곳을 놓침).
- **After 측정 시점**: 룰 승격·변경 직후 같은 맥락에서 재지 말고 **무관 작업을 1개 이상 사이에 둔 뒤** 측정 — 같은 맥락 즉시 측정은 효과를 과대평가한다(FinEvo-Bench 전역 교차 배치 설계, 2026-08-18 검증).
- **의미 축약** (행동 규칙 삭제·커버리지 감소 가능): `/harness-bench` Before/After 게이트 + 사용자 승인 필수.
- 공통: **삭제보다 이관 우선**(내용 무손실 — lazy·knowledge로), 보안 게이트·사용자 주권 룰은 대상 제외(독트린 3).

**목표선·기록**: 사이클 종료 시 **여유 ≥ 1,500B**(신규 룰 2~3건 흡수 버퍼). history.md에 `다이어트: 후보 N→반영 M, −XB, 여유 YB` + 항목별 `[무손실|의미축약]` 분류(hit 추적 대상).

### Step 2 — 포인터 무결성

목적: `.md`가 참조하는 파일 경로가 실제로 존재하는지 확인한다 (죽은 링크 방지).

```bash
cd ~/.claude && grep -rhoE '(~/\.claude/)?(rules-lazy|rules|skills|agents|scripts|commands)/[A-Za-z0-9_/.-]+\.(md|sh|json)' --include='*.md' CLAUDE.md rules rules-lazy agents skills commands 2>/dev/null | sed 's|~/.claude/||' | sort -u | while read -r f; do [ -e "$f" ] || echo "MISSING: $f"; done
```

> 예시 텍스트로 등장하는 `rules/A.md`·`rules/B.md`·`commands/C.md` 등은 실제 참조가 아니므로 결과에서 무시한다.

### Step 3 — 모델 핀 점검

목적: 별칭(opus/sonnet/haiku) 대신 하드코딩된 버전 ID가 박혀 있으면 모델 세대교체 시 즉시 깨진다.

```bash
grep -H '^model:' ~/.claude/agents/*.md ~/.claude/skills/*/SKILL.md 2>/dev/null
# 본문 내 하드코딩도 탐지 (frontmatter 밖 사각지대 — 예시 문구는 결과에서 무시)
grep -rHnE 'claude-(opus|sonnet|haiku|fable)-[0-9][0-9a-z.-]*|sonnet-4-[0-9]|opus-4-[0-9]' ~/.claude/CLAUDE.md ~/.claude/rules ~/.claude/rules-lazy ~/.claude/agents ~/.claude/skills ~/.claude/commands --include='*.md' 2>/dev/null
```

판단: 값이 `opus`/`sonnet`/`haiku` 별칭이 아니라 `claude-opus-4-...` 같은 구체 버전 ID면 P0 플래그. model pin은 머신별(gitignored settings.local.json 또는 ANTHROPIC_MODEL env — 2026-07-15)이므로, **추적 settings.json에 model 키가 있으면 그 자체가 posture 위반 플래그**다.

```bash
grep -H '"model"' ~/.claude/settings.json 2>/dev/null && echo "⚠️ 추적 settings.json에 model 키 존재 (posture 위반)"
grep -H '"model"' ~/.claude/settings.local.json 2>/dev/null
```

### Step 4 — MCP 도구명 실재성

목적: `.md`가 참조하는 `mcp__{서버}__{도구}` 이름이 실제 연결된 서버에 존재하는지 확인한다 (죽은 서버·구식 도구명 방지).

```bash
grep -rhoE 'mcp__[A-Za-z0-9_]+__[A-Za-z0-9_]+' ~/.claude/CLAUDE.md ~/.claude/rules ~/.claude/rules-lazy ~/.claude/agents ~/.claude/skills 2>/dev/null | sort -u
```

위 목록을 현재 세션의 ToolSearch 결과 및 연결된 MCP 서버 목록과 대조한다 — 미연결 서버를 참조하거나 존재하지 않는 도구명이면 P0 플래그.

### Step 5 — 중복·충돌 스팟체크

목적: 동일 주제를 서로 다른 파일이 상이한 기준으로 규정하는 충돌을 찾는다.

점검 대상 쌍 (알려진 중복 후보):
- `agents/qa.md` ↔ `rules-lazy/qa-process.md` (체크리스트·Ralph·G-E 루프 기준 일치 여부)
- `rules-lazy/token-efficiency.md` ↔ `rules-lazy/agent-routing-mcp.md` (subagent 반환 적재 기준 일치 여부)
- `agents/coder.md` ↔ `rules-lazy/loop-auto.md` (G-E 루프 재시도 규칙 일치 여부)

```bash
diff <(grep -n 'MANDATORY\|재시도\|Gate' ~/.claude/agents/qa.md) <(grep -n 'MANDATORY\|재시도\|Gate' ~/.claude/rules-lazy/qa-process.md)
```

(참고용 diff — 자동 판정 불가, 목록 대조 후 수동 판단)

동일 주제에 상이한 기준·수치가 발견되면 P2 플래그.

### Step 6 — 스크립트 함수 실재성

목적: 룰 문서가 참조하는 셸 함수가 실제 스크립트에 정의돼 있는지 확인한다.

```bash
grep -E '^\s*(gate|zerosum|killswitch)\)' ~/.claude/scripts/harness-bench.sh ~/.claude/scripts/harness-evolve.sh 2>/dev/null
```

룰 문서에서 언급하는 서브커맨드(예: `gate`, `zerosum`, `killswitch`)가 위 결과에 없으면 P0 플래그 (문서와 구현 불일치).

> 결합 case arm(`before|after)`)은 단일 라벨 grep에 안 잡힌다 — 패턴에 `|` 포함할 것: `grep -E '^\s*[a-z|-]+\)'`

### Step 6.4 — 메모리 위생 (user·feedback provenance 재검증 — 2026-08-18 신설)

목적: 사용자 속성·피드백 메모리의 과잉추론 누적을 정기 회수한다 — LLM은 증거 이상으로 사용자 속성을 지어내며(12모델 전원 35~49%) 자발 재검토는 드물어, revision 루프가 있어야만 오염이 회복된다는 실증(Personalization Mirage + HINDSIGHT — citation-verifier 교차 검증 2026-08-18).

1. mem0 `feedback` 카테고리 + auto-memory `user`/`feedback` 타입에서 표본 5~10건 추출.
2. 각 건에 §C-2 provenance(사용자 원문 인용·`(추정)` 태그) 존재 확인 — 없으면 근거 소급 확인 후 태그 보강 또는 `번복됨`/삭제 제안.
3. 현재 사실과 어긋난 stale 항목은 update — 결과는 history.md에 `메모리 위생: 표본 N, 보강 M, stale K` 1줄.
4. 템플릿-규칙 정합 스팟: user·feedback 계열 T 템플릿 예문(T24 등)이 §C-2 provenance를 반영하는지 1회 대조 (2026-08-19 검수에서 T24 불일치 실측 — 신규 템플릿 추가 시 재발 지점).

### Step 6.5 — 온톨로지 vault 갱신 (선택 — 지난 감사 이후 변경량 있을 때)

목적: `~/.claude` 자체를 `/graphify --obsidian`으로 뽑은 하네스 온톨로지 vault(`graphify-out/obsidian/`)를 최신 상태로 유지한다.

```bash
# git pull은 사용자 직접 (하네스 push/pull 사용자 주권 정책 — Claude 자동 실행 금지):
#   사용자에게 아래 실행 요청 후, 이 감사를 끝낸 뒤 순차로 /graphify 를 실행한다
#   (스킬 안에서 다른 스킬을 부르고 돌아오지 않는다. 깊이 N=1)
cd ~/.claude && git pull --ff-only   # ← 사용자 직접 실행
#   이어서(감사 종료 후 순차): graphify ~/.claude --update --obsidian
```

> **멀티서버 필수**: `git pull` 선행은 생략 불가 — 다른 서버가 먼저 갱신했을 수 있는 비결정적 산출물(LLM 추출) 위에서 증분 빌드해야 충돌이 줄어든다. pull 실패(로컬 미커밋 변경 충돌) 시 Step 6.5 중단, 무리한 진행 금지 — 상세: `rules-lazy/code-graph.md` §7.1.

> **왜 git hook이 아니라 이 스킬 주기에 편입했는가**: 하네스 콘텐츠는 대부분 마크다운(rules/agents/skills)이라 semantic 추출에 LLM(에이전트 세션 dispatch)이 필요하다 — `.git/hooks/pre-commit`(`ci-gate-commit.sh`)처럼 순수 bash만 도는 훅에서는 이 단계를 자동화할 수 없다 (코드 파일 전용 `scripts/graphify-autoindex.sh`와 다른 이유로 하네스가 그 훅에서 명시적으로 제외돼 있음 — § "하네스 격리" 참조). 이미 존재하는 30일 주기 self-upgrade 루프에 얹는 것이 가장 저비용이다.

지난 감사 이후 rules/agents/skills 변경이 없었으면 스킵(토큰 절약). `--update`가 "No files changed since last run"을 출력하면 그대로 스킵. vault 변경분은 § 완료 기록 커밋에 함께 포함 — **push는 하지 않는다** (하네스 표준 정책: push는 항상 사용자 직접).

운영 주의 2건 (`rules-lazy/code-graph.md` §7 실측 근거):
- **read-once 우회**: main이 이 세션에서 이미 Read한 파일은 추출 서브에이전트가 차단돼 스텁이 된다 → spawn prompt에 "Read 차단 시 offset/limit 부분 읽기로 우회" 1줄 포함.
- **갱신 후 건강 점검**: graphify 스킬의 Step 4.5 진단(`skills/graphify/SKILL.md` § Step 4.5, dangling/self-loop) 1회 실행 — 이전 빌드 대비 dangling 수가 **증가**하면 스텁·ID 불일치 신호로 보고.

### Step 7 — 의미 정합 전수 정독 (정밀 모드 — 모델 전환 전·대규모 변경 후 필수)

목적: 기계 점검이 못 잡는 상호 모순·실행 불가능 지시·특정 모델 전제를 잡는다. **qa subagent 5분할 병렬 fan-out** (2026-07-06 감사에서 검증된 분할):

| # | 영역 | 대상 |
|---|------|------|
| 1 | always-on | CLAUDE.md + rules/*.md |
| 2 | lazy 전반 | rules-lazy/ a~l |
| 3 | lazy 후반 | rules-lazy/ m~z |
| 4 | 에이전트·스킬·명령 | agents/*.md + skills/*/SKILL.md + commands/*.md |
| 5 | 배선 | settings.json hooks ↔ scripts/ 정합 + enabledPlugins ↔ 설치 실체(cache/registry) + _audit 기록 ↔ 스크립트 파싱 계약 (2026-07-31 Codex: 종전 사각지대) |

spawn prompt 필수 요소 (5요소 + 아래 특칙, 정본 `rules-lazy/agent-routing-mcp.md` § Spawn prompt 5요소 강제):
- 서두에 `[SKILL_DEPTH: 1]` (discuss 와 같은 표기, `rules/agent-routing.md` § SKILL_DEPTH 전달)
- user_request: 감사를 지시한 사용자 발화 원문 인용 또는 원문 파일 경로(main 의 요약만 넘기지 않는다)
- 점검 관점 4종: 1) 실행 가능성(그 파일만 읽고 실행 가능한가) 2) 상호 모순(파일 간 수치·기준) 3) 특정 모델 전제 잔재 4) §헤딩 참조 실재성
- output_format: 파일별 ✅/⚠️ + 발견당 `{파일:라인, 문제 1줄, P0/P1/P2, 제안 1줄}` — 600자 요약 상한
- task_boundary: **읽기 전용** + 보안 게이트·훅 내부 패턴 원문 인용 금지("정합/불일치 + 위치"만) — 세션 컨텍스트 오염 방지 (운영 주의: 상세가 대화에 누적되면 안전필터 오탐 유발 이력)
- 알려진 충돌 후보 쌍(Step 5)을 해당 영역 에이전트에 명시 배정

subagent 보고는 **main이 원문 재검증 후** 수정한다 — 액면 수용 금지 (예: "9→10 교정" 지적이 실제론 의도적 9였던 사례). 단 Step 8 의 외부 모델 답 원문을 읽은 main 은 그 답을 근거로 한 수정을 같은 손으로 하지 않는다: 지적 확인은 qa, 수정은 coder(CLAUDE.md «읽기와 실행의 분리»).

**감사 범위·커버리지 기록 (MANDATORY)**: 감사 보고에 «어디까지 읽었는가»(영역·파일 수)를 적고, 시간·토큰·호출 상한에서 멈췄으면 미검토 목록을 함께 보고한다(2026-10-01 감사의 교훈: 범위 밖으로 남은 영역이 보고에 없으면 «이상 없음»으로 읽힌다).

### Step 8 — 외부 모델 교차검증 (정밀 모드 — 가용 시)

Codex 등 이용 가능한 외부 모델 에이전트로 2차 감사. 호출 전 **모델·effort 게이트**(작업 사이클당 1회, `rules-lazy/codex-model-gate.md` 맨 위 원칙과 §1)와 **전송 사전검사**(`python3 ~/.claude/scripts/external_send_preflight.py <작업디렉터리>` 차단 0건, 같은 파일 §0)를 거친다. 프롬프트에 반드시 포함:
- **이미 수정 완료한 항목 목록** (중립 요약) + "이 목록 밖의 신규 결함만" 지시 — 중복 보고 방지
- 점검 요청 4종: 1) 이번 수정이 만든 2차 부작용 2) 내부 분할 감사의 구조적 사각지대(카탈로그 문서·plugins·settings 정합) 3) 현재 메인 모델의 능력·거동을 암묵 전제한 서술 4) 룰 간 우선순위 미정의 지점
- 읽기 전용 + 중립 보고 특칙 동일 적용

## 완료 기록 (MANDATORY — self-upgrade 루프의 닻)

감사 종료(수정 커밋 완료) 시:
> `_audit/history.md`·`last-run` 기록이 빠지면 SessionStart 의 `harness-usage-check.sh` 가 30일 초과 시 `AUDIT_STALE` 분기에서 경보를 낸다(`scripts/harness-usage-check.sh`).
0. **배선·설정류 수정의 실체 확인 (2026-07-16 신설 — 반복 결함 #6)**: settings.json 훅·스크립트 배선 등은 기록 전에 `git show HEAD:파일 | grep` 으로 **커밋된 실체**를 확인 — 워킹트리·계획·대화 로그가 아니라 커밋이 증거다
0.5. **후보 반영 실체 확인**: 후보 대장 accepted 행의 `commit=` 비고를 `git show --stat <해시>` 로 대조한다(해시가 실재하고 agents·rules 계열을 바꿨는지. § 수정 분류 + hit 추적의 hit 정의와 짝).
1. `~/.claude/_audit/last-run` 갱신 — 내용 1줄: `YYYY-MM-DD {커밋범위} {발견 N건/수정 M건} {판정 1줄}` (T03 주기 체크의 기준점)
2. `~/.claude/_audit/history.md` append — 실행 일자·범위(기계/정밀)·발견 요약·커밋 해시 + **수정별 [구조|조정] 분류와 직전 감사 수정의 hit 여부** (§ 반복 결함 표 하단 분류 규칙). history.md는 git 추적(repo 단위 지식 — 온톨로지 코퍼스 편입, 2026-07-13 전환), `last-run` 신선도 마커만 로컬
3. 반복 결함 패턴 → Mem0 저장 (`category: code_pattern`, `source: harness-audit`) + 본 스킬 § 반복 결함 우선 체크 표에 신규 패턴 반영 제안 (사용자 승인 시 편집 — 이것이 self-upgrade)
4. **의미 변경이 있는 행동 규칙(rules·agents·CLAUDE.md) 변경이 있었으면 `/harness-bench` before/after 필수**(조건부 제안이 아니다. 무손실 이관은 Step 1.5 게이트 2단대로 생략 가능). 이번 감사가 행동 규칙을 건드리지 않았으면 "벤치 불요" 1줄을 `history.md`에 적는다. 벤치를 즉시 못 돌리면(사이클 대기 등) "벤치 대기(BENCH_PENDING 추적)" 1줄을 대신 적고 후속 세션에서 완료한다
5. **감사 기준선 태그 제안**: `audit/{YYYY-MM-DD}` — 승인 시 생성 (`agents/gitops.md` § 태그 규칙). 대규모 룰 변경을 시작하는 감사면 변경 직전 `pre-{변경명}-{MMDD}` 롤백 앵커도 함께 제안
6. **공개 미러 최신성 점검 (MANDATORY — 2026-07-23 신설, 2026-10-23 사용자 지시로 확대, 의뢰서 `intent/2026-10-23-public-mirror-refresh.md`)**: 공개 미러(oh-my-ouroboros)는 포트폴리오·이력서의 근거 링크라 최신이고 안전해야 한다. 매 감사마다 `bash scripts/public-mirror-status.sh` 를 돌린다(종료 코드 1 = 30일 초과, agents·skills·hooks 개수가 «발행 예정 정제본» 과 다름, 게이트 차단 중 하나). 1 이면 아래 A 절차를 처음부터 반복하고 사용자에게 알린다.
   - **A-1 차이 보고**(실행 전): 공개본과 비공개 공개 대상의 agents·skills·rules·hooks·`_audit` 차이 목록과, README 배지·개수·표가 실제와 어긋나는 곳.
   - **A-2 게이트**: `bash scripts/public-export.sh --stage-out <빈 폴더>`(정제본을 남기고 게이트 결과로 끝남). 막히면 거기서 멈추고 막은 파일·패턴을 보고한다. 게이트를 끄거나 우회하지 않는다.
   - **A-3 공개 전 범주 검사**: `python3 -I scripts/public-export-scan.py <그 폴더>`(회사·고객·병원·환자·의료영상 / 내부 호스트·URL·이메일·홈 경로 / 비밀값 / 미공개 연구 이름 / 논문·특허 서지). 걸린 것이 있으면 `config/public-export-rules.txt` 를 고치고 처음부터 다시 내보내 검사한다. 원칙은 «내부 프로젝트 내용은 가명 치환이 아니라 삭제, 범용 내용만 남김»(2026-10-23 사용자 결정, 의뢰서 개정 1)이다. 내부 전용 파일은 `x|`, 범용 규칙 줄에 붙은 내부 출처는 `r|` 로 구절만, 내부 경위만 담은 줄은 `d|` 로 지운다. 코드·시험의 예시 값만 범용 자리값으로 두고, 그때는 정제본 시험을 원본과 같은 방식으로 돌려 결과가 같은지 확인한다. «⚠ 미적중 규칙» 경고는 원문이 바뀐 신호라 그 줄을 다시 본다. 검사 낱말은 비공개 `config/public-export-scan.txt` 에 둔다(공개되는 파일에 쓰지 않는다).
   - **A-4 README**: `public/README.md` 의 배지·표를 실제 개수로 고친다. 수치는 `_audit/history.md` 에 기록된 실측값만 쓰고, 추정·성과 수치는 넣지 않는다. «A Claude Code harness» 같은 기반 표현은 사실대로 둔다.
   - **A-5 이력서·포트폴리오 주장 대조**: 공개될 파일로 (a) 훅이 비밀값 커밋을 막는다 (b) 인용 전 철회 확인 단계(citation-verifier) (c) 반복 교정이 규칙 후보로 올라가고 적용 전후를 측정한다(learn-from-feedback·harness-bench) 가 확인되는지 적고, 과한 문장을 짚는다.
   - **A-6 동기화**: `--publish` 와 push 는 미러 폴더(하네스 밖 저장소)에 쓰므로 사용자가 직접 한다. 매니저는 게이트 결과와 명령을 안내한다.
   - **금지 패턴(`f|`) 후보**가 보이면 제안만 하고, 사용자 승인 뒤에 넣는다.
   - **보고 끝 한 줄(MANDATORY)**: `public-mirror-status.sh` 출력(«마지막 동기화 날짜 / 공개본 agents·skills·hooks 개수 / 게이트 결과»)을 그대로 붙인다.
   - **같은 날 알림**: 새 에이전트·새 훅·규칙 체계 변경을 커밋한 날은 월간 점검을 기다리지 않고 그 보고에서 공개 미러 갱신이 필요하다고 알린다(`rules-lazy/peer-session-messages.md` § 하네스 변경 전파).

## 보고 형식 (MANDATORY)

아래 3단 표 + 근거 + 승인 질문 형식으로 보고한다.

```
## 문제없음 확인
- {점검 항목}: 이상 없음 (근거: {파일:라인})

## P0 — 깨짐·구세대 (즉시 조치)
| # | 항목 | 근거 (파일:라인) | 문제 | 제안 조치 |
|---|------|-----------------|------|----------|

## P1 — 성능 스캐폴드 (권장)
| # | 항목 | 근거 (파일:라인) | 문제 | 제안 조치 |
|---|------|-----------------|------|----------|

## P2 — 다이어트·일관성 (순차)
| # | 항목 | 근거 (파일:라인) | 문제 | 제안 조치 |
|---|------|-----------------|------|----------|

수정 진행할까요? (P0부터 순차 승인 / 전체 일괄 승인 / 보류)
```

> 이 스킬은 감사·보고까지만 수행한다. 실제 수정은 P0/P1/P2 승인 후 coder/gitops 등 별도 에이전트에 위임한다.

## 주기·연계

- 권장 주기: 메인 모델 전환 전 필수(Step 1~8) / 월 1회 기계 점검(Step 1~6, 6.4 메모리 위생 포함, 변경량 있으면 Step 6.5 포함) / 대규모 룰 변경 직후 — 주기 상기는 T03 `_audit/last-run` 체크(§ 트리거)
- 결과 중 반복 결함은 Mem0에 저장 (`category: code_pattern`, `source: harness-audit`) → learner/T41(에이전트 약점 평가)과 연계 + § 반복 결함 우선 체크 표 갱신 제안
- 수정 실행은 이 스킬의 범위 밖 — 별도 승인 후 coder/gitops 등에 위임 (사용자가 사전에 일괄 승인해도 외부 모델 답을 읽은 경우 수정은 coder, 지적 확인은 qa 가 맡는다. 읽기와 실행의 분리)
