"""Sensor platform for Geely Galaxy."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _flatten_dict(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_dict(value, full_key))
        else:
            flat[full_key] = value
    return flat


class GeelyVehicleSensor(SensorEntity):
    """Vehicle connectivity sensor for one Geely vehicle."""

    _attr_has_entity_name = True

    def __init__(self, vehicle: dict, entry_id: str, coordinator: Any) -> None:
        self._vehicle = vehicle
        self._coordinator = coordinator
        self._vin = vehicle.get("vin", "unknown")
        name = vehicle.get("carName") or vehicle.get("seriesNameVs") or self._vin
        self._attr_translation_key = "connectivity"
        self._attr_unique_id = f"{entry_id}_{self._vin}_connectivity"
        self._attr_native_value = "online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            name=name,
            model=vehicle.get("modelName") or vehicle.get("seriesName"),
            manufacturer="Geely",
            serial_number=self._vin,
            configuration_url="https://galaxy-app.geely.com",
        )
        _LOGGER.info("已构建设备实体对象，entry_id=%s，vin=%s，name=%s", entry_id, self._vin, name)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        vehicle = self._coordinator.get_vehicle_static_data(self._vin)
        attrs: dict[str, Any] = dict(vehicle)
        detailed = self._coordinator.get_vehicle_status_attributes(self._vin)
        vehicle_status = detailed.get("vehicleStatus", {}) if isinstance(detailed, dict) else {}
        if isinstance(vehicle_status, dict):
            attrs.update(_flatten_dict({"vehicleStatus": vehicle_status}))
        return attrs

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.async_add_listener(self.async_write_ha_state))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Geely Galaxy sensors from config entry."""
    _LOGGER.info("开始 setup sensor entry，entry_id=%s", entry.entry_id)
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    vehicles = coordinator.data or []
    valid_vehicles = [vehicle for vehicle in vehicles if vehicle.get("vin")]
    _LOGGER.info("车辆过滤完成，entry_id=%s，raw=%s，valid=%s", entry.entry_id, len(vehicles), len(valid_vehicles))

    entities = [
        GeelyVehicleSensor(vehicle, entry.entry_id, coordinator)
        for vehicle in valid_vehicles
    ]
    _LOGGER.info("实体构建完成，entry_id=%s，entity_count=%s", entry.entry_id, len(entities))
    async_add_entities(entities)
    _LOGGER.info("async_add_entities 调用完成，entry_id=%s", entry.entry_id)
