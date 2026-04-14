"""Geely Galaxy integration."""

from __future__ import annotations

import logging
from typing import Any

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up Geely Galaxy from a config entry."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api import GeelyGalaxyApiClient
    from .const import (
        CONF_HARDWARE_DEVICE_ID,
        CONF_REFRESH_TOKEN,
        CONF_TOKEN,
        CONF_TOKEN_EXPIRES_AT,
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

    async def _on_token_update(token: str, token_expires_at: int, refresh_token: str) -> None:
        new_data = dict(entry.data)
        old_refresh_token = new_data.get(CONF_REFRESH_TOKEN)
        new_data[CONF_TOKEN] = token
        new_data[CONF_TOKEN_EXPIRES_AT] = token_expires_at
        new_data[CONF_REFRESH_TOKEN] = refresh_token
        hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.info(
            "token 已更新并写回配置，entry_id=%s，token_expires_at=%s，refresh_token_changed=%s",
            entry.entry_id,
            token_expires_at,
            refresh_token != old_refresh_token,
        )

    client = GeelyGalaxyApiClient(
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        hardware_device_id=entry.data[CONF_HARDWARE_DEVICE_ID],
        token=entry.data.get(CONF_TOKEN),
        token_expires_at=entry.data.get(CONF_TOKEN_EXPIRES_AT, 0),
        request_func=_request,
        on_token_update=_on_token_update,
    )
    _LOGGER.info("API client 初始化完成，entry_id=%s", entry.entry_id)

    coordinator = GeelyGalaxyCoordinator(hass, client)
    _LOGGER.info("coordinator 初始化完成，entry_id=%s", entry.entry_id)
    _LOGGER.info("开始首次刷新车辆数据，entry_id=%s", entry.entry_id)
    try:
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.info("首次刷新车辆数据成功，entry_id=%s", entry.entry_id)
    except Exception:
        _LOGGER.exception("首次刷新车辆数据失败，entry_id=%s", entry.entry_id)
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }
    _LOGGER.info("hass.data 写入完成，entry_id=%s", entry.entry_id)

    _LOGGER.info("开始转发平台 setup，entry_id=%s，platforms=%s", entry.entry_id, PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("平台 setup 转发完成，entry_id=%s", entry.entry_id)
    _LOGGER.info("Geely Galaxy entry 初始化完成，entry_id=%s", entry.entry_id)
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload Geely Galaxy config entry."""
    _LOGGER.info("开始卸载 Geely Galaxy entry，entry_id=%s", entry.entry_id)
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok and DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    _LOGGER.info("卸载 Geely Galaxy entry 结果=%s，entry_id=%s", ok, entry.entry_id)
    return ok
