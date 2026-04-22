"""Geely Galaxy integration."""

from __future__ import annotations

import logging
from typing import Any

from .const import (
    CONF_HARDWARE_DEVICE_ID,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    CONF_VEHICLE_AUTHORIZATIONS,
    DOMAIN,
)
from .session_store import SessionStore

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["switch", "button", "climate", "binary_sensor", "sensor", "device_tracker"]


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up Geely Galaxy from a config entry."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api import GeelyGalaxyApiClient
    from .coordinator import GeelyGalaxyCoordinator

    hardware_device_id = entry.data.get(CONF_HARDWARE_DEVICE_ID)
    if not hardware_device_id:
        _LOGGER.error("初始化失败：缺少 hardware_device_id，entry_id=%s", entry.entry_id)
        return False

    session_store = SessionStore(hass)
    session_data = await session_store.async_load(hardware_device_id)
    if not session_data:
        _LOGGER.error("初始化失败：未找到会话凭证，hardware_device_id=%s", hardware_device_id)
        return False

    refresh_token = session_data.get(CONF_REFRESH_TOKEN)
    if not refresh_token:
        _LOGGER.error("初始化失败：会话凭证缺少 refresh_token，hardware_device_id=%s", hardware_device_id)
        return False

    _LOGGER.debug(
        "开始初始化 Geely Galaxy entry，entry_id=%s，hardware_device_id=%s",
        entry.entry_id,
        hardware_device_id,
    )
    session = async_get_clientsession(hass)
    _LOGGER.debug("HTTP session 初始化完成，entry_id=%s", entry.entry_id)

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

    async def _on_token_update(token: str, token_expires_at: int, refreshed_token: str) -> None:
        await session_store.async_save(
            hardware_device_id,
            {
                CONF_TOKEN: token,
                CONF_TOKEN_EXPIRES_AT: token_expires_at,
                CONF_REFRESH_TOKEN: refreshed_token,
            },
        )

        data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        coordinator = data.get("coordinator") if data else None
        if coordinator is not None and getattr(coordinator, "_poll_entry", None) is None:
            await coordinator.async_start_vehicle_status_polling(entry)
            _LOGGER.debug("token 更新后恢复车辆状态轮询，entry_id=%s", entry.entry_id)

        _LOGGER.debug("token 已更新，entry_id=%s，token_expires_at=%s", entry.entry_id, token_expires_at)

    async def _on_vehicle_authorizations_update(entry_obj: Any, authorizations: dict[str, dict[str, Any]]) -> None:
        if entry_obj.entry_id != entry.entry_id:
            return
        await session_store.async_save(
            hardware_device_id,
            {CONF_VEHICLE_AUTHORIZATIONS: authorizations},
        )
        _LOGGER.debug("车辆 authorization 已持久化，entry_id=%s，count=%s", entry.entry_id, len(authorizations))

    reauth_handled = False

    async def _on_reauth_required() -> None:
        nonlocal reauth_handled
        if reauth_handled:
            return
        reauth_handled = True

        data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        coordinator = data.get("coordinator") if data else None
        if coordinator is not None:
            await coordinator.async_cancel_all_rapid_polls()
            await coordinator.async_stop()

        try:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Geely Galaxy 需要重新登录",
                    "message": "检测到登录凭证已失效，已停止车辆轮询。请在集成配置中重新登录后恢复轮询。",
                    "notification_id": f"{DOMAIN}_{entry.entry_id}_reauth_required",
                },
                blocking=False,
            )
        except Exception as err:
            _LOGGER.warning("发送重新登录通知失败 entry_id=%s err=%s", entry.entry_id, err)

        progress = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        in_reauth = any(
            item.get("context", {}).get("source") == "reauth"
            and item.get("context", {}).get("entry_id") == entry.entry_id
            for item in progress
        )
        if not in_reauth:
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "reauth", "entry_id": entry.entry_id},
                data=entry.data,
            )

        _LOGGER.warning("登录状态失效，已停止轮询并触发重新登录流程 entry_id=%s", entry.entry_id)

    client = GeelyGalaxyApiClient(
        refresh_token=refresh_token,
        hardware_device_id=hardware_device_id,
        token=session_data.get(CONF_TOKEN),
        token_expires_at=session_data.get(CONF_TOKEN_EXPIRES_AT, 0),
        request_func=_request,
        on_token_update=_on_token_update,
        on_reauth_required=_on_reauth_required,
    )
    _LOGGER.debug("API client 初始化完成，entry_id=%s", entry.entry_id)

    coordinator = GeelyGalaxyCoordinator(
        hass,
        client,
        persisted_vehicle_authorizations=session_data.get(CONF_VEHICLE_AUTHORIZATIONS) or {},
        persist_vehicle_authorizations_cb=_on_vehicle_authorizations_update,
    )
    _LOGGER.debug("coordinator 初始化完成，entry_id=%s", entry.entry_id)

    await coordinator.async_config_entry_first_refresh()
    _LOGGER.debug("首次刷新车辆列表完成，entry_id=%s，count=%s", entry.entry_id, len(coordinator.data or []))

    await coordinator.async_start_vehicle_status_polling(entry)
    _LOGGER.debug("已启动每分钟车辆状态轮询（含首次立即获取），entry_id=%s", entry.entry_id)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }
    _LOGGER.debug("hass.data 写入完成，entry_id=%s", entry.entry_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("平台 setup 转发完成，entry_id=%s，platforms=%s", entry.entry_id, PLATFORMS)
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload Geely Galaxy config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data and data.get("coordinator"):
        await data["coordinator"].async_cancel_all_rapid_polls()
        await data["coordinator"].async_stop()

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok and DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
