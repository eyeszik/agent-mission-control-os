# PRODUCTION SPECIFICATION & AUTONOMOUS EXECUTION BLUEPRINT
# Project: Agentic Intent Settlement Layer (AISL) - Middleware Proxy Gateway
# Standard Compatibility: Agentic Commerce Protocol (ACP v1.0), OpenAI Instant Checkout, Perplexity Merchant Feed
# Target Deployment Runtime: Node.js (TypeScript) / Cloudflare Workers Edge / PostgreSQL + Redis

---

## 1. MISSION CHARTER & COMPLETION INVARIANTS

### 1.1 Objective
Construct, test, deploy, and verify an enterprise-grade middleware proxy gateway that interfaces traditional merchant e-commerce platforms (Shopify Storefront API, WooCommerce REST API, custom Stripe checkouts) with modern Agentic Commerce rails (Agentic Commerce Protocol - ACP `/.well-known/acp/config.json`, delegated Stripe Payment Tokens [SPT], and AI shopping product feeds). The engine must dynamically ingest agent intent, execute S2S attribution, manage atomic cart checkout, and log cryptographic ledgers for affiliate commission clearing.

### 1.2 Non-Goals
- Building customer-facing human checkout frontend UIs.
- Relying on client-side tracking cookies or pixel redirects.
- Manual non-idempotent merchant onboarding workflows.

### 1.3 Completion Invariant Contract
```yaml
completion_invariant:
  target_artifact: "Production-ready deployable repository containing Gateway Proxy, Connector Engine, and S2S Ledger."
  acceptance_criteria:
    - "GET /.well-known/acp/config.json returns compliant ACP configuration schema within <10ms."
    - "POST /v1/agent/intent ingests product search, returns real-time catalog prices with bound SubID tracking tokens."
    - "POST /v1/agent/checkout executes atomic delegated payment token reservation against merchant backend."
    - "POST /v1/webhooks/stripe-acp reconciles S2S commission ledger with 0% dropped events."
  evidence_threshold: "100% passing rate on automated integration test suite across mock agent and mock Shopify/Stripe APIs."
  retry_limit: 3
  terminal: true
```

---

## 2. SYSTEM ARCHITECTURE & TOPOLOGY

```
[Autonomous AI Agent / Assistant]
               │
               ▼ (1. Discovery: GET /.well-known/acp/config.json)
               │ (2. Query Intent: POST /v1/agent/intent)
[AISL Gateway Proxy (Edge Worker / Fastly / Node.js Express/Fastify)]
   ├── Authentication & Rate Limiter (Token Bucket / Redis)
   ├── Agent Protocol Adapter (OpenAI ACP & LLM Tool Schema Translators)
   └── SubID & Cryptographic Click ID Generator (UUIDv7 + Salted Hashing)
               │
               ├── (3. Parallel Catalog Query)
               ▼
[Product Feed & Inventory Cache (Redis + Postgres Vector)]
   ├── Shopify Storefront API Poller / Webhook Listener
   └── Standard Product Feed Schema (Google Merchant / ACP Product Format)
               │
               ▼ (4. Intent Match & Delegated Checkout Execution)
[Checkout & Settlement Core Engine]
   ├── Stripe Delegated Token Exchange (Shared Payment Token Handler)
   ├── Atomic Order Placement Dispatcher
   └── S2S Attribution Logger & Ledger (Double-Entry Bookkeeping)
               │
               ▼ (5. Final Settlement & Clawback Protection)
[Merchant Backend (Shopify / Stripe Gateway)]
```

---

## 3. STEP-BY-STEP AUTONOMOUS AGENT WORKFLOW BLUEPRINT

The executing agent must complete the following 6 sequential tasks. Each task is schema-locked, containing its input parameters, step-by-step actions, validation gates, and recovery procedures.

---

### TASK 1: Repository Scaffold & Protocol Manifest Initialization

**1. Context & Objective:**
Initialize the TypeScript project structure, configure production runtime dependencies, and expose the open Agentic Commerce Protocol discovery metadata.

**2. Step-by-Step Implementation Instructions:**
- Initialize a Node.js project using TypeScript (`tsconfig.json` with strict mode, target ES2023).
- Install core runtime dependencies:
  - Framework: `fastify` or `@cloudflare/workers-types` + `itty-router` (Edge compatible).
  - Validation: `zod` for strict runtime schema validation.
  - Crypto & ID: `uuid` (UUIDv7 generation), `crypto` (HMAC-SHA256 signature verification).
  - Storage: `@upstash/redis` (or `ioredis`), `pg` / `kysely` for deterministic database queries.
  - Payment: `stripe` SDK (latest API supporting Agentic Commerce / delegated payments).
- Implement endpoint `GET /.well-known/acp/config.json` serving the compliant ACP configuration:
  ```json
  {
    "version": "2026.1",
    "capabilities": {
      "catalog_search": true,
      "delegated_checkout": true,
      "session_persistence": false
    },
    "endpoints": {
      "catalog_query": "/v1/agent/intent",
      "checkout_execution": "/v1/agent/checkout",
      "order_status": "/v1/agent/order/{order_id}"
    },
    "payment_methods": ["stripe_delegated_token", "merchant_shared_payment_token"],
    "supported_currencies": ["USD", "EUR", "GBP"]
  }
  ```

**3. Validation Gate & Quality Stop-Rule:**
- Run local server; issue `curl -i http://localhost:8080/.well-known/acp/config.json`.
- Must return `HTTP/1.1 200 OK`, `Content-Type: application/json`, matching the exact schema above.
- If response fails validation, halt pipeline and inspect route bindings.

---

### TASK 2: Database Schema & Idempotent Ledger Deployment

**1. Context & Objective:**
Design and deploy a relational database schema supporting product catalogs, agent click telemetry, orders, and a double-entry commission ledger.

**2. Step-by-Step Implementation Instructions:**
- Write and execute migration scripts for PostgreSQL:
  ```sql
  -- 1. Merchants Table
  CREATE TABLE merchants (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      name VARCHAR(255) NOT NULL,
      platform VARCHAR(50) NOT NULL, -- 'shopify', 'woocommerce', 'stripe_custom'
      api_credentials_encrypted JSONB NOT NULL,
      commission_rate_bps INT NOT NULL DEFAULT 500, -- 500 bps = 5.0%
      aisl_cut_bps INT NOT NULL DEFAULT 80, -- 80 bps = 0.8%
      created_at TIMESTAMPTZ DEFAULT NOW()
  );

  -- 2. Click & Intent Telemetry
  CREATE TABLE agent_intents (
      click_id UUID PRIMARY KEY, -- UUIDv7
      agent_id VARCHAR(128) NOT NULL,
      sub_id_1 VARCHAR(64),
      sub_id_2 VARCHAR(64),
      merchant_id UUID REFERENCES merchants(id),
      created_at TIMESTAMPTZ DEFAULT NOW()
  );

  -- 3. Attributed Conversions & Double-Entry Ledger
  CREATE TABLE conversions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      click_id UUID REFERENCES agent_intents(click_id),
      merchant_id UUID REFERENCES merchants(id),
      external_order_id VARCHAR(255) NOT NULL UNIQUE,
      gross_amount_cents BIGINT NOT NULL,
      commission_total_cents BIGINT NOT NULL,
      aisl_fee_cents BIGINT NOT NULL,
      agent_payout_cents BIGINT NOT NULL,
      status VARCHAR(50) NOT NULL DEFAULT 'PENDING_SETTLEMENT', -- 'PENDING_SETTLEMENT', 'SETTLED', 'REFUNDED'
      created_at TIMESTAMPTZ DEFAULT NOW()
  );

  -- 4. Idempotency Lock Table for S2S Postbacks
  CREATE TABLE idempotency_keys (
      key VARCHAR(255) PRIMARY KEY,
      created_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- Implement connection pooling and query builder wrappers ensuring automated reconnection.

**3. Validation Gate & Quality Stop-Rule:**
- Execute test migration script against test Postgres instance.
- Assert all tables and foreign keys exist; test unique constraint on `external_order_id`.

---

### TASK 3: Product Feed Normalizer & Agent Discovery Endpoint

**1. Context & Objective:**
Build the catalog query endpoint allowing AI agents to query merchant inventories in real-time, injecting unique `click_id` tokens into product payloads.

**2. Step-by-Step Implementation Instructions:**
- Implement `POST /v1/agent/intent` accepting:
  ```json
  {
    "agent_id": "openai_chatgpt_operator_1",
    "query": "wireless noise cancelling headphones under 300",
    "max_results": 5,
    "sub_ids": { "sub1": "campaign_alpha", "sub2": "prompt_v4" }
  }
  ```
- Connector logic:
  - Read query, check Redis vector/search cache for available merchant listings.
  - If cache miss, dispatch query to Shopify Storefront GraphQL API:
    ```graphql
    query SearchProducts($query: String!) {
      products(first: 5, query: $query) {
        edges {
          node {
            id
            title
            description
            totalInventory
            variants(first: 1) {
              edges {
                node {
                  id
                  price {
                    amount
                    currencyCode
                  }
                }
              }
            }
          }
        }
      }
    }
    ```
- Telemetry generation:
  - Generate a monotonic UUIDv7 for each product result returned: `click_id = uuidv7()`.
  - Store record in `agent_intents` mapping `(click_id, agent_id, sub_id_1, sub_id_2, merchant_id)`.
  - Return canonicalized product listing containing `acp_token` and bound checkout parameters.

**3. Validation Gate & Quality Stop-Rule:**
- Send synthetic query payload to `/v1/agent/intent`.
- Validate that each product record in response includes a valid UUIDv7 `acp_token` and matches real merchant inventory.

---

### TASK 4: Delegated Checkout & Atomic Order Execution Router

**1. Context & Objective:**
Implement the execution route where the AI agent commits the purchase on behalf of the user using an ACP delegated payment token.

**2. Step-by-Step Implementation Instructions:**
- Implement `POST /v1/agent/checkout` accepting:
  ```json
  {
    "acp_token": "018f4a1e-8e3b-7000-8432-1b1f9b3b0001",
    "merchant_id": "018f4a1e-8e3b-7000-8432-1b1f9b3b0000",
    "variant_id": "gid://shopify/ProductVariant/12345678",
    "quantity": 1,
    "payment_credential": {
      "type": "stripe_payment_token",
      "token": "spt_test_9876543210abcdef"
    },
    "shipping_address": {
      "name": "Jane Doe",
      "address1": "123 Market St",
      "city": "San Francisco",
      "state": "CA",
      "postal_code": "94105",
      "country": "US"
    }
  }
  ```
- Execution Flow:
  1. Retrieve `agent_intents` by `acp_token`. Reject with `404` if invalid or expired (>24 hours).
  2. Instantiate merchant payment execution:
     - Use Stripe Delegated Payment Token API to forward `payment_credential.token` directly to merchant’s connected Stripe account (`Stripe-Account: {merchant_stripe_id}`).
  3. Create Shopify Order:
     - Dispatch checkout via Shopify Admin API `/orders.json` marked as paid with external gateway reference.
  4. Commission Calculation:
     - `gross_amount = order.total_price_cents`
     - `commission_total = gross_amount * (merchant.commission_rate_bps / 10000)`
     - `aisl_fee = gross_amount * (merchant.aisl_cut_bps / 10000)`
     - `agent_payout = commission_total - aisl_fee`
  5. Commit row to `conversions` table with status `PENDING_SETTLEMENT`.

**3. Validation Gate & Quality Stop-Rule:**
- Mock Stripe Delegated Token and Shopify API responses.
- Assert that order creation succeeds and commission calculations match mathematical ledger invariants exactly.

---

### TASK 5: S2S Webhook Ingestion, Deduplication & Clawback Reconciler

**1. Context & Objective:**
Safeguard the system against double-spend conversions, track refund clawbacks, and settle commissions accurately via server-to-server callbacks.

**2. Step-by-Step Implementation Instructions:**
- Implement `POST /v1/webhooks/stripe-acp` accepting merchant and gateway webhooks.
- Signature verification:
  - Enforce `stripe.webhooks.constructEvent(payload, sig, endpointSecret)` using raw HTTP body.
- Idempotency & Deduplication:
  - Generate key: `dedup_key = "event:" + event.id`.
  - Execute atomic Redis `SETNX dedup_key 1` with a 7-day TTL (`EX 604800`).
  - If returned `0`, abort immediately with `200 OK (DUPLICATE_EVENT_IGNORED)`.
- Event Handling:
  - Case `payment_intent.succeeded`: Update conversion record to `SETTLED`.
  - Case `charge.refunded` or `charge.dispute.created`:
    - Query `conversions` by Stripe charge ID.
    - Insert negative offset entry into ledger:
      - `gross_amount_cents: -original_amount`
      - `commission_total_cents: -original_commission`
      - `aisl_fee_cents: -original_aisl_fee`
      - `agent_payout_cents: -original_agent_payout`
    - Update parent conversion status to `REFUNDED`.

**3. Validation Gate & Quality Stop-Rule:**
- Transmit two identical webhook payloads concurrently.
- Verify that exactly one event updates the ledger, and the duplicate returns `200 OK` without ledger modification.

---

### TASK 6: Comprehensive End-to-End Test Suite & Dockerization

**1. Context & Objective:**
Package the proxy service for single-command production deployment and verify end-to-end functionality via synthetic tests.

**2. Step-by-Step Implementation Instructions:**
- Create multi-stage `Dockerfile`:
  - Build stage: Compile TypeScript, prune dev-dependencies.
  - Runner stage: Alpine Node.js / Distroless image exposing port `8080`.
- Create `docker-compose.yml` linking:
  - Service `aisl-proxy`
  - Service `postgres:16-alpine`
  - Service `redis:7-alpine`
- Build an end-to-end synthetic test runner (`tests/e2e.test.ts`):
  1. Boot full stack.
  2. Fetch `/.well-known/acp/config.json` -> Assert schema.
  3. Send search query to `/v1/agent/intent` -> Assert product array and `acp_token`.
  4. Send checkout to `/v1/agent/checkout` with token -> Assert order ID returned.
  5. Fire synthetic `charge.refunded` webhook -> Assert ledger writes negative balancing credit.

**3. Validation Gate & Quality Stop-Rule:**
- Run `npm test` or `docker compose up --abort-on-container-exit`.
- All integration tests must pass with zero errors before project handoff.

---

## 4. AGENT EXECUTION COMMAND

To execute this blueprint autonomously, run:

```bash
# Initialize project workspace
mkdir aisl-proxy && cd aisl-proxy
git init

# Follow Step 1 through Step 6 deterministically:
# 1. Scaffolding & ACP config route
# 2. Migration runner for DB schema
# 3. Catalog proxy with UUIDv7 click tokenization
# 4. Delegated checkout processor
# 5. Webhook listener with Redis atomic SETNX deduplication
# 6. Docker packaging and E2E verification
```
