"""The trading bot: sizing, the paper ledger, the run loop and its live guard."""

from __future__ import annotations

import json

import pytest

from tradingbot.brokers import make_broker
from tradingbot.brokers.alpaca import AlpacaBroker, from_alpaca, to_alpaca
from tradingbot.brokers.paper import PaperBroker
from tradingbot.config import BotConfig, load_bot_config
from tradingbot.engine import TradingBot
from tradingbot.journal import Journal
from tradingbot.sizing import NoTrade, OrderPlan, plan_order

pytestmark = pytest.mark.unit

PRICES = {"NVDA": 100.0, "AAPL": 200.0, "BTC-USD": 50_000.0, "PTT.BK": 33.0}


def cfg(tmp_path, **kw) -> BotConfig:
    base = {"watchlist": ["NVDA"], "state_dir": str(tmp_path), "commission_pct": 0.0}
    return BotConfig.model_validate({**base, **kw})


def paper(c: BotConfig, prices=PRICES) -> PaperBroker:
    return make_broker(c, price_source=lambda t: prices[t])


# --- sizing -----------------------------------------------------------------


def test_buy_sizes_to_the_position_limit(tmp_path):
    plan = plan_order(cfg(tmp_path), "NVDA", "Buy", 100.0, 0, buying_power=100_000, equity=100_000)
    assert isinstance(plan, OrderPlan)
    assert (plan.side, plan.quantity) == ("buy", 100)  # 10% of 100k at 100


def test_overweight_takes_its_weight_of_the_limit(tmp_path):
    plan = plan_order(cfg(tmp_path), "NVDA", "Overweight", 100.0, 0, buying_power=100_000, equity=100_000)
    assert plan.quantity == 60


def test_bullish_rating_never_sells_an_oversized_position(tmp_path):
    result = plan_order(cfg(tmp_path), "NVDA", "Overweight", 100.0, 200, buying_power=80_000, equity=100_000)
    assert isinstance(result, NoTrade)


def test_bearish_rating_never_opens_a_position(tmp_path):
    result = plan_order(cfg(tmp_path), "NVDA", "Underweight", 100.0, 0, buying_power=100_000, equity=100_000)
    assert isinstance(result, NoTrade)


def test_underweight_trims_and_sell_exits(tmp_path):
    c = cfg(tmp_path)
    trim = plan_order(c, "NVDA", "Underweight", 100.0, 100, buying_power=90_000, equity=100_000)
    assert (trim.side, trim.quantity) == ("sell", 70)  # down to 30% of the 10k limit
    exit_ = plan_order(c, "NVDA", "Sell", 100.0, 100, buying_power=90_000, equity=100_000)
    assert (exit_.side, exit_.quantity) == ("sell", 100)


@pytest.mark.parametrize("rating", ["Hold", "REVIEW"])
def test_hold_and_review_never_trade(tmp_path, rating):
    assert isinstance(plan_order(cfg(tmp_path), "NVDA", rating, 100.0, 5, 1e5, 1e5), NoTrade)


def test_buy_keeps_the_cash_reserve(tmp_path):
    c = cfg(tmp_path, min_cash_pct=0.05)
    plan = plan_order(c, "NVDA", "Buy", 100.0, 0, buying_power=8_000, equity=100_000)
    assert plan.quantity == 30  # 8k cash - 5k reserve


def test_board_lots_round_down(tmp_path):
    c = cfg(tmp_path, lot_sizes={"ptt.bk": 100})
    plan = plan_order(c, "PTT.BK", "Buy", 33.0, 0, buying_power=100_000, equity=100_000)
    assert plan.quantity == 300  # 10k / 33 = 303 -> 3 lots


def test_fractional_quantities(tmp_path):
    c = cfg(tmp_path, fractional=True)
    plan = plan_order(c, "BTC-USD", "Buy", 50_000.0, 0, buying_power=100_000, equity=100_000)
    assert plan.quantity == pytest.approx(0.2)


def test_small_orders_are_skipped(tmp_path):
    c = cfg(tmp_path, min_order_value=500)
    assert isinstance(plan_order(c, "NVDA", "Buy", 100.0, 0, buying_power=1_000, equity=1_000), NoTrade)


# --- config -----------------------------------------------------------------


def test_config_rejects_live_paper_and_bad_weights(tmp_path):
    with pytest.raises(ValueError):
        cfg(tmp_path, live=True)
    with pytest.raises(ValueError):
        cfg(tmp_path, rating_weights={"Hold": 0.5})
    with pytest.raises(ValueError):
        cfg(tmp_path, analysts=["astrology"])


def test_load_bot_config_reports_the_file(tmp_path):
    path = tmp_path / "bot.json"
    path.write_text(json.dumps({"watchlist": ["nvda", "NVDA", "aapl"]}))
    assert load_bot_config(path).watchlist == ["NVDA", "AAPL"]
    path.write_text("{")
    with pytest.raises(ValueError, match="bot.json"):
        load_bot_config(path)


def test_graph_config_merges_nested_overrides(tmp_path):
    c = cfg(tmp_path, tradingagents={"llm_provider": "anthropic",
                                     "data_vendors": {"fundamental_data": "sec_edgar,yfinance"}})
    gc = c.graph_config()
    assert gc["llm_provider"] == "anthropic"
    assert gc["data_vendors"]["fundamental_data"] == "sec_edgar,yfinance"
    assert "core_stock_apis" in gc["data_vendors"]


def test_live_needs_both_config_and_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "k")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "s")
    live = cfg(tmp_path, broker="alpaca", live=True)
    with pytest.raises(PermissionError):
        make_broker(live, allow_live=False, price_source=PRICES.get)
    with pytest.raises(PermissionError):
        make_broker(cfg(tmp_path, broker="alpaca"), allow_live=True, price_source=PRICES.get)
    assert make_broker(live, allow_live=True, price_source=PRICES.get).base_url.startswith("https://api.")
    assert "paper" in make_broker(cfg(tmp_path, broker="alpaca"), price_source=PRICES.get).base_url


# --- paper broker -----------------------------------------------------------


def test_paper_ledger_round_trip_persists(tmp_path):
    c = cfg(tmp_path, commission_pct=0.001)
    b = paper(c)
    assert b.submit("NVDA", "buy", 10).status == "filled"
    assert b.account().cash == pytest.approx(100_000 - 1000 - 1)
    again = paper(c)  # reloaded from disk
    assert again.holdings()["NVDA"].quantity == 10
    assert again.submit("NVDA", "sell", 11).status == "rejected"
    assert again.submit("NVDA", "sell", 10).status == "filled"
    assert "NVDA" not in again.holdings()
    assert again.submit("NVDA", "buy", 10_000).status == "rejected"


# --- engine -----------------------------------------------------------------


class FakeGraph:
    def __init__(self, ratings):
        self.ratings = ratings
        self.calls = []

    def propagate(self, ticker, trade_date, asset_type="stock", portfolio=None):
        self.calls.append((ticker, trade_date, asset_type, portfolio))
        rating = self.ratings[ticker]
        if isinstance(rating, Exception):
            raise rating
        return {"final_trade_decision": f"**Rating**: {rating}"}, rating


def make_bot(tmp_path, ratings, **kw):
    c = cfg(tmp_path, **kw)
    graph = FakeGraph(ratings)
    seen = []

    def factory(analysts):
        seen.append(analysts)
        return graph

    bot = TradingBot(c, paper(c), graph_factory=factory, today=lambda: "2026-09-25")
    return bot, graph, seen


def test_run_once_trades_records_and_passes_the_book(tmp_path):
    bot, graph, _ = make_bot(tmp_path, {"NVDA": "Buy", "AAPL": "Hold"}, watchlist=["NVDA", "AAPL"])
    outcomes = bot.run_once()
    assert outcomes[0].order.status == "filled" and outcomes[0].order.quantity == 100
    assert outcomes[1].order is None and "Hold" in outcomes[1].skipped
    # the second ticker's agents saw the position the first one opened
    assert graph.calls[1][3].position_in("NVDA").quantity == 100
    entries = Journal(tmp_path / "journal.jsonl").entries()
    assert [e["rating"] for e in entries] == ["Buy", "Hold"]


def test_second_run_same_day_is_skipped_unless_forced(tmp_path):
    bot, graph, _ = make_bot(tmp_path, {"NVDA": "Buy"})
    bot.run_once()
    assert "already decided" in bot.run_once()[0].skipped
    assert len(graph.calls) == 1
    bot.run_once(force=True)
    assert len(graph.calls) == 2


def test_dry_run_sends_nothing_and_does_not_block_the_real_run(tmp_path):
    bot, _, _ = make_bot(tmp_path, {"NVDA": "Buy"})
    dry = bot.run_once(execute=False)[0]
    assert dry.plan is not None and dry.order is None
    assert bot.broker.holdings() == {}
    assert bot.run_once()[0].order.status == "filled"


def test_one_failing_ticker_does_not_stop_the_rest(tmp_path):
    bot, _, _ = make_bot(tmp_path, {"NVDA": RuntimeError("boom"), "AAPL": "Buy"},
                         watchlist=["NVDA", "AAPL"])
    bad, good = bot.run_once()
    assert "boom" in bad.error
    assert good.order.status == "filled"


def test_order_cap_per_run(tmp_path):
    bot, _, _ = make_bot(tmp_path, {"NVDA": "Buy", "AAPL": "Buy"},
                         watchlist=["NVDA", "AAPL"], max_orders_per_run=1)
    first, second = bot.run_once()
    assert first.order is not None
    assert second.order is None and "max_orders_per_run" in second.skipped


def test_crypto_runs_without_fundamentals(tmp_path):
    bot, graph, seen = make_bot(tmp_path, {"BTC-USD": "Buy"}, watchlist=["BTC-USD"], fractional=True)
    bot.run_once()
    assert "fundamentals" not in seen[0]
    assert graph.calls[0][2] == "crypto"


# --- alpaca -----------------------------------------------------------------


class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, json.dumps(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self):
        self.headers, self.posted = {}, []

    def get(self, url, timeout):
        if url.endswith("/v2/account"):
            return FakeResponse({"cash": "1000", "equity": "5000", "currency": "USD"})
        return FakeResponse([{"symbol": "BTCUSD", "qty": "0.5", "avg_entry_price": "40000"}])

    def post(self, url, json, timeout):
        self.posted.append(json)
        return FakeResponse({"id": "abc", "status": "accepted"})


def test_alpaca_maps_symbols_and_orders(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "k")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "s")
    session = FakeSession()
    b = AlpacaBroker(price_source=PRICES.get, session=session)
    assert b.account().equity == 5000
    assert b.holdings()["BTC-USD"].quantity == 0.5
    result = b.submit("BTC-USD", "buy", 0.25)
    assert result.status == "submitted" and result.order_id == "abc"
    assert session.posted[0] == {"symbol": "BTC/USD", "qty": "0.25", "side": "buy",
                                 "type": "market", "time_in_force": "gtc"}
    assert (to_alpaca("NVDA"), from_alpaca("ETHUSD")) == ("NVDA", "ETH-USD")


# --- shorts -----------------------------------------------------------------


def short_cfg(tmp_path, **kw):
    return cfg(tmp_path, allow_short=True,
               rating_weights={"Buy": 1.0, "Overweight": 0.5, "Underweight": 0.0, "Sell": -0.5}, **kw)


def test_negative_weights_need_allow_short(tmp_path):
    with pytest.raises(ValueError, match="allow_short"):
        cfg(tmp_path, rating_weights={"Sell": -0.5})
    with pytest.raises(ValueError, match="bullish"):
        cfg(tmp_path, allow_short=True, rating_weights={"Buy": -0.5})


def test_sell_flips_a_long_into_a_short(tmp_path):
    plan = plan_order(short_cfg(tmp_path), "NVDA", "Sell", 100.0, 100, buying_power=90_000, equity=100_000)
    assert (plan.side, plan.quantity) == ("sell", 150)  # close 100, open 50 short (5k)


def test_short_opening_is_limited_by_buying_power(tmp_path):
    c = short_cfg(tmp_path, min_cash_pct=0.0)
    plan = plan_order(c, "NVDA", "Sell", 100.0, 0, buying_power=2_000, equity=100_000)
    assert plan.quantity == 20


def test_underweight_does_not_cover_a_short_and_buy_does(tmp_path):
    c = short_cfg(tmp_path)
    assert isinstance(plan_order(c, "NVDA", "Underweight", 100.0, -50, 90_000, 100_000), NoTrade)
    plan = plan_order(c, "NVDA", "Buy", 100.0, -50, buying_power=0, equity=100_000)
    assert (plan.side, plan.quantity) == ("buy", 50)  # covering needs no buying power


def test_paper_broker_shorts_and_covers(tmp_path):
    c = short_cfg(tmp_path)
    prices = dict(PRICES)
    b = paper(c, prices)
    assert b.submit("NVDA", "sell", 10).status == "filled"
    assert b.holdings()["NVDA"].quantity == -10
    prices["NVDA"] = 90.0
    b.refresh()
    acct = b.account()
    assert acct.equity == pytest.approx(100_100)  # +10 x 10 on the short
    assert acct.buying_power == pytest.approx(100_100 - 900)
    assert b.submit("NVDA", "buy", 10).status == "filled"
    assert b.holdings() == {}
    assert b.account().cash == pytest.approx(100_100)


def test_paper_broker_refuses_shorts_when_off(tmp_path):
    assert paper(cfg(tmp_path)).submit("NVDA", "sell", 1).status == "rejected"


def test_crypto_tickers_are_canonical(tmp_path):
    c = cfg(tmp_path, watchlist=["btcusd", "BTC-USDT", "bnb-usd", "nvda"])
    assert c.watchlist == ["BTC-USD", "BNB-USD", "NVDA"]


# --- mt5 --------------------------------------------------------------------


class NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeMT5:
    """Just enough of the MetaTrader5 module: a hedging account with BTCUSDm."""

    TRADE_RETCODE_DONE = 10009
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1

    def __init__(self, trade_mode=0, hedging=True):
        self.trade_mode, self.margin_mode = trade_mode, 2 if hedging else 0
        self.positions, self.requests, self._next = [], [], 1
        self.symbols = {"BTCUSDm": NS(trade_contract_size=1.0, volume_step=0.01, volume_min=0.01,
                                      volume_max=100.0, filling_mode=2)}

    def initialize(self, **kw):
        self.init_kwargs = kw
        return True

    def shutdown(self):
        pass

    def last_error(self):
        return (0, "ok")

    def account_info(self):
        return NS(login=1, server="Exness-MT5Trial", trade_mode=self.trade_mode,
                  margin_mode=self.margin_mode, balance=10_000.0, equity=10_000.0,
                  margin_free=9_000.0, currency="USD")

    def symbol_info(self, sym):
        return self.symbols.get(sym)

    def symbol_select(self, sym, enable):
        return sym in self.symbols

    def symbol_info_tick(self, sym):
        return NS(bid=49_990.0, ask=50_010.0)

    def positions_get(self, symbol=None):
        return tuple(p for p in self.positions if symbol in (None, p.symbol))

    def order_send(self, req):
        self.requests.append(req)
        self._next += 1
        if "position" in req:
            pos = next(p for p in self.positions if p.ticket == req["position"])
            pos.volume = round(pos.volume - req["volume"], 8)
            if pos.volume <= 0:
                self.positions.remove(pos)
        else:
            self.positions.append(NS(ticket=self._next, time=self._next, symbol=req["symbol"],
                                     type=req["type"], volume=req["volume"], magic=req["magic"],
                                     price_open=req["price"], price_current=req["price"]))
        return NS(retcode=10009, volume=req["volume"], price=req["price"], order=self._next, comment="done")


def mt5_broker(tmp_path, fake, live=False, **kw):
    from tradingbot.brokers.mt5 import MT5Broker
    c = cfg(tmp_path, broker="mt5", live=live, mt5={"symbol_suffix": "m"}, **kw)
    return MT5Broker(c.mt5, live=live, mt5_module=fake)


def test_mt5_refuses_a_real_account_without_live(tmp_path):
    with pytest.raises(PermissionError, match="REAL"):
        mt5_broker(tmp_path, FakeMT5(trade_mode=2))
    assert mt5_broker(tmp_path, FakeMT5(trade_mode=2), live=True).is_real


def test_mt5_maps_symbols_and_sizes_in_lots(tmp_path):
    fake = FakeMT5()
    b = mt5_broker(tmp_path, fake)
    assert b.symbol("BTC-USD") == "BTCUSDm"
    assert b.quantity_rules("BTC-USD") == (0.01, 0.01)
    assert b.price("BTC-USD") == 50_000.0
    with pytest.raises(ValueError, match="symbol_map"):
        b.symbol("DOGE-USD")
    result = b.submit("BTC-USD", "buy", 0.057)
    assert result.status == "filled" and result.quantity == pytest.approx(0.05)
    assert fake.requests[0]["volume"] == 0.05 and fake.requests[0]["type_filling"] == 1  # IOC
    assert b.holdings()["BTC-USD"].quantity == pytest.approx(0.05)


def test_mt5_hedging_closes_own_positions_before_opening(tmp_path):
    fake = FakeMT5()
    b = mt5_broker(tmp_path, fake)
    b.submit("BTC-USD", "buy", 0.05)
    # a manual trade on the same symbol, which the bot must not touch
    fake.positions.append(NS(ticket=999, time=0, symbol="BTCUSDm", type=0, volume=1.0, magic=0,
                             price_open=40_000.0, price_current=50_000.0))
    result = b.submit("BTC-USD", "sell", 0.08)  # close 0.05, open 0.03 short
    assert result.status == "filled"
    assert fake.requests[1]["position"] != 999 and fake.requests[1]["volume"] == 0.05
    assert "position" not in fake.requests[2] and fake.requests[2]["volume"] == 0.03
    assert b.holdings()["BTC-USD"].quantity == pytest.approx(-0.03)
    assert any(p.ticket == 999 and p.volume == 1.0 for p in fake.positions)
    # the manual position still counts against the bot's buying power
    # (the short filled at the 49,990 bid)
    assert b.account().buying_power == pytest.approx(10_000 - 1.0 * 50_000 - 0.03 * 49_990)


def test_engine_trades_crypto_on_mt5_with_lot_rules(tmp_path):
    fake = FakeMT5()
    c = cfg(tmp_path, broker="mt5", mt5={"symbol_suffix": "m"}, watchlist=["BTCUSD"],
            max_position_pct=0.5, min_cash_pct=0.0)
    from tradingbot.brokers.mt5 import MT5Broker
    bot = TradingBot(c, MT5Broker(c.mt5, mt5_module=fake),
                     graph_factory=lambda a: FakeGraph({"BTC-USD": "Buy"}), today=lambda: "2026-09-25")
    outcome = bot.run_once()[0]
    assert outcome.order.status == "filled"
    assert fake.requests[0]["volume"] == 0.1  # half of 10,000 equity at 50,000 a coin


def test_unknown_mt5_symbol_fails_before_the_analysis(tmp_path):
    from tradingbot.brokers.mt5 import MT5Broker
    c = cfg(tmp_path, broker="mt5", mt5={"symbol_suffix": "m"}, watchlist=["DOGE-USD"])
    graph = FakeGraph({"DOGE-USD": "Buy"})
    bot = TradingBot(c, MT5Broker(c.mt5, mt5_module=FakeMT5()),
                     graph_factory=lambda a: graph, today=lambda: "2026-09-25")
    outcome = bot.run_once(tickers=["dogeusd"])[0]
    assert outcome.ticker == "DOGE-USD" and "symbol_map" in outcome.error
    assert graph.calls == []


# --- setup wizard and checks ------------------------------------------------


def test_wizard_config_for_exness_is_valid(tmp_path):
    from tradingbot.wizard import Answers, build_config
    data = build_config(Answers(broker="mt5", symbol_suffix="c", coins=("BTC", "SOL"),
                                provider="anthropic", allow_short=True))
    c = BotConfig.model_validate(data)
    assert c.watchlist == ["BTC-USD", "SOL-USD"]
    assert c.mt5.symbol_suffix == "c" and not c.live
    assert c.rating_weights["Sell"] == -0.5 and c.allow_short
    assert c.graph_config()["deep_think_llm"] == "claude-sonnet-5"


def test_wizard_config_for_paper_is_long_only(tmp_path):
    from tradingbot.wizard import Answers, build_config
    c = BotConfig.model_validate(build_config(Answers(broker="paper", starting_cash=5000)))
    assert c.broker == "paper" and c.starting_cash == 5000 and c.rating_weights["Sell"] == 0.0


def test_set_env_value_replaces_blank_and_commented_lines(tmp_path):
    from tradingbot.wizard import set_env_value
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=\n#MT5_LOGIN=\nOTHER=1\n")
    set_env_value(env, "OPENAI_API_KEY", "sk-1")
    set_env_value(env, "MT5_LOGIN", "123")
    set_env_value(env, "NEW_KEY", "x")
    assert env.read_text() == "OPENAI_API_KEY=sk-1\nMT5_LOGIN=123\nOTHER=1\nNEW_KEY=x\n"


def test_checks_report_missing_key_and_bad_symbol(tmp_path, monkeypatch):
    from rich.console import Console

    from tradingbot.brokers.mt5 import MT5Broker
    from tradingbot.wizard import run_checks
    monkeypatch.setenv("OPENAI_API_KEY", "")
    c = cfg(tmp_path, broker="mt5", mt5={"symbol_suffix": "m"}, watchlist=["BTC-USD", "DOGE-USD"],
            tradingagents={"llm_provider": "openai"})
    console = Console(record=True, width=200)
    ok = run_checks(c, lambda cfg_: MT5Broker(cfg_.mt5, mt5_module=FakeMT5()), console)
    text = console.export_text()
    assert not ok
    assert "OPENAI_API_KEY is missing" in text
    assert "OK  BTC-USD: price 50,000.00, min size 0.01" in text
    assert "FAIL DOGE-USD" in text and "demo" in text
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    c2 = c.model_copy(update={"watchlist": ["BTC-USD"]})
    assert run_checks(c2, lambda cfg_: MT5Broker(cfg_.mt5, mt5_module=FakeMT5()), Console(record=True))


def test_wizard_flow_writes_config_and_key(tmp_path, monkeypatch):
    import sys
    import types

    from rich.console import Console

    from tradingbot.wizard import run_wizard

    answers = iter(["Exness via MetaTrader 5 (demo account first)", "Standard (BTCUSDm)",
                    ["BTC", "ETH"], "anthropic", "sk-ant-1", "Thai", "20", True])

    class Q:
        def __init__(self, *a, validate=None, **kw):
            self.validate = validate

        def ask(self):
            value = next(answers)
            if self.validate is not None:
                assert self.validate(value) is True
            return value

    fake = types.SimpleNamespace(select=Q, text=Q, password=Q, confirm=Q, checkbox=Q,
                                 Choice=lambda title, checked=False: title)
    monkeypatch.setitem(sys.modules, "questionary", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # blank reads as unset; restored after the test
    config, env = tmp_path / "bot.json", tmp_path / ".env"
    assert run_wizard(config, env, Console(record=True))
    c = load_bot_config(config)
    assert c.broker == "mt5" and c.mt5.symbol_suffix == "m"
    assert c.watchlist == ["BTC-USD", "ETH-USD"] and c.max_position_pct == 0.2 and c.allow_short
    assert c.graph_config()["output_language"] == "Thai"
    assert env.read_text() == "ANTHROPIC_API_KEY=sk-ant-1\n"
