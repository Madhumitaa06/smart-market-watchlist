"""
Two protections on outbound calls to Yahoo.

Coalescing: if several requests want the same uncached ticker at the same
moment, only one goes to the network and the rest wait for its result.
Without this, ten users hitting a cold popular ticker means ten identical
fetches racing each other.

Rate limiting: a ceiling on total outbound calls per second, regardless of
who is asking. Parallel fetching bounds concurrency within one request but
does nothing across simultaneous requests - ten users x twenty stocks is
still a 200-call burst from one IP.
"""

import threading
import time
from collections import deque

# --- Coalescing -----------------------------------------------------------

_inflight = {}              # ticker -> Event, set when the fetch completes
_results = {}               # ticker -> result of the fetch that ran
_inflight_lock = threading.Lock()


def coalesce(key, fetch_fn):
    """
    Run fetch_fn() for `key`, or wait on the call already running for it.

    The lock is held only while checking and registering, never during the
    network call itself - holding it across the fetch would serialise every
    ticker and undo the parallelism.
    """
    with _inflight_lock:
        event = _inflight.get(key)
        if event is None:
            # We're the leader for this key.
            event = threading.Event()
            _inflight[key] = event
            leader = True
        else:
            leader = False

    if not leader:
        # Someone else is already fetching this. Wait for them.
        # Timeout so a hung leader can't block followers indefinitely.
        if event.wait(timeout=15):
            if key in _results:
                return _results[key]
        # Leader failed or timed out - fall through and fetch ourselves.
        return fetch_fn()

    try:
        result = fetch_fn()
        _results[key] = result
        return result
    finally:
        with _inflight_lock:
            _inflight.pop(key, None)
        event.set()
        # Followers read _results immediately after the event fires, so the
        # entry is cleared on a short delay rather than synchronously.
        threading.Timer(1.0, lambda: _results.pop(key, None)).start()


# --- Rate limiting --------------------------------------------------------

class RateLimiter:
    """
    Sliding-window limiter: at most `limit` calls in any `window` seconds.

    Chose a sliding window over a token bucket because the failure we care
    about is a burst - twenty users arriving at once - and a sliding window
    refuses those precisely, where a bucket would let a full burst through
    on a fresh refill.
    """

    def __init__(self, limit=20, window=1.0):
        self.limit = limit
        self.window = window
        self._calls = deque()
        self._lock = threading.Lock()

    def acquire(self, timeout=10.0):
        """Block until a slot is free. Returns False if it waited too long."""
        deadline = time.time() + timeout

        while True:
            with self._lock:
                now = time.time()
                while self._calls and now - self._calls[0] > self.window:
                    self._calls.popleft()

                if len(self._calls) < self.limit:
                    self._calls.append(now)
                    return True

                wait_for = self.window - (now - self._calls[0])

            if time.time() + wait_for > deadline:
                return False
            time.sleep(min(wait_for, 0.05))


limiter = RateLimiter(limit=20, window=1.0)
