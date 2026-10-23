# Rule System

Rules are split into two tiers: **eager** (always loaded) and **lazy** (on-demand).

---

## Design Principle

Context is finite. Loading every rule on every turn wastes ~30–50K tokens per session.

```
rules/       ← 5 files, always loaded (CLAUDE.md + rules/*.md = 73,054B (2026-10-02 실측) — 예산 75,000B, 초과는 경고만)
rules-lazy/  ← 51 files, loaded only when triggered
```

A lazy rule loads only when its trigger condition fires within the current turn. After loading, it applies for that turn and is not re-loaded unless triggered again.

### Rule Conflict Priority Ladder

`CLAUDE.md` opens with a 10-level ladder (higher wins): user's latest explicit instruction → security/isolation → execution separation & irreversible gates → HARD BAN/HARD GATE → decision sovereignty & completion gate → MANDATORY procedures → routing/skill suggestion → non-MANDATORY style conventions → narrower-trigger tiebreak → ask-user-if-tied. Rule authors place new rules at the correct ladder level instead of inventing local precedence.

### Enforcement, Not Just Text

`scripts/ci-gate-commit.sh` measures the 75,000B always-on budget at commit time. Since 2026-10-01 (user decision) an overrun is a warning only and the commit proceeds; secret, lint and pointer checks still FAIL and block. Text-only "hard block" claims without a matching hook were the gap the gate closed.

### Cross-Cutting MANDATORY Principles

Three principles sit above individual rule files and gate every turn. Their full text lives in `CLAUDE.md` (canonical, principles 3.5, 7.5, and 6), not duplicated here:

- **Pre-work 3-line summary**: for task-type requests only (implies a tool call/file change/experiment/commit/external send) — factual questions and opinion-only talk are excluded — state 3 lines (what/how/why) under a single `[이해]` header. Turn ordering: `[cache detected]`, then the 3 lines, then any gate question, then the body.
- **Decision sovereignty** (detail: `rules-lazy/decision-sovereignty.md`): no recommended options on user-owned decisions, only item plus one-line history plus one-line conclusion.
- **Completion gate**: no "done/passed/fixed" claim without executed verification evidence, checked against the original request for omissions.

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
Defines all 13 agents, routing priority table (24 rows, 0.5–10), TeamCreate duplicate guard, SKILL_DEPTH propagation protocol, and `/discuss` recursion exception.

### `mem0-auto.md`
T01~T41 auto-triggers covering decision capture, compact backup, session restore, QA failures, experiment results, paper reviews, and user feedback. Includes 3-axis Smart Retrieval (History/Current/Future) and project-name isolation pattern.

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
| `background-task.md` | Background execution | bg session + systemd auto-restore + 학습 발사 2종 세트(memguard cgroup 래퍼·train watcher) |
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
| `codex-model-gate.md` | codex·grok 위임 직전 (작업 사이클당 1회) | 모델(Sol/Terra/Luna/기타)·effort(≤xhigh 플러그인, max 직접 exec) 선택 게이트 — config 기본값 제거와 한 쌍 |
| `security-scan-gate.md` | claude-security 플러그인 스캔 직전 (매회) | 깊이(Instant~max)·범위 선택 게이트 — max=754k+ 토큰 실사용 근거, 최초 실행 플랜 검증 절차 |
| `notification-turn-reduction.md` | 알림 턴 처리 방침·보고 1회 규칙 근거 확인 시 | 프롬프트1회·알림 턴 감축의 근거·경위·실측 원문 (agent-routing 해당 § 상세) |
| `knowledge-capture.md` | 대화 중 재사용 가능 지식 확정 시 (CLAUDE.md 10.5) | knowledge/<프로젝트>/ 노트 즉시 작성 → 일간 빌드가 온톨로지 편입 — 트리거·스키마·중복 방지 |
| `agent-eval.md` | 재작업·부정 피드백·qa FAIL 신호 시 | T41 약점 축적 — 동일 약점 3회+ 시 agents 개선, 조정 2회 무효 시 구조 전환 게이트 |
| `agent-personas.md` | 페르소나·비판 모드 커스터마이즈 시 | 페르소나 카탈로그 11종 × 3 (citation-verifier 는 자체 3모드) + 4 비판 모드 |
| `doc-format-registry.md` | 프로젝트 관련 문서 작성·수정 전 (Confluence·연구 기록 등) | 프로젝트별 문서 양식 단일 인덱스 + 필수 조회 게이트 + 미등록 부트스트랩 |
| `citation-verification-log.md` | 논문 검증 완료 후 기록 시 | 2층 저장(T21 요약+상세 로그) — 저장 주체는 main, verifier는 payload 반환만 |
| `dynamic-workflow.md` | Workflow 도구(모드 B) 검토 시 | 사용자 opt-in 필수 — over-application 금지 |
| `error-handling.md` | 도구 차단·MCP 불가·명령 실패 시 | 에러 5분류·재시도 한도·침묵 재시도 금지 |
| `learner.md` | 교정 반복·룰 신설 검토 시 | 자동 패턴 분석 + Zero-Sum 토큰 예산 |
| `llm-judge-practices.md` | judge/평가 설계 시 | LLM judge 모범 사례 |
| `mcp-health-check.md` | OAuth MCP 호출 직전 | 가용성 확인 → 미연결 시 사용자 조치 3택 |
| `mem0-conventions.md` | mem0 저장/검색 호출 직전 | 프로젝트명 식별·매칭 검색·중복 방지·쓰기 provenance(§C-2)·Smart Retrieval 상세 |
| `memory-promotion.md` | 장기 승격·만료 처리 시 | short→long 승격 기준·만료 절차 |
| `prompt-routing-detail.md` | Step 0.5/1.5/1.7 상세 필요 시 | 전처리 상세 — cache 분류·모델 접두사·생략 조건 |
| `rollback-procedure.md` | 거짓 전제 감지·작업 되돌리기 시 | 롤백 절차 — 사용자 변경 보존 |
| `skill-autonomy.md` | 에이전트 스킬 자율 호출 판단 시 | 4-Gate + SKILL_DEPTH 전달 규약 |
| `tool-access-policy.md` | 새 외부 연동 검토 시 | CLI/API-in-Skill 우선 — MCP는 조건 한정 + deferred loading |
| `untrusted-quarantine.md` | 외부 콘텐츠 열람 후 고권한 행동 전 | 격리 → 구조화 반환 → main 실행 (Mem0 쓰기 금지 포함) |
| `peer-session-messages.md` | 타 세션·서버 Claude 피어 메시지 수신 시 | 자기 권한 범위만·에스컬레이션 불가·permission laundering 거부+surface |
| `before-after-report.md` | 적용 전후가 나뉘는 변경 보고 시 | 전·후 각각 무엇을·어떻게·왜 6줄 + 수치 예시 + 도해 |
| `code-execution-detail.md` | 임시·최종 코드 저장 위치 결정·다른 저장소 관련 시 | code-execution.md 의 프로젝트 경계·코드 저장 규칙 정본 상세 |
| `code-review-dfs.md` | 브랜치·모듈 전수 코드 리뷰 시작 시 | 한 함수씩 파고드는 DFS 리뷰 방법론(실행은 reviewer·main) |
| `decision-sovereignty.md` | 사용자 결정 지점 발견·AskUserQuestion 직전 | 추천·유도 금지, 선택지는 장단점 표 |
| `oversight-signature.md` | 비가역 게이트 결정 직후·서명 로그 집계 시 | 감시 품질 서명 기록(oversight-append.sh) |
| `pre-work-summary.md` | 원칙 3.5 근거·적용 범위 확인 시 | 작업 전 3줄 요약 형식·실사고 근거 |
| `uv-env.md` | 프로젝트 첫 작업·venv 오류·서버 이전 시 | uv 관리 파이썬 강제 |

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
All commits pass `scripts/ci-gate-commit.sh`, which scans the staged content for secret-shaped patterns (API-key formats, generic `API_KEY=`/`TOKEN=`/`PASSWORD=` assignments, private-key headers). `bash-write-check.sh` only blocks shell write redirections; it does not scan content.

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
