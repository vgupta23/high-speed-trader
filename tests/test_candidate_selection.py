"""openspec: candidate-selection"""
import pytest

import high_speed_trader as hst


@pytest.mark.parametrize("dc,ok", [(6, True), (10, True), (-10, True),
                                   (25, False), (-10.5, False)])
def test_daychg_window(dc, ok):
    assert (hst.daychg_gate(dc) is None) is ok


def test_scan_tags_and_excludes(monkeypatch):
    hst.CONFIG["universe"] = ["UP", "DN", "BIG"]
    monkeypatch.setattr(hst, "get_quotes", lambda syms: ({
        "UP": {"day_change_pct": 3, "last": 10},
        "DN": {"day_change_pct": -4, "last": 10},
        "BIG": {"day_change_pct": 25, "last": 10}}, None))
    monkeypatch.setattr(hst, "enrich_with_signals", lambda c, include_volume=False: None)
    monkeypatch.setattr(hst, "entry_gate", lambda c: None)
    cands, err = hst.scan_candidates()
    tags = {c["symbol"]: c["bull_or_bear"] for c in cands}
    assert err is None and tags == {"UP": "bull", "DN": "bear"}


def test_trend_bullish():
    assert hst.classify_trend(100, 10, 9, 90, 80) == "bullish"


def test_trend_bearish():
    assert hst.classify_trend(70, 9, 10, 90, 80) == "bearish"


def test_trend_neutral():
    assert hst.classify_trend(70, 10, 9, 60, 80) == "neutral"


def test_trend_missing_input():
    assert hst.classify_trend(None, 10, 9, 90, 80) is None


def test_pick_prompt_has_trend_and_bearish_guidance():
    c = {"symbol": "AAA", "day_change_pct": 3.0, "last": 100.0, "bull_or_bear": "bull",
         "trend": "bearish", "ema10": 9.0, "ema21": 10.0, "sma50": 90.0, "sma200": 95.0}
    p = hst.build_pick_prompt([c])
    assert "longer-term trend bearish" in p
    assert "falling knife" in p and "weight it down hard" in p


def test_volume_gate_rising_passes():
    assert hst.volume_trend_gate({"volume_momentum_pct": 20, "obv_trend": "rising"}) is None


def test_volume_gate_spike_on_falling_obv_fails():
    assert hst.volume_trend_gate({"volume_momentum_pct": 20, "obv_trend": "falling"})


def test_volume_gate_not_in_live_entry_gates():
    assert "volume_trend" not in dict(hst.ENTRY_GATES)
    assert "ema_band" not in dict(hst.ENTRY_GATES)
