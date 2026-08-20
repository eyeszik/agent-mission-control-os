# Production Foundation Phase

This branch is reserved for the production foundation work that promotes the local/CI-verified Agent Mission Control stack toward a deployable production architecture without fabricating external credentials or authorizing irreversible publication/spend.

## Target architecture

- **Identity:** Supabase Auth; backend validates bearer JWTs and derives tenant/user authorization server-side.
- **Database:** Supabase Postgres for durable runs, approvals, idempotency, events, checkpoints, analytics ingestion, publication ledger, and spend-policy records.
- **Secrets:** deployment-platform environment variables; no secrets committed to Git. Production variables are documented but values remain provider-managed.
- **Frontend deployment:** Vercel Next.js project.
- **Backend deployment:** Vercel FastAPI/Python project or equivalent Python runtime with Postgres-backed durability. Deployment configuration must remain portable and explicit.
- **External publication:** adapter interface + dry-run provider; no real provider is enabled until credentials and scopes are verified.
- **Paid media:** policy/approval ledger + disabled provider adapter; no spend occurs by default.
- **Analytics:** normalized event ingestion + first-party production metrics; third-party analytics remains optional until a real source is configured.

## Completion gates

1. Production auth mode exists and local auth remains isolated to local/CI.
2. Postgres schema is migration-managed and production-safe.
3. Backend persistence supports Postgres without SQLite-only assumptions.
4. Secret/config contract is explicit; production boot fails closed when required values are absent.
5. Vercel deployment manifests exist for frontend/backend boundaries.
6. Publication and paid-media modules are capability-gated, auditable, idempotent, and default disabled.
7. Analytics schema and ingestion path are implemented without claiming third-party data that is not connected.
8. CI validates production configuration, contracts, and provider-disabled behavior.
9. No external publishing or spend is executed without explicit provider configuration and authorization.
