"""Tests for circuit breaker."""

from __future__ import annotations

from decimal import Decimal

from astraeus_risk.circuit_breaker import (
    BreakerAction,
    BreakerState,
    CircuitBreaker,
    CircuitBreakerConfig,
)


class TestCircuitBreaker:
    def _make_breaker(self) -> CircuitBreaker:
        return CircuitBreaker(
            CircuitBreakerConfig(
                scope="global",
                warn_threshold=Decimal("-500"),
                halt_threshold=Decimal("-1000"),
                recovery_threshold=Decimal("0"),
            )
        )

    def test_initial_state_closed(self) -> None:
        breaker = self._make_breaker()
        assert breaker.state == BreakerState.CLOSED
        assert not breaker.is_open

    def test_no_event_when_pnl_ok(self) -> None:
        breaker = self._make_breaker()
        event = breaker.evaluate(Decimal("-200"))
        assert event is None

    def test_warn_on_warn_threshold(self) -> None:
        breaker = self._make_breaker()
        event = breaker.evaluate(Decimal("-600"))
        assert event is not None
        assert event.action == BreakerAction.WARN
        assert breaker.state == BreakerState.CLOSED  # warn doesn't trip

    def test_halt_on_halt_threshold(self) -> None:
        breaker = self._make_breaker()
        event = breaker.evaluate(Decimal("-1200"))
        assert event is not None
        assert event.action == BreakerAction.HALT
        assert breaker.state == BreakerState.OPEN
        assert breaker.is_open

    def test_no_event_while_open(self) -> None:
        breaker = self._make_breaker()
        breaker.evaluate(Decimal("-1200"))  # trip it
        event = breaker.evaluate(Decimal("-1500"))  # still bad
        assert event is None  # already open, no new event

    def test_recovery(self) -> None:
        breaker = self._make_breaker()
        breaker.evaluate(Decimal("-1200"))  # trip
        assert breaker.is_open
        event = breaker.evaluate(Decimal("100"))  # recovered
        assert event is not None
        assert event.action == BreakerAction.WARN  # recovery event
        assert breaker.state == BreakerState.CLOSED

    def test_force_open(self) -> None:
        breaker = self._make_breaker()
        breaker.force_open()
        assert breaker.is_open

    def test_reset(self) -> None:
        breaker = self._make_breaker()
        breaker.force_open()
        breaker.reset()
        assert breaker.state == BreakerState.CLOSED

    def test_scope(self) -> None:
        breaker = self._make_breaker()
        assert breaker.scope == "global"
