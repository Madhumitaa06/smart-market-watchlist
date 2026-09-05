import yfinance as yf

stock = yf.Ticker("RELIANCE.NS")

price = stock.history(period="1d")
print("PRICE TEST:")
print(price[['Close', 'Volume']])

print("\nNEWS TEST:")
news = stock.news
if news:
    for item in news[:3]:
        print("-", item.get('title'))
else:
    print("No news returned")
