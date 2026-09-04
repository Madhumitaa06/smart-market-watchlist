# Smart Market Watchlist

Built for Code, by Groww (Sep 2026).

A watchlist that goes beyond showing prices - the goal is to surface what has
*meaningfully* changed since you last looked.

## Status

Backend working end to end:
- SQLite storage with DB-level duplicate prevention
- Price fetching via yfinance, with per-stock failure isolation
- Three tested failure modes: unknown ticker, service unavailable, network error
- FastAPI endpoints: add, remove, list with live prices

Still to build: meaningful-change detection, frontend, auth.

## Run it

    pip3 install fastapi uvicorn yfinance
    uvicorn main:app --reload

Then open http://127.0.0.1:8000/docs

## Notes

See notes.txt for the running log of design decisions.
