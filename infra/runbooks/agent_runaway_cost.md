# Runbook: Agent Runaway Cost

**SLO:** Per-agent daily cost within budget threshold

## Symptom
- `AgentCostBudgetExceeded` alert fires
- Daily cost report shows unexpected spike for a specific agent
- LLM API billing dashboard shows anomalous usage

## Severity
- **P2** — financial impact, not system stability
- **P1** if cost exceeds 10x daily budget (possible infinite loop)

## Immediate Stabilization

1. **Identify the runaway agent:**
   ```bash
   # Check cost tracking metrics
   curl -s http://prometheus:9090/api/v1/query?query=agent_cost_total | jq '.data.result | sort_by(.value[1]) | reverse | .[0:5]'
   ```

2. **Kill the agent process:**
   ```bash
   # If running as a k8s job/pod
   kubectl get pods -n agents -l agent=<agent_name> --sort-by=.metadata.creationTimestamp
   kubectl delete pod -n agents <runaway-pod>
   ```

3. **Disable the agent temporarily:**
   ```bash
   # Scale to zero
   kubectl scale deployment/<agent-deployment> -n agents --replicas=0
   ```

## Diagnosis

1. **Check what triggered the spike:**
   ```bash
   # Review agent logs for the time window
   kubectl logs -n agents -l agent=<agent_name> --since=1h | grep -i "prompt\|completion\|tokens"
   ```

2. **Common causes:**
   - Infinite retry loop on a failing LLM call
   - Prompt that triggers excessively long completions
   - Missing max_tokens limit on API call
   - Agent stuck in a reasoning loop (tool-use cycle)

3. **Check token counts:**
   ```bash
   # Query token usage metrics
   curl -s "http://prometheus:9090/api/v1/query?query=agent_tokens_total{agent='<name>'}" | jq .
   ```

## Recovery

1. **Fix the root cause** (usually a code change):
   - Add/reduce max_tokens
   - Add circuit breaker on retry count
   - Fix the prompt that causes loops

2. **Re-enable with safeguards:**
   ```bash
   kubectl scale deployment/<agent-deployment> -n agents --replicas=1
   ```

3. **Monitor for 30 minutes** to confirm cost is back to normal.

## Prevention
- Every agent call must have a `max_tokens` limit
- Per-agent daily budget hard cap in the orchestrator
- Circuit breaker: if an agent exceeds N calls in M minutes, pause and alert
- Weekly cost review with per-agent breakdown

## Escalation
- If cost > $50 in a single day: immediate kill, post-incident review
- If Anthropic/OpenAI rate-limits the account: check if other agents are affected
