"""SQLAlchemy declarative base.

Phase 0 ships a minimal ``Base`` and a single ``system_health`` model. Later
phases extend ``Base.metadata`` with their own tables; alembic autogenerate
imports this module to discover them.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Project-wide declarative base. Every ORM model inherits from this."""


class SystemHealth(Base):
    """Marker row used by the ``/readyz`` probe.

    Migrations seed exactly one row; ``/readyz`` does ``SELECT 1`` against this
    table to confirm DB connectivity. Keeping a real table (rather than just
    ``SELECT 1``) ensures the migration loop itself is exercised on every
    cold-start.
    """

    __tablename__ = "system_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
