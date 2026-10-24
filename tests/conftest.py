"""Fixtures for Home Assistant based tests."""

from __future__ import annotations

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

API_KEY = "bte_" + "0123456789abcdef" + "_" + "a" * 64
URL = "https://buttle.test"
ENERGY = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}
POWER = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
GAS = {"unit_of_measurement": "m³", "device_class": "gas", "state_class": "total_increasing"}
STATUS_BODY = {
    "status": "ok",
    "api_version": 1,
    "api_release": "1.2.0",
    "client": {"minimum": "0.2.0", "latest": "0.2.0"},
    "scopes": ["readings:write"],
    "limits": {"requests_per_minute": 60, "max_readings_per_request": 200, "max_body_bytes": 262144},
    "retention_days": 730,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/buttle_energy."""
    yield
