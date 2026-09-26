"""A simulated account kept in a JSON file. Fills at the latest close."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from tradingbot.brokers.base import Account, Broker, Holding, OrderResult


class PaperBroker(Broker):
    name = "paper"

    def __init__(
        self,
        state_file: Path,
        starting_cash: float,
        currency: str,
        price_source: Callable[[str], float],
        commission_pct: float = 0.0,
    ):
        self.state_file = Path(state_file)
        self.currency = currency
        self.commission_pct = commission_pct
        self._price_source = price_source
        self._prices: dict[str, float] = {}
        if self.state_file.exists():
            self._state = json.loads(self.state_file.read_text(encoding="utf-8"))
        else:
            self._state = {
                "cash": float(starting_cash),
                "currency": currency,
                "positions": {},
                "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._save()

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash mid-write cannot leave a half ledger.
        fd, tmp = tempfile.mkstemp(dir=self.state_file.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)
        os.replace(tmp, self.state_file)

    def refresh(self) -> None:
        self._prices.clear()

    def price(self, ticker: str) -> float:
        ticker = ticker.upper()
        if ticker not in self._prices:
            self._prices[ticker] = float(self._price_source(ticker))
        return self._prices[ticker]

    def holdings(self) -> dict[str, Holding]:
        return {
            t: Holding(t, p["quantity"], p.get("average_price"))
            for t, p in self._state["positions"].items()
            if p["quantity"]
        }

    def account(self) -> Account:
        value = sum(h.quantity * self.price(t) for t, h in self.holdings().items())
        cash = self._state["cash"]
        return Account(cash=cash, equity=cash + value, currency=self._state.get("currency", self.currency))

    def submit(self, ticker: str, side: str, quantity: float) -> OrderResult:
        ticker = ticker.upper()
        if quantity <= 0 or side not in ("buy", "sell"):
            return OrderResult(ticker, side, quantity, "rejected", message="bad order")
        price = self.price(ticker)
        gross = quantity * price
        fee = gross * self.commission_pct
        pos = self._state["positions"].setdefault(ticker, {"quantity": 0.0, "average_price": None})
        held = pos["quantity"]

        if side == "buy":
            if gross + fee > self._state["cash"] + 1e-9:
                return OrderResult(ticker, side, quantity, "rejected", message="insufficient cash")
            new_qty = held + quantity
            pos["average_price"] = ((held * (pos["average_price"] or 0)) + gross) / new_qty
            pos["quantity"] = new_qty
            self._state["cash"] -= gross + fee
        else:
            if quantity > held + 1e-9:
                return OrderResult(ticker, side, quantity, "rejected", message="short selling is off")
            pos["quantity"] = held - quantity
            self._state["cash"] += gross - fee
            if pos["quantity"] <= 1e-9:
                del self._state["positions"][ticker]

        self._state.setdefault("trades", []).append({
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ticker": ticker, "side": side, "quantity": quantity, "price": price, "fee": fee,
        })
        self._save()
        return OrderResult(ticker, side, quantity, "filled", fill_price=price,
                           message=f"fee {fee:,.2f}")
