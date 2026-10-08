import copy
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import high_speed_trader as hst  # noqa: E402

NY = ZoneInfo("America/New_York")


def ny(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=NY)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    """Fresh CONFIG copy per test; logging/notify silenced so nothing is
    written or sent."""
    monkeypatch.setattr(hst, "CONFIG", copy.deepcopy(hst.CONFIG))
    monkeypatch.setattr(hst, "log", lambda *a, **k: None)
    monkeypatch.setattr(hst, "notify", lambda *a, **k: None)
