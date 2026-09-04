"""
User accounts, sessions, and password reset.

Passwords are hashed with bcrypt, never stored. Sessions are signed cookies:
the server signs a user id and the browser hands it back on each request.
A signed cookie can be read but not forged, which is enough here - it carries
no secret, only an identity claim we can verify.
"""

import hashlib
import os
import secrets
import sqlite3
import time as _time

import bcrypt
from itsdangerous import URLSafeSerializer, BadSignature

DB_FILE = "watchlist.db"
COOKIE_NAME = "session"
RESET_TTL = 30 * 60          # reset links last 30 minutes

# In production this must come from the environment. The fallback lets the
# app run locally without setup; it means sessions reset on redeploy.
SECRET = os.environ.get("SESSION_SECRET", "dev-only-not-for-production")
signer = URLSafeSerializer(SECRET, salt="session")

# bcrypt directly rather than via passlib: passlib 1.7.4 predates bcrypt 4.1
# and its startup self-check hashes an over-length password, which bcrypt 5.0
# rejects rather than silently truncating. One less layer, and one that broke.
BCRYPT_MAX = 72


def _hash(password):
    return bcrypt.hashpw(password.encode("utf-8")[:BCRYPT_MAX], bcrypt.gensalt()).decode()


def _verify(password, hashed):
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:BCRYPT_MAX], hashed.encode())
    except ValueError:
        return False


# Fixed hash used to equalise timing when a username doesn't exist. Comparing
# against this costs about what a real check costs, without the wasted work
# of hashing a throwaway string every time.
_DUMMY_HASH = _hash("timing-equaliser")


def _conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def setup():
    conn = _conn()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_viewed_at TEXT
        )
    """)

    # Reset tokens are stored hashed, never in the clear - a leaked database
    # then yields no usable tokens. Same reasoning as passwords.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reset_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at REAL NOT NULL,
            used INTEGER NOT NULL DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


def create_user(username, password, email):
    """
    Returns (user_id, None) or (None, error_message).

    Uniqueness is enforced by the DB constraint rather than a prior lookup -
    a check-then-insert leaves a window where two signups race.
    """
    username = (username or "").strip().lower()
    email = (email or "").strip().lower()

    if len(username) < 3:
        return None, "Username must be at least 3 characters."
    if len(password) < 8:
        return None, "Password must be at least 8 characters."

    # Deliberately loose. A stricter pattern rejects valid addresses more
    # often than it catches typos, and an address can't be confirmed without
    # sending to it anyway.
    if "@" not in email or "." not in email.split("@")[-1]:
        return None, "That doesn't look like an email address."

    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
            (username, _hash(password), email)
        )
        conn.commit()
        return cur.lastrowid, None
    except sqlite3.IntegrityError:
        # UNIQUE covers both columns; we don't say which collided, since
        # that would confirm whether an address is already registered.
        return None, "That username or email is already registered."
    finally:
        conn.close()


def verify_user(username, password):
    """
    Returns user_id or None.

    Same result for an unknown username and a wrong password, so the response
    can't be used to work out which accounts exist.
    """
    username = (username or "").strip().lower()

    conn = _conn()
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE username = ?",
        (username,)
    ).fetchone()
    conn.close()

    if row is None:
        # Verify against a fixed hash so a missing user costs roughly the
        # same as a wrong password - otherwise timing leaks which usernames
        # exist, regardless of what the message says.
        _verify(password, _DUMMY_HASH)
        return None

    if not _verify(password, row["password_hash"]):
        return None

    return row["id"]


def make_session(user_id):
    return signer.dumps({"uid": user_id})


def read_session(token):
    """User id from a session cookie, or None if absent or forged."""
    if not token:
        return None
    try:
        return signer.loads(token).get("uid")
    except BadSignature:
        return None


def touch_last_viewed(user_id):
    conn = _conn()
    conn.execute(
        "UPDATE users SET last_viewed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()


def get_last_viewed(user_id):
    conn = _conn()
    row = conn.execute(
        "SELECT last_viewed_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["last_viewed_at"] if row else None


# --- Password reset -------------------------------------------------------


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def start_reset(email):
    """
    Issue a reset token for an email, if it belongs to an account.
    Returns the token, or None. The caller must not reveal which.

    Delivery is out of scope: in a deployed system this token would be
    emailed as a link. The generation, hashing, expiry and single-use logic
    are real; only the transport is missing.
    """
    email = (email or "").strip().lower()

    conn = _conn()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()

    if row is None:
        conn.close()
        return None

    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO reset_tokens (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (_token_hash(token), row["id"], _time.time() + RESET_TTL)
    )
    conn.commit()
    conn.close()
    return token


def complete_reset(token, new_password):
    """Consume a reset token and set a new password. Returns (ok, error)."""
    if len(new_password) < 8:
        return False, "Password must be at least 8 characters."

    conn = _conn()
    row = conn.execute(
        "SELECT user_id, expires_at, used FROM reset_tokens WHERE token_hash = ?",
        (_token_hash(token),)
    ).fetchone()

    if row is None:
        conn.close()
        return False, "That reset link isn't valid."

    if row["used"]:
        conn.close()
        return False, "That reset link has already been used."

    if _time.time() > row["expires_at"]:
        conn.close()
        return False, "That reset link has expired. Request a new one."

    # Mark used and change the password together, so a crash between the
    # two can't leave a token spendable twice.
    conn.execute("UPDATE reset_tokens SET used = 1 WHERE token_hash = ?",
                 (_token_hash(token),))
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (_hash(new_password), row["user_id"]))
    conn.commit()
    conn.close()
    return True, None


def find_username(email):
    conn = _conn()
    row = conn.execute(
        "SELECT username FROM users WHERE email = ?",
        ((email or "").strip().lower(),)
    ).fetchone()
    conn.close()
    return row["username"] if row else None
