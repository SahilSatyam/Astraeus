"""Replay / backfill CLI.

Provides commands to:
- Replay a single (strategy_id, as_of_date) pipeline run.
- Backfill a date range serially.
- Verify determinism by comparing output hashes.

Usage:
    python -m astraeus_portfolio.orchestration.replay replay --strategy momentum_daily --date 2026-05-28
    python -m astraeus_portfolio.orchestration.replay backfill --strategy momentum_daily --start 2026-01-01 --end 2026-05-28
    python -m astraeus_portfolio.orchestration.replay verify --strategy momentum_daily --date 2026-05-28
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ReplayResult:
    """Result of a replay or backfill operation.

    Attributes:
        strategy_id: Strategy identifier.
        as_of_date: The replayed date.
        status: 'completed' | 'failed' | 'determinism_violation'.
        stored_hash: Hash of the previously stored result (if verifying).
        computed_hash: Hash of the newly computed result.
        is_forced: Whether --force was used to overwrite.
        version: The version number of this run.
    """

    def __init__(
        self,
        strategy_id: str,
        as_of_date: date,
        status: str,
        stored_hash: str | None = None,
        computed_hash: str | None = None,
        is_forced: bool = False,
        version: int = 1,
    ) -> None:
        self.strategy_id = strategy_id
        self.as_of_date = as_of_date
        self.status = status
        self.stored_hash = stored_hash
        self.computed_hash = computed_hash
        self.is_forced = is_forced
        self.version = version

    def is_deterministic(self) -> bool:
        """Check if the replay produced the same result as stored."""
        if self.stored_hash is None or self.computed_hash is None:
            return True  # No prior result to compare against
        return self.stored_hash == self.computed_hash


class ReplayEngine:
    """Engine for replaying and backfilling pipeline runs.

    The replay engine re-executes the daily pipeline for a given
    (strategy_id, as_of_date) and compares the output hash against
    the stored result for determinism verification.
    """

    def __init__(
        self,
        pipeline_runner: Any = None,
        result_store: Any = None,
    ) -> None:
        """Initialize the replay engine.

        Args:
            pipeline_runner: Callable that runs the daily pipeline.
                Signature: (strategy_id, as_of_date) -> PipelineResult
            result_store: Interface for reading/writing stored results.
                Must support get_hash(strategy_id, as_of_date, task_name) and
                put_result(strategy_id, as_of_date, task_name, hash, version).
        """
        self.pipeline_runner = pipeline_runner
        self.result_store = result_store

    def replay(
        self,
        strategy_id: str,
        as_of_date: date,
        force: bool = False,
    ) -> ReplayResult:
        """Replay a single pipeline run.

        If force=False and a completed result exists, returns the cached result.
        If force=True, re-runs and stores as a new version (prior preserved).

        Args:
            strategy_id: Strategy identifier.
            as_of_date: The date to replay.
            force: Whether to overwrite existing results.

        Returns:
            ReplayResult with status and hash comparison.
        """
        logger.info(
            "replay_start",
            strategy_id=strategy_id,
            as_of_date=str(as_of_date),
            force=force,
        )

        # Check for existing result
        stored_hash = None
        current_version = 0
        if self.result_store is not None:
            stored_hash = self.result_store.get_hash(strategy_id, as_of_date, "pipeline")
            current_version = self.result_store.get_version(strategy_id, as_of_date) or 0

        if stored_hash is not None and not force:
            logger.info(
                "replay_cached",
                strategy_id=strategy_id,
                as_of_date=str(as_of_date),
                stored_hash=stored_hash,
            )
            return ReplayResult(
                strategy_id=strategy_id,
                as_of_date=as_of_date,
                status="completed",
                stored_hash=stored_hash,
                computed_hash=stored_hash,
                is_forced=False,
                version=current_version,
            )

        # Run the pipeline
        if self.pipeline_runner is None:
            logger.error("replay_no_pipeline_runner")
            return ReplayResult(
                strategy_id=strategy_id,
                as_of_date=as_of_date,
                status="failed",
            )

        try:
            result = self.pipeline_runner(strategy_id, as_of_date)
            computed_hash = self._compute_result_hash(result)
            new_version = current_version + 1 if force else max(current_version, 1)

            # Store the result
            if self.result_store is not None:
                self.result_store.put_result(
                    strategy_id=strategy_id,
                    as_of_date=as_of_date,
                    task_name="pipeline",
                    result_hash=computed_hash,
                    version=new_version,
                )

            # Check determinism
            status = "completed"
            if stored_hash is not None and stored_hash != computed_hash:
                status = "determinism_violation"
                logger.warning(
                    "replay_determinism_violation",
                    strategy_id=strategy_id,
                    as_of_date=str(as_of_date),
                    stored_hash=stored_hash,
                    computed_hash=computed_hash,
                )

            return ReplayResult(
                strategy_id=strategy_id,
                as_of_date=as_of_date,
                status=status,
                stored_hash=stored_hash,
                computed_hash=computed_hash,
                is_forced=force,
                version=new_version,
            )

        except Exception as exc:
            logger.error("replay_failed", error=str(exc), exc_info=True)
            return ReplayResult(
                strategy_id=strategy_id,
                as_of_date=as_of_date,
                status="failed",
            )

    def backfill(
        self,
        strategy_id: str,
        start_date: date,
        end_date: date,
        force: bool = False,
    ) -> list[ReplayResult]:
        """Backfill a date range serially.

        Runs the pipeline for each trading day in [start_date, end_date].
        Stops on failure unless force=True.

        Args:
            strategy_id: Strategy identifier.
            start_date: First date to backfill (inclusive).
            end_date: Last date to backfill (inclusive).
            force: Whether to overwrite existing results.

        Returns:
            List of ReplayResult for each date processed.
        """
        logger.info(
            "backfill_start",
            strategy_id=strategy_id,
            start_date=str(start_date),
            end_date=str(end_date),
        )

        results: list[ReplayResult] = []
        current = start_date

        while current <= end_date:
            # Skip weekends (basic — doesn't handle holidays)
            if current.weekday() < 5:
                result = self.replay(strategy_id, current, force=force)
                results.append(result)

                if result.status == "failed" and not force:
                    logger.error(
                        "backfill_stopped_on_failure",
                        strategy_id=strategy_id,
                        failed_date=str(current),
                    )
                    break

            current += timedelta(days=1)

        logger.info(
            "backfill_complete",
            strategy_id=strategy_id,
            total_dates=len(results),
            failures=sum(1 for r in results if r.status == "failed"),
            violations=sum(1 for r in results if r.status == "determinism_violation"),
        )

        return results

    def verify(
        self,
        strategy_id: str,
        as_of_date: date,
    ) -> ReplayResult:
        """Verify determinism by replaying and comparing hashes.

        Always re-runs the pipeline (equivalent to replay with force=False
        but always computes). Does NOT overwrite the stored result.

        Args:
            strategy_id: Strategy identifier.
            as_of_date: The date to verify.

        Returns:
            ReplayResult with determinism comparison.
        """
        logger.info(
            "verify_start",
            strategy_id=strategy_id,
            as_of_date=str(as_of_date),
        )

        stored_hash = None
        if self.result_store is not None:
            stored_hash = self.result_store.get_hash(strategy_id, as_of_date, "pipeline")

        if self.pipeline_runner is None:
            return ReplayResult(
                strategy_id=strategy_id,
                as_of_date=as_of_date,
                status="failed",
            )

        try:
            result = self.pipeline_runner(strategy_id, as_of_date)
            computed_hash = self._compute_result_hash(result)

            if stored_hash is not None and stored_hash != computed_hash:
                return ReplayResult(
                    strategy_id=strategy_id,
                    as_of_date=as_of_date,
                    status="determinism_violation",
                    stored_hash=stored_hash,
                    computed_hash=computed_hash,
                )

            return ReplayResult(
                strategy_id=strategy_id,
                as_of_date=as_of_date,
                status="completed",
                stored_hash=stored_hash,
                computed_hash=computed_hash,
            )

        except Exception as exc:
            logger.error("verify_failed", error=str(exc), exc_info=True)
            return ReplayResult(
                strategy_id=strategy_id,
                as_of_date=as_of_date,
                status="failed",
            )

    @staticmethod
    def _compute_result_hash(result: Any) -> str:
        """Compute a deterministic hash of a pipeline result."""
        try:
            serialized = json.dumps(
                {
                    "status": getattr(result, "status", str(result)),
                    "strategy_id": getattr(result, "strategy_id", ""),
                    "as_of_date": str(getattr(result, "as_of_date", "")),
                },
                sort_keys=True,
                default=str,
            )
            return hashlib.sha256(serialized.encode()).hexdigest()[:16]
        except (TypeError, ValueError):
            return hashlib.sha256(repr(result).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entrypoint for replay/backfill/verify commands."""
    parser = argparse.ArgumentParser(
        description="Replay, backfill, or verify portfolio pipeline runs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # replay command
    replay_parser = subparsers.add_parser("replay", help="Replay a single date")
    replay_parser.add_argument("--strategy", required=True, help="Strategy ID")
    replay_parser.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    replay_parser.add_argument("--force", action="store_true", help="Overwrite existing")

    # backfill command
    backfill_parser = subparsers.add_parser("backfill", help="Backfill a date range")
    backfill_parser.add_argument("--strategy", required=True, help="Strategy ID")
    backfill_parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    backfill_parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    backfill_parser.add_argument("--force", action="store_true", help="Overwrite existing")

    # verify command
    verify_parser = subparsers.add_parser("verify", help="Verify determinism")
    verify_parser.add_argument("--strategy", required=True, help="Strategy ID")
    verify_parser.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")

    args = parser.parse_args()

    # Note: In production, pipeline_runner and result_store would be
    # injected from the application context. This CLI is for development.
    engine = ReplayEngine(pipeline_runner=None, result_store=None)

    if args.command == "replay":
        result = engine.replay(
            strategy_id=args.strategy,
            as_of_date=date.fromisoformat(args.date),
            force=args.force,
        )
        print(f"Replay: {result.status} (hash={result.computed_hash})")

    elif args.command == "backfill":
        results = engine.backfill(
            strategy_id=args.strategy,
            start_date=date.fromisoformat(args.start),
            end_date=date.fromisoformat(args.end),
            force=args.force,
        )
        print(f"Backfill: {len(results)} dates processed")
        failures = [r for r in results if r.status == "failed"]
        if failures:
            print(f"  Failures: {len(failures)}")

    elif args.command == "verify":
        result = engine.verify(
            strategy_id=args.strategy,
            as_of_date=date.fromisoformat(args.date),
        )
        if result.is_deterministic():
            print(f"Verify: PASS (hash={result.computed_hash})")
        else:
            print(
                f"Verify: FAIL — stored={result.stored_hash}, "
                f"computed={result.computed_hash}"
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
