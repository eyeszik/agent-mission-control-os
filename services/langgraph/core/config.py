"""Application config view and logging (mirrors ``@amc/config`` / ``@amc/logger``).

``app.config.load_runtime_config`` stays the single owner of runtime
configuration semantics and the production gates; it is re-exported here and
``AppConfig`` is a small typed view over it plus the settings that live
elsewhere (approver roles, log level). ``app.config`` is imported lazily
because it imports ``core.constants``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .constants import AMC_LOG_LEVELS, ENV_PRODUCTION

if TYPE_CHECKING:  # pragma: no cover
    from services.langgraph.app.config import RuntimeConfig

_PY_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}
DEFAULT_LOG_LEVEL = "info"


@dataclass(frozen=True)
class AppConfig:
    environment: str
    auth_mode: str
    database_backend: str
    log_level: str
    approver_roles: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def is_production(self) -> bool:
        return self.environment == ENV_PRODUCTION

    @property
    def valid(self) -> bool:
        return not self.errors


def load_runtime_config() -> "RuntimeConfig":
    from services.langgraph.app.config import load_runtime_config as _load

    return _load()


def parse_log_level(value: object, default: str = DEFAULT_LOG_LEVEL) -> str:
    text = str(value or "").strip().lower()
    if text == "warning":
        text = "warn"
    return text if text in AMC_LOG_LEVELS else default


def configured_log_level() -> str | None:
    """AMC_LOG_LEVEL when set to a known level, else None (leave logging alone)."""
    raw = (os.environ.get("AMC_LOG_LEVEL") or "").strip()
    if not raw:
        return None
    level = parse_log_level(raw, default="")
    return level or None


def load_app_config() -> AppConfig:
    from services.langgraph.security.approval_authority import approver_roles

    runtime = load_runtime_config()
    return AppConfig(
        environment=runtime.environment,
        auth_mode=runtime.auth.mode,
        database_backend=runtime.database.backend,
        log_level=configured_log_level() or DEFAULT_LOG_LEVEL,
        approver_roles=tuple(sorted(approver_roles())),
        errors=tuple(runtime.errors),
    )


def get_logger(name: str) -> logging.Logger:
    """``logging.getLogger(name)``, set to AMC_LOG_LEVEL when that is configured.

    Without AMC_LOG_LEVEL the logger is returned untouched, so the host's
    logging configuration (uvicorn, pytest) behaves exactly as before.
    """
    logger = logging.getLogger(name)
    level = configured_log_level()
    if level is not None:
        logger.setLevel(_PY_LEVELS[level])
    return logger


__all__ = [
    "AppConfig",
    "DEFAULT_LOG_LEVEL",
    "configured_log_level",
    "get_logger",
    "load_app_config",
    "load_runtime_config",
    "parse_log_level",
]
