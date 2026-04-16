"""Config flow for Geely Galaxy integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries

from .const import CONF_HARDWARE_DEVICE_ID, CONF_REFRESH_TOKEN, DOMAIN
from .session_store import SessionStore

_LOGGER = logging.getLogger(__name__)


class GeelyGalaxyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Geely Galaxy config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        """Handle the user step."""
        if user_input is not None:
            hardware_device_id = user_input[CONF_HARDWARE_DEVICE_ID]
            _LOGGER.info(
                "配置流程收到用户输入，hardware_device_id=%s，含refresh_token=%s",
                hardware_device_id,
                CONF_REFRESH_TOKEN in user_input,
            )
            _LOGGER.info("配置流程开始设置 unique_id，hardware_device_id=%s", hardware_device_id)
            await self.async_set_unique_id(hardware_device_id)
            _LOGGER.info("配置流程完成设置 unique_id，hardware_device_id=%s", hardware_device_id)
            self._abort_if_unique_id_configured()
            session_store = SessionStore(self.hass)
            await session_store.async_save(
                hardware_device_id,
                {CONF_REFRESH_TOKEN: user_input[CONF_REFRESH_TOKEN]},
            )
            _LOGGER.info("配置流程已写入会话凭证，hardware_device_id=%s", hardware_device_id)
            _LOGGER.info("配置流程准备创建 entry，title=%s", hardware_device_id)
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
                    vol.Required(CONF_REFRESH_TOKEN): str,
                    vol.Required(CONF_HARDWARE_DEVICE_ID): str,
                }
            ),
        )
