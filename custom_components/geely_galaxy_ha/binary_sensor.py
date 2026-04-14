"""Binary sensor platform for Geely Galaxy."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    VEHICLE_BINARY_SENSOR_DESCRIPTIONS,
    GeelyVehicleBinarySensorDescription,
    _get_nested,
)

_LOGGER = logging.getLogger(__name__)


def _flatten_dict(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict into dot-separated keys."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_dict(value, full_key))
        else:
            flat[full_key] = value
    return flat


class GeelyVehicleBinarySensor(BinarySensorEntity):
    """A binary sensor entity that reads from vehicleStatus by data_path."""

    _attr_has_entity_name = True

    def __init__(
        self,
        description: GeelyVehicleBinarySensorDescription,
        vehicle: dict,
        entry_id: str,
        coordinator: Any,
    ) -> None:
        self.entity_description = description
        self._coordinator = coordinator
        self._vin = vehicle.get("vin", "unknown")
        name = vehicle.get("carName") or vehicle.get("seriesNameVs") or self._vin
        self._attr_unique_id = f"{entry_id}_{self._vin}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            name=name,
            model=vehicle.get("modelName") or vehicle.get("seriesName"),
            manufacturer="Geely",
            serial_number=self._vin,
            configuration_url="https://galaxy-app.geely.com",
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the binary sensor is on."""
        detailed = self._coordinator.get_vehicle_status_attributes(self._vin)
        vehicle_status = detailed.get("vehicleStatus", {}) if isinstance(detailed, dict) else {}
        if not isinstance(vehicle_status, dict):
            return None
        raw = _get_nested(vehicle_status, self.entity_description.data_path)
        if raw is None:
            return None
        # 将值转换为字符串进行比较（API 返回的可能是 bool 或 string）
        raw_str = str(raw).lower()
        on_value_str = str(self.entity_description.on_value).lower()
        return raw_str == on_value_str

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.async_add_listener(self.async_write_ha_state))


class GeelyVehicleConnectivitySensor(BinarySensorEntity):
    """Device connectivity binary sensor – one per vehicle."""

    _attr_has_entity_name = True
    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:devices"

    def __init__(
        self,
        vehicle: dict,
        entry_id: str,
        coordinator: Any,
    ) -> None:
        self._coordinator = coordinator
        self._vin = vehicle.get("vin", "unknown")
        name = vehicle.get("carName") or vehicle.get("seriesNameVs") or self._vin
        self._attr_unique_id = f"{entry_id}_{self._vin}_connectivity"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            name=name,
            model=vehicle.get("modelName") or vehicle.get("seriesName"),
            manufacturer="Geely",
            serial_number=self._vin,
            configuration_url="https://galaxy-app.geely.com",
        )

    @property
    def is_on(self) -> bool:
        """Return True if coordinator has status data for this vehicle."""
        detailed = self._coordinator.get_vehicle_status_attributes(self._vin)
        return bool(detailed)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all vehicle data as flattened attributes."""
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
    """Set up Geely Galaxy binary sensors from config entry."""
    _LOGGER.info("开始 setup binary_sensor entry，entry_id=%s", entry.entry_id)
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    vehicles = coordinator.data or []
    valid_vehicles = [vehicle for vehicle in vehicles if vehicle.get("vin")]

    entities: list[BinarySensorEntity] = []
    for vehicle in valid_vehicles:
        # 为每辆车创建连通性传感器（非配置驱动，统一创建）
        entities.append(
            GeelyVehicleConnectivitySensor(vehicle, entry.entry_id, coordinator)
        )
        # 按描述创建所有 vehicleStatus binary sensor
        for description in VEHICLE_BINARY_SENSOR_DESCRIPTIONS:
            entities.append(
                GeelyVehicleBinarySensor(description, vehicle, entry.entry_id, coordinator)
            )

    _LOGGER.info(
        "binary_sensor 实体构建完成，entry_id=%s，entity_count=%s",
        entry.entry_id, len(entities),
    )
    async_add_entities(entities)
    _LOGGER.info("binary_sensor async_add_entities 调用完成，entry_id=%s", entry.entry_id)
