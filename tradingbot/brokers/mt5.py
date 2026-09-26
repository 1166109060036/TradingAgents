"""MetaTrader 5 accounts (Exness and other MT5 brokers), crypto and forex CFDs.

Runs where the MetaTrader5 Python package runs: Windows, with the MT5 terminal
installed. Login comes from MT5_LOGIN, MT5_PASSWORD and MT5_SERVER (for Exness,
e.g. ``Exness-MT5Trial7`` for a demo account); leave them unset to use the
account the open terminal is already logged into. MT5_PATH points at a
terminal64.exe that is not in the default location.

Quantities cross this boundary in units of the instrument (coins, for crypto)
and are converted to lots with the symbol's contract size. The bot only manages
positions carrying its magic number, so trades placed by hand on the same
account are never closed by it.
"""

from __future__ import annotations

import importlib
import math
import os
from collections.abc import Callable

from tradingbot.brokers.base import Account, Broker, Holding, OrderResult
from tradingbot.config import MT5Settings
from tradingbot.symbols import canonical_ticker, crypto_coin

# Bits of symbol_info().filling_mode (SYMBOL_FILLING_FOK / _IOC in MQL5).
_FILLING_FOK, _FILLING_IOC = 1, 2
_RETCODE_DONE = 10009
_ACCOUNT_REAL = 2
_MARGIN_HEDGING = 2


def _const(mt5, name: str, default: int) -> int:
    return getattr(mt5, name, default)


class MT5Broker(Broker):
    name = "mt5"

    def __init__(
        self,
        settings: MT5Settings,
        live: bool = False,
        price_fallback: Callable[[str], float] | None = None,
        mt5_module=None,
    ):
        if mt5_module is None:
            try:
                mt5_module = importlib.import_module("MetaTrader5")
            except ImportError as exc:
                raise ValueError(
                    "the mt5 broker needs the MetaTrader5 package, which runs only on Windows "
                    "with the MT5 terminal installed: pip install MetaTrader5"
                ) from exc
        self.mt5 = mt5 = mt5_module
        self.settings = settings
        self._price_fallback = price_fallback
        self._tickers: dict[str, str] = {}

        kwargs = {}
        if os.getenv("MT5_PATH"):
            kwargs["path"] = os.environ["MT5_PATH"]
        if os.getenv("MT5_LOGIN"):
            kwargs.update(login=int(os.environ["MT5_LOGIN"]), password=os.getenv("MT5_PASSWORD", ""),
                          server=os.getenv("MT5_SERVER", ""))
        if not mt5.initialize(**kwargs):
            raise ConnectionError(f"could not connect to the MT5 terminal: {mt5.last_error()}")

        info = mt5.account_info()
        if info is None:
            raise ConnectionError(f"MT5 terminal has no logged-in account: {mt5.last_error()}")
        if info.trade_mode == _const(mt5, "ACCOUNT_TRADE_MODE_REAL", _ACCOUNT_REAL) and not live:
            mt5.shutdown()
            raise PermissionError(
                f"MT5 account {info.login} on {info.server} is a REAL-money account; "
                "set live=true in the config and pass --live to trade it"
            )
        self.is_real = info.trade_mode == _const(mt5, "ACCOUNT_TRADE_MODE_REAL", _ACCOUNT_REAL)
        self.hedging = info.margin_mode == _const(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", _MARGIN_HEDGING)
        self.login, self.server = info.login, info.server

    # --- symbols ------------------------------------------------------------

    def symbol(self, ticker: str) -> str:
        """The broker's symbol for a ticker, e.g. BTC-USD -> BTCUSDm on Exness Standard."""
        ticker = canonical_ticker(ticker)
        sym = self.settings.symbol_map.get(ticker)
        if sym is None:
            coin = crypto_coin(ticker)
            base = f"{coin}USD" if coin else ticker.replace("=X", "").replace("-", "")
            sym = base + self.settings.symbol_suffix
        if self.mt5.symbol_info(sym) is None or not self.mt5.symbol_select(sym, True):
            raise ValueError(
                f"{sym} is not offered on MT5 account {self.login}; "
                f"map it with mt5.symbol_map, e.g. {{\"{ticker}\": \"<symbol in Market Watch>\"}}"
            )
        self._tickers[sym] = ticker
        return sym

    def _ticker_of(self, sym: str) -> str:
        if sym in self._tickers:
            return self._tickers[sym]
        for ticker, mapped in self.settings.symbol_map.items():
            if mapped == sym:
                return ticker
        suffix = self.settings.symbol_suffix
        bare = sym[: -len(suffix)] if suffix and sym.endswith(suffix) else sym
        return canonical_ticker(bare)

    def _contract(self, sym: str) -> float:
        return float(self.mt5.symbol_info(sym).trade_contract_size or 1.0)

    def quantity_rules(self, ticker: str):
        sym = self.symbol(ticker)
        info = self.mt5.symbol_info(sym)
        contract = float(info.trade_contract_size or 1.0)
        return info.volume_step * contract, info.volume_min * contract

    # --- account ------------------------------------------------------------

    def _own_positions(self, sym: str | None = None):
        positions = self.mt5.positions_get(symbol=sym) if sym else self.mt5.positions_get()
        return [p for p in (positions or ()) if p.magic == self.settings.magic]

    def account(self) -> Account:
        info = self.mt5.account_info()
        # Every open position counts against exposure, the bot's and any placed by hand.
        gross = sum(
            p.volume * self._contract(p.symbol) * p.price_current for p in (self.mt5.positions_get() or ())
        )
        return Account(cash=info.balance, equity=info.equity, currency=info.currency,
                       buying_power=min(info.equity - gross, info.margin_free))

    def holdings(self) -> dict[str, Holding]:
        buy_type = _const(self.mt5, "POSITION_TYPE_BUY", 0)
        net: dict[str, list[float]] = {}
        for p in self._own_positions():
            units = p.volume * self._contract(p.symbol) * (1 if p.type == buy_type else -1)
            q, cost = net.setdefault(self._ticker_of(p.symbol), [0.0, 0.0])
            net[self._ticker_of(p.symbol)] = [q + units, cost + units * p.price_open]
        return {
            t: Holding(t, q, cost / q if q else None)
            for t, (q, cost) in net.items() if abs(q) > 1e-12
        }

    def price(self, ticker: str) -> float:
        tick = self.mt5.symbol_info_tick(self.symbol(ticker))
        if tick is not None and tick.bid > 0 and tick.ask > 0:
            return (tick.bid + tick.ask) / 2
        if self._price_fallback is not None:
            return float(self._price_fallback(ticker))
        raise ValueError(f"no MT5 quote for {ticker}")

    # --- orders -------------------------------------------------------------

    def _filling(self, sym: str) -> int:
        mode = self.mt5.symbol_info(sym).filling_mode
        if mode & _FILLING_FOK:
            return _const(self.mt5, "ORDER_FILLING_FOK", 0)
        if mode & _FILLING_IOC:
            return _const(self.mt5, "ORDER_FILLING_IOC", 1)
        return _const(self.mt5, "ORDER_FILLING_RETURN", 2)

    def _deal(self, sym: str, side: str, lots: float, position: int | None = None):
        mt5 = self.mt5
        tick = mt5.symbol_info_tick(sym)
        request = {
            "action": _const(mt5, "TRADE_ACTION_DEAL", 1),
            "symbol": sym,
            "volume": lots,
            "type": _const(mt5, "ORDER_TYPE_BUY", 0) if side == "buy" else _const(mt5, "ORDER_TYPE_SELL", 1),
            "price": tick.ask if side == "buy" else tick.bid,
            "deviation": self.settings.deviation,
            "magic": self.settings.magic,
            "comment": "tradingbot",
            "type_time": _const(mt5, "ORDER_TIME_GTC", 0),
            "type_filling": self._filling(sym),
        }
        if position is not None:
            request["position"] = position
        result = mt5.order_send(request)
        if result is None:
            return None, f"order_send failed: {mt5.last_error()}"
        if result.retcode != _const(mt5, "TRADE_RETCODE_DONE", _RETCODE_DONE):
            return None, f"retcode {result.retcode}: {result.comment}"
        return result, ""

    def _lots(self, info, units: float) -> float:
        step = info.volume_step
        lots = math.floor(units / float(info.trade_contract_size or 1.0) / step + 1e-9) * step
        return round(lots, 8)

    def submit(self, ticker: str, side: str, quantity: float) -> OrderResult:
        sym = self.symbol(ticker)
        info = self.mt5.symbol_info(sym)
        remaining = self._lots(info, quantity)
        if remaining < info.volume_min:
            return OrderResult(ticker, side, quantity, "rejected", message=f"below {info.volume_min} lots")

        fills, notes = [], []
        if self.hedging:
            # A hedging account opens a new ticket for an opposite deal; close ours first.
            opposite = _const(self.mt5, "POSITION_TYPE_SELL", 1) if side == "buy" \
                else _const(self.mt5, "POSITION_TYPE_BUY", 0)
            for p in sorted(self._own_positions(sym), key=lambda p: p.time):
                if remaining <= 0 or p.type != opposite:
                    continue
                lots = round(min(p.volume, remaining), 8)
                result, err = self._deal(sym, side, lots, position=p.ticket)
                if result is None:
                    notes.append(err)
                    break
                fills.append(result)
                remaining = round(remaining - lots, 8)
        while remaining >= info.volume_min and not notes:
            lots = min(remaining, info.volume_max)
            result, err = self._deal(sym, side, lots)
            if result is None:
                notes.append(err)
                break
            fills.append(result)
            remaining = round(remaining - lots, 8)

        filled_lots = sum(r.volume for r in fills)
        contract = float(info.trade_contract_size or 1.0)
        status = "filled" if fills and not notes else ("partial" if fills else "rejected")
        return OrderResult(
            ticker, side, filled_lots * contract if fills else quantity, status,
            fill_price=fills[-1].price if fills else None,
            order_id=",".join(str(r.order) for r in fills) or None,
            message=f"{sym} {filled_lots:g} lots" + (f"; {notes[0]}" if notes else ""),
        )
