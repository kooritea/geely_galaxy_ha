"""Data update coordinator for Geely Galaxy integration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

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

_RAPID_POLL_INITIAL_DELAY = 3  # 命令发送后等待秒数
_RAPID_POLL_INTERVAL = 3  # 快速轮询间隔秒数
_RAPID_POLL_TIMEOUT = 60  # 快速轮询最大持续秒数


@dataclass
class _RapidPollWatcher:
    """跟踪某个开关是否已达到预期状态变化。"""

    pre_command_value: bool | None
    check_fn: Callable[[dict[str, Any]], bool | None]


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

        # 快速轮询状态
        self._rapid_poll_vins: set[str] = set()
        self._rapid_poll_tasks: dict[str, asyncio.Task] = {}
        self._rapid_poll_watchers: dict[str, dict[str, _RapidPollWatcher]] = {}

    async def _async_update_data(self) -> list[dict[str, Any]]:
        try:
            vehicles = await self.client.async_get_vehicle_list()
            return vehicles
        except Exception as err:
            raise UpdateFailed(f"Failed to update Geely vehicles: {err}") from err

    async def async_start_vehicle_status_polling(self, entry: ConfigEntry) -> None:
        if self._status_poll_unsub is not None:
            return

        async def _poll(_now) -> None:
            await self.async_poll_vehicle_status(entry)

        self._status_poll_unsub = async_track_time_interval(
            self.hass,
            _poll,
            DEFAULT_VEHICLE_STATUS_INTERVAL,
        )

        # 立即获取一次车辆状态，消除启动后的空白等待期
        await self.async_poll_vehicle_status(entry)

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
            if vin in self._rapid_poll_vins:
                _LOGGER.debug("跳过快速轮询中的车辆 vin=%s", vin)
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

    # ------------------------------------------------------------------
    # 快速轮询：开关操作后针对单车的高频状态查询
    # ------------------------------------------------------------------

    async def async_poll_single_vehicle_status(
        self, vin: str, entry: ConfigEntry
    ) -> bool:
        """轮询单个 VIN 的车辆状态，返回 True 表示状态有变化。"""
        vehicles = self.data or []
        await self._async_refresh_vehicle_authorizations_if_needed(vehicles, entry)

        auth = self.vehicle_authorizations.get(vin)
        if not auth:
            return False
        access_token = auth.get("access_token")
        user_id = auth.get("user_id")
        if not access_token or not user_id:
            return False

        try:
            detailed = await self.client.async_get_vehicle_detailed_status(
                vehicle_id=vin,
                user_id=user_id,
                authorization=access_token,
            )
            if self.vehicle_status_by_vin.get(vin) != detailed:
                self.vehicle_status_by_vin[vin] = detailed
                self.async_update_listeners()
                _LOGGER.info("快速轮询状态有变化 vin=%s", vin)
                return True
            _LOGGER.debug("快速轮询状态无变化 vin=%s", vin)
            return False
        except Exception as err:
            _LOGGER.warning("快速轮询请求失败 vin=%s err=%s", vin, err)
            return False

    async def async_start_rapid_poll(
        self,
        vin: str,
        entry: ConfigEntry,
        switch_key: str,
        pre_command_value: bool | None,
        check_fn: Callable[[dict[str, Any]], bool | None],
    ) -> None:
        """开关操作后启动针对该 VIN 的快速轮询。

        如果该 VIN 已有快速轮询在运行，则追加 watcher 并重启循环。
        """
        watcher = _RapidPollWatcher(
            pre_command_value=pre_command_value,
            check_fn=check_fn,
        )

        if vin in self._rapid_poll_vins:
            # 已有快速轮询：追加/覆盖 watcher，取消旧任务重启
            self._rapid_poll_watchers.setdefault(vin, {})[switch_key] = watcher
            existing_task = self._rapid_poll_tasks.get(vin)
            if existing_task and not existing_task.done():
                existing_task.cancel()
            _LOGGER.info("重启快速轮询 vin=%s switch=%s", vin, switch_key)
        else:
            self._rapid_poll_vins.add(vin)
            self._rapid_poll_watchers[vin] = {switch_key: watcher}
            _LOGGER.info("启动快速轮询 vin=%s switch=%s", vin, switch_key)

        task = self.hass.async_create_task(
            self._async_rapid_poll_loop(vin, entry),
            f"geely_rapid_poll_{vin}",
        )
        self._rapid_poll_tasks[vin] = task

    async def _async_rapid_poll_loop(
        self, vin: str, entry: ConfigEntry
    ) -> None:
        """快速轮询内部循环，作为 asyncio.Task 运行。"""
        try:
            # 等待车辆处理指令
            await asyncio.sleep(_RAPID_POLL_INITIAL_DELAY)

            loop = asyncio.get_running_loop()
            deadline = loop.time() + _RAPID_POLL_TIMEOUT

            while loop.time() < deadline:
                changed = await self.async_poll_single_vehicle_status(vin, entry)

                # 每次轮询后都检查 watchers（不仅在整体状态变化时），
                # 避免极端情况下字段变化被其他字段变化抵消导致漏检
                self._check_and_remove_satisfied_watchers(vin)

                # 所有 watchers 都已满足，提前结束
                if not self._rapid_poll_watchers.get(vin):
                    _LOGGER.info("快速轮询完成（状态已变化） vin=%s", vin)
                    break

                # 请求完成后再等待，天然串行不会并发
                await asyncio.sleep(_RAPID_POLL_INTERVAL)
            else:
                _LOGGER.info("快速轮询超时退出 vin=%s", vin)

        except asyncio.CancelledError:
            # 被新命令取消重启，不清理 _rapid_poll_vins（新任务接管）
            _LOGGER.debug("快速轮询被取消（将由新任务接管） vin=%s", vin)
            return

        finally:
            # 仅当本 task 仍是当前有效 task 时才清理
            current_task = self._rapid_poll_tasks.get(vin)
            if current_task is asyncio.current_task():
                self._cleanup_rapid_poll(vin)

    def _check_and_remove_satisfied_watchers(self, vin: str) -> None:
        """检查并移除已满足状态变化条件的 watchers。"""
        watchers = self._rapid_poll_watchers.get(vin)
        if not watchers:
            return

        current_status = self.vehicle_status_by_vin.get(vin, {})
        satisfied_keys: list[str] = []

        for key, watcher in watchers.items():
            current_value = watcher.check_fn(current_status)
            if current_value is not None and current_value != watcher.pre_command_value:
                satisfied_keys.append(key)
                _LOGGER.info(
                    "开关状态已变化 vin=%s switch=%s: %s → %s",
                    vin, key, watcher.pre_command_value, current_value,
                )

        for key in satisfied_keys:
            del watchers[key]

    def _cleanup_rapid_poll(self, vin: str) -> None:
        """清理指定 VIN 的快速轮询状态，恢复常规轮询。"""
        self._rapid_poll_vins.discard(vin)
        self._rapid_poll_watchers.pop(vin, None)
        self._rapid_poll_tasks.pop(vin, None)
        _LOGGER.info("快速轮询已清理，恢复常规轮询 vin=%s", vin)

    async def async_cancel_all_rapid_polls(self) -> None:
        """取消所有活跃的快速轮询任务（集成卸载时调用）。"""
        for vin, task in list(self._rapid_poll_tasks.items()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            # task 的 finally 块已执行 _cleanup_rapid_poll，
            # 此处用 discard 做兜底确保清理干净
            self._rapid_poll_vins.discard(vin)

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
