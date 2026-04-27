"""Data update coordinator for Geely Galaxy integration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GeelyGalaxyApiClient
from .const import (
    CONF_VEHICLE_AUTHORIZATIONS,
    DEFAULT_VEHICLE_STATUS_INTERVAL,
    DOMAIN,
    PT_READY_VEHICLE_STATUS_INTERVAL,
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
            update_interval=None,
        )
        self.client = client
        self._persist_vehicle_authorizations_cb = persist_vehicle_authorizations_cb
        self.vehicle_authorizations: dict[str, dict[str, Any]] = persisted_vehicle_authorizations or {}
        self.vehicle_status_by_vin: dict[str, dict[str, Any]] = {}
        self._authorization_refresh_lock = asyncio.Lock()
        self._last_authorization_refresh_at = 0
        self._refresh_cooldown_seconds = 60
        self._last_auth_refresh_warning_at = 0
        self._vehicle_last_polled_at: dict[str, float] = {}
        self._vehicle_poll_interval_sources_by_vin: dict[str, dict[str, int]] = {}
        self._vehicle_poll_timer_handles: dict[str, asyncio.TimerHandle] = {}
        self._vehicle_next_poll_at: dict[str, float] = {}
        self._vehicle_poll_generation: dict[str, int] = {}
        self._vehicle_poll_inflight: set[str] = set()
        self._poll_entry: ConfigEntry | None = None

        # 快速轮询状态
        self._rapid_poll_vins: set[str] = set()
        self._rapid_poll_tasks: dict[str, asyncio.Task] = {}
        self._rapid_poll_watchers: dict[str, dict[str, _RapidPollWatcher]] = {}

    async def _async_update_data(self) -> list[dict[str, Any]]:
        try:
            vehicles = await self.client.async_get_vehicle_list()

            if self._poll_entry is not None:
                now = self._get_current_timestamp()
                for vehicle in vehicles:
                    vin = vehicle.get("vin")
                    if not vin:
                        continue
                    if vin in self._vehicle_poll_timer_handles or vin in self._vehicle_poll_inflight:
                        continue
                    self._schedule_vehicle_poll(vin, self._poll_entry, now)
                    _LOGGER.debug("检测到新车辆并启动状态轮询 vin=%s", vin)

            return vehicles
        except Exception as err:
            raise UpdateFailed(f"Failed to update Geely vehicles: {err}") from err

    async def async_start_vehicle_status_polling(self, entry: ConfigEntry) -> None:
        if self._poll_entry is not None:
            return

        if not self.data:
            vehicles = await self._async_update_data()
            self.data = vehicles
        else:
            vehicles = self.data

        self._poll_entry = entry

        now = self._get_current_timestamp()
        for vehicle in vehicles:
            vin = vehicle.get("vin")
            if not vin:
                continue
            self._schedule_vehicle_poll(vin, entry, now)

    async def async_stop(self) -> None:
        for vin in list(self._vehicle_poll_timer_handles):
            self._cancel_vehicle_poll(vin)
        self._vehicle_next_poll_at.clear()
        self._vehicle_poll_inflight.clear()
        self._poll_entry = None

    async def async_poll_vehicle_status(self, entry: ConfigEntry) -> None:
        vehicles = self.data or []
        if not vehicles:
            return

        await self._async_refresh_vehicle_authorizations_if_needed(vehicles, entry)

        now = self._get_current_timestamp()
        changed = False
        for vehicle in vehicles:
            vin = vehicle.get("vin")
            if not vin:
                continue
            should_poll_now = self._update_vehicle_poll_intervals(vin, now)
            if not should_poll_now:
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
                _LOGGER.debug("车辆状态轮询成功 vin=%s", vin)
            except Exception as err:
                _LOGGER.debug("车辆状态轮询失败 vin=%s err=%s", vin, err)
            finally:
                self._mark_vehicle_polled(vin, now)

        if changed:
            self.async_update_listeners()

    def _get_current_timestamp(self) -> float:
        return datetime.now(UTC).timestamp()

    def _is_pt_ready(self, vin: str) -> bool:
        status = self.vehicle_status_by_vin.get(vin, {})
        pt_ready = (
            status.get("vehicleStatus", {})
            .get("additionalVehicleStatus", {})
            .get("electricVehicleStatus", {})
            .get("ptReady")
        )
        return str(pt_ready) == "1"

    def _get_effective_vehicle_poll_interval_seconds(self, vin: str) -> int:
        return min(
            self._vehicle_poll_interval_sources_by_vin.get(
                vin,
                {"default": int(DEFAULT_VEHICLE_STATUS_INTERVAL.total_seconds())},
            ).values()
        )

    def _build_vehicle_poll_interval_sources(self, vin: str) -> dict[str, int]:
        interval_sources = {"default": int(DEFAULT_VEHICLE_STATUS_INTERVAL.total_seconds())}
        if self._is_pt_ready(vin):
            interval_sources["pt_ready"] = int(PT_READY_VEHICLE_STATUS_INTERVAL.total_seconds())
        if vin in self._rapid_poll_vins:
            interval_sources["rapid"] = _RAPID_POLL_INTERVAL
        return interval_sources

    def _is_vehicle_due(self, vin: str, now: float) -> bool:
        last_polled_at = self._vehicle_last_polled_at.get(vin)
        if last_polled_at is None:
            return True
        interval_seconds = self._get_effective_vehicle_poll_interval_seconds(vin)
        return now - last_polled_at >= interval_seconds

    def _update_vehicle_poll_intervals(self, vin: str, now: float) -> bool:
        self._vehicle_poll_interval_sources_by_vin[vin] = self._build_vehicle_poll_interval_sources(vin)
        return self._is_vehicle_due(vin, now)

    def _mark_vehicle_polled(self, vin: str, now: float) -> None:
        self._vehicle_last_polled_at[vin] = now

    def _cancel_vehicle_poll(self, vin: str) -> None:
        handle = self._vehicle_poll_timer_handles.pop(vin, None)
        if handle is not None:
            handle.cancel()

    def _schedule_vehicle_poll(self, vin: str, entry: ConfigEntry, due_at: float) -> None:
        self._cancel_vehicle_poll(vin)
        now = self._get_current_timestamp()
        delay = max(0.0, due_at - now)
        generation = self._vehicle_poll_generation.get(vin, 0) + 1
        self._vehicle_poll_generation[vin] = generation
        self._vehicle_next_poll_at[vin] = due_at

        def _timer_callback() -> None:
            if hasattr(self.hass, "async_create_task"):
                self.hass.async_create_task(
                    self._async_on_vehicle_poll_timer(vin, entry, generation),
                    f"geely_vehicle_poll_{vin}",
                )
            else:
                asyncio.create_task(self._async_on_vehicle_poll_timer(vin, entry, generation))

        self._vehicle_poll_timer_handles[vin] = asyncio.get_running_loop().call_later(delay, _timer_callback)

    def _reschedule_vehicle_poll(self, vin: str, entry: ConfigEntry, now: float, force: bool = False) -> None:
        self._update_vehicle_poll_intervals(vin, now)
        last_polled_at = self._vehicle_last_polled_at.get(vin)
        interval_seconds = self._get_effective_vehicle_poll_interval_seconds(vin)
        due_at = now if last_polled_at is None else (last_polled_at + interval_seconds)

        current_due_at = self._vehicle_next_poll_at.get(vin)
        if not force and current_due_at is not None and abs(current_due_at - due_at) < 1e-6:
            return

        self._schedule_vehicle_poll(vin, entry, due_at)

    async def _async_poll_single_vehicle_regular(self, vin: str, entry: ConfigEntry) -> bool:
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
            changed = self.vehicle_status_by_vin.get(vin) != detailed
            if changed:
                self.vehicle_status_by_vin[vin] = detailed
                _LOGGER.debug("车辆状态轮询成功 vin=%s", vin)
                return True
            _LOGGER.debug("车辆状态轮询成功 vin=%s", vin)
            return False
        except Exception as err:
            _LOGGER.warning("车辆状态轮询失败 vin=%s err=%s", vin, err)
            return False

    async def _async_on_vehicle_poll_timer(self, vin: str, entry: ConfigEntry, generation: int) -> None:
        self._vehicle_poll_timer_handles.pop(vin, None)

        current_generation = self._vehicle_poll_generation.get(vin)
        _LOGGER.debug(
            "车辆状态轮询定时器触发 vin=%s generation=%s current_generation=%s inflight=%s rapid=%s",
            vin,
            generation,
            current_generation,
            vin in self._vehicle_poll_inflight,
            vin in self._rapid_poll_vins,
        )
        if current_generation != generation:
            return
        if vin in self._rapid_poll_vins:
            return
        if vin in self._vehicle_poll_inflight:
            return

        now = self._get_current_timestamp()
        if not self._is_vehicle_due(vin, now):
            _LOGGER.debug("车辆状态轮询未到期，跳过执行 vin=%s now=%s", vin, now)
            self._reschedule_vehicle_poll(vin, entry, now)
            return

        self._vehicle_poll_inflight.add(vin)
        poll_now: float | None = None
        try:
            changed = await self._async_poll_single_vehicle_regular(vin, entry)
            poll_now = self._get_current_timestamp()
            self._mark_vehicle_polled(vin, poll_now)
            if changed:
                self.async_update_listeners()
        except Exception as err:
            _LOGGER.warning("车辆状态轮询处理异常 vin=%s err=%s", vin, err)
        finally:
            self._vehicle_poll_inflight.discard(vin)
            if self._vehicle_poll_generation.get(vin) == generation and vin not in self._rapid_poll_vins:
                if poll_now is None:
                    poll_now = self._get_current_timestamp()
                _LOGGER.debug("重排车辆状态轮询 vin=%s at=%s generation=%s", vin, poll_now, generation)
                self._reschedule_vehicle_poll(vin, entry, poll_now, force=True)
                _LOGGER.debug(
                    "车辆状态轮询已重排 vin=%s generation=%s next_due_at=%s",
                    vin,
                    generation,
                    self._vehicle_next_poll_at.get(vin),
                )

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
            changed = self.vehicle_status_by_vin.get(vin) != detailed
            if changed:
                self.vehicle_status_by_vin[vin] = detailed
                self.async_update_listeners()
                _LOGGER.debug("快速轮询状态有变化 vin=%s", vin)
            else:
                _LOGGER.debug("快速轮询状态无变化 vin=%s", vin)
            self._mark_vehicle_polled(vin, self._get_current_timestamp())
            return changed
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
            _LOGGER.debug("重启快速轮询 vin=%s switch=%s", vin, switch_key)
        else:
            self._rapid_poll_vins.add(vin)
            self._rapid_poll_watchers[vin] = {switch_key: watcher}
            _LOGGER.debug("启动快速轮询 vin=%s switch=%s", vin, switch_key)

        self._cancel_vehicle_poll(vin)

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
                    _LOGGER.debug("快速轮询完成（状态已变化） vin=%s", vin)
                    break

                # 请求完成后再等待，天然串行不会并发
                await asyncio.sleep(_RAPID_POLL_INTERVAL)
            else:
                _LOGGER.debug("快速轮询超时退出 vin=%s", vin)

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
                _LOGGER.debug(
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
        _LOGGER.debug("快速轮询已清理，恢复常规轮询 vin=%s", vin)

        if self._poll_entry is not None:
            self._reschedule_vehicle_poll(vin, self._poll_entry, self._get_current_timestamp(), force=True)

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
