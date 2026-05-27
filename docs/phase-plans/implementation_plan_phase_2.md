# Phase 2 — Feature Store & Research Sandbox

**Window:** Weeks 6–9 (3 weeks, 1–3 engineers)
**Owner inputs from Phase 1:** Timescale hypertables for OHLCV/fundamentals/macro, Redpanda topics, the `data_lineage` table, the schema registry, MinIO bucket layout, the market calendar service.
**Downstream consumers:** Phase 3 (backtester), Phase 5 (sentiment features write-back), Phase 7 (recommendation engine signal generators).

---

## 1. Goals & Non-Goals

### Goals (MUST ship)
1. A **point-in-time-correct feature retrieval layer** over Timescale — calling code declares an `as_of_ts` and is structurally incapable of seeing rows whose knowledge timestamp is in the future.
2. **Survivorship-bias-aware universe tables** — delisted, merged, and renamed tickers retained, queryable as "the index/universe membership as of date D."
3. **Feature definitions as code** — a single Python DSL where features are declared once and produce both an offline materialization and an online retrieval path.
4. A **backfill engine** that can replay 10 years of history for a new feature in under 30 minutes for the S&P 500 + Russell 2000 (≈3500 names) without contention with live ingestion.
5. **JupyterHub on Kubernetes** with read-only DB role, MinIO-backed notebooks, a project kernel image, and no path to write to production tables.
6. **MLflow tracking server** wired into the JupyterHub kernel and Prefect runs, with artifacts on MinIO and metadata on the platform Postgres.
7. **Exit notebook**: 5 factor exposures (momentum, value, quality, low-vol, size) computed monthly across 2015-01–2024-12 on a survivorship-correct universe, with a PIT regression test that proves identical values regardless of when the query runs.

### Non-goals (explicitly out of scope for Phase 2)
- **Online sub-millisecond serving.** Timescale + Redis cache is fine for daily/intraday cadence. A dedicated low-latency feature server is a Phase 8 concern.
- **Streaming feature transforms.** Features that require online stateful computation are deferred. Phase 2 ships batch and micro-batch (≤1 min cadence). Tick-level streaming features land in Phase 3 if needed.
- **Alt-data features.** Sentiment/embeddings land in Phase 5 and write into the same store via the same DSL. Phase 2 only ships the substrate.
- **A general-purpose ML feature platform.** No on-the-fly Python UDFs at retrieval time, no graph features, no entity-relationship modeling beyond `(symbol, ts)` and `(universe, date)`.
- **Data quality framework.** Great Expectations / Soda is deferred to Phase 10. We do ship narrow PIT-correctness tests now.
- **Feature monitoring / drift.** Drift detection is Phase 6/7 concern, downstream of where features actually drive predictions.

---

## 2. Build vs Buy: Feast vs Homegrown

### Position: **Build homegrown over Timescale.** Adopt Feast only if a hard requirement for cross-language clients (Go/Java) appears in Phase 8.

### Why not Feast
1. **PIT join model is row-level and weak for our shape.** Feast's `get_historical_features` does an as-of join driven by an entity dataframe. For `3500 tickers × 2520 trading days × 40 features ≈ 350M rows`, materializing the entity dataframe in pandas memory is the choke point. Timescale's native `time_bucket` + `LATERAL` joins push this work into Postgres where it belongs.
2. **Two registries to maintain.** Feast keeps its own metadata; we already have Alembic, the schema registry from Phase 1, and `data_lineage`. A second registry creates drift.
3. **No survivorship semantics.** Feast has no concept of universe membership; you'd model it as just another feature, which loses the ergonomic "S&P 500 as of D" query.
4. **Online store mismatch.** Feast's online stores are Redis/DynamoDB/Cassandra row stores keyed by entity. Our online cadence is daily-to-minute, not millisecond.
5. **Materialization opacity.** Feast's `materialize` step is a black box. We want every transform to be a Prefect task with the data lineage hash recorded.

### Why not Tecton, Hopsworks, etc.
Closed-source/SaaS or heavyweight. Cost and operational footprint are unjustified for a 3-engineer team.

### What "homegrown" actually means
We are not building a feature store from scratch. We are building **three thin layers**:

1. **A Python DSL** (~400 LOC) that lets a researcher declare `FeatureDefinition(name, entity, dtype, transform, dependencies, freshness_sla)`. The DSL produces (a) a SQL view or materialization plan, (b) an entry in the feature catalog (`feature_registry` table), (c) a Prefect flow.
2. **A retrieval client** (~300 LOC) — the `astraeus.features.get(...)` function that all backtests, notebooks, and downstream services call. This is the only sanctioned way to read features and it always requires `as_of_ts`.
3. **A PIT-correct SQL pattern** baked into Timescale views and a small set of stored functions. All feature tables follow the same `(entity, event_ts, knowledge_ts, value, value_version)` shape.

### Decision rule for revisiting
Reopen this if any of: (a) a non-Python service in Phase 8 needs feature reads, (b) feature count exceeds ~500, (c) we onboard >5 researchers.

---

## 3. PIT Semantics — The Hard Part

### Formal definition

For any feature `F`, entity `e`, query time `as_of`, and value `v`, the retrieval contract is:

> `F.get(e, as_of) = v` if and only if there exists a row `r` in `F`'s storage such that:
> 1. `r.entity = e`
> 2. `r.event_ts <= as_of` (the underlying observation predates the query)
> 3. `r.knowledge_ts <= as_of` (we *knew* the observation by the query time — this is the leakage guard)
> 4. Among rows satisfying 1–3, `r` has the largest `event_ts`, and among ties, the largest `knowledge_ts`.
> 5. `r` has not been superseded by a row with the same `(entity, event_ts)` and a `knowledge_ts <= as_of` and a higher `value_version`.

The two-timestamp model `(event_ts, knowledge_ts)` is **bitemporal**. This is the only correct shape.

### Storage shape (canonical for every feature table)

```sql
CREATE TABLE feature_<group>_<name> (
    symbol         text        NOT NULL,
    event_ts       timestamptz NOT NULL,   -- when the world produced this fact
    knowledge_ts   timestamptz NOT NULL,   -- when we (the platform) could have known it
    value          numeric,                 -- or jsonb / vector for non-scalar
    value_version  smallint    NOT NULL DEFAULT 1,
    source_hash    text        NOT NULL,   -- joins to data_lineage
    PRIMARY KEY (symbol, event_ts, knowledge_ts)
);
SELECT create_hypertable('feature_<group>_<name>', 'event_ts', chunk_time_interval => interval '90 days');
CREATE INDEX ON feature_<group>_<name> (symbol, event_ts DESC, knowledge_ts DESC);
```

`knowledge_ts` is set by the materialization job and is **never** equal to `now()` for historical backfills — it must reflect when the upstream data was first available to us. For ingestion of vendor data, `knowledge_ts = source_publication_ts + ingestion_lag_floor`.

### Leakage failure modes and how each is prevented

#### (a) Look-ahead via fundamentals revisions
A 10-K filed 2023-03-15 reports Q4-2022 revenue of $100M. On 2023-08-01 the company restates Q4-2022 to $95M. A naive query for "Q4-2022 revenue as of 2023-04-01" must return $100M, not the restated $95M.

**Prevention:** Restatements arrive as **new rows** with the same `(symbol, event_ts)` but a later `knowledge_ts` and `value_version=2`. The retrieval query filters `WHERE knowledge_ts <= as_of_ts` and picks the highest version among surviving rows. We **never** UPDATE in place.

```sql
-- WRONG (naive single-timestamp model)
SELECT value FROM feature_fundamentals_revenue
WHERE symbol = 'AAPL' AND event_ts <= '2023-04-01'
ORDER BY event_ts DESC LIMIT 1;

-- RIGHT (bitemporal)
SELECT value FROM feature_fundamentals_revenue
WHERE symbol = 'AAPL'
  AND event_ts     <= '2023-04-01'
  AND knowledge_ts <= '2023-04-01'
ORDER BY event_ts DESC, knowledge_ts DESC, value_version DESC
LIMIT 1;
```

#### (b) Survivorship bias
Universe table retains delisted entities with explicit `effective_from`/`effective_to` membership intervals. Universe queries are bitemporal too. The retrieval client refuses to return features without a universe scope.

#### (c) Late-arriving data
The ingestion contract from Phase 1 (`data_lineage.first_observed_at`) is the floor for `knowledge_ts`. The materialization layer adds `vendor_lag_min` per source.

#### (d) Restated benchmarks / reference data
Universe tables track `announcement_ts` and `effective_ts` separately; the membership interval starts at `effective_ts`. `knowledge_ts` is `announcement_ts`.

#### (e) Forward-looking "snapshot" tables
**No snapshot tables.** Every materialization is append-only. Continuous aggregates use Timescale's invalidation log so they remain reproducible.

#### (f) Time-zone confusion
All timestamps are `timestamptz` stored as UTC, no exceptions. The DSL rejects `timestamp` (without tz).

#### (g) Floating-point comparison on knowledge_ts
All timestamps are nanosecond-precision in Postgres; tick-level features use a separate `event_ns bigint` column.

### The canonical retrieval primitive

```sql
CREATE OR REPLACE FUNCTION pit_latest(
    feature_table  regclass,
    p_symbol       text,
    p_as_of        timestamptz
) RETURNS TABLE (event_ts timestamptz, knowledge_ts timestamptz, value numeric)
LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN QUERY EXECUTE format($f$
        SELECT event_ts, knowledge_ts, value
        FROM %s
        WHERE symbol = $1
          AND event_ts     <= $2
          AND knowledge_ts <= $2
        ORDER BY event_ts DESC, knowledge_ts DESC, value_version DESC
        LIMIT 1
    $f$, feature_table) USING p_symbol, p_as_of;
END $$;
```

For multi-symbol multi-feature retrieval, the Python client builds a single `LATERAL` query:

```sql
SELECT eq.symbol, eq.as_of_ts, f.value
FROM   entity_query eq
LEFT JOIN LATERAL (
    SELECT value
    FROM feature_momentum_20d
    WHERE symbol = eq.symbol
      AND event_ts     <= eq.as_of_ts
      AND knowledge_ts <= eq.as_of_ts
    ORDER BY event_ts DESC, knowledge_ts DESC, value_version DESC
    LIMIT 1
) f ON true;
```

Researchers do not write it by hand.

---

## 4. Universe Tables

### Schema

```sql
CREATE TABLE universe (
    universe_id    text        NOT NULL,    -- 'sp500', 'russell2000'
    symbol         text        NOT NULL,
    effective_from timestamptz NOT NULL,
    effective_to   timestamptz,             -- NULL = currently a member
    announcement_ts timestamptz,
    knowledge_ts   timestamptz NOT NULL,
    reason_added   text,
    reason_removed text,
    successor_symbol text,
    PRIMARY KEY (universe_id, symbol, effective_from, knowledge_ts)
);
CREATE INDEX universe_lookup ON universe (universe_id, effective_from, effective_to);

CREATE TABLE security_master (
    symbol         text PRIMARY KEY,
    cusip          text,
    isin           text,
    figi           text,                    -- preferred long-term identifier
    listed_ticker  text,
    name           text,
    asset_class    text,
    listing_exchange text,
    listed_from    timestamptz,
    delisted_at    timestamptz,
    delisting_reason text
);

CREATE TABLE security_alias (
    canonical_symbol text NOT NULL REFERENCES security_master(symbol),
    alias_type     text NOT NULL,           -- 'ticker', 'cusip', 'isin'
    alias_value    text NOT NULL,
    effective_from timestamptz NOT NULL,
    effective_to   timestamptz,
    knowledge_ts   timestamptz NOT NULL,
    PRIMARY KEY (alias_type, alias_value, effective_from)
);
```

### Why a separate `security_master` and `security_alias`
Tickers get reused. CUSIPs change. ISINs are most stable but not universal. We pick **FIGI as the canonical immutable identifier**, store an internal `symbol` (stable surrogate) in `security_master`, and resolve external identifiers via `security_alias`.

### Handling CUSIP/ticker changes
- **Ticker change** (FB → META on 2022-06-09): same `canonical_symbol`, new `security_alias` row.
- **Merger:** `security_master` for absorbed entity gets `delisted_at`, `delisting_reason='merger'`, `successor_symbol`.
- **Spinoff:** parent retains its symbol; spun entity gets a new `security_master` row.

### Query: "S&P 500 as of 2015-06-30"

```sql
SELECT u.symbol, sm.listed_ticker
FROM universe u
JOIN security_master sm ON sm.symbol = u.symbol
WHERE u.universe_id = 'sp500'
  AND u.effective_from <= '2015-06-30'
  AND (u.effective_to IS NULL OR u.effective_to > '2015-06-30')
  AND u.knowledge_ts <= '2015-06-30';
```

Wrapped in `astraeus.universe.members(universe_id, as_of_ts)`. Backtests never read the table directly.

### Sourcing universe history
- **S&P 500:** CRSP/Compustat or scrape S&P press releases historically. Maintain via official `S&P Dow Jones` index changes feed.
- **Russell 2000:** FTSE Russell publishes annual reconstitutions.
- **Crypto universes:** maintain in-house from exchange listing/delisting events.

Budget: 2 engineer-days for historical load including reconciliation against published constituent lists.

---

## 5. Feature Definitions as Code

### DSL shape (Pythonic, no YAML)

```python
# libs/features/definitions/momentum.py
from astraeus.features import FeatureDefinition, Entity, sql_transform

momentum_20d = FeatureDefinition(
    name="momentum_20d",
    group="price_derived",
    entity=Entity.SYMBOL,
    dtype="numeric",
    description="20 trading day price momentum, log return.",
    dependencies=["ohlcv_daily"],
    freshness_sla=timedelta(hours=2),
    knowledge_lag=timedelta(0),
    materialization="incremental",
    partition_grain="daily",
    transform=sql_transform("""
        WITH lagged AS (
          SELECT symbol, event_ts, knowledge_ts, close,
                 LAG(close, 20) OVER (PARTITION BY symbol ORDER BY event_ts) AS close_20
          FROM ohlcv_daily
          WHERE event_ts <= :as_of
        )
        SELECT symbol, event_ts, knowledge_ts,
               LN(close / NULLIF(close_20, 0)) AS value,
               1 AS value_version
        FROM lagged
        WHERE close_20 IS NOT NULL
    """),
    owner="quant-research",
    tags=["factor", "momentum"],
)
```

### What the DSL produces
1. **Migration:** Alembic auto-generates the `feature_price_derived_momentum_20d` hypertable.
2. **Registry row** in `feature_registry`: `(name, group, dtype, dependencies[], owner, definition_hash, code_commit, materialization, freshness_sla, registered_at)`. `definition_hash = sha256(canonical(transform_source) + sorted(deps) + dtype)`.
3. **Prefect flow** registered with name `materialize_<feature_name>`.
4. **Online retrieval path:** Postgres view `v_pit_<feature_name>(symbol, as_of_ts)`.
5. **Offline retrieval path:** Parquet-on-MinIO partition writer.

### Versioning
- The **definition hash** is the version.
- A redefinition triggers a backfill and writes new rows with `feature_definition_hash = H2`. Old rows retained 90 days then archived.
- Backtests pin features by hash. Strategy registry stores `{feature_name: hash}`.

### Online vs offline transforms
- **Online (incremental):** Prefect cron task; only computes new partition. Writes to Timescale.
- **Offline (backfill):** Same SQL parameterized by `(start_date, end_date)`, writes to Parquet on MinIO, bulk-loads via `COPY`. 50–100x faster than transactional inserts.
- **Idempotency:** every materialization computes deterministic `run_hash`. Re-running is always safe.

### Worked example: 20-day momentum end-to-end

1. Researcher writes `momentum_20d.py` and opens PR.
2. CI runs: DSL validates SQL compiles against schema registry; synthetic-data unit test on 30-row Timescale fixture; PIT regression test.
3. PR merges. CD runs Alembic migration, registers Prefect flow, registers DSL entry.
4. Ops engineer triggers backfill: `start=2014-01-01, end=2025-01-01`. Flow queries universe (~5,500 distinct symbols), splits into ~120 monthly chunks, writes to staging Parquet, `COPY`s into hypertable.
5. Total wall time on 4-vCPU Postgres + 8-worker Prefect: ~12 minutes.
6. Exit notebook calls `astraeus.features.get(['momentum_20d'], universe='sp500', as_of_ts=monthly)`.

---

## 6. Storage Layout

### Hot path (Timescale, online)
- One **hypertable per feature**.
- **Partitioning:** by `event_ts` with 90-day chunk interval. Tick-level (Phase 5+): 1-day chunks.
- **Retention:** daily-cadence kept indefinitely; minute-cadence ages out to compressed chunks at 30 days, parquet at 1 year.
- **Compression:** Timescale native compression on chunks older than 14 days, segment by `symbol`, order by `event_ts DESC`. ~10x ratio.
- **Continuous aggregates:** only for OHLCV-style rollups inherited from Phase 1. Features that need rollups are their own materialized features.

### Cold path (MinIO, offline)
- Bucket: `s3://astraeus-features/`
- Layout: `feature_<group>_<name>/feature_definition_hash=<h>/dt=YYYY-MM-DD/symbol_bucket=<0..15>/data.parquet`
- 16-way `symbol_bucket` shard prevents single-file bloat.
- Parquet: snappy compression, 128 MB row groups, dictionary encoding on `symbol`.
- A **manifest** file `_manifest.json` per `feature_definition_hash` lists all partitions, rowcounts, lineage hashes.

### Why both hot and cold
- **Hot wins for:** small-window queries, point lookups, JOIN with universe tables.
- **Cold wins for:** 10-year backtests pulling 350M rows. Reading parquet directly into the backtester via DuckDB/polars is 10–20x faster.
- Retrieval client picks automatically based on query span: `< 1 year` and any window touching last 30 days → hot; everything else → cold.

### Indexing
- `(symbol, event_ts DESC, knowledge_ts DESC)` as the only index per feature table.
- No GIN/BRIN. Queries are always range-by-time + equality-on-symbol.
- Universe table: `(universe_id, effective_from, effective_to)` and `(symbol, effective_from)`.

### Naming
- Feature group prefixes (`price_derived_`, `fundamentals_`, `microstructure_`, `sentiment_`, `macro_`).
- Snake_case end to end.

---

## 7. Backfill & Materialization

### Orchestration choice: **Prefect 2** (over Airflow, Dagster, lightweight)

- **Python-native flows.**
- **Dynamic DAGs:** backfill flow that fans out over (universe × date_chunk) is a one-liner with `flow.map`.
- **Lightweight self-host:** Prefect server in single Postgres + worker pod.
- **Native event-driven triggers** (Prefect 2.10+).

Why not Dagster: software-defined-assets would compete with `feature_registry` and `data_lineage`.
Why not Airflow: ops weight + DAG-as-DSL friction + harder dynamic fan-out.
Why not lightweight: we'll regret reinventing retries, observability, backfill semantics.

### Backfill engine design

```python
@flow(name="backfill_feature")
def backfill_feature(
    feature_name: str,
    start: date,
    end: date,
    universe_id: str,
    chunk: timedelta = timedelta(days=30),
    write_mode: Literal["staging_parquet", "direct"] = "staging_parquet",
    dry_run: bool = False,
):
    fdef = registry.get(feature_name)
    chunks = list(date_chunks(start, end, chunk))
    symbols = universe.members_over_window(universe_id, start, end)
    materialize_chunk.map(
        feature_def=unmapped(fdef),
        chunk=chunks,
        symbols=unmapped(symbols),
        write_mode=unmapped(write_mode),
    )
    finalize_lineage(fdef, start, end)
```

Key properties:
1. **No nuking:** writes to staging schema, validates, then atomically swaps via partition attach.
2. **Backpressure:** max 4 chunks materializing concurrently.
3. **Resumable:** chunks with successful `run_hash` skipped on rerun.
4. **Bulk path:** staging_parquet → `COPY` from S3. ~50x faster.
5. **Throttle on lineage drift:** if upstream dependency's lineage hash changed mid-backfill, abort.

### Materialization triggers

- **Cron** (`schedule="0 17 * * 1-5"` after US close).
- **Event-driven:** subscribed to Redpanda topic `feature.materialized.<dep_name>`.
- **On-demand only:** rarely-used features.

Backtests **never trigger materialization implicitly**. If feature/range isn't materialized, get explicit `MaterializationRequired` error.

### Cost / runtime targets
- Daily incremental for 100 features × 5500 symbols: ≤5 min.
- Full backfill of one new feature, 10 years, 5500 symbols: ≤30 min.
- CI: synthetic 100-symbol × 1-year fixture, ≤30 sec.

---

## 8. Research Sandbox

### Choice: **JupyterHub on Kubernetes** with **KubeSpawner**

- VS Code dev containers: no shared infra story.
- Hex / Deepnote: SaaS, vendor lock, poor data residency.
- Plain Jupyter on a VM: no isolation, no quotas, secrets sprawl.

### Topology
- Hub deployed in cluster namespace `astraeus-research`.
- KubeSpawner launches `singleuser-server` pods from custom kernel image. Idle culler at 60 min.
- Authentication: GitHub OAuth (or Keycloak when Phase 10 SSO lands).
- Resource defaults: 2 CPU / 8 GB / 50 GB ephemeral. Power users: `large` profile (8/32/200).

### Notebook storage on S3/MinIO
- `s3contents` mounts `s3://astraeus-notebooks/<user>/`.
- Versioning enabled; 30 days of object versions.
- Local pod scratch is `/scratch` (ephemeral).

### Kernel image
Single project image `astraeus/research-kernel:<version>`:
- Python 3.12, jupyterlab, ipykernel.
- Pinned: `astraeus-features`, `astraeus-universe`, `astraeus-backtest-stub`, `polars`, `duckdb`, `pyarrow`, `numpy`, `pandas`, `statsmodels`, `scikit-learn`, `xgboost`, `mlflow`, `psycopg[binary]`, `boto3`.
- Rebuilt weekly; old tags preserved 90 days.
- Startup hook injects: read-only DB connection, MinIO read creds, MLflow URI, banner.

### Read-only DB role
```sql
CREATE ROLE researcher_ro NOINHERIT NOLOGIN;
GRANT CONNECT ON DATABASE astraeus TO researcher_ro;
GRANT USAGE ON SCHEMA public, features, universe, lineage TO researcher_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA features, universe, lineage TO researcher_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA features GRANT SELECT ON TABLES TO researcher_ro;
REVOKE ALL ON SCHEMA staging, exec, ops FROM researcher_ro;

CREATE ROLE researcher_alice LOGIN PASSWORD '...' IN ROLE researcher_ro;
```
- Statement timeout at role level (`statement_timeout = '5min'`).
- `pg_hba.conf` restricts to JupyterHub pod CIDR.
- PgBouncer in transaction mode, max 10 connections per user.

### Secrets handling
- No secrets in notebooks ever. Startup hook injects creds via env.
- `mask` IPython magic auto-redacts known patterns from cell outputs.
- Pre-commit-style server extension scans saved notebooks and refuses keys.
- Outbound network whitelisted: MinIO, Postgres, MLflow, Prefect API, public via logging proxy. PyPI via pull-through cache.

### What researchers cannot do
- Write to production feature tables.
- Delete/modify another user's notebooks.
- Reach broker/exec/order schemas.
- Run code as a different user.

---

## 9. Experiment Tracking

### Choice: **MLflow** self-hosted

- Self-hostable with existing infra. W&B self-hosting is paid.
- Vendor neutrality.
- Artifact storage on MinIO native.

### Topology
- `mlflow-server` deployment, 1 replica, behind cluster ingress.
- Backend store: platform Postgres, schema `mlflow`.
- Artifact store: `s3://astraeus-mlflow/`.
- Auth: OAuth proxy. Bearer token from kernel.

### What gets tracked
1. **Params:** full strategy/feature config, including `feature_name → definition_hash` map.
2. **Metrics:** Sharpe, Sortino, max DD, turnover.
3. **Tags:** `git_commit`, `data_lineage_hash`, `universe_id` and `universe_snapshot_hash`, `as_of_window`.
4. **Artifacts:** notebook (`.ipynb`) snapshot, realized-PnL series as parquet, plots, materialized feature manifest.
5. **Model:** serialized via `mlflow.<flavor>.log_model`.

### Convention
A wrapper `astraeus.tracking.run(experiment, ...)` is the only sanctioned entrypoint. Auto-attaches lineage hash and git commit.

### Reproducibility guarantee
Given a run ID:
1. `git checkout <run.tags.git_commit>`
2. Read `run.params.feature_hash_map` and `run.tags.data_lineage_hash`
3. Re-execute and get bitwise-identical metrics.

Asserted by reproducibility test in Phase 3 CI.

---

## 10. Contracts Exposed to Downstream

### Python client API

```python
from astraeus.features import features
from astraeus.universe import universe

# Universe membership
members: list[str] = universe.members(universe_id="sp500", as_of_ts=dt)

# Single-asof retrieval
df = features.get(
    symbols=members,
    feature_names=["momentum_20d", "value_book_to_market", "quality_roe"],
    as_of_ts=dt,
)

# Multi-asof retrieval — entity dataframe pattern
df = features.get_panel(
    entity_df=pd.DataFrame({"symbol": [...], "as_of_ts": [...]}),
    feature_names=[...],
    backend="auto",   # 'hot' | 'cold' | 'auto'
)

# Streaming (Phase 7 use)
async for row in features.stream(
    symbols=[...], feature_names=[...], from_ts=dt, until_ts=None
):
    ...
```

The client **enforces**:
- `as_of_ts` required and tz-aware.
- Symbols validated against `security_master`.
- Feature names validated against `feature_registry`.
- Backend logged with run for reproducibility.
- All retrievals emit OpenTelemetry spans with `feature_definition_hash`.

### SQL contracts (for read-heavy clients bypassing Python)

For Phase 3's vectorized backtester (DuckDB + Parquet):
- `s3://astraeus-features/feature_<group>_<name>/feature_definition_hash=<h>/dt=YYYY-MM-DD/...`
- Manifest at `s3://astraeus-features/feature_<group>_<name>/feature_definition_hash=<h>/_manifest.json`

### Tables/views shared with downstream

| Consumer | Table/view | Contract |
|---|---|---|
| Phase 3 | `features.v_pit_<name>(symbol, as_of_ts)` views | PIT-correct read |
| Phase 3 | `universe.members(...)` | Survivorship-correct |
| Phase 5 | DSL: register `FeatureDefinition` with group `sentiment_` | Same bitemporal contract |
| Phase 7 | `features.get_panel` for daily Stage 1 aggregator | One call per universe member |
| Phase 7 | `features.get_panel` over macro features | Same |

### Versioning of the contracts
- Python client: SemVer in `libs/features/`.
- SQL views: additive only during Phase 2-7. Renaming requires deprecation window.
- Manifests: schema versioned (`manifest_schema_version: 1`).

---

## 11. Testing Strategy for PIT Correctness

### Level 1: Schema invariants (every feature table)
A pytest fixture introspects every `feature_*` table and asserts:
- Has columns `symbol, event_ts, knowledge_ts, value, value_version, source_hash`.
- Primary key is `(symbol, event_ts, knowledge_ts)`.
- `event_ts` and `knowledge_ts` are `timestamptz`.
- Hypertable created on `event_ts`.

### Level 2: PIT regression suite (per feature)
For each registered feature, generated test:
1. Picks 50 random `(symbol, as_of_ts)` pairs.
2. Records value via `features.get(...)`.
3. Inserts synthetic future row (`event_ts > as_of_ts`).
4. Re-calls — asserts identical.
5. Inserts synthetic late-arriving correction.
6. Re-calls — asserts identical.

### Level 3: Time-travel property tests (Hypothesis)
```python
@given(symbol=symbols(), t1=timestamps(...), t2_offset=integers(...))
def test_pit_idempotent(symbol, t1, t2_offset):
    t2 = t1 + timedelta(days=t2_offset)
    val_at_t1_queried_now = features.get(symbol, ["X"], as_of_ts=t1)
    with simulated_clock(t2):
        val_at_t1_queried_at_t2 = features.get(symbol, ["X"], as_of_ts=t1)
    assert val_at_t1_queried_now == val_at_t1_queried_at_t2
```

### Level 4: Survivorship sanity (universe)
- Pick known events: Lehman bankruptcy, GE removal from Dow, FB→META rename, Bear Stearns, Sears delisting.
- Assert: `universe.members('sp500', as_of_ts='2008-09-12')` includes Lehman.
- Assert: querying features for Lehman with `as_of_ts='2008-09-15'` returns valid; with `as_of_ts='2008-09-20'` returns null/delisted.
- Assert: META and FB resolve to same `canonical_symbol`.

### Level 5: Reproducibility / lineage chain
- Run 1-year backtest of exit-criteria notebook in CI on frozen 50-symbol fixture.
- Re-run after randomly inserting late-arriving data.
- Assert: identical metrics output.
- Assert: lineage hash recorded in MLflow matches across runs.

### CI gating
- Levels 1, 2, 4 on every PR.
- Level 3 nightly.
- Level 5 nightly + on every release.

A PR adding a feature without Level 2 test is blocked by CI lint.

---

## 12. Exit Criteria Checklist

### The notebook
1. Loads universe `sp500` for each month-end 2015-01-31 through 2024-12-31. Confirms ≥500 names per month, with delisted retained.
2. Computes 5 factor exposures per (symbol, month-end):
   - **Momentum:** 12-1 month return (skip last)
   - **Value:** book-to-market
   - **Quality:** ROE (TTM)
   - **Low-volatility:** 60-day realized vol, sign-flipped
   - **Size:** log market cap, sign-flipped
3. Z-scores cross-sectionally per month. Builds long-short decile portfolios. Computes equal-weighted forward 1-month returns.
4. Reports per-factor: annualized return, Sharpe, max DD, hit rate, turnover.
5. Logs full run to MLflow with all params, metrics, plots, lineage hash.

### Hard checks (CI runs these)
- [ ] Notebook executes top-to-bottom in <10 minutes on standard kernel.
- [ ] No NaN feature values for "live" universe members (>99.5% coverage).
- [ ] **PIT regression:** re-run after inserting 1000 synthetic future rows — Sharpe values identical to ≤1e-9.
- [ ] **Time-travel regression:** re-run with `simulated_clock(2020-01-01)` — Sharpe values for 2015–2019 sub-window match.
- [ ] **Survivorship check:** ≥1 month-end set contains a name later delisted.
- [ ] MLflow run contains `data_lineage_hash`, `universe_snapshot_hash`, `feature_hash_map`.
- [ ] Re-running with same pinned hashes produces bitwise-identical PnL.

### Operational exit
- [ ] JupyterHub URL accessible; OAuth working.
- [ ] Read-only DB role enforced.
- [ ] MLflow URL accessible; runs visible and artifacts downloadable.
- [ ] New researcher can clone repo, register feature, run backfill, retrieve values from notebook in <1 hour.
- [ ] Backfill of one new feature across 10-year window completes in <30 minutes.

---

## 13. Risks & Open Questions

### Risk: Restated fundamentals — sourcing
We need a vendor that provides `as_first_reported` AND `as_currently_reported`. Compustat PIT, Shardar, S&P CapIQ all do; Yahoo and Alpha Vantage do not.
**Mitigation:** budget for Sharadar SF1. Without it, fundamentals features marked `pit_quality='best_effort'`.

### Risk: Late-arriving alternative data (foreshadows Phase 5)
Sentiment lag is highly variable.
**Mitigation:** hard-codify in Phase 5 review: `knowledge_ts = ingestion_completed_ts + safety_lag`, never `event_ts`.

### Risk: Vendor restatements that aren't flagged
Some vendors silently restate without revision history.
**Mitigation:** ingestion contract — write new `(event_ts, knowledge_ts)` rows on every full reload, never UPDATE.

### Risk: Universe completeness
S&P 500 historical well-published. Russell 2000 messier. Crypto DIY.
**Mitigation:** Phase 2 ships only `sp500` and `crsp_us_total`. Russell and crypto deferred to Phase 3 if needed.

### Risk: Definition-hash bloat
Every minor refactor changes hash and triggers backfill.
**Mitigation:** DSL canonicalizes SQL before hashing.

### Risk: Read-only role circumvention
**Mitigation:** REVOKE `pg_execute_server_program`, audit `SECURITY DEFINER` functions, run pgaudit. Treat as public-facing interface.

### Risk: Time-zone handling at boundaries
**Mitigation:** market calendar service from Phase 1 is source of truth; DSL has `session` parameter.

### Open question: tick-level features in Phase 2?
Plan says no. Forward-compatible storage shape (`event_ns` extension).

### Open question: CAGGs vs explicit features for OHLCV rollups
**Recommendation:** depend on them. CAGGs have known refresh windows; DSL respects via `knowledge_lag`.

### Open question: How many researchers in year 1?
If >5, multi-tenant story needs more design.

---

## Sequencing & Estimated Effort

| Week | Eng A (storage/PIT) | Eng B (sandbox/orchestration) |
|---|---|---|
| 1 | Feature table shape + universe schema + migration patterns; PIT primitive; Level 1+2 tests | JupyterHub local k3d; MLflow server; kernel image MVP |
| 2 | DSL skeleton; canonical feature (`momentum_20d`) end-to-end; Prefect flow | Read-only role + pgbouncer; S3 contents for notebooks; MLflow wrapper; quickstart doc |
| 3 | 4 more features; universe historical load; Level 3+4+5 tests | Exit notebook; CI gates; JupyterHub on real cluster (or docker-compose if cluster slips); risk review |

Solo run: 5–6 weeks. Plan robust to dropping JupyterHub-on-k8s to docker-compose Jupyter for Phase 2.

---

## Critical Files for Implementation

- `/Users/mukesh/python-projects/Astraeus/libs/features/` — DSL, retrieval client, registry
- `/Users/mukesh/python-projects/Astraeus/libs/universe/` — universe and security-master client
- `/Users/mukesh/python-projects/Astraeus/infra/jupyterhub/` — helm values, kernel Dockerfile, S3 contents config, OAuth setup
- `/Users/mukesh/python-projects/Astraeus/infra/mlflow/` — server deployment, Postgres backend, MinIO bucket policy
- `/Users/mukesh/python-projects/Astraeus/apps/workers/prefect/flows/materialize.py` — backfill engine entrypoint

---

## Scope Mode: 2-Year Resume + Self-Sustaining Trading

**Key adjustments**

- **Notebook environment:** plain JupyterLab in `docker-compose`, not JupyterHub. JupyterHub is multi-user infra; you're the only user. Configure it as a docker service that mounts a project directory and uses a read-only DB role — the *pattern* matches institutional setups; the user count doesn't.
- **MLflow:** self-hosted on the same docker-compose, backed by local Postgres + MinIO. No managed MLflow.
- **Backfill universe:** retarget the 30-minute-for-3,500-names exit criterion to "10 minutes for the ~150-name universe defined in Phase 1 (scope mode)." The bound that matters is *fast enough to iterate*, not the absolute count.
- **Feature DSL + PIT semantics:** stay 100% as planned. This is the most resume-load-bearing piece of Phase 2 — interviewers will ask about point-in-time correctness, and the answer needs to match what's in the repo.
- **Survivorship-bias universe tables:** stay as planned.

**What stays (resume-load-bearing)**

- Feature definitions as code, offline + online retrieval parity, lineage propagation from Phase 1, backfill engine as a Prefect flow, MLflow experiment tracking. These are the talking points; keep them.

**Budget impact:** $0/mo additional.
