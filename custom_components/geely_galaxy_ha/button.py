"""Button platform for Geely Galaxy."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class GeelyVehicleFindCarButton(ButtonEntity):
    """Geely vehicle find car button entity."""

    _attr_has_entity_name = True
    _attr_translation_key = "find_car"
    _attr_icon = "mdi:car-search"

    def __init__(
        self,
        vehicle: dict,
        entry_id: str,
        coordinator: Any,
        client: Any,
    ) -> None:
        self._coordinator = coordinator
        self._client = client
        self._vin = vehicle.get("vin", "unknown")
        self._entry_id = entry_id
        name = vehicle.get("carName") or vehicle.get("seriesNameVs") or self._vin
        self._attr_unique_id = f"{entry_id}_{self._vin}_find_car"
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

    async def async_press(self) -> None:
        auth = self._coordinator.vehicle_authorizations.get(self._vin, {})
        authorization = auth.get("access_token")
        if not authorization:
            return

        await self._client.async_remote_find_vehicle(
            vehicle_id=self._vin,
            authorization=authorization,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Geely Galaxy buttons from config entry."""
    _LOGGER.info("开始 setup button entry，entry_id=%s", entry.entry_id)
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]

    vehicles = coordinator.data or []
    valid_vehicles = [vehicle for vehicle in vehicles if vehicle.get("vin")]

    entities: list[ButtonEntity] = [
        GeelyVehicleFindCarButton(vehicle, entry.entry_id, coordinator, client)
        for vehicle in valid_vehicles
    ]

    async_add_entities(entities)
