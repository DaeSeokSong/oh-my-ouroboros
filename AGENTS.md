# Agent Catalog

12 specialized agents with defined roles, models, tools, and routing triggers. Figures are not an agent: main draws them with the `/figure` skill (designer was folded into that skill on 2026-11-10).

> **Picking up a session (Grok or any other model, 2026-10-23)**: every session keeps a work-status card at `<project root>/.scratch/handoff/<first 8 chars of the session id>.md` (harness manager: `~/.claude/.scratch/handoff/`). Read the most recent one first, follow its «이어받는 이에게» and «4. 다음 할 일» sections, ask the user about anything under «결정 대기», and keep updating the same file. The harness rules (CLAUDE.md, rules/, rules-lazy/) still apply; pushes, training launches and external posts stay with the user. Format and update points: `rules-lazy/session-handoff.md`.

---

## Agent Table

| Agent | Model | Role | Core Tools | Invocation |
|-------|-------|------|-----------|------------|
| **searcher** | Sonnet | Internet search — papers, library docs, tech articles | Tavily MCP, WebSearch, WebFetch | subagent |
| **scout** | Haiku | Codebase recon + project structure analysis (deepinit mode) | Glob, Grep, Read, Bash(read-only) | subagent |
| **planner** | Opus | Architecture design, experiment planning, workflow | Read, Glob, Grep | subagent |
| **coder** | Sonnet | Code write/modify/review + conditional refactor | Read, Write, Edit, Bash | subagent |
| **qa** | Sonnet | Validation, test execution, bug tracing (tracer mode), Ralph loop | Read, Grep, Glob, Bash, Edit(FAIL fixes · paper-read qa-report.md only) | subagent |
| **security** | Sonnet | Code vulnerability review — injection/authz/secret exposure/supply chain (4 lenses), /security-review + claude-security plugin liaison | Read, Grep, Glob, Bash | subagent |
| **reviewer** | Opus | One-function-at-a-time DFS code review — gaps between design intent and code (unjustified constants, comment/code mismatch, unreachable branches, deviation from design docs); method in `rules-lazy/code-review-dfs.md` | Read, Grep, Glob, Bash | subagent |
| **researcher** | Opus | Paper writing, experiment analysis, critical design evaluation | Read, Write, Edit | subagent / teammate |
| **docs** | Sonnet | Confluence and Jira drafts (fetch and publish stay with main) | Read, Write, Edit | subagent |
| **gitops** | Sonnet | Git commit, branch, diff, log, stash | Bash(git), Read | subagent |
| **citation-verifier** | Sonnet | Citation trust verification — retraction lookup + check of the cited numbers against the source tables (default), stance debate only for contested citations (scite replacement) | WebFetch, WebSearch, scientific-papers/arxiv-latex/tavily MCP | subagent |
| **tutor** | Opus | User-comprehension teacher — quiz → misconception diagnosis → step-down re-explanation → re-quiz until all correct (an item exhausted at ladder rung 6 is handed off as "tutor limit" and excluded); external material only via searcher (`NEEDS_SEARCH`) | Read, Grep, Glob, Write/Edit (quiz.md·quiz-key.md·primer.md·math-notes.md in the artifact folder only; `quiz-search.log`·`quiz-visual.log`·`artifact-log.tsv`·`artifact/study.html` are main-only) | subagent (main relays rounds via SendMessage) |

> **Note**: For `/discuss` sessions any agent may be summoned as a teammate (SendMessage-capable) via `TeamCreate` — `researcher` is the most common, but architecture debates summon planner/coder etc. (see canonical examples in `rules/agent-routing.md`). Outside discussions, all run subagent-only.

---

## Agent Detail

### searcher
- **Trigger**: "검색해", "찾아봐", internet resource needed, paper lookup
- **Constraints**: Summoned by main only (on main's own judgment or on an agent's `NEEDS_SEARCH`) — never directly performs code edits
- **Special**: Agents cannot spawn it directly; they emit `NEEDS_SEARCH` and main summons searcher and relays the result
- **Tavily**: Uses `search` for general queries, `extract` for full-page content

### scout
- **Trigger**: "파일 찾아", "코드 어디", project structure unknown, before coder/qa
- **Modes**:
  - Standard: symbol/file search via Glob + Grep
  - deepinit: full project structure analysis for new projects
- **Output**: File list + dependency graph + impact scope

### planner
- **Trigger**: Architecture design, experiment planning, "설계해", workflow creation
- **Constraints**: Delegates all search to searcher; no direct internet access
- **Output**: Phase plan with gate conditions, team composition, artifact list

### coder
- **Trigger**: Code write, modify, bug fix, new module
- **Constraints**: No execution except verification runs (pytest, dry-run, ruff/mypy read-only) — writes to file only; user runs the rest
- **Special**: Needs scout recon before writing; main summons scout and passes the result (coder emits `NEEDS_CONTEXT` if it is missing)
- **Refactor guard**: No refactoring during active experiments

### qa
- **Trigger**: After code changes, test execution, "검증해", "테스트해"
- **Modes**:
  - Standard: syntax/import check, test run, PASS/FAIL report
  - tracer: causal bug tracing — follows call chain to root cause
  - ralph-loop: auto-retry loop until tests pass (5-Gate guarded)
- **Ralph Wiggum Loop**: Max N retry rounds; escalates to main on convergence failure

### researcher
- **Trigger**: Paper writing, experiment analysis, "논문", "비교 분석", critical evaluation
- **Teammate mode**: Participates in `/discuss` sessions with SendMessage
- **Constraints**: Delegates search to searcher; does not execute code

### docs
- **Trigger**: Confluence page create/update, Jira issue, "문서화", "컨플루언스"
- **Protocol**: writes drafts only; fetching and publishing stay with main (`skills/confluence/SKILL.md` §3)
- **Writing only (2026-11-10)**: no wiki or memory connection. docs writes draft files (`*.storage.html`, patch lists, comment bodies) and returns their paths; main fetches pages, reviews the draft, then asks for a rewrite or publishes. Before publishing, code blocks a body whose hash differs from the reviewed one or that holds a credential or patient-id shape (`skills/confluence/SKILL.md` §3-1). Jira comments only via `scripts/jira_comment.py` run by main (preview → user approval → post·update)

### gitops
- **Trigger**: "커밋해", "브랜치", "diff", "로그", git operations
- **Constraints**: push/pull are user-only — gitops only handles local git ops
- **Output**: Commit message following `{issue} {type}: {Subject}` format

### citation-verifier
- **Trigger**: right before citing a paper in text/experiments; SOTA baseline or domain-mechanism references; pre-2020 citations (routing 3.6)
- **Modes**: default `대조` (check) runs once: retraction gate (Crossref + OpenAlex) → source full text → each cited number or claim marked match / mismatch / not in source. Optional for contested citations: advocate + skeptic in parallel → synthesis debate. Separate review-collection mode.
- **Constraints**: returns verdict only — no file writes (untrusted isolation); caller (main) stores results (mem0 T21 + detail log per `rules-lazy/citation-verification-log.md`)
- **Verdict**: 허용 / 경고 / 금지 with per-claim check results (and supporting/contrasting/mentioning counts when debated) and confidence

### tutor
- **Trigger**: "이해 안 돼", "다시 설명해줘", "퀴즈 내줘", "가르쳐줘" on an existing artifact; /paper-read Step 7 and /research close-out after conclusions are confirmed by the key-paper deep read (mandatory); /discuss and /experiment reports (offered)
- **Modes**: quiz / diagnose (misconception type: term·formula·causality·number·context) / reteach (explanation ladder, one rung lower per round) / verify (re-quiz wrong items only) / explain (math·science concept note + ELI5 Q&A, no quiz)
- **Constraints**: no web access — emits `NEEDS_SEARCH`, main runs searcher and feeds back the summary; writes only `quiz.md` (questions, round log), `quiz-key.md` (answers, opened by main only at grading), `primer.md` and `math-notes.md`; questions and answers must be grounded in the artifact (notes/review) — external material is auxiliary and labeled
- **Exit**: all questions answered correctly (+ integration check), or user stops, or an item stuck at ladder rung 6 is handed off as "tutor limit" and excluded from the loop; main records rounds and final score in Mem0

---

## Routing Priority

> **Canonical**: `rules/agent-routing.md` § 라우팅 테이블 (25 rows, first-match wins). The table below is a condensed mirror for quick lookup — **on any conflict the canonical file wins**, and edits must land there first.

| Priority | Trigger | Primary Agent | Secondary |
|----------|---------|---------------|-----------|
| 0.5 | 2+ independent tasks (paper reviews always go to 3.5) | parallel-dispatch | qa/coder/scout/searcher |
| 0.7 | Repeat/monitor pattern | /loop skill | ralph-loop (qa) |
| 1 | Code modify/write | scout → coder | qa ∥ security |
| 1.9 | Branch/module full code review, "파고들어", design-intent comparison (narrower than row 2, so above it) | reviewer (reads `rules-lazy/code-review-dfs.md` first, returns one function at a time) | main Q&A/records, user decides, coder applies in bulk |
| 2 | Code review/validate | scout → qa ∥ security | coder |
| 2.5 | Bug root cause | scout → qa (tracer) ∥ security | coder |
| 2.6 | New project structure | scout (deepinit) | — |
| 2.7 | Security review/vulnerability check | security | /security-review (light) · claude-security plugin (deep, depth gate) |
| 3 | Internet search (paper/arXiv keywords → 3.5 wins, narrower trigger) | searcher | researcher |
| 3.5 | Paper search/read (any number of papers) | /paper-read skill | searcher → citation-verifier → scout → main(triage) → researcher×3 → qa → docs → tutor |
| 3.6 | Citation trust check (pre-citation) | citation-verifier | searcher |
| 3.7 | Deep multi-source research | /research skill | searcher/citation-verifier/researcher → tutor (close-out, mandatory) |
| 3.75 | Follow-up question on the previous report's math/science note, or a concept that needs a formula | tutor `explain` (mandatory; `math-notes.md` + ELI5 Q&A, no quiz; spawn prompt names `mode=explain`) | main via `/figure` skill (`NEEDS_VISUAL`) · searcher (`NEEDS_SEARCH`, return-only) · continue to a quiz only after user accepts, via 3.8 |
| 3.8 | Comprehension help on an existing artifact ("이해 안 돼", "퀴즈 내줘"), paper-read Step 7, research close-out (after key-paper deep read confirms conclusions) | tutor (via main, after main confirms artifact type: paper review / research report / experiment report / none) | searcher (`NEEDS_SEARCH`, max 3 per artifact, main counts via `quiz-search.log`) · if none, ask the type; papers → /paper-read sequentially first; experiment reports proceed directly |
| 4 | File/symbol search | scout | — |
| 4.85 | Start of a non-trivial task (experiment, feature, harness `feat:`), "의뢰서", "왜 하는지부터" | /intent skill (write intent.md → user correction → commit; approval triggers the plan) | `superpowers:writing-plans` (plan.md) · 4.9 brainstorming comes after intent |
| 4.9 | New feature/system design (pre-implementation) | brainstorming opt-in | planner/coder |
| 5 | Architecture/experiment | planner | researcher |
| 5.5 | Experiment design with training being confirmed (new round/arm, paper experiment) | researcher "review-angle check" mandatory (`rules-lazy/design-review-check.md`, report = `.review.md` beside the intent doc) | citation-verifier (collect reviewer comments) · user decides to proceed |
| 6 | Paper write/analysis | researcher | searcher |
| 7 | Figure/diagram | main via `/figure` skill (ask who draws first via decision popup: figure skill · Codex image generation · Grok · another connected agent; the mod enforces it) | researcher |
| 8 | Confluence/Jira | docs | — |
| 8.5 | Git operations | gitops | — |
| 9 | Discussion/debate | TeamCreate → teammates | /discuss skill |
| 10 | Simple Q&A | main direct | — |

---

## Invocation Modes

### Subagent (Single Task)
```
Agent(subagent_type="coder", description="sonnet: Modify loss function")
```

### Teammate (Discussion)
```
TeamCreate(team_name="arch-review")
Agent(team_name="arch-review", name="researcher", ...)
Agent(team_name="arch-review", name="planner", ...)
```

> Teammates use SendMessage for cross-agent communication. Required for `/discuss` sessions.

---

## Skill Auto-Call (4-Gate)

Agents have no Skill tool: they request a whitelisted skill from main via `NEEDS_SKILL: <skill> <reason>`, and main decides using the 4 gates below (on any conflict `rules/agent-routing.md` wins):

| Gate | Condition |
|------|-----------|
| 1 | Skill is in agent's whitelist (agents/*.md) |
| 2 | Task cannot complete without skill |
| 3 | Quality threshold unmet without skill |
| 4 | Context < 60% |

`SKILL_DEPTH=1` in spawn prompt disables all skill calls (recursion guard).
