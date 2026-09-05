"""
Password reset. Single-use and non-revealing are the two properties worth
locking down - both are easy to break with an innocent-looking change.
"""

import sqlite3
import auth


def test_reset_changes_the_password():
    auth.create_user("alice", "originalpass", "a@example.com")
    token = auth.start_reset("a@example.com")
    ok, err = auth.complete_reset(token, "brandnewpass")
    assert ok
    assert auth.verify_user("alice", "brandnewpass") is not None
    assert auth.verify_user("alice", "originalpass") is None


def test_a_token_cannot_be_used_twice():
    auth.create_user("alice", "originalpass", "a@example.com")
    token = auth.start_reset("a@example.com")
    auth.complete_reset(token, "firstchange")
    ok, err = auth.complete_reset(token, "secondchange")
    assert not ok
    assert "already been used" in err


def test_an_unknown_email_yields_no_token():
    """The endpoint returns the same message either way; the absence of a
    token is what stops an attacker enumerating registered addresses."""
    assert auth.start_reset("nobody@example.com") is None


def test_tokens_are_stored_hashed():
    auth.create_user("alice", "originalpass", "a@example.com")
    token = auth.start_reset("a@example.com")
    conn = sqlite3.connect(auth.DB_FILE)
    stored = conn.execute("SELECT token_hash FROM reset_tokens").fetchone()[0]
    conn.close()
    assert stored != token


def test_a_forged_token_is_rejected():
    ok, err = auth.complete_reset("made-up-token", "newpassword1")
    assert not ok
