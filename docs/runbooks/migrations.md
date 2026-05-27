# Migrations Runbook

Astraeus uses Alembic on top of SQLAlchemy 2.0 async. Migrations are
**reversible by default** until a forward-only policy is adopted in Phase 10.

## Adding a new migration

1. Write or modify the SQLAlchemy model under `libs/db/astraeus_db/`.
2. Generate the migration:

   ```bash
   make revision MSG="add foo column to bars"
   ```

3. **Review the generated SQL.** Alembic autogenerate misses constraints,
   index types, and Timescale-specific DDL. Hand-edit as needed.
4. Implement `downgrade()`. If a migration is genuinely forward-only, raise
   `NotImplementedError` and document why in the migration's docstring.
5. Apply locally and verify the round-trip:

   ```bash
   make migrate
   make downgrade
   make migrate
   ```

## Conventions

- **Filename**: `YYYYMMDDHHMM_short_slug.py`. Configured via `file_template`.
- **One change per migration**. Index changes ship in a separate migration
  from column changes so they can be rolled back independently.
- **No data migrations in Alembic.** Data backfills go in
  `scripts/migrations_data/` and run as one-shot jobs. Alembic is DDL-only.
- **Large tables**: any migration touching tables larger than 10M rows must
  consider lock behavior. Use `CREATE INDEX CONCURRENTLY` (Postgres) and
  consider chunked backfills.
- **Server defaults** for new NOT NULL columns: provide a default that the
  DB can apply without a full table rewrite.
- **Naming**: column types `TIMESTAMPTZ` (never naked `TIMESTAMP`) — see
  Phase 1 PIT discipline.

## Where DSN comes from

Alembic does **not** read `sqlalchemy.url` from `alembic.ini`. The DSN is
loaded from `astraeus_config.DatabaseSettings` in
`libs/db/astraeus_db/migrations/env.py`. To run migrations against a
non-default database, override env vars:

```bash
ASTRAEUS_DB__NAME=astraeus_research \
  cd libs/db && uv run alembic upgrade head
```

## Production-time migrations

Phase 10 will lock down forward-only migrations behind a CI policy and
require a checklist for any DDL touching a table > 10M rows. Until then,
keep `downgrade()` honest.
