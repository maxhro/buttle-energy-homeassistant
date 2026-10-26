"""Tests for smoothing.py (no Home Assistant needed)."""

from __future__ import annotations

import importlib
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

_DIR = Path(__file__).parents[1] / "custom_components" / "powermesh_energy"
_PACKAGE = types.ModuleType("powermesh_smoothing_pkg")
_PACKAGE.__path__ = [str(_DIR)]
sys.modules["powermesh_smoothing_pkg"] = _PACKAGE
smoothing = importlib.import_module("powermesh_smoothing_pkg.smoothing")

START = datetime(2026, 1, 2, 3, 4, 0, tzinfo=UTC)


def reading(value: float, when: datetime, state_class: str = "measurement") -> dict:
    return {
        "entity_id": "sensor.power",
        "timestamp": when.isoformat(),
        "state": value,
        "unit_of_measurement": "W",
        "attributes": {"device_class": "power", "state_class": state_class},
    }


def feed(smoother, value: float, seconds: float, state_class: str = "measurement") -> list[dict]:
    when = START + timedelta(seconds=seconds)
    return smoother.add(reading(value, when, state_class), when)


def test_default_and_options() -> None:
    assert smoothing.DEFAULT == "mean_1min"
    assert smoothing.OPTIONS["mean_1min"] == ("time_simple_moving_average", 60)
    assert smoothing.OPTIONS["throttle_5min"] == ("time_throttle", 300)
    assert smoothing.OPTIONS["none"] == ("none", None)
    assert smoothing.option_for(None, "sensor.x") == "mean_1min"
    assert smoothing.option_for({"sensor.x": "bogus"}, "sensor.x") == "mean_1min"
    assert smoothing.option_for({"sensor.x": "none"}, "sensor.x") == "none"
    assert smoothing.Smoother("bogus").option == "mean_1min"


def test_none_passes_every_change() -> None:
    smoother = smoothing.Smoother("none")
    out = feed(smoother, 5, 1) + feed(smoother, 6, 2)
    assert [r["state"] for r in out] == [5, 6]
    assert all(r["smoothing"] == "none" and "smoothing_window" not in r for r in out)


def test_throttle_keeps_first_value_per_window() -> None:
    smoother = smoothing.Smoother("throttle_1min")
    out = []
    for value, seconds in [(1, 0), (2, 10), (3, 59), (4, 60), (5, 70), (6, 185)]:
        out += feed(smoother, value, seconds)
    assert [r["state"] for r in out] == [1, 4, 6]
    assert all(r["smoothing"] == "time_throttle" and r["smoothing_window"] == 60 for r in out)


def test_mean_is_time_weighted_one_reading_per_window() -> None:
    smoother = smoothing.Smoother("mean_1min")
    assert feed(smoother, 100, 0) == []
    assert feed(smoother, 400, 45) == []
    # 100 W for 45 s and 400 W for 15 s.
    out = smoother.flush(START + timedelta(seconds=60))
    assert len(out) == 1
    assert out[0]["state"] == 175
    assert out[0]["timestamp"] == "2026-01-02T03:04:00Z"
    assert out[0]["smoothing"] == "time_simple_moving_average" and out[0]["smoothing_window"] == 60
    assert out[0]["unit_of_measurement"] == "W" and out[0]["entity_id"] == "sensor.power"
    assert smoother.flush(START + timedelta(seconds=200)) == []


def test_mean_carries_previous_state_into_next_window() -> None:
    smoother = smoothing.Smoother("mean_1min")
    feed(smoother, 100, 0)
    # The window closes when the next change arrives; 100 W stays current until 150 s.
    closed = feed(smoother, 300, 150)
    assert [r["state"] for r in closed] == [100]
    out = smoother.flush(START + timedelta(seconds=180))
    # Window 120–180 s: 100 W for 30 s, 300 W for 30 s.
    assert [r["state"] for r in out] == [200]
    assert out[0]["timestamp"] == "2026-01-02T03:06:00Z"


def test_mean_ignores_out_of_order_and_rounds() -> None:
    smoother = smoothing.Smoother("mean_10s")
    feed(smoother, 1, 0)
    feed(smoother, 2, 3)
    assert feed(smoother, 50, 1) == []
    out = smoother.flush(START + timedelta(seconds=10))
    assert out[0]["state"] == round((1 * 3 + 2 * 7) / 10, 4)


def test_mean_closes_window_on_meter_reset() -> None:
    smoother = smoothing.Smoother("mean_1min")
    feed(smoother, 1000, 0, "total_increasing")
    out = feed(smoother, 2, 30, "total_increasing")
    assert [r["state"] for r in out] == [1000]
    tail = smoother.flush(START + timedelta(seconds=60))
    assert [r["state"] for r in tail] == [2]
    assert tail[0]["timestamp"] == "2026-01-02T03:04:30Z"


def test_drain_emits_partial_window() -> None:
    smoother = smoothing.Smoother("mean_5min")
    feed(smoother, 10, 0)
    feed(smoother, 20, 30)
    out = smoother.drain(START + timedelta(seconds=60))
    assert [r["state"] for r in out] == [15]
    assert smoother.drain(START + timedelta(seconds=90)) == []
    assert smoothing.Smoother("throttle_1min").drain(START) == []
