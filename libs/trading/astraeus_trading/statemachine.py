"""Order state machine with explicit transitions.

The order lifecycle follows a strict state graph. Any attempt to transition
outside the allowed edges raises ``InvalidTransitionError``. The state machine
is the single source of truth for what transitions are legal.

States:
    NEW → PENDING_NEW → SUBMITTED → PARTIAL_FILL → FILLED
                                  → CANCELLED
                                  → REJECTED
                                  → EXPIRED
"""

from __future__ import annotations

from enum import StrEnum

from astraeus_domain import AstraeusError


class InvalidTransitionError(AstraeusError):
    """Raised when an order state transition is not allowed."""

    code = "astraeus.trading.invalid_transition"
    status = 409


class OrderState(StrEnum):
    """Explicit order lifecycle states."""

    NEW = "new"
    PENDING_NEW = "pending_new"
    SUBMITTED = "submitted"
    PARTIAL_FILL = "partial_fill"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


# Allowed transitions: from_state -> set of valid to_states
_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.NEW: {OrderState.PENDING_NEW, OrderState.REJECTED},
    OrderState.PENDING_NEW: {
        OrderState.SUBMITTED,
        OrderState.REJECTED,
        OrderState.CANCELLED,
    },
    OrderState.SUBMITTED: {
        OrderState.PARTIAL_FILL,
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
    },
    OrderState.PARTIAL_FILL: {
        OrderState.PARTIAL_FILL,  # additional partial fills
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
    },
    # Terminal states — no outgoing transitions
    OrderState.FILLED: set(),
    OrderState.CANCELLED: set(),
    OrderState.REJECTED: set(),
    OrderState.EXPIRED: set(),
}

TERMINAL_STATES: frozenset[OrderState] = frozenset(
    {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.EXPIRED}
)


class OrderStateMachine:
    """Validates and applies state transitions for a single order.

    Usage::

        sm = OrderStateMachine(OrderState.NEW)
        sm.transition(OrderState.PENDING_NEW)
        sm.transition(OrderState.SUBMITTED)
        sm.transition(OrderState.FILLED)
    """

    def __init__(self, initial: OrderState = OrderState.NEW) -> None:
        self._state = initial

    @property
    def state(self) -> OrderState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    def can_transition(self, to: OrderState) -> bool:
        """Check if a transition is allowed without applying it."""
        allowed = _TRANSITIONS.get(self._state, set())
        return to in allowed

    def transition(self, to: OrderState) -> OrderState:
        """Apply a state transition. Raises on invalid transition."""
        if not self.can_transition(to):
            raise InvalidTransitionError(
                f"Cannot transition from {self._state!r} to {to!r}",
                extra={"from_state": self._state, "to_state": to},
            )
        self._state = to
        return self._state

    @staticmethod
    def allowed_transitions(state: OrderState) -> frozenset[OrderState]:
        """Return the set of states reachable from the given state."""
        return frozenset(_TRANSITIONS.get(state, set()))
