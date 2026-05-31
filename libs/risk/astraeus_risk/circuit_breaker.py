"""Circuit breaker for PnL drawdown protection.

The circuit breaker monitors account-level PnL and triggers when drawdown
exceeds configured thresholds. When tripped, it arms the kill switch for
the affected scope.

Two modes:
- WARN: Log alert, continue trading.
- HALT: Arm kill switch, pause all new submissions for the scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class BreakerState(StrEnum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Tripped — trading halted


class BreakerAction(StrEnum):
    WARN = "warn"
    HALT = "halt"


@dataclass
class CircuitBreakerConfig:
    """Configuration for a circuit breaker.

    Attributes:
        scope: What this breaker protects (e.g. 'global', 'strategy:momentum').
        warn_threshold: PnL drawdown that triggers a warning.
        halt_threshold: PnL drawdown that triggers a halt.
        recovery_threshold: PnL improvement needed to reset from OPEN to CLOSED.
    """

    scope: str
    warn_threshold: Decimal = Decimal("-500")
    halt_threshold: Decimal = Decimal("-1000")
    recovery_threshold: Decimal = Decimal("0")


@dataclass
class BreakerEvent:
    """Event emitted when a circuit breaker changes state."""

    scope: str
    action: BreakerAction
    current_pnl: Decimal
    threshold: Decimal
    message: str


class CircuitBreaker:
    """PnL drawdown circuit breaker.

    Usage::

        breaker = CircuitBreaker(CircuitBreakerConfig(
            scope="global",
            warn_threshold=Decimal("-500"),
            halt_threshold=Decimal("-1000"),
        ))
        event = breaker.evaluate(current_pnl=Decimal("-750"))
        if event and event.action == BreakerAction.HALT:
            # arm kill switch
    """

    def __init__(self, config: CircuitBreakerConfig) -> None:
        self._config = config
        self._state = BreakerState.CLOSED

    @property
    def state(self) -> BreakerState:
        return self._state

    @property
    def scope(self) -> str:
        return self._config.scope

    @property
    def is_open(self) -> bool:
        return self._state == BreakerState.OPEN

    def evaluate(self, current_pnl: Decimal) -> BreakerEvent | None:
        """Evaluate PnL against thresholds.

        Returns a BreakerEvent if a threshold is crossed, None otherwise.
        """
        # If already open, check for recovery
        if self._state == BreakerState.OPEN:
            if current_pnl >= self._config.recovery_threshold:
                self._state = BreakerState.CLOSED
                return BreakerEvent(
                    scope=self._config.scope,
                    action=BreakerAction.WARN,
                    current_pnl=current_pnl,
                    threshold=self._config.recovery_threshold,
                    message=f"Circuit breaker recovered for {self._config.scope}",
                )
            return None

        # Check halt threshold (more severe)
        if current_pnl <= self._config.halt_threshold:
            self._state = BreakerState.OPEN
            return BreakerEvent(
                scope=self._config.scope,
                action=BreakerAction.HALT,
                current_pnl=current_pnl,
                threshold=self._config.halt_threshold,
                message=(
                    f"HALT: PnL {current_pnl} breached halt threshold "
                    f"{self._config.halt_threshold} for {self._config.scope}"
                ),
            )

        # Check warn threshold
        if current_pnl <= self._config.warn_threshold:
            return BreakerEvent(
                scope=self._config.scope,
                action=BreakerAction.WARN,
                current_pnl=current_pnl,
                threshold=self._config.warn_threshold,
                message=(
                    f"WARN: PnL {current_pnl} breached warn threshold "
                    f"{self._config.warn_threshold} for {self._config.scope}"
                ),
            )

        return None

    def force_open(self) -> None:
        """Manually trip the circuit breaker."""
        self._state = BreakerState.OPEN

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed."""
        self._state = BreakerState.CLOSED
