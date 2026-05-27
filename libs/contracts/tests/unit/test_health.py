import pytest
from astraeus_contracts import (
    HealthResponse,
    ProblemDetails,
    ReadinessCheck,
    ReadinessResponse,
    VersionResponse,
)
from pydantic import ValidationError


@pytest.mark.unit
def test_health_response_defaults_status_ok() -> None:
    resp = HealthResponse(service="api", version="0.1.0")
    assert resp.status == "ok"
    assert resp.model_dump()["service"] == "api"


@pytest.mark.unit
def test_health_response_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({"service": "api", "version": "0.1.0", "rogue": True})


@pytest.mark.unit
def test_readiness_response_aggregates_checks() -> None:
    resp = ReadinessResponse(
        status="degraded",
        service="api",
        checks=[
            ReadinessCheck(name="postgres", healthy=True),
            ReadinessCheck(name="redis", healthy=False, detail="connection refused"),
        ],
    )
    assert resp.checks[1].detail == "connection refused"


@pytest.mark.unit
def test_version_response_optional_fields() -> None:
    resp = VersionResponse(service="api", version="0.1.0")
    assert resp.git_sha is None
    assert resp.build_time is None


@pytest.mark.unit
def test_problem_details_minimum() -> None:
    p = ProblemDetails(title="Not Found", status=404, code="astraeus.common.not_found")
    assert p.type == "about:blank"
    assert p.code == "astraeus.common.not_found"


@pytest.mark.unit
def test_problem_details_status_bounds() -> None:
    with pytest.raises(ValidationError):
        ProblemDetails(title="x", status=999, code="astraeus.x")
