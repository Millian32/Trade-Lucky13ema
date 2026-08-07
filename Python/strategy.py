import ta


class Lucky13EmaStrategy:
    def __init__(self, config):
        self.config = config
        self.position = 0
        self.entry_price = 0.0
        self.trail_stop = 0.0

    def add_indicators(self, df):
        data = df.copy()
        data["vwap"] = ta.volume.VolumeWeightedAveragePrice(
            data["high"], data["low"], data["close"], data["volume"]
        ).volume_weighted_average_price()
        data["ema13"] = ta.trend.EMAIndicator(
            data["close"], window=int(self.config["ema_length"])
        ).ema_indicator()
        return data

    def evaluate_latest(self, df):
        if len(df) < 25:
            return None

        data = self.add_indicators(df)
        i = len(data) - 1
        prev = data.iloc[i - 1]
        curr = data.iloc[i]

        is_green = curr["close"] > curr["open"]
        is_red = curr["close"] < curr["open"]
        prev_below = prev["close"] <= prev["ema13"]
        prev_above = prev["close"] >= prev["ema13"]

        buy_condition = is_green and curr["close"] > curr["ema13"] and prev_below
        sell_condition = is_red and curr["close"] < curr["ema13"] and prev_above

        vol_mult = float(self.config["vol_mult"])
        vol_sma = data["volume"].iloc[max(0, i - 20):i].mean()
        vol_ok = curr["volume"] > vol_sma * vol_mult

        if bool(self.config["use_filters"]):
            vwap_long_ok = curr["close"] > curr["vwap"]
            vwap_short_ok = curr["close"] < curr["vwap"]
        else:
            vwap_long_ok = True
            vwap_short_ok = True

        if bool(self.config["use_vwap_cross"]):
            long_vwap_cross = curr["close"] > curr["vwap"] and prev["close"] <= prev["vwap"]
            short_vwap_cross = curr["close"] < curr["vwap"] and prev["close"] >= prev["vwap"]
            buy_filter = long_vwap_cross
            sell_filter = short_vwap_cross
        else:
            buy_filter = vwap_long_ok
            sell_filter = vwap_short_ok

        buy_signal = buy_condition and vol_ok and buy_filter
        sell_signal = sell_condition and vol_ok and sell_filter

        price = float(curr["close"])
        timestamp = str(curr["timestamp"])

        if self.position == 1:
            if bool(self.config["use_trailing"]):
                if price < self.trail_stop:
                    self.position = 0
                    return {
                        "action": "exit_long",
                        "price": price,
                        "timestamp": timestamp,
                    }
                new_stop = price - float(self.config["trail_offset"])
                if new_stop > self.trail_stop:
                    self.trail_stop = new_stop
            else:
                profit_price = self.entry_price * (1 + float(self.config["profit_pct"]) / 100.0)
                stop_price = self.entry_price * (1 - float(self.config["stop_pct"]) / 100.0)
                if price >= profit_price or price <= stop_price:
                    self.position = 0
                    return {
                        "action": "exit_long",
                        "price": price,
                        "timestamp": timestamp,
                    }

        if self.position == -1:
            if bool(self.config["use_trailing"]):
                if price > self.trail_stop:
                    self.position = 0
                    return {
                        "action": "exit_short",
                        "price": price,
                        "timestamp": timestamp,
                    }
                new_stop = price + float(self.config["trail_offset"])
                if new_stop < self.trail_stop:
                    self.trail_stop = new_stop
            else:
                profit_price = self.entry_price * (1 - float(self.config["profit_pct"]) / 100.0)
                stop_price = self.entry_price * (1 + float(self.config["stop_pct"]) / 100.0)
                if price <= profit_price or price >= stop_price:
                    self.position = 0
                    return {
                        "action": "exit_short",
                        "price": price,
                        "timestamp": timestamp,
                    }

        if buy_signal and self.position <= 0:
            self.position = 1
            self.entry_price = price
            if bool(self.config["use_trailing"]):
                self.trail_stop = self.entry_price - float(self.config["trail_offset"])
            return {
                "action": "enter_long",
                "price": price,
                "timestamp": timestamp,
            }

        if sell_signal and self.position >= 0:
            self.position = -1
            self.entry_price = price
            if bool(self.config["use_trailing"]):
                self.trail_stop = self.entry_price + float(self.config["trail_offset"])
            return {
                "action": "enter_short",
                "price": price,
                "timestamp": timestamp,
            }

        return None
