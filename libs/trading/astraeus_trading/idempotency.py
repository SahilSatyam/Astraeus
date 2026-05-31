"""Idempotency key derivation.

The ``client_order_id`` is a deterministic hash of the order's logical identity.
Submitting the same order twice (e.g. after a network blip + retry) produces the
same key, and the broker (Alpaca, IBKR) will reject the duplicate.

Format: sha256(strategy_id || rec_id || decision_id || retry_n)
"""

from __future__ import annotations

import hashlib


def derive_client_order_id(
    strategy_id: str,
    rec_id: str,
    decision_id: str,
    retry_n: int = 0,
) -> str:
    """Derive a deterministic client_order_id from order inputs.

    Args:
        strategy_id: The strategy that generated the recommendation.
        rec_id: The recommendation ID from Phase 7.
        decision_id: The HITL decision ID from Phase 7.
        retry_n: Retry counter (0 for first attempt).

    Returns:
        A hex-encoded SHA-256 hash suitable for use as a broker client_order_id.
    """
    payload = f"{strategy_id}||{rec_id}||{decision_id}||{retry_n}"
    return hashlib.sha256(payload.encode()).hexdigest()
