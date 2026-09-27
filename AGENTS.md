# Agent Mission Control OS - Agents Directory

## Base44 Dev Environment

This is a pnpm monorepo: `apps/web` (Next.js 16 + React 19) and `services/langgraph` (FastAPI + LangGraph). The shared TypeScript contracts live in `packages/shared`.

**Running locally (docker-compose.base44.yml):**
- `api` service: Python 3.12, installs deps from `services/langgraph/pyproject.toml`, runs `uvicorn ... --reload` from the repo root on port 8000.
- `web` service: Node 22, runs `pnpm install` → builds `@amc/shared` → `next dev` on port 3000.
- In local mode (`AMC_ENV=local`, `AMC_AUTH_MODE=local`): SQLite file-based DB (no Postgres needed), local loopback auth (no Supabase needed), OpenAI optional (generation degrades gracefully).
- The `@amc/shared` package must be built (`pnpm --filter @amc/shared build`) before the web app starts — its `main` points to `dist/index.js`.
- Backend imports use `services.langgraph.*` namespace packages (no `__init__.py` in `services/`); must run from repo root.
- CORS (`AMC_CORS_ALLOWED_ORIGINS`) must include the web preview origin; the web `NEXT_PUBLIC_API_BASE_URL` must point to the API's public URL.
- Uvicorn must bind `0.0.0.0` (not 127.0.0.1) to be reachable through Docker port mapping.

**Verify:** `curl http://localhost:8000/ready` → `{"ready":true,...}` and `curl http://localhost:3000/mission-control` → 200.



This document outlines the specialized agents, their roles, and their responsibilities within the Agent Mission Control OS ecosystem.

## Core Agents

1. **Orchestrator Agent**
   - **Role:** High-level task delegation and workflow management.
   - **Responsibilities:** Parses incoming requirements, breaks them down into sub-tasks (Task DAG), and assigns them to specialized agents. Monitors the execution flow.

2. **Execution Agent (Codex)**
   - **Role:** Code generation and system modification.
   - **Responsibilities:** Executes specific implementation tasks, writes configuration files, and applies changes based on the execution blueprint.

3. **Validation Agent**
   - **Role:** Quality assurance and constraint checking.
   - **Responsibilities:** Reviews generated artifacts against the `constraint_ledger.yaml` and `validation_report.json` formats to ensure correctness, security, and stability before final approval.

4. **Governance Agent**
   - **Role:** Risk management and compliance.
   - **Responsibilities:** Evaluates actions against the `risk_register.json` and updates the `governance_decisions.json`.
