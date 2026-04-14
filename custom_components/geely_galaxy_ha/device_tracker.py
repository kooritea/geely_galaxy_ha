"""Device tracker platform for Geely Galaxy — shows vehicle on the HA map."""

from __future__ import annotations

import logging
import math
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, _get_nested

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GCJ-02 → WGS-84 coordinate conversion (China offset removal)
# ---------------------------------------------------------------------------
# 中国地图使用 GCJ-02（火星坐标系），Home Assistant 使用 WGS-84。
# 当 API 返回 GCJ-02 坐标时需要转换为 WGS-84，否则在 HA 地图上会有
# 100-700 米偏移。

_GCJ_A = 6378245.0  # 长半轴
_GCJ_EE = 0.00669342162296594  # 偏心率平方


def _out_of_china(lat: float, lng: float) -> bool:
    """Check if coordinate is outside China (no transform needed)."""
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(x: float, y: float) -> float:
    ret = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
    )
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * math.sqrt(abs(x))
    )
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lat: float, lng: float) -> tuple[float, float]:
    """Convert GCJ-02 (Mars) coordinates to WGS-84."""
    if _out_of_china(lat, lng):
        return lat, lng
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _GCJ_EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_GCJ_A * (1 - _GCJ_EE)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (_GCJ_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return round(lat - d_lat, 6), round(lng - d_lng, 6)


class GeelyVehicleTracker(TrackerEntity):
    """Represent vehicle location on the Home Assistant map."""

    _attr_has_entity_name = True

    def __init__(
        self,
        vehicle: dict,
        entry_id: str,
        coordinator: Any,
    ) -> None:
        self._coordinator = coordinator
        self._vin = vehicle.get("vin", "unknown")
        name = vehicle.get("carName") or vehicle.get("seriesNameVs") or self._vin
        self._attr_translation_key = "vehicle_location"
        self._attr_unique_id = f"{entry_id}_{self._vin}_device_tracker"
        self._attr_icon = "mdi:car"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            name=name,
            model=vehicle.get("modelName") or vehicle.get("seriesName"),
            manufacturer="Geely",
            serial_number=self._vin,
            configuration_url="https://galaxy-app.geely.com",
        )

    # ------------------------------------------------------------------
    # TrackerEntity required properties
    # ------------------------------------------------------------------

    @property
    def source_type(self) -> SourceType:
        """Return the source type (GPS)."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return latitude in WGS-84.

        API returns value in milli-arcseconds (degrees × 3600 × 1000).
        If marsCoordinates is true, converts from GCJ-02 to WGS-84.
        """
        coords = self._get_converted_coordinates()
        return coords[0] if coords else None

    @property
    def longitude(self) -> float | None:
        """Return longitude in WGS-84.

        API returns value in milli-arcseconds (degrees × 3600 × 1000).
        If marsCoordinates is true, converts from GCJ-02 to WGS-84.
        """
        coords = self._get_converted_coordinates()
        return coords[1] if coords else None

    @property
    def location_accuracy(self) -> float:
        """Return GPS accuracy — not provided by the API, default 0."""
        return 0

    @property
    def battery_level(self) -> int | None:
        """Return battery charge level %."""
        vehicle_status = self._vehicle_status()
        raw = _get_nested(vehicle_status, "additionalVehicleStatus.electricVehicleStatus.chargeLevel")
        if raw is None:
            return None
        try:
            return int(float(raw))
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional position attributes for the map card."""
        vehicle_status = self._vehicle_status()
        attrs: dict[str, Any] = {}

        altitude = _get_nested(vehicle_status, "basicVehicleStatus.position.altitude")
        if altitude is not None:
            attrs["altitude"] = altitude

        speed = _get_nested(vehicle_status, "basicVehicleStatus.speed")
        if speed is not None:
            attrs["speed"] = speed

        direction = _get_nested(vehicle_status, "basicVehicleStatus.direction")
        if direction is not None:
            attrs["direction"] = direction

        pos_trusted = _get_nested(vehicle_status, "basicVehicleStatus.position.posCanBeTrusted")
        if pos_trusted is not None:
            attrs["position_can_be_trusted"] = pos_trusted

        mars_coords = _get_nested(vehicle_status, "basicVehicleStatus.position.marsCoordinates")
        if mars_coords is not None:
            attrs["mars_coordinates"] = mars_coords
        attrs["coordinate_system"] = "GCJ-02 → WGS-84" if self._is_mars_coordinates() else "WGS-84"

        return attrs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _vehicle_status(self) -> dict[str, Any]:
        """Get vehicleStatus subtree from coordinator."""
        detailed = self._coordinator.get_vehicle_status_attributes(self._vin)
        if not isinstance(detailed, dict):
            return {}
        vs = detailed.get("vehicleStatus", {})
        return vs if isinstance(vs, dict) else {}

    def _get_position_field(self, field: str) -> Any:
        """Get a single field from basicVehicleStatus.position."""
        return _get_nested(
            self._vehicle_status(),
            f"basicVehicleStatus.position.{field}",
        )

    def _is_mars_coordinates(self) -> bool:
        """Check if coordinates are in GCJ-02 (Mars coordinate system).

        marsCoordinates == "true" → GCJ-02, needs conversion to WGS-84
        marsCoordinates == "false" → WGS-84, no conversion needed
        If field is missing, assume GCJ-02 for Chinese vehicles (safe default).
        """
        raw = self._get_position_field("marsCoordinates")
        if raw is None:
            # 字段缺失时，中国车辆默认假定为 GCJ-02
            return True
        return str(raw).lower() == "true"

    def _get_converted_coordinates(self) -> tuple[float, float] | None:
        """Get latitude and longitude, converting from GCJ-02 to WGS-84 if needed.

        Conversion flow:
        1. Raw value ÷ 3_600_000 (milli-arcseconds → degrees)
        2. If marsCoordinates is true (or missing): convert GCJ-02 → WGS-84
        3. If marsCoordinates is false: already WGS-84, no conversion
        """
        raw_lat = self._get_position_field("latitude")
        raw_lng = self._get_position_field("longitude")
        if raw_lat is None or raw_lng is None:
            return None
        try:
            lat = float(raw_lat) / 3_600_000
            lng = float(raw_lng) / 3_600_000
        except (ValueError, TypeError):
            return None

        if self._is_mars_coordinates():
            lat, lng = gcj02_to_wgs84(lat, lng)

        return round(lat, 6), round(lng, 6)

    async def async_added_to_hass(self) -> None:
        """Start listening for coordinator updates."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Geely Galaxy device tracker from config entry."""
    _LOGGER.info("开始 setup device_tracker entry，entry_id=%s", entry.entry_id)
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    vehicles = coordinator.data or []
    valid_vehicles = [vehicle for vehicle in vehicles if vehicle.get("vin")]

    entities = [
        GeelyVehicleTracker(vehicle, entry.entry_id, coordinator)
        for vehicle in valid_vehicles
    ]

    _LOGGER.info(
        "device_tracker 实体构建完成，entry_id=%s，entity_count=%s",
        entry.entry_id, len(entities),
    )
    async_add_entities(entities)
