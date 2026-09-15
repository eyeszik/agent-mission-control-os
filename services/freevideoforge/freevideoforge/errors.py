"""Typed error hierarchy.

Every failure the pipeline can raise on purpose is one of these, so callers can
distinguish "the environment is missing something" from "the brief was invalid"
from "a provider produced unusable media".
"""

from __future__ import annotations


class ForgeError(Exception):
    """Base class for every deliberate FreeVideoForge failure."""

    #: Short machine-readable class used for retry/repair routing.
    failure_class = "generic"


class ConfigError(ForgeError):
    """The request or configuration is invalid and cannot be repaired."""

    failure_class = "config"


class DependencyError(ForgeError):
    """A required local binary or library is missing."""

    failure_class = "dependency"


class ProviderUnavailable(ForgeError):
    """A provider was asked for but cannot run on this host."""

    failure_class = "provider_unavailable"


class PaidProviderRejected(ForgeError):
    """A provider that would require paid credentials was requested in free mode."""

    failure_class = "paid_provider_rejected"


class RenderError(ForgeError):
    """Media composition failed."""

    failure_class = "render"


class QualityGateError(ForgeError):
    """A mandatory structural quality gate failed."""

    failure_class = "quality"


class ResourceError(ForgeError):
    """The requested job exceeds the governor's resource budget."""

    failure_class = "resource"


class StateError(ForgeError):
    """The persisted job state is missing or inconsistent."""

    failure_class = "state"
