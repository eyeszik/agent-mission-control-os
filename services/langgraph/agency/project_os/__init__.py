"""Project OS: PROJECT is the durable unit of system state.

tenant → project → (brand / campaign / workstream) → artifact → version →
evidence → dependencies → approval → execution receipt → observation receipt
→ measurement → learning signal.

Runs are executions within projects; chats are interfaces into projects; the
filesystem workspace is a materialized view; external providers are adapters;
memory is scoped knowledge. This package holds the pure contracts and policies.
Persistence lives in ``services/langgraph/persistence/{projects,project_ops,
project_knowledge,project_media,portfolio}.py`` and the HTTP surface in
``api/routes/{projects,project_ops,portfolio}.py``.
"""

from .vocabulary import PROJECT_OS_VERSION, WORKSPACE_SCHEMA_VERSION

__all__ = ["PROJECT_OS_VERSION", "WORKSPACE_SCHEMA_VERSION"]
