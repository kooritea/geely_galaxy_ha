"""API client for Geely Galaxy integration."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import random
import string
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable
from urllib.parse import quote

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

    XCHANGER_DEVICE_BASE_URL = "https://device-api.xchanger.cn"
    XCHANGER_USER_BASE_URL = "https://user-api.xchanger.cn"
    XCHANGER_API_KEY = "67e1bd743f1c4c31841206cbb354b4af"
    XCHANGER_ACCEPT = "application/json;responseformat=3"
    XCHANGER_CONTENT_TYPE = "application/json; charset=UTF-8"
    XCHANGER_OPERATOR_CODE = "geelygalaxy"
    XCHANGER_APP_ID = "galaxy_SDK"
    XCHANGER_USER_AGENT = "okhttp/4.9.3"
    XCHANGER_SIGNATURE_VERSION = "1.0"

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

    @staticmethod
    def _hmac_sha1(secret: str, text: str) -> str:
        digest = hmac.new(secret.encode("utf-8"), text.encode("utf-8"), hashlib.sha1).digest()
        return base64.b64encode(digest).decode("utf-8")

    @staticmethod
    def _content_md5_from_json_body(json_body: dict[str, Any]) -> str:
        body_bytes = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        return base64.b64encode(hashlib.md5(body_bytes).digest()).decode("utf-8")

    @staticmethod
    def _content_md5_from_text(text: str) -> str:
        digest = hashlib.md5(text.encode("utf-8")).digest()
        return base64.b64encode(digest).decode("utf-8")

    @staticmethod
    def _xchanger_nonce(timestamp_ms: int) -> str:
        prefix = "".join(random.choices(string.ascii_lowercase + string.digits, k=3))
        middle = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=7))
        return f"{prefix}-{middle}{suffix}{timestamp_ms}"

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
        token: str | None = None,
    ) -> str:
        token_line = f"token:{token}\n" if token else ""
        appcode_line = f"x-ca-appcode:{appcode}\n" if appcode else ""
        return (
            f"{method}\n"
            f"{accept}\n"
            f"{content_md5}\n"
            f"{content_type}\n"
            f"{date_str}\n"
            f"{token_line}"
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

    def _build_oauth_code_headers(self, path: str) -> dict[str, str]:
        key = API_KEY_REFRESH
        date_str = self._format_gmt_date()
        timestamp_ms = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())
        appcode = "galaxy-app-user"

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
            token=self.token,
            appcode=appcode,
        )
        signature = self._hmac_sha256(API_KEYS[key], sign_str)
        headers = self._build_common_headers(key, date_str, nonce, timestamp_ms, signature)
        headers["x-ca-signature-headers"] = "x-ca-appcode,x-ca-nonce,x-ca-key,token,x-ca-timestamp"
        headers["content-type"] = "application/x-www-form-urlencoded; charset=utf-8"
        headers["user-agent"] = self.USER_AGENT
        headers["x-ca-appcode"] = appcode
        return headers

    def _build_post_headers(self, key: str, path: str, json_body: dict[str, Any]) -> dict[str, str]:
        date_str = self._format_gmt_date()
        timestamp_ms = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())

        content_md5 = self._content_md5_from_json_body(json_body)
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

    def _build_xchanger_headers(
        self,
        *,
        method: str,
        host: str,
        path: str,
        query_param: str | None,
        body_md5_base64: str,
        authorization: str | None = None,
    ) -> dict[str, str]:
        timestamp = int(time.time() * 1000)
        nonce = self._xchanger_nonce(timestamp)
        sign_text = (
            f"{self.XCHANGER_ACCEPT}\n"
            f"x-api-signature-nonce:{nonce}\n"
            f"x-api-signature-version:{self.XCHANGER_SIGNATURE_VERSION}\n"
            f"\n"
            f"{query_param or ''}\n"
            f"{body_md5_base64}\n"
            f"{timestamp}\n"
            f"{method}\n"
            f"{path}"
        )
        signature = self._hmac_sha1(self.XCHANGER_API_KEY, sign_text)
        headers = {
            "Content-Type": self.XCHANGER_CONTENT_TYPE,
            "Accept": self.XCHANGER_ACCEPT,
            "Connection": "Keep-Alive",
            "x-operator-code": self.XCHANGER_OPERATOR_CODE,
            "host": host,
            "x-app-id": self.XCHANGER_APP_ID,
            "User-Agent": self.XCHANGER_USER_AGENT,
            "x-api-signature-version": self.XCHANGER_SIGNATURE_VERSION,
            "x-api-signature-nonce": nonce,
            "x-signature": signature,
            "x-timestamp": str(timestamp),
        }
        if authorization:
            headers["authorization"] = authorization
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

    @staticmethod
    def _is_login_invalid(status: int, payload: dict[str, Any]) -> bool:
        code = payload.get("code")
        return status == 403 or code == "user-login-invalid-expired" or code == "403"

    async def _async_request_with_retry_once_on_login_invalid(
        self,
        *,
        method: str,
        url: str,
        headers_factory: Callable[[], dict[str, str]],
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        status, payload = await self._async_request(method, url, headers_factory(), json_body)
        if self._is_login_invalid(status, payload):
            _LOGGER.warning(
                "Geely API token 无效（status=%s，code=%s），清除 token 并刷新重试一次",
                status,
                payload.get("code"),
            )
            self.token = None
            self.token_expires_at = 0
            await self.async_refresh_token()
            status, payload = await self._async_request(method, url, headers_factory(), json_body)
            _LOGGER.warning(
                "token 刷新重试完成，status=%s，code=%s",
                status,
                payload.get("code"),
            )
        return status, payload

    async def async_ensure_valid_token(self) -> str:
        now = int(datetime.now(UTC).timestamp())
        if self.token and self.token_expires_at > now:
            return self.token
        return await self.async_refresh_token()

    async def async_refresh_token(self) -> str:
        path = f"/api/v1/login/refresh?refreshToken={self.refresh_token}"
        url = f"https://galaxy-user-api.geely.com{path}"
        headers = self._build_get_headers(API_KEY_REFRESH, path)

        status, payload = await self._async_request("GET", url, headers)
        if status != 200 or payload.get("code") != "success":
            raise RuntimeError(f"refresh token failed: {payload}")

        dto = payload["data"]["centerTokenDto"]
        self.token = dto["token"]
        self.refresh_token = dto.get("refreshToken", self.refresh_token)
        self.token_expires_at = int(dto["expireAt"] / 1000)

        if self._on_token_update:
            await self._on_token_update(self.token, self.token_expires_at, self.refresh_token)

        return self.token

    async def async_get_vehicle_list(self) -> list[dict[str, Any]]:
        await self.async_ensure_valid_token()
        path = "/vc/app/v1/vehicle/control/myList"
        url = f"https://galaxy-vc.geely.com{path}"
        data = await self._async_request_with_retry_once_on_403(
            method="POST",
            url=url,
            headers_factory=lambda: self._build_post_headers(API_KEY_VEHICLE_LIST, path, {}),
            json_body={},
        )
        return data

    async def _async_request_with_retry_once_on_403(
        self,
        method: str,
        url: str,
        headers_factory: Callable[[], dict[str, str]],
        json_body: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        status, payload = await self._async_request_with_retry_once_on_login_invalid(
            method=method,
            url=url,
            headers_factory=headers_factory,
            json_body=json_body,
        )

        if status != 200:
            raise RuntimeError(f"request failed status={status}, payload={payload}")
        if payload.get("code") != "0":
            raise RuntimeError(f"api failed payload={payload}")

        data = payload.get("data", [])
        if not isinstance(data, list):
            raise RuntimeError(f"unexpected data payload={payload}")
        return data

    async def async_get_oauth_code(self) -> str:
        await self.async_ensure_valid_token()
        path = "/api/v1/oauth2/code?client_id=30000025&isDestruction=false&response_type=code&scope=snsapiUserinfo"
        url = f"https://galaxy-user-api.geely.com{path}"
        status, payload = await self._async_request_with_retry_once_on_login_invalid(
            method="GET",
            url=url,
            headers_factory=lambda: self._build_oauth_code_headers(path),
            json_body=None,
        )
        if status != 200 or payload.get("code") != "success":
            raise RuntimeError(f"get oauth code failed: {payload}")
        oauth_code = payload.get("data", {}).get("code")
        if not oauth_code:
            raise RuntimeError(f"oauth code missing: {payload}")
        return oauth_code

    async def async_get_authorization(self, oauth_code: str) -> dict[str, Any]:
        path = "/auth/account/session/secure"
        query_param = "identity_type=geelygalaxy"
        url = f"{self.XCHANGER_USER_BASE_URL}{path}?{query_param}"
        json_body = {"authCode": oauth_code}
        body_md5 = self._content_md5_from_json_body(json_body)
        headers = self._build_xchanger_headers(
            method="POST",
            host=self.XCHANGER_USER_BASE_URL.replace("https://", ""),
            path=path,
            query_param=query_param,
            body_md5_base64=body_md5,
            authorization=None,
        )
        status, payload = await self._async_request("POST", url, headers, json_body)
        if status != 200 or payload.get("success") is not True or payload.get("code") != 1000:
            raise RuntimeError(f"get authorization failed: {payload}")

        data = payload.get("data") or {}
        access_token = data.get("accessToken")
        user_id = data.get("userId")
        expires_in = data.get("expiresIn")
        if not access_token or not user_id or not isinstance(expires_in, int):
            raise RuntimeError(f"authorization payload invalid: {payload}")

        return {
            "access_token": access_token,
            "user_id": user_id,
            "expires_at": int(time.time()) + expires_in,
        }

    async def async_get_vehicle_detailed_status(
        self,
        *,
        vehicle_id: str,
        user_id: str,
        authorization: str,
    ) -> dict[str, Any]:
        path = f"/remote-control/vehicle/status/{vehicle_id}"
        query_param = f"latest=&target=&userId={quote(user_id, safe='')}"
        url = f"{self.XCHANGER_DEVICE_BASE_URL}{path}?{query_param}"
        body_md5 = self._content_md5_from_text("")
        headers = self._build_xchanger_headers(
            method="GET",
            host=self.XCHANGER_DEVICE_BASE_URL.replace("https://", ""),
            path=path,
            query_param=query_param,
            body_md5_base64=body_md5,
            authorization=authorization,
        )
        status, payload = await self._async_request("GET", url, headers)
        code = payload.get("code")
        if status != 200 or payload.get("success") is not True or str(code) != "1000":
            raise RuntimeError(f"get vehicle detailed status failed: {payload}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError(f"vehicle detailed status payload invalid: {payload}")
        return data
