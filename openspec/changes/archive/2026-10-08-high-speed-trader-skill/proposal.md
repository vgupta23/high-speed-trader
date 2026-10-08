# Proposal

## Why

The trading rules live only in prose (`SKILLS.md`) and have drifted from the code: `SKILLS.md` says 8% stop-loss/take-profit, the code uses 10%, and the RSI / Fibonacci / forward-P/E gates and the `ENABLE_LIVE_TRADE` master switch are undocumented there. Capturing the rules as testable OpenSpec requirements gives one verifiable contract for the stateless intraday loop.

## What Changes

- Record the trader's behavior as OpenSpec capabilities, derived from `SKILLS.md` and reconciled with the current code (code is treated as the intended behavior where they differ).
- Specify exits at **+10% / -10%** from entry (replacing the 8% in `SKILLS.md`), plus the pre-close flatten.
- Specify the deterministic entry gates and the `ENABLE_LIVE_TRADE` master switch as requirements.
- Update `SKILLS.md` (and `docs/design.md` / `README.md` where they cite 8%) to match the specs.
- Add automated tests that verify each requirement's scenarios.
- No runtime behavior change beyond what the code already does.

## Capabilities

### New Capabilities
- `tick-loop`: Stateless fixed-interval tick, regular-hours-only session, no stored state, unlimited trades.
- `position-exits`: Take-profit, stop-loss, and pre-close flatten for open positions.
- `candidate-selection`: Universe as a floor, day-change window, bull/bear tagging, trend classification, volume trend.
- `entry-gates`: Deterministic SMA, RSI, Fibonacci, and forward-P/E gates plus conviction and sizing rules before a buy.
- `order-safety`: Equities-only scope, broker tradability check, and the live-trade master switch / simulation mode.

### Modified Capabilities

(none — `openspec/specs/` is empty)

## Impact

- Code: `high_speed_trader.py` (no functional change expected; tests added against `evaluate_position`, `in_session`, `daychg_gate`, `classify_trend`, entry gates).
- Docs: `SKILLS.md`, `docs/design.md`, `README.md`.
- New: `openspec/` tree, `tests/` for spec verification.
- No new runtime dependencies (test runner only).
