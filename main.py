from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import database
import prices

app = FastAPI(title="Smart Market Watchlist")

# No auth yet. Every request acts as user 1 - the column exists so
# adding login later doesn't require a schema change.
CURRENT_USER = 1


@app.on_event("startup")
def startup():
    """Make sure the table exists before serving any requests."""
    database.setup()


class AddStockRequest(BaseModel):
    ticker: str


@app.get("/watchlist")
def read_watchlist():
    """
    Return the user's watchlist with current prices.
    Price failures are per-stock: a failing ticker is marked unavailable
    rather than failing the whole response.
    """
    entries = database.get_watchlist(CURRENT_USER)
    tickers = [e["ticker"] for e in entries]

    if not tickers:
        return {"stocks": []}

    results = prices.get_prices(tickers)

    # Merge the stored 'added_at' into each price result.
    added_at = {e["ticker"]: e["added_at"] for e in entries}
    for r in results:
        r["added_at"] = added_at.get(r["ticker"])

    return {"stocks": results}


@app.post("/watchlist")
def add_to_watchlist(request: AddStockRequest):
    """
    Add a ticker to the watchlist.
    Validates the ticker exists before storing it - we don't want dead
    symbols sitting in the list failing on every future load.
    """
    ticker = request.ticker.strip().upper()

    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker cannot be empty.")

    # Check it's real before we commit it to the database.
    check = prices.get_price(ticker)
    if not check["ok"]:
        raise HTTPException(status_code=400, detail=check["message"])

    added = database.add_stock(CURRENT_USER, ticker)
    if not added:
        raise HTTPException(status_code=409, detail=f"{ticker} is already in your watchlist.")

    return {"ticker": ticker, "added": True}


@app.delete("/watchlist/{ticker}")
def remove_from_watchlist(ticker: str):
    """Remove a ticker from the watchlist."""
    ticker = ticker.strip().upper()
    removed = database.remove_stock(CURRENT_USER, ticker)

    if not removed:
        raise HTTPException(status_code=404, detail=f"{ticker} is not in your watchlist.")

    return {"ticker": ticker, "removed": True}
