"""Base exception used across every Astraeus service.

Every exception that crosses a service boundary inherits from `AstraeusError`.
Error codes are namespaced (`astraeus.<domain>.<short_name>`) and stable across
versions; messages are not.
"""

from __future__ import annotations

from typing import Any


class AstraeusError(Exception):
    """Base error for all Astraeus services.

    Attributes:
        code: Stable, namespaced error code (e.g. ``astraeus.api.not_found``).
        status: HTTP status code to surface for this error.
        detail: Human-readable detail. May be displayed to clients.
        extra: Optional structured context, included in logs and Problem Details.
    """

    code: str = "astraeus.unknown"
    status: int = 500

    def __init__(
        self,
        detail: str,
        *,
        code: str | None = None,
        status: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status
        self.extra: dict[str, Any] = extra or {}

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"code={self.code!r}, status={self.status}, detail={self.detail!r})"
        )


class NotFoundError(AstraeusError):
    code = "astraeus.common.not_found"
    status = 404


class ValidationError(AstraeusError):
    code = "astraeus.common.validation_failed"
    status = 422


class ConflictError(AstraeusError):
    code = "astraeus.common.conflict"
    status = 409


class DependencyUnavailableError(AstraeusError):
    code = "astraeus.common.dependency_unavailable"
    status = 503
