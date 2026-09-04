import prices

print("--- Real stock ---")
print(prices.get_price("RELIANCE.NS"))

print("\n--- Bad ticker ---")
r = prices.get_price("NOTAREALSTOCK.NS")
print("reason: ", r["reason"])
print("message:", r["message"])
