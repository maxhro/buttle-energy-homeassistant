"""Tests for readings.py."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

_PATH = Path(__file__).parents[1] / "custom_components" / "powermesh_energy" / "readings.py"
_SPEC = importlib.util.spec_from_file_location("powermesh_readings", _PATH)
readings = importlib.util.module_from_spec(_SPEC)
sys.modules["powermesh_readings"] = readings
_SPEC.loader.exec_module(readings)

ENERGY = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}
POWER = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
WHEN = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)

PREFS = {
    "energy_sources": [
        {
            "type": "grid",
            "stat_energy_from": "sensor.grid_import",
            "stat_energy_to": "sensor.grid_export",
            "power_config": {"stat_rate": "sensor.grid_power"},
        },
        {
            "type": "grid",
            "flow_from": [{"stat_energy_from": "sensor.legacy_import"}],
            "flow_to": [{"stat_energy_to": "sensor.legacy_export"}],
            "power": [{"stat_rate": "sensor.legacy_power"}],
        },
        {"type": "solar", "stat_energy_from": "sensor.pv_energy", "stat_rate": "sensor.pv_power"},
        {"type": "battery", "stat_energy_from": "sensor.bat_out", "stat_energy_to": "sensor.bat_in", "stat_soc": "sensor.soc"},
        {"type": "gas", "stat_energy_from": "sensor.gas_m3"},
        {"type": "water", "stat_energy_from": "sensor.water"},
        {"type": "solar", "stat_energy_from": "forecast:external"},
    ],
    "device_consumption": [{"stat_consumption": "sensor.fridge_energy", "stat_rate": "sensor.fridge_power"}],
}


def test_key_public_id() -> None:
    key = "bte_" + "a" * 16 + "_" + "b" * 64
    assert readings.key_public_id(key) == "a" * 16
    assert readings.key_public_id(key.upper()) is None
    assert readings.key_public_id("bte_short") is None


def test_dashboard_statistic_ids_reads_current_and_legacy_format() -> None:
    ids = readings.dashboard_statistic_ids(PREFS)
    for expected in [
        "sensor.grid_import", "sensor.grid_export", "sensor.grid_power",
        "sensor.legacy_import", "sensor.legacy_export", "sensor.legacy_power",
        "sensor.pv_energy", "sensor.pv_power", "sensor.bat_out", "sensor.bat_in",
        "sensor.gas_m3", "sensor.fridge_energy", "sensor.fridge_power", "forecast:external",
    ]:
        assert expected in ids
    assert "sensor.water" not in ids
    assert "sensor.soc" not in ids
    assert len(ids) == len(set(ids))
    assert readings.dashboard_statistic_ids(None) == []


def test_suggest_splits_compatible_and_skipped() -> None:
    attributes = {
        "sensor.grid_import": ENERGY,
        "sensor.grid_power": POWER,
        "sensor.gas_m3": {"unit_of_measurement": "m³", "device_class": "gas", "state_class": "total_increasing"},
        "sensor.pv_energy": {**ENERGY, "unit_of_measurement": "Wh"},
        "sensor.pv_power": {**POWER, "state_class": "total"},
    }
    suggestion, skipped = readings.suggest(PREFS, attributes)
    assert suggestion == ["sensor.grid_import", "sensor.grid_power", "sensor.pv_energy"]
    assert skipped["sensor.gas_m3"] == "device_class"
    assert skipped["sensor.pv_power"] == "state_class"
    assert skipped["sensor.grid_export"] == "missing"
    assert skipped["forecast:external"] == "external_statistic"


def test_incompatibility_reasons() -> None:
    assert readings.incompatibility("light.x", ENERGY) == "entity_id"
    assert readings.incompatibility("sensor.x", None) == "missing"
    assert readings.incompatibility("sensor.x", {**ENERGY, "unit_of_measurement": "W"}) == "unit"
    assert readings.incompatibility("sensor.x", {**POWER, "unit_of_measurement": "kW"}) is None


def test_build_reading_contains_only_six_fields() -> None:
    reading = readings.build_reading("sensor.grid_import", "12.0", {**ENERGY, "friendly_name": "Netz"}, WHEN)
    assert reading == {
        "entity_id": "sensor.grid_import",
        "timestamp": "2026-01-02T03:04:05Z",
        "value": 12,
        "unit": "kWh",
        "device_class": "energy",
        "state_class": "total_increasing",
    }
    assert readings.build_reading("sensor.p", "-1.5", POWER, WHEN)["value"] == -1.5


def test_build_reading_rejects_unusable_states() -> None:
    for state in ["unknown", "unavailable", "nan", "inf", "1e13", ""]:
        assert readings.build_reading("sensor.p", state, POWER, WHEN) is None
    assert readings.build_reading("sensor.p", "1", POWER, WHEN.replace(tzinfo=None)) is None
    assert readings.build_reading("sensor.p", "1", {**POWER, "unit_of_measurement": "VA"}, WHEN) is None


def test_timestamp_key_converts_to_utc_seconds() -> None:
    local = datetime(2026, 6, 1, 12, 0, 0, 999999, tzinfo=timezone(timedelta(hours=2)))
    assert readings.timestamp_key(local) == "2026-06-01T10:00:00Z"


def test_chunks() -> None:
    items = [{"i": i} for i in range(450)]
    sizes = [len(batch) for batch in readings.chunks(items, 200)]
    assert sizes == [200, 200, 50]


def test_invalid_indices() -> None:
    body = {"error": {"code": "invalid_readings", "details": [{"index": 3, "field": "unit"}, {"index": "x"}, {"index": 7}]}}
    assert readings.invalid_indices(body) == {3, 7}
    assert readings.invalid_indices({"error": {"code": "invalid_payload"}}) == set()
    assert readings.invalid_indices(None) == set()


SERVER = {"api_version": 2, "api_release": "2.0.0", "client": {"minimum": "1.0.0", "latest": "1.0.0"}}


def test_parse_version() -> None:
    assert readings.parse_version("1.10.3") == (1, 10, 3)
    assert readings.parse_version(" 0.2.0 ") == (0, 2, 0)
    for invalid in ["1.0", "v1.0.0", "1.0.0-beta", None, 1]:
        assert readings.parse_version(invalid) is None


def test_compatibility() -> None:
    check = readings.compatibility
    assert check(SERVER, "1.0.0", 2, "2.0.0") == (None, None)
    assert check(SERVER | {"api_release": "2.1.0"}, "1.0.0", 2, "2.0.0") == (None, None)
    assert check(SERVER | {"client": {"minimum": "0.9.0", "latest": "1.1.0"}}, "1.0.0", 2, "2.0.0") == (None, "1.1.0")
    assert check(SERVER | {"client": {"minimum": "1.1.0", "latest": "1.1.0"}}, "1.0.0", 2, "2.0.0") == ("update_required", "1.1.0")
    assert check(SERVER | {"api_release": "1.9.9"}, "1.0.0", 2, "2.0.0")[0] == "api_incompatible"
    assert check(SERVER | {"api_version": 1, "api_release": "1.2.0"}, "1.0.0", 2, "2.0.0")[0] == "api_incompatible"
    assert check({"api_version": 1}, "1.0.0", 2, "2.0.0")[0] == "api_incompatible"
    assert check(None, "1.0.0", 2, "2.0.0")[0] == "api_incompatible"
