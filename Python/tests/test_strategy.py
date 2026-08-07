import pandas as pd

from strategy import Lucky13EmaStrategy


BASE_CONFIG = {
    "ema_length": 13,
    "vol_mult": 1.2,
    "use_filters": True,
    "use_vwap_cross": False,
    "use_trailing": True,
    "trail_offset": 10,
    "profit_pct": 2.0,
    "stop_pct": 1.0,
}


def make_frame(prev_row, curr_row):
    rows = []
    for index in range(23):
        rows.append(
            {
                "timestamp": f"2024-01-01 09:{index:02d}:00",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100.0,
            }
        )

    rows.append(prev_row)
    rows.append(curr_row)
    return pd.DataFrame(rows)


def test_evaluate_latest_returns_none_for_short_series():
    strategy = Lucky13EmaStrategy(BASE_CONFIG)
    df = pd.DataFrame([{"timestamp": "t", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])

    assert strategy.evaluate_latest(df) is None


def test_evaluate_latest_enters_long(monkeypatch):
    strategy = Lucky13EmaStrategy(BASE_CONFIG)
    df = make_frame(
        {
            "timestamp": "2024-01-01 09:23:00",
            "open": 98.0,
            "high": 100.0,
            "low": 97.0,
            "close": 99.0,
            "volume": 100.0,
        },
        {
            "timestamp": "2024-01-01 09:24:00",
            "open": 100.0,
            "high": 112.0,
            "low": 99.0,
            "close": 110.0,
            "volume": 200.0,
        },
    )

    enriched = df.copy()
    enriched["vwap"] = 105.0
    enriched["ema13"] = 100.0
    enriched.loc[23, "ema13"] = 100.0
    enriched.loc[24, "ema13"] = 100.0
    enriched.loc[23, "vwap"] = 98.0
    enriched.loc[24, "vwap"] = 105.0

    monkeypatch.setattr(strategy, "add_indicators", lambda incoming: enriched)

    signal = strategy.evaluate_latest(df)

    assert signal["action"] == "enter_long"
    assert strategy.position == 1
    assert strategy.trail_stop == 100.0


def test_evaluate_latest_exits_long_on_trailing_stop(monkeypatch):
    strategy = Lucky13EmaStrategy(BASE_CONFIG)
    strategy.position = 1
    strategy.entry_price = 110.0
    strategy.trail_stop = 100.0

    df = make_frame(
        {
            "timestamp": "2024-01-01 09:23:00",
            "open": 110.0,
            "high": 111.0,
            "low": 108.0,
            "close": 109.0,
            "volume": 100.0,
        },
        {
            "timestamp": "2024-01-01 09:24:00",
            "open": 100.0,
            "high": 101.0,
            "low": 89.0,
            "close": 95.0,
            "volume": 200.0,
        },
    )

    enriched = df.copy()
    enriched["vwap"] = 100.0
    enriched["ema13"] = 100.0

    monkeypatch.setattr(strategy, "add_indicators", lambda incoming: enriched)

    signal = strategy.evaluate_latest(df)

    assert signal["action"] == "exit_long"
    assert strategy.position == 0


def test_evaluate_latest_enters_short_with_vwap_cross(monkeypatch):
    config = BASE_CONFIG.copy()
    config["use_vwap_cross"] = True
    strategy = Lucky13EmaStrategy(config)
    df = make_frame(
        {
            "timestamp": "2024-01-01 09:23:00",
            "open": 106.0,
            "high": 107.0,
            "low": 103.0,
            "close": 105.0,
            "volume": 100.0,
        },
        {
            "timestamp": "2024-01-01 09:24:00",
            "open": 101.0,
            "high": 102.0,
            "low": 89.0,
            "close": 90.0,
            "volume": 200.0,
        },
    )

    enriched = df.copy()
    enriched["ema13"] = 100.0
    enriched["vwap"] = 100.0
    enriched.loc[23, "vwap"] = 100.0
    enriched.loc[24, "vwap"] = 95.0

    monkeypatch.setattr(strategy, "add_indicators", lambda incoming: enriched)

    signal = strategy.evaluate_latest(df)

    assert signal["action"] == "enter_short"
    assert strategy.position == -1