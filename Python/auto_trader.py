import json
import os
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from broker import AlpacaBroker, PaperBroker
from strategy import Lucky13EmaStrategy


DEFAULT_AUTO_CONFIG = {
    "symbol": "IONQ",
    "timeframe": "1m",
    "capital": 30000.0,
    "position_size_pct": 1.0,
    "poll_seconds": 15,
    "dry_run": True,
    "broker": {
        "name": "paper",
        "paper": True,
        "api_key_env": "ALPACA_API_KEY",
        "api_secret_env": "ALPACA_API_SECRET",
    },
}


def load_config():
    config_path = Path(__file__).with_name("config.json")
    with config_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    merged = DEFAULT_AUTO_CONFIG.copy()
    merged.update(raw)

    if "broker" in raw:
        broker_config = DEFAULT_AUTO_CONFIG["broker"].copy()
        broker_config.update(raw["broker"])
        merged["broker"] = broker_config

    return merged


def make_broker(config):
    broker_name = str(config["broker"]["name"]).lower()
    if broker_name == "paper":
        return PaperBroker()

    if broker_name == "alpaca":
        api_key = os.getenv(config["broker"]["api_key_env"])
        api_secret = os.getenv(config["broker"]["api_secret_env"])
        if not api_key or not api_secret:
            raise RuntimeError(
                "Missing Alpaca credentials. Set env vars from config: "
                f"{config['broker']['api_key_env']} and {config['broker']['api_secret_env']}"
            )
        return AlpacaBroker(api_key, api_secret, paper=bool(config["broker"]["paper"]))

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

    strategy = Lucky13EmaStrategy(config)
    broker = make_broker(config)

    print(
        f"Starting auto-trader | symbol={symbol} timeframe={timeframe} "
        f"broker={config['broker']['name']} dry_run={dry_run}"
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
            signal = strategy.evaluate_latest(df)

            if signal is None:
                print(f"{latest_ts}: no signal")
            else:
                action = signal["action"]
                price = signal["price"]
                qty = calc_entry_qty(config, price)
                print(f"{latest_ts}: signal={action} price={price:.2f} qty={qty}")

                if dry_run:
                    print("[DRY RUN] Order not sent.")
                else:
                    execute_action(broker, symbol, action, qty)

        except Exception as exc:
            print(f"Loop error: {exc}")

        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
