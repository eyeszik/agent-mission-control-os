# Operations runbook

Everything in this file is about money that has already moved. The gateway
handles the happy path on its own; these are the jobs and the alarms around it.

## The two scheduled jobs

| Job | Command | Suggested cadence | Exit code |
| --- | --- | --- | --- |
| Agent payouts | `npm run payouts` | daily | `1` if any payout failed |
| Reconciliation | `npm run reconcile` | every 15 minutes | `1` if anything is outstanding |

Both are ordinary one-shot processes. Run them from cron, a Kubernetes CronJob,
or a sidecar — anything that can page on a non-zero exit.

The gateway also serves `GET /internal/reconciliation`, which returns the same
report as the CLI with `200` when clean and `503` when not, so an uptime monitor
can watch it without running a process. **It is not behind agent
authentication or the rate limiter** — bind it to an internal listener or put it
behind your ingress' own access control.

## Paying agents

### Registering a destination

Commission accrues from the first sale, but nothing leaves until an agent has a
payout destination. Until then every sweep skips that agent and reconciliation
reports `balance_unpayable`.

```bash
npm run agent-account -- \
  --agent-id agent_acme \
  --stripe-account acct_1234567890 \
  --currency USD \
  --minimum-cents 5000          # accrue below $50 rather than paying it out
```

`--disable` stops payouts without deleting the account; `--enable` resumes them.

### Running a sweep

```bash
npm run payouts                      # every eligible agent
npm run payouts -- --agent-id agent_acme
npm run payouts -- --dry-run         # report balances, claim nothing
```

Each sweep, per agent and currency, does three things in order:

1. **Claim** — atomically attach every eligible conversion to a new `IN_FLIGHT`
   payout row inside one Postgres transaction.
2. **Transfer** — one Stripe Connect transfer, keyed on the payout's own
   `idempotency_key`.
3. **Confirm or release** — mark `PAID` and write the ledger legs, or mark
   `FAILED` and delete the claim so the money is claimable again next run.

The claim happens *before* the external call on purpose. A crash in between
leaves a visible `IN_FLIGHT` row for reconciliation to surface, which is far
better than the alternative failure mode of paying twice.

Concurrent sweeps are safe: `payout_items.conversion_id` is a UNIQUE index, so a
racing claim aborts its own transaction rather than funding a second transfer.

### What is eligible

- A **sale** counts once it is `SETTLED` — the settlement webhook confirmed the
  capture cleared. A sale still `PENDING_SETTLEMENT` is never paid on.
- A **reversal** counts, negatively, only if its parent sale was itself claimed
  by a payout. Refunding a sale that was never paid out nets to zero rather than
  inventing a debt.
- A net balance of zero or less transfers nothing and claims nothing. The debt
  carries forward and nets against the agent's next sale.

## Alarms

`npm run reconcile` reports findings at two severities.

### `critical` — the books disagree with reality

| Check | Meaning | What to do |
| --- | --- | --- |
| `ledger_unbalanced` | An entry group's debits ≠ credits. | Stop payouts. The books are corrupt; find the group and the code path that wrote it before transferring anything else. |
| `conversion_split_violation` | A conversion violates the commission invariants. | `conversions_split_balance_check` must have been dropped. Restore the constraint, then correct the rows. |
| `orphaned_capture` | A `payment_intent.succeeded` / `charge.succeeded` matched no conversion. | Money moved that the gateway cannot attribute. Reconcile each event id against the Stripe dashboard; refund it if no order exists. |
| `payout_in_flight_stale` | A payout claimed conversions over an hour ago and never resolved. | Check Stripe for a transfer carrying that payout's `idempotency_key`. If it landed, mark the row `PAID` by hand; if not, re-running with the same key is safe. **Never** release the claim without checking first. |

### `warning` — overdue, may resolve itself

| Check | Meaning | What to do |
| --- | --- | --- |
| `settlement_overdue` | Sales stuck in `PENDING_SETTLEMENT` past the threshold. | Usually the Stripe webhook endpoint is unreachable. Check the endpoint's delivery log. |
| `balance_unpayable` | An agent earned commission with no enabled destination. | Register it with `npm run agent-account`, or accept that it accrues. |

Thresholds are tunable:

```bash
npm run reconcile -- --pending-settlement-minutes 180 --stale-payout-minutes 30
```

### `ORPHANED CAPTURE` in the logs

Distinct from the `orphaned_capture` reconciliation check. This log line means
checkout captured a payment, the merchant order failed, *and* the compensating
refund also failed. The money is sitting on the rail with no order behind it.
Refund it manually from the Stripe dashboard using the logged
`paymentIntentId`. This is the one state the gateway cannot resolve on its own.

## Merchant lifecycle

```bash
npm run merchant -- list
echo '{"platform":"shopify", ... }' | npm run merchant -- rotate --merchant-id <uuid>
npm run merchant -- disable --merchant-id <uuid>
npm run merchant -- enable  --merchant-id <uuid>
```

**Rotation** re-seals new credentials under AES-256-GCM and overwrites the old
ciphertext — a rotated-away token stops existing in the database. The platform
cannot change: conversions, ledger entries and connector routing are all keyed
off it, so a platform switch is a new merchant.

**Disabling** drops a merchant out of catalogue fan-out while leaving its
conversions and ledger entries intact. It is deliberately a flag, not a delete:
the books must stay readable for a merchant that has stopped trading.

Neither command prints credentials. Their output is safe to paste into a ticket.

## Ledger accounts

| Account | Sale | Reversal | Payout |
| --- | --- | --- | --- |
| `merchant_receivable` | DEBIT | CREDIT | — |
| `merchant_revenue` | CREDIT | DEBIT | — |
| `agent_payable` | CREDIT | DEBIT | DEBIT |
| `platform_revenue` | CREDIT | DEBIT | — |
| `agent_cash` | — | — | CREDIT |

A fully settled and paid-out sale leaves `agent_payable` at zero: the sale
credits it, the payout debits it back. Balances are reported as
`debits − credits`, so an outstanding liability reads negative.

## Restoring service

Migrations run at boot behind a Postgres advisory lock, so rolling out N
replicas applies them exactly once. Migrations `003` and `004` are additive —
new tables and nullable/defaulted columns only — so an older gateway build keeps
running against a newer schema. Roll forward rather than down.
