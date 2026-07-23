---
name: harness-audit
description: "Use when: 하네스 전체 정밀 점검·감사 — '하네스 점검', '하네스 감사', 'audit' 키워드, 메인 모델 전환 전, 대규모 룰 변경 후, 월 1회 주기 자가진단."
model: opus
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
| 월 1회 주기 (T03 주기 체크가 상기) | 자가진단 | 기계 점검 (Step 1~6) |

> **주기 상기 메커니즘**: 세션 시작 T03에서 `_audit/last-run` mtime이 30일 초과(또는 부재)면 main이 사용자에게 /harness-audit 실행을 **제안**한다 (직접 실행 금지 — 스킬 자동 제안 규칙 준수). 감사 완료 시 § 완료 기록이 last-run을 갱신한다.

## 반복 결함 우선 체크 (역대 감사에서 확인된 4대 패턴)

새 감사는 아래 패턴부터 grep 기반으로 훑는다 — 재발 확률이 가장 높다:

| # | 패턴 | 탐지 방법 |
|---|------|----------|
| 1 | **라벨-실체 drift** — 기능 추가 후 명칭·카운트 미갱신 (예: 5-Gate 라벨에 6항목, 에이전트 수 stale) | 숫자 포함 라벨(N-Gate, N개 에이전트) grep → 실체 개수 대조 |
| 2 | **파생 카탈로그 미동기화** — 에이전트/스킬 추가 시 AGENTS.md·RULES.md·CLAUDE.md 카운트·요약 표 누락 | agents/ 파일 수 ↔ 각 카탈로그 표 행 수 대조 |
| 3 | **훅 신설 시 세션 격리·문서화 누락** — 전역 캐시로 subagent↔main 오차단, 차단 복구 절차 룰 부재 | hooks 스크립트의 캐시 키에 session_id 포함 여부 + code-execution.md 문서화 여부 |
| 4 | **MCP 도구명 rename 미추적** — 서버 업데이트로 구식 도구명 잔존 | Step 4 (ToolSearch 대조) |
| 5 | **구축-미사용 rot** — 인프라를 만들고 루프에 정의까지 했는데 실사용 추적이 없어 조용히 썩음 (예: bench 미실행으로 축약 루프 영구 블로킹, 판단 기준의 기준선 미기록으로 실행 불가) | `scripts/harness-usage-check.sh` (T03 자동) + 신규 인프라 추가 시 "cadence-구동이면 신선도 마커, event-구동이면 트리거 배선" 자문 |
| 6 | **완료 기록-실체 불일치** — 수정을 "완료"로 기록했으나 실제 커밋에 미반영 (예: 07-10 "SessionStart 하드 배선" 기록 vs 실제 최초 커밋은 07-16 — 6일간 훅 부재 무감지) | hit 추적 시 배선·설정류 수정은 `git show HEAD:파일` grep으로 실체 대조 — 기록만 믿지 않는다 |

> **MANDATORY 라벨 유지 기준 (2026-07-09 감축 사이클에서 확립)**: 위반 = 실피해(보안·사용자 주권·데이터 손실·비용 폭주·무한 재귀)인 것만 라벨 유지. 스타일·프로세스·권한 부여·효율 지침은 평문으로 — 라벨 남발은 진짜 MANDATORY의 신호 대비를 죽인다(늑대와 양치기). 감사 시 신규 MANDATORY가 이 기준을 통과하는지 확인.

> **수정 분류 + hit 추적 (2026-07-13 이식 — EvoPolicyGym, arXiv 2607.02440)**: 감사의 각 수정을 **구조 신설**(새 룰·스킬·훅·게이트 도입)과 **파라미터 조정**(기존 구조의 임계값·문구·한도 변경)으로 분류해 history.md에 남기고, 다음 감사 Step 1에서 직전 감사 수정들의 hit(재발 방지 확인) 여부를 대조한다. 판정 규칙: **동일 대상이 파라미터 조정 2회 후에도 재발하면 3회째는 구조 재설계로 전환** — 같은 구조 안의 조정은 틀린 메커니즘을 구제하지 못한다는 실측 근거(동 논문: same-topology edit의 구제 성공률이 낮고, 조정은 구조가 이미 맞는 계열일 때만 유효).

## 절차 (Step 1~6)

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

> **스캐폴딩 밀도 = 모델 능력의 함수 — 지금부터 적용 (2026-07-09 사용자 결정으로 즉시 적용 전환)**: Anthropic Fable 5 프롬프팅 가이드 — "이전 모델용 스킬은 과도하게 규범적인 경우가 많으며 출력 품질 저하 — 검토·제거 고려". 사용자 판단: Opus 4.8+도 능력이 충분하므로 미래 지향으로 지금 갱신. 적용 방식(안전 우선): ① **신규 룰·스킬은 원칙형 1줄 우선** — 동작별 열거는 실제 실패 사례가 있을 때만 추가 (quick-skill에 write-time 게이트) ② **기존 열거는 일괄 삭제가 아니라 감사 주기마다 축약 후보 3~5건 선별** → `/harness-bench` Before/After 게이트 통과 시에만 반영 (무검증 대량 삭제는 회귀 위험 — 기존 게이트 규율 유지) ③ 축약해도 안 되는 것: 보안 게이트·사용자 주권(승인·push) 규칙 — 이건 모델 능력과 무관한 정책이다.

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

### Step 6.5 — 온톨로지 vault 갱신 (선택 — 지난 감사 이후 변경량 있을 때)

목적: `~/.claude` 자체를 `/graphify --obsidian`으로 뽑은 하네스 온톨로지 vault(`graphify-out/obsidian/`)를 최신 상태로 유지한다.

```bash
# git pull은 사용자 직접 (하네스 push/pull 사용자 주권 정책 — Claude 자동 실행 금지):
#   사용자에게 아래 실행 요청 후, graphify --update만 스킬이 진행
cd ~/.claude && git pull --ff-only   # ← 사용자 직접 실행
graphify ~/.claude --update --obsidian
```

> **멀티서버 필수**: `git pull` 선행은 생략 불가 — 다른 서버가 먼저 갱신했을 수 있는 비결정적 산출물(LLM 추출) 위에서 증분 빌드해야 충돌이 줄어든다. pull 실패(로컬 미커밋 변경 충돌) 시 Step 6.5 중단, 무리한 진행 금지 — 상세: `rules-lazy/code-graph.md` §7.1.

> **왜 git hook이 아니라 이 스킬 주기에 편입했는가**: 하네스 콘텐츠는 대부분 마크다운(rules/agents/skills)이라 semantic 추출에 LLM(에이전트 세션 dispatch)이 필요하다 — `.git/hooks/pre-commit`(`ci-gate-commit.sh`)처럼 순수 bash만 도는 훅에서는 이 단계를 자동화할 수 없다 (코드 파일 전용 `scripts/graphify-autoindex.sh`와 다른 이유로 하네스가 그 훅에서 명시적으로 제외돼 있음 — § "하네스 격리" 참조). 이미 존재하는 30일 주기 self-upgrade 루프에 얹는 것이 가장 저비용이다.

지난 감사 이후 rules/agents/skills 변경이 없었으면 스킵(토큰 절약). `--update`가 "No files changed since last run"을 출력하면 그대로 스킵. vault 변경분은 § 완료 기록 커밋에 함께 포함 — **push는 하지 않는다** (하네스 표준 정책: push는 항상 사용자 직접).

운영 주의 2건 (`rules-lazy/code-graph.md` §7 실측 근거):
- **read-once 우회**: main이 이 세션에서 이미 Read한 파일은 추출 서브에이전트가 차단돼 스텁이 된다 → spawn prompt에 "Read 차단 시 offset/limit 부분 읽기로 우회" 1줄 포함.
- **갱신 후 건강 점검**: Step 4.5 진단(dangling/self-loop) 1회 실행 — 이전 빌드 대비 dangling 수가 **증가**하면 스텁·ID 불일치 신호로 보고.

### Step 7 — 의미 정합 전수 정독 (정밀 모드 — 모델 전환 전·대규모 변경 후 필수)

목적: 기계 점검이 못 잡는 상호 모순·실행 불가능 지시·특정 모델 전제를 잡는다. **qa subagent 5분할 병렬 fan-out** (2026-07-06 감사에서 검증된 분할):

| # | 영역 | 대상 |
|---|------|------|
| 1 | always-on | CLAUDE.md + rules/*.md |
| 2 | lazy 전반 | rules-lazy/ a~l |
| 3 | lazy 후반 | rules-lazy/ m~z |
| 4 | 에이전트·스킬 | agents/*.md + skills/*/SKILL.md |
| 5 | 배선 | settings.json hooks ↔ scripts/ 정합 |

spawn prompt 필수 요소 (4요소 + 아래 특칙):
- 점검 관점 4종: ① 실행 가능성(그 파일만 읽고 실행 가능한가) ② 상호 모순(파일 간 수치·기준) ③ 특정 모델 전제 잔재 ④ §헤딩 참조 실재성
- output_format: 파일별 ✅/⚠️ + 발견당 `{파일:라인, 문제 1줄, P0/P1/P2, 제안 1줄}` — 600자 요약 상한
- task_boundary: **읽기 전용** + 보안 게이트·훅 내부 패턴 원문 인용 금지("정합/불일치 + 위치"만) — 세션 컨텍스트 오염 방지 (운영 주의: 상세가 대화에 누적되면 안전필터 오탐 유발 이력)
- 알려진 충돌 후보 쌍(Step 5)을 해당 영역 에이전트에 명시 배정

subagent 보고는 **main이 원문 재검증 후** 수정한다 — 액면 수용 금지 (예: "9→10 교정" 지적이 실제론 의도적 9였던 사례).

### Step 8 — 외부 모델 교차검증 (정밀 모드 — 가용 시)

Codex 등 이용 가능한 외부 모델 에이전트로 2차 감사. 프롬프트에 반드시 포함:
- **이미 수정 완료한 항목 목록** (중립 요약) + "이 목록 밖의 신규 결함만" 지시 — 중복 보고 방지
- 점검 요청 4종: ① 이번 수정이 만든 2차 부작용 ② 내부 분할 감사의 구조적 사각지대(카탈로그 문서·plugins·settings 정합) ③ 현재 메인 모델의 능력·거동을 암묵 전제한 서술 ④ 룰 간 우선순위 미정의 지점
- 읽기 전용 + 중립 보고 특칙 동일 적용

## 완료 기록 (MANDATORY — self-upgrade 루프의 닻)

감사 종료(수정 커밋 완료) 시:
0. **배선·설정류 수정의 실체 확인 (2026-07-16 신설 — 반복 결함 #6)**: settings.json 훅·스크립트 배선 등은 기록 전에 `git show HEAD:파일 | grep` 으로 **커밋된 실체**를 확인 — 워킹트리·계획·대화 로그가 아니라 커밋이 증거다
1. `~/.claude/_audit/last-run` 갱신 — 내용 1줄: `YYYY-MM-DD {커밋범위} {발견 N건/수정 M건} {판정 1줄}` (T03 주기 체크의 기준점)
2. `~/.claude/_audit/history.md` append — 실행 일자·범위(기계/정밀)·발견 요약·커밋 해시 + **수정별 [구조|조정] 분류와 직전 감사 수정의 hit 여부** (§ 반복 결함 표 하단 분류 규칙). history.md는 git 추적(repo 단위 지식 — 온톨로지 코퍼스 편입, 2026-07-13 전환), `last-run` 신선도 마커만 로컬
3. 반복 결함 패턴 → Mem0 저장 (`category: code_pattern`, `source: harness-audit`) + 본 스킬 § 반복 결함 우선 체크 표에 신규 패턴 반영 제안 (사용자 승인 시 편집 — 이것이 self-upgrade)
4. 수정이 있었으면 효과 측정이 필요한 변경(행동 규칙류)에 한해 `/harness-bench` 게이트 제안
5. **감사 기준선 태그 제안**: `audit/{YYYY-MM-DD}` — 승인 시 생성 (`agents/gitops.md` § 태그 규칙). 대규모 룰 변경을 시작하는 감사면 변경 직전 `pre-{변경명}-{MMDD}` 롤백 앵커도 함께 제안
6. **공개 미러 갱신 제안 (2026-07-23 신설)**: 지난 감사 이후 rules·agents·skills 변경이 있었으면 "공개 미러(oh-my-ouroboros)도 갱신할까요?" 제안 — 수락 시 `bash scripts/public-export.sh` dry-run 결과(게이트 통과 + 변경 트리) 확인 후 `--publish` 및 push는 사용자 직접. 게이트 차단 시 `config/public-export-rules.txt`에 s|/x| 규칙 추가로 해소.

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

- 권장 주기: 메인 모델 전환 전 필수(Step 1~8) / 월 1회 기계 점검(Step 1~6, 변경량 있으면 Step 6.5 포함) / 대규모 룰 변경 직후 — 주기 상기는 T03 `_audit/last-run` 체크(§ 트리거)
- 결과 중 반복 결함은 Mem0에 저장 (`category: code_pattern`, `source: harness-audit`) → learner/T41(에이전트 약점 평가)과 연계 + § 반복 결함 우선 체크 표 갱신 제안
- 수정 실행은 이 스킬의 범위 밖 — 별도 승인 후 coder/gitops 등에 위임 (사용자가 사전에 일괄 승인한 경우 main 직접 수정 가능)
