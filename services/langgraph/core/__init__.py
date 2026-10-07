"""AMC backend core: constants, errors and config, the Python-native
counterparts of the TypeScript ``@amc/constants``, ``@amc/errors`` and
``@amc/config``/``@amc/logger`` packages (same semantics, no cross-language
imports)."""

from .config import AppConfig, get_logger, load_app_config, load_runtime_config
from .constants import (
    AMC_AGENCY_RUN_STATES,
    AMC_APPROVER_ROLES,
    AMC_AUTH_MODES,
    AMC_DATABASE_BACKENDS,
    AMC_ENVIRONMENTS,
    AMC_LOG_LEVELS,
)
from .errors import (
    AMCError,
    ConflictError,
    ErrorEnvelope,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
    ensure_valid,
    error_envelope,
    register_error_handlers,
)

__all__ = [
    "AMCError",
    "AMC_AGENCY_RUN_STATES",
    "AMC_APPROVER_ROLES",
    "AMC_AUTH_MODES",
    "AMC_DATABASE_BACKENDS",
    "AMC_ENVIRONMENTS",
    "AMC_LOG_LEVELS",
    "AppConfig",
    "ConflictError",
    "ErrorEnvelope",
    "ForbiddenError",
    "NotFoundError",
    "UnauthorizedError",
    "ValidationError",
    "ensure_valid",
    "error_envelope",
    "get_logger",
    "load_app_config",
    "load_runtime_config",
    "register_error_handlers",
]
