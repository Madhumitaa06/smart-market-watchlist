"""
Failure classification. The distinction between "your ticker is wrong" and
"our data source is down" matters: telling a user to check their symbol while
Yahoo is offline sends them chasing a problem that isn't theirs.
"""

import requests

import prices


class _Boom:
    def __init__(self, exc):
        self.exc = exc

    def history(self, period):
        raise self.exc


def _force(monkeypatch, exc):
    monkeypatch.setattr(prices.yf, "Ticker", lambda t: _Boom(exc))


def test_connection_error_is_a_network_problem(monkeypatch):
    _force(monkeypatch, requests.exceptions.ConnectionError())
    result = prices.get_price("RELIANCE.NS")

    assert not result["ok"]
    assert result["reason"] == prices.NETWORK_ERROR


def test_timeout_is_a_service_problem(monkeypatch):
    _force(monkeypatch, requests.exceptions.Timeout())
    result = prices.get_price("RELIANCE.NS")

    assert result["reason"] == prices.SERVICE_UNAVAILABLE


def test_unexpected_errors_blame_the_service_not_the_user(monkeypatch):
    """The deliberate default: we don't know whose fault it is, so we don't
    tell the user their input was wrong."""
    _force(monkeypatch, ValueError("something we've never seen"))
    result = prices.get_price("RELIANCE.NS")

    assert result["reason"] == prices.SERVICE_UNAVAILABLE
    assert result["reason"] != prices.UNKNOWN_TICKER


def test_every_failure_carries_a_human_message(monkeypatch):
    for exc in [requests.exceptions.ConnectionError(),
                requests.exceptions.Timeout(),
                RuntimeError("x")]:
        _force(monkeypatch, exc)
        result = prices.get_price("RELIANCE.NS")
        assert result["message"]
        assert not result["message"].startswith("Traceback")


def test_failures_never_raise(monkeypatch):
    """Callers rely on this - one bad ticker must not take down a whole list."""
    _force(monkeypatch, Exception("catastrophic"))
    result = prices.get_price("ANYTHING.NS")   # must not raise
    assert result["ok"] is False
