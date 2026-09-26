"""Bot settings: what to trade, where, and within which limits."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from tradingagents.agents.rating import RATINGS_5_TIER
from tradingagents.default_config import DEFAULT_CONFIG
from tradingbot.symbols import canonical_ticker

# Share of ``max_position_pct`` each rating targets. Hold is absent on purpose:
# it keeps whatever is held rather than steering to a size.
DEFAULT_RATING_WEIGHTS = {"Buy": 1.0, "Overweight": 0.6, "Underweight": 0.3, "Sell": 0.0}

ALL_ANALYSTS = ("market", "social", "news", "fundamentals")


class MT5Settings(BaseModel):
    """How the bot finds its symbols and its own positions on a MetaTrader 5 account."""

    symbol_suffix: str = Field(
        default="", description="Appended to every broker symbol, e.g. 'm' for Exness Standard (BTCUSDm)"
    )
    symbol_map: dict[str, str] = Field(
        default_factory=dict, description="Explicit ticker -> broker symbol, e.g. {'BTC-USD': 'BTCUSDm'}"
    )
    magic: int = Field(default=26092601, description="Tags the bot's orders; other positions are left alone")
    deviation: int = Field(default=50, ge=0, description="Maximum slippage in points")

    @field_validator("symbol_map")
    @classmethod
    def _canonical_keys(cls, mapping: dict[str, str]) -> dict[str, str]:
        return {canonical_ticker(k): v for k, v in mapping.items()}


class BotConfig(BaseModel):
    watchlist: list[str] = Field(min_length=1, description="Yahoo Finance tickers to trade")
    broker: Literal["paper", "alpaca", "mt5"] = "paper"
    live: bool = Field(
        default=False,
        description="Use the broker's real-money endpoint. Also needs --live on the command line.",
    )
    analysts: list[str] = Field(default_factory=lambda: list(ALL_ANALYSTS))
    currency: str = "USD"

    # Risk limits.
    max_position_pct: float = Field(
        default=0.10, gt=0, le=1, description="Largest share of equity one ticker may take"
    )
    rating_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_RATING_WEIGHTS))
    min_cash_pct: float = Field(default=0.05, ge=0, lt=1, description="Cash never spent on buys")
    min_order_value: float = Field(default=50.0, ge=0, description="Smaller orders are skipped")
    max_orders_per_run: int = Field(default=10, ge=0)
    allow_short: bool = Field(
        default=False, description="Let negative rating weights open short positions (CFD accounts)"
    )
    fractional: bool = Field(default=False, description="Allow fractional quantities")
    lot_sizes: dict[str, float] = Field(
        default_factory=dict, description="Board lot per ticker, e.g. {'PTT.BK': 100}"
    )

    # Paper broker only.
    starting_cash: float = Field(default=100_000.0, gt=0)
    commission_pct: float = Field(default=0.001, ge=0, lt=0.1)

    mt5: MT5Settings = Field(default_factory=MT5Settings)

    state_dir: str = "~/.tradingagents/bot"
    # Overrides for the TradingAgents config (llm_provider, deep_think_llm, ...).
    tradingagents: dict[str, Any] = Field(default_factory=dict)

    @field_validator("watchlist")
    @classmethod
    def _unique_upper(cls, tickers: list[str]) -> list[str]:
        seen: list[str] = []
        for t in tickers:
            t = canonical_ticker(t) if t.strip() else ""
            if t and t not in seen:
                seen.append(t)
        if not seen:
            raise ValueError("watchlist is empty")
        return seen

    @field_validator("analysts")
    @classmethod
    def _known_analysts(cls, analysts: list[str]) -> list[str]:
        unknown = sorted(set(analysts) - set(ALL_ANALYSTS))
        if unknown or not analysts:
            raise ValueError(f"analysts must be a non-empty subset of {ALL_ANALYSTS}, got {analysts}")
        return analysts

    @field_validator("rating_weights")
    @classmethod
    def _valid_weights(cls, weights: dict[str, float]) -> dict[str, float]:
        normalized = {k.strip().capitalize(): float(v) for k, v in weights.items()}
        unknown = sorted(set(normalized) - set(RATINGS_5_TIER))
        if unknown:
            raise ValueError(f"unknown ratings in rating_weights: {unknown}")
        if any(not -1 <= v <= 1 for v in normalized.values()):
            raise ValueError("rating_weights must lie between -1 and 1")
        if normalized.get("Hold") is not None:
            raise ValueError("Hold keeps the current position and takes no weight")
        return normalized

    @field_validator("lot_sizes")
    @classmethod
    def _positive_lots(cls, lots: dict[str, float]) -> dict[str, float]:
        if any(v <= 0 for v in lots.values()):
            raise ValueError("lot sizes must be positive")
        return {canonical_ticker(k): float(v) for k, v in lots.items()}

    @model_validator(mode="after")
    def _live_needs_real_broker(self):
        if self.live and self.broker == "paper":
            raise ValueError("live=true needs a real broker; the paper broker is simulated")
        return self

    @model_validator(mode="after")
    def _weights_match_direction(self):
        for rating, weight in self.rating_weights.items():
            if weight < 0 and not self.allow_short:
                raise ValueError(f"{rating} has a negative weight (a short) but allow_short is false")
            if weight < 0 and rating in ("Buy", "Overweight"):
                raise ValueError(f"{rating} is bullish and cannot target a short")
        return self

    @property
    def state_path(self) -> Path:
        return Path(self.state_dir).expanduser()

    def lot_size(self, ticker: str) -> float | None:
        """Quantity step for a ticker: its board lot, or None when fractional."""
        lot = self.lot_sizes.get(canonical_ticker(ticker))
        if lot is not None:
            return lot
        return None if self.fractional else 1.0

    def graph_config(self) -> dict[str, Any]:
        """The TradingAgents config with this bot's overrides applied."""
        config = copy.deepcopy(DEFAULT_CONFIG)
        for key, value in self.tradingagents.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
        return config


def load_bot_config(path: str | Path) -> BotConfig:
    """Read a bot config JSON file, failing before any order can be sent."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return BotConfig.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"bot config {path} is not usable: {exc}") from exc
