# ADR-0008 — Broker Adapter Pattern (Alpaca → IBKR)

**Status**: accepted
**Date**: 2026-04-20
**Decider(s)**: Sahil

## Context

The platform needs to support multiple brokers over its lifecycle:
1. Alpaca paper (development + first 12 months)
2. Interactive Brokers (live trading, post-paper validation)
3. Potentially Binance (crypto, future scope)

Switching brokers should not require OMS or strategy code changes.

## Decision

Abstract `BrokerAdapter` ABC with per-broker implementations.

```python
class BrokerAdapter(ABC):
    async def submit_order(self, order: BrokerOrder) -> BrokerOrderStatus: ...
    async def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus: ...
    async def get_positions(self) -> list[BrokerPosition]: ...
    async def get_fills(self, since: datetime) -> list[BrokerFill]: ...
```

The OMS depends only on the ABC. Broker selection is a configuration choice
(environment variable), not a code change.

## Migration path

1. **Phase 8 (paper):** `AlpacaAdapter` with paper credentials.
2. **Phase 8 (live):** `IBKRAdapter` via `ib_insync` TWS API. Config change only.
3. **Future:** `BinanceAdapter` for crypto. Same interface.

## Consequences

- OMS code is broker-agnostic; tested against a `MockBroker` in CI.
- Reconciliation worker uses the same adapter interface.
- Each adapter handles broker-specific quirks (rate limits, WebSocket vs REST, order ID formats).
- Adding a new broker = one new file implementing the ABC + config entry.

## Alternatives considered

- **Direct broker SDK calls in OMS** — tight coupling, untestable without live credentials.
- **Message queue between OMS and broker** — adds latency and complexity for no benefit at this scale.
