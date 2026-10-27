# Decision ledger — UNSPLIT

This file records **only** decisions a human has actually made. It currently
records none. Draft text, a recommendation, or an agent's confidence is not a
decision.

## Gate 1 — creative direction

| Field | Value |
| --- | --- |
| Decision id | `CD-001` |
| Status | **OPEN — awaiting human decision** |
| Question | Which creative direction should become the brand system? |
| Options | A — REGISTER (recommended) · B — NIGHT SHIFT · C — FIELD RECORD · named hybrid · reject and re-brief |
| Attachments | [`strategy.md`](strategy.md) (3 directions, measured contrast, risks) · [`brand-prompt.md`](brand-prompt.md) |
| Approver | *not set* |
| Decided at | *not decided* |
| Scope if approved | direction only — **not** assets, publication, spend, or deployment |
| Artefacts that would be created after approval | approved brief, `CreativeGenome` v1, DTCG token set, logo family, poster, variants, website section, provenance manifest |
| Approval mechanism | explicit human answer in the session, then recorded here with approver, timestamp and the exact option chosen |

### What is *not* approved

- The name **UNSPLIT** — uncleared.
- Any price, margin, target, market claim or business model in `strategy.md`.
- Any colour, type choice, mark, copy line or application.
- Any generated asset — none exists yet.

## Gate 2 — final artefacts

| Field | Value |
| --- | --- |
| Decision id | `CD-002` |
| Status | **NOT REACHED** — blocked by `CD-001` |
| Question | Are the generated artefacts approved for the stated use? |
| Approval mechanism | Project OS approval bound to the exact head bytes (`open_artifact_approval` → `/approvals/{id}/decide`) |
| Separation of duties | the generating agent may not approve |

Gate 2 will be requested **separately** after assets exist, are read back from
storage and re-hashed. Publication, sending, deployment and spend remain
prohibited regardless of either gate.

## Change log

| Date | Change | Actor |
| --- | --- | --- |
| 2026-10-27 | Ledger created. No decisions recorded. Gate 1 opened. | drafting agent |
