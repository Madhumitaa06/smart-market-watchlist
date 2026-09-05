"""
Caching behaviour, including the two decisions that aren't obvious:
TTL is read-time not write-time, and failures are never stored.
"""

import time

import cache
import market
import prices


def test_a_fresh_quote_is_returned(monkeypatch):
    monkeypatch.setattr(market, "current_ttl", lambda: 300)
    cache.put_quote("X.NS", {"ticker": "X.NS", "price": 100})

    hit = cache.get_quote("X.NS")
    assert hit is not None
    assert hit["cached"] is True


def test_an_expired_quote_is_not_returned(monkeypatch):
    monkeypatch.setattr(market, "current_ttl", lambda: 0)
    cache.put_quote("X.NS", {"ticker": "X.NS", "price": 100})
    time.sleep(0.01)

    assert cache.get_quote("X.NS") is None


def test_ttl_is_decided_at_read_time(monkeypatch):
    """Stored while the market was open, read after it closed - the longer
    closed-market TTL should apply, not the one in force when it was written."""
    monkeypatch.setattr(market, "current_ttl", lambda: 1)
    cache.put_quote("X.NS", {"ticker": "X.NS", "price": 100})
    time.sleep(1.1)

    assert cache.get_quote("X.NS") is None

    monkeypatch.setattr(market, "current_ttl", lambda: 3600)
    assert cache.get_quote("X.NS") is not None


def test_closed_market_gets_the_longer_ttl():
    assert market.TTL_CLOSED > market.TTL_OPEN


def test_history_rows_are_not_duplicated():
    rows = [("2026-07-01", 100.0, 1000), ("2026-07-02", 101.0, 1000)]
    cache.put_history("X.NS", rows)
    cache.put_history("X.NS", rows)          # same day, written twice

    assert cache.history_count("X.NS") == 2


def test_history_comes_back_oldest_first():
    cache.put_history("X.NS", [("2026-07-03", 102.0, 1000),
                               ("2026-07-01", 100.0, 1000),
                               ("2026-07-02", 101.0, 1000)])
    dates = [h["date"] for h in cache.get_history("X.NS")]

    assert dates == sorted(dates)


def test_failed_fetches_are_not_cached(monkeypatch):
    """A cached outage would keep showing 'unavailable' long after recovery."""
    monkeypatch.setattr(prices, "get_price",
                        lambda t: {"ticker": t, "ok": False, "reason": "x",
                                   "message": "down"})
    prices.get_price_cached("Y.NS")

    assert cache.get_quote("Y.NS") is None
