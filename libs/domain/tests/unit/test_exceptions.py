import pytest
from astraeus_domain.exceptions import (
    AstraeusError,
    ConflictError,
    DependencyUnavailableError,
    NotFoundError,
    ValidationError,
)


@pytest.mark.unit
def test_astraeus_error_defaults() -> None:
    err = AstraeusError("boom")
    assert err.code == "astraeus.unknown"
    assert err.status == 500
    assert err.detail == "boom"
    assert err.extra == {}


@pytest.mark.unit
def test_astraeus_error_overrides() -> None:
    err = AstraeusError(
        "missing field",
        code="astraeus.api.bad_request",
        status=400,
        extra={"field": "symbol"},
    )
    assert err.code == "astraeus.api.bad_request"
    assert err.status == 400
    assert err.extra == {"field": "symbol"}
    assert "astraeus.api.bad_request" in repr(err)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cls", "expected_code", "expected_status"),
    [
        (NotFoundError, "astraeus.common.not_found", 404),
        (ValidationError, "astraeus.common.validation_failed", 422),
        (ConflictError, "astraeus.common.conflict", 409),
        (DependencyUnavailableError, "astraeus.common.dependency_unavailable", 503),
    ],
)
def test_subclass_codes_stable(
    cls: type[AstraeusError], expected_code: str, expected_status: int
) -> None:
    err = cls("x")
    assert err.code == expected_code
    assert err.status == expected_status
    assert isinstance(err, AstraeusError)
