"""
Coalescing and rate limiting. Both are concurrency behaviour, so they're
asserted rather than eyeballed - a regression here is invisible until you're
being rate limited in production.
"""

import threading
import time

import fetchguard


def test_concurrent_requests_for_one_key_share_a_single_fetch():
    calls = {"n": 0}

    def slow_fetch():
        calls["n"] += 1
        time.sleep(0.3)
        return "result"

    threads = [threading.Thread(target=fetchguard.coalesce, args=("K", slow_fetch))
               for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert calls["n"] == 1, f"expected 1 fetch, got {calls['n']}"


def test_different_keys_do_not_share():
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        time.sleep(0.05)
        return "x"

    t1 = threading.Thread(target=fetchguard.coalesce, args=("A", fetch))
    t2 = threading.Thread(target=fetchguard.coalesce, args=("B", fetch))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert calls["n"] == 2


def test_the_limiter_refuses_a_burst():
    lim = fetchguard.RateLimiter(limit=5, window=1.0)
    start = time.time()
    for _ in range(10):
        lim.acquire()
    assert time.time() - start >= 0.9


def test_the_limiter_does_not_block_under_the_cap():
    lim = fetchguard.RateLimiter(limit=10, window=1.0)
    start = time.time()
    for _ in range(5):
        lim.acquire()
    assert time.time() - start < 0.2
