# Token-economy playbook (extended Claude Code sessions)

`#NN` cites an external Claude Code tips guide that is not in this repository.

## Tier 1: structural (prevent bloat before the session starts)

- **Write an ultra-specific `CLAUDE.md`** (#15, #18). The highest-leverage lever: the explanation cost is paid once per repo instead of once per session.
- **Nested `CLAUDE.md` per directory** (#16) in monorepos. Each session inherits only the subtree's rules, not the whole repo's.
- **`@imports`** (#17) pull style guides and specs in by reference instead of pasting them inline. Editing the file doesn't bloat chat history retroactively.
- **Scope the workspace** with `--add-dir` (#13) and `--allowed-tools` (#10) instead of blanket repo access. Narrower scope means fewer speculative file reads.
- **Git worktrees** (#22) or parallel sessions for separable work. Each gets a small, clean context instead of one marathon session carrying unrelated history.
- **Delegate research-heavy or exploratory sub-steps to sub-agents** (#21). Their noisy intermediate output (searches, grep dumps, failed attempts) stays in the sub-agent's context; the parent receives only the final report.

## Tier 2: in-session discipline (keep the running session lean)

- **`file:line` references** (#32), not whole-file pastes. Claude reads only the slice it needs.
- **Grep or sed the log or coverage output before pasting** (extends #39). Feed in the 20 relevant lines, not the 2,000-line dump.
- **Ask for diffs or patches** once a file is already in context, not full re-pastes.
- **Redirect `--verbose`** (#12) to a log file, never into the conversation.
- **`--output-format json` / `stream-json`** (#08) for headless and CI runs, so downstream tooling parses structure instead of prose.

## Tier 3: reactive (context is filling up or degrading now)

- **`/compact` with a focus instruction** (#03) the moment output starts degrading. The longer the wait, the lossier the compaction.
- **`/clear` plus a `RESUME.md` handoff** (#49) for a real subject change. Rule of thumb: `/compact` is the same thread, leaner; `/clear` plus `RESUME.md` is a different subject. Compacting when you should have cleared carries dead weight into the new topic.
- **Checkpoint commits** (#24) before any large autonomous step. A bad run gets `git reset`, not argued with in more tokens.

## Tier 4: measurement (close the loop so Tier 1 keeps improving)

- **Mine `~/.claude/projects/*.jsonl`** (#46) weekly: which tasks cost the most tokens, which sessions needed the most back-and-forth. Feed the findings back into `CLAUDE.md` as explicit rules (#18).
- Every repeated mid-session correction is a signal that `CLAUDE.md` is under-specified. Under-specification is the most expensive waste because it recurs every session until it is fixed once.

## Beyond the guide

- **Prompt caching.** Order content so the stable prefix (system prompt, `CLAUDE.md`) comes first and variable task content last. The Anthropic API caches repeated prefixes, cutting cost and latency on long sessions. Confidence: medium. It is real at the API level; whether a specific integration surfaces it automatically depends on the setup, so check directly.
- **Model tier by pass, not only by session.** Run the Analyst and Planner passes on a cheap model and reserve the expensive model for the Executor pass on hard problems (a finer-grained #11).
- **A self-authored structured ledger beats a generic `/compact` summary.** Have Claude maintain `DECISIONS.md` or `RESUME.md` in a fixed schema: decisions made, open questions, files touched, current state. It is queryable and diffable across sessions (extends #40, #49).
- **Large specs and style guides:** never paste them. Write them to a file, then `@import` it (#17) or say "read X before doing Y".
- **When output verbosity, not input history, is the cost driver,** cap it in the instruction: "Respond in ≤400 words; ask before expanding."

## Guide accuracy notes

- #11: the guide's model names are outdated. Check current model ids before using them.
- #30: MCP servers are defined in `.mcp.json` at the project root, not in `.claude/settings.json` (which governs auto-approval of MCP servers, not their definition).
- #05 (`/doctor`) and the general shape of #31 (think / think hard / ultrathink escalation) were checked against Claude Code documentation when this playbook was written; re-check before relying on them.
