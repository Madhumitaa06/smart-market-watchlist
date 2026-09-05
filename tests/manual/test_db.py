import database

database.setup()

print("Add RELIANCE:", database.add_stock(1, "RELIANCE.NS"))
print("Add TCS:", database.add_stock(1, "TCS.NS"))
print("Add RELIANCE again:", database.add_stock(1, "RELIANCE.NS"))

print("\nWatchlist:", database.get_watchlist(1))

print("\nRemove TCS:", database.remove_stock(1, "TCS.NS"))
print("Remove TCS again:", database.remove_stock(1, "TCS.NS"))

print("\nFinal:", database.get_watchlist(1))
