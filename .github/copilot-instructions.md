# Copilot instructions for high-speed-trader

## Project purpose

This repository is a stateless intraday equity trading bot for a Robinhood account. The primary implementation is `high_speed_trader.py`; it reads live broker state on every tick, applies deterministic risk rules, and lets an AI choose which symbol to buy. The rules are intentionally strict and are documented in `SKILLS.md` and `docs/design.md`.

## Build, test, and lint commands

There is no repository-defined test suite or lint configuration in this repo today.

Use the script directly for the practical validation path:

```bash
# install runtime dependency
python -m pip install -r requirements.txt

# one dry-run tick (reads live state, asks AI for a pick, places no orders)
python3 high_speed_trader.py --once --simulation

# simulated loop
python3 high_speed_trader.py --loop --simulation

# compare Claude vs OpenAI picks without placing orders (--providers narrows it)
python3 high_speed_trader.py --ai-picks

# CLI help / argument reference
python3 high_speed_trader.py --help
```

If a Python test file is ever added later, use a single-file invocation such as:

```bash
python3 -m pytest tests/test_some_feature.py -q
```

There is no repo-specific lint command to standardize on right now; prefer keeping code compatible with the Python standard library and existing script patterns.

## High-level architecture

- `high_speed_trader.py` is the entire application. Most behavior lives in one file rather than a multi-package app.
- The bot is intentionally stateless: every tick fetches fresh broker state instead of reusing cached positions, prices, or entry data.
- `CONFIG` at the top of `high_speed_trader.py` is the central configuration surface. CLI flags override `CONFIG` values when passed in.
- The main loop is conceptually:
  1. Check whether the current time is within regular exchange hours.
  2. Fetch a fresh account snapshot (cash, open positions, current prices).
  3. Apply risk controls: stop-loss checks and close-out logic before entering new trades.
  4. If market conditions allow, scan the seed universe and/or broader liquid equities, ask the chosen AI provider for a symbol, and verify the trade is valid before buying.
- All real broker actions (quotes, positions, account data, orders) go through the configured MCP client and Robinhood MCP integration regardless of `pick_provider`. `MCP_CLIENT` currently supports only `claude`; `MCP_CLIENT_BIN`, `MCP_SERVER`, and `MCP_CLIENT_TIMEOUT_SEC` configure its executable, server name, and timeout.
- `pick_provider` only affects the decision about which symbol to buy:
  - `claude` uses Claude Code CLI and may do WebSearch
  - `openai` uses the OpenAI chat completions API
- `README.md` and `SKILLS.md` are the source of truth for the trading rules. `docs/design.md` explains the implementation pattern.

## Key conventions

- Treat the repo as equity-only. Do not introduce options, futures, crypto, or other derivatives logic.
- Never add persisted state. No DB, no cache, no local memory of positions or fills across ticks. Re-read live broker state every cycle.
- Respect the hard safety gates:
  - `CONFIG["enable_live_trade"]` defaults to `False`
  - `--simulation` disables order placement for a run
  - sells fire at more than +8% or at -8% or worse versus entry on open positions
  - positions are flattened near the close to avoid holding through the close when the loop is no longer watching
- Secrets are loaded from a local `.env` file and should never be committed. The project expects values such as `ROBINHOOD_ACCOUNT_NUMBER`, `OPENAI_API_KEY`, `CLAUDE_MODEL`, `OPENAI_MODEL`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID`.
- The seed universe is guidance, not a strict boundary. The AI may propose a valid symbol outside the watchlist, but it must still pass strength/tradability checks before an order is placed.
- Keep risk math deterministic and separate from AI reasoning. The AI chooses what to buy; the Python logic chooses sizing, stop-loss, and whether the trade is allowed.
- The bot is designed for rapid polling, not a slow batch pipeline. Any change should respect the tick-based, short-interval execution model.

## When making changes

- Prefer edits in `high_speed_trader.py` that preserve the stateless, tick-driven model.
- Before changing trading logic, check `SKILLS.md` for the non-negotiable rules and `docs/design.md` for the implementation structure.
- Keep new configuration in `CONFIG` rather than scattering environment-specific values across the file.
- If a change affects the broker rail, verify it still routes through the configured client + Robinhood MCP rather than bypassing that path. Do not advertise another MCP client as supported without implementing its invocation and tool-permission adapter.
- If a change affects live-buy safety, explicitly reason about `--simulation` and `enable_live_trade` behavior.

## Relevant repo docs

- `README.md` — setup, environment variables, run commands, and operational warnings
- `SKILLS.md` — the trading rules and assumptions the bot follows
- `docs/design.md` — architecture overview and tick flow
- `.env.example` — required/optional environment variables
