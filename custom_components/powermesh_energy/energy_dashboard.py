"""Derive a transfer suggestion from the Home Assistant energy dashboard."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .readings import suggest

_LOGGER = logging.getLogger(__name__)


async def async_dashboard_preferences(hass: HomeAssistant) -> dict[str, Any] | None:
    """Return the energy dashboard configuration, or None if unavailable."""
    try:
        from homeassistant.components.energy.data import async_get_manager

        manager = await async_get_manager(hass)
    except Exception:  # noqa: BLE001 - the energy integration is optional
        _LOGGER.debug("Energy dashboard configuration is not available", exc_info=True)
        return None
    data = manager.data
    return dict(data) if data else None


async def async_suggestion(hass: HomeAssistant) -> tuple[list[str], dict[str, str]]:
    """Return (compatible entity ids, skipped id -> reason) from the dashboard."""
    preferences = await async_dashboard_preferences(hass)
    attributes: dict[str, Any] = {}
    for state in hass.states.async_all("sensor"):
        attributes[state.entity_id] = state.attributes
    return suggest(preferences, attributes)
