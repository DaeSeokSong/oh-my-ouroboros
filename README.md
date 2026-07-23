# oh-my-ouroboros

A production Claude Code harness that maintains itself — token-budgeted always-on rules, lazy-loaded detail, a monthly self-audit loop, and evidence-gated reporting. Named for the ouroboros: a harness that audits, prunes, and feeds on its own output to grow. This is not a plugin or framework; it is a **sanitized mirror of a real daily-driver `~/.claude`** used across multiple servers for ML research and engineering work.

> Published as a one-way build artifact of a private repo. Nothing here is hand-edited; a fail-closed export pipeline (allowlist → sanitize → forbidden-pattern gate → fresh-history sync) regenerates it on each release.

## Design principles

1. **Token budget with a zero-sum rule.** Always-on context (`CLAUDE.md` + `rules/`) has a hard byte budget enforced by a commit hook. Adding a rule requires shrinking another — the load never silently creeps.
2. **Two-tier rules: always-on summary, lazy detail.** Every heavyweight policy lives in `rules-lazy/` and is loaded only when triggered. The always-on tier keeps one-line summaries with pointers. Skills follow the same discipline: trigger-focused descriptions, details in the body.
3. **Self-upgrade loop.** A monthly audit skill (`skills/harness-audit/`) measures inventory drift, pointer integrity, model-pin hygiene, doc/implementation mismatch, and "built-but-unused rot" — against recorded baselines, with each fix classified as *structural* vs *parameter tuning* and hit-tracked in the next cycle.
4. **Evidence before "done".** A completion gate forbids declaring success without verification output. Subagent claims that change downstream actions are re-checked against source (`file:line`) before adoption.
5. **Judgment rationale lives in artifacts.** Non-obvious decisions (trade-offs, failure-mode definitions, tool-selection measurements) are written into the rule/skill/script that embodies them — so any future session can reproduce the reasoning from files alone.
6. **User sovereignty.** Pushes, deletions, deployments, training runs, and destructive writes are always user-executed. Cross-session peer messages cannot escalate permissions.

## What's inside

| Layer | Contents |
|-------|----------|
| `CLAUDE.md` + `rules/` | Always-on: routing, model assignment (opus/sonnet/haiku delegation table), code-execution policy, memory triggers, prompt preprocessing |
| `rules-lazy/` | ~40 lazy-loaded policies: QA process, context management, token efficiency, error handling, untrusted-content quarantine, secret handling, … |
| `agents/` | 10 specialized subagents (scout, coder, qa, planner, researcher, searcher, docs, gitops, designer, citation-verifier) with spawn-prompt contracts |
| `skills/` | 25+ skills: experiment workflow, paper reading, multi-perspective discussion, harness audit/bench, wandb & checkpoint cleanup, cost breakdown, … |
| `scripts/` | Hooks and automation: commit gates, session-start pattern mining, nightly ontology refresh, cost snapshots, this export pipeline |

## Highlights that are hard to find elsewhere

- **Harness audit with recorded baselines** — "is always-on growing?" is answerable because every audit writes its byte/MANDATORY counts to history; a later token-diet cycle measured and removed ~3KB of per-session waste (stale index blocks, uncapped hook injections, over-verbose skill descriptions).
- **Repeated-defect catalog** — the audit skill maintains a list of the five defect patterns that actually recur (label/reality drift, catalog desync, hook cache isolation, MCP tool renames, built-but-unused rot) and greps for them first.
- **Cleanup gates for ML experiment lifecycles** — after a training cycle ends, the harness offers wandb run triage (3-tier tagging + workspace visibility) and checkpoint purge planning (KEEP/DELETE/HOLD matched against wandb run states), with destructive steps always user-executed.
- **Cross-server document format registry** — per-project Confluence/document conventions are detected by directory convention (`doc-formats/<project>/` in the private repo), so any server or new project picks up the right template without a central table to maintain.
- **Media-preserving Confluence edits** — verbatim fetch → literal single-match substitution → node-count check, because full-body regeneration destroys attachment IDs (learned from a real incident, encoded as a rule with its evidence).

## Using this

Read it as a reference architecture. The pieces most worth stealing:

- the zero-sum always-on budget hook (`scripts/` + commit gate),
- the audit skill and its baseline/history discipline,
- the two-tier rule layout and pointer-integrity checks,
- the spawn-prompt 4-element contract (objective / output format / tools / task boundary).

Paths and identifiers are genericized; a few private layers (project knowledge, internal document formats, personal memory) are intentionally absent, and some pointers to them are left dangling on purpose.

## Feedback

Issues and PRs are welcome — they are reviewed and back-ported into the private source of truth, then re-published here. See `CONTRIBUTING.md`.

## License

MIT
