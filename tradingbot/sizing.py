"""Turn a rating into an order. Pure arithmetic, no I/O.

Each rating targets a share of the per-ticker limit (``max_position_pct`` of
equity times the rating's weight). Two rules keep a rating from acting against
its own direction: a bullish rating only ever buys, a bearish one only ever
sells. So Overweight on a position already above its target leaves it alone, and
Underweight on a flat book does not open one. Hold and REVIEW never trade. The
bot is long-only: nothing sells below zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tradingagents.agents.rating import is_review
from tradingbot.config import BotConfig

BULLISH = {"Buy", "Overweight"}
BEARISH = {"Underweight", "Sell"}


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
    return math.floor(quantity / step + 1e-9) * step


def plan_order(
    cfg: BotConfig,
    ticker: str,
    rating: str,
    price: float,
    held_quantity: float,
    cash: float,
    equity: float,
) -> OrderPlan | NoTrade:
    """The order that moves ``ticker`` toward the size its rating asks for."""
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

    held_quantity = max(held_quantity, 0.0)  # long-only: a short is never added to
    current_value = held_quantity * price
    target_value = equity * cfg.max_position_pct * cfg.rating_weights[rating]
    step = cfg.lot_size(ticker)

    if rating in BULLISH:
        if target_value <= current_value:
            return NoTrade(ticker, f"{rating}: already at or above target {target_value:,.2f}")
        spendable = cash - equity * cfg.min_cash_pct
        budget = min(target_value - current_value, spendable / (1 + cfg.commission_pct))
        if budget <= 0:
            return NoTrade(ticker, f"{rating}: no cash above the {cfg.min_cash_pct:.0%} reserve")
        quantity = _round_down(budget / price, step)
        side = "buy"
    else:
        if held_quantity <= 0:
            return NoTrade(ticker, f"{rating}: nothing held to sell")
        if target_value == 0:
            quantity = held_quantity  # a full exit sells odd lots too
        else:
            if target_value >= current_value:
                return NoTrade(ticker, f"{rating}: already at or below target {target_value:,.2f}")
            quantity = min(_round_down((current_value - target_value) / price, step), held_quantity)
        side = "sell"

    if quantity <= 0:
        return NoTrade(ticker, f"{rating}: size rounds to zero at price {price:,.2f}")
    if quantity * price < cfg.min_order_value:
        return NoTrade(
            ticker, f"{rating}: order {quantity * price:,.2f} is under the minimum {cfg.min_order_value:,.2f}"
        )
    return OrderPlan(
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        target_value=target_value,
        reason=f"{rating}: target {target_value:,.2f}, holding {current_value:,.2f}",
    )
