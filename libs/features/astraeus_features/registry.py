"""Feature registry — manages feature definitions in the catalog.

Handles registration, lookup, and validation of feature definitions.
The registry is the source of truth for what features exist and their
current definition hashes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select, text

from astraeus_features.dsl import FeatureDefinition
from astraeus_features.models import FeatureRegistry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("astraeus.features.registry")


async def register(
    session: AsyncSession,
    feature_def: FeatureDefinition,
    code_commit: str | None = None,
    create_table: bool = True,
) -> FeatureRegistry:
    """Register a feature definition in the catalog.

    If the feature already exists with the same definition_hash, this is a no-op.
    If the hash differs, the registry entry is updated (triggering a backfill).

    Args:
        session: Database session.
        feature_def: The feature definition to register.
        code_commit: Git commit SHA for traceability.
        create_table: If True, creates the feature hypertable if it doesn't exist.

    Returns:
        The FeatureRegistry row.
    """
    # Check if already registered
    existing = await session.execute(
        select(FeatureRegistry).where(FeatureRegistry.name == feature_def.name)
    )
    row = existing.scalar_one_or_none()

    if row is not None:
        if row.definition_hash == feature_def.definition_hash:
            logger.debug("feature_already_registered", name=feature_def.name)
            return row

        # Definition changed — update
        logger.info(
            "feature_definition_changed",
            name=feature_def.name,
            old_hash=row.definition_hash[:12],
            new_hash=feature_def.definition_hash[:12],
        )
        row.definition_hash = feature_def.definition_hash
        row.transform_sql = feature_def.transform
        row.dependencies = {"deps": feature_def.dependencies}
        row.freshness_sla_seconds = feature_def.freshness_sla_seconds
        row.knowledge_lag_seconds = feature_def.knowledge_lag_seconds
        row.owner = feature_def.owner
        row.tags = {"tags": feature_def.tags}
        row.code_commit = code_commit
        row.updated_at = datetime.now(tz=UTC)
    else:
        # New registration
        row = FeatureRegistry(
            name=feature_def.name,
            group=feature_def.group,
            entity=feature_def.entity.value,
            dtype=feature_def.dtype,
            description=feature_def.description,
            dependencies={"deps": feature_def.dependencies},
            transform_sql=feature_def.transform,
            definition_hash=feature_def.definition_hash,
            materialization=feature_def.materialization.value,
            freshness_sla_seconds=feature_def.freshness_sla_seconds,
            knowledge_lag_seconds=feature_def.knowledge_lag_seconds,
            owner=feature_def.owner,
            tags={"tags": feature_def.tags},
            table_name=feature_def.table_name,
            code_commit=code_commit,
        )
        session.add(row)

        logger.info(
            "feature_registered",
            name=feature_def.name,
            group=feature_def.group,
            hash=feature_def.definition_hash[:12],
            table=feature_def.table_name,
        )

    # Create the storage table if requested
    if create_table:
        await session.execute(text(feature_def.create_table_sql()))
        await session.execute(text(feature_def.pit_view_sql()))

    await session.flush()
    return row


async def get_definition(
    session: AsyncSession,
    feature_name: str,
) -> FeatureRegistry | None:
    """Look up a feature definition by name."""
    result = await session.execute(
        select(FeatureRegistry).where(FeatureRegistry.name == feature_name)
    )
    return result.scalar_one_or_none()


async def list_features(
    session: AsyncSession,
    group: str | None = None,
    owner: str | None = None,
) -> list[FeatureRegistry]:
    """List registered features, optionally filtered by group or owner."""
    query = select(FeatureRegistry).order_by(FeatureRegistry.group, FeatureRegistry.name)

    if group:
        query = query.where(FeatureRegistry.group == group)
    if owner:
        query = query.where(FeatureRegistry.owner == owner)

    result = await session.execute(query)
    return list(result.scalars().all())


async def get_table_name(
    session: AsyncSession,
    feature_name: str,
) -> str | None:
    """Resolve a feature name to its storage table name."""
    result = await session.execute(
        select(FeatureRegistry.table_name).where(FeatureRegistry.name == feature_name)
    )
    return result.scalar_one_or_none()
