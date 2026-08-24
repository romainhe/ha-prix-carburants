"""Binary sensor platform for Carburants."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from . import CarburantsConfigEntry
from .const import FUELS, open_unique_id, outage_unique_id
from .coordinator import CarburantsCoordinator
from .entity import CarburantsStationEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CarburantsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors for every configured station."""
    coordinator = entry.runtime_data.coordinator

    entities: list[BinarySensorEntity] = []
    for station_id, station in coordinator.data.items():
        entities.append(CarburantsOpenBinarySensor(coordinator, station_id))
        entities.extend(
            CarburantsFuelOutageBinarySensor(coordinator, station_id, fuel)
            for fuel in station.tracked_fuels
        )

    async_add_entities(entities)


class CarburantsFuelOutageBinarySensor(CarburantsStationEntity, BinarySensorEntity):
    """Out-of-stock flag for one fuel at one station."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator: CarburantsCoordinator, station_id: str, fuel: str
    ) -> None:
        """Initialise the outage sensor."""
        super().__init__(coordinator, station_id, outage_unique_id(station_id, fuel))
        self._fuel = fuel
        self._attr_translation_key = f"{fuel}_outage"

    @property
    def is_on(self) -> bool | None:
        """Return True when the fuel is currently out of stock."""
        station = self.station
        if station is None:
            return None
        state = station.fuels.get(self._fuel)
        return state.in_outage if state else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the outage type and start date."""
        station = self.station
        if station is None:
            return {}
        state = station.fuels.get(self._fuel)
        return {
            "station_id": station.id,
            "fuel_label": FUELS[self._fuel],
            "outage_type": state.outage_type if state else None,
            "since": (
                state.outage_since.isoformat() if state and state.outage_since else None
            ),
        }


class CarburantsOpenBinarySensor(CarburantsStationEntity, BinarySensorEntity):
    """Whether the station is open right now."""

    _attr_translation_key = "open"
    _attr_icon = "mdi:store-clock"

    def __init__(self, coordinator: CarburantsCoordinator, station_id: str) -> None:
        """Initialise the open/closed sensor."""
        super().__init__(coordinator, station_id, open_unique_id(station_id))
        self._unsub_boundary: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        """Arm the wake-up on the next opening or closing time."""
        await super().async_added_to_hass()
        self.async_on_remove(self._async_cancel_boundary)
        self._async_schedule_boundary()

    async def async_will_remove_from_hass(self) -> None:
        """Drop the pending wake-up before the entity goes away."""
        self._async_cancel_boundary()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Re-arm on every poll: the published hours may have changed."""
        self._async_schedule_boundary()
        super()._handle_coordinator_update()

    @callback
    def _async_cancel_boundary(self) -> None:
        """Cancel the pending wake-up, if any."""
        if self._unsub_boundary is not None:
            self._unsub_boundary()
            self._unsub_boundary = None

    @callback
    def _async_schedule_boundary(self) -> None:
        """Schedule a wake-up on the next transition, if one is known.

        Purely local: this only recomputes the state from the WeekSchedule
        already in memory, and never hits the API. When the schedule knows of
        no upcoming transition, nothing is armed and the state stays as
        computed at the last poll.
        """
        self._async_cancel_boundary()

        station = self.station
        if station is None or station.opening_hours is None:
            return

        boundary = station.opening_hours.next_boundary_after(dt_util.now())
        if boundary is None:
            return

        self._unsub_boundary = async_track_point_in_time(
            self.hass, self._handle_boundary, boundary
        )

    @callback
    def _handle_boundary(self, _now) -> None:
        """Write the new state, then arm the following transition."""
        self._unsub_boundary = None
        self.async_write_ha_state()
        self._async_schedule_boundary()

    @property
    def is_on(self) -> bool | None:
        """Return True/False, or None when the station publishes no hours."""
        station = self.station
        if station is None or station.opening_hours is None:
            return None
        return station.opening_hours.is_open_at(dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the weekly schedule and the 24/7 automat flag."""
        station = self.station
        if station is None:
            return {}
        return {
            "station_id": station.id,
            "automate_24_24": station.automate_24_24,
            "horaires_semaine": (
                station.opening_hours.as_dict() if station.opening_hours else None
            ),
            "ferme_aujourdhui": (
                station.opening_hours.days[dt_util.now().isoweekday()].closed
                if station.opening_hours
                and dt_util.now().isoweekday() in station.opening_hours.days
                else None
            ),
        }
