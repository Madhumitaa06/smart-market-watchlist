import sqlite3
import threading
import time

import cache
import prices
import fetchguard

cache.setup()

conn = sqlite3.connect("watchlist.db")
conn.execute("DELETE FROM quote_cache")
conn.commit()
conn.close()

# --- Coalescing: 8 threads, same ticker, should produce 1 network call ---
calls = {"n": 0}
original = prices.get_price

def counting_fetch(ticker):
    calls["n"] += 1
    time.sleep(0.4)
    return original(ticker)

prices.get_price = counting_fetch

threads = [threading.Thread(target=prices.get_price_guarded, args=("RELIANCE.NS",))
           for _ in range(8)]

start = time.time()
for t in threads: t.start()
for t in threads: t.join()

print("8 concurrent requests for the same ticker")
print(f"  network calls made: {calls['n']}  (want 1)")
print(f"  elapsed: {time.time() - start:.2f}s")

prices.get_price = original

# --- Rate limiter ---
lim = fetchguard.RateLimiter(limit=5, window=1.0)
start = time.time()
for _ in range(10):
    lim.acquire()
print(f"\n10 calls through a 5/sec limiter: {time.time() - start:.2f}s  (want ~1s)")
