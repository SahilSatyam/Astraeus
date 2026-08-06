import asyncio
import time
from datetime import UTC, datetime
from decimal import Decimal

from apps.workers.astraeus_workers.streaming import StreamingWorker
from astraeus_marketdata.adapters.base import BarRecord
from astraeus_marketdata.models import Base
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


async def main():
    with PostgresContainer("postgres:15") as postgres:
        postgres.driver = "asyncpg"
        engine = create_async_engine(postgres.get_connection_url())

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        worker = StreamingWorker(
            session_factory=session_factory,
            api_key="test",
            api_secret="test",
        )

        bars = []
        for i in range(500):
            bars.append(
                BarRecord(
                    symbol=f"SYM{i}",
                    ts=datetime.now(UTC),
                    resolution="1M",
                    open=Decimal("10.0"),
                    high=Decimal("10.5"),
                    low=Decimal("9.5"),
                    close=Decimal("10.2"),
                    volume=100,
                    vwap=Decimal("10.1"),
                    trades=10,
                )
            )

        # First insert to populate
        await worker._flush_batch(bars)

        # Now benchmark when all exist
        start = time.perf_counter()
        for _ in range(5):
            await worker._flush_batch(bars)
        end = time.perf_counter()

        print(f"Time taken (all existing): {end - start:.4f} seconds")

        # Benchmark when none exist
        bars_new = []
        for i in range(500):
            bars_new.append(
                BarRecord(
                    symbol=f"SYM_NEW{i}",
                    ts=datetime.now(UTC),
                    resolution="1M",
                    open=Decimal("10.0"),
                    high=Decimal("10.5"),
                    low=Decimal("9.5"),
                    close=Decimal("10.2"),
                    volume=100,
                    vwap=Decimal("10.1"),
                    trades=10,
                )
            )

        start = time.perf_counter()
        await worker._flush_batch(bars_new)
        end = time.perf_counter()

        print(f"Time taken (none existing): {end - start:.4f} seconds")


if __name__ == "__main__":
    asyncio.run(main())
