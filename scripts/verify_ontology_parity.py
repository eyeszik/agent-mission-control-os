#!/usr/bin/env python3
"""Verify the N1/N2 ontology is identical across Python and TypeScript.

The backend enforces the ontology; the frontend renders and pre-validates
against it. If the two vocabularies drift, the UI will offer states and
departments the server rejects, and the mismatch will surface as an opaque 4xx
at the worst possible moment. This gate makes drift a build failure instead.

Parsing the TypeScript with regular expressions is deliberate: adding a Node
toolchain dependency to a Python CI step to read four constant arrays would
cost more than it proves.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ONTOLOGY_TS = ROOT / "packages/shared/src/schemas/ontology.ts"
LIFECYCLE_TS = ROOT / "packages/shared/src/schemas/lifecycle.ts"
PROJECT_OS_TS = ROOT / "packages/shared/src/schemas/projectOs.ts"


class ParityError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"ontology-parity FAIL: {message}")


def _read(path: Path) -> str:
    if not path.is_file():
        raise ParityError(f"missing mirrored schema: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def _string_array(text: str, name: str, path: Path) -> list[str]:
    """Extract `const NAME = ['a', 'b'] as const;` / `: T[] = [...]`."""
    match = re.search(rf"const\s+{re.escape(name)}\b[^=]*=\s*\[(.*?)\]", text, re.DOTALL)
    if not match:
        raise ParityError(f"{path.relative_to(ROOT)} does not declare {name}")
    return re.findall(r"'([^']*)'", match.group(1))


def _record_of_arrays(text: str, name: str, path: Path) -> dict[str, list[str]]:
    """Extract `const NAME: Record<...> = { key: ['a'], ... };`."""
    match = re.search(rf"const\s+{re.escape(name)}\b[^=]*=\s*\{{(.*?)\n\}};", text, re.DOTALL)
    if not match:
        raise ParityError(f"{path.relative_to(ROOT)} does not declare {name}")
    result: dict[str, list[str]] = {}
    for key, values in re.findall(r"(\w+)\s*:\s*\[(.*?)\]", match.group(1), re.DOTALL):
        result[key] = re.findall(r"'([^']*)'", values)
    return result


def _record_of_strings(text: str, name: str, path: Path) -> dict[str, str]:
    match = re.search(rf"const\s+{re.escape(name)}\b[^=]*=\s*\{{(.*?)\n\}};", text, re.DOTALL)
    if not match:
        raise ParityError(f"{path.relative_to(ROOT)} does not declare {name}")
    return dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", match.group(1)))


def _compare(label: str, python_value, typescript_value) -> list[str]:
    if python_value == typescript_value:
        return []
    if isinstance(python_value, dict) and isinstance(typescript_value, dict):
        problems = []
        for key in sorted(set(python_value) | set(typescript_value)):
            if key not in python_value:
                problems.append(f"{label}: TypeScript declares '{key}', Python does not")
            elif key not in typescript_value:
                problems.append(f"{label}: Python declares '{key}', TypeScript does not")
            elif python_value[key] != typescript_value[key]:
                problems.append(
                    f"{label}.{key}: Python={python_value[key]} TypeScript={typescript_value[key]}"
                )
        return problems
    return [f"{label}: Python={python_value} TypeScript={typescript_value}"]


def check_n1(problems: list[str]) -> None:
    from services.langgraph.agency.kernel.ontology import (
        ARTIFACT_TYPE_OWNER,
        ONTOLOGY_VERSION,
        ArtifactType,
        Capability,
        Department,
    )

    text = _read(ONTOLOGY_TS)

    version = re.search(r"ONTOLOGY_VERSION\s*=\s*'([^']+)'", text)
    if not version or version.group(1) != ONTOLOGY_VERSION:
        problems.append(
            f"ontology version: Python={ONTOLOGY_VERSION} "
            f"TypeScript={version.group(1) if version else 'missing'}"
        )

    problems += _compare(
        "departments",
        sorted(item.value for item in Department),
        sorted(_string_array(text, "DEPARTMENTS", ONTOLOGY_TS)),
    )
    problems += _compare(
        "capabilities",
        sorted(item.value for item in Capability),
        sorted(_string_array(text, "CAPABILITIES", ONTOLOGY_TS)),
    )
    problems += _compare(
        "artifact types",
        sorted(item.value for item in ArtifactType),
        sorted(_string_array(text, "AGENCY_ARTIFACT_TYPES", ONTOLOGY_TS)),
    )
    problems += _compare(
        "artifact ownership",
        {key.value: value.value for key, value in ARTIFACT_TYPE_OWNER.items()},
        _record_of_strings(text, "ARTIFACT_TYPE_OWNER", ONTOLOGY_TS),
    )


def check_n2(problems: list[str]) -> None:
    from services.langgraph.agency.kernel.lifecycle import (
        DEGRADED_PROVENANCE_MODES,
        LIFECYCLE_VERSION,
        lifecycle_snapshot,
    )

    text = _read(LIFECYCLE_TS)

    version = re.search(r"LIFECYCLE_VERSION\s*=\s*'([^']+)'", text)
    if not version or version.group(1) != LIFECYCLE_VERSION:
        problems.append(
            f"lifecycle version: Python={LIFECYCLE_VERSION} "
            f"TypeScript={version.group(1) if version else 'missing'}"
        )

    snapshot = lifecycle_snapshot()["entities"]
    for entity, prefix in (("engagement", "ENGAGEMENT"), ("workstream", "WORKSTREAM"), ("artifact", "ARTIFACT")):
        data = snapshot[entity]
        problems += _compare(
            f"{entity} states",
            sorted(data["transitions"]),
            sorted(_string_array(text, f"{prefix}_STATES", LIFECYCLE_TS)),
        )
        problems += _compare(
            f"{entity} transitions",
            {state: sorted(targets) for state, targets in data["transitions"].items()},
            {state: sorted(targets) for state, targets in _record_of_arrays(text, f"{prefix}_TRANSITIONS", LIFECYCLE_TS).items()},
        )
        problems += _compare(
            f"{entity} client-visible states",
            sorted(data["client_visible"]),
            sorted(_string_array(text, f"{prefix}_CLIENT_VISIBLE", LIFECYCLE_TS)),
        )
        problems += _compare(
            f"{entity} dependency-gated states",
            sorted(data["dependency_gated"]),
            sorted(_string_array(text, f"{prefix}_DEPENDENCY_GATED", LIFECYCLE_TS)),
        )

    problems += _compare(
        "degraded provenance modes",
        sorted(DEGRADED_PROVENANCE_MODES),
        sorted(_string_array(text, "DEGRADED_PROVENANCE_MODES", LIFECYCLE_TS)),
    )


def check_project_os(problems: list[str]) -> None:
    """Project OS vocabularies: folders, lifecycles, memory authority, stages."""
    from services.langgraph.agency.project_os import vocabulary as v

    text = _read(PROJECT_OS_TS)
    version = re.search(r"PROJECT_OS_VERSION\s*=\s*'([^']+)'", text)
    if not version or version.group(1) != v.PROJECT_OS_VERSION:
        problems.append(
            f"project OS version: Python={v.PROJECT_OS_VERSION} "
            f"TypeScript={version.group(1) if version else 'missing'}"
        )
    ordered = {
        "WORKSPACE_FOLDERS": list(v.WORKSPACE_FOLDERS),
        "SYSTEM_FOLDERS": list(v.SYSTEM_FOLDERS),
        "MEMORY_AUTHORITY_ORDER": list(v.MEMORY_AUTHORITY_ORDER),
        "KNOWLEDGE_STAGES": list(v.KNOWLEDGE_STAGES),
        "ROUTING_TIERS": list(v.ROUTING_TIERS),
        "LEARNING_PROMOTION_STAGES": list(v.LEARNING_PROMOTION_STAGES),
    }
    for name, python_value in ordered.items():
        # Order is semantic here (authority ranking, pipeline order).
        problems += _compare(f"project OS {name}", python_value, _string_array(text, name, PROJECT_OS_TS))
    unordered = {
        "PROJECT_LIFECYCLE_STATES": v.ProjectLifecycle,
        "STORAGE_BACKENDS": v.StorageBackend,
        "STORAGE_OBJECT_STATUSES": v.StorageObjectStatus,
        "ACTIVITY_TYPES": v.ActivityType,
        "CONTENT_STATES": v.ContentState,
        "CONTENT_KINDS": v.ContentKind,
        "SCHEDULED_JOB_KINDS": v.ScheduledJobKind,
        "SCHEDULED_JOB_STATUSES": v.ScheduledJobStatus,
        "PUBLICATION_STATES": v.PublicationState,
        "PROVIDER_MODES": v.ProviderMode,
        "MEMORY_SCOPES": v.MemoryScope,
        "MEMORY_STATUSES": v.MemoryStatus,
        "RIGHTS_CLASSES": v.RightsClass,
        "KNOWLEDGE_STATUSES": v.KnowledgeStatus,
        "CAPABILITY_STATUSES": v.CapabilityStatus,
    }
    for name, enum_cls in unordered.items():
        problems += _compare(
            f"project OS {name}",
            sorted(item.value for item in enum_cls),
            sorted(_string_array(text, name, PROJECT_OS_TS)),
        )
    problems += _compare(
        "project OS APPROVAL_BOUND_CONTENT_STATES",
        sorted(v.APPROVAL_BOUND_CONTENT_STATES),
        sorted(_string_array(text, "APPROVAL_BOUND_CONTENT_STATES", PROJECT_OS_TS)),
    )
    for name, transitions in (("CONTENT_TRANSITIONS", v.CONTENT_TRANSITIONS), ("PROJECT_TRANSITIONS", v.PROJECT_TRANSITIONS)):
        problems += _compare(
            f"project OS {name}",
            {state: sorted(targets) for state, targets in transitions.items()},
            {state: sorted(targets) for state, targets in _record_of_arrays(text, name, PROJECT_OS_TS).items()},
        )
    horizons = re.search(r"CALENDAR_HORIZON_DAYS\s*=\s*\[([^\]]*)\]", text)
    ts_horizons = [int(x) for x in re.findall(r"\d+", horizons.group(1))] if horizons else []
    problems += _compare("project OS CALENDAR_HORIZON_DAYS", list(v.CALENDAR_HORIZON_DAYS), ts_horizons)


def main() -> None:
    problems: list[str] = []
    check_n1(problems)
    check_n2(problems)
    check_project_os(problems)
    if problems:
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        raise ParityError(f"{len(problems)} ontology parity violation(s) between Python and TypeScript")
    print("ontology-parity: N1 department ontology, N2 lifecycle matrices and project OS vocabularies agree across Python and TypeScript")


if __name__ == "__main__":
    main()
