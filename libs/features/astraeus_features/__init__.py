"""Astraeus feature store — PIT-correct retrieval, DSL, and backfill engine."""

from astraeus_features.backfill import backfill_feature
from astraeus_features.dsl import Entity, FeatureDefinition, MaterializationMode, sql_transform
from astraeus_features.models import FeatureRegistry, MaterializationRun
from astraeus_features.registry import get_definition, list_features, register
from astraeus_features.retrieval import (
    MaterializationRequired,
    PITRetrievalError,
    get,
    get_panel,
    pit_latest,
)

__all__ = [
    "Entity",
    "FeatureDefinition",
    "FeatureRegistry",
    "MaterializationMode",
    "MaterializationRequired",
    "MaterializationRun",
    "PITRetrievalError",
    "backfill_feature",
    "get",
    "get_definition",
    "get_panel",
    "list_features",
    "pit_latest",
    "register",
    "sql_transform",
]
