"""Climate platform for Geely Galaxy."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, _get_nested

_LOGGER = logging.getLogger(__name__)

DEFAULT_TEMPERATURE = 26
MIN_TEMPERATURE = 16
MAX_TEMPERATURE = 32


class GeelyVehicleClimate(ClimateEntity, RestoreEntity):
    """Geely vehicle climate entity (thermostat)."""

    _attr_has_entity_name = True
    _attr_translation_key = "climate"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = MIN_TEMPERATURE
    _attr_max_temp = MAX_TEMPERATURE
    _attr_target_temperature_step = 1
    _attr_icon = "mdi:air-conditioner"
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        vehicle: dict,
        entry: ConfigEntry,
        coordinator: Any,
        client: Any,
    ) -> None:
        self._coordinator = coordinator
        self._client = client
        self._vin = vehicle.get("vin", "unknown")
        self._entry = entry
        self._target_temperature: float = DEFAULT_TEMPERATURE
        name = vehicle.get("carName") or vehicle.get("seriesNameVs") or self._vin
        self._attr_unique_id = f"{entry.entry_id}_{self._vin}_climate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            name=name,
            model=vehicle.get("modelName") or vehicle.get("seriesName"),
            manufacturer="Geely",
            serial_number=self._vin,
            configuration_url="https://galaxy-app.geely.com",
        )

    async def async_added_to_hass(self) -> None:
        """Restore last known target temperature on startup."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None:
            last_temp = last_state.attributes.get(ATTR_TEMPERATURE)
            if last_temp is not None:
                try:
                    self._target_temperature = float(last_temp)
                except (ValueError, TypeError):
                    pass

        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        auth = self._coordinator.vehicle_authorizations.get(self._vin, {})
        return bool(auth.get("access_token") and auth.get("user_id"))

    @property
    def hvac_mode(self) -> HVACMode:
        detailed = self._coordinator.get_vehicle_status_attributes(self._vin)
        vehicle_status = (
            detailed.get("vehicleStatus", {}) if isinstance(detailed, dict) else {}
        )
        if not isinstance(vehicle_status, dict):
            return HVACMode.OFF

        raw = _get_nested(
            vehicle_status,
            "additionalVehicleStatus.climateStatus.preClimateActive",
        )
        if raw is not None and str(raw).lower() == "true":
            return HVACMode.HEAT_COOL
        return HVACMode.OFF

    @property
    def target_temperature(self) -> float:
        return self._target_temperature

    def _extract_climate_state(self, detailed: dict[str, Any]) -> bool | None:
        """Extract climate on/off state from vehicle status dict.

        Used as check_fn for rapid polling.
        """
        vehicle_status = (
            detailed.get("vehicleStatus", {}) if isinstance(detailed, dict) else {}
        )
        if not isinstance(vehicle_status, dict):
            return None
        raw = _get_nested(
            vehicle_status,
            "additionalVehicleStatus.climateStatus.preClimateActive",
        )
        if raw is None:
            return None
        return str(raw).lower() == "true"

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.HEAT_COOL:
            await self._async_turn_on_climate()
        elif hvac_mode == HVACMode.OFF:
            await self._async_turn_off_climate()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        self._target_temperature = temperature

        # If climate is currently on, re-send with new temperature
        if self.hvac_mode == HVACMode.HEAT_COOL:
            await self._async_turn_on_climate()
        else:
            # Just update the local state, will be used on next turn on
            self.async_write_ha_state()

    async def _async_turn_on_climate(self) -> None:
        auth = self._coordinator.vehicle_authorizations.get(self._vin, {})
        authorization = auth.get("access_token")
        if not authorization:
            return

        pre_command_value = self._extract_climate_state(
            self._coordinator.get_vehicle_status_attributes(self._vin)
        )

        await self._client.async_remote_climate(
            vehicle_id=self._vin,
            authorization=authorization,
            turn_on=True,
            temperature=int(self._target_temperature),
        )

        self.async_write_ha_state()

        self.hass.async_create_task(
            self._coordinator.async_start_rapid_poll(
                vin=self._vin,
                entry=self._entry,
                switch_key="climate",
                pre_command_value=pre_command_value,
                check_fn=self._extract_climate_state,
            )
        )

    async def _async_turn_off_climate(self) -> None:
        auth = self._coordinator.vehicle_authorizations.get(self._vin, {})
        authorization = auth.get("access_token")
        if not authorization:
            return

        pre_command_value = self._extract_climate_state(
            self._coordinator.get_vehicle_status_attributes(self._vin)
        )

        await self._client.async_remote_climate(
            vehicle_id=self._vin,
            authorization=authorization,
            turn_on=False,
        )

        self.async_write_ha_state()

        self.hass.async_create_task(
            self._coordinator.async_start_rapid_poll(
                vin=self._vin,
                entry=self._entry,
                switch_key="climate",
                pre_command_value=pre_command_value,
                check_fn=self._extract_climate_state,
            )
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Geely Galaxy climate from config entry."""
    _LOGGER.debug("开始 setup climate entry，entry_id=%s", entry.entry_id)
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]

    vehicles = coordinator.data or []
    valid_vehicles = [vehicle for vehicle in vehicles if vehicle.get("vin")]

    entities: list[ClimateEntity] = []
    for vehicle in valid_vehicles:
        entities.append(
            GeelyVehicleClimate(vehicle, entry, coordinator, client)
        )

    async_add_entities(entities)
