# Runbook: Broker Disconnect

## Trigger
- `broker_disconnect_total` counter increments
- Reconciliation worker fails to fetch broker state
- Order submission returns connection error

## Impact
- New orders cannot be submitted
- Existing orders may fill without local state update
- Position drift accumulates until reconnection

## Steps

### 1. Assess Scope
- Check which broker is disconnected (Alpaca / IBKR)
- Check if it's a network issue or broker-side outage
- Check broker status page (status.alpaca.markets / ibkr.com/status)

### 2. Immediate Actions
- Kill switch is NOT automatically armed on disconnect (orders already in-flight are fine)
- If disconnect persists > 30s, manually arm kill switch for affected accounts:
  ```
  POST /killswitch/account:{account_id}/arm
  {"armed_by": "operator", "reason": "broker disconnect > 30s"}
  ```

### 3. Monitor Reconciliation
- Once connection restores, reconciliation worker will detect any drift
- If drift > 0, kill switch is auto-armed by recon worker
- Review drifts: `GET /recon/drift?since=<disconnect_time>`

### 4. Resolution
- Resolve each drift manually (compare broker state vs local)
- Mark drifts as resolved in DB
- Disarm kill switch:
  ```
  POST /killswitch/account:{account_id}/disarm
  {"armed_by": "operator", "reason": "drift resolved after reconnection"}
  ```

### 5. Post-Incident
- Log the disconnect duration and any drifts found
- If drifts were found, investigate root cause (missed fills, phantom orders)
- Update monitoring thresholds if needed

## Escalation
- If disconnect > 5 minutes: escalate to on-call
- If drift involves real money: freeze all trading, manual reconciliation required
