from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RegistryIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeRole:
    role_id: str
    title: str
    skill_name: str
    department: str
    family: str
    skill_path: str
    organizational_seniority: str
    capabilities: tuple[str, ...]
    runtime_authority: dict[str, Any]


@dataclass(frozen=True)
class RuntimePhase:
    phase_id: str
    slug: str
    name: str
    orchestrator_ids: tuple[str, ...]
    gate_id: str
    output_contract: str


class RoleOSRegistry:
    """Read-only, hash-verified runtime view of Agency Role OS v2 registries."""

    REQUIRED_FILES = (
        "roles.runtime.json",
        "orchestrators.runtime.json",
        "phases.runtime.json",
        "capability_index.runtime.json",
        "authority_registry.runtime.json",
        "routing_index.runtime.json",
        "state_model.runtime.json",
    )

    def __init__(self, runtime_root: Path | str):
        self.root = Path(runtime_root)
        self.manifest = self._load_json("manifest.runtime.json")
        self._verify_manifest()

        raw_roles = self._load_json("roles.runtime.json")
        self.roles: dict[str, RuntimeRole] = {
            r["role_id"]: RuntimeRole(
                role_id=r["role_id"],
                title=r["title"],
                skill_name=r["skill_name"],
                department=r["department"],
                family=r["family"],
                skill_path=r["skill_path"],
                organizational_seniority=r["organizational_seniority"],
                capabilities=tuple(r["capabilities"]),
                runtime_authority=dict(r["runtime_authority"]),
            )
            for r in raw_roles
        }
        raw_phases = self._load_json("phases.runtime.json")
        self.phases: dict[str, RuntimePhase] = {
            p["phase_id"]: RuntimePhase(
                phase_id=p["phase_id"],
                slug=p["slug"],
                name=p["name"],
                orchestrator_ids=tuple(p["orchestrator_ids"]),
                gate_id=p["gate_id"],
                output_contract=p["output_contract"],
            )
            for p in raw_phases
        }
        raw_orchestrators = self._load_json("orchestrators.runtime.json")
        self.orchestrators = {o["orchestrator_id"]: o for o in raw_orchestrators}
        self.capability_index: dict[str, list[str]] = self._load_json("capability_index.runtime.json")
        self.authority_registry = self._load_json("authority_registry.runtime.json")
        self.routing_index = self._load_json("routing_index.runtime.json")
        self.state_model = self._load_json("state_model.runtime.json")

    @property
    def registry_hash(self) -> str:
        return str(self.manifest["registry_hash"])

    def get_role(self, role_id: str) -> RuntimeRole:
        try:
            return self.roles[role_id]
        except KeyError as exc:
            raise KeyError(f"unknown role_id: {role_id}") from exc

    def get_phase(self, phase_id: str) -> RuntimePhase:
        try:
            return self.phases[phase_id]
        except KeyError as exc:
            raise KeyError(f"unknown phase_id: {phase_id}") from exc

    def _load_json(self, name: str):
        path = self.root / name
        if not path.exists():
            raise RegistryIntegrityError(f"missing runtime registry file: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _verify_manifest(self) -> None:
        entries = {e["path"]: e for e in self.manifest.get("files", [])}
        for name in self.REQUIRED_FILES:
            entry = entries.get(name)
            if entry is None:
                raise RegistryIntegrityError(f"manifest missing file: {name}")
            path = self.root / name
            if not path.exists():
                raise RegistryIntegrityError(f"runtime file missing: {name}")
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != entry["sha256"]:
                raise RegistryIntegrityError(f"hash mismatch: {name}")
            if len(data) != entry["bytes"]:
                raise RegistryIntegrityError(f"byte count mismatch: {name}")
