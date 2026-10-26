"""Helpers without Home Assistant imports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import math
import re
from typing import Any

ENTITY_ID_PATTERN = re.compile(r"^sensor\.[a-z0-9_]{1,200}$")
API_KEY_PATTERN = re.compile(r"^pme_([a-f0-9]{16})_[a-f0-9]{64}$")
MAX_ABS_VALUE = 1e12

# Supported combinations per device class.
ALLOWED: dict[str, dict[str, frozenset[str]]] = {
    "energy": {
        "units": frozenset({"Wh", "kWh", "MWh"}),
        "state_classes": frozenset({"total", "total_increasing"}),
    },
    "power": {
        "units": frozenset({"W", "kW"}),
        "state_classes": frozenset({"measurement"}),
    },
}

# Energy dashboard keys that reference a statistic/entity to transfer.
_DASHBOARD_KEYS = (
    "stat_energy_from",
    "stat_energy_to",
    "stat_rate",
    "stat_rate_from",
    "stat_rate_to",
    "stat_consumption",
)
# Source types that are never suggested.
_EXCLUDED_SOURCE_TYPES = frozenset({"water"})


def key_public_id(api_key: str) -> str | None:
    """Return the public part of a powermesh.de API key, or None if malformed."""
    if not isinstance(api_key, str):
        return None
    match = API_KEY_PATTERN.fullmatch(api_key.strip())
    return match.group(1) if match else None


def dashboard_statistic_ids(preferences: Mapping[str, Any] | None) -> list[str]:
    """Collect every statistic id referenced by the energy dashboard.

    Supports the current flat grid format as well as the legacy
    ``flow_from``/``flow_to``/``power`` lists and nested ``power_config``.
    Order follows the dashboard; duplicates are removed.
    """
    if not preferences:
        return []
    found: list[str] = []

    def collect(node: Any) -> None:
        if isinstance(node, Mapping):
            for key in _DASHBOARD_KEYS:
                value = node.get(key)
                if isinstance(value, str) and value and value not in found:
                    found.append(value)
            for nested in ("flow_from", "flow_to", "power", "power_config"):
                if nested in node:
                    collect(node[nested])
        elif isinstance(node, list):
            for item in node:
                collect(item)

    for source in preferences.get("energy_sources") or []:
        if isinstance(source, Mapping) and source.get("type") not in _EXCLUDED_SOURCE_TYPES:
            collect(source)
    collect(preferences.get("device_consumption") or [])
    return found


def incompatibility(entity_id: str, attributes: Mapping[str, Any] | None) -> str | None:
    """Return why an entity cannot be transferred, or None if it is compatible."""
    if not ENTITY_ID_PATTERN.match(entity_id):
        return "entity_id"
    if attributes is None:
        return "missing"
    device_class = attributes.get("device_class")
    rules = ALLOWED.get(device_class) if isinstance(device_class, str) else None
    if rules is None:
        return "device_class"
    if attributes.get("unit_of_measurement") not in rules["units"]:
        return "unit"
    if attributes.get("state_class") not in rules["state_classes"]:
        return "state_class"
    return None


def suggest(
    preferences: Mapping[str, Any] | None,
    attributes_of: Mapping[str, Mapping[str, Any] | None],
) -> tuple[list[str], dict[str, str]]:
    """Split the dashboard entities into a compatible suggestion and skipped ones.

    ``attributes_of`` maps entity ids to their current state attributes (None if
    the entity currently has no state). External statistics (``domain:id``) are
    skipped because they are not entities.
    """
    suggestion: list[str] = []
    skipped: dict[str, str] = {}
    for statistic_id in dashboard_statistic_ids(preferences):
        if ":" in statistic_id:
            skipped[statistic_id] = "external_statistic"
            continue
        reason = incompatibility(statistic_id, attributes_of.get(statistic_id))
        if reason is None:
            suggestion.append(statistic_id)
        else:
            skipped[statistic_id] = reason
    return suggestion, skipped


def build_reading(
    entity_id: str,
    state: str,
    attributes: Mapping[str, Any],
    timestamp: datetime,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a reading from a state, or None if it cannot be sent."""
    if not ENTITY_ID_PATTERN.fullmatch(entity_id):
        return None
    if isinstance(state, bool):
        return None
    try:
        value = float(state)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or abs(value) > MAX_ABS_VALUE:
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    if value.is_integer() and abs(value) < 2**53:
        number: int | float = int(value)
    else:
        number = value
    raw_unit = attributes.get("unit_of_measurement")
    unit = "" if raw_unit is None else raw_unit
    if (
        not isinstance(unit, str)
        or len(unit) > 64
        or unit.casefold() in {"unknown", "unavailable", "none"}
    ):
        return None
    reading: dict[str, Any] = {
        "entity_id": entity_id,
        "timestamp": timestamp_key(timestamp),
        "state": number,
        "unit_of_measurement": unit,
    }
    allowed_limits = {"friendly_name": 255, "device_class": 64, "state_class": 64}
    safe_attributes = {
        name: value
        for name, limit in allowed_limits.items()
        if isinstance((value := attributes.get(name)), str)
        and 0 < len(value) <= limit
        and value.casefold() not in {"unknown", "unavailable", "none"}
    }
    if safe_attributes:
        reading["attributes"] = safe_attributes
    if isinstance(context, Mapping):
        safe_context: dict[str, Any] = {}
        for name, limit in (("area", 255), ("floor", 255), ("device_id", 128)):
            value = context.get(name)
            if (
                isinstance(value, str)
                and 0 < len(value) <= limit
                and value.strip() == value
                and value.casefold() not in {"unknown", "unavailable", "none"}
            ):
                safe_context[name] = value
        labels = context.get("labels")
        if isinstance(labels, (list, tuple)):
            safe_labels: list[str] = []
            for label in labels:
                if (
                    isinstance(label, str)
                    and 0 < len(label) <= 255
                    and label.strip() == label
                    and label.casefold() not in {"unknown", "unavailable", "none"}
                    and label not in safe_labels
                ):
                    safe_labels.append(label)
                if len(safe_labels) == 20:
                    break
            if safe_labels:
                safe_context["labels"] = safe_labels
        if safe_context:
            reading["context"] = safe_context
    return reading


def is_api_reading(reading: Any) -> bool:
    """Check the new REST reading schema before restoring any persisted data."""
    if not isinstance(reading, Mapping):
        return False
    required = {"entity_id", "timestamp", "state", "unit_of_measurement"}
    if not required.issubset(reading):
        return False
    entity_id = reading.get("entity_id")
    if not isinstance(entity_id, str) or not ENTITY_ID_PATTERN.fullmatch(entity_id):
        return False
    if not isinstance(reading.get("timestamp"), str):
        return False
    try:
        timestamp = datetime.fromisoformat(reading["timestamp"].replace("Z", "+00:00"))
    except ValueError:
        return False
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return False
    if isinstance(reading["state"], bool):
        return False
    try:
        raw_state = reading["state"]
        if isinstance(raw_state, bool) or not isinstance(raw_state, (int, float)):
            return False
        state = float(raw_state)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(state) or abs(state) > MAX_ABS_VALUE:
        return False
    if (
        not isinstance(reading.get("unit_of_measurement"), str)
        or len(reading["unit_of_measurement"]) > 64
        or reading["unit_of_measurement"].casefold() in {"unknown", "unavailable", "none"}
    ):
        return False
    allowed = required | {"attributes", "context", "smoothing", "smoothing_window"}
    if set(reading) - allowed:
        return False
    if "attributes" in reading:
        attrs = reading["attributes"]
        if not isinstance(attrs, Mapping) or set(attrs) - {"friendly_name", "device_class", "state_class"}:
            return False
        if any(
            not isinstance(value, str)
            or not value
            or len(value) > (255 if key == "friendly_name" else 64)
            or value.casefold() in {"unknown", "unavailable", "none"}
            for key, value in attrs.items()
        ):
            return False
    if "context" in reading:
        ctx = reading["context"]
        if not isinstance(ctx, Mapping) or set(ctx) - {"area", "floor", "labels", "device_id"}:
            return False
        bounds = {"area": 255, "floor": 255, "device_id": 128}
        if any(
            not isinstance(value, str) or not value or len(value) > bounds[key]
            or value.casefold() in {"unknown", "unavailable", "none"}
            for key, value in ctx.items()
            if key in bounds
        ):
            return False
        labels = ctx.get("labels", [])
        if (
            not isinstance(labels, list)
            or len(labels) > 20
            or any(not isinstance(label, str) or not label or len(label) > 255 for label in labels)
            or len(set(labels)) != len(labels)
            or any(label.casefold() in {"unknown", "unavailable", "none"} for label in labels)
        ):
            return False
    if "smoothing" in reading and reading["smoothing"] not in {
        "none", "time_simple_moving_average", "time_throttle"
    }:
        return False
    if "smoothing_window" in reading and (
        type(reading["smoothing_window"]) is not int or not 1 <= reading["smoothing_window"] <= 86400
    ):
        return False
    return True


def timestamp_key(timestamp: datetime) -> str:
    """UTC timestamp with whole seconds."""
    return timestamp.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_version(value: Any) -> tuple[int, int, int] | None:
    """Parse ``x.y.z``; None if malformed."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})", value.strip())
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def compatibility(
    server: Mapping[str, Any] | None, client_version: str, api_major: int, min_api_release: str
) -> tuple[str | None, str | None]:
    """Return (blocking problem, newer integration version available).

    Problems: ``api_incompatible`` (server too old or other major version) or
    ``update_required`` (server requires a newer integration).
    """
    server = server if isinstance(server, Mapping) else {}
    release = parse_version(server.get("api_release"))
    own = parse_version(client_version)
    if server.get("api_version") != api_major or release is None or release < (parse_version(min_api_release) or (0, 0, 0)):
        return "api_incompatible", None
    client = server.get("client") if isinstance(server.get("client"), Mapping) else {}
    minimum = parse_version(client.get("minimum"))
    latest = parse_version(client.get("latest"))
    if own is None or (minimum is not None and own < minimum):
        return "update_required", client.get("latest") if latest else None
    if latest is not None and latest > own:
        return None, client["latest"]
    return None, None


def chunks(readings: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    """Yield consecutive batches of at most ``size`` readings."""
    for start in range(0, len(readings), size):
        yield readings[start : start + size]


def invalid_indices(error_body: Mapping[str, Any] | None) -> set[int]:
    """Indices of rejected readings in an error response."""
    if not isinstance(error_body, Mapping):
        return set()
    error = error_body.get("error")
    if not isinstance(error, Mapping) or error.get("code") != "invalid_readings":
        return set()
    indices: set[int] = set()
    for detail in error.get("details") or []:
        if isinstance(detail, Mapping) and isinstance(detail.get("index"), int):
            indices.add(detail["index"])
    return indices
