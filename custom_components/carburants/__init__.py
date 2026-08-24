"""The Carburants integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CarburantsApi
from .const import (
    CONF_PRICE_EVENT_THRESHOLD,
    CONF_SCAN_INTERVAL,
    CONF_STATIONS,
    DEFAULT_PRICE_EVENT_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import CarburantsCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


@dataclass
class CarburantsRuntimeData:
    """Runtime objects attached to the config entry."""

    coordinator: CarburantsCoordinator


CarburantsConfigEntry = ConfigEntry[CarburantsRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: CarburantsConfigEntry) -> bool:
    """Set up Carburants from a config entry."""
    api = CarburantsApi(async_get_clientsession(hass))
    coordinator = CarburantsCoordinator(
        hass,
        entry,
        api,
        list(entry.data.get(CONF_STATIONS, [])),
        timedelta(minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        entry.options.get(CONF_PRICE_EVENT_THRESHOLD, DEFAULT_PRICE_EVENT_THRESHOLD),
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = CarburantsRuntimeData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: CarburantsConfigEntry
) -> None:
    """Reload the entry when stations or settings change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CarburantsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
