"""Sensor platform for Geely Galaxy."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    VEHICLE_SENSOR_DESCRIPTIONS,
    GeelyVehicleSensorDescription,
    _get_nested,
)

_LOGGER = logging.getLogger(__name__)


class GeelyVehicleStatusSensor(SensorEntity):
    """A sensor entity that reads from vehicleStatus by data_path."""

    _attr_has_entity_name = True

    def __init__(
        self,
        description: GeelyVehicleSensorDescription,
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
    def native_value(self) -> Any:
        """Return sensor value from coordinator data."""
        detailed = self._coordinator.get_vehicle_status_attributes(self._vin)
        vehicle_status = detailed.get("vehicleStatus", {}) if isinstance(detailed, dict) else {}
        if not isinstance(vehicle_status, dict):
            return None
        raw = _get_nested(vehicle_status, self.entity_description.data_path)
        if raw is None:
            return None
        # 特殊处理: updateTime 是毫秒时间戳，需要转为 datetime
        if self.entity_description.key == "update_time":
            try:
                return datetime.fromtimestamp(int(raw) / 1000, tz=UTC)
            except (ValueError, TypeError, OSError):
                return None
        # 值映射: 将 API 原始值转换为 options 中的键
        if self.entity_description.value_map is not None:
            return self.entity_description.value_map.get(str(raw), str(raw))
        return raw

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.async_add_listener(self.async_write_ha_state))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Geely Galaxy sensors from config entry."""
    _LOGGER.debug("开始 setup sensor entry，entry_id=%s", entry.entry_id)
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    vehicles = coordinator.data or []
    valid_vehicles = [vehicle for vehicle in vehicles if vehicle.get("vin")]
    _LOGGER.debug(
        "车辆过滤完成，entry_id=%s，raw=%s，valid=%s",
        entry.entry_id, len(vehicles), len(valid_vehicles),
    )

    entities: list[SensorEntity] = []
    for vehicle in valid_vehicles:
        for description in VEHICLE_SENSOR_DESCRIPTIONS:
            entities.append(
                GeelyVehicleStatusSensor(description, vehicle, entry.entry_id, coordinator)
            )

    _LOGGER.debug("实体构建完成，entry_id=%s，entity_count=%s", entry.entry_id, len(entities))
    async_add_entities(entities)
    _LOGGER.debug("async_add_entities 调用完成，entry_id=%s", entry.entry_id)
