"""Sensor platform for Geely Galaxy."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class GeelyVehicleSensor(SensorEntity):
    """Vehicle presence sensor for one Geely vehicle."""

    _attr_has_entity_name = True

    def __init__(self, vehicle: dict, entry_id: str) -> None:
        self._vehicle = vehicle
        self._vin = vehicle.get("vin", "unknown")
        name = vehicle.get("carName") or vehicle.get("seriesNameVs") or self._vin
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{self._vin}_vehicle"
        self._attr_native_value = "online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            name=name,
            model=vehicle.get("modelName") or vehicle.get("seriesName"),
            manufacturer="Geely",
            serial_number=self._vin,
            configuration_url="https://galaxy-app.geely.com",
        )
        self._attr_extra_state_attributes = {
            "vin": self._vin,
            "series_name": vehicle.get("seriesName"),
            "series_name_vs": vehicle.get("seriesNameVs"),
            "model_name": vehicle.get("modelName"),
            "car_name": vehicle.get("carName"),
            "default_vehicle": vehicle.get("defaultVehicle"),
            "vehicle_photo_small": vehicle.get("vehiclePhotoSmall"),
            "vehicle_photo_big": vehicle.get("vehiclePhotoBig"),
        }
        _LOGGER.info("已构建设备实体对象，entry_id=%s，vin=%s，name=%s", entry_id, self._vin, name)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Geely Galaxy sensors from config entry."""
    _LOGGER.info("开始 setup sensor entry，entry_id=%s", entry.entry_id)
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    _LOGGER.info("开始读取 coordinator 车辆数据，entry_id=%s", entry.entry_id)
    vehicles = coordinator.data or []
    valid_vehicles = [vehicle for vehicle in vehicles if vehicle.get("vin")]
    _LOGGER.info("车辆过滤完成，entry_id=%s，raw=%s，valid=%s", entry.entry_id, len(vehicles), len(valid_vehicles))

    entities = [GeelyVehicleSensor(vehicle, entry.entry_id) for vehicle in valid_vehicles]
    _LOGGER.info("实体构建完成，entry_id=%s，entity_count=%s", entry.entry_id, len(entities))
    _LOGGER.info("开始调用 async_add_entities，entry_id=%s", entry.entry_id)
    async_add_entities(entities)
    _LOGGER.info("async_add_entities 调用完成，entry_id=%s", entry.entry_id)
