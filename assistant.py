"""
A restricted assistant that answers only from stored data.

No language model. Questions are matched to intents and answered by querying
the same history the anomaly detector uses, so every number in an answer is
one the system already computed and could show you.

That constraint is the point. The rest of the product never asserts anything
it can't back with a figure; an assistant that generated plausible-sounding
text would be the one component that could. Deterministic lookups can be
wrong about intent - they cannot be wrong about facts.
"""

import re
import statistics

import cache
import database
import anomaly


# Questions this deliberately won't answer. Investment advice from an
# unlicensed source is a regulatory line, not a stylistic one.
ADVICE_PATTERNS = [
    r"\bshould i (buy|sell|invest|hold|exit)",
    r"\bis \w+ (a )?good (buy|investment|time|entry|stock|idea)",
    r"\b(good|bad) (time|idea) to (buy|sell|invest|enter|exit)",
    r"\bshould .* (buy|sell|invest in|hold)",
    r"\bworth (buying|investing|holding)",
    r"\bwill \w+ (go|rise|fall|drop|increase|decrease|crash|recover|bounce)",
    r"\b(going|likely) to (go|rise|fall|drop|crash|recover)",
    r"\bwhat will .* (be|do) (tomorrow|next|in)",
    r"\bpredict",
    r"\bforecast",
    r"\bshould i put money",
    r"\brecommend a stock",
    r"\bwhich stock (should|is best)",
]

ADVICE_REPLY = (
    "I can tell you what a stock has done - how it moved, whether that was "
    "unusual for it, when it last had a notable day. I can't tell you whether "
    "to buy, sell or hold, or where a price is going. That's investment advice, "
    "and it isn't something this app is set up to give.\n\n"
    "Try asking what a stock has actually done instead."
)

CAPABILITIES = (
    "I answer from the price history this app has stored. I can tell you:\n\n"
    "- how much a stock moved over a week, month or year\n"
    "- whether it's had unusual days recently\n"
    "- its typical daily range\n"
    "- its high and low over the stored period\n"
    "- what's in your watchlist\n\n"
    "I can't give investment advice, predict prices, or answer anything "
    "outside the data I hold."
)


def _find_ticker(text, user_tickers):
    """
    Pull a ticker from the question.

    Checks the user's own watchlist first - if they ask about "TCS" they
    almost certainly mean the one they're tracking. Falls back to any
    NSE-shaped symbol so questions about unwatched stocks still work.
    """
    upper = text.upper()

    for t in user_tickers:
        base = t.replace(".NS", "")
        if re.search(rf"\b{re.escape(base)}\b", upper):
            return t

    # Scan every candidate rather than only the first. "How much did RELIANCE
    # move" starts with a common word, and stopping at the first match would
    # give up before reaching the ticker.
    skip = {"I", "THE", "AND", "IS", "HOW", "WHAT", "MY", "IN", "ON", "OF",
            "DID", "DOES", "HAS", "HAVE", "LAST", "THIS", "OR", "FOR", "WAS",
            "MUCH", "MOVE", "MOVED", "DAY", "DAYS", "WEEK", "MONTH", "YEAR",
            "ANY", "UNUSUAL", "VOLATILE", "HIGHEST", "LOWEST", "STOCK",
            "STOCKS", "ABOUT", "OVER", "SINCE", "FROM", "THAT", "THERE",
            "BEEN", "HAVE", "WITH", "PAST", "RECENT", "RECENTLY", "TELL",
            "SHOW", "GIVE", "PRICE", "TODAY", "NOW", "GOOD", "BAD"}

    for candidate in re.findall(r"\b([A-Z][A-Z0-9&\-]{2,19})(?:\.NS)?\b", upper):
        if candidate not in skip:
            return candidate if candidate.endswith(".NS") else candidate + ".NS"

    return None


def _period_days(text):
    """How far back the question is asking. Defaults to a month."""
    t = text.lower()
    if re.search(r"\b(year|12 months|yearly|annual)\b", t):
        return 250, "the last year"
    if re.search(r"\b(6 months|six months|half year)\b", t):
        return 125, "the last six months"
    if re.search(r"\b(week|7 days|seven days)\b", t):
        return 5, "the last week"
    if re.search(r"\b(month|30 days|thirty days)\b", t):
        return 22, "the last month"
    if re.search(r"\b(today|yesterday)\b", t):
        return 2, "the last day"
    m = re.search(r"\b(\d{1,3})\s*days?\b", t)
    if m:
        n = int(m.group(1))
        return n, f"the last {n} days"
    return 22, "the last month"


def _need_ticker():
    return {
        "answer": "Which stock? Name one from your watchlist, or any NSE "
                  "ticker - for example RELIANCE or TCS.",
        "kind": "clarify",
    }


def _no_data(ticker):
    return {
        "answer": f"I don't hold enough history for {ticker} yet. Add it to "
                  f"your watchlist and it'll build up from the next load.",
        "kind": "no_data",
    }


def answer(question, user_id):
    """
    Route a question to a lookup, or decline.

    Order matters: advice is checked before anything else, so a question like
    "should I buy Reliance" is declined rather than being answered as a
    price query because it happens to contain a ticker.
    """
    q = (question or "").strip()
    if not q:
        return {"answer": CAPABILITIES, "kind": "help"}

    lower = q.lower()

    for pattern in ADVICE_PATTERNS:
        if re.search(pattern, lower):
            return {"answer": ADVICE_REPLY, "kind": "declined"}

    if re.search(r"\b(help|what can you|what do you do|capabilities)\b", lower):
        return {"answer": CAPABILITIES, "kind": "help"}

    entries = database.get_watchlist(user_id)
    user_tickers = [e["ticker"] for e in entries]

    if re.search(r"\b(my watchlist|what am i (watching|tracking)|my stocks)\b", lower):
        if not user_tickers:
            return {"answer": "Your watchlist is empty.", "kind": "watchlist"}
        names = ", ".join(t.replace(".NS", "") for t in user_tickers)
        return {
            "answer": f"You're watching {len(user_tickers)} "
                      f"{'stock' if len(user_tickers) == 1 else 'stocks'}: {names}.",
            "kind": "watchlist",
        }

    ticker = _find_ticker(q, user_tickers)

    if re.search(r"\b(unusual|anomal|notable|spike|jump|anything happen)\b", lower):
        if not ticker:
            return _need_ticker()
        events = anomaly.past_events(ticker)
        if not events:
            return {
                "answer": f"No unusual days for {ticker.replace('.NS','')} in the "
                          f"history I hold - it's been behaving normally.",
                "kind": "events",
            }
        lines = [f"{e['date']}: {e['message']}" for e in events[:5]]
        more = f"\n\nand {len(events) - 5} more." if len(events) > 5 else ""
        return {
            "answer": f"{ticker.replace('.NS','')} had {len(events)} unusual "
                      f"{'day' if len(events) == 1 else 'days'}:\n\n"
                      + "\n\n".join(lines) + more,
            "kind": "events",
        }

    if re.search(r"\b(volatil|typical|normal range|normal move|usually move)\b", lower):
        if not ticker:
            return _need_ticker()
        history = cache.get_history(ticker, limit=30)
        if len(history) < 10:
            return _no_data(ticker)
        closes = [h["close"] for h in history]
        returns = anomaly._daily_returns(closes)
        stdev = statistics.stdev(returns)
        return {
            "answer": f"{ticker.replace('.NS','')} typically moves about "
                      f"{stdev:.2f}% on a given day, measured over the last "
                      f"{len(history)} trading days I hold. A move much beyond "
                      f"that is what this app flags.",
            "kind": "volatility",
        }

    if re.search(r"\b(high|highest|low|lowest|peak|max|min)\b", lower):
        if not ticker:
            return _need_ticker()
        days, label = _period_days(q)
        history = cache.get_history(ticker, limit=days)
        if len(history) < 2:
            return _no_data(ticker)
        closes = [h["close"] for h in history]
        hi, lo = max(closes), min(closes)
        hi_date = history[closes.index(hi)]["date"]
        lo_date = history[closes.index(lo)]["date"]
        return {
            "answer": f"Over {label} ({len(history)} trading days I hold), "
                      f"{ticker.replace('.NS','')} closed highest at Rs {hi:,.2f} "
                      f"on {hi_date} and lowest at Rs {lo:,.2f} on {lo_date}.",
            "kind": "range",
        }

    if re.search(r"\b(move|moved|change|changed|up|down|perform|gain|lose|lost|return)\b", lower):
        if not ticker:
            return _need_ticker()
        days, label = _period_days(q)
        history = cache.get_history(ticker, limit=days)
        if len(history) < 2:
            return _no_data(ticker)

        first, last = history[0]["close"], history[-1]["close"]
        pct = (last - first) / first * 100
        direction = "up" if pct >= 0 else "down"

        note = ""
        if len(history) < days * 0.8:
            note = (f" I only hold {len(history)} trading days for this stock, "
                    f"so that's the period this covers.")

        return {
            "answer": f"Over {label}, {ticker.replace('.NS','')} went from "
                      f"Rs {first:,.2f} ({history[0]['date']}) to Rs {last:,.2f} "
                      f"({history[-1]['date']}) - {direction} {abs(pct):.2f}%.{note}",
            "kind": "movement",
        }

    return {"answer": "I didn't follow that. " + CAPABILITIES, "kind": "unknown"}
