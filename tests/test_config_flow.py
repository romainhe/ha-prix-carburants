"""Tests for the config and options flows."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.carburants.api import CarburantsApiError, parse_station
from custom_components.carburants.const import (
    CONF_PRICE_EVENT_THRESHOLD,
    CONF_SCAN_INTERVAL,
    CONF_STATIONS,
    DOMAIN,
)
from tests.fixtures.records import STATION_NO_HOURS, STATION_WITH_PRICES

STATIONS = [parse_station(STATION_WITH_PRICES), parse_station(STATION_NO_HOURS)]


async def test_search_by_postal_code_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.MENU

    with patch(
        "custom_components.carburants.config_flow.CarburantsApi.async_search_text",
        AsyncMock(return_value=STATIONS),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "recherche"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"query": "67000"}
        )

    assert result["step_id"] == "stations"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: ["67000002"]}
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_STATIONS: ["67000002"]}


async def test_search_by_radius_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "custom_components.carburants.config_flow.CarburantsApi.async_search_geo",
        AsyncMock(return_value=STATIONS),
    ) as search:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "proximite"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "location": {
                    "latitude": 48.61,
                    "longitude": 7.78,
                    "radius": 5000,
                }
            },
        )

    search.assert_awaited_once_with(48.61, 7.78, 5000)
    assert result["step_id"] == "stations"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: ["67000002", "67000026"]}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STATIONS] == ["67000002", "67000026"]


async def test_empty_selection_shows_error(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "custom_components.carburants.config_flow.CarburantsApi.async_search_text",
        AsyncMock(return_value=STATIONS),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "recherche"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"query": "67000"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STATIONS: []}
        )

    assert result["step_id"] == "stations"
    assert result["errors"] == {"base": "no_station_selected"}


async def test_no_results_returns_to_search(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "custom_components.carburants.config_flow.CarburantsApi.async_search_text",
        AsyncMock(return_value=[]),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "recherche"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"query": "00000"}
        )

    assert result["step_id"] == "recherche"
    assert result["errors"] == {"base": "no_results"}


async def test_api_error_shows_cannot_connect(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with patch(
        "custom_components.carburants.config_flow.CarburantsApi.async_search_text",
        AsyncMock(side_effect=CarburantsApiError("boom")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "recherche"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"query": "67000"}
        )

    assert result["step_id"] == "recherche"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_single_entry_only(hass):
    MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, data={CONF_STATIONS: ["1"]}
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_settings_branch(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, data={CONF_STATIONS: ["67000002"]}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "reglages"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 30, CONF_PRICE_EVENT_THRESHOLD: 0.005},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_SCAN_INTERVAL: 30,
        CONF_PRICE_EVENT_THRESHOLD: 0.005,
    }


async def test_options_stations_branch_merges_existing(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, data={CONF_STATIONS: ["67000026"]}
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with (
        patch(
            "custom_components.carburants.config_flow.CarburantsApi.async_search_text",
            AsyncMock(return_value=[STATIONS[0]]),
        ),
        patch(
            "custom_components.carburants.config_flow.CarburantsApi.async_fetch",
            AsyncMock(return_value=[STATIONS[1]]),
        ),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "stations"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "recherche"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"query": "67000"}
        )

        # Both the already-tracked station and the new search hit are offered.
        assert set(result["data_schema"].schema[CONF_STATIONS].options) == {
            "67000002",
            "67000026",
        }

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_STATIONS: ["67000002", "67000026"]}
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_STATIONS] == ["67000002", "67000026"]


async def test_options_flow_deselecting_a_station_purges_its_device(hass):
    """Walk the whole removal path: options flow -> entry update -> reload -> purge."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_STATIONS: ["67000002", "67000026"]},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.carburants.CarburantsApi.async_fetch",
        AsyncMock(return_value=STATIONS),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "67000002")}) is not None
    )
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "67000026")}) is not None
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with (
        patch(
            "custom_components.carburants.config_flow.CarburantsApi.async_search_text",
            AsyncMock(return_value=[STATIONS[0]]),
        ),
        patch(
            "custom_components.carburants.CarburantsApi.async_fetch",
            AsyncMock(return_value=[STATIONS[0]]),
        ),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "stations"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "recherche"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"query": "67000"}
        )
        assert result["step_id"] == "selection"

        # Deselect 67000026: only the kept station is submitted.
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_STATIONS: ["67000002"]}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_STATIONS] == ["67000002"]

    assert device_registry.async_get_device(identifiers={(DOMAIN, "67000026")}) is None
    kept_device = device_registry.async_get_device(identifiers={(DOMAIN, "67000002")})
    assert kept_device is not None
