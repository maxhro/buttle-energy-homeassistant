"""Diagnostic sensors showing the upload state."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ButtleConfigEntry
from .const import DOMAIN, STATUSES, VERSION
from .uploader import ButtleUploader


async def async_setup_entry(
    hass: HomeAssistant, entry: ButtleConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the diagnostic sensors."""
    uploader = entry.runtime_data
    async_add_entities(
        [
            ButtleStatusSensor(uploader),
            ButtlePendingSensor(uploader),
            ButtleLastUploadSensor(uploader),
        ]
    )


class _ButtleSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, uploader: ButtleUploader, key: str) -> None:
        self._uploader = uploader
        self._attr_translation_key = key
        self._attr_unique_id = f"{uploader.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uploader.entry.entry_id)},
            name="buttle.de",
            manufacturer="Buttle",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=uploader.client.base_url,
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._uploader.async_add_listener(self.async_write_ha_state))


class ButtleStatusSensor(_ButtleSensor):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES

    def __init__(self, uploader: ButtleUploader) -> None:
        super().__init__(uploader, "upload_status")

    @property
    def native_value(self) -> str:
        return self._uploader.status

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "last_error": self._uploader.last_error,
            "accepted_total": self._uploader.accepted_total,
            "dropped_total": self._uploader.dropped_total,
            "entities": self._uploader.entities,
            "integration_version": VERSION,
            "latest_integration_version": self._uploader.latest_version,
            "server_release": self._uploader.server_release,
        }


class ButtlePendingSensor(_ButtleSensor):
    _attr_native_unit_of_measurement = "readings"

    def __init__(self, uploader: ButtleUploader) -> None:
        super().__init__(uploader, "pending_readings")

    @property
    def native_value(self) -> int:
        return self._uploader.pending


class ButtleLastUploadSensor(_ButtleSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, uploader: ButtleUploader) -> None:
        super().__init__(uploader, "last_upload")

    @property
    def native_value(self) -> datetime | None:
        return self._uploader.last_upload
