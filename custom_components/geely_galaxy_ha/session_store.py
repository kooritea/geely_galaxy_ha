"""Session credential storage for Geely Galaxy integration."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from .const import SESSIONS_STORE_DIR, SESSIONS_STORE_FILE


class SessionStore:
    """Persist credentials in .storage/geely_galaxy_ha/sessions.json."""

    def __init__(self, hass: Any) -> None:
        self._path = Path(hass.config.path(SESSIONS_STORE_DIR, SESSIONS_STORE_FILE))
        self._lock = asyncio.Lock()

    async def async_load(self, hardware_device_id: str) -> dict[str, Any] | None:
        payload = await self._async_read_all()
        session = payload.get("sessions", {}).get(hardware_device_id)
        if not isinstance(session, dict):
            return None
        return session

    async def async_save(self, hardware_device_id: str, partial: dict[str, Any]) -> None:
        async with self._lock:
            payload = await self._async_read_all()
            sessions = payload.setdefault("sessions", {})
            current = sessions.get(hardware_device_id) or {}
            merged = dict(current)
            merged.update(partial)
            sessions[hardware_device_id] = merged
            await self._async_write_all(payload)

    async def _async_read_all(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._read_all_sync)

    def _read_all_sync(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"sessions": {}}
        try:
            text = self._path.read_text(encoding="utf-8")
            payload = json.loads(text)
        except json.JSONDecodeError as err:
            raise RuntimeError(f"invalid sessions store json: {err}") from err

        if not isinstance(payload, dict):
            raise RuntimeError("invalid sessions store payload")

        sessions = payload.get("sessions")
        if sessions is None:
            payload["sessions"] = {}
        elif not isinstance(sessions, dict):
            raise RuntimeError("invalid sessions store sessions field")

        return payload

    async def _async_write_all(self, payload: dict[str, Any]) -> None:
        await asyncio.to_thread(self._write_all_sync, payload)

    def _write_all_sync(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp_path.replace(self._path)
