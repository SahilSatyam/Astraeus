"""Topic model refit worker — triggered by cron or manual invocation.

Re-fits BERTopic every 30 days on a 90-day rolling window.
Computes drift from previous run and alerts if threshold exceeded.

Usage:
    python -m astraeus_workers.topic_refit
    python -m astraeus_workers.topic_refit --force
"""

from __future__ import annotations

import argparse
import asyncio

import structlog

logger = structlog.get_logger("astraeus.workers.topic_refit")


async def run() -> None:
    """Execute the topic model refit."""
    from astraeus_altdata.topic_refit import run_refit
    from astraeus_config.base import Settings
    from astraeus_db.engine import create_async_session_factory

    settings = Settings()
    session_factory = create_async_session_factory(settings.db.dsn)

    async with session_factory() as session:
        result = await run_refit(session)

        if result is None:
            logger.info("topic_refit_not_due")
        elif result.get("skipped"):
            logger.warning("topic_refit_skipped", **result)
        else:
            logger.info("topic_refit_success", **result)

            # Record drift metric
            from astraeus_altdata.metrics import record_topic_drift

            drift = result.get("drift_score", 0.0)
            record_topic_drift(float(drift))


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Topic model refit worker")
    parser.add_argument("--force", action="store_true", help="Force refit regardless of schedule")
    _args = parser.parse_args()

    asyncio.run(run())


if __name__ == "__main__":
    main()
