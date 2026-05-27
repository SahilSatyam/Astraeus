# Phase 1 — Market Data Platform MVP

**Timeline:** Weeks 2–6 · **Depends on:** Phase 0 · **Blocks:** Phases 2–8

---

## 1. Phase Goals & Refined Exit Criteria

The mission is **trustworthy market data with provable lineage**. Trustworthy means: identical inputs produce identical bytes on disk, every row can be traced to its source response, and a downstream consumer can replay any historical window deterministically. This is the foundation everything else stands on — Phase 3's "backtester that doesn't lie" is impossible if Phase 1 lies first.

Refined exit criteria:

- **Reproducible backfill** of S&P 500 daily OHLCV from 2010-01-01 to today using Polygon as primary, Yahoo as cross-check; row counts and per-row hashes match across two clean runs.
- **One streaming symbol** (e.g., SPY via Alpaca WebSocket) ingested for 24 hours with zero gaps in market hours and explicit gap markers outside market hours.
- **Corporate-action correctness:** AAPL 2014-06 (7:1) and 2020-08 (4:1) splits, plus dividends, applied via a re-runnable adjustment job; both adjusted and unadjusted series available.
- **Lineage visible:** for any `(symbol, date)` row in `market_bars`, a single SQL query returns `source`, `source_response_hash`, `ingestion_run_id`, `schema_version`, `adjusted_at`.
- **Replay drill:** delete one symbol's data, re-run ingestion from outbox/raw store, end up byte-identical.

---

## 2. Scope Boundaries

| In scope | Out of scope (deferred) |
|---|---|
| Daily OHLCV (equities, ETFs) | Tick-by-tick storage at scale |
| 1-minute bars (single venue) | Options chains and Greeks |
| Macro series from FRED | Futures roll logic |
| Alpaca WebSocket trades + quotes for 1–2 symbols | Full L2 order book |
| Corporate actions: splits, cash dividends | Spinoffs, M&A symbol remap (Phase 1.5) |
| Polygon, Yahoo, AlphaVantage, FRED, Alpaca historical/streaming | IBKR, Binance (Phase 8) |
| Idempotent ingestion + outbox + DLQ | CDC into downstream stores (Phase 2) |
| Avro schemas in registry | Protobuf services (revisit if proto becomes more useful) |

The crypto and forex adapters are scaffolded (interface contract + one stub) but not productionised — they exist so Phase 2 can read from them without surgery later.

---

## 3. Week-by-Week Breakdown

### Week 2 — Contracts & Skeleton
- Define Avro schemas for `bar_v1`, `tick_v1`, `corporate_action_v1`, `macro_series_v1` in `libs/contracts/avro/`.
- Stand up Karapace (Apicurio is heavier; Karapace is fine for one team) as schema registry alongside Redpanda from Phase 0.
- Topic naming policy: `md.<asset_class>.<resolution>.<source>.v1` (e.g., `md.equity.daily.polygon.v1`). Document in `libs/contracts/README.md`.
- Stub `BaseAdapter` interface and `IngestionRun` lifecycle in `libs/marketdata/`.

### Week 3 — Polygon + Yahoo Historical
- Polygon REST adapter: paginated `/v2/aggs/ticker/{ticker}/range/1/day/...`; rate-limit-aware (token bucket); retries with jitter; raw response stored to MinIO before parsing.
- Yahoo (yfinance) adapter as cross-check source.
- Outbox pattern: `(ingestion_run_id, payload_hash, payload, kafka_offset_after_publish)` written in same DB transaction as the raw landing.
- DLQ topic per source: `md.dlq.<source>.v1`.

### Week 4 — Timescale Sink + Adjustments
- Timescale hypertables: `market_bars_raw` (unadjusted) and `market_bars_adjusted` (split/div applied). Two separate tables, not a flag column — accidental re-adjustment is too easy with a flag.
- Corporate-action ingestion from Polygon Reference; adjustment job rewrites adjusted table from raw + actions; idempotent on `(symbol, action_id)`.
- Continuous aggregate for weekly/monthly rollups.
- Lineage table populated from outbox.

### Week 5 — Streaming + Calendar
- Alpaca WebSocket consumer producing onto `md.equity.tick.alpaca.v1`.
- `pandas-market-calendars` wrapped behind a `MarketCalendar` service exposed over gRPC + cached in Redis (NYSE, NASDAQ, CME, LSE day one).
- Gap detection: nightly job comparing expected trading days from calendar vs present days in `market_bars_adjusted`. Gap rows materialised in `data_gaps` table.

### Week 6 — Replay, FRED, Hardening
- Replay tool: `astraeus md replay --source polygon --from 2024-01-01 --to 2024-01-31 --dry-run`.
- FRED adapter (low-frequency macro series; trivial vs equities).
- AlphaVantage adapter (hot backup for Polygon outages).
- Chaos drill: kill the Polygon adapter mid-backfill, restart, verify zero duplicate rows and zero missing rows.
- Wire ingestion lag and DLQ depth metrics into Grafana.

---

## 4. Component & Service Architecture

```
                ┌─────────────────────────────────────────────┐
                │                Schema Registry              │
                │                  (Karapace)                 │
                └───────────────────┬─────────────────────────┘
                                    │ Avro schemas
                                    ▼
┌──────────────────┐    ┌──────────────────────┐    ┌──────────────────┐
│  Source Adapters │    │   Ingestion Worker   │    │  MinIO (raw)     │
│  (Polygon, AV,   │───►│  (per-source pods,   │───►│  source/         │
│   Yahoo, Alpaca, │    │   async, rate-limit, │    │   yyyy/mm/dd/    │
│   FRED)          │    │   outbox writer)     │    │   resp_<hash>.   │
└──────────────────┘    └──────────┬───────────┘    │   json.zst       │
                                   │ outbox          └──────────────────┘
                                   │ relay
                                   ▼
                        ┌──────────────────────┐
                        │   Redpanda Topics    │
                        │   md.equity.*        │
                        │   md.macro.*         │
                        │   md.dlq.*           │
                        └──────────┬───────────┘
                                   │
                ┌──────────────────┴─────────────────┐
                ▼                                    ▼
    ┌────────────────────┐                ┌────────────────────┐
    │  Timescale Sink    │                │  CDC Reserved      │
    │  (raw + adjusted)  │                │  (Phase 2 hooks)   │
    └─────────┬──────────┘                └────────────────────┘
              │
              ▼
    ┌────────────────────┐    ┌────────────────────┐
    │  Adjustment Worker │    │  Gap Detector       │
    │  (splits/divs)     │    │  (nightly)          │
    └────────────────────┘    └────────────────────┘

    ┌────────────────────┐    ┌────────────────────┐
    │  Calendar Service  │    │  Lineage Service    │
    │  (NYSE, NASDAQ,    │    │  (read API over     │
    │   CME, LSE)        │    │   lineage table)    │
    └────────────────────┘    └────────────────────┘
```

Six services, each independently deployable. The outbox-relay pattern is what gives effectively-once: same DB transaction writes raw landing + outbox row; relay publishes to Redpanda; consumer is idempotent on `(source, payload_hash)`.

---

## 5. Folder & File Structure

```
apps/
├─ md-ingest-polygon/       # one binary per source — keeps blast radius small
├─ md-ingest-yahoo/
├─ md-ingest-alphavantage/
├─ md-ingest-fred/
├─ md-stream-alpaca/        # WS consumer
├─ md-sink-timescale/       # Redpanda → Timescale
├─ md-adjust-worker/        # corporate actions
├─ md-gap-detector/         # nightly cron
├─ md-calendar/             # gRPC + Redis cache
└─ md-replay-cli/           # operator tool
libs/
├─ contracts/
│  ├─ avro/
│  │  ├─ bar_v1.avsc
│  │  ├─ tick_v1.avsc
│  │  ├─ corporate_action_v1.avsc
│  │  └─ macro_series_v1.avsc
│  └─ topics.py             # canonical topic name builders
├─ marketdata/
│  ├─ adapters/             # BaseAdapter + concrete sources
│  ├─ outbox.py
│  ├─ ratelimit.py
│  ├─ retry.py
│  └─ lineage.py
└─ calendar/
   └─ schedules.py
infra/
└─ migrations/              # Alembic, includes Timescale extensions
```

One adapter per binary is deliberate. A single bug in the Yahoo adapter that OOMs the pod must not stop Polygon ingestion. Co-locating them in a monorepo gives shared libs + isolated runtime.

---

## 6. Data Model / Schema Changes

```sql
-- Hypertable: raw, unadjusted bars (immutable after initial write)
CREATE TABLE market_bars_raw (
    symbol         TEXT        NOT NULL,
    ts             TIMESTAMPTZ NOT NULL,
    resolution     TEXT        NOT NULL,             -- '1m','1h','1d'
    open           NUMERIC(20,8) NOT NULL,
    high           NUMERIC(20,8) NOT NULL,
    low            NUMERIC(20,8) NOT NULL,
    close          NUMERIC(20,8) NOT NULL,
    volume         BIGINT,
    vwap           NUMERIC(20,8),
    trades         INT,
    source         TEXT        NOT NULL,
    schema_version SMALLINT    NOT NULL,
    ingest_run_id  UUID        NOT NULL,
    payload_hash   BYTEA       NOT NULL,             -- sha256 of source row
    PRIMARY KEY (symbol, ts, resolution, source)
);
SELECT create_hypertable('market_bars_raw', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    partitioning_column => 'symbol',
    number_partitions   => 16);

-- Hypertable: split/div-adjusted bars; rebuilt by the adjustment worker
CREATE TABLE market_bars_adjusted (
    LIKE market_bars_raw INCLUDING ALL,
    adjusted_at      TIMESTAMPTZ NOT NULL,
    adjustment_hash  BYTEA NOT NULL                  -- hash of action set used
);
SELECT create_hypertable('market_bars_adjusted', 'ts', ...);

-- Corporate actions
CREATE TABLE corporate_actions (
    action_id    UUID PRIMARY KEY,
    symbol       TEXT NOT NULL,
    action_type  TEXT NOT NULL CHECK (action_type IN ('split','dividend','spinoff')),
    ex_date      DATE NOT NULL,
    ratio        NUMERIC(20,10),
    cash_amount  NUMERIC(20,8),
    source       TEXT NOT NULL,
    raw_payload  JSONB,
    UNIQUE (symbol, action_type, ex_date, source)
);

-- Lineage: one row per (target_table, primary_key, source) write
CREATE TABLE data_lineage (
    id              BIGSERIAL PRIMARY KEY,
    target_table    TEXT NOT NULL,
    target_pk       JSONB NOT NULL,                  -- composite PK as json
    source          TEXT NOT NULL,
    source_endpoint TEXT,
    source_response_hash BYTEA NOT NULL,
    source_response_uri  TEXT,                       -- minio://...
    schema_version  SMALLINT NOT NULL,
    ingest_run_id   UUID NOT NULL,
    written_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON data_lineage (target_table, (target_pk->>'symbol'), written_at DESC);

-- Outbox (drained by relay into Redpanda)
CREATE TABLE outbox (
    id             BIGSERIAL PRIMARY KEY,
    topic          TEXT NOT NULL,
    key            BYTEA,
    payload        BYTEA NOT NULL,
    headers        JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at   TIMESTAMPTZ
);
CREATE INDEX ON outbox (published_at) WHERE published_at IS NULL;

-- Instrument master
CREATE TABLE instruments (
    symbol         TEXT PRIMARY KEY,
    asset_class    TEXT NOT NULL,
    primary_exchange TEXT,
    listed_at      DATE,
    delisted_at    DATE,
    sector         TEXT,
    industry       TEXT,
    is_active      BOOLEAN GENERATED ALWAYS AS (delisted_at IS NULL) STORED
);

-- Gaps
CREATE TABLE data_gaps (
    symbol     TEXT NOT NULL,
    resolution TEXT NOT NULL,
    expected_ts TIMESTAMPTZ NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    PRIMARY KEY (symbol, resolution, expected_ts)
);
```

Compression policy: `ALTER TABLE market_bars_adjusted SET (timescaledb.compress, timescaledb.compress_segmentby='symbol');` then `add_compression_policy(..., INTERVAL '30 days')`. Older chunks compress 6–10×.

---

## 7. API Surface

**REST (FastAPI, internal):**
- `POST /md/backfill` — body `{source, asset_class, symbols[], from, to, dry_run}` → `IngestionRun`.
- `GET  /md/runs/{run_id}` — status + counters.
- `GET  /md/lineage` — `?table=market_bars_adjusted&symbol=AAPL&ts=...` → list of source response refs.
- `GET  /md/gaps` — open gaps with filters.
- `POST /md/replay` — re-emit raw rows from outbox/MinIO into topic for a window.

**Kafka/Redpanda topics (Avro-encoded):**

| Topic | Key | Value | Notes |
|---|---|---|---|
| `md.equity.daily.polygon.v1` | `symbol` | `bar_v1` | Append, key partitioned |
| `md.equity.tick.alpaca.v1` | `symbol` | `tick_v1` | High volume; tighter retention |
| `md.equity.action.v1` | `symbol` | `corporate_action_v1` | Compacted topic |
| `md.macro.fred.v1` | `series_id` | `macro_series_v1` | Compacted |
| `md.dlq.<source>.v1` | original key | original value + error headers | Manual replay |

Avro `bar_v1` sketch:
```json
{
  "type": "record", "name": "Bar", "namespace": "astraeus.md",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "ts_micros", "type": "long", "logicalType": "timestamp-micros"},
    {"name": "resolution", "type": "string"},
    {"name": "open", "type": {"type": "bytes", "logicalType": "decimal", "precision": 20, "scale": 8}},
    {"name": "high", "type": {"type": "bytes", "logicalType": "decimal", "precision": 20, "scale": 8}},
    {"name": "low",  "type": {"type": "bytes", "logicalType": "decimal", "precision": 20, "scale": 8}},
    {"name": "close","type": {"type": "bytes", "logicalType": "decimal", "precision": 20, "scale": 8}},
    {"name": "volume","type": ["null","long"], "default": null},
    {"name": "source","type": "string"},
    {"name": "schema_version", "type": "int"},
    {"name": "ingest_run_id", "type": "string"},
    {"name": "payload_hash", "type": "bytes"}
  ]
}
```

---

## 8. External Dependencies

| Provider | Purpose | Auth | Rate limit | Failure mode |
|---|---|---|---|---|
| Polygon.io | Primary equities (REST + WS) | API key | 5 calls/min on free, unlimited paid | Quota exhaust → switch to AlphaVantage |
| Alpaca | Streaming + paper-trading bridge | API key + secret | 200 reqs/min | Reconnect WS on disconnect |
| Yahoo (yfinance) | Cross-check + free fallback | none | unofficial | Frequent layout breaks; cross-check only |
| AlphaVantage | Hot backup for Polygon | API key | 5 calls/min, 500/day | Used only on Polygon outage |
| FRED | Macro series | API key | 120 reqs/min | Low-frequency, low risk |

Secrets land in Vault path `astraeus/md/<source>/`. Rotation cadence: 90 days; Polygon keys rotated quarterly with a stagger window.

---

## 9. Key Technical Decisions & Tradeoffs

**Avro vs Protobuf.** Avro for streaming. Schema evolution rules in Avro (BACKWARD/FORWARD) are mature, the Kafka tooling assumes Avro by default, and human-readable JSON-encoded `.avsc` makes diff review easy. Protobuf wins on RPC and on raw throughput; we don't need either advantage here. If Phase 8 introduces FIX-derived order events with stricter latency targets, those services can use proto independently.

**Timescale vs vanilla Postgres partitioning.** Timescale. Native partition management, continuous aggregates, compression, and the `time_bucket` ergonomics all matter daily. The complaint about Timescale is licensing on cluster mode; we're single-node for this MVP and that's fine. Plan: revisit at the 1B-row mark.

**Effectively-once vs exactly-once.** Exactly-once across heterogeneous systems is a marketing term. The honest pattern is *idempotent sinks keyed on a deterministic ID + transactional outbox at the source*. We do that. The deterministic ID is `sha256(source || endpoint || canonical(payload))`. Re-publish, re-consume, re-write — same row, same hash, no duplicate.

**Outbox vs CDC.** Outbox now, CDC reserved. CDC (Debezium on Postgres logical replication) is the right answer for Phase 2 fan-out into the feature store. For Phase 1 the outbox table is simpler to reason about and the relay can be a 50-line Python loop.

**Push (vendor pushes to us) vs pull (we poll vendor).** Pull for historical backfills, push for streaming. The pull adapters live behind explicit cron schedules so a runaway adapter cannot exceed quota. Streaming WS reconnect is exponential-backoff with full re-subscribe; we never trust resume tokens across restarts.

**Per-source pod vs one big ingester.** Per-source. Vendors fail independently and at different cadences (Yahoo broke its CSV format twice in 2023). Isolation gives clean SLOs and clean blast radius.

**Why not zipline/QuantConnect data feeds?** They're products, not infrastructure. We need lineage and replay we own, not vendor-locked bundles.

---

## 10. Risks, Failure Modes & Mitigations

| Risk | Probability | Mitigation |
|---|---|---|
| Vendor outage (Polygon) | High | AlphaVantage hot backup on a circuit-breaker pattern; Yahoo as last-resort cross-check |
| Schema drift mid-day | Medium | Schema registry rejects incompatible payloads; DLQ + alert; raw payload retained for replay |
| Late-arriving corrections | High | Adjustment worker is idempotent; restatements re-trigger downstream feature recompute |
| Survivorship via delisting | High | `instruments` keeps `delisted_at`; never filter on `is_active` for historical backtests |
| Time-zone bugs | High | All TS in UTC end-to-end; convert at display only; calendar service exposes local-zone helpers but storage is UTC |
| Float / decimal contamination | Medium | All prices `NUMERIC(20,8)`; serialise via Avro `decimal` logical type; no `float` in schemas |
| Gaps masked as nulls | Medium | Detector materialises gaps as rows in `data_gaps`; absence ≠ silence |
| Corporate action source disagreement | Medium | Track action source in `corporate_actions`; prefer Polygon Reference, alert if Yahoo split-adjusts disagree by >0.5% |
| Backfill running forever | Low | Per-job watchdog; resumable via `ingest_run_id` + outbox |
| Time-of-trade ambiguity for ticks | High (later) | Capture both vendor `t` (their server) and local `ingested_at`; never use ingestion time for backtests |

---

## 11. Testing Strategy

**Contract tests.** For each Avro schema, golden bytes pinned in `libs/contracts/avro/__golden__/`; CI rejects breaking changes that aren't BACKWARD-compatible.

**Adapter unit tests.** Replay recorded vendor responses (in `libs/marketdata/__fixtures__/`) and assert deterministic parsing. No network in unit tests.

**Integration tests** (Testcontainers: Postgres+Timescale, Redpanda, MinIO, Karapace):
- End-to-end Polygon mock → Redpanda → Timescale → assertions on row counts and hashes.
- Idempotency: same payload twice produces one row.
- Outbox crash recovery: kill relay mid-publish, restart, no dupes.

**Property tests** (Hypothesis):
- Adjustment worker: `apply(reverse(actions), apply(actions, raw)) == raw` (within decimal precision).
- Gap detector: never reports gap on a calendar holiday.

**Determinism drill.** Two clean runs of the SPY 2020-01 backfill must produce identical `payload_hash` sets and identical row counts. CI gate.

**Chaos.** Toxiproxy on the Redpanda port; verify backfill survives 30s of zero throughput.

---

## 12. Observability Hooks

| Signal | Type | SLO |
|---|---|---|
| `md_ingest_lag_seconds{source,topic}` | gauge | p95 < 60s for daily, < 5s for streaming |
| `md_dlq_depth{source}` | gauge | alert if > 0 for 5 min |
| `md_payload_hash_collisions_total` | counter | alert on any non-zero |
| `md_gap_open_total{symbol_class}` | gauge | alert if > 0 outside known holidays |
| `md_adjust_worker_lag_seconds` | gauge | < 600s after corporate-action arrival |
| `md_outbox_unpublished{age_bucket}` | gauge | none > 60s |
| `md_calendar_cache_hit_ratio` | gauge | > 0.95 |
| Trace spans | OTel | every adapter call has `source`, `endpoint`, `symbol_count`, `bytes_in` |

Grafana dashboards: one per source plus one cross-source rollup. Pager rules on DLQ depth and ingestion lag breaches.

---

## 13. Definition of Done

- [ ] All four historical adapters running in dev compose, gated by feature flag for staging.
- [ ] Alpaca WS streaming SPY for 24 consecutive hours with zero unexpected gaps.
- [ ] S&P 500 daily backfill 2010-01-01 → today: row count audit + hash audit pass.
- [ ] `astraeus md replay --source polygon --from ... --to ... --dry-run` produces identical hash diff vs current state.
- [ ] AAPL split test: adjusted close on 2014-06-08 = adjusted close on 2014-06-09 ± dividend/return; off by exactly 7× from raw.
- [ ] Gap detector run on a known holiday week: zero false positives.
- [ ] Toxiproxy chaos drill: backfill completes despite 30s broker outage; one alert fires; no data loss.
- [ ] Lineage query for one row returns full chain (source → endpoint → response hash → minio URI → outbox row → topic offset → table row) in < 100ms.
- [ ] Grafana dashboard live; pager rules active.
- [ ] Runbook: "Polygon outage" and "Schema drift detected" exist in `infra/runbooks/`.

---

## 14. Interview Talking Points

- **Effectively-once with deterministic IDs and transactional outbox.** Most candidates will say "exactly-once" and you can correct that. The honest framing is the conversation that hedge-fund infra engineers actually have.
- **Schema registry + Avro logical decimal.** Most retail systems use floats and silently corrupt prices on reads. Decimal end-to-end is non-negotiable.
- **Lineage as a first-class table.** Lineage is not a logging concern; it's a queryable database object. This is what makes restatements safe.
- **Adjusted vs raw as separate tables, not a flag.** Defends against the most common backtest bug.
- **Per-source pod isolation.** Operational story: a Yahoo CSV layout change last quarter would have stopped Polygon ingestion if they shared a process.
- **Calendar as a service.** Sounds trivial; bug source #1 in retail quant systems. UTC storage + calendar-aware retrieval is the only sane pattern.

---

## 15. Open Questions

1. **Polygon tier.** Free tier is too rate-limited for a 500-symbol universe; assume Starter ($79/mo) for the MVP. User to confirm budget.
2. **Universe membership policy.** S&P 500 is itself a moving target — need to decide whether we track historical constituents or a frozen snapshot for the demo.
3. **Storage tiering for raw responses.** MinIO local is fine for MVP. At what point do we move >180-day raw to cold S3? Defer until we have cost data.
4. **Tick vs minute storage.** Defer tick storage; the demo only needs minute bars. Revisit when Phase 8 needs execution-quality analysis.
5. **Crypto streaming.** Worth scaffolding the Binance adapter in week 6 even without productionising? Lean yes — the contract shape will be informative for Phase 2.

---

## Scope Mode: 2-Year Resume + Self-Sustaining Trading

The Phase 1 plan was scoped against a paid-Polygon, full-S&P-500 baseline. For a one-user portfolio + small live trading bet, the data tier is rebuilt around free sources first; paid tiers wait until a strategy actually demands intraday.

**Adapter priority (revised)**

1. **Alpaca Market Data API** — primary for paper-era data. Free for US equities, includes 1m bars and historical to 2016. For an Indian resident, Alpaca's market-data and paper-trading APIs are generally accessible; live trading at Alpaca is the part that's gated, and that's handled in Phase 8 by switching the broker adapter to IBKR. Phase 1's data path is unaffected.
2. **yfinance** — backfill convenience for daily bars and fundamentals. Unreliable for production but fine for personal use; treat its outputs as cross-checks, not source-of-truth.
3. **Alpha Vantage free tier** — 5 calls/min, 500/day. Useful for fundamentals and a few macro series.
4. **FRED** — free, no caveats, the macro source.
5. **SEC EDGAR** — free, fundamentals and filings.
6. **Polygon Starter ($29/mo)** — only if/when a Phase 3 strategy needs intraday bars across a wide universe. Defer until that's a real requirement.
7. **Binance** — defer the adapter; crypto trading isn't on the 2-year roadmap.

**Universe size**

- Drop full S&P 500 + Russell 2000 to **~150 names**: SPY/QQQ/IWM, the S&P 100, plus a handful of liquid ADRs and sector ETFs. Big enough to do real factor work, small enough that backfills finish on a laptop in minutes and free-tier rate limits don't gate development.
- Keep the survivorship-bias-aware universe schema — it's a key resume talking point — populate it with what's free.

**Storage**

- TimescaleDB and MinIO in `docker-compose`, on the dev machine or one $20–40/mo VPS. No managed RDS, no S3.
- Cold raw responses go to a local archive directory + offsite Backblaze B2 sync (~$1/mo) for safety, not for replay performance.

**What stays unchanged (resume-load-bearing)**

- Per-row hashes, lineage table, idempotent ingestion, DLQ, outbox pattern, corporate-action correctness, market-calendar service. These are the *story* of Phase 1.

**Budget impact:** $0/mo for Phase 1 data; +$29/mo when/if Polygon Starter is needed.
