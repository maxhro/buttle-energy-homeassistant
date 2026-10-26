"""Collect only bounded, explicitly allow-listed Home Assistant metadata."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry,
    device_registry,
    entity_registry,
    floor_registry,
    label_registry,
)


def entity_metadata(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """Return known area, floor, labels and device identifier for an entity."""
    entities = entity_registry.async_get(hass)
    entity = entities.async_get(entity_id)
    if entity is None:
        return {}

    devices = device_registry.async_get(hass)
    device = devices.async_get(entity.device_id) if entity.device_id else None
    area_id = entity.area_id or (device.area_id if device is not None else None)
    areas = area_registry.async_get(hass)
    area = areas.async_get_area(area_id) if area_id else None
    floor = (
        floor_registry.async_get(hass).async_get_floor(area.floor_id)
        if area is not None and area.floor_id
        else None
    )

    metadata: dict[str, Any] = {}
    if area is not None:
        metadata["area"] = area.name
    if floor is not None:
        metadata["floor"] = floor.name
    if device is not None:
        metadata["device_id"] = device.id

    label_ids = set(getattr(entity, "labels", ()))
    if device is not None:
        label_ids.update(getattr(device, "labels", ()))
    if area is not None:
        label_ids.update(getattr(area, "labels", ()))
    labels = label_registry.async_get(hass)
    names = []
    for label_id in sorted(label_ids):
        label = labels.async_get_label(label_id)
        if label is not None and isinstance(label.name, str) and label.name not in names:
            names.append(label.name)
        if len(names) == 20:
            break
    if names:
        metadata["labels"] = names
    return metadata


def entity_friendly_name(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return a user-assigned entity name, when the registry has one."""
    entity = entity_registry.async_get(hass).async_get(entity_id)
    if entity is None:
        return None
    name = entity.name or entity.original_name
    return name if isinstance(name, str) else None
