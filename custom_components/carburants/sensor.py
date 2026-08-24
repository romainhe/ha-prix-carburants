"""Sensor platform for Carburants."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CarburantsConfigEntry
from .const import FUELS, last_update_unique_id, price_unique_id
from .coordinator import CarburantsCoordinator
from .entity import CarburantsStationEntity

FUEL_ICONS = {
    "gazole": "mdi:fuel",
    "sp95": "mdi:fuel",
    "sp98": "mdi:fuel",
    "e10": "mdi:fuel",
    "e85": "mdi:leaf",
    "gplc": "mdi:gas-cylinder",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CarburantsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for every configured station."""
    coordinator = entry.runtime_data.coordinator

    entities: list[SensorEntity] = []
    for station_id, station in coordinator.data.items():
        entities.append(CarburantsLastUpdateSensor(coordinator, station_id))
        entities.extend(
            CarburantsFuelPriceSensor(coordinator, station_id, fuel)
            for fuel in station.tracked_fuels
        )

    async_add_entities(entities)


class CarburantsFuelPriceSensor(CarburantsStationEntity, SensorEntity):
    """Price of one fuel at one station."""

    _attr_native_unit_of_measurement = "€/L"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 3

    def __init__(
        self, coordinator: CarburantsCoordinator, station_id: str, fuel: str
    ) -> None:
        """Initialise the price sensor."""
        super().__init__(coordinator, station_id, price_unique_id(station_id, fuel))
        self._fuel = fuel
        self._attr_translation_key = fuel
        self._attr_icon = FUEL_ICONS.get(fuel, "mdi:fuel")

    @property
    def native_value(self) -> float | None:
        """Return the current price, or None while out of stock."""
        station = self.station
        if station is None:
            return None
        state = station.fuels.get(self._fuel)
        return state.price if state else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the price timestamp and the station id."""
        station = self.station
        if station is None:
            return {}
        state = station.fuels.get(self._fuel)
        return {
            "station_id": station.id,
            "fuel_label": FUELS[self._fuel],
            "updated_at": (
                state.updated_at.isoformat() if state and state.updated_at else None
            ),
        }


class CarburantsLastUpdateSensor(CarburantsStationEntity, SensorEntity):
    """Most recent price update across all fuels of a station."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_update"

    def __init__(self, coordinator: CarburantsCoordinator, station_id: str) -> None:
        """Initialise the diagnostic sensor."""
        super().__init__(coordinator, station_id, last_update_unique_id(station_id))

    @property
    def native_value(self) -> datetime | None:
        """Return the most recent update timestamp."""
        station = self.station
        return station.last_update if station else None
