import uuid
from datetime import UTC, datetime
from decimal import Decimal

from astraeus_marketdata.models import MarketBarRaw
from sqlalchemy.dialects.postgresql import insert

# We don't have postgres here so we can just look at the code generated
stmt = (
    insert(MarketBarRaw)
    .values(
        symbol="AAPL",
        ts=datetime.now(UTC),
        resolution="1M",
        open=Decimal("10.0"),
        high=Decimal("10.5"),
        low=Decimal("9.5"),
        close=Decimal("10.2"),
        volume=100,
        vwap=Decimal("10.1"),
        trades=10,
        source="alpaca",
        schema_version=1,
        ingest_run_id=uuid.uuid4(),
        payload_hash=b"hash",
    )
    .on_conflict_do_nothing(index_elements=["symbol", "ts", "resolution", "source"])
)

print(stmt)
