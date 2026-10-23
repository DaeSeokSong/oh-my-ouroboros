# Agent Catalog

13 specialized agents with defined roles, models, tools, and routing triggers.

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
| **designer** | Sonnet | Figures, TikZ diagrams, matplotlib plots | Read, Write, Edit, Bash | subagent |
| **docs** | Sonnet | Confluence pages, Jira issues, documentation | Read, Write, Edit, MCP | subagent |
| **gitops** | Sonnet | Git commit, branch, diff, log, stash | Bash(git), Read | subagent |
| **citation-verifier** | Sonnet | Citation trust verification — retraction/correction detection + stance debate (scite replacement) | WebFetch, WebSearch, scientific-papers/arxiv-latex/tavily MCP | subagent |
| **tutor** | Opus | User-comprehension teacher — quiz → misconception diagnosis → step-down re-explanation → re-quiz until all correct (an item exhausted at ladder rung 6 is handed off as "tutor limit" and excluded); external material only via searcher (`NEEDS_SEARCH`) | Read, Grep, Glob, Write/Edit (quiz.md·quiz-key.md·primer.md·math-notes.md in the artifact folder only; `quiz-search.log`·`quiz-visual.log`·`artifact-log.tsv`·`artifact/study.html` are main-only) | subagent (main relays rounds via SendMessage) |

> **Note**: For `/discuss` sessions any agent may be summoned as a teammate (SendMessage-capable) via `TeamCreate` — `researcher` is the most common, but architecture debates summon planner/coder etc. (see canonical examples in `rules/agent-routing.md`). Outside discussions, all run subagent-only.

---

## Agent Detail

### searcher
- **Trigger**: "검색해", "찾아봐", internet resource needed, paper lookup
- **Constraints**: Always called by other agents — never directly performs code edits
- **Special**: All agents may freely summon searcher for search sub-tasks
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
- **Constraints**: No execution — writes to file only; user runs
- **Special**: Calls scout before writing to understand impact scope
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

### designer
- **Trigger**: Figure generation, TikZ diagrams, matplotlib plots, "그림 그려", "시각화"
- **Standards**: TikZ for structural diagrams; matplotlib for data plots
- **Output**: Saved to `docs/paper/figures/` (or project-specified path)

### docs
- **Trigger**: Confluence page create/update, Jira issue, "문서화", "컨플루언스"
- **Protocol**: 3-step confirmation before any Confluence update (see CLAUDE.md)
- **MCP**: Uses Confluence MCP + Jira MCP; Jira comments only via `scripts/jira_comment.py` (preview → user approval → post·update), never the MCP comment tool

### gitops
- **Trigger**: "커밋해", "브랜치", "diff", "로그", git operations
- **Constraints**: push/pull are user-only — gitops only handles local git ops
- **Output**: Commit message following `{issue} {type}: {Subject}` format

### citation-verifier
- **Trigger**: right before citing a paper in text/experiments; SOTA baseline or domain-mechanism references; pre-2020 citations (routing 3.6)
- **Modes**: advocate + skeptic in parallel → synthesis debate; retraction gate (Crossref + OpenAlex) runs first
- **Constraints**: returns verdict only — no file writes (untrusted isolation); caller (main) stores results (mem0 T21 + detail log per `rules-lazy/citation-verification-log.md`)
- **Verdict**: 허용 / 경고 / 금지 with supporting/contrasting/mentioning counts and confidence

### tutor
- **Trigger**: "이해 안 돼", "다시 설명해줘", "퀴즈 내줘", "가르쳐줘" on an existing artifact; /paper-read Step 7 and /research close-out after conclusions are confirmed by the key-paper deep read (mandatory); /discuss and /experiment reports (offered)
- **Modes**: quiz / diagnose (misconception type: term·formula·causality·number·context) / reteach (explanation ladder, one rung lower per round) / verify (re-quiz wrong items only) / explain (math·science concept note + ELI5 Q&A, no quiz)
- **Constraints**: no web access — emits `NEEDS_SEARCH`, main runs searcher and feeds back the summary; writes only `quiz.md` (questions, round log) and `quiz-key.md` (answers, opened by main only at grading); questions and answers must be grounded in the artifact (notes/review) — external material is auxiliary and labeled
- **Exit**: all questions answered correctly (+ integration check), or user stops, or an item stuck at ladder rung 6 is handed off as "tutor limit" and excluded from the loop; main records rounds and final score in Mem0

---

## Routing Priority

> **Canonical**: `rules/agent-routing.md` § 라우팅 테이블 (24 rows, first-match wins). The table below is a condensed mirror for quick lookup — **on any conflict the canonical file wins**, and edits must land there first.

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
| 3.75 | Follow-up question on the previous report's math/science note, or a concept that needs a formula | tutor `explain` (mandatory; `math-notes.md` + ELI5 Q&A, no quiz; spawn prompt names `mode=explain`) | designer (`NEEDS_VISUAL`) · searcher (`NEEDS_SEARCH`, return-only) · continue to a quiz only after user accepts, via 3.8 |
| 3.8 | Comprehension help on an existing artifact ("이해 안 돼", "퀴즈 내줘"), paper-read Step 7, research close-out (after key-paper deep read confirms conclusions) | tutor (via main, after main confirms artifact type: paper review / research report / experiment report / none) | searcher (`NEEDS_SEARCH`, max 3 per artifact, main counts via `quiz-search.log`) · if none, ask the type; papers → /paper-read sequentially first; experiment reports proceed directly |
| 4 | File/symbol search | scout | — |
| 4.85 | Start of a non-trivial task (experiment, feature, harness `feat:`), "의뢰서", "왜 하는지부터" | /intent skill (write intent.md → user correction → commit; approval triggers the plan) | `superpowers:writing-plans` (plan.md) · 4.9 brainstorming comes after intent |
| 4.9 | New feature/system design (pre-implementation) | brainstorming opt-in | planner/coder |
| 5 | Architecture/experiment | planner | researcher |
| 6 | Paper write/analysis | researcher | searcher |
| 7 | Figure/diagram | designer | researcher |
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

Agents may autonomously invoke whitelisted skills after passing all 4 gates:

| Gate | Condition |
|------|-----------|
| 1 | Skill is in agent's whitelist (agents/*.md) |
| 2 | Task cannot complete without skill |
| 3 | Quality threshold unmet without skill |
| 4 | Context < 60% |

`SKILL_DEPTH=1` in spawn prompt disables all skill auto-calls (recursion guard).
