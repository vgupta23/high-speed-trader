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
| `universe` | Seed watchlist (guideline, not a hard boundary) |
| `candidate_min_daychg` | Minimum abs(day-change %) to become a candidate |
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
4. Otherwise, quote the seed universe, filter to day-change movers, ask the
   configured AI to pick one (or pass), verify conviction and tradability,
   and buy with `deploy_fraction` of settled cash if `enable_live_buys` is on.

## Logs

Human-readable activity lines are appended to `~/.high_speed_trader.log`
(and printed to stdout). This is an activity trail only — the bot never
reads it back to decide anything, which keeps it consistent with "no state
is stored."

## Safety checklist before going live

- [ ] Ran `--once --simulation` and read the log output end to end.
- [ ] Ran `--loop --simulation` for at least one full session and confirmed
      the picks and stop-loss checks look reasonable.
- [ ] Confirmed `place_equity_order`'s real signature in your Robinhood MCP
      matches the dollar-buy / quantity-sell assumptions in `place_buy` /
      `place_sell_all` (see `docs/design.md`'s Known Limitations).
- [ ] Started with a small `deploy_fraction` and a small account balance.
- [ ] Only then set `CONFIG["enable_live_buys"] = True`.
