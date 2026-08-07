from abc import ABC, abstractmethod


class Broker(ABC):
    @abstractmethod
    def get_position_qty(self, symbol):
        raise NotImplementedError

    @abstractmethod
    def submit_market_order(self, symbol, side, qty):
        raise NotImplementedError


class PaperBroker(Broker):
    def __init__(self):
        self.positions = {}

    def get_position_qty(self, symbol):
        return int(self.positions.get(symbol, 0))

    def submit_market_order(self, symbol, side, qty):
        qty = int(qty)
        current = self.get_position_qty(symbol)
        if side == "buy":
            new_qty = current + qty
        elif side == "sell":
            new_qty = current - qty
        else:
            raise ValueError(f"Unsupported side: {side}")

        self.positions[symbol] = new_qty
        print(f"[PAPER] {side.upper()} {qty} {symbol} -> position {new_qty}")


class AlpacaBroker(Broker):
    def __init__(self, api_key, api_secret, paper=True):
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
        except ImportError as exc:
            raise RuntimeError(
                "alpaca-py is required for AlpacaBroker. Install with: pip install alpaca-py"
            ) from exc

        self._TradingClient = TradingClient
        self._MarketOrderRequest = MarketOrderRequest
        self._OrderSide = OrderSide
        self._TimeInForce = TimeInForce
        self.client = self._TradingClient(api_key, api_secret, paper=paper)

    def get_position_qty(self, symbol):
        try:
            position = self.client.get_open_position(symbol)
        except Exception:
            return 0

        qty = int(float(position.qty))
        side = str(position.side).lower()
        if "short" in side:
            return -abs(qty)
        return abs(qty)

    def submit_market_order(self, symbol, side, qty):
        qty = int(qty)
        side_enum = self._OrderSide.BUY if side == "buy" else self._OrderSide.SELL

        order = self._MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side_enum,
            time_in_force=self._TimeInForce.DAY,
        )
        submitted = self.client.submit_order(order_data=order)
        print(f"[ALPACA] Submitted {side.upper()} {qty} {symbol} order id={submitted.id}")
