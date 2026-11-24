"""FRRE fail-closed policy constants (W1, pure).

These are literals, not configuration: nothing reads them from the environment, so a
repair actor cannot widen them at runtime. Changing any of them is a protected-control
change that needs independent review (docs/frre/FRRE-v15-spec.md, sections 3 and 14).
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Final

FRRE_POLICY_VERSION: Final = "amc-frre-policy/v1"

# Effects FRRE may never take on its own, at any wave.
AUTO_MERGE: Final = False
AUTO_PROMOTION: Final = False
SELF_APPROVAL: Final = False
POLICY_SELF_MUTATION: Final = False
PRODUCTION_WRITE: Final = False
# W1 ships no enabled capability. Activation is a separate, owner-approved wave (W8).
ENABLED_BY_DEFAULT: Final = False
# The only external effect FRRE will ever have (a draft PR) is delivered in W6, behind its own
# mode gate. Until then the guard refuses every move into RELEASED, even with a valid permit.
DELIVERY_ENABLED: Final = False

DEFAULT_MAX_ATTEMPTS: Final = 3
DEFAULT_MAX_RECOVERIES: Final = 3
CONCURRENCY_PER_WORKSPACE: Final = 1

# Paths no repair plan may ever list as writable: validators, integrity pins, CI, security,
# the governance kernel, migrations, escrowed acceptance fixtures and FRRE's own policy and
# guards. A plan that overlaps any of them is refused before it can be authorized.
PROTECTED_FLOOR: Final[tuple[str, ...]] = (
    "scripts/verify_*",
    "manifest.json",
    ".github/*",
    "services/langgraph/security/*",
    "services/langgraph/agency/kernel/*",
    "supabase/migrations/*",
    "*/tests/fixtures/*",
    "services/langgraph/agency/frre/policy.py",
    "services/langgraph/agency/frre/guards.py",
)


def is_protected(path: str) -> bool:
    """True when ``path`` (repo-relative POSIX) falls under the protected floor.

    ``fnmatchcase`` lets ``*`` cross ``/``, so ``.github/*`` covers the whole tree. A path
    that tries to escape with ``..`` or is absolute is treated as protected: it is never
    a legitimate repair target.
    """
    if path.startswith("/") or ".." in path.split("/") or "\\" in path:
        return True
    return any(fnmatchcase(path, pattern) for pattern in PROTECTED_FLOOR)


__all__ = [
    "AUTO_MERGE", "AUTO_PROMOTION", "CONCURRENCY_PER_WORKSPACE", "DEFAULT_MAX_ATTEMPTS", "DELIVERY_ENABLED",
    "DEFAULT_MAX_RECOVERIES", "ENABLED_BY_DEFAULT", "FRRE_POLICY_VERSION", "POLICY_SELF_MUTATION",
    "PRODUCTION_WRITE", "PROTECTED_FLOOR", "SELF_APPROVAL", "is_protected",
]
