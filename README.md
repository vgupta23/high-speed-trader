# High-Speed Trader

[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](LICENSE)

A stateless, high-speed, **equity-only** intraday trading bot for a Robinhood
account. Every tick reads live broker state, applies a hard $0.50/share
stop-loss, and lets an AI (Claude or OpenAI) pick what to buy next — nothing
is cached or saved between ticks. See [`SKILLS.md`](SKILLS.md) for the rules
and [`docs/design.md`](docs/design.md) for how it's built.

> **Read this whole file before running with real money.** This is
> experimental, unaudited software. It can place real market orders with no
> confirmation prompt once you turn buys on. Equities can move fast between
> ticks. Not financial advice. Use money you can afford to lose, and start
> tiny.

## Setup, step by step

<details>
<summary><strong>Step 1 — Get Python</strong> (click to expand)</summary>

**Windows**: install from [python.org](https://www.python.org/). On the
first installer screen, tick "Add python.exe to PATH." Then open a **new**
terminal:
```bash
python --version
```
**macOS**: `brew install python` or [python.org](https://www.python.org/).

**Linux**: almost certainly already installed. `python3 --version`.

You want **3.9 or newer** (this repo has been run on 3.11 — needed for
`zoneinfo`).
</details>

<details>
<summary><strong>Step 2 — Install the Claude Code CLI and log in</strong></summary>

Follow [Anthropic's current install guide](https://docs.claude.com/claude-code)
for Claude Code, then:
```bash
claude --version     # prints a version = installed
claude               # run once, log in, then /exit
claude -p "say hi"   # headless works = you're good
```
If `claude -p` says "Invalid API key," you have a stale `ANTHROPIC_API_KEY`
environment variable overriding your login. Delete it, open a new terminal,
log in with plain `claude`.

Every broker call this bot makes (quotes, positions, cash, orders) goes
through this CLI via a headless `claude -p` call, **regardless of which AI
makes the entry pick** — this step is not optional even if you plan to use
`pick_provider = "openai"`. See [AI model requirements](#ai-model-requirements)
below for what kind of Claude access (subscription vs. API billing) that
needs.
</details>

<details>
<summary><strong>Step 3 — Add the Robinhood MCP and authorize it</strong> (one time)</summary>

```bash
claude mcp add -s user --transport sse robinhood https://agent.robinhood.com/mcp/trading
```
If it later shows "Failed to connect," it's usually the transport. Remove
and re-add with the other one:
```bash
claude mcp remove -s user robinhood
claude mcp add -s user --transport http robinhood https://agent.robinhood.com/mcp/trading
```
Then open interactive `claude`, run `/mcp`, select `robinhood`, and finish
the login in your browser. Confirm:
```bash
claude mcp list      # robinhood should show connected
```
If you name the server anything other than `robinhood`, update
`CONFIG["mcp_server"]` in `high_speed_trader.py` to match.
</details>

<details>
<summary><strong>Step 4 — Prove it can reach your account</strong> (read-only, no orders)</summary>

```bash
claude -p "Call get_accounts and return only JSON listing each account_number and its agentic_allowed flag." --allowedTools "mcp__robinhood__get_accounts" --dangerously-skip-permissions
```
Write down the account number that shows `agentic_allowed: true`. That's
the account the bot trades. If this returns your account, the whole
pipeline works.

This bot is **equity-only** (see [`SKILLS.md`](SKILLS.md)) — it never
places an options order, so unlike an options-trading bot, you do **not**
need options trading approval on the Robinhood account for this repo.
</details>

<details>
<summary><strong>Step 5 — Clone this repo and install</strong></summary>

Green Code button → Download ZIP → unzip. Or:
```bash
git clone https://github.com/vgupta23/high-speed-trader.git
cd high-speed-trader
python -m pip install -r requirements.txt
```
(The only dependency is `tzdata`, and only Windows actually needs it.)
</details>

<details>
<summary><strong>Step 6 — Configure secrets (.env)</strong></summary>

All account/API secrets are read from environment variables, which the
script loads from a local `.env` file at startup (falling back to whatever
the shell already has exported). `.env` is gitignored — it never gets
committed.
```bash
cp .env.example .env
# then edit .env and fill in:
#   ROBINHOOD_ACCOUNT_NUMBER=...       (the account_number from Step 4)
#   OPENAI_API_KEY=...                 (only if pick_provider = "openai")
#   TELEGRAM_BOT_TOKEN=...             (optional)
#   TELEGRAM_CHAT_ID=...               (optional)
```
**Never commit a real account number or key** — the script refuses to run
while `ROBINHOOD_ACCOUNT_NUMBER` is left at its placeholder.
</details>

## AI model requirements

Two separate things need AI access here, and they aren't the same:

- **The broker rail always runs through Claude Code**, no matter what
  `pick_provider` you choose (steps above). That means you need either a
  **Claude subscription that Claude Code can use (Pro, Max, or Team)**, or
  an **Anthropic Console API key with billing enabled** — some Claude usage
  is unavoidable just to read quotes/positions and place orders.
- **The entry pick** (which equity to buy) additionally depends on
  `CONFIG["pick_provider"]`:
  - `"claude"` (default) — uses that same Claude Code access, plus
    `WebSearch` for fresh catalysts. No separate API key needed.
  - `"openai"` — needs an `OPENAI_API_KEY` with available credits, set in
    `.env`. Claude Code access is *still* required for the broker rail even
    in this mode.

## Configure the bot

Setup (above) gets secrets into `.env`. Everything else about *how* the bot
trades lives in the `CONFIG` dict near the top of `high_speed_trader.py`:

| Key | What it controls |
|---|---|
| `account_number` | Robinhood account the bot trades (or set `ROBINHOOD_ACCOUNT_NUMBER` env var) |
| `mcp_server` | MCP server name, as shown by `claude mcp list` |
| `pick_provider` | `"claude"` or `"openai"` — who picks the entry |
| `up_universe` | Seed watchlist for momentum longs (guideline, not a hard boundary) |
| `down_universe` | Seed watchlist for dip-buy bounces (guideline, not a hard boundary) |
| `candidate_min_daychg` | Minimum day-change % (up) for an `up_universe` name to become a candidate |
| `candidate_max_daychg` | Maximum day-change % (up) for an `up_universe` name to still be considered -- above this it's excluded as a one-day outlier, default `10.0` |
| `candidate_min_down_daychg` | Minimum abs(day-change %) down for a `down_universe` name to become a candidate, e.g. `5.0` == down more than 5% |
| `deploy_fraction` | Fraction of settled cash to commit per new entry |
| `min_trade_usd` | Skip an entry sized below this |
| `conviction_accept` | Which AI conviction levels clear the gate |
| `stop_loss_usd` | Hard stop: sell if price is down this many $/share |
| `close_out_minutes_before_close` | Flatten everything this close to the bell |
| `enable_live_buys` | **Stays `False` until you deliberately flip it** |
| `tick_interval_sec` | Seconds between ticks (loop mode) |
| `session_open` / `session_close` / `tz` | Trading window |

## Run

Always dry-run first:

```bash
# One simulated tick: evaluates positions and gets a real AI pick, places NO orders
python3 high_speed_trader.py --once --simulation

# Simulated loop, ticking every 15s (or CONFIG["tick_interval_sec"])
python3 high_speed_trader.py --loop --simulation

# Only scan up_universe (momentum longs) or down_universe (dip-buy candidates)
python3 high_speed_trader.py --once --simulation --up
python3 high_speed_trader.py --once --simulation --down

# Ask both claude and openai for a pick on the same scan and log whether
# they agree. Read-only: ignores cash, places no orders.
python3 high_speed_trader.py --compare-providers --up
```

Once you've reviewed simulated output and flipped
`CONFIG["enable_live_buys"] = True`:

```bash
# Single live tick (good for cron/launchd scheduling)
python3 high_speed_trader.py --once

# Foreground live loop, Ctrl+C to stop
python3 high_speed_trader.py --loop
```

### CLI flags

| Flag | Overrides | Default |
|---|---|---|
| `--once` | run exactly one tick | — |
| `--loop` | run forever, sleeping between ticks | — |
| `--interval N` | `CONFIG["tick_interval_sec"]` | `15` |
| `--simulation` | disables all order placement for this run | off |
| `--session-open HH:MM` | `CONFIG["session_open"]` | `09:30` |
| `--session-close HH:MM` | `CONFIG["session_close"]` | `16:00` |
| `--ignore-weekday` | testing only: treat weekends as in-session | off |
| `--up` | only scan `up_universe` (momentum longs); skip `down_universe` | off |
| `--down` | only scan `down_universe` (dip-buy candidates); skip `up_universe` | off |
| `--compare-providers` | one scan, picks from both `claude` and `openai`; no orders, no cash check (needs `OPENAI_API_KEY`) | off |

`--up` and `--down` are mutually exclusive; omit both to scan both
universes (the default). This only affects the entry scan — the stop-loss
and close-out guard on existing positions always run regardless.

Every override flag follows the same rule: if you pass it on the command
line, it wins; otherwise the value in `CONFIG` is used.

`--session-open`/`--session-close`/`--ignore-weekday` are for testing
outside market hours — leave them off for real trading so the bot only
ever runs during the regular session.

## What it actually does, in one pass

1. Skip the tick if it's outside regular exchange hours (or the weekend).
2. Pull a fresh account snapshot (cash + open positions + current prices) —
   nothing is reused from a prior tick.
3. Sell any position that's down $0.50/share from its average cost, or
   flatten everything if the close is near. Winners are never force-sold.
4. Otherwise, quote both seed universes, filter to day-change movers
   (`up_universe` names up at least `candidate_min_daychg`, `down_universe`
   names down more than `candidate_min_down_daychg`), ask the configured AI
   to pick one momentum long or dip-buy bounce (or pass), verify conviction
   and tradability, and buy with `deploy_fraction` of settled cash if
   `enable_live_buys` is on.

## Logs

Human-readable activity lines are appended to `~/.high_speed_trader.log`
(and printed to stdout). This is an activity trail only — the bot never
reads it back to decide anything, which keeps it consistent with "no state
is stored."

## Robinhood MCP tool reference

The Robinhood MCP server (`https://agent.robinhood.com/mcp/trading`, added in
Step 3) exposes ~90 tools as `mcp__<server_name>__<tool>` — everything from
quotes to order placement to SEC filings. This bot only ever calls seven of
them (marked **used by this bot** below); the rest are documented here for
anyone extending it or poking around with `claude -p` directly, e.g.:

```bash
claude -p "Call get_equity_quotes for AAPL and print the JSON." \
  --allowedTools "mcp__robinhood__get_equity_quotes" --dangerously-skip-permissions
```

Every write tool below (order placement/cancellation, watchlist/alert/scan
mutations, exercises) places or changes something real — the MCP server's own
tool descriptions say to confirm with the user before calling them in an
interactive session; this bot's unattended use of `place_equity_order` is
gated entirely by `CONFIG["enable_live_buys"]` (see Safety checklist below).

<details>
<summary><strong>Accounts &amp; portfolio</strong></summary>

| Tool | What it does |
|---|---|
| `get_accounts` | Lists brokerage accounts, including which one is `agentic_allowed` (tradable by an agent). **Used by this bot** — Step 4 verification. |
| `get_portfolio` | Portfolio market value by asset type, plus buying power. **Used by this bot** — cash snapshot every tick (`get_account_snapshot`). |
</details>

<details>
<summary><strong>Equities — read</strong></summary>

| Tool | What it does |
|---|---|
| `get_equity_positions` | Open equity positions: symbol, quantity, average cost, hold breakdown. **Used by this bot.** |
| `get_equity_quotes` | Real-time quotes + last close for one or more symbols. **Used by this bot.** |
| `get_equity_orders` | Order history/status by account, with filters (`state`, `symbol`, `created_at_gte`, `order_id`). |
| `get_equity_tradability` | Per-session tradability + fractional eligibility for up to 10 symbols. **Used by this bot** — gate before every buy. |
| `get_equity_fundamentals` | Valuation ratios, market cap, today's OHLCV, 52-week range, dividend schedule. |
| `get_equity_historicals` | OHLCV bars over a time range (charting/backtesting). |
| `get_equity_price_book` | Level 2 bid/ask depth snapshot (max 4 symbols). |
| `get_equity_tax_lots` | Open tax lots for one symbol — cost basis, acquisition date, long/short-term. |
| `get_equity_technical_indicators` | RSI, MACD, Bollinger Bands, moving averages, ATR, VWAP, etc. over a symbol's bars. |
| `get_equity_analyst_ratings` | Analyst price targets and Buy/Hold/Sell breakdown. |
| `get_equity_news` | Recent news articles for a ticker. |
</details>

<details>
<summary><strong>Equities — orders</strong></summary>

| Tool | What it does |
|---|---|
| `review_equity_order` | Simulates an order (no execution): returns quote + pre-trade alerts (buying power, PDT, halts). **Used by this bot** — always called before `place_equity_order` for buys. |
| `place_equity_order` | Places a real order. `side` (buy/sell), `type` (market/limit/stop_market/stop_limit), and exactly one of `quantity` or `dollar_amount` (`dollar_amount` requires `type=market`). Supports `tax_lots` for specified-lot sells, `market_hours` (regular/extended/all_day), and a `ref_id` UUID for idempotent retries. **Used by this bot** — buys sized by dollar amount, stop-loss/close-out sells by share quantity, matching how `place_buy`/`place_sell_all` call it (confirmed against this schema — see `docs/design.md`). |
| `cancel_equity_order` | Cancels an open order by `order_id`. |
</details>

<details>
<summary><strong>Options</strong></summary>

| Tool | What it does |
|---|---|
| `get_option_chains` | Expirations/contract set for an underlying. |
| `get_option_instruments` | Lists option contracts, filterable by expiration/strike/type/state. |
| `get_option_quotes` | Real-time quotes for option contracts by instrument UUID. |
| `get_option_historicals` | OHLC bars for option contracts. |
| `get_option_orders` | Options order history/status. |
| `get_option_positions` | Open (or all) options positions. |
| `review_option_order` / `place_option_order` | Simulate/place single- or multi-leg (spreads, condors, calendars, rolls) options orders. Requires `option_level_2`+ on the account. |
| `cancel_option_order` | Cancels an open options order. |
| `exercise_option` / `cancel_option_exercise` | Exercise a long option (irrevocable) or cancel a still-queued exercise request. |
| `get_option_watchlist` / `add_option_to_watchlist` / `remove_option_from_watchlist` | Manage the dedicated single-leg options watchlist. |
| `get_option_level_upgrade_info` | Returns the URL to apply for/raise options trading level. |

This bot is equity-only and never calls any option tool — see
[`SKILLS.md`](SKILLS.md).
</details>

<details>
<summary><strong>Crypto</strong></summary>

| Tool | What it does |
|---|---|
| `get_crypto_account_onboarding_info` | Link to open a crypto account. |
| `get_crypto_orders` / `get_crypto_positions` | Crypto order history / open positions. |
| `get_crypto_quotes` | Real-time bid/ask/mark + previous close for crypto pairs. |
| `get_currency_pairs` | Catalog of supported crypto pairs and per-pair order constraints. |
| `preview_crypto_order` / `place_crypto_order` | Simulate/place a crypto order (`market`/`limit`/`stop_loss`/`stop_limit`, `quantity` or `dollar_amount`, optional `tax_lots`). |
| `cancel_crypto_order` | Cancels an open crypto order. |
</details>

<details>
<summary><strong>Advanced (OCO) orders</strong></summary>

| Tool | What it does |
|---|---|
| `get_advanced_orders` | Multi-leg contingency orders (OCO, OTO) with legs hydrated. |
| `review_advanced_order` / `place_advanced_order` | Simulate/place a one-cancels-the-other equity order: a take-profit limit leg + a stop-loss leg, same symbol/side/quantity. |
| `cancel_advanced_order` | Cancels an advanced order and all its legs. |
</details>

<details>
<summary><strong>Watchlists &amp; search</strong></summary>

| Tool | What it does |
|---|---|
| `get_watchlists` / `get_watchlist_items` | List the user's watchlists / an individual list's items. |
| `create_watchlist` / `update_watchlist` | Create a custom watchlist / rename or restyle one. |
| `add_to_watchlist` / `remove_from_watchlist` | Add or remove stocks, crypto pairs, or indexes (mutually exclusive per call). |
| `follow_watchlist` / `unfollow_watchlist` | Follow/unfollow a Robinhood-curated list. |
| `get_popular_watchlists` | Discover curated lists (e.g. "100 Most Popular", "Daily Movers"). |
| `search` | Resolve a name/partial ticker to an instrument, crypto pair, or market index. |
</details>

<details>
<summary><strong>Alerts</strong></summary>

| Tool | What it does |
|---|---|
| `get_alerts` | List configured price/indicator alerts. |
| `create_alert` / `update_alert` / `delete_alert` | Create, modify, or (with a confirm step) delete an alert. Conditions span price and indicator (SMA/EMA/VWAP/RSI/MACD/Bollinger) triggers. |
| `get_alert_log` / `mark_alerts_read` | Read fired-alert history and mark events as read. |
</details>

<details>
<summary><strong>Scanners</strong></summary>

| Tool | What it does |
|---|---|
| `get_scans` | List saved scanners (screeners). |
| `create_scan` | Create a scanner, optionally from a preset (`DAILY_GAINERS`, `DAILY_LOSERS`, `HIGH_OPTIONS_VOLUME_IV`, `UPCOMING_EARNINGS`) plus custom filters. |
| `run_scan` | Execute a saved scan against live market data. |
| `update_scan_config` / `update_scan_filters` | Change a scan's sort/columns, or replace its filters. |
| `get_scanner_filter_specs` | Valid filter types/predicates for building scan filters. |
</details>

<details>
<summary><strong>Research &amp; fundamentals</strong></summary>

| Tool | What it does |
|---|---|
| `get_earnings_calendar` | Market-wide earnings schedule over a date window. |
| `get_earnings_results` | Trailing/upcoming earnings (EPS estimate vs. actual) for one symbol. |
| `get_financials` | Revenue, gross profit, net income, margin by fiscal period. |
| `get_sec_filing_index` / `get_sec_filing` / `get_sec_filing_facts` / `get_sec_filing_facts_catalog` | Find, read, and extract structured facts from SEC filings (10-K/10-Q/8-K). |
| `get_politician_trades` | Disclosed congressional trading activity (STOCK Act data, ranges not exact amounts). |
</details>

<details>
<summary><strong>P&amp;L, indexes &amp; account upgrades</strong></summary>

| Tool | What it does |
|---|---|
| `get_pnl_trade_history` | Chronological realized-P&L trade log (equities/options/crypto). |
| `get_realized_pnl` | Bucketed realized gain/loss totals over a time window. |
| `get_indexes` / `get_index_quotes` / `get_index_historicals` | Market index lookups, real-time values, and history (SPX, NDX, DJI, etc.). |
| `get_limited_margin_upgrade_info` | Eligibility + link to upgrade a cash account to limited margin (trade unsettled funds, no leverage). |
</details>

## Safety checklist before going live

- [ ] Ran `--once --simulation` and read the log output end to end.
- [ ] Ran `--loop --simulation` for at least one full session and confirmed
      the picks and stop-loss checks look reasonable.
- [x] `place_equity_order`'s dollar-buy / quantity-sell assumptions in
      `place_buy` / `place_sell_all` match its real MCP signature — confirmed
      against the tool schema (see
      [Robinhood MCP tool reference](#robinhood-mcp-tool-reference) above).
- [ ] Started with a small `deploy_fraction` and a small account balance.
- [ ] Only then set `CONFIG["enable_live_buys"] = True`.
