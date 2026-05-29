# Runbook: Schema Drift Detected

## Trigger

- Alert: `md_dlq_depth{source=*} > 0` for 5 minutes
- DLQ entries with `error_type: ValidationError` or `KeyError`
- Karapace schema registry rejects a new schema version

## Impact

- New data from the affected source cannot be ingested
- Existing data is unaffected (immutable once written)
- Downstream consumers continue reading historical data normally
- DLQ accumulates failed records for later replay

## Diagnosis

1. Identify the affected source and error:
   ```bash
   curl http://localhost:8000/md/dlq | jq '.[] | {source, error_type, error_message}'
   ```

2. Check the raw response that caused the failure:
   ```bash
   # Find the most recent archived response
   mc ls local/astraeus-raw-responses/<source>/$(date +%Y/%m/%d)/
   # Download and inspect
   mc cat local/astraeus-raw-responses/<source>/2024/01/15/<run_id>/AAPL.json.gz | gunzip | jq .
   ```

3. Compare against the expected schema:
   ```bash
   # Check registered schema
   curl http://localhost:8081/subjects/md.equity.daily.v1-value/versions/latest | jq .
   ```

4. Check adapter logs for parsing errors:
   ```bash
   docker compose logs workers 2>&1 | grep -i "parse\|schema\|validation"
   ```

## Resolution

### Case 1: Source added a new field (additive change)

This is the most common case. Sources add optional fields without warning.

1. **No action needed** — our parsers use `.get()` with defaults.
2. Verify the DLQ entries are actually from a different issue.
3. If the new field is useful, update the adapter to capture it.

### Case 2: Source renamed or removed a field (breaking change)

1. **Stop the affected adapter** to prevent DLQ flooding:
   ```bash
   # If running as a separate pod, scale to 0
   # If in workers service, set feature flag to disable
   ```

2. **Inspect the new format** from archived raw responses.

3. **Update the adapter parser**:
   ```python
   # In libs/marketdata/astraeus_marketdata/adapters/<source>.py
   # Update the field mapping in the parsing logic
   ```

4. **Test with recorded fixtures**:
   ```bash
   # Save the new response format as a test fixture
   # Run adapter unit tests
   uv run pytest libs/marketdata/tests/unit/ -k <source>
   ```

5. **Replay failed records from DLQ**:
   ```bash
   # After fixing the parser, replay the DLQ entries
   # The outbox relay will re-publish them
   ```

### Case 3: Schema registry rejects a new version

If we're publishing a new schema version that Karapace rejects:

1. Check compatibility mode:
   ```bash
   curl http://localhost:8081/config | jq .
   # Should be: {"compatibilityLevel": "BACKWARD"}
   ```

2. Test compatibility before registering:
   ```bash
   curl -X POST http://localhost:8081/compatibility/subjects/<topic>-value/versions/latest \
       -H "Content-Type: application/json" \
       -d '{"schema": "<new_schema_json>"}'
   ```

3. If the change is intentionally breaking:
   - Create a new topic version: `md.equity.daily.v2`
   - Register the new schema on the new topic
   - Update producers and consumers to use the new topic
   - Keep the old topic alive until all consumers migrate

## Recovery

1. **Verify no data loss** — all failed records should be in the DLQ:
   ```bash
   curl "http://localhost:8000/md/dlq?source=<source>" | jq 'length'
   ```

2. **Replay from DLQ** after the fix is deployed:
   ```sql
   -- Check DLQ outbox entries
   SELECT count(*) FROM outbox WHERE topic = 'md.dlq.v1' AND published_at IS NOT NULL;
   ```

3. **Run gap detection** to find any missing data:
   ```bash
   curl "http://localhost:8000/md/gaps"
   ```

4. **Backfill gaps** if any:
   ```bash
   uv run python scripts/md-backfill.py --source <source> \
       --symbols <affected_symbols> --start <gap_start> --end <gap_end>
   ```

## Prevention

- Pin adapter tests to recorded vendor responses (golden fixtures)
- Monitor vendor changelogs and status pages
- Schema registry BACKWARD compatibility prevents accidental breaks
- Raw response archival in MinIO means we can always replay with a fixed parser

## Escalation

- If multiple sources drift simultaneously: likely a shared dependency issue
- If schema registry is down: adapters continue working (validation is optional)
- If data corruption from bad parsing: full replay from MinIO archive
