# ACP compatibility and evidence status

This file records, per protocol surface, what was verified against published
specifications, what follows the AISL blueprint instead, and what is still
unverified. It exists so that nothing in this repository has to be taken on
trust.

Verified on 2026-09-12 against:

- Stripe — Shared payment tokens:
  <https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens>
- Stripe — Agentic Commerce Protocol:
  <https://docs.stripe.com/agentic-commerce/acp>
- OpenAI — Delegated Payment Spec:
  <https://developers.openai.com/commerce/specs/payment>
- ACP specification repository:
  <https://github.com/agentic-commerce-protocol/agentic-commerce-protocol>

---

## 1. Shared payment token redemption — VERIFIED

Stripe documents that a seller charges a granted shared payment token by
creating a PaymentIntent:

```bash
curl https://api.stripe.com/v1/payment_intents \
  -d amount=1000 \
  -d currency=usd \
  -d "payment_method_data[shared_payment_granted_token]=spt_123" \
  -d confirm=true
```

`src/connectors/stripe/delegatedPayments.ts` issues exactly this call. The
parameter shape is asserted by the mock Stripe server in
`tests/helpers/mockStripe.ts`, which returns a `parameter_missing` error if
`payment_method_data[shared_payment_granted_token]` is absent — so a regression
in the adapter fails a test rather than a live payment.

Two consequences of that documentation are load-bearing here:

- **Preview API version.** `shared_payment_granted_token` ships on
  `2026-04-22.preview`, outside the stable SDK's parameter types. The single
  cast that crosses that gap is isolated in the adapter and commented. Override
  with `STRIPE_API_VERSION` when the parameter graduates.
- **Connected account.** An SPT is scoped to the seller's Stripe profile, so the
  charge is created on the merchant's connected account (`Stripe-Account`) when
  `stripe_account_id` is configured for that merchant.

Token id prefix is `spt_`; the gateway does not validate the prefix, because the
`merchant_shared_payment_token` credential type is explicitly allowed to carry a
non-Stripe handle.

## 2. Discovery manifest `/.well-known/acp/config.json` — BLUEPRINT, NOT UPSTREAM

The blueprint's completion invariant fixes both the path and the exact document:

```json
{ "version": "2026.1", "capabilities": {...}, "endpoints": {...},
  "payment_methods": [...], "supported_currencies": [...] }
```

It is served verbatim and asserted verbatim in `tests/e2e/gateway.e2e.test.ts`.

**The upstream ACP specification does not define this path or this document.**
The published spec (`spec/2026-04-17/openapi/`) covers agentic checkout, cart,
feed, delegate payment, delegate authentication and webhooks; no `.well-known`
discovery document appears in it. Treat this manifest as an AISL-local
convention, useful for a gateway that fronts many merchants, and do not expect
a third-party ACP client to find the gateway through it.

## 3. Agent-facing endpoints — BLUEPRINT, NOT UPSTREAM

`POST /v1/agent/intent`, `POST /v1/agent/checkout` and
`GET /v1/agent/order/{order_id}` are the blueprint's own surface. Upstream ACP
models the merchant side as checkout sessions
(`openapi.agentic_checkout.yaml`) and a product feed (`openapi.feed.yaml`).

Interoperating with an ACP-native agent therefore needs an adapter layer that is
**not** implemented here. It is a clean addition rather than a rewrite: the
service layer (`src/services/`) is protocol-agnostic, and `src/app.ts` is the
only file that binds it to routes.

One upstream shape *is* adopted: the error envelope
`{ type, code, message, param }` from the delegate-payment spec, so an agent can
parse gateway failures with the same handler it uses for upstream ACP calls.

## 4. Delegate payment endpoint — NOT IMPLEMENTED (deliberately)

The OpenAI spec defines `POST /agentic_commerce/delegate_payment`
(OpenAI → PSP, returning a `vt_...` vault token), with `Authorization`,
`Idempotency-Key`, `Request-Id`, `API-Version`, `Signature` and `Timestamp`
headers.

That endpoint is implemented by a *payment service provider*. This gateway sits
on the seller side of the handshake: it receives an already-granted token and
redeems it. Implementing the PSP endpoint would mean holding raw PAN data and
falls outside both the blueprint's objective and its non-goals.

## 5. Webhook signature verification — VERIFIED

`stripe.webhooks.constructEvent(rawBody, signature, endpointSecret)` performs
HMAC-SHA256 over the exact request bytes with a replay window. The gateway
retains the raw buffer in its content-type parser specifically so this
verification sees the bytes that were signed. The test suite generates genuine
signatures with `Stripe.webhooks.generateTestHeaderString`, so signature
handling is exercised for real rather than stubbed.

## 6. Merchant platform APIs — PARTIALLY VERIFIED

| Call | Status |
| --- | --- |
| Shopify Storefront `products(query:)` GraphQL | Shape follows the blueprint plus standard Storefront fields (`availableForSale`, `handle`, `onlineStoreUrl`, `featuredImage`). Exercised against a mock, **not** against a live store. |
| Shopify Admin `POST /admin/api/{version}/orders.json` | Standard Admin REST order creation with an external `sale` transaction. Exercised against a mock, **not** a live store. |
| WooCommerce REST v3 products/orders | Implemented to the documented v3 shapes; **no test coverage against a mock or live store.** |

Before pointing this at a live store, run one search and one order against a
development store and confirm the selection sets still resolve — Shopify
deprecates Storefront fields on a rolling API-version schedule, and
`admin_api_version` / `storefront_api_version` are per-merchant settings for
exactly that reason.

## 7. Known gaps

- The WooCommerce connector has no automated coverage.
- There is no ACP-native checkout-session adapter (see §3).
- Currency handling assumes a single currency per merchant catalogue; a
  multi-currency Shopify market would need per-context pricing.
- `idempotency_keys` (blueprint table 4) is created but unused: durable webhook
  dedupe is served by `webhook_events`, which additionally records what was
  applied. The table is retained because the blueprint's schema is locked.
