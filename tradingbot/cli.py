"""Command line for the trading bot: ``tradingbot run|status|history|loop|init``."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from tradingbot.brokers import make_broker
from tradingbot.config import BotConfig, load_bot_config
from tradingbot.engine import TradingBot
from tradingbot.journal import Journal

app = typer.Typer(name="tradingbot", help="Automated trading driven by TradingAgents decisions.",
                  no_args_is_help=True)
console = Console()

ConfigOpt = typer.Option("bot.json", "--config", "-c", help="Bot config JSON file")

EXAMPLE = {
    "watchlist": ["NVDA", "AAPL", "BTC-USD"],
    "broker": "paper",
    "live": False,
    "analysts": ["market", "social", "news", "fundamentals"],
    "currency": "USD",
    "starting_cash": 100000,
    "max_position_pct": 0.10,
    "rating_weights": {"Buy": 1.0, "Overweight": 0.6, "Underweight": 0.3, "Sell": 0.0},
    "min_cash_pct": 0.05,
    "min_order_value": 50,
    "max_orders_per_run": 10,
    "fractional": False,
    "lot_sizes": {},
    "commission_pct": 0.001,
    "state_dir": "~/.tradingagents/bot",
    "tradingagents": {
        "llm_provider": "openai",
        "deep_think_llm": "gpt-6-sol",
        "quick_think_llm": "gpt-6-luna",
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
    },
}


PRESETS = {
    "default": EXAMPLE,
    # Crypto CFDs on an Exness MT5 account. Start on a demo account; shorts stay
    # off until allow_short is set and Sell is given a negative weight.
    "exness-crypto": {
        "watchlist": ["BTC-USD", "ETH-USD", "SOL-USD"],
        "broker": "mt5",
        "live": False,
        "analysts": ["market", "social", "news"],
        "currency": "USD",
        "max_position_pct": 0.15,
        "rating_weights": {"Buy": 1.0, "Overweight": 0.5, "Underweight": 0.0, "Sell": 0.0},
        "allow_short": False,
        "min_cash_pct": 0.10,
        "min_order_value": 10,
        "max_orders_per_run": 5,
        "mt5": {"symbol_suffix": "m", "symbol_map": {}, "magic": 26092601, "deviation": 50},
        "state_dir": "~/.tradingagents/bot-exness",
        "tradingagents": {
            "llm_provider": "openai",
            "deep_think_llm": "gpt-6-sol",
            "quick_think_llm": "gpt-6-luna",
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
        },
    },
}


def _load(path: str) -> BotConfig:
    try:
        return load_bot_config(path)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None


def _broker(cfg: BotConfig, live: bool):
    try:
        return make_broker(cfg, allow_live=live)
    except (PermissionError, ValueError, ConnectionError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None


def _banner(cfg: BotConfig, dry_run: bool) -> None:
    mode = "LIVE MONEY" if cfg.live else ("simulated" if cfg.broker == "paper" else "demo/paper account")
    style = "bold red" if cfg.live else "green"
    console.print(f"[{style}]Broker: {cfg.broker} ({mode}){' — dry run, no orders' if dry_run else ''}[/{style}]")


@app.command()
def init(
    path: str = typer.Argument("bot.json", help="Where to write the example config"),
    preset: str = typer.Option("default", "--preset", help=f"One of: {', '.join(PRESETS)}"),
):
    """Write an example bot config to start from."""
    if preset not in PRESETS:
        console.print(f"[red]Unknown preset {preset!r}; choose from {', '.join(PRESETS)}[/red]")
        raise typer.Exit(code=1)
    target = Path(path)
    if target.exists():
        console.print(f"[yellow]{target} exists; not overwriting.[/yellow]")
        raise typer.Exit(code=1)
    target.write_text(json.dumps(PRESETS[preset], indent=2) + "\n", encoding="utf-8")
    console.print(f"Wrote {target}. Edit the watchlist and LLM settings, then: tradingbot run -c {target}")


@app.command()
def setup(
    config: str = typer.Option("bot.json", "--config", "-c", help="Where to write the bot config"),
    env: str = typer.Option(".env", "--env", help="Where to store the API key"),
):
    """Answer a few questions to create bot.json and store your API key."""
    from tradingbot.wizard import run_wizard

    if not run_wizard(Path(config), Path(env), console):
        raise typer.Exit(code=1)
    console.print(f"Next: tradingbot check -c {config}")


@app.command()
def check(config: str = ConfigOpt, live: bool = typer.Option(False, "--live")):
    """Check the API key, the broker connection and every symbol before trading."""
    from tradingbot.wizard import run_checks

    cfg = _load(config)
    if not run_checks(cfg, lambda c: make_broker(c, allow_live=live), console):
        console.print("[red]Fix the items marked FAIL, then run the check again.[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]All good.[/green] Try: tradingbot run -c {config} --dry-run")


@app.command()
def run(
    config: str = ConfigOpt,
    dry_run: bool = typer.Option(False, "--dry-run", help="Decide and size, but send no orders"),
    live: bool = typer.Option(False, "--live", help="Confirm real-money orders (config must say live=true)"),
    force: bool = typer.Option(False, "--force", help="Re-run tickers already decided today"),
    ticker: Annotated[list[str] | None, typer.Option("--ticker", "-t", help="Only these tickers")] = None,
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Run the agents once over the watchlist and trade on their ratings."""
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING)
    cfg = _load(config)
    _banner(cfg, dry_run)
    bot = TradingBot(cfg, _broker(cfg, live))
    for outcome in bot.run_once(tickers=ticker or None, execute=not dry_run, force=force):
        color = "red" if outcome.error else ("cyan" if outcome.order or outcome.plan else "white")
        console.print(f"[{color}]{escape(outcome.summary())}[/{color}]")
    _print_status(bot.broker)


def _print_status(broker) -> None:
    acct = broker.account()
    table = Table(title=f"{broker.name} account — cash {acct.cash:,.2f} / equity {acct.equity:,.2f} {acct.currency}")
    for col in ("Ticker", "Quantity", "Avg price", "Last", "Value", "P/L %"):
        table.add_column(col, justify="right" if col != "Ticker" else "left")
    for t, h in sorted(broker.holdings().items()):
        try:
            last = broker.price(t)
        except Exception:
            last = None
        value = f"{h.quantity * last:,.2f}" if last else "-"
        direction = 1 if h.quantity > 0 else -1
        pnl = f"{(last / h.average_price - 1) * 100 * direction:+.2f}" if last and h.average_price else "-"
        avg = f"{h.average_price:,.2f}" if h.average_price else "-"
        table.add_row(t, f"{h.quantity:g}", avg, f"{last:,.2f}" if last else "-", value, pnl)
    console.print(table)


@app.command()
def status(config: str = ConfigOpt, live: bool = typer.Option(False, "--live")):
    """Show cash, equity and open positions."""
    cfg = _load(config)
    _print_status(_broker(cfg, live))


@app.command()
def history(config: str = ConfigOpt, n: int = typer.Option(20, "-n", help="How many entries")):
    """Show the most recent decisions and orders."""
    cfg = _load(config)
    table = Table(title="Bot journal")
    for col in ("Time", "Date", "Ticker", "Rating", "Action", "Note"):
        table.add_column(col)
    for e in Journal(cfg.state_path / "journal.jsonl").entries()[-n:]:
        order, plan = e.get("order") or {}, e.get("plan") or {}
        if order:
            action = f"{order['side']} {order['quantity']:g} [{order['status']}]"
        elif plan:
            action = f"(dry) {plan['side']} {plan['quantity']:g}"
        else:
            action = "-"
        note = e.get("error") or e.get("skipped") or (order.get("message") if order else "") or ""
        table.add_row(e.get("time", "")[:19], e.get("trade_date", ""), e.get("ticker", ""),
                      e.get("rating") or "-", escape(action), escape(note[:60]))
    console.print(table)


def _next_run(at: str, weekdays_only: bool, now: datetime) -> datetime:
    hour, minute = (int(x) for x in at.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    while weekdays_only and candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


@app.command()
def loop(
    config: str = ConfigOpt,
    at: str = typer.Option("16:30", "--at", help="Local time to run each day, HH:MM"),
    weekdays_only: bool = typer.Option(True, "--weekdays-only/--every-day",
                                       help="Skip Saturday and Sunday (use --every-day for crypto)"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    live: bool = typer.Option(False, "--live"),
):
    """Keep running: trade once a day at the given local time."""
    logging.basicConfig(level=logging.WARNING)
    cfg = _load(config)
    _banner(cfg, dry_run)
    bot = TradingBot(cfg, _broker(cfg, live))
    while True:
        when = _next_run(at, weekdays_only, datetime.now())
        console.print(f"Next run at {when:%Y-%m-%d %H:%M}. Ctrl+C to stop.")
        time.sleep(max(0.0, (when - datetime.now()).total_seconds()))
        for outcome in bot.run_once(execute=not dry_run):
            console.print(escape(outcome.summary()))


if __name__ == "__main__":
    app()
