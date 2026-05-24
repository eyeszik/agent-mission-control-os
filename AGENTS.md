# Agent Mission Control OS - Agents Directory

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
