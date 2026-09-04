from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# NSE regular trading session.
OPEN_TIME = time(9, 15)
CLOSE_TIME = time(15, 30)

# Cache lifetimes, in seconds.
TTL_OPEN = 150      # 2.5 min - prices move
TTL_CLOSED = 3600   # 1 hour - closing price can't change


def now_ist():
    return datetime.now(IST)


def is_market_open(when=None):
    """
    True if NSE is in its regular session.
    Does not account for market holidays - a holiday is treated as open,
    which costs a few redundant fetches but never wrong data.
    """
    when = when or now_ist()

    if when.weekday() >= 5:      # Saturday, Sunday
        return False

    return OPEN_TIME <= when.time() <= CLOSE_TIME


def current_ttl():
    """Cache lifetime appropriate to the current market state."""
    return TTL_OPEN if is_market_open() else TTL_CLOSED
