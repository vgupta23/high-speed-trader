# Tasks

## 1. Test scaffolding

- [x] 1.1 Add `tests/` with pytest and a `requirements-dev.txt` entry; verify `pytest -q` collects and imports `high_speed_trader` without network access

## 2. position-exits and tick-loop

- [x] 2.1 Write tests for `evaluate_position` covering every position-exits scenario (90.00 sells, 90.01 holds, 110.01 sells, 110.00 holds, close-out sells, custom threshold); verify they pass
- [x] 2.2 Write tests for `in_session` / `in_close_out_window` covering tick-loop hours scenarios (pre-open, 10:00 weekday, after close, weekend); verify they pass
- [x] 2.3 Write tests for `tick` with monkeypatched broker calls: snapshot failure skips trading, exits precede entries, no state file is read; verify they pass

## 3. candidate-selection and entry-gates

- [x] 3.1 Write tests for `daychg_gate` and bull/bear tagging in `scan_candidates` (6% in, 25% out, +3%/-4% tags); verify they pass
- [x] 3.2 Write tests for `classify_trend` (bullish, bearish, mixed, missing input); verify they pass
- [x] 3.3 Write tests for `sma_gate`, `rsi_gate`, `fib_gate`, `forward_pe_gate`, `volume_trend_gate`, `ema_band_gate` per spec scenarios; verify they pass
- [x] 3.4 Write tests for `maybe_enter` (low conviction, already held, below min trade, 25% sizing) with a stubbed broker; verify they pass
- [x] 3.5 Verify the pick prompt includes trend reads and the bearish down-weight instruction (assert on `build_pick_prompt` output)

## 4. order-safety

- [x] 4.1 Write tests that no `place_buy`/`place_sell_all` order is sent when `enable_live_trade` is false or `--simulation` is set, and that an untradable symbol is not bought; verify they pass
- [x] 4.2 Confirm no code path orders non-equity instruments (grep for options/crypto order tools in `high_speed_trader.py`); verify none are called

## 5. Docs reconciliation

- [x] 5.1 Update `SKILLS.md` to 10% stop-loss/take-profit, the entry gates, the opt-in volume trend, and the master switch; verify each statement maps to a spec requirement
- [x] 5.2 Replace remaining "8%" references in `docs/design.md` and `README.md`; verify with `grep -n "8%" SKILLS.md README.md docs/design.md`
- [x] 5.3 Run `openspec validate high-speed-trader-skill --strict` and the full `pytest` suite; verify both are clean

## Workflow follow-up

- Archive with `openspec archive high-speed-trader-skill` once tests pass.
