"""Broker adapters. ``make_broker`` picks one from the bot config."""

from __future__ import annotations

from functools import partial

from tradingbot.brokers.base import Account, Broker, Holding, OrderResult
from tradingbot.config import BotConfig


def make_broker(cfg: BotConfig, allow_live: bool = False, price_source=None) -> Broker:
    """Build the configured broker. Live trading needs ``allow_live`` as well."""
    if price_source is None:
        from tradingbot.brokers.prices import latest_close
        price_source = partial(latest_close, config=cfg.graph_config())

    if cfg.live and not allow_live:
        raise PermissionError("config asks for live trading; pass --live to confirm real-money orders")
    if allow_live and not cfg.live:
        raise PermissionError("--live was passed but the config has live=false; refusing to guess")

    if cfg.broker == "paper":
        from tradingbot.brokers.paper import PaperBroker
        return PaperBroker(
            cfg.state_path / "paper_account.json",
            starting_cash=cfg.starting_cash,
            currency=cfg.currency,
            price_source=price_source,
            commission_pct=cfg.commission_pct,
            allow_short=cfg.allow_short,
        )
    if cfg.broker == "alpaca":
        from tradingbot.brokers.alpaca import AlpacaBroker
        return AlpacaBroker(price_source=price_source, live=cfg.live)
    if cfg.broker == "mt5":
        from tradingbot.brokers.mt5 import MT5Broker
        return MT5Broker(cfg.mt5, live=cfg.live, price_fallback=price_source)
    raise ValueError(f"unknown broker {cfg.broker!r}")
