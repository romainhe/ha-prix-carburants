"""Data update coordinator and event emission for Carburants."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CarburantsApi, CarburantsApiError, FuelState, Station
from .const import (
    DOMAIN,
    EVENT_FUEL_OUTAGE,
    EVENT_PRICE_CHANGED,
    FUELS,
    outage_unique_id,
    price_unique_id,
)

_LOGGER = logging.getLogger(__name__)


class CarburantsCoordinator(DataUpdateCoordinator[dict[str, Station]]):
    """Poll every configured station in one request and diff the result."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: CarburantsApi,
        station_ids: list[str],
        scan_interval: timedelta,
        price_threshold: float,
    ) -> None:
        """Initialise the coordinator."""
        self.api = api
        self.station_ids = station_ids
        self._price_threshold = price_threshold
        self._previous: dict[str, dict[str, FuelState]] = {}
        self._primed = False

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Station]:
        """Fetch every station and emit events for what changed."""
        try:
            stations = await self.api.async_fetch(self.station_ids)
        except CarburantsApiError as err:
            raise UpdateFailed(str(err)) from err

        data = {station.id: station for station in stations}
        self._process_events(data)
        return data

    def _process_events(self, data: dict[str, Station]) -> None:
        """Diff against the previous poll and fire the resulting events."""
        previous = self._previous
        self._previous = {
            station_id: dict(station.fuels) for station_id, station in data.items()
        }

        if not self._primed:
            self._primed = True
            return

        for station_id, station in data.items():
            old_fuels = previous.get(station_id)
            if old_fuels is None:
                continue
            for fuel, state in station.tracked_fuels.items():
                old_state = old_fuels.get(fuel)
                if old_state is None:
                    continue
                self._fire_price_event(station, fuel, old_state, state)
                self._fire_outage_event(station, fuel, old_state, state)

    def _entity_id(self, platform: str, unique_id: str) -> str | None:
        """Resolve an entity_id from a unique_id, or None if not registered."""
        registry = er.async_get(self.hass)
        return registry.async_get_entity_id(platform, DOMAIN, unique_id)

    def _base_payload(self, station: Station, fuel: str) -> dict:
        """Build the station/fuel fields shared by both event types."""
        return {
            "station_id": station.id,
            "station_name": station.name,
            "address": station.address,
            "city": station.city,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "fuel": fuel,
            "fuel_label": FUELS[fuel],
        }

    def _fire_price_event(
        self, station: Station, fuel: str, old: FuelState, new: FuelState
    ) -> None:
        """Fire carburants_price_changed when the price moved enough."""
        if old.price is None or new.price is None:
            return
        delta = round(new.price - old.price, 4)
        if abs(delta) < self._price_threshold:
            return

        payload = self._base_payload(station, fuel) | {
            "entity_id": self._entity_id("sensor", price_unique_id(station.id, fuel)),
            "direction": "down" if delta < 0 else "up",
            "old_price": old.price,
            "new_price": new.price,
            "delta": delta,
            "delta_percent": round(delta / old.price * 100, 2),
            "updated_at": new.updated_at.isoformat() if new.updated_at else None,
        }
        _LOGGER.debug("Firing %s: %s", EVENT_PRICE_CHANGED, payload)
        self.hass.bus.async_fire(EVENT_PRICE_CHANGED, payload)

    def _fire_outage_event(
        self, station: Station, fuel: str, old: FuelState, new: FuelState
    ) -> None:
        """Fire carburants_fuel_outage when the outage flag flipped."""
        if old.in_outage == new.in_outage:
            return

        since = new.outage_since or old.outage_since
        payload = self._base_payload(station, fuel) | {
            "entity_id": self._entity_id(
                "binary_sensor", outage_unique_id(station.id, fuel)
            ),
            "state": "start" if new.in_outage else "end",
            "outage_type": new.outage_type or old.outage_type,
            "since": since.isoformat() if since else None,
        }
        _LOGGER.debug("Firing %s: %s", EVENT_FUEL_OUTAGE, payload)
        self.hass.bus.async_fire(EVENT_FUEL_OUTAGE, payload)
