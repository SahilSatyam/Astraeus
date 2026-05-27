# Phase 8 — Live Trading Infrastructure

**Timeline:** Weeks 26–32 · **Depends on:** Phases 1–7 · **Blocks:** Phase 10

---

## 1. Phase Goals & Refined Exit Criteria

This is the safety-critical phase. Every other phase can produce wrong-but-recoverable output; this one can produce *unrecoverable* output — a duplicated order, a silently-failed cancel, a runaway algorithm. The mission: a paper-trading-first execution stack that satisfies institutional standards on idempotency, reconciliation, and architectural isolation between LLMs and brokers.

**Architectural inviolable rule:** there is no code path from any agent (Phase 6) to any broker SDK. The Phase 6 Execution agent writes to a `recommendation` row that requires HITL approval (Phase 7) before reaching the OMS. The OMS itself has no LLM imports. This is not a policy; it's a wiring decision verified at CI by an import-graph audit.

Refined exit criteria:

- **Two-week paper trading run** with zero reconciliation drift on Alpaca paper.
- **State machine completeness**: every order traverses `NEW → PENDING_NEW → SUBMITTED → (PARTIAL → ) FILLED | CANCELLED | REJECTED | EXPIRED` and never leaks state across restarts.
- **Idempotency proven**: chaos test that double-submits orders under network partition produces exactly one broker order per `client_order_id`.
- **Kill switches functional** at user, strategy, and global level; flipping the global kill switch halts all in-flight algos within 1 second.
- **Reconciliation cadence**: 5-second reconciliation against broker; any drift > 0 generates an alert and pauses new submissions.
- **Pre-trade risk hooks**: all four risk controls (daily loss, exposure, position limit, AI-confidence threshold) enforced.
- **Trade journal append-only**: zero gaps in journal sequence numbers; every state transition recorded.

---

## 2. Scope Boundaries

| In | Out |
|---|---|
| Alpaca paper → Alpaca live → IBKR | Binance live (scaffold + paper only this phase) |
| Equities | Options, futures execution |
| Time-in-force: DAY, GTC | OCO, brackets (defer) |
| Smart-order-routing-lite (single venue per symbol) | Multi-venue routing |
| Pre-trade risk gateway | TCA dashboards (basic only) |
| Reconciliation worker | High-frequency strategies |

We will *not* attempt to compete with FIX-tuned HFT systems. The latency budget is "good enough for daily-bar strategies and minute-bar strategies", not microseconds.

---

## 3. Week-by-Week Breakdown

### Week 26 — Schemas + Alpaca Paper Adapter
- Order/Fill/Position schema; outbox pattern (mirror Phase 1).
- Alpaca paper adapter; smoke-test order lifecycle.
- Idempotency key format pinned: `client_order_id = sha256(strategy_id || rec_id || decision_id || retry_n)`.

### Week 27 — OMS State Machine
- OMS service with explicit state machine; persisted state.
- Order/event sourcing on top of `order_event` append log.
- Snapshot rebuild from event log proven.

### Week 28 — Pre-Trade Risk Gateway
- Risk pre-trade hooks: daily loss limit, max exposure, position limit, AI-confidence threshold.
- Each rule independently bypassable via override token (audit-logged).

### Week 29 — Reconciliation + Trade Journal
- Reconciliation worker (5s cadence): broker → local; diff alerts.
- Trade journal (append-only, no UPDATE/DELETE), gapless sequence number, per-account.
- Drift remediation runbook.

### Week 30 — Kill Switches + Circuit Breakers
- Global, strategy, user kill switch with sub-second propagation (Redis pub/sub + in-process flag).
- PnL drawdown circuit breaker (auto-flatten).
- Volatility halt awareness (read from broker; halt new orders).

### Week 31 — IBKR Adapter + Live Promotion Drill
- IBKR adapter via ib_insync (TWS/Gateway); same OMS interface.
- Promotion checklist for paper → live.
- Architectural audit: confirm no LLM/agent → broker import path.

### Week 32 — Two-Week Soak Test + Hardening
- Run paper trading autonomously, measure drift = 0.
- Chaos drills: broker disconnect, partition, kill-switch flip, reconciliation drift.
- Final runbook pass.

---

## 4. Component & Service Architecture

```
       ┌─────────────────────────────────────────────────────────────┐
       │                  HITL Approval (from Phase 7)               │
       └─────────────────────────────┬───────────────────────────────┘
                                     │ approved recommendations
                                     ▼
                          ┌────────────────────────┐
                          │   Pre-Trade Risk       │
                          │   Gateway              │
                          └──────────┬─────────────┘
                                     │ pass / reject
                                     ▼
                          ┌────────────────────────┐
                          │        OMS             │
                          │  (state machine,       │
                          │   event-sourced)       │
                          └──────────┬─────────────┘
                                     │ broker-neutral order
                                     ▼
                          ┌────────────────────────┐
                          │        EMS             │
                          │  (broker adapters,     │
                          │   smart routing)       │
                          └──────────┬─────────────┘
                ┌────────────────────┼────────────────────┐
                ▼                    ▼                    ▼
         ┌──────────┐         ┌──────────┐         ┌──────────┐
         │  Alpaca  │         │   IBKR   │         │ Binance  │
         │  paper/  │         │ (TWS/IBG)│         │  paper   │
         │  live    │         │          │         │          │
         └──────────┘         └──────────┘         └──────────┘

         ┌──────────────────────┐    ┌─────────────────────────┐
         │ Reconciliation       │    │ Trade Journal           │
         │ Worker (5s)          │    │ (append-only)           │
         └──────────────────────┘    └─────────────────────────┘
         ┌──────────────────────┐    ┌─────────────────────────┐
         │ Kill Switch Service  │    │ Position Service        │
         │ (Redis pub/sub)      │    │ (snapshot + delta)      │
         └──────────────────────┘    └─────────────────────────┘
```

---

## 5. Folder & File Structure

```
apps/
├─ oms/                     # state machine, event log
├─ ems/                     # broker adapters + routing
├─ risk-gateway/            # pre-trade hooks
├─ recon-worker/            # 5s reconciliation
├─ kill-switch-service/
└─ position-service/
libs/
├─ trading/
│  ├─ statemachine.py       # explicit ENUM states + transitions
│  ├─ idempotency.py        # client_order_id derivation
│  ├─ events.py             # OrderEvent schemas
│  └─ journal.py            # append-only writer
├─ brokers/
│  ├─ base.py               # BrokerAdapter ABC
│  ├─ alpaca.py
│  ├─ ibkr.py
│  └─ binance.py            # paper-only this phase
└─ risk/
   ├─ pre_trade.py
   └─ circuit_breaker.py
infra/
└─ runbooks/
   ├─ broker_disconnect.md
   ├─ recon_drift.md
   └─ kill_switch_flip.md
```

CI rule: `apps/oms/**` and `libs/brokers/**` cannot import from `libs/agents/**`. Enforced via an import-graph linter.

---

## 6. Data Model / Schema Changes

```sql
CREATE TABLE order_t (                              -- "order" is reserved
    order_id          UUID PRIMARY KEY,
    client_order_id   TEXT NOT NULL UNIQUE,         -- idempotency key
    account_id        TEXT NOT NULL,
    strategy_id       TEXT NOT NULL,
    rec_id            UUID,                         -- Phase 7 recommendation
    decision_id       UUID,                         -- Phase 7 decision
    symbol            TEXT NOT NULL,
    side              TEXT NOT NULL CHECK (side IN ('buy','sell')),
    qty               NUMERIC(20,8) NOT NULL,
    order_type        TEXT NOT NULL,                -- market, limit
    limit_price       NUMERIC(20,8),
    tif               TEXT NOT NULL DEFAULT 'DAY',
    state             TEXT NOT NULL,                -- mirrored from latest event
    submitted_to      TEXT NOT NULL,                -- broker name
    broker_order_id   TEXT,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE order_event (                          -- append-only
    event_seq         BIGSERIAL PRIMARY KEY,
    order_id          UUID NOT NULL REFERENCES order_t,
    event_type        TEXT NOT NULL,                -- new, submitted, partial_fill, filled, cancelled, rejected, expired
    payload           JSONB NOT NULL,
    occurred_at       TIMESTAMPTZ NOT NULL,
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    source            TEXT NOT NULL                 -- oms | broker | recon
);
CREATE INDEX ON order_event (order_id, event_seq);

CREATE TABLE fill (
    fill_id           UUID PRIMARY KEY,
    order_id          UUID NOT NULL REFERENCES order_t,
    qty               NUMERIC(20,8) NOT NULL,
    price             NUMERIC(20,8) NOT NULL,
    fees              NUMERIC(20,8) NOT NULL DEFAULT 0,
    venue             TEXT,
    broker_fill_id    TEXT,
    occurred_at       TIMESTAMPTZ NOT NULL,
    received_at       TIMESTAMPTZ DEFAULT now(),
    UNIQUE (order_id, broker_fill_id)
);

CREATE TABLE position (
    account_id   TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    qty          NUMERIC(20,8) NOT NULL,
    avg_cost     NUMERIC(20,8) NOT NULL,
    updated_at   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (account_id, symbol)
);

CREATE TABLE reconciliation_diff (
    diff_id       UUID PRIMARY KEY,
    account_id    TEXT NOT NULL,
    kind          TEXT NOT NULL,                    -- order|position|cash
    local_repr    JSONB,
    broker_repr   JSONB,
    detected_at   TIMESTAMPTZ DEFAULT now(),
    resolved_at   TIMESTAMPTZ,
    resolution    TEXT
);

CREATE TABLE kill_switch_state (
    scope    TEXT PRIMARY KEY,                      -- global | account:<id> | strategy:<id>
    armed    BOOLEAN NOT NULL DEFAULT false,
    armed_by TEXT,
    armed_at TIMESTAMPTZ,
    reason   TEXT
);

CREATE TABLE trade_journal (                        -- append-only audit log
    seq        BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    kind       TEXT NOT NULL,                       -- order_state, fill, override, kill_switch_flip
    payload    JSONB NOT NULL,
    written_at TIMESTAMPTZ DEFAULT now()
);
-- Enforce append-only via permission and trigger
REVOKE UPDATE, DELETE ON trade_journal FROM PUBLIC;
```

---

## 7. API Surface

```
POST /oms/orders                # submit (idempotent)
POST /oms/orders/{id}/cancel
POST /oms/orders/{id}/replace
GET  /oms/orders/{id}
GET  /oms/orders?account_id=&strategy_id=&from=&to=
GET  /position/{account_id}
GET  /position/{account_id}/{symbol}
GET  /recon/drift?since=
POST /killswitch/{scope}/arm
POST /killswitch/{scope}/disarm
```

`POST /oms/orders` request:
```json
{
  "client_order_id": "sha256...",
  "account_id": "alpaca-paper-1",
  "strategy_id": "momentum_xs",
  "rec_id": "uuid",
  "decision_id": "uuid",
  "symbol": "AAPL",
  "side": "buy",
  "qty": "100",
  "order_type": "market",
  "tif": "DAY"
}
```

Submitting twice with the same `client_order_id` returns the existing order, not a duplicate.

---

## 8. External Dependencies

| Broker | SDK / Protocol | Notes |
|---|---|---|
| Alpaca | alpaca-py | REST + WS |
| IBKR | ib_insync over TWS / IB Gateway | Latency higher; gateway must run on dedicated container |
| Binance | python-binance | Paper trading only this phase; live deferred |

Secrets in Vault: `astraeus/trading/<broker>/<account>`. Credentials per environment; production live keys gated behind a separate Vault role with break-glass approval.

---

## 9. Key Technical Decisions & Tradeoffs

**Event sourcing for orders.** The order's state is the fold of its events. Reconstructing state from `order_event` is always possible, which is the only way to recover from process crashes mid-transition. The cost is more complex querying; we mitigate with the `order_t` projection that's eventually consistent with the event log.

**Idempotency via deterministic client_order_id.** Most retail bugs are duplicate orders after a network blip + retry. The fix: every submission carries a deterministic `client_order_id` derived from inputs. Brokers honor this (Alpaca + IBKR both); the OMS rejects same-key resubmits before reaching the broker.

**OMS/EMS separation.** OMS owns lifecycle and state; EMS owns broker-specific quirks. The boundary is a `BrokerOrder` Pydantic message, not a Python interface call. This lets us replace IBKR with a different broker without touching OMS code.

**Reconciliation every 5s, not every minute.** 60s drift can cost five figures. 5s is the empirically defensible cadence for daily-bar strategies; HFT would do tens of milliseconds. Reconciliation that finds drift > 0 immediately *pauses new submissions* until cleared.

**Kill switch on Redis pub/sub + in-process flag.** Redis pub/sub propagates the flip; every order-emitting code path reads an in-process flag in the hot path (no DB call per order). The hot-path cost is one cache lookup; the propagation cost is one Redis publish. Sub-second end-to-end.

**Architectural enforcement of LLM-broker isolation.** Three layers:
1. Phase 6 Execution agent's tool allowlist contains no broker tool.
2. Code organization: `libs/agents` cannot import from `apps/oms` or `libs/brokers`.
3. CI gate runs an import-graph audit on every PR.

This is what makes the platform regulator-defensible.

**Time-in-force defaults to DAY.** GTC is dangerous; we require explicit opt-in. No order ever goes out as "any time, any place" by default.

**Replace = cancel + new, not in-place modify.** Easier to reason about, easier to audit. Slightly higher round-trip cost — acceptable.

**Currency / FX.** All internal accounting in USD this phase. Crypto live deferred precisely because FX semantics need their own thinking.

---

## 10. Risks, Failure Modes & Mitigations

| Risk | Mitigation |
|---|---|
| Duplicate orders | Idempotent `client_order_id`; OMS dedup before broker call |
| Lost fill (broker delivered, we missed) | 5s reconciliation; order_event from recon source replays into state machine |
| Broker disconnect during cancel | Cancel becomes pending; reconciliation resolves true broker state; UI flagged |
| Partial fill race | State machine handles `PARTIAL` explicitly; remaining qty tracked |
| Kill-switch flip fails silently | Health-check on flag propagation; alert if any worker reads stale flag > 5s after flip |
| Runaway algorithm | Per-strategy throttle (max orders/min); circuit breaker on PnL; global kill switch |
| AI agent connecting to broker | Architectural enforcement (Section 9); CI gate; periodic audit |
| Compliance / surveillance gaps | Append-only journal; per-decision rationale; surveillance hooks reserved |
| Clock skew | NTP discipline; all timestamps UTC; broker timestamps preserved in payload |
| Regulatory: best execution | TCA reports per fill; deferred deeper analysis |
| Live promotion accident | Paper accounts and live accounts in different Vault roles; UI confirmation step; production "live" mode requires a separate runtime flag |

---

## 11. Testing Strategy

**Idempotency chaos test.** ToxiProxy injects packet loss; submit 1000 orders with retries; assert exactly N broker orders for N unique `client_order_id`s.

**State machine completeness.** Property test: random sequence of events; assert state transitions only follow allowed edges.

**Reconciliation drift simulation.** Inject a phantom broker order in the broker adapter mock; assert recon detects within 5s, alerts, pauses submissions.

**Kill-switch propagation test.** Flip global kill; assert all in-flight algorithm processes pause new submissions within 1 second.

**Replay tests.** Replay `order_event` for an order; reconstruct projection; assert match against snapshot.

**Architectural audit (CI).** `import-linter` config asserts `libs.agents`, `libs.recommender.stages.thesis` cannot import broker modules.

**End-to-end paper trading soak.** Two weeks autonomous; measure drift = 0; collect metrics on order acceptance, fill latency, recon cadence.

---

## 12. Observability Hooks

| Signal | Type | Notes |
|---|---|---|
| `oms_order_latency_ms{state_transition}` | histogram | per transition |
| `oms_idempotency_dedup_total` | counter | should rise on retries, never spike |
| `oms_state_machine_violations_total` | counter | must be 0 |
| `recon_drift_open_count` | gauge | alert if > 0 |
| `recon_drift_resolution_seconds` | histogram | p99 target < 60s |
| `kill_switch_propagation_seconds` | histogram | < 1s p99 |
| `pretrade_rejection_total{rule}` | counter | per rule |
| `fill_slippage_bps{strategy}` | histogram | sliced by venue |
| `broker_disconnect_total{broker}` | counter | alert |
| `journal_seq_gap_total` | counter | must be 0 |

---

## 13. Definition of Done

- [ ] Two-week Alpaca paper soak: zero recon drift events.
- [ ] Idempotency chaos: exactly one broker order per `client_order_id` despite retries.
- [ ] Kill switch verified across all algorithm processes (sub-1s).
- [ ] All four pre-trade risk hooks enforced and tested.
- [ ] Architectural audit (CI) green on every PR.
- [ ] State machine property tests green.
- [ ] IBKR adapter passes the same lifecycle tests as Alpaca.
- [ ] Trade journal append-only verified; UPDATE/DELETE on `trade_journal` denied at DB level.
- [ ] Live-promotion runbook reviewed and signed.
- [ ] Reconciliation runbook drilled with a synthetic drift.

---

## 14. Interview Talking Points

- **Idempotency under network failure is the #1 retail trading bug.** Deterministic `client_order_id` + broker-side honoring is the answer.
- **OMS/EMS separation lets us swap brokers.** Discuss the test that proves it (running the same lifecycle test suite on every adapter).
- **Architectural isolation between LLMs and brokers.** Three-layer enforcement (allowlist, import discipline, CI). This is the regulator-defensible posture.
- **Reconciliation as continuous truth maintenance.** 5s cadence; drift pauses submissions automatically. Most retail systems reconcile end-of-day.
- **Trade journal is append-only at the DB level.** Permission revocation prevents updates/deletes; auditable by construction.
- **Kill switches at three levels.** Global, account, strategy. Sub-second propagation via Redis pub/sub + in-process flag.
- **Why we don't claim exactly-once with brokers.** Deterministic idempotency keys + at-least-once submission + broker-honored dedup = effectively-once. Honest framing.

---

## 15. Open Questions

1. Live trading promotion — do we want a separate physical environment or just separate Vault roles? Lean separate roles + runtime flag now, separate environment when scale requires.
2. TCA depth — basic slippage tracking only, or analyst-grade decomposition (delay, market impact, opportunity)? Start basic.
3. IBKR via FIX vs ib_insync — FIX is heavier ops; ib_insync good enough for MVP.
4. Crypto live — when? Probably out of phase scope; revisit after equities are stable.
5. Surveillance hooks (front-running, wash-trade detection) — needed before live? Yes for live; deferred for paper.

---

## Scope Mode: 2-Year Resume + Self-Sustaining Trading

This is the phase where scope mode bites hardest, because going live with real money on an unproven platform is how a personal trading project ends in losses larger than the resume is worth.

**Revised promotion ladder**

1. **Months 0–12:** paper trading on Alpaca only. The two-week run in the original exit criteria becomes a **rolling 6-month run with zero reconciliation drift** before any live consideration.
2. **Months 12–15:** live with **$1–2k** on Alpaca, single strategy, smallest-lot sizing. The goal is to surface bugs that paper trading hides (partial fills, locate failures, real-world slippage), not to make money.
3. **Months 15–24:** scale to **$5–10k** only after three clean months of live operation matching paper-traded expectations within a tolerance band.
4. **Beyond:** scale only with documented edge. Don't add capital because you have it; add capital because the curve says you should.

**Adjustments**

- **Brokers (Indian resident operator, US markets):**
  - **Paper trading (first 12 months):** Alpaca paper. Free, clean API, generally available to non-US residents for paper accounts and market data.
  - **Live trading:** Interactive Brokers (IBKR) — the de facto retail path for an Indian resident trading US markets via API. Integration via `ib_insync` (Python wrapper over TWS API) for the MVP; FIX is descoped (heavier ops, no benefit at this scale).
  - **OMS adapter:** the broker interface is the same for Alpaca and IBKR. Cutover from paper to live is a config + credentials change, not a rewrite. The broker-agnostic OMS is itself a resume talking point.
  - **Account setup lead time:** IBKR KYC takes 2–4 weeks for Indian residents; LRS outbound remittance to fund the account adds another few business days. Start the IBKR application no later than ~Month 10 if a Month-12 live cutover is the target.
  - **Tax / compliance hooks (operator-level, not platform code):** W-8BEN with IBKR for the IRS treaty rate on dividends; ITR Schedule FA at year-end; capital gains and dividends taxed under Indian rules with foreign tax credit. Bookkeeping is ~1–2 hours per quarter; the platform's immutable trade journal is the source-of-truth for that paperwork.
  - **Out of scope:** Zerodha / Upstox / Angel One (no US trading), Groww / INDmoney / Vested (US trading exists but no public retail API), GIFT IFSC brokers (API maturity not there yet — revisit in 12–18 months).
- **Crypto live (Binance):** descoped indefinitely.
- **Surveillance hooks:** descoped (no other users to surveil; you can't front-run yourself in a meaningful way at $5k notional). Document the gap as deferred.
- **Kill switches:** stay 100%. User-level, strategy-level, global. This is the most important code in the project.
- **Reconciliation:** stay 100%. Drift is the silent killer; don't compromise here.
- **Order state machine, idempotency, audit log:** stay 100%.
- **Capital sourcing:** treat the trading account as a separate bucket from infra costs. Do not pull from trading PnL to fund Anthropic bills — conflating them creates pressure to over-leverage when behind on infra spend.

**What stays (resume-load-bearing)**

- The architectural firewall between agents and brokers (no LLM imports anywhere in OMS), the order state machine, idempotency keys end-to-end, reconciliation, kill switches at three scopes, immutable trade journal, pre-trade risk hooks. All of it.

**Budget impact:** $0/mo (Alpaca is commission-free for US equities); trading capital is a separate pool, not infrastructure spend.
