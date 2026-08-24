"""Tests for the sensor platform."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.carburants.api import parse_station
from custom_components.carburants.const import CONF_STATIONS, DOMAIN
from tests.fixtures.records import STATION_WITH_PRICES


async def _setup(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, data={CONF_STATIONS: ["67000002"]}
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.carburants.CarburantsApi.async_fetch",
        AsyncMock(return_value=[parse_station(STATION_WITH_PRICES)]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_price_sensor_state_and_attributes(hass):
    await _setup(hass)

    state = hass.states.get("sensor.route_de_la_wantzenau_strasbourg_gazole")
    assert state is not None
    assert state.state == "2.299"
    assert state.attributes["unit_of_measurement"] == "€/L"
    assert state.attributes["state_class"] == "measurement"
    assert state.attributes["station_id"] == "67000002"
    assert state.attributes["updated_at"] == "2026-08-24T10:25:29+00:00"


async def test_sensor_created_only_for_tracked_fuels(hass):
    await _setup(hass)

    # Gazole has a price, SP98 and E10 are temporarily out -> tracked.
    assert hass.states.get("sensor.route_de_la_wantzenau_strasbourg_gazole")
    assert hass.states.get("sensor.route_de_la_wantzenau_strasbourg_sp98")
    assert hass.states.get("sensor.route_de_la_wantzenau_strasbourg_e10")
    # SP95, E85 and GPLc are definitively out -> not sold, no entity.
    assert hass.states.get("sensor.route_de_la_wantzenau_strasbourg_sp95") is None
    assert hass.states.get("sensor.route_de_la_wantzenau_strasbourg_e85") is None
    assert hass.states.get("sensor.route_de_la_wantzenau_strasbourg_gplc") is None


async def test_price_is_none_while_out_of_stock(hass):
    await _setup(hass)

    state = hass.states.get("sensor.route_de_la_wantzenau_strasbourg_e10")
    assert state.state == "unknown"


async def test_last_update_sensor(hass):
    await _setup(hass)

    state = hass.states.get("sensor.route_de_la_wantzenau_strasbourg_last_update")
    assert state.state == "2026-08-24T10:25:29+00:00"
    assert state.attributes["device_class"] == "timestamp"


async def test_entities_become_unavailable_when_station_disappears(hass):
    entry = await _setup(hass)
    coordinator = entry.runtime_data.coordinator

    with patch.object(coordinator.api, "async_fetch", AsyncMock(return_value=[])):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    state = hass.states.get("sensor.route_de_la_wantzenau_strasbourg_gazole")
    assert state.state == "unavailable"


async def test_unload_entry(hass):
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    # Unloading a config entry does not delete the states of registered
    # entities: Entity.__async_remove_impl keeps them as unavailable and
    # stamps `restored: True`. Only removing the entry deletes them.
    state = hass.states.get("sensor.route_de_la_wantzenau_strasbourg_gazole")
    assert state.state == "unavailable"
    assert state.attributes.get("restored") is True
