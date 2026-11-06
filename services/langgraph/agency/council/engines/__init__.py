"""Engine adapters: LangGraph (native), CrewAI and AutoGen (optional ``council`` extra)."""

from __future__ import annotations

from .base import CouncilEngine, EngineUnavailable


def get_engine(name: str) -> CouncilEngine:
    if name == "langgraph":
        from .langgraph_engine import LangGraphEngine

        return LangGraphEngine()
    if name == "crewai":
        from .crewai_engine import CrewAIEngine

        return CrewAIEngine()
    if name == "autogen":
        from .autogen_engine import AutoGenEngine

        return AutoGenEngine()
    raise EngineUnavailable(name, "UNSUPPORTED_ENGINE")


def engine_catalog() -> list[dict]:
    out = []
    for name in ("langgraph", "crewai", "autogen"):
        available, reason = get_engine(name).availability()
        out.append({"engine": name, "available": available, "detail": reason})
    return out


__all__ = ["engine_catalog", "get_engine"]
