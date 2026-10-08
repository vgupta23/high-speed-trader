"""openspec: position-exits"""
import high_speed_trader as hst


def pos(entry, cur):
    return {"average_buy_price": entry, "current_price": cur}


def test_stop_loss_at_threshold():
    action, reason = hst.evaluate_position(pos(100.0, 90.0), False)
    assert action == "sell" and "stop-loss" in reason


def test_just_above_stop_loss_holds():
    assert hst.evaluate_position(pos(100.0, 90.01), False)[0] == "hold"


def test_above_take_profit_sells():
    action, reason = hst.evaluate_position(pos(100.0, 110.01), False)
    assert action == "sell" and "take-profit" in reason


def test_exactly_take_profit_holds():
    assert hst.evaluate_position(pos(100.0, 110.0), False)[0] == "hold"


def test_close_out_sells_flat_position():
    action, reason = hst.evaluate_position(pos(100.0, 100.0), True)
    assert action == "sell" and "close-out" in reason


def test_custom_threshold():
    hst.CONFIG["stop_loss_pct"] = 5.0
    assert hst.evaluate_position(pos(100.0, 95.0), False)[0] == "sell"
