from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping


class NextActionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectExecutionState:
    completed_work_order_ids: frozenset[str] = frozenset()
    stale_dependency_refs: frozenset[str] = frozenset()
    unavailable_tools: frozenset[str] = frozenset()
    blocked_work_order_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ActionScore:
    work_order_id: str
    score: float
    completion_criticality: float
    critical_path_unblocking: float
    uncertainty_reduction: float
    information_gain: float
    reversibility: float
    resource_efficiency: float


@dataclass(frozen=True)
class NextActionSelection:
    selected_work_order_id: str | None
    eligible_work_order_ids: tuple[str, ...]
    blocked: dict[str, tuple[str, ...]]
    scores: tuple[ActionScore, ...]
    selection_hash: str
    terminal_hint: str


class NextBestActionEngine:
    """Deterministically select the highest-value execution-ready Work Order."""

    WEIGHTS = {
        "completion_criticality": 0.30,
        "critical_path_unblocking": 0.25,
        "uncertainty_reduction": 0.15,
        "information_gain": 0.10,
        "reversibility": 0.10,
        "resource_efficiency": 0.10,
    }

    def select(
        self,
        work_orders: Iterable[Mapping[str, Any]],
        state: ProjectExecutionState,
        *,
        uncertainty_reduction: Mapping[str, float] | None = None,
        information_gain: Mapping[str, float] | None = None,
        resource_efficiency: Mapping[str, float] | None = None,
    ) -> NextActionSelection:
        orders = [dict(x) for x in work_orders]
        if not orders:
            raise NextActionError("work_orders must not be empty")
        by_id = {str(w["work_order_id"]): w for w in orders}
        if len(by_id) != len(orders):
            raise NextActionError("duplicate work_order_id")

        self._validate_graph(by_id)
        children = {wid: set() for wid in by_id}
        for wid, wo in by_id.items():
            for dep in wo.get("dependency_refs", []):
                children[str(dep)].add(wid)

        descendants = {wid: self._descendants(wid, children) for wid in by_id}
        max_desc = max((len(x) for x in descendants.values()), default=0)
        max_children = max((len(x) for x in children.values()), default=0)

        blocked: dict[str, tuple[str, ...]] = {}
        eligible: list[str] = []
        scores: list[ActionScore] = []
        uncertainty_reduction = uncertainty_reduction or {}
        information_gain = information_gain or {}
        resource_efficiency = resource_efficiency or {}

        for wid in sorted(by_id):
            wo = by_id[wid]
            if wid in state.completed_work_order_ids:
                continue
            reasons = self._block_reasons(wid, wo, state)
            if reasons:
                blocked[wid] = tuple(sorted(set(reasons)))
                continue
            eligible.append(wid)

            cc = (len(descendants[wid]) + 1) / max(1, len(by_id))
            cpu = (len(children[wid]) / max_children) if max_children else 0.0
            ur = self._bounded(uncertainty_reduction.get(wid, 0.0))
            ig = self._bounded(information_gain.get(wid, 0.0))
            rev = self._reversibility(wo.get("side_effect_class"))
            re = self._bounded(resource_efficiency.get(wid, 0.5))
            score = (
                self.WEIGHTS["completion_criticality"] * cc
                + self.WEIGHTS["critical_path_unblocking"] * cpu
                + self.WEIGHTS["uncertainty_reduction"] * ur
                + self.WEIGHTS["information_gain"] * ig
                + self.WEIGHTS["reversibility"] * rev
                + self.WEIGHTS["resource_efficiency"] * re
            )
            scores.append(ActionScore(
                work_order_id=wid,
                score=round(score, 9),
                completion_criticality=round(cc, 9),
                critical_path_unblocking=round(cpu, 9),
                uncertainty_reduction=ur,
                information_gain=ig,
                reversibility=rev,
                resource_efficiency=re,
            ))

        scores.sort(key=lambda x: (-x.score, x.work_order_id))
        selected = scores[0].work_order_id if scores else None
        if selected is not None:
            terminal_hint = "CONTINUE"
        elif len(state.completed_work_order_ids & set(by_id)) == len(by_id):
            terminal_hint = "COMPLETE_CANDIDATE"
        else:
            terminal_hint = "BLOCKED"

        payload = {
            "selected": selected,
            "eligible": sorted(eligible),
            "blocked": {k: list(v) for k, v in sorted(blocked.items())},
            "scores": [asdict(s) for s in scores],
            "terminal_hint": terminal_hint,
        }
        selection_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return NextActionSelection(
            selected_work_order_id=selected,
            eligible_work_order_ids=tuple(sorted(eligible)),
            blocked=blocked,
            scores=tuple(scores),
            selection_hash=selection_hash,
            terminal_hint=terminal_hint,
        )

    @staticmethod
    def _block_reasons(wid: str, wo: Mapping[str, Any], state: ProjectExecutionState) -> list[str]:
        reasons: list[str] = []
        deps = {str(x) for x in wo.get("dependency_refs", [])}
        unmet = sorted(deps - set(state.completed_work_order_ids))
        if unmet:
            reasons.append("UNSATISFIED_DEPENDENCY:" + ",".join(unmet))
        stale = sorted(deps & set(state.stale_dependency_refs))
        if stale:
            reasons.append("STALE_DEPENDENCY:" + ",".join(stale))
        if wid in state.blocked_work_order_ids:
            reasons.append("EXPLICITLY_BLOCKED")
        rt = wo.get("_runtime") or {}
        if not bool(rt.get("execution_ready", False)):
            for blocker in rt.get("blockers") or ["EXECUTION_NOT_READY"]:
                reasons.append(str(blocker))
        tools = {str(x) for x in wo.get("tool_plan", [])}
        unavailable = sorted(tools & set(state.unavailable_tools))
        if unavailable:
            reasons.append("TOOL_UNAVAILABLE:" + ",".join(unavailable))
        return reasons

    @staticmethod
    def _validate_graph(by_id: Mapping[str, Mapping[str, Any]]) -> None:
        for wid, wo in by_id.items():
            for dep in wo.get("dependency_refs", []):
                if dep not in by_id:
                    raise NextActionError(f"{wid} references unknown dependency {dep}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node: str) -> None:
            if node in visiting:
                raise NextActionError("work order graph contains a cycle")
            if node in visited:
                return
            visiting.add(node)
            for dep in by_id[node].get("dependency_refs", []):
                dfs(str(dep))
            visiting.remove(node)
            visited.add(node)

        for wid in by_id:
            dfs(wid)

    @staticmethod
    def _descendants(start: str, children: Mapping[str, set[str]]) -> set[str]:
        seen: set[str] = set()
        stack = list(children[start])
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(children[node])
        return seen

    @staticmethod
    def _bounded(value: float) -> float:
        return round(max(0.0, min(1.0, float(value))), 9)

    @staticmethod
    def _reversibility(side_effect_class: Any) -> float:
        return {
            "PURE": 1.0,
            "DRAFT": 1.0,
            "REVERSIBLE_WRITE": 0.65,
            "IRREVERSIBLE_WRITE": 0.0,
        }.get(str(side_effect_class), 0.0)
