import pandas as pd
import numpy as np
import ta
from datetime import datetime


# --- CONFIGURATION ---
SYMBOL = "IONQ"
TIMEFRAME = "1m"  # just for logging
CAPITAL = 30_000.0
USE_FILTERS = True
VOL_MULT = 1.2
EMA_LENGTH = 13
PROFIT_PCT = 2.0
STOP_PCT = 1.0
USE_TRAILING = True
TRAIL_OFFSET = 10  # points; for a more realistic version, use price %
USE_VWAP_CROSS = False  # toggle to require VWAP cross

# --- MOCK DATA GENERATOR (you can swap with real CSV or yfinance) ---
def mock_data():
    np.random.seed(123)
    n = 10_000
    dates = pd.date_range("2024-01-01 09:30:00", periods=n, freq="1min")
    prices = 500.0 + np.cumsum(np.random.randn(n) * 0.5)
    opens = prices + np.random.randn(n) * 0.5
    closes = prices + np.random.randn(n) * 0.5
    highs = np.maximum(prices + 2.0, np.maximum(opens, closes))
    lows = np.minimum(prices - 2.0, np.minimum(opens, closes))
    volumes = np.random.randint(50_000, 200_000, n)
    return pd.DataFrame({
        "timestamp": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })

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
    # Load or generate data
    df = mock_data()  # or load from CSV: df = pd.read_csv("...")

    # Initialize algo and run
    algo = Lucky13emaAlgo()
    algo.run(df)