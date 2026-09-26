"""First-run setup: ask a few questions, write bot.json and the API key to .env.

The pure parts (building the config, editing .env) are separate from the
prompts so they can be tested; ``run_wizard`` is the interactive shell around
them, and ``run_checks`` verifies a finished setup before the first real run.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingbot.config import BotConfig

# (deep, quick) model per provider: a capable model for the managers, a cheaper
# one for the analysts that run most of the calls.
LLM_PRESETS = {
    "openai": ("gpt-6-sol", "gpt-6-luna"),
    "anthropic": ("claude-sonnet-5", "claude-haiku-4-5"),
    "google": ("gemini-3.8-flash", "gemini-3.8-flash"),
}

# Exness symbol suffix by account type.
ACCOUNT_SUFFIXES = {
    "Standard (BTCUSDm)": "m",
    "Standard Cent (BTCUSDc)": "c",
    "Pro / Raw Spread / Zero (BTCUSD)": "",
}

COINS = ["BTC", "ETH", "SOL", "XRP", "LTC", "BNB", "DOGE", "ADA", "DOT", "LINK", "AVAX", "BCH"]


@dataclass
class Answers:
    broker: str = "mt5"              # "mt5" | "paper"
    symbol_suffix: str = "m"
    coins: tuple[str, ...] = ("BTC", "ETH")
    provider: str = "openai"
    language: str = "Thai"
    max_position_pct: float = 0.15
    allow_short: bool = False
    starting_cash: float = 10_000.0  # paper only


def build_config(a: Answers) -> dict:
    """The bot.json content for a set of answers. Validated before it is returned."""
    deep, quick = LLM_PRESETS[a.provider]
    weights = {"Buy": 1.0, "Overweight": 0.5, "Underweight": 0.0,
               "Sell": -0.5 if a.allow_short else 0.0}
    data = {
        "watchlist": [f"{c}-USD" for c in a.coins],
        "broker": a.broker,
        "live": False,
        "analysts": ["market", "social", "news"],
        "currency": "USD",
        "max_position_pct": a.max_position_pct,
        "rating_weights": weights,
        "allow_short": a.allow_short,
        "min_cash_pct": 0.10,
        "min_order_value": 10,
        "max_orders_per_run": 5,
        "fractional": True,
        "state_dir": "~/.tradingagents/bot-exness" if a.broker == "mt5" else "~/.tradingagents/bot-paper",
        "tradingagents": {
            "llm_provider": a.provider,
            "deep_think_llm": deep,
            "quick_think_llm": quick,
            "output_language": a.language,
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
        },
    }
    if a.broker == "mt5":
        data["mt5"] = {"symbol_suffix": a.symbol_suffix, "symbol_map": {}, "magic": 26092601, "deviation": 50}
    else:
        data["starting_cash"] = a.starting_cash
        data["commission_pct"] = 0.001
    BotConfig.model_validate(data)
    return data


_ENV_LINE = re.compile(r"^\s*#?\s*([A-Z0-9_]+)\s*=")


def set_env_value(path: Path, key: str, value: str) -> None:
    """Set ``key=value`` in a .env file, replacing an existing or commented line."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replaced = False
    for i, line in enumerate(lines):
        m = _ENV_LINE.match(line)
        if m and m.group(1) == key and not replaced:
            lines[i] = f"{key}={value}"
            replaced = True
    if not replaced:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_wizard(config_path: Path, env_path: Path, console) -> bool:
    """Ask the setup questions. Returns False when the user cancels."""
    import questionary

    def ask(q):
        answer = q.ask()
        if answer is None:
            raise KeyboardInterrupt
        return answer

    try:
        a = Answers()
        broker = ask(questionary.select(
            "Where should the bot trade?",
            choices=["Exness via MetaTrader 5 (demo account first)", "Paper account (simulated, no broker)"],
        ))
        a.broker = "mt5" if broker.startswith("Exness") else "paper"
        if a.broker == "mt5":
            kind = ask(questionary.select(
                "Exness account type (check the symbol names in MT5 Market Watch)",
                choices=[*ACCOUNT_SUFFIXES, "Other suffix"],
            ))
            a.symbol_suffix = ACCOUNT_SUFFIXES.get(kind) if kind in ACCOUNT_SUFFIXES else ask(
                questionary.text("Suffix after BTCUSD in Market Watch (may be empty):"))
        else:
            a.starting_cash = float(ask(questionary.text("Starting cash (USD):", default="10000")))
        a.coins = tuple(ask(questionary.checkbox(
            "Coins to trade (space to select, enter to confirm)",
            choices=[questionary.Choice(c, checked=c in ("BTC", "ETH")) for c in COINS],
            validate=lambda xs: bool(xs) or "pick at least one",
        )))
        a.provider = ask(questionary.select("AI provider for the analysis", choices=list(LLM_PRESETS)))
        key_env = get_api_key_env(a.provider)
        if key_env and not os.getenv(key_env):
            key = ask(questionary.password(f"{key_env} (paste your API key):"))
            if key.strip():
                set_env_value(env_path, key_env, key.strip())
                os.environ[key_env] = key.strip()
        a.language = ask(questionary.select("Report language", choices=["Thai", "English"]))
        pct = ask(questionary.text("Largest share of equity per coin, in %:", default="15",
                                   validate=lambda s: s.replace(".", "", 1).isdigit() and 0 < float(s) <= 100))
        a.max_position_pct = float(pct) / 100
        a.allow_short = ask(questionary.confirm("Allow short positions on a Sell rating?", default=False))

        if config_path.exists() and not ask(questionary.confirm(f"{config_path} exists. Overwrite?", default=False)):
            console.print("Kept the existing config.")
            return True
        config_path.write_text(json.dumps(build_config(a), indent=2) + "\n", encoding="utf-8")
        console.print(f"[green]Wrote {config_path}[/green]")
        return True
    except KeyboardInterrupt:
        console.print("[yellow]Setup cancelled.[/yellow]")
        return False


def run_checks(cfg: BotConfig, make_broker, console) -> bool:
    """Verify the API key, the broker connection and every watchlist symbol."""
    ok = True

    def report(passed: bool, text: str):
        nonlocal ok
        ok &= passed
        console.print(f"[{'green' if passed else 'red'}]{'OK ' if passed else 'FAIL'}[/] {text}")

    provider = cfg.graph_config()["llm_provider"]
    key_env = get_api_key_env(provider)
    report(not key_env or bool(os.getenv(key_env)),
           f"LLM provider {provider}: " + (f"{key_env} is set" if not key_env or os.getenv(key_env)
                                           else f"{key_env} is missing from .env"))
    try:
        broker = make_broker(cfg)
        acct = broker.account()
        extra = ""
        if cfg.broker == "mt5":
            extra = f" (account {broker.login} on {broker.server}, {'REAL' if broker.is_real else 'demo'})"
        report(True, f"broker {cfg.broker}{extra}: equity {acct.equity:,.2f} {acct.currency}")
    except Exception as exc:
        report(False, f"broker {cfg.broker}: {exc}")
        return False
    for ticker in cfg.watchlist:
        try:
            rules = broker.quantity_rules(ticker)
            price = broker.price(ticker)
            lot = f", min size {rules[1]:g}" if rules else ""
            report(True, f"{ticker}: price {price:,.2f}{lot}")
        except Exception as exc:
            report(False, f"{ticker}: {exc}")
    return ok
