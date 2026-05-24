# Cloudflare Infrastructure Scaffold

This directory contains placeholders and structural scaffolds for running Agent Mission Control OS orchestration logic at the edge.

## Rules
1. **No Deployment:** Do not run `wrangler deploy` until the LangGraph backend logic is fully integrated and tested.
2. **Canonical State Bounds:** Do not store full generated artifacts or vector embeddings inside the Durable Object memory. Use R2 and Vector databases.
3. **No Real Credentials:** The `wrangler.example.toml` must remain sanitized.
