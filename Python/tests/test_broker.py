import pytest

from broker import PaperBroker


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