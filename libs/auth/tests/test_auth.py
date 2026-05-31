"""Tests for the astraeus_auth library."""

from __future__ import annotations

import pytest
from astraeus_auth.config import AuthSettings
from astraeus_auth.models import Principal, Role
from astraeus_auth.tokens import (
    TokenError,
    create_access_token,
    create_service_token,
    decode_token,
    token_to_principal,
)


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings(jwt_secret="test-secret-key-for-testing")


class TestPrincipal:
    def test_operator_can_trade(self):
        p = Principal.from_role("user1", Role.OPERATOR)
        assert p.can_trade()
        assert p.can_arm_kill_switch()

    def test_analyst_cannot_trade(self):
        p = Principal.from_role("user2", Role.ANALYST)
        assert not p.can_trade()
        assert not p.can_arm_kill_switch()

    def test_viewer_has_minimal_permissions(self):
        p = Principal.from_role("user3", Role.VIEWER)
        assert not p.can_trade()
        assert not p.can_arm_kill_switch()
        assert p.has_permission("read:market_data")

    def test_service_can_do_everything(self):
        p = Principal.from_role("recon-worker", Role.SERVICE)
        assert p.can_trade()
        assert p.can_arm_kill_switch()
        assert p.has_permission("admin:all")


class TestTokens:
    def test_create_and_decode_access_token(self, auth_settings: AuthSettings):
        token = create_access_token("operator", Role.OPERATOR, auth_settings)
        payload = decode_token(token, auth_settings)
        assert payload["sub"] == "operator"
        assert payload["role"] == "operator"
        assert payload["type"] == "access"

    def test_create_and_decode_service_token(self, auth_settings: AuthSettings):
        token = create_service_token("recon-worker", auth_settings)
        payload = decode_token(token, auth_settings)
        assert payload["sub"] == "recon-worker"
        assert payload["role"] == "service"
        assert payload["type"] == "service"

    def test_invalid_token_raises(self, auth_settings: AuthSettings):
        with pytest.raises(TokenError, match="Invalid token"):
            decode_token("not-a-valid-jwt", auth_settings)

    def test_wrong_secret_raises(self, auth_settings: AuthSettings):
        token = create_access_token("user", Role.OPERATOR, auth_settings)
        wrong_settings = AuthSettings(jwt_secret="wrong-secret")
        with pytest.raises(TokenError, match="Invalid token"):
            decode_token(token, wrong_settings)

    def test_token_to_principal(self, auth_settings: AuthSettings):
        token = create_access_token("sahil", Role.OPERATOR, auth_settings)
        payload = decode_token(token, auth_settings)
        principal = token_to_principal(payload)
        assert principal.subject == "sahil"
        assert principal.role == Role.OPERATOR
        assert principal.can_trade()

    def test_unknown_role_defaults_to_viewer(self):
        payload = {"sub": "unknown", "role": "superadmin"}
        principal = token_to_principal(payload)
        assert principal.role == Role.VIEWER
        assert not principal.can_trade()


class TestAuthSettings:
    def test_defaults(self):
        settings = AuthSettings()
        assert settings.jwt_algorithm == "HS256"
        assert settings.enabled is True
        assert "/health" in settings.public_paths
        assert "/metrics" in settings.public_paths
