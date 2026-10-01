# Portfolio command center and cost × quality routing

## Portfolio

`GET /portfolio` aggregates every project the principal may access. Each project row reports:

- brand health (`OK` or `AT_RISK`, with the open risks behind it);
- active campaigns and the production queue;
- the approval queue (content reviews plus run approvals);
- the next 14 days of calendar;
- the publication queue (pending, blocked or enqueued jobs);
- spend-authorization status;
- stale assets and rights expiry;
- content gaps (atoms without derivatives);
- search visibility and performance.

Search visibility and performance read `UNKNOWN_NO_OBSERVED_METRICS` until M5 measurements exist.

**Isolation.** The portfolio returns counts and health signals only. Another project's memory, conversations and brand canon never appear in it. The tests assert this, both for a principal scoped to one project and for a different tenant.

Cross-brand reuse is limited to:

- M0 agency memory;
- provider capability profiles;
- workstream templates.

Private brand canon, customer data, project conversations, client secrets and unapproved proprietary assets never cross a project boundary.

The Mission Control UI shows this in **Projects** mode. That mode has four panels:

- `ProjectWorkspacePanel`: project picker and creator, mirror folders, the DAM list;
- `ProjectActivityPanel`: threads, messages with artifact cards, the activity stream;
- `ContentCalendarPanel`: upcoming slots, blocked jobs, guarded transitions;
- `PortfolioCommandCenter`.

## Cost × quality router

`ProviderCapabilityProfile` records:

- provider, model, task and formats;
- local or cloud;
- **observed** cost per unit, p95 latency, acceptance rate and failure rate, each with a sample size and an evidence ref, or `UNKNOWN`;
- rights constraints and benchmark refs;
- last-verified time and mode.

Rules for profiles:

- Profiles can be registered as DISABLED or DRY_RUN only. `LIVE` is refused, because provider activation is a reviewed code change.
- Registering a profile requires an approver.

`POST /providers/route` applies the routing priority:

1. reuse an approved asset;
2. apply a deterministic transform;
3. execute locally for free;
4. make a cheap draft, then evaluate;
5. produce a premium final, only with a recorded justification;
6. post-process before regenerating.

The objective is **COST_PER_APPROVED_ARTIFACT** (observed cost ÷ observed acceptance rate), not raw generation cost. A profile missing either input ranks after every observed one, and its objective is reported as `UNKNOWN`.

Other guarantees:

- Disabled profiles, profiles with the wrong format and profiles with a failure rate above the limit are excluded, with reasons.
- Routing is advice. It never activates a provider.
