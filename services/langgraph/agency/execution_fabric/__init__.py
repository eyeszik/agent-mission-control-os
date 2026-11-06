"""Execution fabric: the governed execution plane over the compiled planners.

``schedule`` reads planner output; ``consumer.execute_mission`` runs eligible
cells through the canonical skill dispatcher and ProjectOS with a two-phase
write-ahead; ``coverage`` derives read models (coverage graph, autonomy
envelopes, cross-modal witness). See ``docs/execution-fabric.md``.
"""
