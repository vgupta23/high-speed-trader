# Design

## Context

`high_speed_trader.py` already implements the loop; this change documents it as specs and closes drift with `SKILLS.md`. See proposal.md for motivation. Constraints: single-file script, broker access through an MCP client (Robinhood), AI used only for the pick step, no test suite yet.

## Goals / Non-Goals

**Goals:**
- Make every spec scenario verifiable by an offline unit test (no broker or AI calls).
- Make `SKILLS.md` match the specs.

**Non-Goals:**
- Changing trading behavior or thresholds.
- Backtesting, persistence, or non-equity instruments.

## Decisions

- **Code is the source of truth where it differs from SKILLS.md.** Chosen by the user: 10% exits, extra gates, and the master switch are specified as-is, and `SKILLS.md` is edited to match. Alternative: revert code to 8% — rejected, the 10% change was deliberate (latest commit).
- **Test pure functions, stub the broker.** `evaluate_position`, `in_session`, `in_close_out_window`, `daychg_gate`, `classify_trend`, and the gate functions take plain values, so pytest with no mocks covers most scenarios. `maybe_enter` / `place_*` are tested with monkeypatched broker functions. Alternative: integration tests against `--simulation` — rejected, needs live credentials.
- **Gates stay deterministic, outside the AI.** Consistent with the existing hard-stop philosophy.
- **Volume trend and EMA band remain report-only.** They are specified as non-affecting live entries, matching the code's `--trend-analysis` opt-in.

## Risks / Trade-offs

- [Specs describe unvalidated strategy, not profitability] → Specs verify behavior only.
- [Spec/code drift recurs] → Tests encode scenarios; run them in the existing git hook/CI.
- [Activity log is a file, "no state" is strict] → Spec allows a write-only human log never read back.
