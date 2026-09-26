"""A simulated account kept in a JSON file. Fills at the latest close."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from tradingbot.brokers.base import Account, Broker, Holding, OrderResult

_EPS = 1e-9


class PaperBroker(Broker):
    name = "paper"

    def __init__(
        self,
        state_file: Path,
        starting_cash: float,
        currency: str,
        price_source: Callable[[str], float],
        commission_pct: float = 0.0,
        allow_short: bool = False,
    ):
        self.state_file = Path(state_file)
        self.currency = currency
        self.commission_pct = commission_pct
        self.allow_short = allow_short
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
        values = [h.quantity * self.price(t) for t, h in self.holdings().items()]
        cash = self._state["cash"]
        equity = cash + sum(values)
        return Account(
            cash=cash,
            equity=equity,
            currency=self._state.get("currency", self.currency),
            buying_power=equity - sum(abs(v) for v in values),
        )

    def submit(self, ticker: str, side: str, quantity: float) -> OrderResult:
        ticker = ticker.upper()
        if quantity <= 0 or side not in ("buy", "sell"):
            return OrderResult(ticker, side, quantity, "rejected", message="bad order")
        price = self.price(ticker)
        signed = quantity if side == "buy" else -quantity
        pos = self._state["positions"].get(ticker, {"quantity": 0.0, "average_price": None})
        held = pos["quantity"]
        new_qty = held + signed

        if new_qty < -_EPS and not self.allow_short:
            return OrderResult(ticker, side, quantity, "rejected", message="short selling is off")
        # Only the part that adds exposure has to be funded.
        opening = max(abs(new_qty) - abs(held), 0.0) if held * new_qty >= 0 else abs(new_qty)
        fee = quantity * price * self.commission_pct
        if opening * price + fee > self.account().available + _EPS:
            return OrderResult(ticker, side, quantity, "rejected", message="insufficient buying power")

        if abs(new_qty) <= _EPS:
            self._state["positions"].pop(ticker, None)
        else:
            if held == 0 or held * signed > 0:  # opening or adding: average in
                avg = pos["average_price"] or 0.0
                pos["average_price"] = (abs(held) * avg + quantity * price) / abs(new_qty)
            elif held * new_qty < 0:  # flipped through zero: the remainder opened here
                pos["average_price"] = price
            pos["quantity"] = new_qty
            self._state["positions"][ticker] = pos
        self._state["cash"] -= signed * price + fee

        self._state.setdefault("trades", []).append({
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ticker": ticker, "side": side, "quantity": quantity, "price": price, "fee": fee,
        })
        self._save()
        return OrderResult(ticker, side, quantity, "filled", fill_price=price, message=f"fee {fee:,.2f}")
