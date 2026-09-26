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
            cash=acct.cash,
            currency=acct.currency,
            positions=[
                Position(ticker=h.ticker, quantity=h.quantity, average_price=h.average_price)
                for h in self.holdings().values()
            ],
        )
