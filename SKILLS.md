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
- **Stop-loss**: if an open position's equity price has dropped 50 cents from
  its entry price, sell the full position immediately. This is a hard,
  non-negotiable exit — don't wait for confirmation.
- **Take-profit**: uncapped. Let winners run; there is no forced exit while a
  position is profitable. Profit-taking, if any, is a per-tick judgment call,
  not a rule.

## Stock Selection Logic

- Maintain a universe list as a starting guideline — a seed watchlist, not a
  boundary.
- The universe is a floor, not a ceiling: any liquid, actively-traded U.S.
  equity may be traded if it satisfies the entry logic, even if it isn't on
  the seed list.

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
  positions, entry prices, or timestamps.
- Every tick treats the broker's live state as the sole source of truth —
  fetch positions, quotes, and account data fresh each time. The process can
  be stopped and restarted at any point with nothing to reload or reconcile.
