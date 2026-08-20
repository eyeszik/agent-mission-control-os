# Production Boundary

This repository must distinguish **implemented capability** from **externally activated capability**.

Implemented in this phase: production configuration contracts, provider adapters, audit/policy records, deployment manifests, Postgres migrations, authentication verification hooks, analytics ingestion, and CI production-readiness checks.

Not automatically activated: real social/ad publication, paid media spend, third-party analytics ingestion, or any external mutation requiring provider credentials/scopes. Those remain fail-closed until concrete provider configuration is verified.
