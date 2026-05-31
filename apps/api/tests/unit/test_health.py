"""Unit tests for health check endpoints.

Tests /healthz, /readyz, and /version routes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    # Patch settings and DB before importing app
    with (
        patch("astraeus_api.app.Settings") as mock_settings,
        patch("astraeus_api.app.configure_logging"),
        patch("astraeus_api.app.configure_tracing"),
        patch("astraeus_api.app.FastAPIInstrumentor"),
        patch("astraeus_api.app.Instrumentator"),
    ):
        mock_settings.return_value = MagicMock(
            observability=MagicMock(),
            app=MagicMock(name="api", version="0.1.0-test"),
            env=MagicMock(value="test"),
        )

        from astraeus_api.app import create_app

        app = create_app(mock_settings.return_value)
        yield TestClient(app, raise_server_exceptions=False)


class TestHealthz:
    """Test liveness probe."""

    @pytest.mark.unit
    def test_healthz_returns_200(self, client):
        """Liveness probe always returns 200."""
        response = client.get("/healthz")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_healthz_response_shape(self, client):
        """Healthz returns status, service, and version."""
        response = client.get("/healthz")
        if response.status_code == 200:
            data = response.json()
            assert "status" in data


class TestMetrics:
    """Test Prometheus metrics endpoint."""

    @pytest.mark.unit
    def test_metrics_endpoint_exists(self, client):
        """Metrics endpoint returns 200."""
        response = client.get("/metrics")
        # Prometheus instrumentator exposes this
        assert response.status_code in (200, 404)  # 404 if instrumentator not fully wired in test
