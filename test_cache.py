import cache
import market

cache.setup()

print("Market open right now:", market.is_market_open())
print("Current TTL (seconds):", market.current_ttl())

cache.put_quote("TEST.NS", {"ticker": "TEST.NS", "price": 100.0})
print("\nImmediately after put:", cache.get_quote("TEST.NS"))

cache.put_history("TEST.NS", [
    ("2026-09-01", 100.0, 1000),
    ("2026-09-02", 102.0, 1200),
    ("2026-09-03", 101.0,  900),
])
cache.put_history("TEST.NS", [("2026-09-03", 101.0, 900)])  # duplicate, ignored

print("\nHistory:", cache.get_history("TEST.NS"))
print("Row count (should be 3):", cache.history_count("TEST.NS"))
