"""Switch platform for Geely Galaxy."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    VEHICLE_SWITCH_DESCRIPTIONS,
    GeelyVehicleSwitchDescription,
    _get_nested,
)

_LOGGER = logging.getLogger(__name__)


class GeelyVehicleRemoteSwitch(SwitchEntity):
    """Geely vehicle remote switch entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        description: GeelyVehicleSwitchDescription,
        vehicle: dict,
        entry: ConfigEntry,
        coordinator: Any,
        client: Any,
    ) -> None:
        self.entity_description = description
        self._coordinator = coordinator
        self._client = client
        self._vin = vehicle.get("vin", "unknown")
        self._entry = entry
        name = vehicle.get("carName") or vehicle.get("seriesNameVs") or self._vin
        self._attr_unique_id = f"{entry.entry_id}_{self._vin}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            name=name,
            model=vehicle.get("modelName") or vehicle.get("seriesName"),
            manufacturer="Geely",
            serial_number=self._vin,
            configuration_url="https://galaxy-app.geely.com",
        )

    @property
    def available(self) -> bool:
        auth = self._coordinator.vehicle_authorizations.get(self._vin, {})
        return bool(auth.get("access_token") and auth.get("user_id"))

    @property
    def is_on(self) -> bool | None:
        detailed = self._coordinator.get_vehicle_status_attributes(self._vin)
        return self._extract_switch_state(detailed)

    def _extract_switch_state(self, detailed: dict[str, Any]) -> bool | None:
        """从车辆状态字典中提取本开关的 on/off 状态。

        供 coordinator 快速轮询的 check_fn 回调使用。
        """
        vehicle_status = detailed.get("vehicleStatus", {}) if isinstance(detailed, dict) else {}
        if not isinstance(vehicle_status, dict):
            return None

        if self.entity_description.service_type == "climate":
            raw = _get_nested(vehicle_status, "additionalVehicleStatus.climateStatus.preClimateActive")
            return None if raw is None else str(raw).lower() == "true"

        if self.entity_description.service_type == "door":
            locks = [
                _get_nested(vehicle_status, "additionalVehicleStatus.drivingSafetyStatus.doorLockStatusDriver"),
                _get_nested(vehicle_status, "additionalVehicleStatus.drivingSafetyStatus.doorLockStatusPassenger"),
                _get_nested(vehicle_status, "additionalVehicleStatus.drivingSafetyStatus.doorLockStatusDriverRear"),
                _get_nested(vehicle_status, "additionalVehicleStatus.drivingSafetyStatus.doorLockStatusPassengerRear"),
            ]
            valid = [item for item in locks if item is not None]
            if not valid:
                return None
            return any(str(item) == "0" for item in valid)

        if self.entity_description.service_type == "trunk":
            raw = _get_nested(vehicle_status, "additionalVehicleStatus.drivingSafetyStatus.trunkOpenStatus")
            return None if raw is None else str(raw) == "1"

        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        auth = self._coordinator.vehicle_authorizations.get(self._vin, {})
        authorization = auth.get("access_token")
        if not authorization:
            return

        pre_command_value = self.is_on

        if self.entity_description.service_type == "climate":
            await self._client.async_remote_climate(
                vehicle_id=self._vin,
                authorization=authorization,
                turn_on=True,
            )
        elif self.entity_description.service_type == "door":
            await self._client.async_remote_door(
                vehicle_id=self._vin,
                authorization=authorization,
                unlock=True,
            )
        elif self.entity_description.service_type == "trunk":
            await self._client.async_remote_trunk(
                vehicle_id=self._vin,
                authorization=authorization,
                open_=True,
            )

        self.async_write_ha_state()

        # 启动快速轮询以尽早反映车辆状态变化
        self.hass.async_create_task(
            self._coordinator.async_start_rapid_poll(
                vin=self._vin,
                entry=self._entry,
                switch_key=self.entity_description.key,
                pre_command_value=pre_command_value,
                check_fn=self._extract_switch_state,
            )
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        auth = self._coordinator.vehicle_authorizations.get(self._vin, {})
        authorization = auth.get("access_token")
        if not authorization:
            return

        pre_command_value = self.is_on

        if self.entity_description.service_type == "climate":
            await self._client.async_remote_climate(
                vehicle_id=self._vin,
                authorization=authorization,
                turn_on=False,
            )
        elif self.entity_description.service_type == "door":
            await self._client.async_remote_door(
                vehicle_id=self._vin,
                authorization=authorization,
                unlock=False,
            )
        elif self.entity_description.service_type == "trunk":
            await self._client.async_remote_trunk(
                vehicle_id=self._vin,
                authorization=authorization,
                open_=False,
            )

        self.async_write_ha_state()

        # 启动快速轮询以尽早反映车辆状态变化
        self.hass.async_create_task(
            self._coordinator.async_start_rapid_poll(
                vin=self._vin,
                entry=self._entry,
                switch_key=self.entity_description.key,
                pre_command_value=pre_command_value,
                check_fn=self._extract_switch_state,
            )
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._coordinator.async_add_listener(self.async_write_ha_state))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Geely Galaxy switches from config entry."""
    _LOGGER.info("开始 setup switch entry，entry_id=%s", entry.entry_id)
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]

    vehicles = coordinator.data or []
    valid_vehicles = [vehicle for vehicle in vehicles if vehicle.get("vin")]

    entities: list[SwitchEntity] = []
    for vehicle in valid_vehicles:
        for description in VEHICLE_SWITCH_DESCRIPTIONS:
            entities.append(
                GeelyVehicleRemoteSwitch(description, vehicle, entry, coordinator, client)
            )

    async_add_entities(entities)
