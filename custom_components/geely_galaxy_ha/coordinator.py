"""Data update coordinator for Geely Galaxy integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GeelyGalaxyApiClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class GeelyGalaxyCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinate Geely vehicle list updates."""

    def __init__(self, hass: HomeAssistant, client: GeelyGalaxyApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> list[dict[str, Any]]:
        _LOGGER.info("开始拉取车辆列表数据")
        try:
            vehicles = await self.client.async_get_vehicle_list()
            _LOGGER.info("车辆列表拉取成功，count=%s", len(vehicles))
            return vehicles
        except Exception as err:
            _LOGGER.exception("车辆列表拉取失败: %s", err)
            raise UpdateFailed(f"Failed to update Geely vehicles: {err}") from err
