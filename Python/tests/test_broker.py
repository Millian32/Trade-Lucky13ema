import time

import pytest

from broker import AlpacaAuthClient, AlpacaTradeExecutor, PaperBroker


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.last_get = None
        self.last_post = None
        self.next_get_response = FakeResponse()
        self.next_post_response = FakeResponse()

    def get(self, url, headers=None, timeout=None):
        self.last_get = {"url": url, "headers": headers, "timeout": timeout}
        return self.next_get_response

    def post(self, url, headers=None, json=None, data=None, timeout=None):
        self.last_post = {
            "url": url,
            "headers": headers,
            "json": json,
            "data": data,
            "timeout": timeout,
        }
        return self.next_post_response


def test_paper_broker_tracks_long_and_flatten():
    broker = PaperBroker()

    broker.submit_market_order("IONQ", "buy", 10)
    assert broker.get_position_qty("IONQ") == 10

    broker.submit_market_order("IONQ", "sell", 10)
    assert broker.get_position_qty("IONQ") == 0


def test_paper_broker_tracks_short_position():
    broker = PaperBroker()

    broker.submit_market_order("IONQ", "sell", 7)

    assert broker.get_position_qty("IONQ") == -7


def test_paper_broker_rejects_unknown_side():
    broker = PaperBroker()

    with pytest.raises(ValueError):
        broker.submit_market_order("IONQ", "hold", 1)


def test_alpaca_auth_client_issues_and_caches_token(monkeypatch):
    session = FakeSession()
    session.next_post_response = FakeResponse(
        payload={
            "access_token": "token-123",
            "expires_in": 900,
            "token_type": "Bearer",
        }
    )
    auth = AlpacaAuthClient(
        client_id="client-id",
        client_secret="client-secret",
        auth_base_url="https://authx.alpaca.markets/v1",
        session=session,
    )

    token_1 = auth.get_access_token()
    token_2 = auth.get_access_token()

    assert token_1 == "token-123"
    assert token_2 == "token-123"
    assert session.last_post["url"] == "https://authx.alpaca.markets/v1/oauth2/token"
    assert session.last_post["data"]["grant_type"] == "client_credentials"


def test_alpaca_trade_executor_uses_oauth_header():
    class StubAuth:
        def get_access_token(self):
            return "oauth-token"

    session = FakeSession()
    session.next_post_response = FakeResponse(payload={"id": "order-1"})
    executor = AlpacaTradeExecutor(
        base_url="https://paper-api.alpaca.markets/v2",
        auth_client=StubAuth(),
        session=session,
    )

    response = executor.submit_market_order("IONQ", "buy", 3)

    assert response["id"] == "order-1"
    assert session.last_post["headers"]["Authorization"] == "Bearer oauth-token"


def test_alpaca_trade_executor_position_handles_404():
    session = FakeSession()
    session.next_get_response = FakeResponse(status_code=404)
    executor = AlpacaTradeExecutor(
        base_url="https://paper-api.alpaca.markets/v2",
        api_key="k",
        api_secret="s",
        session=session,
    )

    qty = executor.get_position_qty("IONQ")

    assert qty == 0


def test_alpaca_auth_refreshes_after_expiry(monkeypatch):
    session = FakeSession()
    session.next_post_response = FakeResponse(
        payload={
            "access_token": "token-refresh",
            "expires_in": 1,
            "token_type": "Bearer",
        }
    )
    auth = AlpacaAuthClient(
        client_id="client-id",
        client_secret="client-secret",
        auth_base_url="https://authx.alpaca.markets/v1",
        session=session,
    )

    auth.issue_token()
    auth._expires_at = time.time() - 1
    token = auth.get_access_token()

    assert token == "token-refresh"