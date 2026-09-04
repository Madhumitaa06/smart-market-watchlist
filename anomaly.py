"""
Decides whether a stock's latest move is unusual *for that stock*.

A fixed threshold (e.g. "flag anything over 2%") treats a placid stock and a
volatile one identically, which is wrong: 2% on a stock that normally drifts
0.3% is an event, the same 2% on a stock that swings 3% daily is a Tuesday.
So each stock is judged against its own recent distribution.
"""

import statistics

import cache

WINDOW = 30          # trading days of history to build the baseline from
MIN_DAYS = 20        # below this, the baseline is too thin to trust
Z_THRESHOLD = 2.0    # standard deviations before we call a move unusual
VOLUME_HIGH = 1.5    # multiple of average volume considered heavy
VOLUME_THIN = 0.7    # multiple below which we caveat the signal


def _daily_returns(closes):
    """Percentage change from each close to the next."""
    return [
        (closes[i] - closes[i - 1]) / closes[i - 1] * 100
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]


def assess(ticker, today_change_pct, today_volume):
    """
    Judge today's move against this stock's own recent behaviour.

    Returns a verdict dict. When there isn't enough history, says so
    explicitly rather than guessing - an unfounded verdict is worse
    than an honest 'not enough data'.
    """
    history = cache.get_history(ticker, limit=WINDOW)

    if len(history) < MIN_DAYS:
        return {
            "assessed": False,
            "reason": "insufficient_history",
            "message": f"Not enough history yet ({len(history)} days). Need at least {MIN_DAYS}.",
        }

    closes = [h["close"] for h in history]
    volumes = [h["volume"] for h in history]

    returns = _daily_returns(closes)
    mean = statistics.mean(returns)
    stdev = statistics.stdev(returns)

    # A stock that hasn't moved at all has no scale to measure against.
    if stdev == 0:
        return {
            "assessed": False,
            "reason": "no_variation",
            "message": "This stock hasn't moved enough recently to establish a normal range.",
        }

    z = (today_change_pct - mean) / stdev

    avg_volume = statistics.mean(volumes)
    volume_ratio = today_volume / avg_volume if avg_volume else None

    unusual = abs(z) >= Z_THRESHOLD
    direction = "up" if today_change_pct > 0 else "down"

    verdict = {
        "assessed": True,
        "unusual": unusual,
        "z_score": round(z, 2),
        "typical_move_pct": round(stdev, 2),
        "today_move_pct": round(today_change_pct, 2),
        "volume_ratio": round(volume_ratio, 2) if volume_ratio else None,
        "days_of_history": len(history),
        "message": _describe(unusual, z, direction, today_change_pct, stdev, volume_ratio),
    }
    return verdict


def _describe(unusual, z, direction, move, stdev, volume_ratio):
    """
    Turn the numbers into a sentence. The user sees a claim, not a z-score -
    'moved 4x its normal range' is actionable, 'z = 3.1' is not.
    """
    if not unusual:
        return f"Moved {abs(move):.2f}%, within its normal range."

    multiple = abs(move) / stdev if stdev else 0
    base = f"Moved {direction} {abs(move):.2f}% - about {multiple:.1f}x its typical daily range."

    if volume_ratio is None:
        return base

    if volume_ratio >= VOLUME_HIGH:
        return base + f" On {volume_ratio:.1f}x normal volume, so this looks like a real event."

    if volume_ratio <= VOLUME_THIN:
        return base + f" But volume was only {volume_ratio:.1f}x normal - this could be a single large trade rather than broad activity."

    return base + f" Volume was around normal ({volume_ratio:.1f}x)."


def enrich(quote):
    """
    Attach an anomaly verdict to a price quote.

    A failed quote gets no verdict - there's nothing to assess, and a
    verdict on missing data would be fabricated.
    """
    if not quote.get("ok"):
        return quote

    quote["anomaly"] = assess(
        quote["ticker"],
        quote["change_pct"],
        quote["volume"],
    )
    return quote


def enrich(quote):
    """
    Attach an anomaly verdict to a price quote.

    A failed quote gets no verdict - there's nothing to assess, and a
    verdict on missing data would be fabricated.
    """
    if not quote.get("ok"):
        return quote

    quote["anomaly"] = assess(
        quote["ticker"],
        quote["change_pct"],
        quote["volume"],
    )
    return quote


def _ago(seconds):
    """Human-readable age. Users think in 'a moment ago', not epoch deltas."""
    if seconds is None:
        return None
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    hours = int(seconds // 3600)
    return f"{hours} hour{'s' if hours > 1 else ''} ago"


def present(stock, market_open):
    """
    Add display-ready fields.

    Formatting lives here rather than in the frontend so that every client -
    web, mobile, anything later - shows the same wording. The raw numbers
    stay in the payload for anyone who wants them.
    """
    stock["updated"] = _ago(stock.get("age_seconds"))
    stock["price_state"] = "live" if market_open else "last close"

    verdict = stock.get("anomaly") or {}
    stock["headline"] = verdict.get("message")

    return stock


def past_events(ticker, lookback=60):
    """
    Find days in stored history that were anomalous for this stock.

    Runs the same z-score test as the live path, but backwards over each
    day's move against the 30 days before it - so a flagged past day is
    judged by the standard that applied at the time, not by today's.

    Real events from real data. Nothing here is synthetic.
    """
    history = cache.get_history(ticker, limit=lookback)
    if len(history) < MIN_DAYS + 5:
        return []

    events = []

    # Walk forward, using a trailing window as the baseline for each day.
    for i in range(MIN_DAYS, len(history)):
        window = history[max(0, i - WINDOW):i]
        closes = [h["close"] for h in window]
        volumes = [h["volume"] for h in window]

        returns = _daily_returns(closes)
        if len(returns) < 5:
            continue

        stdev = statistics.stdev(returns)
        if stdev == 0:
            continue
        mean = statistics.mean(returns)

        prev = history[i - 1]["close"]
        today = history[i]
        if prev == 0:
            continue

        move = (today["close"] - prev) / prev * 100
        z = (move - mean) / stdev

        if abs(z) < Z_THRESHOLD:
            continue

        avg_volume = statistics.mean(volumes)
        volume_ratio = today["volume"] / avg_volume if avg_volume else None
        direction = "up" if move > 0 else "down"

        events.append({
            "date": today["date"],
            "move_pct": round(move, 2),
            "z_score": round(z, 2),
            "typical_move_pct": round(stdev, 2),
            "volume_ratio": round(volume_ratio, 2) if volume_ratio else None,
            "message": _describe(True, z, direction, move, stdev, volume_ratio),
        })

    # Most recent first.
    events.reverse()
    return events


def digest(ticker, since_date):
    """
    Anomalous days for this ticker since a given date.

    Each past day is judged against the 30 days before it, not against
    today's baseline - a day was unusual by the standard that applied at
    the time. Using today's numbers to judge August would be reading the
    past with information it didn't have.
    """
    history = cache.get_history(ticker, limit=90)
    if len(history) < MIN_DAYS + 2:
        return []

    events = []

    for i in range(MIN_DAYS, len(history)):
        today = history[i]
        if since_date and today["date"] <= since_date:
            continue

        window = history[max(0, i - WINDOW):i]
        closes = [h["close"] for h in window]
        volumes = [h["volume"] for h in window]

        returns = _daily_returns(closes)
        if len(returns) < 5:
            continue

        stdev = statistics.stdev(returns)
        if stdev == 0:
            continue
        mean = statistics.mean(returns)

        prev = history[i - 1]["close"]
        if prev == 0:
            continue

        move = (today["close"] - prev) / prev * 100
        z = (move - mean) / stdev
        if abs(z) < Z_THRESHOLD:
            continue

        avg_volume = statistics.mean(volumes)
        volume_ratio = today["volume"] / avg_volume if avg_volume else None

        events.append({
            "ticker": ticker,
            "date": today["date"],
            "move_pct": round(move, 2),
            "z_score": round(z, 2),
            "message": _describe(True, z, "up" if move > 0 else "down",
                                 move, stdev, volume_ratio),
        })

    events.reverse()
    return events
