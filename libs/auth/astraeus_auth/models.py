"""Authentication models — Principal, Role, and permissions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    """User roles with increasing privilege levels."""

    VIEWER = "viewer"
    ANALYST = "analyst"
    OPERATOR = "operator"
    SERVICE = "service"  # Internal service-to-service


# Permission matrix — what each role can do
ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.VIEWER: {
        "read:positions",
        "read:orders",
        "read:market_data",
        "read:features",
    },
    Role.ANALYST: {
        "read:positions",
        "read:orders",
        "read:market_data",
        "read:features",
        "read:pnl",
        "write:recommendations",
        "write:agents",
        "approve:recommendations",
    },
    Role.OPERATOR: {
        "read:positions",
        "read:orders",
        "read:market_data",
        "read:features",
        "read:pnl",
        "write:recommendations",
        "write:agents",
        "approve:recommendations",
        "write:orders",
        "write:kill_switch",
        "write:strategies",
        "admin:all",
    },
    Role.SERVICE: {
        # Service accounts can do everything — they're internal
        "read:positions",
        "read:orders",
        "read:market_data",
        "read:features",
        "read:pnl",
        "write:recommendations",
        "write:agents",
        "approve:recommendations",
        "write:orders",
        "write:kill_switch",
        "write:strategies",
        "admin:all",
    },
}


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated principal extracted from a validated JWT.

    Every request handler receives this via dependency injection.
    The subject identifies WHO, the role determines WHAT they can do.
    """

    subject: str  # User ID or service name
    role: Role
    permissions: frozenset[str]

    def has_permission(self, permission: str) -> bool:
        """Check if this principal has a specific permission."""
        return permission in self.permissions or "admin:all" in self.permissions

    def can_trade(self) -> bool:
        """Shorthand: can this principal submit/cancel orders?"""
        return self.has_permission("write:orders")

    def can_arm_kill_switch(self) -> bool:
        """Shorthand: can this principal arm/disarm the kill switch?"""
        return self.has_permission("write:kill_switch")

    @classmethod
    def from_role(cls, subject: str, role: Role) -> Principal:
        """Create a Principal with the standard permission set for a role."""
        permissions = ROLE_PERMISSIONS.get(role, set())
        return cls(subject=subject, role=role, permissions=frozenset(permissions))
