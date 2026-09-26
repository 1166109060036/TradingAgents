"""Which tickers are crypto, and their coin."""

from __future__ import annotations

from tradingagents.dataflows.symbols import crypto_base

_QUOTES = ("-USD", "-USDT", "-USDC")


def crypto_coin(ticker: str) -> str | None:
    """``BTC`` for ``BTC-USD``/``BTCUSD``/``BNB-USD``; None for anything else.

    Yahoo spells every crypto pair ``<COIN>-USD``, so a dashed USD quote marks a
    coin even when it is missing from the data layer's short list of known bases.
    """
    base = crypto_base(ticker)
    if base:
        return base
    upper = ticker.strip().upper()
    for quote in _QUOTES:
        if upper.endswith(quote) and len(upper) > len(quote):
            return upper[: -len(quote)]
    return None


def canonical_ticker(ticker: str) -> str:
    """Crypto as Yahoo's ``<COIN>-USD``; everything else upper-cased as given."""
    coin = crypto_coin(ticker)
    return f"{coin}-USD" if coin else ticker.strip().upper()
