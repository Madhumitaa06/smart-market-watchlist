"""
Shared fixtures.

Every test runs against a throwaway database in a temp directory. The modules
read DB_FILE at call time rather than holding a connection, so pointing that
at a temp path is enough to isolate a test run completely - no risk of a test
touching real user data, and no ordering dependencies between tests.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth
import cache
import database


@pytest.fixture(autouse=True)
def temp_db(monkeypatch, tmp_path):
    db = str(tmp_path / "test.db")
    monkeypatch.setattr(database, "DB_FILE", db)
    monkeypatch.setattr(cache, "DB_FILE", db)
    monkeypatch.setattr(auth, "DB_FILE", db)

    database.setup()
    cache.setup()
    auth.setup()
    yield db


@pytest.fixture
def steady_history():
    """A calm stock: small daily moves, steady volume."""
    rows = []
    price = 100.0
    for i in range(40):
        price *= 1.002 if i % 2 else 0.998      # ~0.2% daily
        rows.append((f"2026-07-{i+1:02d}", round(price, 2), 1_000_000))
    return rows


@pytest.fixture
def choppy_history():
    """A volatile stock: large daily moves."""
    rows = []
    price = 100.0
    for i in range(40):
        price *= 1.04 if i % 2 else 0.96        # ~4% daily
        rows.append((f"2026-07-{i+1:02d}", round(price, 2), 1_000_000))
    return rows
