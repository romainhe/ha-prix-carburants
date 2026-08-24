"""Shared entity base for Carburants."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Station
from .const import DOMAIN
from .coordinator import CarburantsCoordinator


class CarburantsStationEntity(CoordinatorEntity[CarburantsCoordinator]):
    """Base entity bound to one station device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CarburantsCoordinator,
        station_id: str,
        unique_id: str,
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._station_id = station_id
        self._attr_unique_id = unique_id

        station = coordinator.data.get(station_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, station_id)},
            name=station.name if station else station_id,
            manufacturer="Ministère de l'Économie",
            model="prix-carburants.gouv.fr",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.prix-carburants.gouv.fr/",
        )

    @property
    def station(self) -> Station | None:
        """Return the current station data, or None if it vanished."""
        return self.coordinator.data.get(self._station_id)

    @property
    def available(self) -> bool:
        """Return True when the station is present in the last poll."""
        return super().available and self.station is not None
