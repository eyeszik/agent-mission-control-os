# Agent Mission Control OS - Gemini AI Instructions

## Context
This repository (`agent-mission-control-os`) contains the orchestration logic, state files, and execution blueprints for a multi-agent system.

## Rules for Gemini CLI
1. **Architecture Preservation:** Do not modify the JSON/YAML state files (e.g., `execution_blueprint.json`, `task_dag.json`) unless explicitly instructed.
2. **Agent Handoffs:** Respect the boundaries defined in `codex/codex_file_handoff_matrix.md`.
3. **No Unprompted Execution:** Do not start implementing the runtime or executing the task DAG automatically. Wait for explicit directives.
4. **Formatting:** Maintain strict schema compliance when editing JSON or YAML configuration files. Always validate syntax before finalizing edits.
