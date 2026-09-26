"""An automated trading bot driven by TradingAgents decisions.

The ``tradingagents`` package decides; it deliberately holds no execution model.
This package is the other half: it reads the book from a broker, asks the graph
for a rating per ticker, turns the rating into a sized order under explicit risk
limits, and sends it. Paper trading is the default; a live account needs both a
config switch and a command-line flag.
"""

from tradingbot.config import BotConfig, load_bot_config
from tradingbot.engine import TickerOutcome, TradingBot
from tradingbot.sizing import OrderPlan, plan_order
