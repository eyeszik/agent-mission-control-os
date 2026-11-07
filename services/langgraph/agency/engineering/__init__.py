"""Governed repository engineering extensions.

This package owns wire contracts and policy adapters only. Durable state remains
in ``persistence.durable_runs`` and ``agency.durable``; it introduces no second
scheduler, store, or state machine.
"""

from .contracts import CONTRACT_VERSION

__all__ = ["CONTRACT_VERSION"]
