"""Unit tests for health check endpoints.

Tests /healthz, /readyz, and /version routes.
"""

from __future__ import annotations

import pytest


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
        data = response.json()
        assert data["status"] == "ok"
        assert "service" in data
        assert "version" in data


class TestMetrics:
    """Test Prometheus metrics endpoint."""

    @pytest.mark.unit
    def test_metrics_endpoint_exists(self, client):
        """Metrics endpoint returns 200."""
        response = client.get("/metrics")
        assert response.status_code == 200
