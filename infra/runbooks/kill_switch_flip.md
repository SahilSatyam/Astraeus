# Runbook: Kill Switch Flip

## Trigger
- Manual operator action (planned maintenance, risk event)
- Automatic: reconciliation drift detected
- Automatic: circuit breaker PnL threshold breached
- Automatic: system health degradation

## Scopes
- `global` — halts ALL order submissions across all accounts/strategies
- `account:{id}` — halts submissions for a specific trading account
- `strategy:{id}` — halts submissions for a specific strategy

## Arming a Kill Switch

### Via API
```
POST /killswitch/{scope}/arm
{
  "armed_by": "operator",
  "reason": "planned maintenance window"
}
```

### Verification
- Check propagation: all OMS instances should reject new orders within 1 second
- Test with a dummy order submission — should return HTTP 423

### What Happens When Armed
1. OMS checks kill switch state before every order submission
2. If any relevant scope is armed, submission is rejected with HTTP 423
3. Existing in-flight orders are NOT cancelled (they continue their lifecycle)
4. Reconciliation worker continues running (monitoring doesn't stop)

## Disarming a Kill Switch

### Pre-Conditions
- Root cause of the arm event is resolved
- If armed by recon: all drifts resolved (`recon_drift_open_count` = 0)
- If armed by circuit breaker: PnL recovered above threshold

### Via API
```
POST /killswitch/{scope}/disarm
{
  "armed_by": "operator",
  "reason": "maintenance complete, all clear"
}
```

### Post-Disarm
- Verify order submission works (test with paper order)
- Monitor for 5 minutes to ensure no immediate re-arm

## Emergency: Global Kill Switch
For catastrophic scenarios (runaway algorithm, market flash crash):

```
POST /killswitch/global/arm
{
  "armed_by": "emergency",
  "reason": "EMERGENCY: <description>"
}
```

This is the nuclear option. All trading stops immediately. Resume only after thorough investigation.

## Audit Trail
Every kill switch flip is recorded in the trade journal:
- `kind: kill_switch_flip`
- `payload: {scope, action, armed_by, reason}`

Query audit trail:
```sql
SELECT * FROM trade_journal
WHERE kind = 'kill_switch_flip'
ORDER BY written_at DESC;
```

## SLA
- Propagation time: < 1 second from arm to rejection of new orders
- Monitored via `kill_switch_propagation_seconds` histogram
