from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os

from services.langgraph.agency.reliability import ProductionTrustKernel
from services.langgraph.agency.role_os import RoleOSRegistry
from services.langgraph.app.in_memory_queue import BoundedInMemoryQueue
from services.langgraph.persistence.trust_kernel import DatabaseReliabilityStore


@lru_cache(maxsize=1)
def runtime_queue() -> BoundedInMemoryQueue[dict]:
    maxsize = int((os.environ.get("AMC_MVP_QUEUE_MAXSIZE") or "128").strip())
    return BoundedInMemoryQueue(maxsize=maxsize)


@lru_cache(maxsize=1)
def role_os_registry() -> RoleOSRegistry:
    runtime_root = Path(__file__).resolve().parents[3] / "runtime" / "role_os"
    return RoleOSRegistry(runtime_root)


@lru_cache(maxsize=1)
def trust_kernel() -> ProductionTrustKernel:
    return ProductionTrustKernel(DatabaseReliabilityStore())
