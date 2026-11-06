"""Mission council: George (strategy) -> Fable/Cipher (security) -> Sentinel gate -> Arty (prototype).

One mission lifecycle, three orchestration engines (LangGraph, CrewAI, AutoGen),
one model abstraction (deterministic mock by default, the repository's model
router when real models are enabled). A mission is a ``runs`` row, so approvals,
events and checkpoints reuse the existing primitives. See docs/mission-council.md.
"""
