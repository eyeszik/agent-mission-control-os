# Content operations, calendar and scheduler

## One verified fact core, many derivatives

A **ContentAtom** is a versioned set of claims. Each claim carries its evidence refs and a verification state: `VERIFIED`, `UNVERIFIED` or `CONTRADICTED`. Derivatives are built from the atom, never written free-hand:

```
ContentAtom → article · email · newsletter · carousel · social post · thread · video script
            · short video · reel · story · podcast · FAQ · landing section
            · AI-search answer · paid creative
```

`derive_variant` (in `agency/project_os/content.py`) produces the channel-native *structure* for each format: the sections it must contain, which claims feed each one, and channel constraints such as X's 280 characters or the 60-character email subject. It calls no LLM. Copy and creative roles fill the structure under their N3 contracts.

Rules:

- A derivative may cite only claims that exist in the atom version it came from (`assert_lineage`), so the claim → evidence chain survives every transformation.
- Contradicted claims are never used.
- **AI-search answers and paid creative use VERIFIED claims only.**
- A derivative that uses an unverified claim, or a claim without evidence, carries a release blocker. It can be drafted and reviewed, but `READY` and `SCHEDULED` are refused.
- `GET /projects/{id}/content/atoms/{atom}/exhaustion` is the **ContentExhaustionMap**: which claims and formats have been used, and which have not.

Each content item is registered in the N4 registry under its kind's N1 type (`CONTENT_KIND_ARTIFACT`; for example `article → copy_variant/copy` and `reel → media_asset/creative`), so content is part of the one artifact graph.

## Lifecycle

```
IDEA → PLANNED → IN_PRODUCTION → REVIEW → APPROVED → READY → SCHEDULED → DUE
     → PUBLISHING → PUBLISHED → VERIFIED → MEASURED → REFRESH_DUE → ARCHIVED
```

- **Entering APPROVED is an approval decision.** It requires an approver role, and the item's creator cannot approve it. This uses the same separation-of-duties check as run approvals.
- `READY`, `SCHEDULED`, `DUE` and `PUBLISHING` require `approved_version == version`.
- Any edit bumps the version, returns the item to `IN_PRODUCTION`, and cancels its pending jobs, so a stale approval can never be published.
- `DUE` through `VERIFIED` are entered only by the scheduler and the publication worker, never by a button in the UI.

## Calendar

`POST /projects/{id}/calendars/{cal}/plan` materializes open slots from cadences (channel, kind, posts per week, weekdays and hour). It supports horizons of **14, 30, 90, 182 and 365 days**. Re-planning is idempotent: the same calendar, channel and time never produce a duplicate slot. Fractional cadences accumulate, so 0.5 a week becomes one slot every other week.

`adaptive_reschedule` (the AdaptiveCalendar) picks the earliest open slot after both now and the blocked slot.

## Scheduler

There is **one scheduler**: `scheduled_jobs` driven by `run_scheduler_tick`. Publish jobs, evergreen REFRESH jobs and CRM LIFECYCLE jobs are all rows in it.

Each due job is processed in this order:

1. **Dependency check:** the item's artifact must not be invalidated or under review.
2. **Evidence and freshness check:** `evidence_fresh_until` has not passed and there are no release blockers.
3. **Rights check:** required for image, video and audio, or for any item with a rights reference. Expired or missing rights block.
4. **Exact approval check:** the approval is bound to the current version.
5. **Provider availability:** `AMC_PUBLICATION_MODE` must not be `disabled`.
6. **Compare-and-set claim:** `PENDING|BLOCKED → ENQUEUED`. Overlapping ticks cannot both claim a job.
7. **Trust-kernel outbox enqueue,** then the `OutboxDispatcher`.
8. **Adapter:** see [`publishing-providers.md`](publishing-providers.md).
9. **Read-back, reconciliation and receipts.**

The tick never calls a provider. A failing gate leaves the job `BLOCKED` with its reasons and records a `QA_BLOCKED` event. The next tick re-evaluates it, so granting the missing approval unblocks the job without rescheduling.

**Refresh jobs** (the EvergreenRefreshEngine) move a VERIFIED or MEASURED item to `REFRESH_DUE`.

**CRM journeys** (`POST /projects/{id}/journeys`) cover:

- welcome, onboarding, education
- abandoned cart, purchase, post-purchase
- cross-sell, upsell
- retention, win-back, referral
- renewal, feedback, customer success

Each step is a LIFECYCLE job that delivers an approved content item through the same gate and publication path. Behavioural triggers are recorded on the step, but nothing evaluates customer behaviour yet. Nothing is sent: the path is dry-run until a reviewed provider exists.

## Content supply forecaster

`POST /projects/{id}/forecast` takes:

- horizon and cadences;
- brands and campaigns;
- approval batch size;
- research refresh interval;
- optional **observed** unit costs.

It returns:

- items by kind and by category (articles, emails, posts, videos, graphics, landing pages);
- master assets and channel derivatives;
- approval batches and research refreshes;
- generation workload;
- cost.

A kind without an observed unit cost reports `UNKNOWN`, and so does the total. No price is invented.
