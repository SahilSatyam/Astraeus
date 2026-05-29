"""MLflow experiment tracking wrapper.

Provides a standardized entrypoint for logging experiments that automatically
attaches lineage hashes, git commit, universe snapshot, and feature definition
hashes for full reproducibility.

Usage:
    from astraeus_features.tracking import run_experiment

    with run_experiment("factor_analysis", params={...}) as run:
        # ... compute metrics ...
        run.log_metric("sharpe", 1.42)
        run.log_metric("max_dd", -0.15)
        run.log_artifact("pnl.parquet")
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Generator

import structlog

logger = structlog.get_logger("astraeus.features.tracking")


def _get_git_commit() -> str | None:
    """Get current git commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S603, S607
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _compute_universe_hash(members: list[str]) -> str:
    """Compute a deterministic hash of universe membership."""
    canonical = ",".join(sorted(members))
    return hashlib.sha256(canonical.encode()).hexdigest()


class ExperimentRun:
    """Wrapper around an MLflow run with Astraeus-specific conventions."""

    def __init__(self, run: Any) -> None:
        self._run = run
        self._mlflow: Any = None

    @property
    def run_id(self) -> str:
        return self._run.info.run_id

    def log_param(self, key: str, value: Any) -> None:
        """Log a parameter."""
        if self._mlflow:
            self._mlflow.log_param(key, value)

    def log_params(self, params: dict[str, Any]) -> None:
        """Log multiple parameters."""
        if self._mlflow:
            self._mlflow.log_params(params)

    def log_metric(self, key: str, value: float, step: int | None = None) -> None:
        """Log a metric."""
        if self._mlflow:
            self._mlflow.log_metric(key, value, step=step)

    def log_metrics(self, metrics: dict[str, float], step: int | None = None) -> None:
        """Log multiple metrics."""
        if self._mlflow:
            self._mlflow.log_metrics(metrics, step=step)

    def log_artifact(self, local_path: str, artifact_path: str | None = None) -> None:
        """Log an artifact file."""
        if self._mlflow:
            self._mlflow.log_artifact(local_path, artifact_path)

    def set_tag(self, key: str, value: str) -> None:
        """Set a tag on the run."""
        if self._mlflow:
            self._mlflow.set_tag(key, value)


@contextmanager
def run_experiment(
    experiment_name: str,
    params: dict[str, Any] | None = None,
    feature_hash_map: dict[str, str] | None = None,
    universe_members: list[str] | None = None,
    tags: dict[str, str] | None = None,
) -> Generator[ExperimentRun, None, None]:
    """Context manager for a tracked experiment run.

    Automatically attaches:
    - git_commit: current HEAD SHA
    - data_lineage_hash: hash of feature definitions used
    - universe_snapshot_hash: hash of universe membership
    - run_timestamp: when the run started

    Args:
        experiment_name: MLflow experiment name.
        params: Parameters to log.
        feature_hash_map: {feature_name: definition_hash} for reproducibility.
        universe_members: List of symbols in the universe (for snapshot hash).
        tags: Additional tags.

    Yields:
        ExperimentRun wrapper for logging metrics/artifacts.
    """
    try:
        import mlflow  # noqa: PLC0415

        mlflow.set_experiment(experiment_name)

        with mlflow.start_run() as run:
            wrapper = ExperimentRun(run)
            wrapper._mlflow = mlflow

            # Auto-attach standard tags
            git_commit = _get_git_commit()
            if git_commit:
                mlflow.set_tag("git_commit", git_commit)

            mlflow.set_tag("run_timestamp", datetime.now(tz=UTC).isoformat())

            if feature_hash_map:
                lineage_hash = hashlib.sha256(
                    str(sorted(feature_hash_map.items())).encode()
                ).hexdigest()
                mlflow.set_tag("data_lineage_hash", lineage_hash)
                mlflow.log_params(
                    {f"feature_hash.{k}": v[:12] for k, v in feature_hash_map.items()}
                )

            if universe_members:
                universe_hash = _compute_universe_hash(universe_members)
                mlflow.set_tag("universe_snapshot_hash", universe_hash)
                mlflow.log_param("universe_size", len(universe_members))

            if tags:
                for k, v in tags.items():
                    mlflow.set_tag(k, v)

            if params:
                mlflow.log_params(params)

            yield wrapper

    except ImportError:
        logger.warning(
            "mlflow_not_installed",
            msg="MLflow not available. Experiment tracking disabled.",
        )
        # Yield a no-op wrapper
        wrapper = ExperimentRun(type("FakeRun", (), {"info": type("Info", (), {"run_id": "local"})()})())
        yield wrapper
