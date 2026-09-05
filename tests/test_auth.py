"""
Account handling. The tests that matter are the ones covering what an
attacker could learn, not just whether login works.
"""

import sqlite3
import auth


def test_a_user_can_be_created_and_verified():
    uid, err = auth.create_user("alice", "correcthorse", "a@example.com")
    assert err is None
    assert auth.verify_user("alice", "correcthorse") == uid


def test_wrong_password_fails():
    auth.create_user("alice", "correcthorse", "a@example.com")
    assert auth.verify_user("alice", "wrong") is None


def test_unknown_user_fails_the_same_way():
    assert auth.verify_user("nobody", "anything") is None


def test_passwords_are_not_stored():
    auth.create_user("alice", "correcthorse", "a@example.com")
    conn = sqlite3.connect(auth.DB_FILE)
    stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    conn.close()
    assert "correcthorse" not in stored
    assert stored.startswith("$2")


def test_duplicate_username_is_rejected():
    auth.create_user("alice", "correcthorse", "a@example.com")
    uid, err = auth.create_user("alice", "different1", "b@example.com")
    assert uid is None
    assert err is not None


def test_duplicate_email_is_rejected_without_saying_which():
    """The error must not confirm whether an address is already registered."""
    auth.create_user("alice", "correcthorse", "a@example.com")
    uid, err = auth.create_user("bob", "different1", "a@example.com")
    assert uid is None
    assert "email" in err.lower() and "username" in err.lower()


def test_short_password_rejected():
    uid, err = auth.create_user("alice", "short", "a@example.com")
    assert uid is None


def test_session_round_trip():
    assert auth.read_session(auth.make_session(42)) == 42


def test_a_tampered_session_is_rejected():
    token = auth.make_session(42)
    assert auth.read_session(token[:-3] + "xyz") is None
    assert auth.read_session("not-a-token") is None
    assert auth.read_session(None) is None
