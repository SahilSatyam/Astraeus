## Streaming Optimization (Astraeus Monorepo)

-   **Optimization implemented:** Resolved N+1 lookup during idempotency checks when saving streamed `MarketBarRaw` data by switching to a batched `INSERT ... ON CONFLICT DO NOTHING RETURNING` statement.
-   **Why:** Eliminates individual database `select` queries on a hot path, batching network operations into a single execution.
-   **Measured Performance Improvment:** N+1 queries drop from N+1 database roundtrips to exactly 1 bulk UPSERT query per batch. We also properly ensured we only issue Outbox entries for records actually inserted by taking advantage of the `RETURNING` properties.
