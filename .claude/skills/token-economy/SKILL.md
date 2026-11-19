---
name: token-economy
description: Efficiency booster prompt wrapper (Lite and Pro) for any model, and a token-economy playbook for long Claude Code sessions. Use when asked to make a prompt cheaper, tighter or more reliable, to wrap a task in the efficiency booster, to cut token usage or context bloat in a session, to decide between /compact and /clear, or to audit CLAUDE.md and session habits for token waste.
---

# Token economy

Two tools. Read only the file the request needs.

| The request | Read |
|---|---|
| Wrap a prompt, or write one for another model, so the answer is direct and complete | [`booster.md`](booster.md) |
| A session is long, slow, expensive or degrading; or set up a repo so sessions stay cheap | [`playbook.md`](playbook.md) |

## Choosing a booster

- **Lite** (about 70 tokens): routine, low-stakes calls. Paste it before or after the task.
- **Pro**: substantive or high-stakes deliverables. Fill the four slots (`{CONTEXT}`, `{CONSTRAINTS}`, `{OUTPUT_FORMAT}`, `{TASK}`); leave a slot out rather than padding it.
- Emit the chosen booster verbatim with the user's task filled in. Don't paraphrase it: the wording is the product.
- For a prompt that will be cached, put the booster (stable) first and the task (variable) last.

## Using the playbook

- Start at the tier that matches the moment: Tier 1 before a session or when setting up a repo, Tier 2 while working, Tier 3 when context is already degrading, Tier 4 on a weekly review.
- Recommend the one or two changes with the most leverage for the situation, not the whole list.
- This repo already applies most of Tier 1: a specific root `CLAUDE.md`, a nested `CLAUDE.md` per subsystem under `services/langgraph/agency/`, and on-demand skills in `.claude/skills/`. When Tier 4 turns up a repeated correction, the fix goes in the nested file for that subsystem, not the root file, so only sessions working there pay for it.

## Limits

- The playbook's `#NN` numbers cite an external Claude Code tips guide that is not in this repository. Treat them as labels, and check a command or flag against current Claude Code documentation before relying on it.
- Claude Code commands, flags and model names change. The accuracy notes at the end of `playbook.md` record what was checked and what was not.
