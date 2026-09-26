"""One pass over the watchlist: decide, size, execute, record."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from tradingagents.dataflows.date_window import get_current_date
from tradingbot.brokers.base import Broker, OrderResult
from tradingbot.config import BotConfig
from tradingbot.journal import Journal
from tradingbot.sizing import NoTrade, OrderPlan, plan_order
from tradingbot.symbols import canonical_ticker, crypto_coin

logger = logging.getLogger(__name__)


@dataclass
class TickerOutcome:
    ticker: str
    trade_date: str
    rating: str | None = None
    plan: OrderPlan | None = None
    skipped: str | None = None
    order: OrderResult | None = None
    error: str | None = None
    extras: dict = field(default_factory=dict)

    def summary(self) -> str:
        if self.error:
            return f"{self.ticker}: ERROR {self.error}"
        head = f"{self.ticker}: {self.rating or '-'}"
        if self.order:
            return f"{head} -> {self.order.side} {self.order.quantity:g} [{self.order.status}] {self.order.message}"
        if self.plan:
            return f"{head} -> would {self.plan.side} {self.plan.quantity:g} @ {self.plan.price:,.2f} (dry run)"
        return f"{head} -> no trade ({self.skipped})"


def _default_graph_factory(cfg: BotConfig):
    """Build TradingAgents graphs lazily, one per analyst selection."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graphs: dict[tuple[str, ...], object] = {}
    config = cfg.graph_config()

    def get(analysts: tuple[str, ...]):
        if analysts not in graphs:
            graphs[analysts] = TradingAgentsGraph(selected_analysts=analysts, config=config)
        return graphs[analysts]

    return get


class TradingBot:
    def __init__(
        self,
        cfg: BotConfig,
        broker: Broker,
        journal: Journal | None = None,
        graph_factory: Callable[[tuple[str, ...]], object] | None = None,
        today: Callable[[], str] = get_current_date,
    ):
        self.cfg = cfg
        self.broker = broker
        self.journal = journal or Journal(cfg.state_path / "journal.jsonl")
        self._graph_for = graph_factory or _default_graph_factory(cfg)
        self._today = today

    def analysts_for(self, ticker: str) -> tuple[str, ...]:
        """Crypto has no company filings, so its run drops the fundamentals analyst."""
        analysts = self.cfg.analysts
        if crypto_coin(ticker):
            analysts = [a for a in analysts if a != "fundamentals"] or ["market"]
        return tuple(analysts)

    def run_once(self, tickers: list[str] | None = None, execute: bool = True,
                 force: bool = False) -> list[TickerOutcome]:
        trade_date = self._today()
        self.broker.refresh()
        orders_sent = 0
        outcomes = []
        for ticker in [canonical_ticker(t) for t in (tickers or self.cfg.watchlist)]:
            outcome = TickerOutcome(ticker, trade_date)
            outcomes.append(outcome)
            if not force and self.journal.decided_on(ticker, trade_date):
                outcome.skipped = "already decided today (use --force to run again)"
                continue
            try:
                self._decide(outcome)
                if isinstance(outcome.plan, OrderPlan) and execute:
                    if orders_sent >= self.cfg.max_orders_per_run:
                        outcome.skipped = f"max_orders_per_run ({self.cfg.max_orders_per_run}) reached"
                        outcome.plan = None
                    else:
                        outcome.order = self.broker.submit(ticker, outcome.plan.side, outcome.plan.quantity)
                        orders_sent += outcome.order.status != "rejected"
            except Exception as exc:  # one bad ticker must not stop the rest
                logger.exception("bot run failed for %s", ticker)
                outcome.error = f"{type(exc).__name__}: {exc}"
            self._record(outcome, execute)
        return outcomes

    def _decide(self, outcome: TickerOutcome) -> None:
        ticker = outcome.ticker
        # Resolve the broker side first: a symbol the account does not offer should
        # fail before the agents spend a full analysis on it.
        rules = self.broker.quantity_rules(ticker)
        asset_type = "crypto" if crypto_coin(ticker) else "stock"
        portfolio = self.broker.portfolio_context()
        graph = self._graph_for(self.analysts_for(ticker))
        final_state, rating = graph.propagate(
            ticker, outcome.trade_date, asset_type=asset_type, portfolio=portfolio
        )
        outcome.rating = rating
        if isinstance(final_state, dict):
            outcome.extras["decision"] = (final_state.get("final_trade_decision") or "")[:2000]

        acct = self.broker.account()
        held = self.broker.holdings().get(ticker)
        step_kw = {"step": rules[0], "min_quantity": rules[1]} if rules else {}
        result = plan_order(
            self.cfg, ticker, rating,
            price=self.broker.price(ticker),
            held_quantity=held.quantity if held else 0.0,
            buying_power=acct.available, equity=acct.equity,
            **step_kw,
        )
        if isinstance(result, NoTrade):
            outcome.skipped = result.reason
        else:
            outcome.plan = result

    def _record(self, outcome: TickerOutcome, execute: bool) -> None:
        self.journal.record({
            "ticker": outcome.ticker,
            "trade_date": outcome.trade_date,
            "broker": self.broker.name,
            "executed": execute,
            "rating": outcome.rating,
            "plan": asdict(outcome.plan) if outcome.plan else None,
            "order": asdict(outcome.order) if outcome.order else None,
            "skipped": outcome.skipped,
            "error": outcome.error,
            **outcome.extras,
        })
