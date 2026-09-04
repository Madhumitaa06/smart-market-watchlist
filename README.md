# Baseline

**A watchlist that tells you what actually changed.**

Live: https://baseline-watchlist.onrender.com
Built for Code, by Groww — September 2026.

---

## The problem I actually solved

Most watchlists show prices. The user has to work out whether a number means
anything. A 2% move looks the same whether it happened to a stock that
normally drifts 0.3% a day or one that swings 5% on a routine Tuesday.

Fixed thresholds inherit that flaw. Groww's own price alerts fire at a flat
5% move, which means a calm stock moving 4% — genuinely abnormal for it —
gets silence, while a volatile stock moving 5% triggers an alert on a day
nothing happened. Groww later shipped Notification Management so users could
mute alerts, which reads to me as the fixed-threshold problem surfacing as
alert fatigue.

Baseline judges every stock against **its own** recent behaviour, and stays
quiet otherwise.

---

## What counts as a meaningful change

A z-score on daily returns over a 30-day window, flagged at z ≥ 2.

- **Why z-score over percentile:** it yields a magnitude, not just a rank.
  "Three standard deviations out" is something a user can act on; percentile
  can't distinguish "top 5% by a hair" from "far beyond anything recent".
  With ~22 trading days in the window, percentile buckets are also coarse.
- **Known weakness:** stock returns have fat tails, so z=2 flags somewhat
  more than the theoretical 5% of days. I accepted this and would move to a
  robust estimator or empirical percentile with more time.
- **Volume is deliberately treated differently** — a simple ratio to the
  30-day average, not a z-score. Price drives the verdict so it gets the
  statistical rigour; volume is corroborating evidence and only needs to be
  legible. "3× normal volume" is readable, "volume z of 2.4" is not.

The two combine: price decides *whether* to flag, volume shapes *how
confidently* it's described.

> Moved up 5.50% — about 4.6× its typical daily range. On 3.6× normal
> volume, so this looks like a real event.

> Moved up 5.50% — about 4.6× its typical daily range. But volume was only
> 0.3× normal — this could be a single large trade rather than broad activity.

Identical price move, different verdict. The system declines to overclaim
from price alone.

---

## Since you last looked

The brief asks what changed since the user last *checked*, not since
yesterday's close. Those differ, and the difference matters.

- `last_viewed_at` is stored per user and updated only after a **30-minute
  gap**, not on every page load. Updating per request means refreshing at
  9:05 after looking at 9:00 wipes your digest and replaces it with "nothing
  in the last five minutes" — technically true, useless. You would lose the
  thing you came back for by reading it.
- The digest lists **only the anomalous days** in the gap, not every day. A
  three-month absence yields however many events actually occurred.
- A single since-you-left delta would hide the story: −5% Wednesday and +5%
  Thursday nets to zero, when something clearly happened twice.
- Each past day is judged against **the 30 days before it**, not today's
  baseline. A day was unusual by the standard that applied at the time.
- For a stock the user has never seen, `added_at` is the baseline.
- When nothing crossed the line, it says so explicitly. A blank panel reads
  as broken; "nothing significant happened while you were away" is a real
  answer.

Verified on live data: backdating a last visit to 1 July produced 8
anomalous days across 3 stocks — including RELIANCE on 6 Aug at 3.52%,
3.0× its typical range, which a fixed 5% threshold would never have seen.

---

## What the user sees

Three groups rather than one ranked list: **needs attention**, **quiet**,
**unavailable**. Ranking a stock we couldn't price against one that moved 3%
forces a comparison that doesn't mean anything, and burying a broken stock at
the bottom of a long list means the user may never notice their data is
missing.

- Flagged stocks show the full verdict; quiet ones collapse to one line. If
  everything looked equally important, the ordering would carry no
  information.
- Users see plain English, never the z-score. The statistic is how the system
  decides; the multiple is what a person can act on. Raw numbers in the UI
  would push the interpretation back onto the user.
- Freshness is always visible: "updated 23 min ago", "last close" vs "live".
  A price seen at 9pm is a closing price, and the user should know that
  rather than assume.
- Formatting happens server-side, so any future client shows identical
  wording without duplicating the logic.

There is also a **How this works** page inside the product. The argument for
per-stock baselines is the whole point — a user who doesn't understand why
the app stays quiet will assume it's broken.

---

## Stale, delayed and unreliable data

Yahoo Finance via `yfinance` is unofficial and will intermittently fail. The
system treats that as expected, not exceptional.

- **Market-aware caching.** 150s TTL during NSE hours, 1 hour when closed —
  a closing price cannot change over a weekend. A flat TTL would refetch
  roughly 1,500 times across a weekend for the same number.
- **TTL is evaluated on read, not write.** A quote cached at 3:29pm is judged
  by the market-open rule when read at 3:31pm; baking expiry in at write time
  would freeze a stale decision into the row.
- **Failures are never cached.** A cached outage would keep showing
  "unavailable" for the full TTL after the service recovered. Failures are
  cheap to retry; stale errors are expensive.
- **Three distinct failure modes**, not one generic error: unknown ticker
  (user-fixable), service unavailable, network error. Unknown exceptions
  default to *service* problems rather than blaming the user's input — when
  we don't know whose fault it is, we don't send them chasing a typo that
  isn't there.
- **Per-stock isolation.** One failing ticker marks that row unavailable; the
  other nine render normally.
- Users get a plain-English message; full exception detail goes to the log.
  Nothing is swallowed silently.

**Known gap:** market holidays aren't handled, so Diwali is treated as an
open day and uses the short TTL. Costs a few redundant fetches, never wrong
data.

---

## Scaling

| Measure | Result |
|---|---|
| 6 tickers, cold | 1.94s (parallel) vs ~6× a single fetch sequentially |
| 6 tickers, warm | 0.00s |
| 8 concurrent requests, one cold ticker | 1 network call, not 8 |
| 10 calls through a 5/sec limiter | 1.00s — burst correctly refused |

- **Parallel fetching**, capped at 8 workers rather than one per ticker.
  Unbounded concurrency against a single unofficial endpoint invites rate
  limiting. Order is preserved so the watchlist doesn't reshuffle.
- **Request coalescing.** Several simultaneous requests for the same cold
  ticker share one fetch. The lock is held only while registering, never
  across the network call — holding it during the fetch would serialise every
  ticker and undo the parallelism.
- **Outbound rate limiting**, sliding window rather than token bucket. The
  failure mode we care about is a burst; a sliding window refuses those
  precisely, where a bucket lets a full burst through on a fresh refill.
- **Background refresher** keeps the 20 most-watched tickers warm during
  market hours, at TTL−20s so entries are replaced just *before* expiry.

**Honest limit:** the cache scales with ticker *popularity*, not user count.
Ten users on ten different stocks means ten fetches. In practice watchlists
cluster on large caps, so hit rates should be decent — but that's a bet, not
a guarantee. Ten users × twenty distinct stocks is still a 200-call burst
from one IP.

---

## Accounts

- Passwords hashed with bcrypt, never stored. bcrypt is used directly rather
  than via passlib — passlib 1.7.4 predates bcrypt 4.1 and its startup
  self-check hashes an over-length password, which bcrypt 5.0 rejects.
- **Identical response** for an unknown username and a wrong password, and a
  fixed dummy hash is verified when the user doesn't exist, so response
  *timing* doesn't leak which accounts are real either.
- Session cookies are signed, `httponly` (JavaScript can't read them, so an
  injection can't steal one) and `samesite=lax`.
- Uniqueness enforced by DB constraints, not check-then-insert — the same
  race-window reasoning as duplicate watchlist entries.
- **Password reset**: tokens are random, stored as SHA-256 hashes, expire in
  30 minutes, and are single-use. Marking used and changing the password
  happen in one transaction so a crash between them can't leave a token
  spendable twice. `/reset/start` returns the same response whether or not
  the email exists.
- Email is collected **only** for recovery. No phone, no name — data I don't
  use is a liability, not a feature.

---

## What I deliberately did not build

- **RSI, moving averages, indicator panels.** Groww already ships TradingView
  charts with full indicators. Rebuilding them worse isn't differentiation,
  and it contradicts the decision to show verdicts rather than raw numbers.
- **Portfolio tracking.** The brief asks for a watchlist. Holdings, cost
  basis and P&L are a different product.
- **News as a dependency.** Yahoo's news is reachable but inconsistent, and
  timing correlation isn't causation. The anomaly signal stands alone; news
  would have been enrichment, not foundation.
- **Bulk and block deal data.** A genuinely good signal — a large investor
  taking a position often *is* the cause of an anomalous move. NSE publishes
  it but blocks automated access, so it would need scraping with no stability
  guarantee. Identified, costed, dropped.
- **Email delivery for reset.** Token generation, hashing, expiry and
  single-use are real; only transport is stubbed. Half-built delivery would
  be worse than none.

---

## Known limitations

- **Free-tier hosting**: the instance sleeps after ~15 minutes idle, so a
  cold first request takes up to 50s. The UI says so rather than leaving a
  silent wait. The background refresher is effectively a no-op on this tier,
  since it stops whenever the app sleeps.
- **Ephemeral disk**: SQLite data is lost on restart. Postgres is the fix and
  Render offers it free; I prioritised getting the core logic right.
- Market holidays unhandled (see above).
- Fat-tailed returns vs the normality assumption in z-scores (see above).

---

## Running it

    pip install -r requirements.txt
    uvicorn main:app --reload

Then http://127.0.0.1:8000

Set `SESSION_SECRET` in the environment for anything beyond local use — the
in-code fallback exists so the app runs without setup, and means sessions
reset on restart.

---

## Layout

| File | Does |
|---|---|
| `main.py` | API endpoints, request handling |
| `anomaly.py` | Z-score detection, verdict wording, digest |
| `prices.py` | yfinance access, failure classification, caching wrapper |
| `cache.py` | Quote cache and daily history store |
| `market.py` | NSE hours, market-aware TTL |
| `fetchguard.py` | Request coalescing, outbound rate limiting |
| `refresher.py` | Background warming of popular tickers |
| `auth.py` | Accounts, sessions, password reset |
| `database.py` | Watchlist storage |
| `static/` | Frontend and the reasoning page |
| `notes.txt` | Running decision log kept while building |

---

## With another week

1. Postgres, so data survives a restart.
2. Bulk/block deal data through a paid provider — the strongest missing
   signal for *why* a move happened.
3. Request coalescing across processes, not just threads.
4. A robust volatility estimator that handles fat tails properly.
5. Real email delivery for password reset.
