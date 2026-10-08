# High-Speed Trader Skill

A stateless, tick-driven intraday equity trading loop. Every tick reads live
broker state and acts on it — nothing is remembered between ticks or between
runs.

## Loop Logic

- Run on a fixed polling interval (a "tick"). Any interval works; pick one and
  loop on it for as long as the market session is open.
- On each tick:
  1. Fetch fresh broker state (positions, quotes, buying power) — never reuse
     a value computed on a previous tick.
  2. Check every open position against the stop-loss rule below; exit
     immediately if it's tripped.
  3. Scan the universe for new entries that meet the selection logic.
  4. Place any resulting orders.
  5. Sleep until the next tick.
- **Unlimited trades**: there is no cap on how many trades happen in a
  session. Enter and exit as many times as the rules trigger.
- **Stop-loss**: if an open position's equity price has dropped 10% or more from
  its entry price, sell the full position immediately. This is a hard,
  non-negotiable exit — don't wait for confirmation.
- **Take-profit**: if an open position is up more than 10% from its entry
  price, sell the full position.
- **Master switch**: no buy or sell order is placed unless live trading is
  explicitly enabled (`ENABLE_LIVE_TRADE`, off by default). `--simulation`
  always forces it off.

## Stock Selection Logic

- Maintain a single seed watchlist (`universe`) as a starting guideline, not
  a boundary. Every name in it is checked for both setups on each scan,
  tagged `bull_or_bear`:
  - `bull` — momentum longs: names already trading up on the day.
  - `bear` — dip-buy candidates: names trading down hard (more than a
    configured drop threshold) that look like a bounce, not a name still
    falling for a real reason.
- The universe is a floor, not a ceiling: any liquid, actively-traded U.S.
  equity may be traded if it satisfies the entry logic, even if it isn't on
  the seed list.
- A momentum-long candidate has a floor and a ceiling on its day change: it
  must be up at least a configured minimum, but a move past a configured
  maximum is treated as a one-day outlier (e.g. a halt or news-driven spike)
  rather than real continuation, and is excluded from the pick step
  entirely.
- A single day's price move isn't enough: each candidate is also scored on
  its trailing 5-day volume trend (mean volume over the last 5 trading days vs.
  the 5 trading days before that) and On-Balance-Volume trend over the same
  window, pulled from historicals rather than one day's number. A big
  day-change on flat or falling 5-day volume reads as a one-day spike; a
  rising 5-day volume trend with rising OBV reads as sustained interest. The
  volume trend informs the pick and the `--trend-analysis` report only; it is
  never a hard entry gate.
- Each candidate also carries a longer-term bull/bear trend read, classified
  deterministically (not by the AI) from daily moving averages: bullish is
  the 10-day EMA above the 21-day EMA with price holding both the 50-day and
  200-day SMA; bearish is price having broken below all three levels;
  anything else is neutral. A momentum long against a bearish trend, or a
  dip-buy in one, should be weighted down hard -- it's more likely a
  short-lived bounce or a falling knife than a real setup.

## Entry Gates

Deterministic checks (not the AI) a candidate must clear before a buy:

- Price above the 200-day SMA, or between the 50-day and 200-day SMA.
- 14-period RSI above 30 and at most 70.
- Price inside the 0.382-0.764 Fibonacci retracement zone of the last swing
  (a truncated history rejects).
- Forward P/E positive and below 90 (zero/negative forward EPS rejects).
- Pick decision is buy with high or medium conviction, the symbol isn't
  already held, and the order (25% of settled cash) meets the minimum size.
- The broker confirms the symbol is a tradable equity.

`--trend-analysis` additionally reports the 10-day volume/OBV gate and the
8/21-day EMA band; neither affects live entries.

## Instrument Scope

- Stocks/equities only. No options, futures, crypto, or other derivatives,
  even where the broker rail supports them.

## Trading Style

- This is high-speed trading: decisions and orders happen on short polling
  intervals within the session, not as a single daily pick.
- Speed favors quick, decisive execution — especially on the stop-loss —
  over waiting for extra confirmation.

## Trading Hours

- Trade only during regular stock exchange hours (9:30 AM–4:00 PM ET,
  NYSE/Nasdaq calendar). No pre-market, no after-hours.
- Because the loop enforces the stop-loss only while it's running, flatten
  any open positions before the closing bell rather than holding them
  through a close the loop won't be watching.

## State

- No state is stored. No local files, database, or in-memory cache of
  positions, entry prices, or timestamps. (A write-only human activity log
  is allowed; it is never read back to make decisions.)
- Every tick treats the broker's live state as the sole source of truth —
  fetch positions, quotes, and account data fresh each time. The process can
  be stopped and restarted at any point with nothing to reload or reconcile.
