import cache
import prices
import anomaly

cache.setup()

for ticker in ["RELIANCE.NS", "TCS.NS", "INFY.NS"]:
    print(f"\n=== {ticker} ===")
    stored = prices.fetch_history(ticker)
    print(f"History rows stored: {stored}")

    quote = prices.get_price(ticker)
    if not quote["ok"]:
        print("Quote failed:", quote["message"])
        continue

    verdict = anomaly.assess(ticker, quote["change_pct"], quote["volume"])
    for k, v in verdict.items():
        print(f"  {k}: {v}")
