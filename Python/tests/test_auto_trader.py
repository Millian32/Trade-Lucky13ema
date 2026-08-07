from pathlib import Path

import pytest

import auto_trader
from auto_trader import calc_entry_qty, execute_action, load_config, make_broker
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
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
{
  "symbol": "SPY",
  "broker": {
    "name": "alpaca"
  }
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(auto_trader, "__file__", str(tmp_path / "auto_trader.py"))

    config = load_config()

    assert config["symbol"] == "SPY"
    assert config["broker"]["name"] == "alpaca"
    assert config["broker"]["paper"] is True
    assert config["broker"]["api_key_env"] == "ALPACA_API_KEY"


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
        def __init__(self, api_key, api_secret, paper=True):
            captured["api_key"] = api_key
            captured["api_secret"] = api_secret
            captured["paper"] = paper

    monkeypatch.setenv("TEST_ALPACA_KEY", "key")
    monkeypatch.setenv("TEST_ALPACA_SECRET", "secret")
    monkeypatch.setattr(auto_trader, "AlpacaBroker", FakeAlpacaBroker)

    broker = make_broker(
        {
            "broker": {
                "name": "alpaca",
                "paper": False,
                "api_key_env": "TEST_ALPACA_KEY",
                "api_secret_env": "TEST_ALPACA_SECRET",
            }
        }
    )

    assert isinstance(broker, FakeAlpacaBroker)
    assert captured == {"api_key": "key", "api_secret": "secret", "paper": False}


def test_make_broker_rejects_unknown_broker():
    with pytest.raises(ValueError, match="Unsupported broker name"):
        make_broker({"broker": {"name": "unknown"}})