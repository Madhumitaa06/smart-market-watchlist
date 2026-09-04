import requests
import prices

class FakeTicker:
    def __init__(self, exc):
        self.exc = exc
    def history(self, period):
        raise self.exc

original = prices.yf.Ticker

def check(name, exc):
    prices.yf.Ticker = lambda t: FakeTicker(exc)
    r = prices.get_price("RELIANCE.NS")
    print(f"{name}: reason={r['reason']}")
    print(f"   message={r['message']}\n")

check("Connection error", requests.exceptions.ConnectionError())
check("Timeout", requests.exceptions.Timeout())
check("Unexpected error", ValueError("something odd"))

prices.yf.Ticker = original
