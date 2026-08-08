import sqlite3

import pandas as pd
import pytest

import auto_trader
from auto_trader import (
    RiskManager,
    TradeJournal,
    calc_entry_qty,
    execute_action,
    fetch_bars,
    fetch_bars_alpaca,
    is_market_open,
    load_config,
    make_broker,
)
from broker import PaperBroker


class RecordingBroker:
    def __init__(self, qty=0):
        self.qty = qty
        self.orders = []

    def get_position_qty(self, symbol):
        return self.qty

    def submit_market_order(self, symbol, side, qty):
        self.orders.append((symbol, side, qty))
        if side == "buy":
            self.qty += qty
        else:
            self.qty -= qty


def test_calc_entry_qty_uses_position_size_percentage():
    config = {"capital": 10000, "position_size_pct": 0.25}

    qty = calc_entry_qty(config, last_price=50)

    assert qty == 50


def test_calc_entry_qty_never_returns_zero():
    config = {"capital": 10, "position_size_pct": 0.01}

    qty = calc_entry_qty(config, last_price=500)

    assert qty == 1


def test_execute_action_closes_short_then_enters_long():
    broker = RecordingBroker(qty=-5)

    execute_action(broker, "IONQ", "enter_long", entry_qty=3)

    assert broker.orders == [("IONQ", "buy", 5), ("IONQ", "buy", 3)]
    assert broker.qty == 3


def test_execute_action_closes_long_then_enters_short():
    broker = RecordingBroker(qty=4)

    execute_action(broker, "IONQ", "enter_short", entry_qty=2)

    assert broker.orders == [("IONQ", "sell", 4), ("IONQ", "sell", 2)]
    assert broker.qty == -2


def test_execute_action_exits_existing_long_only():
    broker = RecordingBroker(qty=6)

    execute_action(broker, "IONQ", "exit_long", entry_qty=99)

    assert broker.orders == [("IONQ", "sell", 6)]
    assert broker.qty == 0


def test_execute_action_exits_existing_short_only():
    broker = RecordingBroker(qty=-8)

    execute_action(broker, "IONQ", "exit_short", entry_qty=99)

    assert broker.orders == [("IONQ", "buy", 8)]
    assert broker.qty == 0


def test_load_config_merges_nested_broker_config(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(
        '{"symbol":"SPY","risk":{"max_drawdown_pct":3.5},"broker":{"name":"alpaca"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(auto_trader, "__file__", str(tmp_path / "auto_trader.py"))

    config = load_config()

    assert config["symbol"] == "SPY"
    assert config["risk"]["max_drawdown_pct"] == 3.5
    assert config["risk"]["max_trades_per_day"] == 5
    assert config["broker"]["name"] == "alpaca"
    assert config["broker"]["paper"] is True
    assert config["broker"]["api_key_env"] == "ALPACA_API_KEY"


def test_load_config_merges_local_config_file(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(
        '{"broker":{"name":"paper"},"symbol":"IONQ"}',
        encoding="utf-8",
    )
    (tmp_path / "config.local.json").write_text(
        '{"broker":{"name":"alpaca","api_key":"local-key","api_secret":"local-secret"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(auto_trader, "__file__", str(tmp_path / "auto_trader.py"))

    config = load_config()

    assert config["broker"]["name"] == "alpaca"
    assert config["broker"]["api_key"] == "local-key"
    assert config["broker"]["api_secret"] == "local-secret"


def test_make_broker_returns_paper_broker():
    broker = make_broker({"broker": {"name": "paper"}})

    assert isinstance(broker, PaperBroker)


def test_make_broker_requires_alpaca_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="Missing Alpaca credentials"):
        make_broker(
            {
                "broker": {
                    "name": "alpaca",
                    "paper": True,
                    "api_key_env": "ALPACA_API_KEY",
                    "api_secret_env": "ALPACA_API_SECRET",
                }
            }
        )


def test_make_broker_builds_alpaca_broker(monkeypatch):
    captured = {}

    class FakeAlpacaBroker:
        def __init__(self, api_key, api_secret, paper=True, base_url=None, auth_client=None):
            captured["api_key"] = api_key
            captured["api_secret"] = api_secret
            captured["paper"] = paper
            captured["base_url"] = base_url
            captured["auth_client"] = auth_client

    monkeypatch.setenv("TEST_ALPACA_KEY", "key")
    monkeypatch.setenv("TEST_ALPACA_SECRET", "secret")
    monkeypatch.setattr(auto_trader, "AlpacaBroker", FakeAlpacaBroker)

    broker = make_broker(
        {
            "broker": {
                "name": "alpaca",
                "paper": False,
                "alpaca_base_url": "https://paper-api.alpaca.markets/v2",
                "api_key_env": "TEST_ALPACA_KEY",
                "api_secret_env": "TEST_ALPACA_SECRET",
            }
        }
    )

    assert isinstance(broker, FakeAlpacaBroker)
    assert captured == {
        "api_key": "key",
        "api_secret": "secret",
        "paper": False,
        "base_url": "https://paper-api.alpaca.markets/v2",
        "auth_client": None,
    }


def test_make_broker_uses_alpaca_keys_from_config(monkeypatch):
    captured = {}

    class FakeAlpacaBroker:
        def __init__(self, api_key, api_secret, paper=True, base_url=None, auth_client=None):
            captured["api_key"] = api_key
            captured["api_secret"] = api_secret
            captured["paper"] = paper
            captured["base_url"] = base_url
            captured["auth_client"] = auth_client

    monkeypatch.setattr(auto_trader, "AlpacaBroker", FakeAlpacaBroker)

    broker = make_broker(
        {
            "broker": {
                "name": "alpaca",
                "paper": True,
                "alpaca_base_url": "https://paper-api.alpaca.markets/v2",
                "api_key": "cfg-key",
                "api_secret": "cfg-secret",
                "api_key_env": "UNUSED_KEY",
                "api_secret_env": "UNUSED_SECRET",
            }
        }
    )

    assert isinstance(broker, FakeAlpacaBroker)
    assert captured == {
        "api_key": "cfg-key",
        "api_secret": "cfg-secret",
        "paper": True,
        "base_url": "https://paper-api.alpaca.markets/v2",
        "auth_client": None,
    }


def test_make_broker_builds_alpaca_broker_with_oauth(monkeypatch):
    captured = {}

    class FakeAuthClient:
        def __init__(self, client_id, client_secret, auth_base_url):
            self.client_id = client_id
            self.client_secret = client_secret
            self.auth_base_url = auth_base_url

    class FakeAlpacaBroker:
        def __init__(self, api_key, api_secret, paper=True, base_url=None, auth_client=None):
            captured["api_key"] = api_key
            captured["api_secret"] = api_secret
            captured["paper"] = paper
            captured["base_url"] = base_url
            captured["auth_client"] = auth_client

    monkeypatch.setattr(auto_trader, "AlpacaAuthClient", FakeAuthClient)
    monkeypatch.setattr(auto_trader, "AlpacaBroker", FakeAlpacaBroker)

    broker = make_broker(
        {
            "broker": {
                "name": "alpaca",
                "paper": True,
                "alpaca_base_url": "https://paper-api.alpaca.markets/v2",
                "oauth_client_id": "oauth-id",
                "oauth_client_secret": "oauth-secret",
                "oauth_auth_base_url": "https://authx.sandbox.alpaca.markets/v1",
            }
        }
    )

    assert isinstance(broker, FakeAlpacaBroker)
    assert captured["api_key"] is None
    assert captured["api_secret"] is None
    assert captured["paper"] is True
    assert captured["base_url"] == "https://paper-api.alpaca.markets/v2"
    assert isinstance(captured["auth_client"], FakeAuthClient)
    assert captured["auth_client"].client_id == "oauth-id"


def test_make_broker_builds_ibkr_broker(monkeypatch):
    captured = {}

    class FakeIbkrBroker:
        def __init__(self, host, port, client_id, exchange, currency):
            captured["host"] = host
            captured["port"] = port
            captured["client_id"] = client_id
            captured["exchange"] = exchange
            captured["currency"] = currency

    monkeypatch.setattr(auto_trader, "IbkrBroker", FakeIbkrBroker)

    broker = make_broker(
        {
            "broker": {
                "name": "ibkr",
                "ibkr_host": "127.0.0.1",
                "ibkr_port": 4002,
                "ibkr_client_id": 7,
                "ibkr_exchange": "SMART",
                "ibkr_currency": "USD",
            }
        }
    )

    assert isinstance(broker, FakeIbkrBroker)
    assert captured == {
        "host": "127.0.0.1",
        "port": 4002,
        "client_id": 7,
        "exchange": "SMART",
        "currency": "USD",
    }


def test_make_broker_rejects_unknown_broker():
    with pytest.raises(ValueError, match="Unsupported broker name"):
        make_broker({"broker": {"name": "unknown"}})


def test_risk_manager_blocks_entries_after_max_trades_per_day(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_trader, "__file__", str(tmp_path / "auto_trader.py"))
    manager = RiskManager(
        {
            "capital": 10000,
            "risk": {
                "enabled": True,
                "max_drawdown_pct": 10,
                "max_trades_per_day": 1,
                "kill_switch_file": "kill_switch.txt",
            },
        }
    )

    manager.record_action("IONQ", "enter_long", 5, 100, "2024-01-02 10:00:00", "paper")
    allowed, reason = manager.allow_action("enter_long", "2024-01-02 10:05:00", 101)

    assert allowed is False
    assert reason == "max trades per day reached"


def test_risk_manager_blocks_entries_after_max_drawdown(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_trader, "__file__", str(tmp_path / "auto_trader.py"))
    manager = RiskManager(
        {
            "capital": 10000,
            "risk": {
                "enabled": True,
                "max_drawdown_pct": 5,
                "max_trades_per_day": 5,
                "kill_switch_file": "kill_switch.txt",
            },
        }
    )

    manager.record_action("IONQ", "enter_long", 10, 100, "2024-01-02 10:00:00", "paper")
    allowed, reason = manager.allow_action("enter_short", "2024-01-02 10:10:00", 40)

    assert allowed is False
    assert reason == "max drawdown reached"


def test_risk_manager_kill_switch_blocks_entries_only(tmp_path, monkeypatch):
    kill_switch = tmp_path / "kill_switch.txt"
    kill_switch.write_text("stop", encoding="utf-8")
    monkeypatch.setattr(auto_trader, "__file__", str(tmp_path / "auto_trader.py"))
    manager = RiskManager(
        {
            "capital": 10000,
            "risk": {
                "enabled": True,
                "max_drawdown_pct": 5,
                "max_trades_per_day": 5,
                "kill_switch_file": "kill_switch.txt",
            },
        }
    )

    entry_allowed, entry_reason = manager.allow_action("enter_long", "2024-01-02 10:00:00", 100)
    exit_allowed, exit_reason = manager.allow_action("exit_long", "2024-01-02 10:00:00", 100)

    assert entry_allowed is False
    assert entry_reason == "kill switch active"
    assert exit_allowed is True
    assert exit_reason is None


def test_is_market_open_returns_true_inside_session():
    class FakeCalendar:
        def schedule(self, start_date, end_date):
            return pd.DataFrame(
                {
                    "market_open": [pd.Timestamp("2024-01-02 14:30:00+00:00")],
                    "market_close": [pd.Timestamp("2024-01-02 21:00:00+00:00")],
                }
            )

    config = {"market": {"enabled": True, "calendar": "XNYS", "timezone": "America/New_York"}}

    assert is_market_open("2024-01-02 10:00:00", config, calendar=FakeCalendar()) is True


def test_is_market_open_returns_false_on_holiday():
    class FakeCalendar:
        def schedule(self, start_date, end_date):
            return pd.DataFrame(columns=["market_open", "market_close"])

    config = {"market": {"enabled": True, "calendar": "XNYS", "timezone": "America/New_York"}}

    assert is_market_open("2024-01-01 10:00:00", config, calendar=FakeCalendar()) is False


def test_trade_journal_writes_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_trader, "__file__", str(tmp_path / "auto_trader.py"))
    journal = TradeJournal(
        {
            "trade_journal": {
                "enabled": True,
                "format": "csv",
                "path": "logs/trades.csv",
            }
        }
    )

    journal.record(
        {
            "timestamp": "2024-01-02T10:00:00",
            "symbol": "IONQ",
            "action": "enter_long",
            "qty": 5,
            "price": 100.5,
            "realized_pnl": 0.0,
            "equity": 10000.0,
            "drawdown_pct": 0.0,
            "broker": "paper",
            "note": "dry_run",
        }
    )

    contents = (tmp_path / "logs" / "trades.csv").read_text(encoding="utf-8").strip().splitlines()

    assert contents[0].startswith("timestamp,symbol,action")
    assert "enter_long" in contents[1]


def test_trade_journal_writes_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_trader, "__file__", str(tmp_path / "auto_trader.py"))
    journal = TradeJournal(
        {
            "trade_journal": {
                "enabled": True,
                "format": "sqlite",
                "path": "logs/trades.db",
            }
        }
    )

    journal.record(
        {
            "timestamp": "2024-01-02T10:00:00",
            "symbol": "IONQ",
            "action": "exit_long",
            "qty": 5,
            "price": 105.0,
            "realized_pnl": 22.5,
            "equity": 10022.5,
            "drawdown_pct": 0.0,
            "broker": "paper",
            "note": "live",
        }
    )

    db_path = tmp_path / "logs" / "trades.db"
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT action, realized_pnl FROM trades").fetchall()

    assert rows == [("exit_long", 22.5)]


def test_fetch_bars_dispatches_to_yfinance(monkeypatch):
    expected = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2024-01-02T14:30:00Z")],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        }
    )

    monkeypatch.setattr(auto_trader, "fetch_bars_yfinance", lambda **kwargs: expected)

    actual = fetch_bars(
        config={"market_data": {"source": "yfinance"}},
        symbol="IONQ",
        interval="1m",
    )

    assert actual.equals(expected)


def test_fetch_bars_dispatches_to_alpaca(monkeypatch):
    expected = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2024-01-02T14:30:00Z")],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        }
    )

    monkeypatch.setattr(auto_trader, "fetch_bars_alpaca", lambda **kwargs: expected)

    actual = fetch_bars(
        config={"market_data": {"source": "alpaca"}},
        symbol="IONQ",
        interval="1m",
    )

    assert actual.equals(expected)


def test_fetch_bars_alpaca_parses_bar_payload(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "bars": {
                    "IONQ": [
                        {
                            "t": "2024-01-02T14:30:00Z",
                            "o": 100.0,
                            "h": 101.0,
                            "l": 99.0,
                            "c": 100.5,
                            "v": 12345,
                        }
                    ]
                }
            }

    def fake_get(url, headers=None, params=None, timeout=None):
        return FakeResponse()

    monkeypatch.setattr(auto_trader.requests, "get", fake_get)

    cfg = {
        "broker": {},
        "market_data": {
            "alpaca_base_url": "https://data.alpaca.markets",
            "alpaca_feed": "iex",
            "alpaca_api_key": "key",
            "alpaca_api_secret": "secret",
        },
    }
    df = fetch_bars_alpaca(config=cfg, symbol="IONQ", interval="1m", limit=10)

    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(df) == 1


def test_fetch_bars_alpaca_requires_credentials():
    cfg = {
        "broker": {},
        "market_data": {
            "alpaca_base_url": "https://data.alpaca.markets",
            "alpaca_feed": "iex",
        },
    }
    with pytest.raises(RuntimeError, match="Missing Alpaca market data credentials"):
        fetch_bars_alpaca(config=cfg, symbol="IONQ", interval="1m", limit=10)