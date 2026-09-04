import sqlite3

DB_FILE = "watchlist.db"


def get_connection():
    """Open a connection to the database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # lets us read columns by name
    return conn


def setup():
    """Create the table if it doesn't exist yet. Safe to run repeatedly."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, ticker)
        )
    """)
    conn.commit()
    conn.close()


def add_stock(user_id, ticker):
    """Add a ticker to a user's watchlist. Returns True if added, False if already there."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO watchlist (user_id, ticker) VALUES (?, ?)",
            (user_id, ticker)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # already in the list
    finally:
        conn.close()


def remove_stock(user_id, ticker):
    """Remove a ticker. Returns True if something was actually removed."""
    conn = get_connection()
    cursor = conn.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
        (user_id, ticker)
    )
    conn.commit()
    removed = cursor.rowcount > 0
    conn.close()
    return removed


def get_watchlist(user_id):
    """Return all tickers for a user, oldest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT ticker, added_at FROM watchlist WHERE user_id = ? ORDER BY added_at",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
