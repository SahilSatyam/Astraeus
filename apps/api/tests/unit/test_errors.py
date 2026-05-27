import pytest
from astraeus_domain import AstraeusError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.mark.unit
async def test_astraeus_error_renders_problem_details(app: FastAPI) -> None:
    @app.get("/_test/raise-astraeus")
    async def _raise() -> None:
        raise AstraeusError(
            "thing missing",
            code="astraeus.api.test_thing_missing",
            status=418,
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/_test/raise-astraeus")

    assert resp.status_code == 418
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "astraeus.api.test_thing_missing"
    assert body["status"] == 418
    assert body["detail"] == "thing missing"
    assert body["type"].endswith("astraeus.api.test_thing_missing")


@pytest.mark.unit
async def test_unhandled_exception_renders_500_problem(app: FastAPI) -> None:
    @app.get("/_test/boom")
    async def _boom() -> None:
        raise RuntimeError("kaboom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/_test/boom")

    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "astraeus.internal"
    assert body["status"] == 500
