"""Config and options flows for Carburants."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LOCATION
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CarburantsApi, CarburantsApiError, Station
from .const import (
    CONF_PRICE_EVENT_THRESHOLD,
    CONF_QUERY,
    CONF_SCAN_INTERVAL,
    CONF_STATIONS,
    DEFAULT_PRICE_EVENT_THRESHOLD,
    DEFAULT_RADIUS_M,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FUELS,
    MAX_RADIUS_M,
    MAX_SCAN_INTERVAL,
    MIN_RADIUS_M,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _station_label(station: Station) -> str:
    """Build the label shown in the station picker."""
    parts = [f"{station.address}, {station.city}"]
    if station.distance_km is not None:
        parts.append(f"{station.distance_km:.1f} km".replace(".", ","))
    priced = [
        f"{FUELS[fuel]} {state.price:.3f} €".replace(".", ",")
        for fuel, state in station.tracked_fuels.items()
        if state.price is not None
    ]
    if priced:
        parts.append(" · ".join(priced))
    return " · ".join(parts)


class _SearchMixin:
    """Shared search steps for the config and options flows."""

    hass: Any
    _results: dict[str, Station]

    def _api(self) -> CarburantsApi:
        return CarburantsApi(async_get_clientsession(self.hass))

    async def _async_run_search(self, coro) -> tuple[dict[str, str], list[Station]]:
        """Run a search coroutine, mapping API failures to form errors."""
        try:
            stations = await coro
        except CarburantsApiError:
            return {"base": "cannot_connect"}, []
        if not stations:
            return {"base": "no_results"}, []
        return {}, stations

    async def _async_after_search(self) -> ConfigFlowResult:
        """Continue the flow once a search has produced results.

        Overridden by each flow to point at its own next step.
        """
        raise NotImplementedError

    async def async_step_recherche(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search by postal code or city."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, stations = await self._async_run_search(
                self._api().async_search_text(user_input[CONF_QUERY])
            )
            if not errors:
                self._results = {station.id: station for station in stations}
                return await self._async_after_search()

        return self.async_show_form(
            step_id="recherche",
            data_schema=vol.Schema({vol.Required(CONF_QUERY): cv.string}),
            errors=errors,
        )

    async def async_step_proximite(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search within a radius of a point."""
        errors: dict[str, str] = {}
        if user_input is not None:
            location = user_input[CONF_LOCATION]
            radius = int(
                min(
                    max(location.get("radius", DEFAULT_RADIUS_M), MIN_RADIUS_M),
                    MAX_RADIUS_M,
                )
            )
            errors, stations = await self._async_run_search(
                self._api().async_search_geo(
                    location["latitude"], location["longitude"], radius
                ),
            )
            if not errors:
                self._results = {station.id: station for station in stations}
                return await self._async_after_search()

        return self.async_show_form(
            step_id="proximite",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOCATION,
                        default={
                            "latitude": self.hass.config.latitude,
                            "longitude": self.hass.config.longitude,
                            "radius": DEFAULT_RADIUS_M,
                        },
                    ): selector.LocationSelector(
                        selector.LocationSelectorConfig(radius=True)
                    )
                }
            ),
            errors=errors,
        )


class CarburantsConfigFlow(ConfigFlow, _SearchMixin, domain=DOMAIN):
    """Handle the initial configuration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._results: dict[str, Station] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return CarburantsOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the two search methods."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured(error="single_instance_allowed")
        return self.async_show_menu(
            step_id="user", menu_options=["recherche", "proximite"]
        )

    async def _async_after_search(self) -> ConfigFlowResult:
        """Move to station selection once a search has produced results."""
        return await self.async_step_stations()

    async def async_step_stations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the stations to monitor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get(CONF_STATIONS) or []
            if not selected:
                errors["base"] = "no_station_selected"
            else:
                return self.async_create_entry(
                    title="Prix carburants", data={CONF_STATIONS: list(selected)}
                )

        options = {
            station_id: _station_label(station)
            for station_id, station in self._results.items()
        }
        return self.async_show_form(
            step_id="stations",
            data_schema=vol.Schema(
                {vol.Required(CONF_STATIONS, default=[]): cv.multi_select(options)}
            ),
            errors=errors,
        )


class CarburantsOptionsFlow(OptionsFlow, _SearchMixin):
    """Handle station management and settings."""

    def __init__(self) -> None:
        """Initialise flow state."""
        self._results: dict[str, Station] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the two option branches."""
        return self.async_show_menu(
            step_id="init", menu_options=["stations", "reglages"]
        )

    async def async_step_stations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the two search methods for adding stations."""
        return self.async_show_menu(
            step_id="stations", menu_options=["recherche", "proximite"]
        )

    async def _async_after_search(self) -> ConfigFlowResult:
        """Move to the merged station picker once a search has results."""
        return await self.async_step_selection()

    async def async_step_selection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Merge already-tracked stations with the new search hits."""
        current: list[str] = list(self.config_entry.data.get(CONF_STATIONS, []))

        if user_input is not None:
            selected = user_input.get(CONF_STATIONS) or []
            if not selected:
                return await self._async_show_selection(
                    current, {"base": "no_station_selected"}
                )
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_STATIONS: list(selected)},
            )
            return self.async_create_entry(data=dict(self.config_entry.options))

        return await self._async_show_selection(current, {})

    async def _async_show_selection(
        self, current: list[str], errors: dict[str, str]
    ) -> ConfigFlowResult:
        """Render the merged station picker."""
        options = dict(self._results)
        missing = [station_id for station_id in current if station_id not in options]
        if missing:
            try:
                for station in await self._api().async_fetch(missing):
                    options[station.id] = station
            except CarburantsApiError:
                _LOGGER.debug("Could not refresh labels for tracked stations")

        labels = {
            station_id: _station_label(station)
            for station_id, station in options.items()
        }
        for station_id in current:
            labels.setdefault(station_id, station_id)

        return self.async_show_form(
            step_id="selection",
            data_schema=vol.Schema(
                {vol.Required(CONF_STATIONS, default=current): cv.multi_select(labels)}
            ),
            errors=errors,
        )

    async def async_step_reglages(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit polling interval and price-event threshold."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="reglages",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                    vol.Required(
                        CONF_PRICE_EVENT_THRESHOLD,
                        default=options.get(
                            CONF_PRICE_EVENT_THRESHOLD,
                            DEFAULT_PRICE_EVENT_THRESHOLD,
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=0.5)),
                }
            ),
        )
