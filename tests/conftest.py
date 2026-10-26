"""Fixtures for Home Assistant based tests."""

from __future__ import annotations

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

ENERGY = {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}
POWER = {"unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}
GAS = {"unit_of_measurement": "m³", "device_class": "gas", "state_class": "total_increasing"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/powermesh_energy."""
    yield
