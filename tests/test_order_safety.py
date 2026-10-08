"""openspec: order-safety"""
import re
from pathlib import Path

import pytest

import high_speed_trader as hst


@pytest.fixture
def no_ai(monkeypatch):
    monkeypatch.setattr(hst, "claude_json",
                        lambda *a, **k: pytest.fail("order sent to broker"))


def test_default_disabled_blocks_buy_and_sell(monkeypatch, no_ai):
    monkeypatch.setitem(hst.CONFIG, "enable_live_trade", False)
    assert hst.place_buy("AAA", 100.0)[0] is None
    assert hst.place_sell_all("AAA", 1.0)[0] is None


def test_enabled_places_order(monkeypatch):
    monkeypatch.setitem(hst.CONFIG, "enable_live_trade", True)
    monkeypatch.setattr(hst, "claude_json",
                        lambda *a, **k: {"filled": True, "avg_price": 1, "quantity": 1})
    assert hst.place_buy("AAA", 100.0)[1] is None


def test_live_trade_defaults_off_without_env():
    src = Path(hst.__file__).read_text()
    assert 'os.environ.get("ENABLE_LIVE_TRADE", "")' in src  # unset -> "" -> False


def test_simulation_forces_off(monkeypatch, no_ai):
    monkeypatch.setitem(hst.CONFIG, "enable_live_trade", True)
    monkeypatch.setitem(hst.CONFIG, "account_number", "123")
    monkeypatch.setattr("sys.argv", ["x", "--once", "--simulation"])
    monkeypatch.setattr(hst, "tick", lambda simulation=False: None)
    hst.main()
    assert hst.CONFIG["enable_live_trade"] is False


def test_untradable_symbol_not_bought(monkeypatch):
    monkeypatch.setattr(hst, "claude_json", lambda *a, **k: {"tradable": False})
    assert hst.is_tradable_equity("ZZZ") is False
    monkeypatch.setattr(hst, "scan_candidates", lambda: ([{"symbol": "ZZZ"}], None))
    monkeypatch.setattr(hst, "pick_name", lambda c: (
        {"decision": "buy", "symbol": "ZZZ", "conviction": "high"}, None))
    monkeypatch.setattr(hst, "place_buy", lambda *a: pytest.fail("bought untradable"))
    hst.maybe_enter({"settled_cash": 1000.0, "positions": []})


def test_only_equity_order_tools_used():
    src = Path(hst.__file__).read_text()
    assert not re.search(r"place_(option|crypto)_order|exercise_option", src)
