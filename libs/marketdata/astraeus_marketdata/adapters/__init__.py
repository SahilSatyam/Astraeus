"""Market data source adapters."""

from astraeus_marketdata.adapters.alpaca import AlpacaAdapter
from astraeus_marketdata.adapters.alpaca_ws import AlpacaStreamClient, StreamFeed
from astraeus_marketdata.adapters.alphavantage import AlphaVantageAdapter
from astraeus_marketdata.adapters.base import AdapterResult, BaseAdapter
from astraeus_marketdata.adapters.fred import FredAdapter
from astraeus_marketdata.adapters.polygon import PolygonAdapter
from astraeus_marketdata.adapters.yahoo import YahooAdapter

__all__ = [
    "AdapterResult",
    "AlpacaAdapter",
    "AlpacaStreamClient",
    "AlphaVantageAdapter",
    "BaseAdapter",
    "FredAdapter",
    "PolygonAdapter",
    "StreamFeed",
    "YahooAdapter",
]
