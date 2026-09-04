"""
Keeps popular tickers warm in the background.

Users then hit cache rather than triggering fetches themselves, which moves
load off the request path entirely: a cold popular ticker no longer means
whoever asked first waits on the network.

Popularity is measured by how many watchlists a ticker appears in - the
tickers most likely to be asked for next are the ones already being watched
by the most people.
"""

import logging
import sqlite3
import threading
import time

import market

log = logging.getLogger("refresher")

DB_FILE = "watchlist.db"
TOP_N = 20              # how many tickers to keep warm
IDLE_SLEEP = 300        # seconds between passes when markets are closed


def popular_tickers(limit=TOP_N):
    """Tickers ranked by how many watchlists they appear in."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT ticker, COUNT(*) AS watchers
        FROM watchlist
        GROUP BY ticker
        ORDER BY watchers DESC
        LIMIT ?
        """,
        (limit,)
    ).fetchall()
    conn.close()
    return [r["ticker"] for r in rows]


def _refresh_once():
    # Imported here rather than at module load to avoid a circular import:
    # prices imports cache, and this module is started from main.
    import prices

    tickers = popular_tickers()
    if not tickers:
        return 0

    # Goes through the same guarded path as user requests, so the refresher
    # shares the rate limiter rather than competing with real traffic.
    prices.get_prices_cached(tickers)
    return len(tickers)


def _loop(stop_event):
    while not stop_event.is_set():
        try:
            if market.is_market_open():
                n = _refresh_once()
                log.info("Refreshed %d popular tickers", n)
                # Slightly under the market-hours TTL, so entries are
                # replaced just before they expire rather than after.
                wait = market.TTL_OPEN - 20
            else:
                # Nothing to refresh - the closing price cannot change.
                wait = IDLE_SLEEP
        except Exception:
            log.exception("Refresh pass failed")
            wait = 60      # back off rather than spinning on a persistent error

        stop_event.wait(wait)


_stop = threading.Event()
_thread = None


def start():
    """Start the background refresher. Safe to call once at app startup."""
    global _thread
    if _thread is not None:
        return
    _thread = threading.Thread(target=_loop, args=(_stop,), daemon=True)
    _thread.start()
    log.info("Background refresher started")


def stop():
    _stop.set()
