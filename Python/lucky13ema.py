import pandas as pd
import ta
import json
import yfinance as yf
from pathlib import Path
from datetime import datetime


# --- CONFIGURATION ---
DEFAULT_CONFIG = {
    "symbol": "IONQ",
    "timeframe": "1m",
    "capital": 30_000.0,
    "use_filters": True,
    "vol_mult": 1.2,
    "ema_length": 13,
    "profit_pct": 2.0,
    "stop_pct": 1.0,
    "use_trailing": True,
    "trail_offset": 10,
    "use_vwap_cross": False,
}


def load_config():
    config_path = Path(__file__).with_name("config.json")
    if not config_path.exists():
        return DEFAULT_CONFIG.copy()

    with config_path.open("r", encoding="utf-8") as f:
        user_config = json.load(f)

    config = DEFAULT_CONFIG.copy()
    config.update(user_config)
    return config


CONFIG = load_config()
SYMBOL = CONFIG["symbol"]
TIMEFRAME = CONFIG["timeframe"]  # just for logging
CAPITAL = CONFIG["capital"]
USE_FILTERS = CONFIG["use_filters"]
VOL_MULT = CONFIG["vol_mult"]
EMA_LENGTH = CONFIG["ema_length"]
PROFIT_PCT = CONFIG["profit_pct"]
STOP_PCT = CONFIG["stop_pct"]
USE_TRAILING = CONFIG["use_trailing"]
TRAIL_OFFSET = CONFIG["trail_offset"]  # points; for a more realistic version, use price %
USE_VWAP_CROSS = CONFIG["use_vwap_cross"]  # toggle to require VWAP cross

def fetch_data(symbol=SYMBOL, period="5d", interval=TIMEFRAME):
    data = yf.download(tickers=symbol, period=period, interval=interval,
                       auto_adjust=False, progress=False)
    if data.empty:
        raise RuntimeError(f"No data returned for {symbol}")

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [c[0].lower() for c in data.columns]
    else:
        data.columns = [str(c).lower() for c in data.columns]

    df = data.reset_index().rename(columns={"Datetime": "timestamp", "Date": "timestamp"})
    if "timestamp" not in df.columns:
        df = df.rename(columns={df.columns[0]: "timestamp"})

    return df[["timestamp", "open", "high", "low", "close", "volume"]].dropna()

# --- STRATEGY CLASS ---
class Lucky13emaAlgo:
    def __init__(self):
        self.position = 0  # 0 = flat, +1 = long, -1 = short
        self.entry_price = 0.0
        self.trail_stop = 0.0
        self.exits = []  # collect exit events

    def add_vwap_ema(self, df):
        # VWAP on OHLCV
        df["vwap"] = ta.volume.VolumeWeightedAveragePrice(
            df["high"], df["low"], df["close"], df["volume"]
        ).volume_weighted_average_price()

        # EMA(13) on close
        df["ema13"] = ta.trend.EMAIndicator(df["close"], window=EMA_LENGTH).ema_indicator()

        return df

    def run(self, df):
        print(f"Running Lucky13ema algo on {len(df)} candles...")

        df = self.add_vwap_ema(df)

        for i in range(1, len(df)):
            prev = df.iloc[i - 1]
            curr = df.iloc[i]

            # --- BASE CONDITIONS ---
            is_green = curr["close"] > curr["open"]
            is_red = curr["close"] < curr["open"]
            prev_below = prev["close"] <= prev["ema13"]
            prev_above = prev["close"] >= prev["ema13"]

            buy_condition = is_green and curr["close"] > curr["ema13"] and prev_below
            sell_condition = is_red and curr["close"] < curr["ema13"] and prev_above

            # --- FILTERS ---
            vol_sma = df["volume"].iloc[max(0, i-20):i].mean()
            vol_ok = curr["volume"] > vol_sma * VOL_MULT

            if USE_FILTERS:
                vwap_long_ok = curr["close"] > curr["vwap"]
                vwap_short_ok = curr["close"] < curr["vwap"]
            else:
                vwap_long_ok = True
                vwap_short_ok = True

            # VWAP cross mode
            if USE_VWAP_CROSS:
                if i > 0:
                    long_vwap_cross = curr["close"] > curr["vwap"] and prev["close"] <= prev["vwap"]
                    short_vwap_cross = curr["close"] < curr["vwap"] and prev["close"] >= prev["vwap"]
                else:
                    long_vwap_cross = False
                    short_vwap_cross = False
                buy_filter = long_vwap_cross
                sell_filter = short_vwap_cross
            else:
                buy_filter = vwap_long_ok
                sell_filter = vwap_short_ok

            buy_signal = buy_condition and vol_ok and buy_filter
            sell_signal = sell_condition and vol_ok and sell_filter

            # --- ENTRIES --- (only if not already in that direction)
            if buy_signal and self.position <= 0:
                qty = int(CAPITAL * 100 / curr["close"])  # 100% equity, no leverage
                self.position = 1
                self.entry_price = curr["close"]
                if USE_TRAILING:
                    self.trail_stop = self.entry_price - TRAIL_OFFSET
                print(
                    f"{curr['timestamp']}: LONG entry "
                    f"@ {curr['close']:.2f}, qty {qty}, pos={self.position}"
                )

            elif sell_signal and self.position >= 0:
                qty = int(CAPITAL * 100 / curr["close"])  # 100% equity short
                self.position = -1
                self.entry_price = curr["close"]
                if USE_TRAILING:
                    self.trail_stop = self.entry_price + TRAIL_OFFSET
                print(
                    f"{curr['timestamp']}: SHORT entry "
                    f"@ {curr['close']:.2f}, qty {qty}, pos={self.position}"
                )

            # --- EXITS ---
            if self.position == 1:
                price = curr["close"]
                if USE_TRAILING:
                    if price < self.trail_stop:
                        print(
                            f"{curr['timestamp']}: LONG stopped out "
                            f"@ {price:.2f}, pos={self.position} -> 0"
                        )
                        self.exits.append(("long_stop", curr["timestamp"], price))
                        self.position = 0
                    else:
                        # update trailing stop higher
                        new_stop = price - TRAIL_OFFSET
                        if new_stop > self.trail_stop:
                            self.trail_stop = new_stop
                else:
                    profit_price = self.entry_price * (1 + PROFIT_PCT / 100.0)
                    stop_price = self.entry_price * (1 - STOP_PCT / 100.0)
                    if price >= profit_price:
                        print(
                            f"{curr['timestamp']}: LONG take profit "
                            f"@ {price:.2f}, pos={self.position} -> 0"
                        )
                        self.exits.append(("long_tp", curr["timestamp"], price))
                        self.position = 0
                    elif price <= stop_price:
                        print(
                            f"{curr['timestamp']}: LONG stop loss "
                            f"@ {price:.2f}, pos={self.position} -> 0"
                        )
                        self.exits.append(("long_sl", curr["timestamp"], price))
                        self.position = 0

            elif self.position == -1:
                price = curr["close"]
                if USE_TRAILING:
                    if price > self.trail_stop:
                        print(
                            f"{curr['timestamp']}: SHORT stopped out "
                            f"@ {price:.2f}, pos={self.position} -> 0"
                        )
                        self.exits.append(("short_stop", curr["timestamp"], price))
                        self.position = 0
                    else:
                        # update trailing stop lower
                        new_stop = price + TRAIL_OFFSET
                        if new_stop < self.trail_stop:
                            self.trail_stop = new_stop
                else:
                    profit_price = self.entry_price * (1 - PROFIT_PCT / 100.0)
                    stop_price = self.entry_price * (1 + STOP_PCT / 100.0)
                    if price <= profit_price:
                        print(
                            f"{curr['timestamp']}: SHORT take profit "
                            f"@ {price:.2f}, pos={self.position} -> 0"
                        )
                        self.exits.append(("short_tp", curr["timestamp"], price))
                        self.position = 0
                    elif price >= stop_price:
                        print(
                            f"{curr['timestamp']}: SHORT stop loss "
                            f"@ {price:.2f}, pos={self.position} -> 0"
                        )
                        self.exits.append(("short_sl", curr["timestamp"], price))
                        self.position = 0

        print(f"Finished. Final position: {self.position}")


# --- MAIN ---
if __name__ == "__main__":
    df = fetch_data()

    algo = Lucky13emaAlgo()
    algo.run(df)