# Baseline

**A watchlist that tells you what actually changed.**

Live: https://baseline-watchlist.onrender.com · Built for Code, by Groww, September 2026

---

## What it is

You open your watchlist after three days away. Ten stocks. Which one actually
did something?

Baseline answers that in one line, then splits your list into three:

- **Needs attention** — moved unusually *for that stock*
- **Quiet** — nothing worth your time
- **Unavailable** — we couldn't price it, and you should know

Plus a panel at the top telling you what happened while you were gone.

---

## Why it's different

On 6 August, Reliance moved 3.52%.

A watchlist with a 5% alert threshold says nothing. Baseline says:

> **RELIANCE.NS · 2026-08-06**
> Moved up 3.52% — about 3.0× its typical daily range. On 1.7× normal volume,
> so this looks like a real event.

Same data. The difference is that Baseline knows what 3.52% means *for
Reliance* — a stock whose typical day is about 1.2%. A fixed threshold can't,
because it treats every stock as the same stock.

A watchlist that flags everything is as useless as one that flags nothing.

---

## See it in action

Open the live link, or:

**Empty state** — eight one-tap NSE tickers, because a blank box assumes you
know the `.NS` format.

**Main view** — summary line, three tabs with counts, quiet stocks collapsed to
one line so flagged ones stand out.

**Since you last looked** — a panel listing the days that mattered while you
were away, each with a date and a reason.

**Detail panel** — click any stock for the full verdict, its typical range vs
today's move, volume against its 30-day average, data freshness, and past
unusual days from its own history.

**How this works** — a page inside the product explaining the reasoning. A user
who doesn't understand why the app stays quiet will assume it's broken.

You can use all of it without signing up. Your list follows you if you do.

---

## The problem, stated properly

Most watchlists show prices and leave you to work out whether a number means
anything.

Flat percentage alerts are the industry norm, and they have a structural
problem no amount of tuning fixes: set the threshold low and everything is
flagged, which means nothing is; set it high and you miss real events on
calmer stocks. Products that go this route often end up shipping controls to
mute alerts, which treats the symptom rather than the cause.

Baseline judges every stock against **its own** recent behaviour, and stays
quiet otherwise.

---

## How it decides

A z-score on daily returns over a 30-day window, flagged at z ≥ 2.

**Why z-score over percentile:** it yields a magnitude, not just a rank. "Three
standard deviations out" is something you can act on; percentile can't
distinguish "top 5% by a hair" from "far beyond anything recent". With ~22
trading days in the window, percentile buckets are also coarse.

**Why volume is measured differently** — a plain ratio to the 30-day average,
not a z-score. Price drives the verdict so it gets the statistical rigour;
volume corroborates and only needs to be legible. "3× normal volume" is
readable; "volume z of 2.4" is not. Precision matched to the job.

The two combine: price decides *whether* to flag, volume decides *how
confidently* it's described.

> Moved up 5.50% — about 4.6× its typical daily range. On 3.6× normal volume,
> so this looks like a real event.

> Moved up 5.50% — about 4.6× its typical daily range. But volume was only 0.3×
> normal — this could be a single large trade rather than broad activity.

Identical price move, different verdict. The system won't overclaim from price
alone.

---

## Since you last looked

The brief asks what changed since the user last *checked*, not since
yesterday's close. Those differ, and the difference is the feature.

Backdating a last visit to 1 July across three stocks produced 8 anomalous
days. Two TCS entries are worth comparing:

| Date | Move | Volume | Verdict |
|---|---|---|---|
| 28 Aug | 4.16% | 1.3× | "Volume was around normal." |
| 12 Aug | 3.93% | 1.6× | "This looks like a real event." |

The *smaller* move is described more confidently, because volume corroborated
it. That's the design working, not a quirk.

How it decides what to show:

- `last_viewed_at` updates only after a **30-minute gap**, not per page load.
  Otherwise refreshing at 9:05 after looking at 9:00 wipes your digest and
  replaces it with "nothing in the last five minutes" — true, and useless. You
  would lose the thing you came back for by reading it.
- **Only anomalous days**, not every day. Three months away yields however many
  events actually occurred, not 60 rows.
- **Not a single delta.** −5% Wednesday and +5% Thursday nets to zero, when
  something clearly happened twice.
- Each past day is judged against **the 30 days before it**. A day was unusual
  by the standard that applied at the time; using today's baseline would be
  reading the past with information it didn't have.
- For a stock you've never seen, `added_at` is the baseline.
- When nothing crossed the line it says so. A blank panel reads as broken;
  "nothing significant happened while you were away" is a real answer.

---

## Engineering decisions

### Treating the data source as unreliable

Yahoo Finance via `yfinance` is unofficial and will intermittently fail. The
system is built assuming that, not surprised by it.

- **Market-aware caching.** 150s TTL during NSE hours, 1 hour when closed — a
  closing price cannot change over a weekend. A flat TTL would refetch roughly
  1,500 times across a weekend for an unchanging number.
- **TTL evaluated on read, not write.** A quote cached at 3:29pm is judged by
  the market-open rule when read at 3:31pm. Baking expiry in at write time would
  freeze a stale decision into the row.
- **Failures are never cached.** A cached outage would keep showing
  "unavailable" for the full TTL after recovery. Failures are cheap to retry;
  stale errors are expensive.
- **Three failure modes, not one error.** Unknown ticker (user-fixable), service
  unavailable, network error. Unexpected exceptions default to *service*
  problems rather than blaming the user's input — when we don't know whose fault
  it is, we don't send them chasing a typo that isn't there.
- **Per-stock isolation.** One failing ticker marks that row unavailable; the
  rest render normally.
- Users get plain English; full exception detail goes to the log.

### Scaling

| Measure | Result |
|---|---|
| 6 tickers, cold | 1.94s parallel vs ~6× a single fetch sequentially |
| 6 tickers, warm | 0.00s |
| 8 concurrent requests, one cold ticker | 1 network call, not 8 |
| 10 calls through a 5/sec limiter | 1.00s — burst correctly refused |

- **Parallel fetching**, capped at 8 workers rather than one per ticker.
  Unbounded concurrency against a single unofficial endpoint invites rate
  limiting. Order preserved so the watchlist doesn't reshuffle between loads.
- **Request coalescing.** Simultaneous requests for the same cold ticker share
  one fetch. The lock is held only while registering, never across the network
  call — holding it during the fetch would serialise every ticker and undo the
  parallelism.
- **Outbound rate limiting**, sliding window rather than token bucket. The
  failure mode that matters is a burst; a sliding window refuses those precisely,
  where a bucket lets a full burst through on a fresh refill.
- **Background refresher** warms the 20 most-watched tickers during market
  hours, at TTL−20s so entries are replaced just *before* expiry.

**Where this stops working:** the cache scales with ticker popularity, not user
count. Ten users on ten different stocks means ten fetches. Watchlists cluster
on large caps in practice, so hit rates should hold — but that's a bet, and ten
users × twenty distinct stocks is still a 200-call burst from one IP.
Cross-process coalescing and a shared cache are the next step.

### What the user sees

Three groups rather than one ranked list, because ranking a stock we couldn't
price against one that moved 3% forces a comparison that means nothing — and
burying a broken stock at the bottom of a long list means you may never notice
your data is missing.

- Flagged stocks show the full verdict; quiet ones collapse to one line. If
  everything looked equally important, the ordering would carry no information.
- Plain English, never the z-score. The statistic is how the system decides; the
  multiple is what a person can act on.
- Freshness always visible: "updated 23 min ago", "last close" vs "live".
- Formatting happens server-side, so any future client shows identical wording
  without duplicating the logic.

---

## Security

- Passwords hashed with bcrypt, never stored. bcrypt directly rather than via
  passlib — passlib 1.7.4 predates bcrypt 4.1 and its startup self-check hashes
  an over-length password, which bcrypt 5.0 rejects.
- **Identical response** for an unknown username and a wrong password, and a
  fixed dummy hash is verified when the user doesn't exist, so response *timing*
  doesn't leak which accounts are real either.
- Session cookies signed, `httponly` (JavaScript can't read them, so an
  injection can't steal one) and `samesite=lax`.
- Uniqueness enforced by DB constraints, not check-then-insert — the same
  race-window reasoning as duplicate watchlist entries.
- **Password reset**: tokens random, stored as SHA-256 hashes, 30-minute expiry,
  single use. Marking used and changing the password happen in one transaction,
  so a crash between them can't leave a token spendable twice. `/reset/start`
  returns the same response whether or not the email exists.
- **Guests.** A visitor uses the app before signing up; their list lives on a
  device-scoped identity and merges into their account if they register. A guest
  is a user row with an unusable password hash, so watchlist queries need no
  special case, and the merge uses INSERT OR IGNORE so a ticker added on both
  sides can't abort the operation.
- Email collected only for recovery. No phone, no name, no behavioural tracking,
  no analytics, no third-party pixels. A commercial product would want usage
  data; leaving it out is a decision, not an oversight.

---

## What I chose not to build

- **RSI, moving averages, indicator panels.** Charting platforms already do this
  well, and rebuilding them worse isn't differentiation. It also contradicts the
  decision to show verdicts rather than raw numbers.
- **Similar-stock recommendations.** They optimise for adding more stocks, not a
  more useful watchlist. A watchlist isn't better with more entries — it's
  better with the right ones.
- **Portfolio tracking.** The brief asks for a watchlist. Holdings, cost basis
  and P&L are a different product.
- **News as a dependency.** Yahoo's news is reachable but inconsistent, and
  timing correlation isn't causation. The anomaly signal stands alone.
- **Bulk and block deal data.** Genuinely the strongest missing signal — a large
  investor taking a position often *is* why a stock moved. NSE publishes it but
  blocks automated access, so it needs scraping with no stability guarantee.
  Identified, costed, dropped.
- **Email delivery for reset.** Token generation, hashing, expiry and single-use
  are real; only transport is stubbed. Half-built delivery is worse than none.

---

## Trade-offs, and what I'd do instead

| Decision | Why | With more time |
|---|---|---|
| z-scores, though returns have fat tails | Standard, explainable, adequate at this threshold | Empirical percentile or a robust estimator |
| SQLite over Postgres | No server to run; setup speed mattered more than scale | Postgres — the free tier's disk is ephemeral, so data is lost on restart |
| Market holidays unhandled | Costs a few redundant fetches, never wrong data | An NSE holiday calendar |
| Plain HTML over a framework | Nothing here needs a build step | Unchanged, honestly |
| Free-tier hosting | Zero cost, real URL | A paid instance — free sleeps after 15 min, so a cold load takes up to 50s and the background refresher stops with it |

---

## Running it

    pip install -r requirements.txt
    uvicorn main:app --reload

Then http://127.0.0.1:8000

Set `SESSION_SECRET` in the environment for anything beyond local use. The
in-code fallback exists so the app runs without setup, and means sessions reset
on restart.

---

## Layout

| File | Does |
|---|---|
| `main.py` | API endpoints, request handling, identity resolution |
| `anomaly.py` | Z-score detection, verdict wording, digest |
| `prices.py` | yfinance access, failure classification, caching wrapper |
| `cache.py` | Quote cache and daily history store |
| `market.py` | NSE hours, market-aware TTL |
| `fetchguard.py` | Request coalescing, outbound rate limiting |
| `refresher.py` | Background warming of popular tickers |
| `auth.py` | Accounts, sessions, password reset, guest identities |
| `database.py` | Watchlist storage |
| `static/` | Frontend and the reasoning page |
| `notes.txt` | Decision log kept while building |
