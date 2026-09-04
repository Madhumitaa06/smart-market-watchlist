import logging
from concurrent.futures import ThreadPoolExecutor
import yfinance as yf
import requests

import cache

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


def get_price_cached(ticker):
    """
    Cached wrapper around get_price.

    Only successful fetches are cached. Caching a failure would mean a
    transient Yahoo outage locks in an error for the whole TTL - the user
    would keep seeing 'unavailable' long after the service recovered.
    Failures are cheap to retry; stale errors are expensive.
    """
    hit = cache.get_quote(ticker)
    if hit is not None:
        return hit

    result = get_price(ticker)

    if result["ok"]:
        cache.put_quote(ticker, result)
        result["cached"] = False
        result["age_seconds"] = 0

    return result


def get_prices_cached(tickers, max_workers=8):
    """
    Fetch several tickers concurrently, using the cache where possible.

    Sequential fetching costs roughly (n x latency); a 20-stock watchlist
    would block for ~10s. Fetching in parallel makes the total closer to
    the slowest single call.

    Worker count is capped rather than unbounded: one thread per ticker
    would hammer Yahoo from a single client and invite rate limiting.
    Cache hits return without touching the network at all, so in the
    common case very few of these threads do any real work.

    Order is preserved so the caller can rely on it, regardless of which
    fetches finish first.
    """
    if not tickers:
        return []

    with ThreadPoolExecutor(max_workers=min(max_workers, len(tickers))) as pool:
        return list(pool.map(get_price_cached, tickers))


def fetch_history(ticker, days=60):
    """
    Fetch daily closes and store them. Returns the number of rows stored.

    Asks for more calendar days than the 30 trading days we need, because
    weekends and holidays mean ~60 calendar days yields ~40 trading days.
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=f"{days}d")

        if hist.empty:
            return 0

        rows = [
            (index.strftime("%Y-%m-%d"), float(row["Close"]), int(row["Volume"]))
            for index, row in hist.iterrows()
        ]
        cache.put_history(ticker, rows)
        return len(rows)

    except Exception:
        log.exception("Failed fetching history for %s", ticker)
        return 0


def ensure_history(ticker, minimum=20):
    """
    Make sure we hold enough history to compute a baseline.
    Only hits the network when we're short - stored closes never change.
    """
    if cache.history_count(ticker) >= minimum:
        return True

    fetch_history(ticker)
    return cache.history_count(ticker) >= minimum
