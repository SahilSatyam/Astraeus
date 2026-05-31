"""Pre-trade risk gateway.

Every order passes through the risk gateway before reaching the OMS. Four
independent rules are evaluated:

1. Daily loss limit — reject if realized + unrealized loss exceeds threshold.
2. Exposure cap — reject if total notional exposure would exceed limit.
3. Position limit — reject if position in a single symbol would exceed limit.
4. AI confidence threshold — reject if the recommendation confidence is below threshold.

Each rule can be independently bypassed via an override token (audit-logged).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class RiskVerdict(StrEnum):
    PASS = "pass"
    REJECT = "reject"


@dataclass(frozen=True)
class RiskCheckResult:
    """Result of a single risk rule evaluation."""

    rule_name: str
    verdict: RiskVerdict
    reason: str = ""
    details: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict == RiskVerdict.PASS


@dataclass(frozen=True)
class OrderRiskContext:
    """Context needed to evaluate risk rules for an order.

    Attributes:
        account_id: Trading account.
        symbol: Instrument being traded.
        side: 'buy' or 'sell'.
        qty: Order quantity.
        notional: Estimated notional value (qty * price).
        current_position_qty: Current position in the symbol.
        total_exposure: Current total notional exposure across all positions.
        daily_pnl: Realized + unrealized PnL for the day.
        ai_confidence: Confidence score from the recommendation (0.0 - 1.0).
    """

    account_id: str
    symbol: str
    side: str
    qty: Decimal
    notional: Decimal
    current_position_qty: Decimal = Decimal("0")
    total_exposure: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    ai_confidence: float = 1.0


class RiskRule(ABC):
    """Abstract base for a pre-trade risk rule."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def evaluate(self, ctx: OrderRiskContext) -> RiskCheckResult:
        """Evaluate the rule against the order context."""
        ...


class DailyLossRule(RiskRule):
    """Reject if daily PnL loss exceeds the configured limit."""

    def __init__(self, max_daily_loss: Decimal) -> None:
        self._max_loss = max_daily_loss

    @property
    def name(self) -> str:
        return "daily_loss_limit"

    def evaluate(self, ctx: OrderRiskContext) -> RiskCheckResult:
        if ctx.daily_pnl < -self._max_loss:
            return RiskCheckResult(
                rule_name=self.name,
                verdict=RiskVerdict.REJECT,
                reason=f"Daily loss {ctx.daily_pnl} exceeds limit -{self._max_loss}",
                details={
                    "daily_pnl": str(ctx.daily_pnl),
                    "limit": str(-self._max_loss),
                },
            )
        return RiskCheckResult(rule_name=self.name, verdict=RiskVerdict.PASS)


class ExposureCapRule(RiskRule):
    """Reject if total exposure after this order would exceed the cap."""

    def __init__(self, max_exposure: Decimal) -> None:
        self._max_exposure = max_exposure

    @property
    def name(self) -> str:
        return "exposure_cap"

    def evaluate(self, ctx: OrderRiskContext) -> RiskCheckResult:
        projected = ctx.total_exposure + ctx.notional
        if projected > self._max_exposure:
            return RiskCheckResult(
                rule_name=self.name,
                verdict=RiskVerdict.REJECT,
                reason=(
                    f"Projected exposure {projected} exceeds cap {self._max_exposure}"
                ),
                details={
                    "current_exposure": str(ctx.total_exposure),
                    "order_notional": str(ctx.notional),
                    "projected": str(projected),
                    "cap": str(self._max_exposure),
                },
            )
        return RiskCheckResult(rule_name=self.name, verdict=RiskVerdict.PASS)


class PositionLimitRule(RiskRule):
    """Reject if position in a single symbol would exceed the limit."""

    def __init__(self, max_position_qty: Decimal) -> None:
        self._max_qty = max_position_qty

    @property
    def name(self) -> str:
        return "position_limit"

    def evaluate(self, ctx: OrderRiskContext) -> RiskCheckResult:
        if ctx.side == "buy":
            projected_qty = ctx.current_position_qty + ctx.qty
        else:
            projected_qty = ctx.current_position_qty - ctx.qty

        if abs(projected_qty) > self._max_qty:
            return RiskCheckResult(
                rule_name=self.name,
                verdict=RiskVerdict.REJECT,
                reason=(
                    f"Projected position {projected_qty} in {ctx.symbol} "
                    f"exceeds limit {self._max_qty}"
                ),
                details={
                    "current_qty": str(ctx.current_position_qty),
                    "order_qty": str(ctx.qty),
                    "projected_qty": str(projected_qty),
                    "limit": str(self._max_qty),
                },
            )
        return RiskCheckResult(rule_name=self.name, verdict=RiskVerdict.PASS)


class AIConfidenceRule(RiskRule):
    """Reject if AI recommendation confidence is below threshold."""

    def __init__(self, min_confidence: float = 0.6) -> None:
        self._min_confidence = min_confidence

    @property
    def name(self) -> str:
        return "ai_confidence_threshold"

    def evaluate(self, ctx: OrderRiskContext) -> RiskCheckResult:
        if ctx.ai_confidence < self._min_confidence:
            return RiskCheckResult(
                rule_name=self.name,
                verdict=RiskVerdict.REJECT,
                reason=(
                    f"AI confidence {ctx.ai_confidence:.3f} below "
                    f"threshold {self._min_confidence}"
                ),
                details={
                    "confidence": str(ctx.ai_confidence),
                    "threshold": str(self._min_confidence),
                },
            )
        return RiskCheckResult(rule_name=self.name, verdict=RiskVerdict.PASS)


class PreTradeRiskGateway:
    """Evaluates all risk rules for an order.

    Usage::

        gateway = PreTradeRiskGateway([
            DailyLossRule(Decimal("1000")),
            ExposureCapRule(Decimal("50000")),
            PositionLimitRule(Decimal("1000")),
            AIConfidenceRule(0.6),
        ])
        results = gateway.check(context)
        if not gateway.all_passed(results):
            # reject order
    """

    def __init__(self, rules: list[RiskRule]) -> None:
        self._rules = rules

    def check(self, ctx: OrderRiskContext) -> list[RiskCheckResult]:
        """Run all risk rules and return results."""
        return [rule.evaluate(ctx) for rule in self._rules]

    @staticmethod
    def all_passed(results: list[RiskCheckResult]) -> bool:
        """Check if all rules passed."""
        return all(r.passed for r in results)

    @staticmethod
    def rejections(results: list[RiskCheckResult]) -> list[RiskCheckResult]:
        """Return only the failed rules."""
        return [r for r in results if not r.passed]
