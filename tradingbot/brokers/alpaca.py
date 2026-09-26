"""Alpaca (US stocks and crypto) over its REST API.

Keys come from ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY. The paper endpoint
is used unless the caller asks for live, which the engine allows only when the
config and the command line both say so.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import requests

from tradingagents.dataflows.symbols import crypto_base
from tradingbot.brokers.base import Account, Broker, Holding, OrderResult

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"


def to_alpaca(ticker: str) -> str:
    base = crypto_base(ticker)
    return f"{base}/USD" if base else ticker.upper()


def from_alpaca(symbol: str) -> str:
    base = crypto_base(symbol)
    return f"{base}-USD" if base else symbol.upper()


class AlpacaBroker(Broker):
    name = "alpaca"

    def __init__(
        self,
        price_source: Callable[[str], float],
        live: bool = False,
        session: requests.Session | None = None,
        timeout: float = 20.0,
    ):
        key, secret = os.getenv("ALPACA_API_KEY_ID"), os.getenv("ALPACA_API_SECRET_KEY")
        if not key or not secret:
            raise ValueError("set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY to use the Alpaca broker")
        self.base_url = LIVE_URL if live else PAPER_URL
        self.live = live
        self.timeout = timeout
        self._price_source = price_source
        self.session = session or requests.Session()
        self.session.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})

    def _get(self, path: str):
        r = self.session.get(self.base_url + path, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def account(self) -> Account:
        data = self._get("/v2/account")
        return Account(cash=float(data["cash"]), equity=float(data["equity"]),
                       currency=data.get("currency", "USD"))

    def holdings(self) -> dict[str, Holding]:
        out = {}
        for p in self._get("/v2/positions"):
            ticker = from_alpaca(p["symbol"])
            out[ticker] = Holding(ticker, float(p["qty"]), float(p["avg_entry_price"]))
        return out

    def price(self, ticker: str) -> float:
        return float(self._price_source(ticker))

    def submit(self, ticker: str, side: str, quantity: float) -> OrderResult:
        body = {
            "symbol": to_alpaca(ticker),
            "qty": f"{quantity:.6f}".rstrip("0").rstrip("."),
            "side": side,
            "type": "market",
            # Crypto trades around the clock and takes only gtc/ioc.
            "time_in_force": "gtc" if crypto_base(ticker) else "day",
        }
        try:
            r = self.session.post(self.base_url + "/v2/orders", json=body, timeout=self.timeout)
        except requests.RequestException as exc:
            return OrderResult(ticker, side, quantity, "rejected", message=str(exc))
        if r.status_code >= 400:
            return OrderResult(ticker, side, quantity, "rejected", message=f"HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        return OrderResult(ticker, side, quantity, "submitted", order_id=data.get("id"),
                           message=data.get("status", ""))
