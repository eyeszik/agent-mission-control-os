"""Typed AMC errors and the JSON error envelope (mirrors ``@amc/errors``).

``AMCError`` subclasses FastAPI's ``HTTPException``: raising one from a route
works with or without the envelope handler, and existing clients that read
``detail`` keep working. With ``register_error_handlers(app)`` the response
body becomes::

    {"detail": message, "error": {"code", "message", "status", "details"?}}
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, TypedDict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


class ErrorBody(TypedDict, total=False):
    code: str
    message: str
    status: int
    details: dict[str, Any]


class ErrorEnvelope(TypedDict):
    detail: str
    error: ErrorBody


class AMCError(HTTPException):
    default_code = "AMC_ERROR"
    default_status = 500
    default_message = "Internal error"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        code: Optional[str] = None,
        status: Optional[int] = None,
        details: Optional[Mapping[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.details = dict(details) if details is not None else None
        super().__init__(status_code=status or self.default_status, detail=self.message, headers=headers)

    @property
    def status(self) -> int:
        return self.status_code

    def to_envelope(self) -> ErrorEnvelope:
        body: ErrorBody = {"code": self.code, "message": self.message, "status": self.status_code}
        if self.details is not None:
            body["details"] = self.details
        return {"detail": self.message, "error": body}

    def __str__(self) -> str:
        return self.message


class ValidationError(AMCError):
    default_code, default_status, default_message = "VALIDATION_FAILED", 422, "Validation failed"


class UnauthorizedError(AMCError):
    default_code, default_status, default_message = "UNAUTHORIZED", 401, "Authentication required"


class ForbiddenError(AMCError):
    default_code, default_status, default_message = "FORBIDDEN", 403, "Forbidden"


class NotFoundError(AMCError):
    default_code, default_status, default_message = "NOT_FOUND", 404, "Not found"


class ConflictError(AMCError):
    default_code, default_status, default_message = "CONFLICT", 409, "Conflict"


def is_amc_error(value: object) -> bool:
    return isinstance(value, AMCError)


def ensure_valid(condition: object, message: str, **details: Any) -> None:
    """Raise ``ValidationError`` unless ``condition`` holds."""
    if not condition:
        raise ValidationError(message, details=details or None)


def error_envelope(error: BaseException) -> ErrorEnvelope:
    """Envelope for any exception; non-AMC errors become a generic 500 so an
    internal message never leaks to a client."""
    if isinstance(error, AMCError):
        return error.to_envelope()
    return AMCError().to_envelope()


async def _amc_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AMCError)
    return JSONResponse(status_code=exc.status_code, content=exc.to_envelope(), headers=exc.headers)


def register_error_handlers(app: FastAPI) -> None:
    """Render ``AMCError`` (and subclasses) as the AMC envelope. Plain
    ``HTTPException`` keeps FastAPI's default ``{"detail": ...}`` body."""
    app.add_exception_handler(AMCError, _amc_error_handler)


__all__ = [
    "AMCError",
    "ConflictError",
    "ErrorBody",
    "ErrorEnvelope",
    "ForbiddenError",
    "NotFoundError",
    "UnauthorizedError",
    "ValidationError",
    "ensure_valid",
    "error_envelope",
    "is_amc_error",
    "register_error_handlers",
]
