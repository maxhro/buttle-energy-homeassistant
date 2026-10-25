"""Buttle Energie: send Home Assistant energy readings to buttle.de."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ButtleClient
from .const import DEFAULT_URL
from .uploader import ButtleUploader

PLATFORMS: list[Platform] = [Platform.SENSOR]

type ButtleConfigEntry = ConfigEntry[ButtleUploader]


async def async_setup_entry(hass: HomeAssistant, entry: ButtleConfigEntry) -> bool:
    """Start collecting and uploading readings for one buttle.de account."""
    if entry.data[CONF_URL].strip().rstrip("/") == "https://buttle.de":
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_URL: DEFAULT_URL},
            unique_id=DEFAULT_URL if entry.unique_id == "https://buttle.de" else entry.unique_id,
        )
    client = ButtleClient(async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_API_KEY])
    uploader = ButtleUploader(hass, entry, client)
    entry.runtime_data = uploader
    await uploader.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ButtleConfigEntry) -> bool:
    """Stop the uploader and persist pending readings."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ButtleConfigEntry) -> None:
    """Delete the local offline buffer when the integration is removed."""
    from homeassistant.helpers.storage import Store

    from .const import DOMAIN, STORAGE_VERSION

    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.buffer").async_remove()


async def _async_reload(hass: HomeAssistant, entry: ButtleConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
