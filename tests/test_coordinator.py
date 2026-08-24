"""Tests for the coordinator's polling and event detection."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.carburants.api import CarburantsApiError, FuelState, Station
from custom_components.carburants.const import (
    DEFAULT_PRICE_EVENT_THRESHOLD,
    DOMAIN,
    EVENT_FUEL_OUTAGE,
    EVENT_PRICE_CHANGED,
)
from custom_components.carburants.coordinator import CarburantsCoordinator


def _station(
    price: float | None = 1.899,
    outage_type: str | None = None,
) -> Station:
    return Station(
        id="67000002",
        address="Route de la Wantzenau",
        city="Strasbourg",
        postal_code="67000",
        latitude=48.612,
        longitude=7.782,
        highway=False,
        fuels={
            "gazole": FuelState(
                fuel="gazole",
                price=price,
                updated_at=datetime(2026, 8, 24, 10, 0, tzinfo=UTC),
                outage_type=outage_type,
                outage_since=(
                    datetime(2026, 8, 24, 9, 0, tzinfo=UTC) if outage_type else None
                ),
            )
        },
        opening_hours=None,
        automate_24_24=False,
    )


class FakeApi:
    """API double returning a scripted sequence of station lists."""

    def __init__(self, sequence: list[list[Station] | Exception]) -> None:
        self.sequence = sequence
        self.calls: list[list[str]] = []

    async def async_fetch(self, station_ids: list[str]) -> list[Station]:
        self.calls.append(station_ids)
        item = self.sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _coordinator(hass, api) -> CarburantsCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data={"stations": ["67000002"]})
    entry.add_to_hass(hass)
    return CarburantsCoordinator(
        hass,
        entry,
        api,
        ["67000002"],
        timedelta(minutes=60),
        DEFAULT_PRICE_EVENT_THRESHOLD,
    )


async def test_first_poll_primes_silently(hass):
    events = async_capture_events(hass, EVENT_PRICE_CHANGED)
    coordinator = _coordinator(hass, FakeApi([[_station(1.899)]]))

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.data["67000002"].fuels["gazole"].price == 1.899
    assert events == []


async def test_price_drop_fires_event(hass):
    events = async_capture_events(hass, EVENT_PRICE_CHANGED)
    coordinator = _coordinator(hass, FakeApi([[_station(1.899)], [_station(1.859)]]))

    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1
    data = events[0].data
    assert data["direction"] == "down"
    assert data["fuel"] == "gazole"
    assert data["fuel_label"] == "Gazole"
    assert data["old_price"] == 1.899
    assert data["new_price"] == 1.859
    assert data["delta"] == pytest.approx(-0.04)
    assert data["delta_percent"] == pytest.approx(-2.11, abs=0.01)
    assert data["station_id"] == "67000002"
    assert data["station_name"] == "Route de la Wantzenau — Strasbourg"
    assert data["city"] == "Strasbourg"
    assert data["latitude"] == 48.612
    assert data["updated_at"] == "2026-08-24T10:00:00+00:00"
    assert "entity_id" in data


async def test_price_rise_fires_event_with_up_direction(hass):
    events = async_capture_events(hass, EVENT_PRICE_CHANGED)
    coordinator = _coordinator(hass, FakeApi([[_station(1.859)], [_station(1.899)]]))

    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["direction"] == "up"


async def test_change_below_threshold_is_ignored(hass):
    events = async_capture_events(hass, EVENT_PRICE_CHANGED)
    coordinator = _coordinator(hass, FakeApi([[_station(1.8990)], [_station(1.8995)]]))

    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert events == []


async def test_outage_start_and_end(hass):
    events = async_capture_events(hass, EVENT_FUEL_OUTAGE)
    price_events = async_capture_events(hass, EVENT_PRICE_CHANGED)
    coordinator = _coordinator(
        hass,
        FakeApi(
            [
                [_station(1.899)],
                [_station(None, outage_type="temporaire")],
                [_station(1.949)],
            ]
        ),
    )

    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert [event.data["state"] for event in events] == ["start", "end"]
    assert events[0].data["outage_type"] == "temporaire"
    assert events[0].data["since"] == "2026-08-24T09:00:00+00:00"
    assert events[0].data["fuel_label"] == "Gazole"
    # Going in and out of an outage is not a price change.
    assert price_events == []


async def test_station_missing_from_response_fires_nothing(hass):
    events = async_capture_events(hass, EVENT_PRICE_CHANGED)
    coordinator = _coordinator(hass, FakeApi([[_station(1.899)], []]))

    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.data == {}
    assert events == []


async def test_api_error_becomes_update_failed(hass):
    coordinator = _coordinator(hass, FakeApi([CarburantsApiError("boom")]))

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
