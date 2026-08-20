# Production Provider Selection

Selected for this phase:

- Supabase: production Postgres + Auth primitives.
- Vercel: Next.js frontend deployment target; FastAPI deployment supported by configuration, but backend deployment remains a distinct project/runtime boundary so durable execution is not coupled to frontend build settings.

External publication, paid media, and third-party analytics providers remain disabled until concrete provider credentials/scopes are connected and verified. The repository will ship provider interfaces, policy gates, audit records, and deterministic dry-run implementations first.
