# Rule System

Rules are split into two tiers: **eager** (always loaded) and **lazy** (on-demand).

---

## Design Principle

Context is finite. Loading every rule on every turn wastes ~30–50K tokens per session.

```
rules/       ← 5 files, always loaded (~780 lines incl. CLAUDE.md, 64KB — _audit 기준선 참조)
rules-lazy/  ← 30+ files, loaded only when triggered
```

A lazy rule loads only when its trigger condition fires within the current turn. After loading, it applies for that turn and is not re-loaded unless triggered again.

---

## Eager Rules (`rules/`)

| File | Load Point | Core Principle | Key Sections |
|------|-----------|----------------|--------------|
| `agent-routing.md` | Always | Route first match from priority table | Agent table, routing priority, spawn guards |
| `mem0-auto.md` | Always | Mem0 triggers are automatic — no user prompt needed | §1 metadata, §2 trigger table T01~T41, §4 infer strategy |
| `model-assignment.md` | Always | Non-Opus work → subagent by default | §1 Opus conditions, §2 Sonnet, §3 Haiku, §4 delegation rules |
| `prompt-routing.md` | Always | Clarify before execute | Step 0~3: CLAUDE.md check, ground truth, clarification, model dispatch |
| `code-execution.md` | Always | Write to file; user runs | Execution prohibition, auto-allow (read-only), Figure exception |

### `agent-routing.md`
Defines all 10 agents, routing priority table (0.5–10), TeamCreate duplicate guard, SKILL_DEPTH propagation protocol, and `/discuss` recursion exception.

### `mem0-auto.md`
37 auto-triggers covering decision capture, compact backup, session restore, QA failures, experiment results, paper reviews, and user feedback. Includes 3-axis Smart Retrieval (History/Current/Future) and project-name isolation pattern.

### `model-assignment.md`
Opus handles math, biology, architecture, cross-module deps, complex debug, and user consensus. Sonnet handles code implementation, docs, git. Haiku handles file search, simple edits, format conversion, test execution.

### `prompt-routing.md`
Step 0: CLAUDE.md check. Step 0.5: Continuation ground truth. Step 1: Clarification (8 ambiguity patterns). Step 1.5: Model dispatch with pre-report. Step 1.7: Repeat-pattern preprocessing skip.

### `code-execution.md`
Code → file → user runs. Read-only commands auto-allowed. Figure scripts (`gen_*.py` under `docs/paper/figures/scripts/`) are the only AI-executable exception.

---

## Lazy Rules (`rules-lazy/`)

| File | Trigger | Core Principle |
|------|---------|----------------|
| `qa-process.md` | After code changes | Goal-driven QA: objective PASS/FAIL criteria only |
| `context-management.md` | 75% context / compact | Mem0 backup → handover.md → compact order |
| `coding-conventions.md` | PyTorch/ML code | Experiment-safe conventions, no mid-experiment refactor |
| `mem0-templates.md` | Any Mem0 T-trigger | T01~T41 call templates with exact field specs |
| `mem0-fields.md` | Mem0 category lookup | 7 category field catalogs + combination examples |
| `answer-detail.md` | Technical explanation | 4-step param explanation; code/formula analogy section |
| `experiment-result-explanation.md` | 실험 결과 보고·문서화 | 전체표→축별 분해(이상값 row)→열/행 해석→종합 순서 고정 (프로젝트 무관) |
| `background-task.md` | Background execution | bg session + systemd auto-restore rules |
| `loop-auto.md` | Repeat pattern detected | /loop cost table, interval/dynamic modes |
| `parallel-dispatch.md` | 2+ independent tasks | Parallel Task dispatch guard, shared-state check |
| `tavily-auto.md` | Internet search | Tavily tool selection, credit budget, query format |
| `token-efficiency.md` | Context > 50% | Search limit caps, lazy load priority order |
| `mcp-fallback.md` | MCP disconnected | Fallback chain: Mem0 → file, Confluence → draft |
| `mcp-fallback-mem0.md` | Mem0 MCP error | Mem0-specific fallback to `decisions.md` write |
| `model-assignment-rules.md` | After model dispatch | Delegation guard, execution separation, tool limits |
| `agent-routing-mcp.md` | Agent spawn | MCP preset per agent, ToolSearch mandatory |
| `memory-write.md` | Decision reached | Short-term/long-term split write protocol |
| `prompt-routing-recommend.md` | Step 2~3 | Agent/rule/skill recommendation table |
| `secret-management.md` | Secret/credential detected | No hardcode; env var only; CI gate patterns |
| `scope-gate.md` | Edit/Write 호출 직전 (ralph loop·G-E Loop) | PreToolUse hook scope gate — 상세: rules-lazy/scope-gate.md |
| `tool-dependency-gate.md` | 작업이 전제하는 도구·설정 부재 감지 시 | 3택 게이트(설치 위임/직접/미사용) + mem0 재질문 방지 + 서드파티 스킬 격리 검토 특칙 |
| `code-graph.md` | 대형 프로젝트 정찰·변경영향 분석 / graphify-out 보유 프로젝트 질문 | Graphify 코드 그래프 게이트·소비·§7 하네스 온톨로지·§8 무인 자동 갱신 타이머 |
| `codex-model-gate.md` | codex 위임 직전 (매회) | 모델(Sol/Terra/Luna/기타)·effort(≤xhigh 플러그인, max 직접 exec) 선택 게이트 — config 기본값 제거와 한 쌍 |
| `knowledge-capture.md` | 대화 중 재사용 가능 지식 확정 시 (CLAUDE.md 10.5) | knowledge/<프로젝트>/ 노트 즉시 작성 → 일간 빌드가 온톨로지 편입 — 트리거·스키마·중복 방지 |
| `agent-eval.md` | 재작업·부정 피드백·qa FAIL 신호 시 | T41 약점 축적 — 동일 약점 3회+ 시 agents 개선, 조정 2회 무효 시 구조 전환 게이트 |
| `agent-personas.md` | 페르소나·비판 모드 커스터마이즈 시 | 9 에이전트 × 3 페르소나 + 4 비판 모드 |
| `doc-format-registry.md` | 프로젝트 관련 문서 작성·수정 전 (Confluence·연구 기록 등) | 프로젝트별 문서 양식 단일 인덱스 + 필수 조회 게이트 + 미등록 부트스트랩 |
| `citation-verification-log.md` | 논문 검증 완료 후 기록 시 | 2층 저장(T21 요약+상세 로그) — 저장 주체는 main, verifier는 payload 반환만 |
| `dynamic-workflow.md` | Workflow 도구(모드 B) 검토 시 | 사용자 opt-in 필수 — over-application 금지 |
| `error-handling.md` | 도구 차단·MCP 불가·명령 실패 시 | 에러 5분류·재시도 한도·침묵 재시도 금지 |
| `learner.md` | 교정 반복·룰 신설 검토 시 | 자동 패턴 분석 + Zero-Sum 토큰 예산 |
| `llm-judge-practices.md` | judge/평가 설계 시 | LLM judge 모범 사례 |
| `mcp-health-check.md` | OAuth MCP 호출 직전 | 가용성 확인 → 미연결 시 사용자 조치 3택 |
| `mem0-conventions.md` | mem0 저장/검색 호출 직전 | 프로젝트명 식별·매칭 검색·중복 방지·Smart Retrieval 상세 |
| `memory-promotion.md` | 장기 승격·만료 처리 시 | short→long 승격 기준·만료 절차 |
| `prompt-routing-detail.md` | Step 0.5/1.5/1.7 상세 필요 시 | 전처리 상세 — cache 분류·모델 접두사·생략 조건 |
| `rollback-procedure.md` | 거짓 전제 감지·작업 되돌리기 시 | 롤백 절차 — 사용자 변경 보존 |
| `skill-autonomy.md` | 에이전트 스킬 자율 호출 판단 시 | 4-Gate + SKILL_DEPTH 전달 규약 |
| `tool-access-policy.md` | 새 외부 연동 검토 시 | CLI/API-in-Skill 우선 — MCP는 조건 한정 + deferred loading |
| `untrusted-quarantine.md` | 외부 콘텐츠 열람 후 고권한 행동 전 | 격리 → 구조화 반환 → main 실행 (Mem0 쓰기 금지 포함) |
| `peer-session-messages.md` | 타 세션·서버 Claude 피어 메시지 수신 시 | 자기 권한 범위만·에스컬레이션 불가·permission laundering 거부+surface |

### Notable Rules

#### `qa-process.md` — Ralph Wiggum Loop
```
5-Gate check → run test → FAIL → tracer mode → fix → re-run
Max N rounds. Convergence failure → escalate to main.
```
Named for persistent self-retry behavior. QA never accepts vague success criteria ("works fine", "no bugs").

#### `context-management.md` — Compact Protocol
```
Context reaches 75%
  → T02 Mem0 backup (MANDATORY — skip forbidden)
  → Write handover.md
  → /compact
```
Handover preserves: active config, decisions, experiment results, in-progress diffs.

#### `coding-conventions.md` — Experiment Guard
Key rule: **no refactoring during active experiments**. Bug injection risk during training runs outweighs code cleanliness.

#### `secret-management.md` — CI Gate
All commits pass `bash-write-check.sh` which scans for hardcoded secrets, API keys, and absolute paths containing usernames.

---

## Rule Loading Mechanism

Rules are loaded via `Read` tool on the rule file path. The global `CLAUDE.md` contains the always-loaded rules inline, and references lazy rules by path with load conditions.

Lazy rule load pattern in agent prompts:
```
When {trigger} occurs → Read ~/.claude/rules-lazy/{topic}.md → apply
```

---

## Adding a New Rule

See [CONTRIBUTING.md](CONTRIBUTING.md) § Adding a New Rule.

Short version:
1. Decide: eager (always needed) or lazy (conditional)?
2. Place in `rules/` or `rules-lazy/`
3. Add load trigger to `CLAUDE.md` or relevant agent prompt
4. Add entry to this file
5. PR with rule file + CLAUDE.md diff + this file update
