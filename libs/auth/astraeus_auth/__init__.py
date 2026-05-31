"""Astraeus authentication and authorization library.

Provides JWT validation, Principal model, and role-based access control
for all backend services. Designed for single-user scope mode with
scaffolding for multi-user OIDC in the future.
"""

from astraeus_auth.config import AuthSettings
from astraeus_auth.dependencies import (
    get_current_user,
    require_role,
    require_trading_permission,
)
from astraeus_auth.models import Principal, Role
from astraeus_auth.tokens import create_service_token, decode_token

__all__ = [
    "AuthSettings",
    "Principal",
    "Role",
    "create_service_token",
    "decode_token",
    "get_current_user",
    "require_role",
    "require_trading_permission",
]
