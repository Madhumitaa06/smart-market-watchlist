import yfinance as yf
import json

stock = yf.Ticker("RELIANCE.NS")
news = stock.news

print("Number of items:", len(news))
print("\nFirst item, full structure:")
print(json.dumps(news[0], indent=2, default=str))
