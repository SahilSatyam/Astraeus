# Runbook: Reconciliation Drift

## Trigger
- `recon_drift_open_count` gauge > 0
- Reconciliation worker auto-arms kill switch for affected account
- Alert fires on drift detection

## Impact
- New order submissions paused for affected account
- Local state does not match broker state
- Potential for incorrect position tracking / PnL calculation

## Types of Drift

### Position Drift
- Local position qty differs from broker-reported qty
- Causes: missed fill, phantom fill, manual broker-side adjustment

### Order Drift
- Order exists in broker but not locally (or vice versa)
- Causes: missed submission ack, broker-side cancel, network partition during submit

## Steps

### 1. Identify the Drift
```
GET /recon/drift?since=<time>
```
Review each drift entry: `kind`, `local_repr`, `broker_repr`

### 2. Determine Root Cause

**Position drift (broker has more):**
- Check if a fill was missed: query broker fills since last known fill
- If fill found: replay it into OMS via `apply_fill`

**Position drift (local has more):**
- Check if a cancel was missed: query broker order status
- If order was cancelled/rejected at broker: update local state

**Order drift (broker has, local doesn't):**
- Likely a submission that succeeded but ack was lost
- Query broker order by client_order_id to correlate

**Order drift (local has, broker doesn't):**
- Order may have been filled/cancelled at broker
- Query broker for final state and replay events

### 3. Remediate
- For each drift, apply the corrective action (replay fill, update state)
- Mark drift as resolved:
  ```sql
  UPDATE reconciliation_diff
  SET resolved_at = now(), resolution = '<description>'
  WHERE diff_id = '<id>';
  ```

### 4. Verify & Resume
- Run one more reconciliation cycle manually
- Confirm `recon_drift_open_count` = 0
- Disarm kill switch:
  ```
  POST /killswitch/account:{account_id}/disarm
  {"armed_by": "operator", "reason": "drift resolved"}
  ```

### 5. Post-Incident
- Document the drift in trade journal
- If drift was caused by a bug, file an issue
- If drift was caused by network, review retry/timeout settings

## Prevention
- 5-second reconciliation cadence catches drift early
- Idempotent client_order_id prevents duplicate orders
- Event sourcing allows state reconstruction from events
