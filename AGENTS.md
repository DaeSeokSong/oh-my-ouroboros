# Agent Catalog

10 specialized agents with defined roles, models, tools, and routing triggers.

---

## Agent Table

| Agent | Model | Role | Core Tools | Invocation |
|-------|-------|------|-----------|------------|
| **searcher** | Sonnet | Internet search — papers, library docs, tech articles | Tavily MCP, WebSearch, WebFetch | subagent |
| **scout** | Haiku | Codebase recon + project structure analysis (deepinit mode) | Glob, Grep, Read, Bash(read-only) | subagent |
| **planner** | Opus | Architecture design, experiment planning, workflow | Read, Glob, Grep | subagent |
| **coder** | Sonnet | Code write/modify/review + conditional refactor | Read, Write, Edit, Bash | subagent |
| **qa** | Sonnet | Validation, test execution, bug tracing (tracer mode), Ralph loop | Read, Grep, Bash, Edit(FAIL fixes only) | subagent |
| **researcher** | Opus | Paper writing, experiment analysis, critical design evaluation | Read, Write, Edit | subagent / teammate |
| **designer** | Sonnet | Figures, TikZ diagrams, matplotlib plots | Read, Write, Edit, Bash | subagent |
| **docs** | Sonnet | Confluence pages, Jira issues, documentation | Read, Write, Edit, MCP | subagent |
| **gitops** | Sonnet | Git commit, branch, diff, log, stash | Bash(git), Read | subagent |
| **citation-verifier** | Sonnet | Citation trust verification — retraction/correction detection + stance debate (scite replacement) | WebFetch, WebSearch, scientific-papers/arxiv-latex/tavily MCP | subagent |

> **Note**: `researcher` can operate as a teammate (SendMessage-capable) for discussion sessions. All others are subagent-only.

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
- **MCP**: Uses Confluence MCP + Jira MCP

### gitops
- **Trigger**: "커밋해", "브랜치", "diff", "로그", git operations
- **Constraints**: push/pull are user-only — gitops only handles local git ops
- **Output**: Commit message following `{issue} {type}: {Subject}` format

### citation-verifier
- **Trigger**: right before citing a paper in text/experiments; SOTA baseline or domain-mechanism references; pre-2020 citations (routing 3.6)
- **Modes**: advocate + skeptic in parallel → synthesis debate; retraction gate (Crossref + OpenAlex) runs first
- **Constraints**: returns verdict only — no file writes (untrusted isolation); caller (main) stores results (mem0 T21 + detail log per `rules-lazy/citation-verification-log.md`)
- **Verdict**: 허용 / 경고 / 금지 with supporting/contrasting/mentioning counts and confidence

---

## Routing Priority

| Priority | Trigger | Primary Agent | Secondary |
|----------|---------|---------------|-----------|
| 0.5 | 2+ independent tasks | parallel-dispatch | qa/coder/scout/searcher |
| 0.7 | Repeat/monitor pattern | /loop skill | ralph-loop (qa) |
| 1 | Code modify/write | scout → coder | qa |
| 2 | Code review/validate | scout → qa | coder |
| 2.5 | Bug root cause | scout → qa (tracer) | coder |
| 2.6 | New project structure | scout (deepinit) | — |
| 3 | Internet search | searcher | researcher |
| 3.5 | Paper search/read | /paper-read skill | searcher → researcher |
| 4 | File/symbol search | scout | — |
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
