"""API client for Geely Galaxy integration."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from .const import API_KEY_REFRESH, API_KEY_VEHICLE_LIST

API_KEYS = {
    "204453306": "uUwSi6m9m8Nx3Grx7dQghyxMpOXJKDGu",
    "204373120": "XfH7OiOe07vorWwvGQdCqh6quYda9yGW",
    "204167276": "5XfsfFBrUEF0fFiAUmAFFQ6lmhje3iMZ",
    "204168364": "NqYVmMgH5HXol8RB8RkOpl8iLCBakdRo",
    "204179735": "UhmsX3xStU4vrGHGYtqEXahtkYuQncMf",
}

RequestFunc = Callable[
    [str, str, dict[str, str], dict[str, Any] | None],
    Awaitable[tuple[int, dict[str, Any]]],
]
TokenUpdateFunc = Callable[[str, int, str], Awaitable[None]]

_LOGGER = logging.getLogger(__name__)


class GeelyGalaxyApiClient:
    """Geely Galaxy async API client."""

    USER_AGENT = "ALIYUN-ANDROID-UA"
    APP_ID = "galaxy-app"
    APP_VERSION = "1.26.1"
    PLATFORM = "Android"

    def __init__(
        self,
        refresh_token: str,
        hardware_device_id: str,
        token: str | None = None,
        token_expires_at: int = 0,
        request_func: RequestFunc | None = None,
        on_token_update: TokenUpdateFunc | None = None,
    ) -> None:
        self.refresh_token = refresh_token
        self.hardware_device_id = hardware_device_id
        self.token = token or ""
        self.token_expires_at = token_expires_at
        self._request_func = request_func
        self._on_token_update = on_token_update

    @staticmethod
    def _format_gmt_date() -> str:
        return datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")

    @staticmethod
    def _hmac_sha256(secret: str, text: str) -> str:
        digest = hmac.new(secret.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _build_sign_string(
        self,
        method: str,
        accept: str,
        content_md5: str,
        content_type: str,
        date_str: str,
        key: str,
        nonce: str,
        timestamp_ms: str,
        path: str,
        appcode: str | None = None,
    ) -> str:
        appcode_line = f"x-ca-appcode:{appcode}\n" if appcode else ""
        return (
            f"{method}\n"
            f"{accept}\n"
            f"{content_md5}\n"
            f"{content_type}\n"
            f"{date_str}\n"
            f"{appcode_line}"
            f"x-ca-key:{key}\n"
            f"x-ca-nonce:{nonce}\n"
            f"x-ca-timestamp:{timestamp_ms}\n"
            f"{path}"
        )

    def _build_common_headers(
        self,
        key: str,
        date_str: str,
        nonce: str,
        timestamp_ms: str,
        signature: str,
    ) -> dict[str, str]:
        headers = {
            "date": date_str,
            "x-ca-signature": signature,
            "x-ca-nonce": nonce,
            "x-ca-key": key,
            "ca_version": "1",
            "accept": "application/json; charset=utf-8",
            "x-ca-timestamp": timestamp_ms,
            "token": self.token or "",
            "deviceSN": self.hardware_device_id,
            "txCookie": "",
            "appid": self.APP_ID,
            "appVersion": self.APP_VERSION,
            "platform": self.PLATFORM,
            "Cache-Control": "no-cache",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "tenantid": "569001701001",
        }

        if key == API_KEY_REFRESH:
            headers["usetoken"] = "true"
            headers["host"] = "galaxy-user-api.geely.com"
            headers["taenantid"] = "569001701001"
            headers["x-ca-appcode"] = "galaxy-app-user"
        else:
            headers["usetoken"] = "1"
            headers["host"] = "galaxy-app.geely.com"
            headers["x-refresh-token"] = "true"

        return headers

    def _build_get_headers(self, key: str, path: str) -> dict[str, str]:
        date_str = self._format_gmt_date()
        timestamp_ms = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())

        sign_str = self._build_sign_string(
            method="GET",
            accept="application/json; charset=utf-8",
            content_md5="",
            content_type="application/x-www-form-urlencoded; charset=utf-8",
            date_str=date_str,
            key=key,
            nonce=nonce,
            timestamp_ms=timestamp_ms,
            path=path,
        )
        signature = self._hmac_sha256(API_KEYS[key], sign_str)

        headers = self._build_common_headers(key, date_str, nonce, timestamp_ms, signature)
        headers["x-ca-signature-headers"] = "x-ca-nonce,x-ca-timestamp,x-ca-key"
        headers["content-type"] = "application/x-www-form-urlencoded; charset=utf-8"
        headers["user-agent"] = self.USER_AGENT
        return headers

    def _build_post_headers(self, key: str, path: str, json_body: dict[str, Any]) -> dict[str, str]:
        date_str = self._format_gmt_date()
        timestamp_ms = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())

        body_bytes = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        content_md5 = base64.b64encode(hashlib.md5(body_bytes).digest()).decode("utf-8")
        content_type = "application/json; charset=utf-8"
        appcode = "usp-gateway-code" if key == API_KEY_VEHICLE_LIST else None

        sign_str = self._build_sign_string(
            method="POST",
            accept="application/json; charset=utf-8",
            content_md5=content_md5,
            content_type=content_type,
            date_str=date_str,
            key=key,
            nonce=nonce,
            timestamp_ms=timestamp_ms,
            path=path,
            appcode=appcode,
        )
        signature = self._hmac_sha256(API_KEYS[key], sign_str)

        headers = self._build_common_headers(key, date_str, nonce, timestamp_ms, signature)
        headers["content-md5"] = content_md5
        headers["content-type"] = content_type
        headers["user-agent"] = self.USER_AGENT
        if appcode:
            headers["x-ca-appcode"] = appcode
            headers["x-ca-signature-headers"] = "x-ca-appcode,x-ca-nonce,x-ca-timestamp,x-ca-key"
            headers["host"] = "galaxy-vc.geely.com"
        else:
            headers["x-ca-signature-headers"] = "x-ca-nonce,x-ca-timestamp,x-ca-key"
        return headers


    async def _async_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        if self._request_func is None:
            raise RuntimeError("request_func is required")
        return await self._request_func(method, url, headers, json_body)

    async def async_ensure_valid_token(self) -> str:
        now = int(datetime.now(UTC).timestamp())
        if self.token and self.token_expires_at > now:
            _LOGGER.info("使用缓存 token，expires_at=%s", self.token_expires_at)
            return self.token
        _LOGGER.info("token 无效或已过期，开始刷新 token")
        return await self.async_refresh_token()

    async def async_refresh_token(self) -> str:
        _LOGGER.info("开始刷新 token")
        path = f"/api/v1/login/refresh?refreshToken={self.refresh_token}"
        url = f"https://galaxy-user-api.geely.com{path}"
        headers = self._build_get_headers(API_KEY_REFRESH, path)

        status, payload = await self._async_request("GET", url, headers)
        if status != 200 or payload.get("code") != "success":
            _LOGGER.error("刷新 token 失败，status=%s，code=%s", status, payload.get("code"))
            raise RuntimeError(f"refresh token failed: {payload}")

        dto = payload["data"]["centerTokenDto"]
        self.token = dto["token"]
        self.refresh_token = dto.get("refreshToken", self.refresh_token)
        self.token_expires_at = int(dto["expireAt"] / 1000)

        if self._on_token_update:
            await self._on_token_update(self.token, self.token_expires_at, self.refresh_token)

        _LOGGER.info("token 刷新成功，expires_at=%s", self.token_expires_at)
        return self.token

    async def async_get_vehicle_list(self) -> list[dict[str, Any]]:
        _LOGGER.info("开始请求车辆列表")
        await self.async_ensure_valid_token()
        path = "/vc/app/v1/vehicle/control/myList"
        url = f"https://galaxy-vc.geely.com{path}"
        data = await self._async_request_with_retry_once_on_403(
            method="POST",
            url=url,
            headers_factory=lambda: self._build_post_headers(API_KEY_VEHICLE_LIST, path, {}),
            json_body={},
        )
        _LOGGER.info("车辆列表请求完成，count=%s", len(data))
        return data

    async def _async_request_with_retry_once_on_403(
        self,
        method: str,
        url: str,
        headers_factory: Callable[[], dict[str, str]],
        json_body: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        status, payload = await self._async_request(method, url, headers_factory(), json_body)

        if status == 403 or payload.get("code") == "user-login-invalid-expired":
            _LOGGER.warning(
                "Geely API token 无效（status=%s，code=%s），清除 token 并刷新重试一次",
                status,
                payload.get("code"),
            )
            self.token = None
            self.token_expires_at = 0
            await self.async_refresh_token()
            status, payload = await self._async_request(method, url, headers_factory(), json_body)
            _LOGGER.info("token 刷新重试完成，status=%s，code=%s", status, payload.get("code"))

        if status != 200:
            _LOGGER.error("请求失败，status=%s，code=%s", status, payload.get("code"))
            raise RuntimeError(f"request failed status={status}, payload={payload}")
        if payload.get("code") != "0":
            _LOGGER.error("API 业务失败，code=%s", payload.get("code"))
            raise RuntimeError(f"api failed payload={payload}")

        data = payload.get("data", [])
        if not isinstance(data, list):
            _LOGGER.error("API 返回 data 结构异常，type=%s", type(data).__name__)
            raise RuntimeError(f"unexpected data payload={payload}")
        return data
