import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf

from broker import AlpacaAuthClient, AlpacaBroker, IbkrBroker, PaperBroker
from strategy import Lucky13EmaStrategy


DEFAULT_AUTO_CONFIG = {
    "symbol": "IONQ",
    "timeframe": "1m",
    "capital": 30000.0,
    "position_size_pct": 1.0,
    "poll_seconds": 15,
    "dry_run": True,
    "risk": {
        "enabled": True,
        "max_drawdown_pct": 5.0,
        "max_trades_per_day": 5,
        "kill_switch_file": "kill_switch.txt",
    },
    "market": {
        "enabled": True,
        "calendar": "XNYS",
        "timezone": "America/New_York",
    },
    "logging": {
        "enabled": True,
        "path": "logs/auto_trader.jsonl",
    },
    "trade_journal": {
        "enabled": True,
        "format": "csv",
        "path": "logs/trade_journal.csv",
    },
    "broker": {
        "name": "paper",
        "paper": True,
        "base_url": "https://paper-api.alpaca.markets/v2",
        "api_key_env": "ALPACA_API_KEY",
        "api_secret_env": "ALPACA_API_SECRET",
        "oauth_client_id_env": "ALPACA_OAUTH_CLIENT_ID",
        "oauth_client_secret_env": "ALPACA_OAUTH_CLIENT_SECRET",
        "oauth_auth_base_url": "https://authx.alpaca.markets/v1",
        "host": "127.0.0.1",
        "port": 7497,
        "client_id": 1,
        "exchange": "SMART",
        "currency": "USD",
    },
}


def deep_merge(base, override):
    merged = base.copy()
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merged[key] = deep_merge(base[key], value)
        else:
            merged[key] = value
    return merged


def resolve_path(path_value):
    path = Path(path_value)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


def load_config():
    config_path = Path(__file__).with_name("config.json")
    with config_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    merged = deep_merge(DEFAULT_AUTO_CONFIG, raw)

    local_config_path = Path(__file__).with_name("config.local.json")
    if local_config_path.exists():
        with local_config_path.open("r", encoding="utf-8") as f:
            local_raw = json.load(f)
        merged = deep_merge(merged, local_raw)

    return merged


class StructuredLogger:
    def __init__(self, config):
        logging_config = config["logging"]
        self.enabled = bool(logging_config["enabled"])
        self.path = resolve_path(logging_config["path"])
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event, **fields):
        payload = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        message = json.dumps(payload, default=str)
        print(message)
        if self.enabled:
            with self.path.open("a", encoding="utf-8") as log_file:
                log_file.write(message + "\n")


class TradeJournal:
    FIELDS = [
        "timestamp",
        "symbol",
        "action",
        "qty",
        "price",
        "realized_pnl",
        "equity",
        "drawdown_pct",
        "broker",
        "note",
    ]

    def __init__(self, config):
        journal_config = config["trade_journal"]
        self.enabled = bool(journal_config["enabled"])
        self.format = str(journal_config["format"]).lower()
        self.path = resolve_path(journal_config["path"])
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.format == "sqlite":
                self._init_sqlite()

    def _init_sqlite(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    price REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    equity REAL NOT NULL,
                    drawdown_pct REAL NOT NULL,
                    broker TEXT NOT NULL,
                    note TEXT NOT NULL
                )
                """
            )

    def record(self, entry):
        if not self.enabled:
            return
        if self.format == "csv":
            self._record_csv(entry)
            return
        if self.format == "sqlite":
            self._record_sqlite(entry)
            return
        raise ValueError(f"Unsupported trade journal format: {self.format}")

    def _record_csv(self, entry):
        file_exists = self.path.exists()
        with self.path.open("a", encoding="utf-8") as csv_file:
            if not file_exists:
                csv_file.write(",".join(self.FIELDS) + "\n")
            csv_file.write(",".join(str(entry[field]) for field in self.FIELDS) + "\n")

    def _record_sqlite(self, entry):
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO trades (
                    timestamp, symbol, action, qty, price,
                    realized_pnl, equity, drawdown_pct, broker, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(entry[field] for field in self.FIELDS),
            )


class RiskManager:
    def __init__(self, config):
        risk_config = config["risk"]
        self.enabled = bool(risk_config["enabled"])
        self.starting_capital = float(config["capital"])
        self.max_drawdown_pct = float(risk_config["max_drawdown_pct"])
        self.max_trades_per_day = int(risk_config["max_trades_per_day"])
        self.kill_switch_file = resolve_path(risk_config["kill_switch_file"])
        self.position_qty = 0
        self.entry_price = 0.0
        self.realized_pnl = 0.0
        self.peak_equity = self.starting_capital
        self.trade_counts = {}

    def _trade_day(self, timestamp):
        return pd.Timestamp(timestamp).date().isoformat()

    def _unrealized_pnl(self, last_price):
        if self.position_qty > 0:
            return (float(last_price) - self.entry_price) * self.position_qty
        if self.position_qty < 0:
            return (self.entry_price - float(last_price)) * abs(self.position_qty)
        return 0.0

    def equity_snapshot(self, last_price):
        equity = self.starting_capital + self.realized_pnl + self._unrealized_pnl(last_price)
        self.peak_equity = max(self.peak_equity, equity)
        if self.peak_equity <= 0:
            drawdown_pct = 0.0
        else:
            drawdown_pct = max(0.0, (self.peak_equity - equity) / self.peak_equity * 100.0)
        return equity, drawdown_pct

    def allow_action(self, action, timestamp, last_price):
        if not self.enabled or not action.startswith("enter"):
            return True, None
        if self.kill_switch_file.exists():
            return False, "kill switch active"

        trade_day = self._trade_day(timestamp)
        if self.max_trades_per_day > 0 and self.trade_counts.get(trade_day, 0) >= self.max_trades_per_day:
            return False, "max trades per day reached"

        _, drawdown_pct = self.equity_snapshot(last_price)
        if self.max_drawdown_pct > 0 and drawdown_pct >= self.max_drawdown_pct:
            return False, "max drawdown reached"

        return True, None

    def record_action(self, symbol, action, qty, price, timestamp, broker_name, note=""):
        price = float(price)
        qty = int(qty)
        trade_day = self._trade_day(timestamp)

        if action == "enter_long":
            if self.position_qty < 0:
                self.realized_pnl += (self.entry_price - price) * abs(self.position_qty)
            self.position_qty = qty
            self.entry_price = price
            self.trade_counts[trade_day] = self.trade_counts.get(trade_day, 0) + 1
        elif action == "enter_short":
            if self.position_qty > 0:
                self.realized_pnl += (price - self.entry_price) * self.position_qty
            self.position_qty = -qty
            self.entry_price = price
            self.trade_counts[trade_day] = self.trade_counts.get(trade_day, 0) + 1
        elif action == "exit_long" and self.position_qty > 0:
            qty = abs(self.position_qty)
            self.realized_pnl += (price - self.entry_price) * self.position_qty
            self.position_qty = 0
            self.entry_price = 0.0
        elif action == "exit_short" and self.position_qty < 0:
            qty = abs(self.position_qty)
            self.realized_pnl += (self.entry_price - price) * abs(self.position_qty)
            self.position_qty = 0
            self.entry_price = 0.0

        equity, drawdown_pct = self.equity_snapshot(price)
        return {
            "timestamp": str(timestamp),
            "symbol": symbol,
            "action": action,
            "qty": qty,
            "price": price,
            "realized_pnl": round(self.realized_pnl, 4),
            "equity": round(equity, 4),
            "drawdown_pct": round(drawdown_pct, 4),
            "broker": broker_name,
            "note": note,
        }


def normalize_timestamp(timestamp, timezone_name):
    parsed = pd.Timestamp(timestamp)
    tz = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        return parsed.tz_localize(tz)
    return parsed.tz_convert(tz)


def is_market_open(timestamp, config, calendar=None):
    market_config = config["market"]
    if not bool(market_config["enabled"]):
        return True

    market_ts = normalize_timestamp(timestamp, market_config["timezone"])
    calendar_obj = calendar or mcal.get_calendar(market_config["calendar"])
    session_date = market_ts.date().isoformat()
    schedule = calendar_obj.schedule(start_date=session_date, end_date=session_date)
    if schedule.empty:
        return False

    market_open = pd.Timestamp(schedule.iloc[0]["market_open"]).tz_convert(market_ts.tzinfo)
    market_close = pd.Timestamp(schedule.iloc[0]["market_close"]).tz_convert(market_ts.tzinfo)
    return market_open <= market_ts <= market_close


def make_broker(config):
    broker_name = str(config["broker"]["name"]).lower()
    if broker_name == "paper":
        return PaperBroker()

    if broker_name == "alpaca":
        oauth_client_id = config["broker"].get("oauth_client_id") or os.getenv(
            config["broker"].get("oauth_client_id_env", "")
        )
        oauth_client_secret = config["broker"].get("oauth_client_secret") or os.getenv(
            config["broker"].get("oauth_client_secret_env", "")
        )

        auth_client = None
        if oauth_client_id and oauth_client_secret:
            auth_client = AlpacaAuthClient(
                oauth_client_id,
                oauth_client_secret,
                auth_base_url=config["broker"].get("oauth_auth_base_url", "https://authx.alpaca.markets/v1"),
            )

        api_key = config["broker"].get("api_key") or os.getenv(config["broker"].get("api_key_env", ""))
        api_secret = config["broker"].get("api_secret") or os.getenv(config["broker"].get("api_secret_env", ""))
        if not auth_client and (not api_key or not api_secret):
            raise RuntimeError(
                "Missing Alpaca credentials. Provide either broker.api_key/broker.api_secret (or env vars), "
                "or OAuth credentials via broker.oauth_client_id/broker.oauth_client_secret."
            )
        return AlpacaBroker(
            api_key,
            api_secret,
            paper=bool(config["broker"]["paper"]),
            base_url=config["broker"].get("base_url"),
            auth_client=auth_client,
        )

    if broker_name == "ibkr":
        return IbkrBroker(
            host=config["broker"]["host"],
            port=int(config["broker"]["port"]),
            client_id=int(config["broker"]["client_id"]),
            exchange=config["broker"]["exchange"],
            currency=config["broker"]["currency"],
        )

    raise ValueError(f"Unsupported broker name: {config['broker']['name']}")


def fetch_bars(symbol, interval="1m", lookback="2d"):
    data = yf.download(
        tickers=symbol,
        period=lookback,
        interval=interval,
        auto_adjust=False,
        progress=False,
    )
    if data.empty:
        raise RuntimeError(f"No data returned for {symbol} at interval {interval}")

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [c[0].lower() for c in data.columns]
    else:
        data.columns = [str(c).lower() for c in data.columns]

    if "volume" not in data.columns:
        raise RuntimeError("Data feed missing volume column.")

    df = data.reset_index().rename(columns={"Datetime": "timestamp", "Date": "timestamp"})
    if "timestamp" not in df.columns:
        df = df.rename(columns={df.columns[0]: "timestamp"})

    keep = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [c for c in keep if c not in df.columns]
    if missing:
        raise RuntimeError(f"Data feed missing required columns: {missing}")

    return df[keep].dropna()


def calc_entry_qty(config, last_price):
    capital = float(config["capital"])
    alloc_pct = float(config["position_size_pct"])
    budget = capital * alloc_pct
    qty = int(budget / float(last_price))
    return max(qty, 1)


def execute_action(broker, symbol, action, entry_qty):
    current_qty = broker.get_position_qty(symbol)

    if action == "enter_long":
        if current_qty < 0:
            broker.submit_market_order(symbol, "buy", abs(current_qty))
            current_qty = 0
        if current_qty == 0:
            broker.submit_market_order(symbol, "buy", entry_qty)

    elif action == "enter_short":
        if current_qty > 0:
            broker.submit_market_order(symbol, "sell", abs(current_qty))
            current_qty = 0
        if current_qty == 0:
            broker.submit_market_order(symbol, "sell", entry_qty)

    elif action == "exit_long":
        if current_qty > 0:
            broker.submit_market_order(symbol, "sell", abs(current_qty))

    elif action == "exit_short":
        if current_qty < 0:
            broker.submit_market_order(symbol, "buy", abs(current_qty))


def main():
    config = load_config()
    symbol = config["symbol"]
    timeframe = config["timeframe"]
    poll_seconds = int(config["poll_seconds"])
    dry_run = bool(config["dry_run"])
    configured_broker = str(config["broker"]["name"])

    strategy = Lucky13EmaStrategy(config)
    broker = PaperBroker() if dry_run else make_broker(config)
    logger = StructuredLogger(config)
    journal = TradeJournal(config)
    risk_manager = RiskManager(config)

    logger.log(
        "startup",
        symbol=symbol,
        timeframe=timeframe,
        configured_broker=configured_broker,
        dry_run=dry_run,
    )

    if configured_broker.lower() == "alpaca" and not dry_run:
        logger.log(
            "live_trading_warning",
            broker=configured_broker,
            message="Live Alpaca mode is enabled. Orders will be sent to the broker.",
        )

    last_processed_ts = None

    while True:
        try:
            df = fetch_bars(symbol, interval=timeframe)
            latest_ts = str(df.iloc[-1]["timestamp"])

            if latest_ts == last_processed_ts:
                time.sleep(poll_seconds)
                continue

            last_processed_ts = latest_ts
            if not is_market_open(df.iloc[-1]["timestamp"], config):
                logger.log("market_closed", symbol=symbol, timestamp=latest_ts)
                time.sleep(poll_seconds)
                continue

            signal = strategy.evaluate_latest(df)
            last_price = float(df.iloc[-1]["close"])
            equity, drawdown_pct = risk_manager.equity_snapshot(last_price)

            if signal is None:
                logger.log(
                    "heartbeat",
                    symbol=symbol,
                    timestamp=latest_ts,
                    equity=round(equity, 4),
                    drawdown_pct=round(drawdown_pct, 4),
                )
            else:
                action = signal["action"]
                price = float(signal["price"])
                qty = calc_entry_qty(config, price)
                allowed, reason = risk_manager.allow_action(action, latest_ts, price)

                if not allowed:
                    logger.log(
                        "trade_blocked",
                        symbol=symbol,
                        timestamp=latest_ts,
                        action=action,
                        price=round(price, 4),
                        qty=qty,
                        reason=reason,
                    )
                    time.sleep(poll_seconds)
                    continue

                if dry_run:
                    logger.log(
                        "dry_run_order",
                        symbol=symbol,
                        timestamp=latest_ts,
                        action=action,
                        price=round(price, 4),
                        qty=qty,
                    )
                else:
                    execute_action(broker, symbol, action, qty)
                    logger.log(
                        "order_sent",
                        symbol=symbol,
                        timestamp=latest_ts,
                        action=action,
                        price=round(price, 4),
                        qty=qty,
                        broker=configured_broker,
                    )

                journal_entry = risk_manager.record_action(
                    symbol=symbol,
                    action=action,
                    qty=qty,
                    price=price,
                    timestamp=latest_ts,
                    broker_name=configured_broker,
                    note="dry_run" if dry_run else "live",
                )
                journal.record(journal_entry)
                logger.log("trade_recorded", **journal_entry)

        except Exception as exc:
            logger.log("loop_error", symbol=symbol, error=str(exc))

        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
