"""Prometheus metrics for the trading infrastructure.

All Phase 8 observability signals defined here. Import and use from
OMS, EMS, reconciliation worker, and kill switch service.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# --- OMS metrics ---

oms_order_latency = Histogram(
    "oms_order_latency_seconds",
    "Order state transition latency",
    labelnames=["state_transition"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

oms_idempotency_dedup = Counter(
    "oms_idempotency_dedup_total",
    "Number of duplicate order submissions caught by idempotency check",
)

oms_state_machine_violations = Counter(
    "oms_state_machine_violations_total",
    "Invalid state transitions attempted (should always be 0)",
)

oms_orders_submitted = Counter(
    "oms_orders_submitted_total",
    "Total orders submitted to brokers",
    labelnames=["broker", "order_type"],
)

# --- Reconciliation metrics ---

recon_drift_open = Gauge(
    "recon_drift_open_count",
    "Number of unresolved reconciliation drifts",
    labelnames=["account_id"],
)

recon_drift_resolution_seconds = Histogram(
    "recon_drift_resolution_seconds",
    "Time to resolve reconciliation drifts",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),
)

recon_cycle_duration = Histogram(
    "recon_cycle_duration_seconds",
    "Duration of a single reconciliation cycle",
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# --- Kill switch metrics ---

kill_switch_propagation_seconds = Histogram(
    "kill_switch_propagation_seconds",
    "Time from kill switch arm to all processes acknowledging",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
)

kill_switch_armed = Gauge(
    "kill_switch_armed",
    "Whether a kill switch is currently armed (1=armed, 0=disarmed)",
    labelnames=["scope"],
)

# --- Pre-trade risk metrics ---

pretrade_rejection = Counter(
    "pretrade_rejection_total",
    "Pre-trade risk rejections",
    labelnames=["rule"],
)

pretrade_check_duration = Histogram(
    "pretrade_check_duration_seconds",
    "Duration of pre-trade risk check",
    buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05),
)

# --- Fill / slippage metrics ---

fill_slippage_bps = Histogram(
    "fill_slippage_bps",
    "Fill slippage in basis points vs expected price",
    labelnames=["strategy", "venue"],
    buckets=(0, 1, 2, 5, 10, 25, 50, 100),
)

# --- Broker metrics ---

broker_disconnect = Counter(
    "broker_disconnect_total",
    "Broker disconnection events",
    labelnames=["broker"],
)

broker_request_duration = Histogram(
    "broker_request_duration_seconds",
    "Duration of broker API requests",
    labelnames=["broker", "operation"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# --- Trade journal metrics ---

journal_seq_gap = Counter(
    "journal_seq_gap_total",
    "Gaps detected in trade journal sequence numbers (must be 0)",
)

journal_entries_written = Counter(
    "journal_entries_written_total",
    "Total trade journal entries written",
    labelnames=["kind"],
)
