"""Geely Galaxy integration."""

from __future__ import annotations

import logging
from typing import Any

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["sensor", "binary_sensor", "device_tracker"]


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up Geely Galaxy from a config entry."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api import GeelyGalaxyApiClient
    from .const import (
        CONF_HARDWARE_DEVICE_ID,
        CONF_REFRESH_TOKEN,
        CONF_TOKEN,
        CONF_TOKEN_EXPIRES_AT,
        CONF_VEHICLE_AUTHORIZATIONS,
    )
    from .coordinator import GeelyGalaxyCoordinator

    _LOGGER.info(
        "开始初始化 Geely Galaxy entry，entry_id=%s，hardware_device_id=%s",
        entry.entry_id,
        entry.data.get(CONF_HARDWARE_DEVICE_ID),
    )
    session = async_get_clientsession(hass)
    _LOGGER.info("HTTP session 初始化完成，entry_id=%s", entry.entry_id)

    async def _request(
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        async with session.request(method, url, headers=headers, json=json_body) as resp:
            try:
                payload = await resp.json(content_type=None)
            except Exception:
                payload = {"code": str(resp.status), "msg": await resp.text()}
            return resp.status, payload

    async def _persist_entry_data(partial_data: dict[str, Any]) -> None:
        new_data = dict(entry.data)
        new_data.update(partial_data)
        hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.info("配置已持久化，entry_id=%s，keys=%s", entry.entry_id, list(partial_data.keys()))

    async def _on_token_update(token: str, token_expires_at: int, refresh_token: str) -> None:
        await _persist_entry_data(
            {
                CONF_TOKEN: token,
                CONF_TOKEN_EXPIRES_AT: token_expires_at,
                CONF_REFRESH_TOKEN: refresh_token,
            }
        )
        _LOGGER.info("token 已更新，entry_id=%s，token_expires_at=%s", entry.entry_id, token_expires_at)

    async def _on_vehicle_authorizations_update(entry_obj: Any, authorizations: dict[str, dict[str, Any]]) -> None:
        if entry_obj.entry_id != entry.entry_id:
            return
        await _persist_entry_data({CONF_VEHICLE_AUTHORIZATIONS: authorizations})
        _LOGGER.info("车辆 authorization 已持久化，entry_id=%s，count=%s", entry.entry_id, len(authorizations))

    client = GeelyGalaxyApiClient(
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        hardware_device_id=entry.data[CONF_HARDWARE_DEVICE_ID],
        token=entry.data.get(CONF_TOKEN),
        token_expires_at=entry.data.get(CONF_TOKEN_EXPIRES_AT, 0),
        request_func=_request,
        on_token_update=_on_token_update,
    )
    _LOGGER.info("API client 初始化完成，entry_id=%s", entry.entry_id)

    coordinator = GeelyGalaxyCoordinator(
        hass,
        client,
        persisted_vehicle_authorizations=entry.data.get(CONF_VEHICLE_AUTHORIZATIONS) or {},
        persist_vehicle_authorizations_cb=_on_vehicle_authorizations_update,
    )
    _LOGGER.info("coordinator 初始化完成，entry_id=%s", entry.entry_id)

    await coordinator.async_config_entry_first_refresh()
    _LOGGER.info("首次刷新车辆列表完成，entry_id=%s，count=%s", entry.entry_id, len(coordinator.data or []))

    coordinator.async_start_vehicle_status_polling(entry)
    _LOGGER.info("已启动每分钟车辆状态轮询，entry_id=%s", entry.entry_id)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }
    _LOGGER.info("hass.data 写入完成，entry_id=%s", entry.entry_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("平台 setup 转发完成，entry_id=%s，platforms=%s", entry.entry_id, PLATFORMS)
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload Geely Galaxy config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data and data.get("coordinator"):
        await data["coordinator"].async_stop()

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok and DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
