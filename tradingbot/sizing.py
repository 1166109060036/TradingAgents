"""Turn a rating into an order. Pure arithmetic, no I/O.

Each rating targets a signed share of the per-ticker limit: ``max_position_pct``
of equity times the rating's weight. A negative weight is a short, allowed only
with ``allow_short``. Two rules keep a rating from acting against its own
direction: a bullish rating only ever buys, a bearish one only ever sells. So
Overweight on a position already above its target leaves it alone, and
Underweight never covers a short. Hold and REVIEW never trade.

Exposure is unlevered: new positions are paid for out of ``buying_power``
(equity less the gross value already held), so the book's gross exposure never
exceeds its equity whatever leverage the broker would lend.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tradingagents.agents.rating import is_review
from tradingbot.config import BotConfig

BULLISH = {"Buy", "Overweight"}
BEARISH = {"Underweight", "Sell"}

_USE_CONFIG = object()


@dataclass(frozen=True)
class OrderPlan:
    ticker: str
    side: str  # "buy" | "sell"
    quantity: float
    price: float
    target_value: float
    reason: str

    @property
    def value(self) -> float:
        return self.quantity * self.price


@dataclass(frozen=True)
class NoTrade:
    ticker: str
    reason: str


def _round_down(quantity: float, step: float | None) -> float:
    if quantity <= 0:
        return 0.0
    if step is None:
        return math.floor(quantity * 1e6) / 1e6
    return round(math.floor(quantity / step + 1e-9) * step, 10)


def plan_order(
    cfg: BotConfig,
    ticker: str,
    rating: str,
    price: float,
    held_quantity: float,
    buying_power: float,
    equity: float,
    step=_USE_CONFIG,
    min_quantity: float = 0.0,
) -> OrderPlan | NoTrade:
    """The order that moves ``ticker`` toward the size its rating asks for.

    ``held_quantity`` is signed (negative is short). ``step`` is the quantity
    increment, None for fractional; by default it comes from the config's lot
    sizes. A broker with its own contract rules passes them instead.
    """
    if is_review(rating):
        return NoTrade(ticker, "decision had no readable rating (REVIEW); needs a human")
    if rating == "Hold":
        return NoTrade(ticker, "Hold keeps the current position")
    if rating not in cfg.rating_weights:
        return NoTrade(ticker, f"no weight configured for {rating}")
    if not price or price <= 0 or not math.isfinite(price):
        return NoTrade(ticker, f"no usable price ({price})")
    if equity <= 0:
        return NoTrade(ticker, "account equity is not positive")
    if step is _USE_CONFIG:
        step = cfg.lot_size(ticker)

    current = held_quantity * price
    target = equity * cfg.max_position_pct * cfg.rating_weights[rating]
    spendable = max(buying_power - equity * cfg.min_cash_pct, 0.0) / (1 + cfg.commission_pct)

    if rating in BULLISH:
        if target <= current:
            return NoTrade(ticker, f"{rating}: already at or above target {target:,.2f}")
        side = "buy"
        closing = min(target - current, max(-current, 0.0))  # covering a short frees exposure
    else:
        if target >= current:
            what = "nothing held to sell" if current <= 0 and target >= 0 else f"already at or below target {target:,.2f}"
            return NoTrade(ticker, f"{rating}: {what}")
        side = "sell"
        closing = min(current - target, max(current, 0.0))  # selling a long frees exposure
    opening = abs(target - current) - closing
    if opening > 0 and spendable <= 0:
        opening = 0.0
        if closing <= 0:
            return NoTrade(ticker, f"{rating}: no buying power above the {cfg.min_cash_pct:.0%} reserve")
    opening = min(opening, spendable)

    if target == 0:
        quantity = abs(held_quantity)  # a full exit closes odd lots too
    else:
        quantity = _round_down((closing + opening) / price, step)
        quantity = min(quantity, abs(held_quantity)) if opening <= 0 else quantity

    if quantity <= 0 or quantity + 1e-12 < min_quantity:
        return NoTrade(ticker, f"{rating}: size rounds below the minimum quantity at price {price:,.2f}")
    if quantity * price < cfg.min_order_value:
        return NoTrade(
            ticker, f"{rating}: order {quantity * price:,.2f} is under the minimum {cfg.min_order_value:,.2f}"
        )
    return OrderPlan(
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        target_value=target,
        reason=f"{rating}: target {target:,.2f}, holding {current:,.2f}",
    )
