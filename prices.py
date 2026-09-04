import logging
import yfinance as yf
import requests

# yfinance prints its own warnings (404s etc). Suppress them so users
# never see raw library output - our own messages replace them.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# Our own logger, for recording what actually failed.
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("prices")


# Failure reasons, kept as constants so the API and UI can branch on them
# without matching on message text.
UNKNOWN_TICKER = "unknown_ticker"
SERVICE_UNAVAILABLE = "service_unavailable"
NETWORK_ERROR = "network_error"

MESSAGES = {
    UNKNOWN_TICKER: "We couldn't find that stock. Indian stocks usually end in .NS (e.g. RELIANCE.NS).",
    SERVICE_UNAVAILABLE: "Price data is temporarily unavailable. Try again shortly.",
    NETWORK_ERROR: "Can't reach the price service. Check your connection.",
}


def _failure(ticker, reason):
    return {
        "ticker": ticker,
        "ok": False,
        "reason": reason,
        "message": MESSAGES[reason],
    }


def get_price(ticker):
    """
    Fetch current price data for one ticker.
    Never raises. On failure, returns ok=False with a reason the caller
    can branch on and a message safe to show a user.
    """
    try:
        stock = yf.Ticker(ticker)
        history = stock.history(period="2d")

        # Yahoo answered, but has nothing for this symbol.
        # Treated as user-fixable, not a system fault.
        if history.empty:
            return _failure(ticker, UNKNOWN_TICKER)

        latest = history.iloc[-1]
        price = float(latest["Close"])
        volume = int(latest["Volume"])

        if len(history) >= 2:
            previous = float(history.iloc[-2]["Close"])
            change = price - previous
            change_pct = (change / previous) * 100
        else:
            previous = change = change_pct = None

        return {
            "ticker": ticker,
            "ok": True,
            "price": round(price, 2),
            "previous_close": round(previous, 2) if previous else None,
            "change": round(change, 2) if change is not None else None,
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "volume": volume,
        }

    except requests.exceptions.ConnectionError:
        log.warning("Network error fetching %s", ticker)
        return _failure(ticker, NETWORK_ERROR)

    except requests.exceptions.Timeout:
        log.warning("Timeout fetching %s", ticker)
        return _failure(ticker, SERVICE_UNAVAILABLE)

    except Exception:
        # Unexpected failure. Log full detail for debugging, but show the
        # user a generic service message - we don't know it's their fault.
        log.exception("Unexpected failure fetching %s", ticker)
        return _failure(ticker, SERVICE_UNAVAILABLE)


def get_prices(tickers):
    """Fetch prices for several tickers. Failures are isolated per ticker."""
    return [get_price(t) for t in tickers]
