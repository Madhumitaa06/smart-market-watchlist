import json
import sqlite3
import time as _time

import market

DB_FILE = "watchlist.db"


def _conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def setup():
    """Create cache tables. Safe to run repeatedly."""
    conn = _conn()

    # Short-lived quote cache, keyed by ticker.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quote_cache (
            ticker TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            fetched_at REAL NOT NULL
        )
    """)

    # Daily closes, one row per ticker per day. Long-lived - a past
    # close never changes, so this is only ever appended to.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_history (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL NOT NULL,
            volume INTEGER NOT NULL,
            PRIMARY KEY (ticker, date)
        )
    """)

    conn.commit()
    conn.close()


def get_quote(ticker):
    """
    Return a cached quote if it's still within its TTL, else None.
    TTL is decided at read time, not write time, so a quote cached
    during market hours correctly expires fast even if read later.
    """
    conn = _conn()
    row = conn.execute(
        "SELECT payload, fetched_at FROM quote_cache WHERE ticker = ?",
        (ticker,)
    ).fetchone()
    conn.close()

    if row is None:
        return None

    age = _time.time() - row["fetched_at"]
    if age > market.current_ttl():
        return None

    quote = json.loads(row["payload"])
    quote["cached"] = True
    quote["age_seconds"] = round(age)
    return quote


def put_quote(ticker, quote):
    """Store a quote. Overwrites any previous entry for this ticker."""
    conn = _conn()
    conn.execute(
        "INSERT OR REPLACE INTO quote_cache (ticker, payload, fetched_at) VALUES (?, ?, ?)",
        (ticker, json.dumps(quote), _time.time())
    )
    conn.commit()
    conn.close()


def put_history(ticker, rows):
    """
    Store daily closes. INSERT OR IGNORE because a given day's close
    is immutable - if we already have it, the new copy is identical.
    rows: list of (date_string, close, volume)
    """
    conn = _conn()
    conn.executemany(
        "INSERT OR IGNORE INTO daily_history (ticker, date, close, volume) VALUES (?, ?, ?, ?)",
        [(ticker, d, c, v) for d, c, v in rows]
    )
    conn.commit()
    conn.close()


def get_history(ticker, limit=30):
    """Return the most recent daily closes, oldest first."""
    conn = _conn()
    rows = conn.execute(
        """
        SELECT date, close, volume FROM daily_history
        WHERE ticker = ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (ticker, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def history_count(ticker):
    """How many days of history we hold. Used to decide if we can compute a baseline."""
    conn = _conn()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM daily_history WHERE ticker = ?",
        (ticker,)
    ).fetchone()["n"]
    conn.close()
    return n
