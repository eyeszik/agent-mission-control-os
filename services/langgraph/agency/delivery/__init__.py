"""Unified delivery: contract, critic, workflow pinning and the release handshake.

Owner map (see docs/unified-delivery.md):

* DeliveryContract defines WHAT success means; it grants nothing.
* N3 roles decide WHO may produce; N2 guards, approval authority and the
  approval record decide WHETHER release may happen.
* ProjectOS/N4 owns artifact and dependency state and is the only invalidator.
* The critic decides deterministic satisfaction; the candidate manifest fixes
  the exact payload before approval; the receipt records what was released.
* The CRG and blast-radius certificate are derived read models with no store.
"""
