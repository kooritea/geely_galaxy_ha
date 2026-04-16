"""Geely Galaxy integration constants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntityDescription,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.components.button import ButtonEntityDescription

DOMAIN = "geely_galaxy_ha"

CONF_REFRESH_TOKEN = "refresh_token"
CONF_HARDWARE_DEVICE_ID = "hardware_device_id"
CONF_TOKEN = "token"
CONF_TOKEN_EXPIRES_AT = "token_expires_at"
CONF_VEHICLE_AUTHORIZATIONS = "vehicle_authorizations"

SESSIONS_STORE_DIR = ".storage/geely_galaxy_ha"
SESSIONS_STORE_FILE = "sessions.json"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=10)
DEFAULT_VEHICLE_STATUS_INTERVAL = timedelta(minutes=1)

API_KEY_REFRESH = "204179735"
API_KEY_VEHICLE_LIST = "204373120"


# ---------------------------------------------------------------------------
# Helper: path-based accessor for nested vehicleStatus dict
# ---------------------------------------------------------------------------

def _get_nested(data: dict[str, Any], path: str) -> Any:
    """Get a nested value from a dict using dot-separated path."""
    keys = path.split(".")
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
        if data is None:
            return None
    return data


# ---------------------------------------------------------------------------
# Sensor entity descriptions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class GeelyVehicleSensorDescription(SensorEntityDescription):
    """Describe a Geely vehicle sensor."""

    data_path: str  # dot-separated path under vehicleStatus
    value_map: dict[str, str] | None = None  # 原始值 → 显示键的映射


VEHICLE_SENSOR_DESCRIPTIONS: tuple[GeelyVehicleSensorDescription, ...] = (
    # -- 基础车辆状态 --
    GeelyVehicleSensorDescription(
        key="distance_to_empty",
        translation_key="distance_to_empty",
        data_path="basicVehicleStatus.distanceToEmpty",
        native_unit_of_measurement="km",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
    ),
    GeelyVehicleSensorDescription(
        key="speed",
        translation_key="speed",
        data_path="basicVehicleStatus.speed",
        native_unit_of_measurement="km/h",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
    ),
    GeelyVehicleSensorDescription(
        key="direction",
        translation_key="direction",
        data_path="basicVehicleStatus.direction",
        icon="mdi:compass",
    ),
    # -- 保养信息 --
    GeelyVehicleSensorDescription(
        key="odometer",
        translation_key="odometer",
        data_path="additionalVehicleStatus.maintenanceStatus.odometer",
        native_unit_of_measurement="km",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
    ),
    GeelyVehicleSensorDescription(
        key="distance_to_service",
        translation_key="distance_to_service",
        data_path="additionalVehicleStatus.maintenanceStatus.distanceToService",
        native_unit_of_measurement="km",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:wrench-clock",
    ),
    GeelyVehicleSensorDescription(
        key="brake_fluid_level_status",
        translation_key="brake_fluid_level_status",
        data_path="additionalVehicleStatus.maintenanceStatus.brakeFluidLevelStatus",
        icon="mdi:car-brake-fluid-level",
    ),
    GeelyVehicleSensorDescription(
        key="service_warning_status",
        translation_key="service_warning_status",
        data_path="additionalVehicleStatus.maintenanceStatus.serviceWarningStatus",
        icon="mdi:car-wrench",
    ),
    # -- 电池状态 --
    GeelyVehicleSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        data_path="additionalVehicleStatus.maintenanceStatus.mainBatteryStatus.voltage",
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:car-battery",
    ),
    # -- 电动车状态 --
    GeelyVehicleSensorDescription(
        key="charge_level",
        translation_key="charge_level",
        data_path="additionalVehicleStatus.electricVehicleStatus.chargeLevel",
        native_unit_of_measurement="%",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    GeelyVehicleSensorDescription(
        key="aver_power_consumption",
        translation_key="aver_power_consumption",
        data_path="additionalVehicleStatus.electricVehicleStatus.averPowerConsumption",
        native_unit_of_measurement="kWh/100km",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash",
    ),
    GeelyVehicleSensorDescription(
        key="distance_to_empty_on_battery_only",
        translation_key="distance_to_empty_on_battery_only",
        data_path="additionalVehicleStatus.electricVehicleStatus.distanceToEmptyOnBatteryOnly",
        native_unit_of_measurement="km",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-arrow-down",
    ),
    GeelyVehicleSensorDescription(
        key="time_to_fully_charged",
        translation_key="time_to_fully_charged",
        data_path="additionalVehicleStatus.electricVehicleStatus.timeToFullyCharged",
        native_unit_of_measurement="min",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-clock",
    ),
    GeelyVehicleSensorDescription(
        key="state_of_charge",
        translation_key="state_of_charge",
        data_path="additionalVehicleStatus.electricVehicleStatus.stateOfCharge",
        icon="mdi:battery-charging",
    ),
    GeelyVehicleSensorDescription(
        key="status_of_charger_connection",
        translation_key="status_of_charger_connection",
        data_path="additionalVehicleStatus.electricVehicleStatus.statusOfChargerConnection",
        icon="mdi:ev-plug-type2",
    ),
    GeelyVehicleSensorDescription(
        key="charge_led_ctrl",
        translation_key="charge_led_ctrl",
        data_path="additionalVehicleStatus.electricVehicleStatus.chargeLEDCtrl",
        icon="mdi:led-on",
    ),
    GeelyVehicleSensorDescription(
        key="charge_hv_sts",
        translation_key="charge_hv_sts",
        data_path="additionalVehicleStatus.chargeHvSts",
        icon="mdi:battery-high",
    ),
    # -- 驾驶行为状态 --
    GeelyVehicleSensorDescription(
        key="cruise_control_status",
        translation_key="cruise_control_status",
        data_path="additionalVehicleStatus.drivingBehaviourStatus.cruiseControlStatus",
        icon="mdi:car-cruise-control",
    ),
    GeelyVehicleSensorDescription(
        key="transimission_gear_position",
        translation_key="transimission_gear_position",
        data_path="additionalVehicleStatus.drivingBehaviourStatus.transimissionGearPostion",
        device_class=SensorDeviceClass.ENUM,
        options=["drive", "reverse", "neutral", "park"],
        value_map={"1": "drive", "2": "reverse", "3": "neutral", "4": "park"},
        icon="mdi:car-shift-pattern",
    ),
    GeelyVehicleSensorDescription(
        key="engine_speed",
        translation_key="engine_speed",
        data_path="additionalVehicleStatus.drivingBehaviourStatus.engineSpeed",
        native_unit_of_measurement="RPM",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:engine",
    ),
    # -- 运行状态 --
    GeelyVehicleSensorDescription(
        key="avg_speed",
        translation_key="avg_speed",
        data_path="additionalVehicleStatus.runningStatus.avgSpeed",
        native_unit_of_measurement="km/h",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer-medium",
    ),
    # -- 配置信息 --
    GeelyVehicleSensorDescription(
        key="fuel_type",
        translation_key="fuel_type",
        data_path="configuration.fuelType",
        icon="mdi:fuel",
    ),
    # -- 时间 --
    GeelyVehicleSensorDescription(
        key="update_time",
        translation_key="update_time",
        data_path="updateTime",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
    ),
)


# ---------------------------------------------------------------------------
# Binary sensor entity descriptions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class GeelyVehicleBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a Geely vehicle binary sensor."""

    data_path: str  # dot-separated path under vehicleStatus
    on_value: str = "1"  # value that means "on" / "true" / "open" / "unlocked"


VEHICLE_BINARY_SENSOR_DESCRIPTIONS: tuple[GeelyVehicleBinarySensorDescription, ...] = (
    # -- 门锁状态 (locked=1, unlocked=0) → is_on 表示"未上锁"，即 on_value="0" --
    GeelyVehicleBinarySensorDescription(
        key="door_lock_status_driver",
        translation_key="door_lock_status_driver",
        data_path="additionalVehicleStatus.drivingSafetyStatus.doorLockStatusDriver",
        device_class=BinarySensorDeviceClass.LOCK,
        on_value="0",  # "0"=未上锁 → is_on=True (unlocked)
        icon="mdi:car-door-lock",
    ),
    GeelyVehicleBinarySensorDescription(
        key="door_lock_status_passenger",
        translation_key="door_lock_status_passenger",
        data_path="additionalVehicleStatus.drivingSafetyStatus.doorLockStatusPassenger",
        device_class=BinarySensorDeviceClass.LOCK,
        on_value="0",
        icon="mdi:car-door-lock",
    ),
    GeelyVehicleBinarySensorDescription(
        key="door_lock_status_driver_rear",
        translation_key="door_lock_status_driver_rear",
        data_path="additionalVehicleStatus.drivingSafetyStatus.doorLockStatusDriverRear",
        device_class=BinarySensorDeviceClass.LOCK,
        on_value="0",
        icon="mdi:car-door-lock",
    ),
    GeelyVehicleBinarySensorDescription(
        key="door_lock_status_passenger_rear",
        translation_key="door_lock_status_passenger_rear",
        data_path="additionalVehicleStatus.drivingSafetyStatus.doorLockStatusPassengerRear",
        device_class=BinarySensorDeviceClass.LOCK,
        on_value="0",
        icon="mdi:car-door-lock",
    ),
    # -- 门开关状态 (open=1, closed=0) --
    GeelyVehicleBinarySensorDescription(
        key="door_open_status_driver",
        translation_key="door_open_status_driver",
        data_path="additionalVehicleStatus.drivingSafetyStatus.doorOpenStatusDriver",
        device_class=BinarySensorDeviceClass.DOOR,
        on_value="1",  # "1"=打开 → is_on=True
        icon="mdi:car-door",
    ),
    GeelyVehicleBinarySensorDescription(
        key="door_open_status_passenger",
        translation_key="door_open_status_passenger",
        data_path="additionalVehicleStatus.drivingSafetyStatus.doorOpenStatusPassenger",
        device_class=BinarySensorDeviceClass.DOOR,
        on_value="1",
        icon="mdi:car-door",
    ),
    # -- 后备箱状态 --
    GeelyVehicleBinarySensorDescription(
        key="trunk_open_status",
        translation_key="trunk_open_status",
        data_path="additionalVehicleStatus.drivingSafetyStatus.trunkOpenStatus",
        device_class=BinarySensorDeviceClass.OPENING,
        on_value="1",  # "1"=开启
        icon="mdi:car-back",
    ),
    # -- 手刹状态 (handBrakeStatus: "1"=拉起, "0"=放下 → 视为 engaged) --
    GeelyVehicleBinarySensorDescription(
        key="hand_brake_status",
        translation_key="hand_brake_status",
        data_path="additionalVehicleStatus.drivingSafetyStatus.handBrakeStatus",
        on_value="1",  # "1"=拉起手刹 → is_on=True (engaged)
        icon="mdi:car-brake-parking",
    ),
    # -- 电子驻车状态 --
    GeelyVehicleBinarySensorDescription(
        key="electric_park_brake_status",
        translation_key="electric_park_brake_status",
        data_path="additionalVehicleStatus.drivingSafetyStatus.electricParkBrakeStatus",
        on_value="0",  # "0"=驻车 → is_on=True (engaged)
        icon="mdi:car-brake-parking",
    ),
    # -- 安全带状态 --
    GeelyVehicleBinarySensorDescription(
        key="seat_belt_status_driver",
        translation_key="seat_belt_status_driver",
        data_path="additionalVehicleStatus.drivingSafetyStatus.seatBeltStatusDriver",
        on_value="false",  # "true"=未系带, "false"=已系带
        icon="mdi:seatbelt",
    ),
    # -- 防盗报警 --
    GeelyVehicleBinarySensorDescription(
        key="vehicle_alarm",
        translation_key="vehicle_alarm",
        data_path="additionalVehicleStatus.drivingSafetyStatus.vehicleAlarm",
        device_class=BinarySensorDeviceClass.SAFETY,
        on_value="1",  # "1"=开启, "0"=关闭
        icon="mdi:alarm-light",
    ),
    # -- 充电状态 --
    GeelyVehicleBinarySensorDescription(
        key="is_charging",
        translation_key="is_charging",
        data_path="additionalVehicleStatus.electricVehicleStatus.isCharging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        on_value="true",
        icon="mdi:battery-charging",
    ),
    GeelyVehicleBinarySensorDescription(
        key="is_plugged_in",
        translation_key="is_plugged_in",
        data_path="additionalVehicleStatus.electricVehicleStatus.isPluggedIn",
        device_class=BinarySensorDeviceClass.PLUG,
        on_value="true",
        icon="mdi:ev-plug-type2",
    ),
    # -- EV 就绪状态 --
    GeelyVehicleBinarySensorDescription(
        key="pt_ready",
        translation_key="pt_ready",
        data_path="additionalVehicleStatus.electricVehicleStatus.ptReady",
        on_value="1",  # "1"=就绪
        icon="mdi:car-electric",
    ),
    # -- 刹车踏板 --
    GeelyVehicleBinarySensorDescription(
        key="brake_pedal_depressed",
        translation_key="brake_pedal_depressed",
        data_path="additionalVehicleStatus.drivingBehaviourStatus.brakePedalDepressed",
        on_value="true",
        icon="mdi:car-brake-alert",
    ),
    # -- 空调预启动 --
    GeelyVehicleBinarySensorDescription(
        key="pre_climate_active",
        translation_key="pre_climate_active",
        data_path="additionalVehicleStatus.climateStatus.preClimateActive",
        on_value="true",  # boolean or "true"
        icon="mdi:air-conditioner",
    ),
    # -- 车辆阻止状态 --
    GeelyVehicleBinarySensorDescription(
        key="eg_blocked_status",
        translation_key="eg_blocked_status",
        data_path="eg.blocked.status",
        on_value="1",
        icon="mdi:car-off",
    ),
)


# ---------------------------------------------------------------------------
# Remote control constants
# ---------------------------------------------------------------------------

REMOTE_SERVICE_RCE = "RCE"
REMOTE_SERVICE_RDU = "RDU"
REMOTE_SERVICE_RDL = "RDL"
REMOTE_SERVICE_RTU = "RTU"
REMOTE_SERVICE_RHL = "RHL"


# ---------------------------------------------------------------------------
# Switch and button entity descriptions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class GeelyVehicleSwitchDescription(SwitchEntityDescription):
    """Describe a Geely vehicle remote switch."""

    service_type: str


@dataclass(frozen=True, kw_only=True)
class GeelyVehicleButtonDescription(ButtonEntityDescription):
    """Describe a Geely vehicle button."""

    service_type: str


VEHICLE_SWITCH_DESCRIPTIONS: tuple[GeelyVehicleSwitchDescription, ...] = (
    GeelyVehicleSwitchDescription(
        key="door_switch",
        translation_key="door_switch",
        icon="mdi:car-door-lock",
        service_type="door",
    ),
    GeelyVehicleSwitchDescription(
        key="trunk_switch",
        translation_key="trunk_switch",
        icon="mdi:car-back",
        service_type="trunk",
    ),
)


VEHICLE_BUTTON_DESCRIPTIONS: tuple[GeelyVehicleButtonDescription, ...] = (
    GeelyVehicleButtonDescription(
        key="find_car",
        translation_key="find_car",
        icon="mdi:car-search",
        service_type="find_car",
    ),
)
