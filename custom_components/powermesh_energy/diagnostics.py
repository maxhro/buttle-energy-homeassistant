"""Diagnostics download for Powermesh Energie (API key redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import PowermeshConfigEntry
from .const import VERSION
from .energy_dashboard import async_suggestion


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: PowermeshConfigEntry) -> dict[str, Any]:
    """Return configuration and upload state without secrets or reading values."""
    uploader = entry.runtime_data
    suggestion, skipped = await async_suggestion(hass)
    return {
        "entry": async_redact_data(dict(entry.data), {CONF_API_KEY}),
        "options": dict(entry.options),
        "integration_version": VERSION,
        "latest_integration_version": uploader.latest_version,
        "server_release": uploader.server_release,
        "entities": uploader.entities,
        "upload_interval": uploader.interval_name,
        "smoothing": uploader.smoothing,
        "dashboard_suggestion": suggestion,
        "dashboard_skipped": skipped,
        "account_setup_required": uploader.account.setup_required if uploader.account else None,
        "account_setup_expires_at": uploader.account.setup_expires_at if uploader.account else None,
        "status": uploader.status,
        "last_error": uploader.last_error,
        "pending": uploader.pending,
        "accepted_total": uploader.accepted_total,
        "dropped_total": uploader.dropped_total,
        "buffer_limit_readings": uploader.buffer_limit,
        "last_upload": uploader.last_upload.isoformat() if uploader.last_upload else None,
    }
