"""Powermesh Energie: send selected Home Assistant sensor readings to powermesh.de."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PowermeshClient
from .const import CONF_API_KEY
from .uploader import PowermeshUploader

PLATFORMS: list[Platform] = [Platform.SENSOR]

type PowermeshConfigEntry = ConfigEntry[PowermeshUploader]


async def async_setup_entry(hass: HomeAssistant, entry: PowermeshConfigEntry) -> bool:
    """Start collecting and uploading readings for one powermesh.de account."""
    api_key = entry.data.get(CONF_API_KEY)
    if not isinstance(api_key, str):
        raise ConfigEntryError(
            "This older integration entry uses an incompatible connection format. "
            "Keep any pending local readings safe before replacing the entry."
        )
    client = PowermeshClient(async_get_clientsession(hass), api_key)
    uploader = PowermeshUploader(hass, entry, client)
    entry.runtime_data = uploader
    await uploader.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PowermeshConfigEntry) -> bool:
    """Stop the uploader and persist pending readings."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: PowermeshConfigEntry) -> None:
    """Delete the local offline buffer and account notices when the integration is removed."""
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.helpers.storage import Store

    from .const import DOMAIN, STORAGE_VERSION
    from .uploader import ACCOUNT_ISSUES

    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.buffer").async_remove()
    for issue in ACCOUNT_ISSUES:
        ir.async_delete_issue(hass, DOMAIN, f"{issue}_{entry.entry_id}")


async def _async_reload(hass: HomeAssistant, entry: PowermeshConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
