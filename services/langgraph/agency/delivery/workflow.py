"""Workflow version pinning for the live agency graph.

A run's graph topology is chosen once, when the run is created, and persisted
with the run. Resume and inspection rebuild the graph from that pin, never from
the current process environment: flipping ``AMC_CONTRACT_MODE`` changes which
topology *new* runs get, and nothing else. A run created before pinning existed
carries no pin and is always treated as ``agency/v1-legacy``.

This module is the single source of both topologies. ``build_agency_workflow``
compiles the graph from :func:`topology`, and :func:`graph_fingerprint` hashes
the same structure, so a code change that alters a version's topology changes
its fingerprint and a paused run pinned to the old fingerprint refuses to
resume instead of replaying through a different graph.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Optional

from services.langgraph.agency.execution.canonical import canonical_hash

WorkflowVersion = Literal["agency/v1-legacy", "agency/v2-contract"]
ContractMode = Literal["off", "shadow", "enforce"]

LEGACY_WORKFLOW: WorkflowVersion = "agency/v1-legacy"
CONTRACT_WORKFLOW: WorkflowVersion = "agency/v2-contract"
CONTRACT_MODES: tuple[ContractMode, ...] = ("off", "shadow", "enforce")
CONTRACT_MODE_ENV = "AMC_CONTRACT_MODE"
CONTRACT_CHECK_NODE = "contract_check"
INTERRUPT_POINTS: tuple[str, ...] = ("delivery",)

_LEGACY_NODES: tuple[str, ...] = (
    "brief_intake",
    "brand_strategy",
    "creative_concepting",
    "copywriting",
    "design_brief",
    "campaign_assembly",
    "brand_safety_qa",
    "hitl_gate",
    "delivery",
)
# v2 evaluates the delivery contract after QA and before the HITL gate, so the
# reviewer sees the contract result and nothing runs between candidate sealing
# (done by the API after the graph pauses) and the static delivery interrupt.
_CONTRACT_NODES: tuple[str, ...] = (
    *_LEGACY_NODES[: _LEGACY_NODES.index("hitl_gate")],
    CONTRACT_CHECK_NODE,
    *_LEGACY_NODES[_LEGACY_NODES.index("hitl_gate"):],
)
_NODES: dict[str, tuple[str, ...]] = {
    LEGACY_WORKFLOW: _LEGACY_NODES,
    CONTRACT_WORKFLOW: _CONTRACT_NODES,
}


class WorkflowPinError(ValueError):
    """A run's pin is unknown or no longer matches the code's topology."""


def topology(workflow_version: str) -> dict[str, Any]:
    nodes = _NODES.get(workflow_version)
    if nodes is None:
        raise WorkflowPinError(f"unknown workflow_version {workflow_version!r}")
    edges = [[nodes[i], nodes[i + 1]] for i in range(len(nodes) - 1)]
    return {
        "workflow_version": workflow_version,
        "node_ids": list(nodes),
        "edges": edges,
        "interrupt_points": list(INTERRUPT_POINTS),
    }


def graph_fingerprint(workflow_version: str) -> str:
    return canonical_hash(topology(workflow_version))


def contract_mode_from_env(environ: Optional[Mapping[str, str]] = None) -> ContractMode:
    raw = ((environ if environ is not None else os.environ).get(CONTRACT_MODE_ENV) or "off").strip().lower()
    if raw not in CONTRACT_MODES:
        raise WorkflowPinError(f"{CONTRACT_MODE_ENV} must be one of off, shadow, enforce")
    return raw  # type: ignore[return-value]


@dataclass(frozen=True)
class WorkflowPin:
    workflow_version: WorkflowVersion
    contract_mode: ContractMode
    graph_fingerprint: str

    def as_metadata(self) -> dict[str, str]:
        return {
            "workflow_version": self.workflow_version,
            "contract_mode": self.contract_mode,
            "graph_fingerprint": self.graph_fingerprint,
        }

    @property
    def uses_contract(self) -> bool:
        return self.workflow_version == CONTRACT_WORKFLOW

    @property
    def enforces_contract(self) -> bool:
        return self.contract_mode == "enforce"


def pin_for_new_run(mode: ContractMode) -> WorkflowPin:
    version: WorkflowVersion = LEGACY_WORKFLOW if mode == "off" else CONTRACT_WORKFLOW
    return WorkflowPin(version, mode, graph_fingerprint(version))


def pinned_workflow(metadata: Optional[Mapping[str, Any]]) -> WorkflowPin:
    """The pin a run was created with. Runs without one are legacy runs."""

    pin = (metadata or {}).get("workflow") if isinstance(metadata, Mapping) else None
    if not pin:
        return WorkflowPin(LEGACY_WORKFLOW, "off", graph_fingerprint(LEGACY_WORKFLOW))
    version = pin.get("workflow_version")
    mode = pin.get("contract_mode")
    if version not in _NODES or mode not in CONTRACT_MODES:
        raise WorkflowPinError("run carries an unknown workflow pin")
    return WorkflowPin(version, mode, str(pin.get("graph_fingerprint") or ""))


def assert_pin_current(pin: WorkflowPin) -> None:
    """Refuse to rebuild a run against a topology it was not created with."""

    if pin.graph_fingerprint != graph_fingerprint(pin.workflow_version):
        raise WorkflowPinError(
            f"workflow topology for {pin.workflow_version} changed since this run was created"
        )
