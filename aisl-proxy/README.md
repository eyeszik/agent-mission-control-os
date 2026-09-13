# AISL Proxy Gateway

Agentic Intent Settlement Layer — a middleware proxy that puts merchant
commerce backends (Shopify, WooCommerce, custom Stripe) behind an agent-facing
protocol surface, mints per-result attribution tokens, redeems delegated
payment credentials, and keeps a double-entry commission ledger that survives
refunds and disputes.

Built from `agentic_commerce_middleware_blueprint.md`, Tasks 1–6.

## What it does

```
AI agent
  │  GET  /.well-known/acp/config.json      discovery
  │  POST /v1/agent/intent                  catalogue search -> UUIDv7 acp_token per result
  │  POST /v1/agent/checkout                delegated payment + order + ledger write
  │  GET  /v1/agent/order/{order_id}        settlement status incl. reversals
  ▼
AISL gateway ── Postgres (merchants, intents, conversions, ledger_entries, payouts)
             └─ Redis    (catalogue cache, webhook dedupe, token-bucket rate limit)
  │
  ├─ Shopify Storefront GraphQL / WooCommerce REST   catalogue
  ├─ Shopify Admin REST / WooCommerce REST           order dispatch
  ├─ Stripe PaymentIntents                           shared payment token redemption
  └─ Stripe Transfers                                agent commission payouts
       ▲
       ├── POST /v1/webhooks/stripe-acp    settlement + clawback
       └── GET  /internal/reconciliation   operator probe: 200 clean, 503 otherwise
```

Two scheduled jobs close the loop: `npm run payouts` moves accrued commission
out to agents, and `npm run reconcile` reports the states that need a human.
Both are documented in [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## Quick start

```bash
cp .env.example .env          # then fill in the secrets it documents
npm install
docker compose up -d postgres redis
npm run migrate
npm run dev
curl -i http://localhost:8080/.well-known/acp/config.json
```

Onboard a merchant (credentials are sealed with AES-256-GCM before they reach
the database — they never appear in plaintext in `merchants`, nor in shell
history if you pipe them in):

```bash
echo '{
  "platform": "shopify",
  "store_domain": "your-store.myshopify.com",
  "storefront_token": "shpstf_...",
  "admin_token": "shpat_...",
  "stripe_account_id": "acct_..."
}' | npx tsx src/cli/onboard-merchant.ts \
    --name "Your Store" --commission-bps 500 --aisl-bps 80
```

## Operator commands

```bash
npm run payouts                 # sweep accrued agent commission and transfer it
npm run payouts -- --dry-run    # report balances without claiming anything
npm run reconcile               # the states that need a human; exit 1 if any
npm run agent-account -- --agent-id agent_acme --stripe-account acct_123
npm run merchant -- list        # rotate / disable / enable a merchant's credentials
```

See [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for the runbook behind each.

## Tests

```bash
npm test          # unit + integration, requires Postgres and Redis
npm run test:unit # pure units, no services needed
```

The suite needs a reachable Postgres and Redis:

```bash
export TEST_DATABASE_URL=postgresql://aisl:aisl@127.0.0.1:5432/aisl_test
export TEST_REDIS_URL=redis://127.0.0.1:6379
```

The integration suite runs the **real** gateway — real Fastify routing, real
connectors, the real Stripe SDK's request encoding, real HMAC webhook
verification, real Postgres transactions, real Redis `SETNX` — against
in-process HTTP stand-ins for Shopify and Stripe. Only the remote servers are
simulated; no gateway code is stubbed out.

## Production deployment

```bash
docker compose up -d --build
```

Compose fails fast if `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
`AISL_ATTRIBUTION_SALT`, `AISL_CREDENTIAL_ENCRYPTION_KEY` or
`AISL_AGENT_API_KEYS` are unset — an unauthenticated payment gateway should not
be one forgotten variable away.

Then point Stripe at `https://your-domain/v1/webhooks/stripe-acp` and subscribe
to `payment_intent.succeeded`, `charge.refunded` and `charge.dispute.created`.

Migrations run at boot behind a Postgres advisory lock, so rolling out N
replicas applies them exactly once.

### Building behind a TLS-inspecting proxy

`npm ci` inside the image will fail with `SELF_SIGNED_CERT_IN_CHAIN` if your
egress proxy re-terminates TLS. Pass the CA as a build secret; it is used only
during install and never lands in the runtime image:

```bash
docker build --secret id=proxy_ca,src=/path/to/ca-bundle.crt .
# or, for compose:
AISL_PROXY_CA_FILE=/path/to/ca-bundle.crt docker compose up -d --build
```

## How the money is accounted for

Commission is integer-cent arithmetic on basis points, with fees truncated
toward zero so a reversal is the exact arithmetic negation of its sale:

```
commission_total = trunc(gross * commission_rate_bps / 10000)
aisl_fee         = trunc(gross * aisl_cut_bps       / 10000)
agent_payout     = commission_total - aisl_fee
merchant_net     = gross - commission_total
```

Two invariants are enforced in code *and* by a Postgres `CHECK` constraint, so
no future code path can write an unbalanced row:

```
commission_total == aisl_fee + agent_payout
gross            == merchant_net + commission_total
```

Beside the denormalised `conversions` row, every transaction also writes
balanced legs into `ledger_entries`:

| account              | sale   | reversal | payout |
| -------------------- | ------ | -------- | ------ |
| `merchant_receivable`| DEBIT  | CREDIT   | —      |
| `merchant_revenue`   | CREDIT | DEBIT    | —      |
| `agent_payable`      | CREDIT | DEBIT    | DEBIT  |
| `platform_revenue`   | CREDIT | DEBIT    | —      |
| `agent_cash`         | —      | —        | CREDIT |

A sale credits `agent_payable`; the payout that discharges it debits the same
account back to zero. Commission that has been earned but not yet transferred is
exactly the outstanding balance on that account.

Debits equal credits within every `entry_group_id`;
`findUnbalancedEntryGroups()` returns the corruption alarm and is asserted
empty by the test suite.

**Commission is never paid on money that did not move.** The gateway settles on
`min(merchant order total, amount actually captured)`, and logs a
`settlement_amount_mismatch` warning when the two disagree (store-side tax or
shipping added after the agent's quote).

## Safety properties worth knowing

- **Attribution tokens are bound, not just random.** Each `acp_token` carries an
  HMAC signature over `(click_id, agent_id, merchant_id)`. Checkout rejects a
  token presented for a different merchant or a different variant, and — when
  the agent returns the signature — one minted for a different agent.
- **Tokens expire.** 24 hours by default (`ACP_TOKEN_TTL_SECONDS`).
- **Checkout is idempotent.** A claim on `checkout_idempotency` is taken before
  any external mutation, and the same key is passed to Stripe. A retried
  checkout replays the original response; it does not charge twice.
- **A failed order refunds the capture.** If the merchant rejects the order
  after the payment succeeded, the gateway issues a compensating refund. If
  *that* also fails, it logs `ORPHANED CAPTURE` — the one state that always
  needs a human.
- **Webhooks are deduplicated twice.** Redis `SETNX` with a 7-day TTL on the hot
  path, plus an `INSERT ... ON CONFLICT DO NOTHING` on `webhook_events` that
  survives a Redis flush. A handler that throws releases both claims so a
  genuine Stripe retry can still run.
- **A refund cannot be undone by a late settlement event.** `markSettled` only
  transitions `PENDING_SETTLEMENT`, never `REFUNDED`.
- **Merchant credentials are encrypted at rest** (AES-256-GCM), and secrets are
  redacted from request logs. They can be rotated in place (`npm run merchant --
  rotate`), which overwrites the old ciphertext rather than archiving it.
- **An agent is never paid twice.** A payout claims its conversions atomically
  before the transfer is attempted, and `payout_items.conversion_id` is a UNIQUE
  index — a concurrent sweep aborts rather than funding a second transfer. A
  failed transfer releases the claim; a transfer whose outcome is unknown stays
  `IN_FLIGHT` for a human, because guessing risks paying twice.
- **A refund is clawed back out of the next payout**, netting against future
  earnings. Refunding a sale that was never paid out nets to zero instead of
  inventing a debt.

## Layout

```
src/
  app.ts                     Fastify wiring, hooks, routes, error mapping
  container.ts               dependency construction (the only place `new` meets config)
  config/env.ts              zod-validated runtime contract
  types/acp.ts               protocol schemas and the frozen discovery manifest
  lib/                       money, ids (UUIDv7), crypto, typed errors
  db/                        pool, migration runner, SQL migrations, repositories
  redis/store.ts             narrow KV surface + Lua token bucket + in-memory twin
  connectors/                Shopify Storefront/Admin, WooCommerce, Stripe SPT
  services/                  intent, checkout, webhook orchestration
  cli/                       onboarding, merchant lifecycle, payouts, reconciliation
tests/
  unit/                      money, crypto, ids, connectors, dedupe primitives
  e2e/                       schema gate + full gateway cycle
  helpers/                   mock Shopify and Stripe servers, harness
```

## Further reading

- [`docs/acp-compatibility.md`](docs/acp-compatibility.md) — what is verified
  against the published Stripe/OpenAI specifications, what follows the
  blueprint instead, and what remains unverified.
- [`docs/blueprint-conformance.md`](docs/blueprint-conformance.md) — each
  blueprint validation gate mapped to the test that proves it.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — payout and reconciliation
  runbooks, every alarm and what to do about it.
