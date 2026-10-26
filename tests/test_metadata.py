"""Registry-backed Home Assistant metadata tests."""

from homeassistant.helpers import (
    area_registry,
    device_registry,
    entity_registry,
    floor_registry,
    label_registry,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powermesh_energy.metadata import entity_friendly_name, entity_metadata


async def test_entity_metadata_uses_device_area_fallback_and_registered_names(hass):
    floors = floor_registry.async_get(hass)
    areas = area_registry.async_get(hass)
    labels = label_registry.async_get(hass)
    devices = device_registry.async_get(hass)
    entities = entity_registry.async_get(hass)

    config_entry = MockConfigEntry(domain="synthetic")
    config_entry.add_to_hass(hass)
    floor = floors.async_create("Ground", level=0)
    area = areas.async_create("Kitchen", floor_id=floor.floor_id)
    label = labels.async_create("Energy")
    device = devices.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("synthetic", "device")},
    )
    devices.async_update_device(device.id, area_id=area.id, labels={label.label_id})
    entity = entities.async_get_or_create(
        "sensor",
        "synthetic",
        "temperature",
        suggested_object_id="temperature",
        device_id=device.id,
    )

    result = entity_metadata(hass, entity.entity_id)

    assert result["area"] == "Kitchen"
    assert result["floor"] == "Ground"
    assert result["device_id"] == device.id
    assert result["labels"] == ["Energy"]


async def test_entity_area_is_used_and_unknown_entity_has_no_metadata(hass):
    areas = area_registry.async_get(hass)
    entities = entity_registry.async_get(hass)
    config_entry = MockConfigEntry(domain="synthetic")
    config_entry.add_to_hass(hass)
    entity_area = areas.async_create("Entity area")
    entity = entities.async_get_or_create(
        "sensor",
        "synthetic",
        "power",
        suggested_object_id="power",
    )
    entities.async_update_entity(entity.entity_id, area_id=entity_area.id)
    entities.async_update_entity(entity.entity_id, name="Room temperature")

    assert entity_metadata(hass, entity.entity_id)["area"] == "Entity area"
    assert entity_friendly_name(hass, entity.entity_id) == "Room temperature"
    assert entity_friendly_name(hass, "sensor.missing") is None
    assert entity_metadata(hass, "sensor.missing") == {}
