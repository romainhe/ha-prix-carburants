"""Tests for the binary sensor platform."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.carburants.api import parse_station
from custom_components.carburants.const import CONF_SCAN_INTERVAL, CONF_STATIONS, DOMAIN
from tests.fixtures.records import STATION_NO_HOURS, STATION_WITH_PRICES

# Far larger than any freezer.move_to() span used below (the widest is the
# ~7-day jump in test_open_sensor_rearms_on_the_following_boundary), so the
# coordinator's own periodic poll can never coincide with -- and confound --
# the boundary timer under test.
_NO_INTERFERING_POLL_MINUTES = 100_000


async def _setup(hass, record) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_STATIONS: [str(record["id"])]},
        options={CONF_SCAN_INTERVAL: _NO_INTERFERING_POLL_MINUTES},
    )
    entry.add_to_hass(hass)
    # These tests assert on UTC wall-clock boundaries; the hass fixture
    # otherwise defaults to US/Pacific.
    await hass.config.async_set_time_zone("UTC")
    with patch(
        "custom_components.carburants.CarburantsApi.async_fetch",
        AsyncMock(return_value=[parse_station(record)]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_outage_sensor_reflects_state(hass):
    await _setup(hass, STATION_WITH_PRICES)

    out = hass.states.get("binary_sensor.route_de_la_wantzenau_strasbourg_e10_outage")
    assert out.state == "on"
    assert out.attributes["device_class"] == "problem"
    assert out.attributes["outage_type"] == "temporaire"
    assert out.attributes["since"] == "2026-08-24T08:38:17+00:00"

    ok = hass.states.get("binary_sensor.route_de_la_wantzenau_strasbourg_gazole_outage")
    assert ok.state == "off"


async def test_no_outage_sensor_for_definitive_outages(hass):
    await _setup(hass, STATION_WITH_PRICES)
    assert (
        hass.states.get("binary_sensor.route_de_la_wantzenau_strasbourg_sp95_outage")
        is None
    )


async def test_open_sensor_is_unknown_without_hours(hass):
    await _setup(hass, STATION_NO_HOURS)
    state = hass.states.get("binary_sensor.49_rte_du_rhin_strasbourg_open")
    assert state.state == "unknown"


async def test_open_sensor_uses_schedule(hass, freezer: FrozenDateTimeFactory):
    # Monday 2026-08-24 at 12:00 local: inside the 06:30-20:30 slot.
    freezer.move_to(datetime(2026, 8, 24, 12, 0, tzinfo=UTC))
    await _setup(hass, STATION_WITH_PRICES)

    state = hass.states.get("binary_sensor.route_de_la_wantzenau_strasbourg_open")
    assert state.state == "on"
    assert state.attributes["automate_24_24"] is False
    assert state.attributes["horaires_semaine"] == {"Lundi": "06:30-20:30"}


async def test_open_sensor_flips_at_the_scheduled_boundary(
    hass, freezer: FrozenDateTimeFactory
):
    # One minute before Monday's 20:30 closing time.
    freezer.move_to(datetime(2026, 8, 24, 20, 29, tzinfo=UTC))
    await _setup(hass, STATION_WITH_PRICES)
    assert (
        hass.states.get("binary_sensor.route_de_la_wantzenau_strasbourg_open").state
        == "on"
    )

    # No wake-up in between: the timer is armed on 20:30 exactly.
    freezer.move_to(datetime(2026, 8, 24, 20, 29, 59, tzinfo=UTC))
    async_fire_time_changed(hass, datetime(2026, 8, 24, 20, 29, 59, tzinfo=UTC))
    await hass.async_block_till_done()
    assert (
        hass.states.get("binary_sensor.route_de_la_wantzenau_strasbourg_open").state
        == "on"
    )

    freezer.move_to(datetime(2026, 8, 24, 20, 30, tzinfo=UTC))
    async_fire_time_changed(hass, datetime(2026, 8, 24, 20, 30, tzinfo=UTC))
    await hass.async_block_till_done()

    assert (
        hass.states.get("binary_sensor.route_de_la_wantzenau_strasbourg_open").state
        == "off"
    )


async def test_open_sensor_rearms_on_the_following_boundary(
    hass, freezer: FrozenDateTimeFactory
):
    freezer.move_to(datetime(2026, 8, 24, 20, 29, tzinfo=UTC))
    await _setup(hass, STATION_WITH_PRICES)

    # Closing time: the sensor must re-arm on next Monday's 06:30 opening,
    # the fixture only publishing hours for Monday.
    freezer.move_to(datetime(2026, 8, 24, 20, 30, tzinfo=UTC))
    async_fire_time_changed(hass, datetime(2026, 8, 24, 20, 30, tzinfo=UTC))
    await hass.async_block_till_done()

    freezer.move_to(datetime(2026, 8, 31, 6, 30, tzinfo=UTC))
    async_fire_time_changed(hass, datetime(2026, 8, 31, 6, 30, tzinfo=UTC))
    await hass.async_block_till_done()

    assert (
        hass.states.get("binary_sensor.route_de_la_wantzenau_strasbourg_open").state
        == "on"
    )


async def test_open_sensor_without_hours_arms_no_timer(
    hass, freezer: FrozenDateTimeFactory
):
    freezer.move_to(datetime(2026, 8, 24, 12, 0, tzinfo=UTC))
    await _setup(hass, STATION_NO_HOURS)
    assert (
        hass.states.get("binary_sensor.49_rte_du_rhin_strasbourg_open").state
        == "unknown"
    )

    # next_boundary_after() returned None: nothing is scheduled, and time
    # passing changes nothing.
    freezer.move_to(datetime(2026, 8, 25, 12, 0, tzinfo=UTC))
    async_fire_time_changed(hass, datetime(2026, 8, 25, 12, 0, tzinfo=UTC))
    await hass.async_block_till_done()

    assert (
        hass.states.get("binary_sensor.49_rte_du_rhin_strasbourg_open").state
        == "unknown"
    )


async def test_open_sensor_rearms_when_the_coordinator_updates(
    hass, freezer: FrozenDateTimeFactory
):
    freezer.move_to(datetime(2026, 8, 24, 12, 0, tzinfo=UTC))
    entry = await _setup(hass, STATION_WITH_PRICES)
    coordinator = entry.runtime_data.coordinator

    # The station starts publishing a shorter Monday: 06:30-13:00.
    shortened = {
        **STATION_WITH_PRICES,
        "horaires": (
            '{"@automate-24-24": "", "jour": [{"@id": "1", "@nom": "Lundi", '
            '"@ferme": "", "horaire": {"@ouverture": "06.30", '
            '"@fermeture": "13.00"}}]}'
        ),
    }
    with patch.object(
        coordinator.api,
        "async_fetch",
        AsyncMock(return_value=[parse_station(shortened)]),
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    # The timer must now fire on the new 13:00 boundary, not the old 20:30
    # one. The coordinator's own scan interval is set far beyond this span
    # (see _NO_INTERFERING_POLL_MINUTES), so no periodic poll can fire here
    # and mask a broken re-arm.
    freezer.move_to(datetime(2026, 8, 24, 13, 0, tzinfo=UTC))
    async_fire_time_changed(hass, datetime(2026, 8, 24, 13, 0, tzinfo=UTC))
    await hass.async_block_till_done()

    assert (
        hass.states.get("binary_sensor.route_de_la_wantzenau_strasbourg_open").state
        == "off"
    )
