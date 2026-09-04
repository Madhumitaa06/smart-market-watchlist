from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import database
import prices
import cache
import refresher
import anomaly
import market

app = FastAPI(title="Smart Market Watchlist")

# No auth yet. Every request acts as user 1 - the column exists so
# adding login later doesn't require a schema change.
CURRENT_USER = 1


@app.on_event("startup")
def startup():
    """Make sure the table exists before serving any requests."""
    database.setup()
    cache.setup()
    refresher.start()


class AddStockRequest(BaseModel):
    ticker: str


@app.get("/watchlist")
def read_watchlist():
    """
    Return the watchlist split into three groups.

    Grouping rather than one ranked list, because these are different kinds
    of thing and ranking them against each other forces a comparison that
    doesn't mean anything. A stock we couldn't price isn't "less important"
    than one that moved 3%, it's an unknown - and burying it at the bottom
    of a long list means the user may never notice their data is broken.
    """
    entries = database.get_watchlist(CURRENT_USER)
    tickers = [e["ticker"] for e in entries]

    if not tickers:
        return {"needs_attention": [], "quiet": [], "unavailable": [],
                "market_open": market.is_market_open()}

    for t in tickers:
        prices.ensure_history(t)

    open_now = market.is_market_open()
    results = [anomaly.present(anomaly.enrich(r), open_now)
               for r in prices.get_prices_cached(tickers)]

    added_at = {e["ticker"]: e["added_at"] for e in entries}
    for r in results:
        r["added_at"] = added_at.get(r["ticker"])

    needs_attention, quiet, unavailable = [], [], []

    for stock in results:
        if not stock.get("ok"):
            unavailable.append(stock)
            continue

        verdict = stock.get("anomaly") or {}
        if verdict.get("unusual"):
            needs_attention.append(stock)
        else:
            quiet.append(stock)

    # Within the flagged group, most extreme first. Absolute z, because a
    # sharp drop deserves attention as much as a sharp rise.
    needs_attention.sort(key=lambda s: abs(s["anomaly"].get("z_score", 0)), reverse=True)

    return {
        "needs_attention": needs_attention,
        "quiet": quiet,
        "unavailable": unavailable,
        "market_open": market.is_market_open(),
        "summary": _summarise(needs_attention, quiet, unavailable),
    }


def _summarise(flagged, quiet, unavailable):
    """
    One line the UI can show above everything else. When nothing is flagged,
    say so explicitly - an empty section reads as broken, but 'nothing
    significant' is genuinely useful information.
    """
    if not flagged and not quiet and not unavailable:
        return "Your watchlist is empty."

    if not flagged:
        return f"Nothing unusual across your {len(quiet)} stocks."

    if len(flagged) == 1:
        return f"1 stock moved unusually: {flagged[0]['ticker']}."

    return f"{len(flagged)} stocks moved unusually."


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
