"""Latest close from the TradingAgents data layer (Yahoo Finance, cached)."""

from __future__ import annotations

import math

from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.date_window import get_current_date
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv


def latest_close(ticker: str, config: dict | None = None) -> float:
    """The most recent reported close on or before today."""
    with run_config(config or {}):
        data = load_ohlcv(ticker, get_current_date(), fill_gaps=False)
    closes = data["Close"].dropna() if data is not None and "Close" in data else []
    if len(closes) == 0:
        raise ValueError(f"no price available for {ticker}")
    price = float(closes.iloc[-1])
    if not math.isfinite(price) or price <= 0:
        raise ValueError(f"unusable price for {ticker}: {price}")
    return price
