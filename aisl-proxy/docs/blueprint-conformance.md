# Blueprint conformance

Each validation gate from `agentic_commerce_middleware_blueprint.md` mapped to
the code that implements it and the test that proves it.

## Completion invariant (§1.3)

| Acceptance criterion | Evidence |
| --- | --- |
| `GET /.well-known/acp/config.json` returns a compliant ACP configuration in <10ms | `gateway.e2e.test.ts` → "returns the blueprint-locked ACP configuration" (exact document equality) and "answers well inside the 10ms budget" (median of 25 samples). Measured out-of-process with curl against the compiled server: 1.7ms total. |
| `POST /v1/agent/intent` returns real-time catalog prices with bound SubID tracking tokens | `gateway.e2e.test.ts` → "returns live catalogue results bound to UUIDv7 attribution tokens": every result's price is compared against the merchant catalogue, and `sub_id_1`/`sub_id_2` round-trip. |
| `POST /v1/agent/checkout` executes an atomic delegated payment token reservation | `gateway.e2e.test.ts` → "redeems the shared payment token, places the order, and books a balanced ledger": asserts the SPT reached Stripe in the documented parameter, on the connected account, under an idempotency key. |
| `POST /v1/webhooks/stripe-acp` reconciles the ledger with 0% dropped events | `gateway.e2e.test.ts` → settlement, duplicate, concurrent-duplicate, clawback, dispute, late-settlement, orphan and unhandled-type cases. Every path answers 200 so Stripe never retries a decided event. |
| 100% passing automated integration suite across mock agent and mock Shopify/Stripe APIs | `npm test`: 5 unit files + 5 integration files, 117 tests. |

## Task 1 — Repository scaffold and protocol manifest

- **Gate:** `curl -i http://localhost:8080/.well-known/acp/config.json` returns
  `200`, `Content-Type: application/json`, exact schema.
- **Implementation:** `src/types/acp.ts` (frozen manifest), `src/app.ts`
  (`registerDiscoveryRoutes`).
- **Evidence:** run against the compiled `dist/index.js`:
  `HTTP/1.1 200 OK`, `content-type: application/json; charset=utf-8`,
  body byte-identical to the blueprint. Plus the automated equality assertion.
- **Deviation:** none. TypeScript `strict` is on with `target: ES2023`, plus
  `noUncheckedIndexedAccess` and `noUnusedLocals`.

## Task 2 — Database schema and idempotent ledger

- **Gate:** migrations apply to a test Postgres; all tables and foreign keys
  exist; the unique constraint on `external_order_id` holds.
- **Implementation:** `src/db/migrations/001_init.sql` (blueprint tables,
  unchanged), `002_settlement_extensions.sql` (settlement columns, double-entry
  `ledger_entries`, indexes), `src/db/migrate.ts` (advisory-locked runner),
  `src/db/repositories/`.
- **Evidence:** `schema.e2e.test.ts` — table existence, foreign-key edges,
  duplicate `external_order_id` rejection, unbalanced-row rejection, migration
  idempotency.
- **Deviations (all additive, none change a blueprint column):**
  - `conversions` gains `currency`, `merchant_net_cents`, `entry_type`,
    `parent_conversion_id`, `stripe_payment_intent_id`, `stripe_charge_id`,
    `agent_id`, `updated_at`. Task 5 requires looking a conversion up by Stripe
    charge id, which the blueprint's column list cannot do.
  - `conversions_split_balance_check` enforces the commission invariants in the
    database, not only in code.
  - `ledger_entries` adds true double-entry legs; a single denormalised row
    cannot express balanced debits and credits.
  - `agent_intent_bindings` records which product a token was minted for, so
    checkout can reject a token replayed against another variant.
  - `webhook_events` and `checkout_idempotency` provide durable dedupe.
  - `idempotency_keys` is created per the blueprint but unused — see
    `acp-compatibility.md` §7.
  - Migration `003_payouts.sql` and `004_merchant_lifecycle.sql` are beyond the
    blueprint entirely; see "Beyond the blueprint" below.

## Task 3 — Product feed normalizer and discovery endpoint

- **Gate:** a synthetic query returns products each carrying a valid UUIDv7
  `acp_token` matching real merchant inventory.
- **Implementation:** `src/services/intentService.ts`,
  `src/connectors/shopify/storefront.ts`,
  `src/connectors/woocommerce/rest.ts`, `src/lib/ids.ts`.
- **Evidence:** `gateway.e2e.test.ts` intent block (5 tests) and
  `connectors.test.ts` (normalisation, auth failure, platform guard).
  `crypto.test.ts` proves UUIDv7 version, format and monotonic ordering.
- **Deviations:**
  - `totalInventory` is supplemented with `availableForSale` and
    `quantityAvailable`, because the blueprint's selection set alone cannot
    express purchasability.
  - Out-of-stock results are filtered out: an agent cannot check them out.
  - Catalogue results are cached in Redis; **attribution tokens never are.**
    Each response mints fresh click ids so two agents cannot share a trail.
  - Multi-merchant fan-out uses `Promise.allSettled`: one unreachable merchant
    degrades the result set rather than failing the search.

## Task 4 — Delegated checkout and atomic order router

- **Gate:** with mocked Stripe and Shopify, order creation succeeds and
  commission calculations match the ledger invariants exactly.
- **Implementation:** `src/services/checkoutService.ts`,
  `src/connectors/stripe/delegatedPayments.ts`,
  `src/connectors/shopify/admin.ts`, `src/lib/money.ts`.
- **Evidence:** `gateway.e2e.test.ts` checkout block (11 tests) and
  `money.test.ts` (11 tests, including a 3,500-case sweep asserting no cent is
  ever lost).
- **Deviations:**
  - The blueprint sets `gross_amount = order.total_price_cents`. The gateway
    settles on `min(order total, captured amount)` so commission is never paid
    on money that did not move, and logs the mismatch. Covered by "never pays
    commission on more than was captured".
  - The blueprint's ordering (pay, then order) leaves order creation able to
    strand money, so a dispatch failure triggers a compensating refund. Covered
    by "refunds the capture when the merchant order cannot be placed".
  - Checkout idempotency was added: a shared payment token charged twice is the
    most expensive failure available here.

## Task 5 — S2S webhook ingestion, deduplication, clawback

- **Gate:** two identical webhook payloads delivered concurrently — exactly one
  updates the ledger, the duplicate returns `200 OK` with no ledger change.
- **Implementation:** `src/services/webhookService.ts`,
  `src/redis/store.ts`, `src/db/repositories/webhookEvents.ts`,
  `ConversionRepository.recordReversal`.
- **Evidence:** `gateway.e2e.test.ts` webhook block (9 tests), including the
  concurrent-delivery race run through real Redis.
- **Deviations:**
  - A second dedupe layer in Postgres backs up Redis `SETNX`.
  - The reversal is a separate `conversions` row (`entry_type = 'REVERSAL'`)
    with a derived `external_order_id`, because the blueprint's own schema marks
    `external_order_id` `UNIQUE` — an in-place negative row is not expressible.
  - `charge.succeeded` and `charge.refund.updated` are handled alongside the
    blueprint's event list.
  - `markSettled` refuses to transition a `REFUNDED` conversion, so a late
    settlement event cannot resurrect a clawed-back sale.

## Task 6 — E2E suite and Dockerization

- **Gate:** `npm test` (or `docker compose up --abort-on-container-exit`) passes
  with zero errors.
- **Implementation:** `Dockerfile` (3-stage: deps → build+prune → distroless-ish
  Alpine runner as uid `node`, healthcheck on `/ready`), `docker-compose.yml`
  (gateway + `postgres:16-alpine` + `redis:7-alpine`, health-gated startup),
  `tests/e2e/gateway.e2e.test.ts`.
- **Evidence:**
  - `npm test` → 117 passed, 0 failed.
  - `docker compose up -d --build` → all three containers reported healthy;
    `/ready` returned `{"status":"ready","database":true,"cache":true}`;
    migrations `001_init.sql` and `002_settlement_extensions.sql` present in
    `schema_migrations` inside the container; `/v1/agent/intent` returned `401`
    without a bearer key.
  - The full synthetic cycle (discovery → search → delegated checkout →
    settlement → refund reconciliation) is a single test asserting the ledger
    nets to zero on every account afterwards.
- **Deviation:** the Dockerfile accepts an optional `proxy_ca` build secret so
  the image can be built behind a TLS-inspecting egress proxy. Without the
  secret it is a plain `npm ci`, and nothing is added to the runtime image.

---

# Beyond the blueprint

The blueprint's six tasks make the gateway an accurate **book of record**. They
stop short of two things a gateway handling real money needs, which are
implemented here and are explicitly *not* traceable to a blueprint gate.

## Agent payouts (`003_payouts.sql`)

Every sale credits `agent_payable` and every reversal debits it back, but the
blueprint never settles that liability — commission accrues forever and nothing
leaves. `PayoutService` sweeps it.

- **Implementation:** `src/db/repositories/payouts.ts`,
  `src/connectors/stripe/transfers.ts`, `src/services/payoutService.ts`,
  `src/cli/run-payouts.ts`, `src/cli/agent-account.ts`.
- **Evidence:** `payouts.e2e.test.ts` (12 tests) plus the schema guard in
  `schema.e2e.test.ts`. Covered: eligibility (settled sales only), the
  never-paid-refund case netting to zero, ledger discharge to a zero
  `agent_payable`, run idempotency, two concurrent sweeps producing exactly one
  transfer, claim release on a failed transfer, clawback netting against a later
  sale, a negative balance carried forward, and each of the four gates
  (unregistered, no destination, below minimum, disabled).
- **Design note.** The claim is taken *before* the external transfer. A crash in
  between therefore leaves a visible `IN_FLIGHT` payout — surfaced by
  reconciliation as `payout_in_flight_stale` — rather than risking a double
  payment. This trade is deliberate: money briefly stuck is recoverable, money
  sent twice is not.
- **Unverified:** `stripe.transfers.create` is exercised against the mock Stripe
  server only. It is the stable, generally available Transfers API rather than a
  preview one, so no cast is needed — but no live transfer has been made.

## Reconciliation and merchant lifecycle (`004_merchant_lifecycle.sql`)

- **Implementation:** `src/services/reconciliationService.ts`,
  `src/cli/reconcile.ts`, `GET /internal/reconciliation`,
  `src/cli/manage-merchant.ts`, `MerchantRepository.rotateCredentials` /
  `setEnabled`.
- **Evidence:** `reconciliation.e2e.test.ts` (10 tests) and
  `merchantLifecycle.e2e.test.ts` (7 tests), including an assertion that a
  rotated-away token leaves no plaintext trace in `merchants`.
- **Runbook:** [`OPERATIONS.md`](OPERATIONS.md).

## WooCommerce coverage

`acp-compatibility.md` §7 previously recorded that the WooCommerce connector had
no automated coverage. It now has 15 tests (`tests/unit/woocommerce.test.ts`)
against an in-process REST v3 stand-in: normalisation, stock-status mapping,
Basic auth, per-merchant currency caching, zero-decimal currency handling, order
creation with the attribution trail, and the auth-failure path. It is still
**not** exercised against a live WooCommerce store.
