import asyncio
import time
from datetime import datetime, timezone
from decimal import Decimal
import uuid
from typing import Any

from astraeus_marketdata.adapters.base import BarRecord
from apps.workers.astraeus_workers.streaming import StreamingWorker

class MockRow:
    def __init__(self, symbol, ts, resolution):
        self.symbol = symbol
        self.ts = ts
        self.resolution = resolution

    # Allow row unpacking as expected by SQLAlchemy Row objects or similar dot access
    def __getattr__(self, name):
        if name == 'symbol': return self.symbol
        if name == 'ts': return self.ts
        if name == 'resolution': return self.resolution
        raise AttributeError(name)

class MockResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

class MockSession:
    def __init__(self, bars):
        self.executes = 0
        self.adds = 0
        self.commits = 0
        self._last_execute = None
        self.bars = bars

    async def execute(self, stmt):
        self.executes += 1
        self._last_execute = stmt

        # Simulate returning the rows we provided
        rows = [MockRow(bar.symbol, bar.ts, bar.resolution) for bar in self.bars]
        return MockResult(rows)

    def add(self, item):
        self.adds += 1

    def add_all(self, items):
        self.adds += len(items)

    async def commit(self):
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class MockSessionFactory:
    def __init__(self, bars):
        self.sessions = []
        self.bars = bars

    def __call__(self, **kwargs) -> MockSession:
        session = MockSession(self.bars)
        self.sessions.append(session)
        return session

async def main():
    bars = []
    for i in range(50):
        bars.append(BarRecord(
            symbol=f"SYM{i}",
            ts=datetime.now(timezone.utc),
            resolution="1M",
            open=Decimal("10.0"),
            high=Decimal("10.5"),
            low=Decimal("9.5"),
            close=Decimal("10.2"),
            volume=100,
            vwap=Decimal("10.1"),
            trades=10,
        ))

    factory = MockSessionFactory(bars)
    worker = StreamingWorker(
        session_factory=factory,
        api_key="test",
        api_secret="test",
    )

    start = time.perf_counter()
    # Mock flush batch
    await worker._flush_batch(bars)
    end = time.perf_counter()

    session = factory.sessions[-1]
    print(f"Time taken (Batched implementation): {end - start:.4f} seconds")
    print(f"Total executes: {session.executes}")
    print(f"Total adds: {session.adds}")

if __name__ == "__main__":
    asyncio.run(main())
