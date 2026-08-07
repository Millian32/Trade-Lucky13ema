from abc import ABC, abstractmethod
import time

import requests


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
    def __init__(self, api_key=None, api_secret=None, paper=True, base_url=None, auth_client=None):
        self.executor = AlpacaTradeExecutor(
            base_url=base_url,
            api_key=api_key,
            api_secret=api_secret,
            paper=paper,
            auth_client=auth_client,
        )

    def get_position_qty(self, symbol):
        return self.executor.get_position_qty(symbol)

    def submit_market_order(self, symbol, side, qty):
        response = self.executor.submit_market_order(symbol, side, qty)
        order_id = response.get("id", "unknown")
        print(f"[ALPACA] Submitted {side.upper()} {qty} {symbol} order id={order_id}")


class AlpacaAuthClient:
    def __init__(self, client_id, client_secret, auth_base_url="https://authx.alpaca.markets/v1", session=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_base_url = auth_base_url.rstrip("/")
        self.session = session or requests.Session()
        self._access_token = None
        self._expires_at = 0.0

    def issue_token(self):
        response = self.session.post(
            f"{self.auth_base_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 900))
        self._expires_at = time.time() + max(expires_in - 30, 1)
        return self._access_token

    def get_access_token(self):
        if not self._access_token or time.time() >= self._expires_at:
            return self.issue_token()
        return self._access_token


class AlpacaTradeExecutor:
    def __init__(self, base_url=None, api_key=None, api_secret=None, paper=True, auth_client=None, session=None):
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = "https://paper-api.alpaca.markets/v2" if paper else "https://api.alpaca.markets/v2"
        self.api_key = api_key
        self.api_secret = api_secret
        self.auth_client = auth_client
        self.session = session or requests.Session()

        if not self.auth_client and (not self.api_key or not self.api_secret):
            raise RuntimeError("Alpaca credentials are required. Provide API keys or an OAuth auth client.")

    def _headers(self):
        if self.auth_client:
            token = self.auth_client.get_access_token()
            return {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
        }

    def get_position_qty(self, symbol):
        response = self.session.get(
            f"{self.base_url}/positions/{symbol}",
            headers=self._headers(),
            timeout=15,
        )
        if response.status_code == 404:
            return 0
        response.raise_for_status()

        payload = response.json()
        qty = int(abs(float(payload.get("qty", 0))))
        side = str(payload.get("side", "")).lower()
        if side == "short":
            return -qty
        return qty

    def submit_market_order(self, symbol, side, qty):
        response = self.session.post(
            f"{self.base_url}/orders",
            headers=self._headers(),
            json={
                "symbol": symbol,
                "qty": int(qty),
                "side": side.lower(),
                "type": "market",
                "time_in_force": "day",
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json()


class IbkrBroker(Broker):
    def __init__(self, host="127.0.0.1", port=7497, client_id=1, exchange="SMART", currency="USD"):
        try:
            from ib_insync import IB, MarketOrder, Stock
        except ImportError as exc:
            raise RuntimeError(
                "ib_insync is required for IbkrBroker. Install with: pip install ib_insync"
            ) from exc

        self._MarketOrder = MarketOrder
        self._Stock = Stock
        self.exchange = exchange
        self.currency = currency
        self.ib = IB()
        self.ib.connect(host, int(port), clientId=int(client_id))

    def get_position_qty(self, symbol):
        for position in self.ib.positions():
            if position.contract.symbol == symbol:
                return int(position.position)
        return 0

    def submit_market_order(self, symbol, side, qty):
        qty = int(qty)
        contract = self._Stock(symbol, self.exchange, self.currency)
        self.ib.qualifyContracts(contract)
        order = self._MarketOrder(side.upper(), qty)
        trade = self.ib.placeOrder(contract, order)
        order_id = getattr(trade.order, "orderId", "pending")
        print(f"[IBKR] Submitted {side.upper()} {qty} {symbol} order id={order_id}")
