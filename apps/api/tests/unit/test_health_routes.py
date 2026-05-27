import pytest
from fastapi import FastAPI
from httpx import AsyncClient


@pytest.mark.unit
async def test_healthz_returns_ok(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "api"


@pytest.mark.unit
async def test_version_includes_service_and_version(client: AsyncClient) -> None:
    resp = await client.get("/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "api"
    assert body["version"] == "0.0.0-test"


@pytest.mark.unit
async def test_readyz_503_when_db_unreachable(client: AsyncClient) -> None:
    """Test settings point at a fake host; /readyz should return 503 + Problem."""
    resp = await client.get("/readyz")
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "astraeus.api.dependency_unavailable"
    assert body["status"] == 503
    assert body["title"]


@pytest.mark.unit
async def test_request_id_header_echoed(client: AsyncClient) -> None:
    resp = await client.get("/healthz", headers={"x-request-id": "test-rid"})
    assert resp.status_code == 200
    assert resp.headers["x-request-id"] == "test-rid"


@pytest.mark.unit
async def test_request_id_generated_when_missing(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.headers.get("x-request-id")
    assert len(resp.headers["x-request-id"]) >= 16


@pytest.mark.unit
async def test_404_returns_problem_details(client: AsyncClient) -> None:
    resp = await client.get("/no-such-route")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "astraeus.http.404"


@pytest.mark.unit
async def test_metrics_endpoint_exposed(client: AsyncClient) -> None:
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


@pytest.mark.unit
def test_create_app_factory_smoke(app: FastAPI) -> None:
    assert app.title == "Astraeus API"
    routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
    assert "/healthz" in routes
    assert "/readyz" in routes
    assert "/version" in routes
