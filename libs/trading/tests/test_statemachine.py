"""Tests for the order state machine."""

from __future__ import annotations

import pytest
from astraeus_trading.statemachine import (
    TERMINAL_STATES,
    InvalidTransitionError,
    OrderState,
    OrderStateMachine,
)


class TestOrderStateMachine:
    """Unit tests for OrderStateMachine."""

    def test_initial_state_is_new(self) -> None:
        sm = OrderStateMachine()
        assert sm.state == OrderState.NEW

    def test_custom_initial_state(self) -> None:
        sm = OrderStateMachine(OrderState.SUBMITTED)
        assert sm.state == OrderState.SUBMITTED

    def test_happy_path_market_order(self) -> None:
        """NEW → PENDING_NEW → SUBMITTED → FILLED."""
        sm = OrderStateMachine()
        sm.transition(OrderState.PENDING_NEW)
        sm.transition(OrderState.SUBMITTED)
        sm.transition(OrderState.FILLED)
        assert sm.state == OrderState.FILLED
        assert sm.is_terminal

    def test_partial_fill_path(self) -> None:
        """NEW → PENDING_NEW → SUBMITTED → PARTIAL_FILL → FILLED."""
        sm = OrderStateMachine()
        sm.transition(OrderState.PENDING_NEW)
        sm.transition(OrderState.SUBMITTED)
        sm.transition(OrderState.PARTIAL_FILL)
        assert not sm.is_terminal
        sm.transition(OrderState.FILLED)
        assert sm.is_terminal

    def test_multiple_partial_fills(self) -> None:
        """PARTIAL_FILL → PARTIAL_FILL is allowed."""
        sm = OrderStateMachine(OrderState.PARTIAL_FILL)
        sm.transition(OrderState.PARTIAL_FILL)
        sm.transition(OrderState.PARTIAL_FILL)
        sm.transition(OrderState.FILLED)
        assert sm.state == OrderState.FILLED

    def test_cancel_from_submitted(self) -> None:
        sm = OrderStateMachine(OrderState.SUBMITTED)
        sm.transition(OrderState.CANCELLED)
        assert sm.state == OrderState.CANCELLED
        assert sm.is_terminal

    def test_cancel_from_partial_fill(self) -> None:
        sm = OrderStateMachine(OrderState.PARTIAL_FILL)
        sm.transition(OrderState.CANCELLED)
        assert sm.state == OrderState.CANCELLED

    def test_reject_from_new(self) -> None:
        sm = OrderStateMachine(OrderState.NEW)
        sm.transition(OrderState.REJECTED)
        assert sm.state == OrderState.REJECTED

    def test_reject_from_pending_new(self) -> None:
        sm = OrderStateMachine(OrderState.PENDING_NEW)
        sm.transition(OrderState.REJECTED)
        assert sm.state == OrderState.REJECTED

    def test_expired_from_submitted(self) -> None:
        sm = OrderStateMachine(OrderState.SUBMITTED)
        sm.transition(OrderState.EXPIRED)
        assert sm.state == OrderState.EXPIRED

    def test_invalid_transition_raises(self) -> None:
        sm = OrderStateMachine(OrderState.FILLED)
        with pytest.raises(InvalidTransitionError):
            sm.transition(OrderState.CANCELLED)

    def test_cannot_transition_from_terminal(self) -> None:
        for terminal in TERMINAL_STATES:
            sm = OrderStateMachine(terminal)
            assert sm.is_terminal
            for target in OrderState:
                if target != terminal:
                    assert not sm.can_transition(target)

    def test_can_transition_check(self) -> None:
        sm = OrderStateMachine(OrderState.SUBMITTED)
        assert sm.can_transition(OrderState.FILLED)
        assert sm.can_transition(OrderState.CANCELLED)
        assert not sm.can_transition(OrderState.NEW)

    def test_allowed_transitions_static(self) -> None:
        allowed = OrderStateMachine.allowed_transitions(OrderState.SUBMITTED)
        assert OrderState.FILLED in allowed
        assert OrderState.CANCELLED in allowed
        assert OrderState.PARTIAL_FILL in allowed
        assert OrderState.NEW not in allowed

    def test_skip_pending_new_not_allowed(self) -> None:
        """Cannot go directly from NEW to SUBMITTED."""
        sm = OrderStateMachine(OrderState.NEW)
        with pytest.raises(InvalidTransitionError):
            sm.transition(OrderState.SUBMITTED)
