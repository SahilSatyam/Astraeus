"""Structlog processors used across services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

if TYPE_CHECKING:
    import structlog


class Redactor:
    """Structlog processor that scrubs known-sensitive keys.

    Loggers must never log secrets, but defense-in-depth requires that the
    pipeline itself catch slips. Any key matching one of the configured
    substrings is replaced with ``"***REDACTED***"`` (case-insensitive).
    """

    DEFAULT_KEYS: ClassVar[frozenset[str]] = frozenset(
        {"password", "passwd", "secret", "token", "api_key", "apikey", "authorization"}
    )

    def __init__(self, *, keys: frozenset[str] | None = None) -> None:
        self._keys = keys or self.DEFAULT_KEYS

    def __call__(
        self,
        _logger: Any,
        _name: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        return cast("structlog.types.EventDict", _redact(event_dict, self._keys))


def _redact(value: Any, keys: frozenset[str]) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and any(key in k.lower() for key in keys):
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v, keys)
        return out
    if isinstance(value, list):
        return [_redact(item, keys) for item in value]
    return value
