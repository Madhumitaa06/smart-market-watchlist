from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

import database
import prices
import cache
import auth
import refresher
import anomaly
import assistant
import market

app = FastAPI(title="Smart Market Watchlist")


@app.on_event("startup")
def startup():
    """Make sure the table exists before serving any requests."""
    database.setup()
    cache.setup()
    auth.setup()
    refresher.start()


class AddStockRequest(BaseModel):
    ticker: str


@app.get("/watchlist")
def read_watchlist(request: Request, response: Response):
    """
    Return the watchlist split into three groups.

    Grouping rather than one ranked list, because these are different kinds
    of thing and ranking them against each other forces a comparison that
    doesn't mean anything. A stock we couldn't price isn't "less important"
    than one that moved 3%, it's an unknown - and burying it at the bottom
    of a long list means the user may never notice their data is broken.
    """
    entries = database.get_watchlist(current_user(request, response))
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
def add_to_watchlist(body: AddStockRequest, request: Request, response: Response):
    """
    Add a ticker to the watchlist.
    Validates the ticker exists before storing it - we don't want dead
    symbols sitting in the list failing on every future load.
    """
    ticker = body.ticker.strip().upper()

    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker cannot be empty.")

    # Check it's real before we commit it to the database.
    check = prices.get_price(ticker)
    if not check["ok"]:
        raise HTTPException(status_code=400, detail=check["message"])

    added = database.add_stock(current_user(request, response), ticker)
    if not added:
        raise HTTPException(status_code=409, detail=f"{ticker} is already in your watchlist.")

    return {"ticker": ticker, "added": True}


@app.delete("/watchlist/{ticker}")
def remove_from_watchlist(ticker: str, request: Request, response: Response):
    """Remove a ticker from the watchlist."""
    ticker = ticker.strip().upper()
    removed = database.remove_stock(current_user(request, response), ticker)

    if not removed:
        raise HTTPException(status_code=404, detail=f"{ticker} is not in your watchlist.")

    return {"ticker": ticker, "removed": True}


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/how")
def how_it_works():
    """
    The reasoning behind the app, in the app.

    Kept in the product rather than only in a README because the argument
    for judging each stock against its own baseline is the whole point -
    a user who doesn't understand why it stays quiet will assume it's broken.
    """
    return FileResponse("static/how.html")


@app.get("/events/{ticker}")
def stock_events(ticker: str):
    """
    Anomalous days from this stock's stored history.

    Each past day is judged against the 30 days before it, not against
    today's baseline - a day is unusual by the standard that applied at
    the time. These are real moves from real data, not examples.
    """
    ticker = ticker.strip().upper()
    prices.ensure_history(ticker)
    return {"ticker": ticker, "events": anomaly.past_events(ticker)}


class Credentials(BaseModel):
    username: str
    password: str


class SignupRequest(BaseModel):
    username: str
    password: str
    email: str


class ResetRequest(BaseModel):
    email: str


class ResetComplete(BaseModel):
    token: str
    password: str


def current_user(request: Request, response: Response = None):
    """
    Who this request belongs to - a signed-in user, or an anonymous guest.

    A signup wall before anyone has seen the product is a poor trade: the
    thing worth signing up for is the thing you can't see yet. So a visitor
    gets a device-scoped identity and can use the app immediately; if they
    sign up, their list comes with them.

    One place decides identity, so no endpoint has to think about it.
    """
    uid = auth.read_session(request.cookies.get(auth.COOKIE_NAME))
    if uid is not None:
        return uid

    guest = auth.read_session(request.cookies.get(auth.GUEST_COOKIE))
    if guest is not None:
        return guest

    if response is None:
        # No way to hand back a new cookie, so nothing to attach a list to.
        raise HTTPException(status_code=401, detail="Please log in.")

    guest_id = auth.make_guest()
    response.set_cookie(
        auth.GUEST_COOKIE,
        auth.make_session(guest_id),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 90,
    )
    return guest_id


def _set_session(response: Response, user_id: int):
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.make_session(user_id),
        httponly=True,      # JavaScript can't read it, so XSS can't steal it
        samesite="lax",     # not sent on cross-site requests
        max_age=60 * 60 * 24 * 30,
    )


@app.post("/signup")
def signup(creds: SignupRequest, request: Request, response: Response):
    user_id, error = auth.create_user(creds.username, creds.password, creds.email)
    if error:
        raise HTTPException(status_code=400, detail=error)

    # Carry across anything added before signing up - otherwise trying the
    # product first punishes you for it.
    moved = 0
    guest_id = auth.read_session(request.cookies.get(auth.GUEST_COOKIE))
    if guest_id is not None:
        moved = auth.merge_guest_into(guest_id, user_id)
        response.delete_cookie(auth.GUEST_COOKIE)

    _set_session(response, user_id)
    return {"username": creds.username.strip().lower(), "merged": moved}


@app.post("/login")
def login(creds: Credentials, request: Request, response: Response):
    user_id = auth.verify_user(creds.username, creds.password)
    if user_id is None:
        # Same message whether the username is unknown or the password is
        # wrong - otherwise this endpoint enumerates valid accounts.
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    moved = 0
    guest_id = auth.read_session(request.cookies.get(auth.GUEST_COOKIE))
    if guest_id is not None:
        moved = auth.merge_guest_into(guest_id, user_id)
        response.delete_cookie(auth.GUEST_COOKIE)

    _set_session(response, user_id)
    return {"username": creds.username.strip().lower(), "merged": moved}


@app.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/me")
def me(request: Request):
    """Who is logged in, if anyone. The frontend uses this to decide what to show."""
    uid = auth.read_session(request.cookies.get(auth.COOKIE_NAME))
    if uid is not None:
        return {"logged_in": True, "guest": False}

    guest = auth.read_session(request.cookies.get(auth.GUEST_COOKIE))
    return {"logged_in": False, "guest": guest is not None}


@app.post("/reset/start")
def reset_start(body: ResetRequest):
    """
    Begin a password reset.

    Always returns the same response whether or not the email is registered.
    Saying "no account with that email" would let anyone test addresses
    against the user base.

    Delivery is stubbed: the token comes back in the response instead of
    being emailed. Generation, hashing, expiry and single-use are real.
    """
    token = auth.start_reset(body.email)
    username = auth.find_username(body.email)

    result = {
        "message": "If that email is registered, a reset link has been sent."
    }

    # Stub only - would not exist once email delivery is wired up.
    if token:
        result["dev_token"] = token
        result["dev_username"] = username
        result["dev_note"] = "Returned here because email delivery is out of scope."

    return result


@app.post("/reset/complete")
def reset_complete(body: ResetComplete):
    ok, error = auth.complete_reset(body.token, body.password)
    if not ok:
        raise HTTPException(status_code=400, detail=error)
    return {"ok": True}


@app.get("/digest")
def catch_up(request: Request):
    """
    What changed since the user last looked.

    Only the anomalous days from the gap - not every day. A user away for
    three months gets however many events actually occurred, which might be
    three or eight; the length follows the data, not the calendar.

    A single since-you-left delta would hide the story: -5% on Wednesday and
    +5% on Thursday nets to zero, when in fact something happened twice.
    """
    user_id = current_user(request)
    last_seen = auth.get_last_viewed(user_id)

    entries = database.get_watchlist(user_id)
    tickers = [e["ticker"] for e in entries]

    # First visit for a stock: the moment it was added is the baseline,
    # since the user has never looked at it before.
    added_at = {e["ticker"]: (e["added_at"] or "")[:10] for e in entries}

    events = []
    for t in tickers:
        prices.ensure_history(t)
        since = last_seen[:10] if last_seen else added_at.get(t)
        events.extend(anomaly.digest(t, since))

    events.sort(key=lambda e: e["date"], reverse=True)

    # Mark the visit only after a real gap, so refreshing doesn't wipe the
    # digest and replace it with "nothing in the last five minutes".
    should_touch = True
    if last_seen:
        try:
            from datetime import datetime
            gap = datetime.now() - datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
            should_touch = gap.total_seconds() > 30 * 60
        except ValueError:
            should_touch = True

    if should_touch:
        auth.touch_last_viewed(user_id)

    return {
        "since": last_seen,
        "first_visit": last_seen is None,
        "events": events,
        "summary": _digest_summary(events, last_seen, len(tickers)),
    }


def _digest_summary(events, last_seen, stock_count):
    """
    A blank digest reads as broken; 'nothing significant happened' is a real
    answer and worth saying out loud.
    """
    if not stock_count:
        return "Add a stock to start tracking what changes."

    if last_seen is None:
        return "Welcome. From now on, this shows what changed while you were away."

    if not events:
        return "Nothing significant happened while you were away."

    if len(events) == 1:
        return f"One thing happened while you were away."

    tickers = len({e["ticker"] for e in events})
    if tickers == 1:
        return f"{len(events)} notable days on {events[0]['ticker']} while you were away."

    return f"{len(events)} notable days across {tickers} stocks while you were away."


class Question(BaseModel):
    question: str


@app.post("/ask")
def ask(body: Question, request: Request, response: Response):
    """
    Answer a question from stored data only.

    No model, no generation. Questions are matched to intents and answered by
    querying the same history the anomaly detector uses, so every figure in a
    reply is one the system already holds. Investment advice is declined
    explicitly rather than deflected.
    """
    return assistant.answer(body.question, current_user(request, response))


@app.get("/ask")
def ask_page():
    return FileResponse("static/ask.html")
