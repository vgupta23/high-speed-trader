"""openspec: tick-loop"""
import pytest

import high_speed_trader as hst
from conftest import ny


def test_before_open_out_of_session():
    assert not hst.in_session(ny(2026, 10, 7, 9, 29))


def test_weekday_midmorning_in_session():
    assert hst.in_session(ny(2026, 10, 7, 10, 0))


def test_after_close_out_of_session():
    assert not hst.in_session(ny(2026, 10, 7, 16, 1))


def test_weekend_out_of_session():
    assert not hst.in_session(ny(2026, 10, 10, 11, 0))


def test_close_out_window():
    assert hst.in_close_out_window(ny(2026, 10, 7, 15, 50))
    assert not hst.in_close_out_window(ny(2026, 10, 7, 14, 0))


def _snapshot(positions=()):
    return {"settled_cash": 1000.0, "positions": list(positions)}


def test_tick_outside_hours_does_nothing(monkeypatch):
    monkeypatch.setattr(hst, "now_tz", lambda: ny(2026, 10, 10, 11, 0))
    monkeypatch.setattr(hst, "get_account_snapshot",
                        lambda: pytest.fail("must not fetch broker state"))
    hst.tick()


def test_tick_snapshot_failure_skips_trading(monkeypatch):
    monkeypatch.setattr(hst, "now_tz", lambda: ny(2026, 10, 7, 10, 0))
    monkeypatch.setattr(hst, "get_account_snapshot", lambda: (None, "boom"))
    monkeypatch.setattr(hst, "manage_positions", lambda *a: pytest.fail("no exits"))
    monkeypatch.setattr(hst, "maybe_enter", lambda *a: pytest.fail("no entries"))
    hst.tick()


def test_exits_precede_entries(monkeypatch):
    calls = []
    monkeypatch.setattr(hst, "now_tz", lambda: ny(2026, 10, 7, 10, 0))
    monkeypatch.setattr(hst, "get_account_snapshot",
                        lambda: (_snapshot([{"symbol": "AAA"}]), None))
    monkeypatch.setattr(hst, "manage_positions", lambda *a: calls.append("exit"))
    monkeypatch.setattr(hst, "maybe_enter", lambda *a: calls.append("enter"))
    hst.tick()
    assert calls == ["exit", "enter"]


def test_close_out_window_skips_entries(monkeypatch):
    calls = []
    monkeypatch.setattr(hst, "now_tz", lambda: ny(2026, 10, 7, 15, 50))
    monkeypatch.setattr(hst, "get_account_snapshot",
                        lambda: (_snapshot([{"symbol": "AAA"}]), None))
    monkeypatch.setattr(hst, "manage_positions", lambda *a: calls.append("exit"))
    monkeypatch.setattr(hst, "maybe_enter", lambda *a: calls.append("enter"))
    hst.tick()
    assert calls == ["exit"]


def test_no_local_state_files(monkeypatch, tmp_path):
    """Restart safety: a tick needs only broker data; run it in an empty cwd."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hst, "now_tz", lambda: ny(2026, 10, 7, 10, 0))
    monkeypatch.setattr(hst, "get_account_snapshot", lambda: (_snapshot(), None))
    monkeypatch.setattr(hst, "maybe_enter", lambda *a: None)
    hst.tick()
    assert list(tmp_path.iterdir()) == []
