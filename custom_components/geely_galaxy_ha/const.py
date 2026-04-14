"""Geely Galaxy integration constants."""

from datetime import timedelta

DOMAIN = "geely_galaxy_ha"

CONF_REFRESH_TOKEN = "refresh_token"
CONF_HARDWARE_DEVICE_ID = "hardware_device_id"
CONF_TOKEN = "token"
CONF_TOKEN_EXPIRES_AT = "token_expires_at"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=10)

API_KEY_REFRESH = "204179735"
API_KEY_VEHICLE_LIST = "204373120"
