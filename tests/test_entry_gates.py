"""openspec: entry-gates"""
import datetime as dt

import pytest

import high_speed_trader as hst


def test_sma_above_200():
    assert hst.sma_gate({"last": 100, "sma50": 90, "sma200": 80}) is None


def test_sma_pullback_above_50():
    assert hst.sma_gate({"last": 85, "sma50": 80, "sma200": 90}) is None


def test_sma_below_both_fails():
    assert hst.sma_gate({"last": 70, "sma50": 80, "sma200": 90})


def test_sma_200_unavailable_fails():
    assert hst.sma_gate({"last": 70, "sma50": 80, "sma200": None})


@pytest.mark.parametrize("rsi,ok", [(30, False), (30.1, True), (70, True),
                                    (70.1, False), (None, False)])
def test_rsi_gate(rsi, ok):
    assert (hst.rsi_gate({"rsi": rsi}) is None) is ok


def test_fib_inside_zone():
    fib = hst.fib_retracement(61.8, 100, "2026-09-01", 0, "2026-06-01")  # upswing
    assert fib["swing"] == "up" and fib["in_zone"]
    assert hst.fib_gate({"last": 38.2, "fib": fib}) is None


def test_fib_outside_zone_fails():
    fib = hst.fib_retracement(95, 100, "2026-09-01", 0, "2026-06-01")
    assert hst.fib_gate({"last": 95, "fib": fib})


def test_fib_truncated_history_fails():
    bars = [[(dt.date(2026, 9, 1) - dt.timedelta(days=i)).isoformat(), 10, 9]
            for i in range(hst.CONFIG["fib_min_bars"] - 1)]
    assert hst.swing_from_bars(bars) is None
    assert hst.fib_gate({"last": 10, "fib": None})


def test_forward_pe_reasonable():
    c = {"fpe": hst.forward_pe(70.0, [0.5, 0.5, 0.5, 0.5])}  # eps 2 -> pe 35
    assert hst.forward_pe_gate(c) is None


def test_forward_pe_annualizes_fewer_estimates():
    assert hst.forward_pe(10.0, [1.0, 1.0])["forward_eps"] == 4.0


def test_forward_pe_nonpositive_eps_fails():
    assert hst.forward_pe_gate({"fpe": hst.forward_pe(10.0, [0.0, -1.0])})


def test_forward_pe_over_cap_fails():
    assert hst.forward_pe_gate({"fpe": hst.forward_pe(400.0, [1, 1, 1, 1])})


def test_ema_band():
    assert hst.ema_band_gate({"last": 10, "ema8": 11, "ema21": 9}) is None
    assert hst.ema_band_gate({"last": 12, "ema8": 11, "ema21": 9})


# ---- conviction and sizing (maybe_enter) ----
@pytest.fixture
def enter(monkeypatch):
    buys = []
    monkeypatch.setattr(hst, "scan_candidates", lambda: ([{"symbol": "AAA"}], None))
    monkeypatch.setattr(hst, "is_tradable_equity", lambda s: True)
    monkeypatch.setattr(hst, "place_buy",
                        lambda s, d: (buys.append((s, d)) or {"quantity": 1, "avg_price": 1}, None))

    def run(pick, cash=1000.0, held=()):
        monkeypatch.setattr(hst, "pick_name", lambda c: (pick, None))
        hst.maybe_enter({"settled_cash": cash, "positions": [{"symbol": s} for s in held]})
        return buys
    return run


def buy(conv="high", sym="AAA"):
    return {"decision": "buy", "symbol": sym, "conviction": conv, "reason": "x"}


def test_buy_sized_25pct(enter):
    assert enter(buy("medium")) == [("AAA", 250.0)]


def test_low_conviction_no_order(enter):
    assert enter(buy("low")) == []


def test_already_held_no_order(enter):
    assert enter(buy(), held=["AAA"]) == []


def test_too_little_cash_no_order(enter):
    assert enter(buy(), cash=50.0) == []
