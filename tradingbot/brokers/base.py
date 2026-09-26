"""What the bot needs from a broker, and nothing more."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from tradingagents.portfolio import PortfolioContext, Position


@dataclass(frozen=True)
class Account:
    cash: float
    equity: float
    currency: str
    # Unlevered room for new exposure: equity less the gross value already held.
    # None means the same as cash (a long-only cash account).
    buying_power: float | None = None

    @property
    def available(self) -> float:
        return self.cash if self.buying_power is None else self.buying_power


@dataclass(frozen=True)
class Holding:
    ticker: str
    quantity: float
    average_price: float | None = None


@dataclass(frozen=True)
class OrderResult:
    ticker: str
    side: str
    quantity: float
    status: str  # "filled" | "submitted" | "rejected"
    fill_price: float | None = None
    order_id: str | None = None
    message: str = ""


class Broker(ABC):
    name: str = "broker"

    def refresh(self) -> None:
        """Drop anything cached, so a new run sizes against fresh prices."""
        return None

    def quantity_rules(self, ticker: str) -> tuple[float | None, float] | None:
        """The broker's (quantity step, minimum quantity) for a ticker, in units.

        None leaves sizing to the config's lot sizes. A step of None is fractional.
        """
        return None

    @abstractmethod
    def account(self) -> Account: ...

    @abstractmethod
    def holdings(self) -> dict[str, Holding]:
        """Open positions keyed by the upper-cased Yahoo ticker."""

    @abstractmethod
    def price(self, ticker: str) -> float:
        """Latest price used for sizing."""

    @abstractmethod
    def submit(self, ticker: str, side: str, quantity: float) -> OrderResult:
        """Send a market order."""

    def portfolio_context(self) -> PortfolioContext:
        """The book as the TradingAgents decision agents read it."""
        acct = self.account()
        return PortfolioContext(
            cash=acct.available,
            currency=acct.currency,
            positions=[
                Position(ticker=h.ticker, quantity=h.quantity, average_price=h.average_price)
                for h in self.holdings().values()
            ],
        )
