# Brand OS 4.0 SOPs in Agent Mission Control

Sources: `services/langgraph/agency/sop/data/brand_os_index.v1.json` (F01-F60), `services/langgraph/agency/sop/data/brand_os/` (F01-F08 drafts), `services/langgraph/agency/sop/brand_os_source.py`, `services/langgraph/agency/sop/source_approval.py`.

## What exists

| Ids | Status | Meaning |
|---|---|---|
| F01-F08 | `NEWLY_AUTHORED_DRAFT` | Newly written v0.1 drafts, adopted by the owner on 2026-11-21 as the starting Brand OS 4.0 procedures. They are **not** recovered Brand OS 3.0 originals and say so in every file. |
| F09-F60 | `SOURCE_UNAVAILABLE` | Identity only (id, name, department). No procedure exists. |

The Brand OS 3.0 original procedures were never recovered (repository, history, Drive and the supplied documents were searched).

## How a draft becomes a project's canonical procedure

1. `stage_sop_for_adoption(principal, project_id=..., sop_id="F01", adapter=...)` checks that the draft bytes still match the pinned digest. It stores them as a Project OS `knowledge_capsule` (role `market_researcher`, subtype `brand_os.sop`) and opens a `BRAND_OS_SOP_ADOPTION` approval bound to that exact content hash.
2. An approver who is not the requester decides it on `/approvals/{id}/decide`.
3. `verify_sop_adoption(...)` returns evidence that the exact, still-current bytes were adopted in this tenant and project. Edited bytes, a new version, another purpose, another tenant or project, pending, rejected or stale approvals and self-approval all fail.

Adoption makes a procedure canonical for that project. It does not authorize running anything: the evidence grants no runtime authority, and publication, spend and send stay disabled.

## Known gaps in the v0.1 drafts

Roles per step are implied rather than bound to N3 roles. Review/approval inside each procedure and step-level recovery are general. Handoffs are partial: F04 references F03, F05 and F06. Reconciling each step against the AGM catalog (dimension witnesses, native bindings) is the next batch; nothing executes F01-F08 today.
