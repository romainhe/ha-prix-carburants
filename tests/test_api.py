"""Tests for the API client and record normalisation."""

from datetime import UTC, datetime

import pytest

from custom_components.carburants.api import (
    CarburantsApi,
    CarburantsApiError,
    parse_station,
)
from tests.fixtures.records import (
    STATION_MINIMAL,
    STATION_NO_HOURS,
    STATION_WITH_PRICES,
)


def test_identity_fields():
    station = parse_station(STATION_WITH_PRICES)
    assert station.id == "67000002"
    assert station.address == "Route de la Wantzenau"
    assert station.city == "Strasbourg"
    assert station.postal_code == "67000"
    assert station.name == "Route de la Wantzenau — Strasbourg"
    assert station.highway is False


def test_position_comes_from_geom_only():
    station = parse_station(STATION_WITH_PRICES)
    assert station.latitude == pytest.approx(48.611994, abs=1e-5)
    assert station.longitude == pytest.approx(7.782216, abs=1e-5)
    assert parse_station(STATION_MINIMAL).latitude is None


def test_highway_flag():
    assert parse_station(STATION_NO_HOURS).highway is True


def test_price_and_timestamp():
    station = parse_station(STATION_WITH_PRICES)
    gazole = station.fuels["gazole"]
    assert gazole.price == 2.299
    assert gazole.updated_at == datetime(2026, 8, 24, 10, 25, 29, tzinfo=UTC)
    assert gazole.in_outage is False


def test_outage_from_per_fuel_fields():
    station = parse_station(STATION_WITH_PRICES)
    e10 = station.fuels["e10"]
    assert e10.in_outage is True
    assert e10.outage_type == "temporaire"
    assert e10.outage_since == datetime(2026, 8, 24, 8, 38, 17, tzinfo=UTC)


def test_outage_falls_back_to_aggregate_lists():
    station = parse_station(STATION_NO_HOURS)
    assert station.fuels["gazole"].outage_type == "temporaire"
    assert station.fuels["e10"].outage_type == "temporaire"
    assert station.fuels["sp98"].outage_type is None


def test_no_outage_when_price_is_present():
    station = parse_station(STATION_MINIMAL)
    assert station.fuels["gazole"].in_outage is False
    assert station.fuels["e10"].in_outage is False


def test_tracked_fuels_exclude_definitive_outages():
    station = parse_station(STATION_WITH_PRICES)
    assert sorted(station.tracked_fuels) == ["e10", "gazole", "sp98"]


def test_tracked_fuels_on_minimal_record():
    station = parse_station(STATION_MINIMAL)
    assert sorted(station.tracked_fuels) == ["e10", "gazole"]


def test_last_update_is_the_most_recent_price_timestamp():
    station = parse_station(STATION_MINIMAL)
    assert station.last_update == datetime(2026, 8, 24, 7, 0, tzinfo=UTC)
    assert parse_station(STATION_NO_HOURS).last_update is None


def test_opening_hours_parsed_when_present():
    station = parse_station(STATION_WITH_PRICES)
    assert station.opening_hours is not None
    assert station.automate_24_24 is False
    assert parse_station(STATION_NO_HOURS).opening_hours is None


async def test_fetch_builds_an_in_query(aioclient_mock, hass):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.carburants.const import API_URL

    aioclient_mock.get(
        API_URL,
        json={"total_count": 1, "results": [STATION_WITH_PRICES]},
    )
    api = CarburantsApi(async_get_clientsession(hass))
    stations = await api.async_fetch(["67000002"])

    assert [s.id for s in stations] == ["67000002"]
    assert aioclient_mock.mock_calls[0][1].query["where"] == "id in (67000002)"


async def test_search_text_uses_postal_code_or_city(aioclient_mock, hass):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.carburants.const import API_URL

    aioclient_mock.get(API_URL, json={"total_count": 0, "results": []})
    api = CarburantsApi(async_get_clientsession(hass))

    await api.async_search_text("67000")
    assert aioclient_mock.mock_calls[0][1].query["where"] == 'cp="67000"'

    await api.async_search_text("Schiltigheim")
    assert (
        aioclient_mock.mock_calls[1][1].query["where"]
        == 'search(ville, "Schiltigheim")'
    )


async def test_search_geo_sorts_by_distance(aioclient_mock, hass):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.carburants.const import API_URL

    aioclient_mock.get(
        API_URL,
        json={
            "total_count": 2,
            "results": [STATION_NO_HOURS, STATION_WITH_PRICES],
        },
    )
    api = CarburantsApi(async_get_clientsession(hass))
    stations = await api.async_search_geo(48.61, 7.78, 10000)

    assert [s.id for s in stations] == ["67000002", "67000026"]
    assert stations[0].distance_km < stations[1].distance_km
    assert (
        aioclient_mock.mock_calls[0][1].query["where"]
        == "distance(geom, geom'POINT(7.78 48.61)', 10000m)"
    )


async def test_http_error_raises_api_error(aioclient_mock, hass):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.carburants.const import API_URL

    aioclient_mock.get(API_URL, status=500)
    api = CarburantsApi(async_get_clientsession(hass))

    with pytest.raises(CarburantsApiError):
        await api.async_fetch(["67000002"])
