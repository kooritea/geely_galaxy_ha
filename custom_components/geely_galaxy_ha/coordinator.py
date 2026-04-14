"""Data update coordinator for Geely Galaxy integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GeelyGalaxyApiClient
from .const import (
    CONF_VEHICLE_AUTHORIZATIONS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VEHICLE_STATUS_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class GeelyGalaxyCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinate Geely vehicle list updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: GeelyGalaxyApiClient,
        *,
        persisted_vehicle_authorizations: dict[str, dict[str, Any]] | None,
        persist_vehicle_authorizations_cb,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self._persist_vehicle_authorizations_cb = persist_vehicle_authorizations_cb
        self.vehicle_authorizations: dict[str, dict[str, Any]] = persisted_vehicle_authorizations or {}
        self.vehicle_status_by_vin: dict[str, dict[str, Any]] = {}
        self._status_poll_unsub: CALLBACK_TYPE | None = None
        self._authorization_refresh_lock = asyncio.Lock()
        self._last_authorization_refresh_at = 0
        self._refresh_cooldown_seconds = 60
        self._last_auth_refresh_warning_at = 0

    async def _async_update_data(self) -> list[dict[str, Any]]:
        try:
            vehicles = await self.client.async_get_vehicle_list()
            return vehicles
        except Exception as err:
            raise UpdateFailed(f"Failed to update Geely vehicles: {err}") from err

    def async_start_vehicle_status_polling(self, entry: ConfigEntry) -> None:
        if self._status_poll_unsub is not None:
            return

        async def _poll(_now) -> None:
            await self.async_poll_vehicle_status(entry)

        self._status_poll_unsub = async_track_time_interval(
            self.hass,
            _poll,
            DEFAULT_VEHICLE_STATUS_INTERVAL,
        )

    async def async_stop(self) -> None:
        if self._status_poll_unsub is not None:
            self._status_poll_unsub()
            self._status_poll_unsub = None

    async def async_poll_vehicle_status(self, entry: ConfigEntry) -> None:
        vehicles = self.data or []
        if not vehicles:
            return

        await self._async_refresh_vehicle_authorizations_if_needed(vehicles, entry)

        changed = False
        for vehicle in vehicles:
            vin = vehicle.get("vin")
            if not vin:
                continue
            auth = self.vehicle_authorizations.get(vin)
            if not auth:
                continue
            access_token = auth.get("access_token")
            user_id = auth.get("user_id")
            if not access_token or not user_id:
                continue
            try:
                detailed = await self.client.async_get_vehicle_detailed_status(
                    vehicle_id=vin,
                    user_id=user_id,
                    authorization=access_token,
                )
                if self.vehicle_status_by_vin.get(vin) != detailed:
                    self.vehicle_status_by_vin[vin] = detailed
                    changed = True
                _LOGGER.info("车辆状态轮询成功 vin=%s", vin)
            except Exception as err:
                _LOGGER.info("车辆状态轮询失败 vin=%s err=%s", vin, err)

        if changed:
            self.async_update_listeners()

    async def _async_refresh_vehicle_authorizations_if_needed(
        self,
        vehicles: list[dict[str, Any]],
        entry: ConfigEntry,
    ) -> None:
        now = int(datetime.now(UTC).timestamp())
        refresh_required = False
        for vehicle in vehicles:
            vin = vehicle.get("vin")
            if not vin:
                continue
            auth = self.vehicle_authorizations.get(vin)
            expires_at = int((auth or {}).get("expires_at", 0))
            if not auth or expires_at <= now:
                refresh_required = True
                break

        if not refresh_required:
            return

        async with self._authorization_refresh_lock:
            now = int(datetime.now(UTC).timestamp())
            refresh_required = False
            for vehicle in vehicles:
                vin = vehicle.get("vin")
                if not vin:
                    continue
                auth = self.vehicle_authorizations.get(vin)
                expires_at = int((auth or {}).get("expires_at", 0))
                if not auth or expires_at <= now:
                    refresh_required = True
                    break

            if not refresh_required:
                return

            if now - self._last_authorization_refresh_at < self._refresh_cooldown_seconds:
                return

            try:
                oauth_code = await self.client.async_get_oauth_code()
                for vehicle in vehicles:
                    vin = vehicle.get("vin")
                    if not vin:
                        continue
                    authorization = await self.client.async_get_authorization(oauth_code)
                    self.vehicle_authorizations[vin] = authorization
                await self._persist_vehicle_authorizations_cb(entry, self.vehicle_authorizations)
                self._last_authorization_refresh_at = int(datetime.now(UTC).timestamp())
            except Exception as err:
                if now - self._last_auth_refresh_warning_at >= self._refresh_cooldown_seconds:
                    _LOGGER.warning("请更新集成授权：所有车辆 authorization 刷新失败 err=%s", err)
                    self._last_auth_refresh_warning_at = now

    def get_vehicle_status_attributes(self, vin: str) -> dict[str, Any]:
        return self.vehicle_status_by_vin.get(vin, {})

    def get_vehicle_static_data(self, vin: str) -> dict[str, Any]:
        vehicles = self.data or []
        for vehicle in vehicles:
            if vehicle.get("vin") == vin:
                return vehicle
        return {}

    def get_all_vins(self) -> list[str]:
        return [v.get("vin") for v in (self.data or []) if v.get("vin")]

    def get_persist_payload(self) -> dict[str, Any]:
        return {
            CONF_VEHICLE_AUTHORIZATIONS: self.vehicle_authorizations,
        }
