"""Tests for position calculation logic.

These test the math of position updates without requiring a database.
"""

from __future__ import annotations

from decimal import Decimal


def _compute_position_after_fill(
    current_qty: Decimal,
    current_avg: Decimal,
    side: str,
    fill_qty: Decimal,
    fill_price: Decimal,
) -> tuple[Decimal, Decimal]:
    """Replicate the position update logic for testing."""
    if side == "buy":
        new_qty = current_qty + fill_qty
        if new_qty != Decimal("0"):
            new_avg = ((current_qty * current_avg) + (fill_qty * fill_price)) / new_qty
        else:
            new_avg = Decimal("0")
    else:
        new_qty = current_qty - fill_qty
        new_avg = current_avg
    return new_qty, new_avg


class TestPositionCalculation:
    def test_first_buy(self) -> None:
        qty, avg = _compute_position_after_fill(
            Decimal("0"), Decimal("0"), "buy", Decimal("100"), Decimal("150")
        )
        assert qty == Decimal("100")
        assert avg == Decimal("150")

    def test_second_buy_averages(self) -> None:
        qty, avg = _compute_position_after_fill(
            Decimal("100"), Decimal("150"), "buy", Decimal("100"), Decimal("160")
        )
        assert qty == Decimal("200")
        assert avg == Decimal("155")  # (100*150 + 100*160) / 200

    def test_sell_reduces_qty(self) -> None:
        qty, avg = _compute_position_after_fill(
            Decimal("200"), Decimal("155"), "sell", Decimal("50"), Decimal("170")
        )
        assert qty == Decimal("150")
        assert avg == Decimal("155")  # avg cost unchanged on sell

    def test_sell_to_zero(self) -> None:
        qty, avg = _compute_position_after_fill(
            Decimal("100"), Decimal("150"), "sell", Decimal("100"), Decimal("160")
        )
        assert qty == Decimal("0")
        assert avg == Decimal("150")  # avg cost preserved

    def test_sell_to_short(self) -> None:
        qty, avg = _compute_position_after_fill(
            Decimal("50"), Decimal("150"), "sell", Decimal("100"), Decimal("160")
        )
        assert qty == Decimal("-50")
        assert avg == Decimal("150")  # avg cost unchanged

    def test_buy_at_different_prices(self) -> None:
        # Buy 10 @ 100, then 20 @ 130
        qty, avg = _compute_position_after_fill(
            Decimal("0"), Decimal("0"), "buy", Decimal("10"), Decimal("100")
        )
        assert qty == Decimal("10")
        assert avg == Decimal("100")

        qty, avg = _compute_position_after_fill(
            qty, avg, "buy", Decimal("20"), Decimal("130")
        )
        assert qty == Decimal("30")
        # (10*100 + 20*130) / 30 = (1000 + 2600) / 30 = 120
        assert avg == Decimal("120")
