"""Tests for pre-trade risk gateway."""

from __future__ import annotations

from decimal import Decimal

from astraeus_risk.pre_trade import (
    AIConfidenceRule,
    DailyLossRule,
    ExposureCapRule,
    OrderRiskContext,
    PositionLimitRule,
    PreTradeRiskGateway,
    RiskVerdict,
)


def _ctx(**kwargs) -> OrderRiskContext:
    """Helper to create a risk context with defaults."""
    defaults = {
        "account_id": "test-account",
        "symbol": "AAPL",
        "side": "buy",
        "qty": Decimal("100"),
        "notional": Decimal("15000"),
        "current_position_qty": Decimal("0"),
        "total_exposure": Decimal("0"),
        "daily_pnl": Decimal("0"),
        "ai_confidence": 0.8,
    }
    defaults.update(kwargs)
    return OrderRiskContext(**defaults)


class TestDailyLossRule:
    def test_pass_when_within_limit(self) -> None:
        rule = DailyLossRule(Decimal("1000"))
        result = rule.evaluate(_ctx(daily_pnl=Decimal("-500")))
        assert result.passed

    def test_reject_when_exceeds_limit(self) -> None:
        rule = DailyLossRule(Decimal("1000"))
        result = rule.evaluate(_ctx(daily_pnl=Decimal("-1500")))
        assert not result.passed
        assert result.verdict == RiskVerdict.REJECT

    def test_pass_at_exact_limit(self) -> None:
        rule = DailyLossRule(Decimal("1000"))
        result = rule.evaluate(_ctx(daily_pnl=Decimal("-1000")))
        assert result.passed  # -1000 is not < -1000

    def test_pass_with_positive_pnl(self) -> None:
        rule = DailyLossRule(Decimal("1000"))
        result = rule.evaluate(_ctx(daily_pnl=Decimal("500")))
        assert result.passed


class TestExposureCapRule:
    def test_pass_when_within_cap(self) -> None:
        rule = ExposureCapRule(Decimal("100000"))
        result = rule.evaluate(_ctx(total_exposure=Decimal("50000"), notional=Decimal("10000")))
        assert result.passed

    def test_reject_when_exceeds_cap(self) -> None:
        rule = ExposureCapRule(Decimal("100000"))
        result = rule.evaluate(_ctx(total_exposure=Decimal("95000"), notional=Decimal("10000")))
        assert not result.passed

    def test_pass_at_exact_cap(self) -> None:
        rule = ExposureCapRule(Decimal("100000"))
        result = rule.evaluate(_ctx(total_exposure=Decimal("90000"), notional=Decimal("10000")))
        assert result.passed  # 100000 is not > 100000


class TestPositionLimitRule:
    def test_pass_when_within_limit(self) -> None:
        rule = PositionLimitRule(Decimal("1000"))
        result = rule.evaluate(_ctx(current_position_qty=Decimal("500"), qty=Decimal("100")))
        assert result.passed

    def test_reject_when_exceeds_limit(self) -> None:
        rule = PositionLimitRule(Decimal("1000"))
        result = rule.evaluate(_ctx(current_position_qty=Decimal("950"), qty=Decimal("100")))
        assert not result.passed

    def test_sell_reduces_position(self) -> None:
        rule = PositionLimitRule(Decimal("1000"))
        result = rule.evaluate(
            _ctx(side="sell", current_position_qty=Decimal("900"), qty=Decimal("100"))
        )
        assert result.passed  # 900 - 100 = 800, within limit


class TestAIConfidenceRule:
    def test_pass_above_threshold(self) -> None:
        rule = AIConfidenceRule(0.6)
        result = rule.evaluate(_ctx(ai_confidence=0.8))
        assert result.passed

    def test_reject_below_threshold(self) -> None:
        rule = AIConfidenceRule(0.6)
        result = rule.evaluate(_ctx(ai_confidence=0.4))
        assert not result.passed

    def test_pass_at_threshold(self) -> None:
        rule = AIConfidenceRule(0.6)
        result = rule.evaluate(_ctx(ai_confidence=0.6))
        assert result.passed  # 0.6 is not < 0.6


class TestPreTradeRiskGateway:
    def test_all_pass(self) -> None:
        gateway = PreTradeRiskGateway(
            [
                DailyLossRule(Decimal("1000")),
                ExposureCapRule(Decimal("100000")),
                PositionLimitRule(Decimal("1000")),
                AIConfidenceRule(0.6),
            ]
        )
        results = gateway.check(_ctx())
        assert gateway.all_passed(results)
        assert gateway.rejections(results) == []

    def test_mixed_results(self) -> None:
        gateway = PreTradeRiskGateway(
            [
                DailyLossRule(Decimal("1000")),
                ExposureCapRule(Decimal("100000")),
                PositionLimitRule(Decimal("1000")),
                AIConfidenceRule(0.6),
            ]
        )
        # Fail on daily loss and AI confidence
        results = gateway.check(_ctx(daily_pnl=Decimal("-2000"), ai_confidence=0.3))
        assert not gateway.all_passed(results)
        rejections = gateway.rejections(results)
        assert len(rejections) == 2
        rule_names = {r.rule_name for r in rejections}
        assert "daily_loss_limit" in rule_names
        assert "ai_confidence_threshold" in rule_names
