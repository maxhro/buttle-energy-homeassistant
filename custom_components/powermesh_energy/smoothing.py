"""Per-entity smoothing modelled on the Home Assistant filter helper (no HA imports).

Unlike the filter helper, which publishes a new state on every change, each
time-based filter here emits at most one reading per window to reduce uploads:

- ``time_simple_moving_average``: time-weighted mean of the state over a fixed
  window aligned to UTC (each value counts for as long as it was current). The
  reading carries the window start as timestamp.
- ``time_throttle``: the first state of each window passes, the rest are dropped.
- ``none``: every state change is sent unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .readings import timestamp_key

NONE = "none"
MEAN = "time_simple_moving_average"
THROTTLE = "time_throttle"

WINDOWS: dict[str, int] = {
    "10s": 10,
    "30s": 30,
    "1min": 60,
    "5min": 300,
    "15min": 900,
    "1h": 3600,
}
# Option key -> (filter, window seconds); ordered as shown in the options flow.
OPTIONS: dict[str, tuple[str, int | None]] = {
    **{f"mean_{name}": (MEAN, seconds) for name, seconds in WINDOWS.items()},
    **{f"throttle_{name}": (THROTTLE, seconds) for name, seconds in WINDOWS.items()},
    NONE: (NONE, None),
}
DEFAULT = "mean_1min"
PRECISION = 4


def resolve(option: Any) -> tuple[str, int | None]:
    """Return (filter, window) for a stored option, falling back to the default."""
    return OPTIONS.get(option, OPTIONS[DEFAULT]) if isinstance(option, str) else OPTIONS[DEFAULT]


def option_for(choices: Mapping[str, Any] | None, entity_id: str) -> str:
    """Configured option key of an entity (default if missing or unknown)."""
    choice = (choices or {}).get(entity_id)
    return choice if isinstance(choice, str) and choice in OPTIONS else DEFAULT


def _number(value: float) -> int | float:
    value = round(value, PRECISION)
    return int(value) if value.is_integer() and abs(value) < 2**53 else value


class Smoother:
    """Turns the readings of one entity into smoothed readings."""

    def __init__(self, option: str) -> None:
        self.option = option if option in OPTIONS else DEFAULT
        self.kind, self.window = OPTIONS[self.option]
        self._template: dict[str, Any] | None = None
        self._start: float | None = None
        self._end: float | None = None
        self._covered_from = 0.0
        self._weighted = 0.0
        self._samples = 0
        self._last_value: float | None = None
        self._last_time = 0.0

    def _tag(self, reading: dict[str, Any]) -> dict[str, Any]:
        tagged = dict(reading) | {"smoothing": self.kind}
        if self.window is not None:
            tagged["smoothing_window"] = self.window
        return tagged

    def add(self, reading: dict[str, Any], when: datetime) -> list[dict[str, Any]]:
        """Feed one reading (from ``build_reading``); return readings ready to send."""
        if self.kind == NONE:
            return [self._tag(reading)]
        t = when.timestamp()
        if self.kind == THROTTLE:
            if self._end is not None and t < self._end:
                return []
            assert self.window is not None
            self._end = (t // self.window) * self.window + self.window
            return [self._tag(reading)]
        if self._last_value is not None and t < self._last_time:
            return []
        out = self.flush(when)
        value = float(reading["state"])
        attributes = reading.get("attributes", {})
        resets = (
            isinstance(attributes, Mapping)
            and attributes.get("state_class") == "total_increasing"
            and self._samples > 0
            and self._last_value is not None
            and value < self._last_value
        )
        if resets:
            # A meter reset must not be averaged with the old count: close the window early.
            out += self._close(t)
            self._last_value = None
            self._start, self._end = t, self._aligned_end(t)
            self._covered_from, self._weighted = t, 0.0
        elif self._start is None:
            assert self.window is not None
            self._start = (t // self.window) * self.window
            self._end = self._start + self.window
            if self._last_value is not None:
                # The previous state stayed current until this change.
                self._covered_from = self._start
                self._weighted = self._last_value * (t - self._start)
            else:
                self._covered_from, self._weighted = t, 0.0
        else:
            assert self._last_value is not None
            self._weighted += self._last_value * (t - self._last_time)
        self._last_value, self._last_time = value, t
        self._samples += 1
        self._template = reading
        return out

    def _aligned_end(self, t: float) -> float:
        assert self.window is not None
        return (t // self.window) * self.window + self.window

    def flush(self, now: datetime) -> list[dict[str, Any]]:
        """Emit the mean of a window that has ended by ``now``."""
        if self.kind != MEAN or self._end is None or now.timestamp() < self._end:
            return []
        return self._close(self._end)

    def drain(self, now: datetime) -> list[dict[str, Any]]:
        """Emit the partial mean of the running window (e.g. on shutdown)."""
        if self.kind != MEAN or self._end is None:
            return []
        return self._close(min(now.timestamp(), self._end))

    def _close(self, end: float) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self._start is not None and self._samples > 0 and self._template is not None and self._last_value is not None:
            weighted = self._weighted + self._last_value * max(0.0, end - self._last_time)
            duration = end - self._covered_from
            mean = weighted / duration if duration > 0 else self._last_value
            start = datetime.fromtimestamp(self._start, UTC)
            out.append(self._tag(self._template | {"timestamp": timestamp_key(start), "state": _number(mean)}))
        self._start = self._end = None
        self._samples = 0
        self._weighted = 0.0
        self._last_time = max(self._last_time, end)
        return out
