# Topic Naming Policy

All Redpanda/Kafka topics in Astraeus follow a strict naming convention for
discoverability, schema evolution, and access control.

## Format

```
md.{asset_class}.{resolution_or_type}.v{version}
```

## Components

| Component | Values | Description |
|-----------|--------|-------------|
| `md` | fixed | Market data domain prefix |
| `asset_class` | `equity`, `macro`, `crypto`, `fundamentals` | Asset class or data domain |
| `resolution_or_type` | `daily`, `minute`, `tick`, `action` | Data granularity or event type |
| `v{version}` | `v1`, `v2`, ... | Schema version (breaking changes = new topic) |

## Active Topics

| Topic | Key | Value Schema | Retention | Notes |
|-------|-----|--------------|-----------|-------|
| `md.equity.daily.v1` | `symbol` | `BarEvent` | 30 days | Daily OHLCV bars |
| `md.equity.minute.v1` | `symbol` | `BarEvent` | 7 days | 1m/5m/15m bars |
| `md.equity.tick.v1` | `symbol` | `TickEvent` | 3 days | Trade-level ticks |
| `md.macro.daily.v1` | `series_id` | `MacroEvent` | compacted | FRED macro series |
| `md.corporate_actions.v1` | `symbol` | `CorporateActionEvent` | compacted | Splits, dividends |
| `md.fundamentals.v1` | `symbol` | `FundamentalEvent` | compacted | Earnings, financials |
| `md.dlq.v1` | original key | `DLQEvent` | 30 days | Dead letter queue |

## Rules

1. **One schema per topic.** Never mix event types on the same topic.
2. **Key = partition key.** All events for the same symbol land on the same partition, preserving order.
3. **Breaking changes = new topic.** Removing a field or changing a type creates `v2`. Additive changes (new optional fields) stay on the same topic.
4. **DLQ per source (optional).** For high-volume sources, use `md.dlq.{source}.v1` to isolate failures.
5. **Compacted topics** for reference data (corporate actions, instruments). These are keyed on `(symbol, action_id)` or `symbol`.

## Schema Registry

Schemas are defined as Pydantic models in `libs/contracts/astraeus_contracts/marketdata.py`.
The `SCHEMA_REGISTRY` dict maps topic names to their schema classes.

Validation: `validate_event(topic, payload)` validates any payload against its registered schema.

## Partition Strategy

- Equity topics: partitioned by `symbol` (hash). 16 partitions default.
- Macro topics: partitioned by `series_id`. 4 partitions (low volume).
- DLQ: 4 partitions (low volume, manual consumption).
