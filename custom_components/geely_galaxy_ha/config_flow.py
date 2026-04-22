"""Config flow for Geely Galaxy integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import CONF_HARDWARE_DEVICE_ID, CONF_REFRESH_TOKEN, DOMAIN
from .session_store import SessionStore

_LOGGER = logging.getLogger(__name__)


class GeelyGalaxyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Geely Galaxy config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the user step."""
        if user_input is not None:
            hardware_device_id = user_input[CONF_HARDWARE_DEVICE_ID]
            _LOGGER.debug(
                "配置流程收到用户输入，hardware_device_id=%s，含refresh_token=%s",
                hardware_device_id,
                CONF_REFRESH_TOKEN in user_input,
            )
            _LOGGER.debug("配置流程开始设置 unique_id，hardware_device_id=%s", hardware_device_id)
            await self.async_set_unique_id(hardware_device_id)
            _LOGGER.debug("配置流程完成设置 unique_id，hardware_device_id=%s", hardware_device_id)
            self._abort_if_unique_id_configured()
            session_store = SessionStore(self.hass)
            await session_store.async_save(
                hardware_device_id,
                {CONF_REFRESH_TOKEN: user_input[CONF_REFRESH_TOKEN]},
            )
            _LOGGER.debug("配置流程已写入会话凭证，hardware_device_id=%s", hardware_device_id)
            _LOGGER.debug("配置流程准备创建 entry，title=%s", hardware_device_id)
            return self.async_create_entry(
                title=hardware_device_id,
                data={
                    CONF_HARDWARE_DEVICE_ID: hardware_device_id,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REFRESH_TOKEN): selector.TextSelector(
                        selector.TextSelectorConfig(type="text")
                    ),
                    vol.Required(CONF_HARDWARE_DEVICE_ID): str,
                }
            ),
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        """Handle reauth flow start."""
        entry = self._get_reauth_entry()
        hardware_device_id = entry.data.get(CONF_HARDWARE_DEVICE_ID)
        if not hardware_device_id:
            return self.async_abort(reason="missing_hardware_device_id")

        await self.async_set_unique_id(hardware_device_id)
        self._abort_if_unique_id_mismatch(reason="wrong_account")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        """Confirm reauth with new refresh token."""
        entry = self._get_reauth_entry()
        hardware_device_id = entry.data.get(CONF_HARDWARE_DEVICE_ID)
        if not hardware_device_id:
            return self.async_abort(reason="missing_hardware_device_id")

        if user_input is not None:
            session_store = SessionStore(self.hass)
            await session_store.async_save(
                hardware_device_id,
                {CONF_REFRESH_TOKEN: user_input[CONF_REFRESH_TOKEN]},
            )
            return self.async_update_reload_and_abort(
                entry,
                data_updates={CONF_HARDWARE_DEVICE_ID: hardware_device_id},
            )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REFRESH_TOKEN): selector.TextSelector(
                        selector.TextSelectorConfig(type="text")
                    ),
                }
            ),
        )
