import time
import cache
import prices

cache.setup()

tickers = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS"]

# Clear the cache so we measure real fetches.
import sqlite3
conn = sqlite3.connect("watchlist.db")
conn.execute("DELETE FROM quote_cache")
conn.commit()
conn.close()

start = time.time()
results = prices.get_prices_cached(tickers)
elapsed = time.time() - start

print(f"Fetched {len(results)} tickers in {elapsed:.2f}s")
print("Order preserved:", [r["ticker"] for r in results] == tickers)
for r in results:
    status = "ok" if r["ok"] else r.get("reason")
    print(f"  {r['ticker']}: {status}")

# Second run should be near-instant from cache.
start = time.time()
prices.get_prices_cached(tickers)
print(f"\nCached run: {time.time() - start:.2f}s")
