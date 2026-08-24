"""HTTP client for the French fuel-price open dataset."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from math import asin, cos, radians, sin, sqrt

import aiohttp

from .const import (
    API_TIMEOUT,
    API_URL,
    FUELS,
    OUTAGE_DEFINITIVE,
    OUTAGE_TEMPORARY,
    SEARCH_LIMIT,
)
from .horaires import WeekSchedule, parse_horaires

_LOGGER = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0


class CarburantsApiError(Exception):
    """Raised when the dataset cannot be reached or answers badly."""


@dataclass(frozen=True)
class FuelState:
    """Current state of one fuel at one station."""

    fuel: str
    price: float | None
    updated_at: datetime | None
    outage_type: str | None
    outage_since: datetime | None

    @property
    def in_outage(self) -> bool:
        """Return True when the fuel is currently out of stock."""
        return self.outage_type is not None


@dataclass(frozen=True)
class Station:
    """A normalised station record."""

    id: str
    address: str
    city: str
    postal_code: str
    latitude: float | None
    longitude: float | None
    highway: bool
    fuels: dict[str, FuelState]
    opening_hours: WeekSchedule | None
    automate_24_24: bool
    distance_km: float | None = field(default=None)

    @property
    def name(self) -> str:
        """Return the human-readable station name."""
        return f"{self.address} — {self.city}"

    @property
    def tracked_fuels(self) -> dict[str, FuelState]:
        """Return only the fuels this station actually distributes.

        A definitive outage means the station does not sell that fuel at all,
        so no entity is created for it.
        """
        return {
            fuel: state
            for fuel, state in self.fuels.items()
            if state.price is not None or state.outage_type == OUTAGE_TEMPORARY
        }

    @property
    def last_update(self) -> datetime | None:
        """Return the most recent price timestamp across all fuels."""
        stamps = [s.updated_at for s in self.fuels.values() if s.updated_at]
        return max(stamps) if stamps else None


def _parse_datetime(raw: object) -> datetime | None:
    """Parse an ISO-8601 timestamp coming from the dataset."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _parse_price(raw: object) -> float | None:
    """Parse a price, which the dataset gives as a float or null."""
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _split_labels(raw: object) -> set[str]:
    """Split a ";"-separated fuel-label list."""
    if not isinstance(raw, str) or not raw:
        return set()
    return {part.strip() for part in raw.split(";") if part.strip()}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def parse_station(record: dict) -> Station:
    """Normalise one raw dataset record into a Station."""
    temporary = _split_labels(record.get("carburants_rupture_temporaire"))
    definitive = _split_labels(record.get("carburants_rupture_definitive"))

    fuels: dict[str, FuelState] = {}
    for fuel, label in FUELS.items():
        price = _parse_price(record.get(f"{fuel}_prix"))
        outage_type = record.get(f"{fuel}_rupture_type") or None
        outage_since = _parse_datetime(record.get(f"{fuel}_rupture_debut"))

        if price is not None:
            # A published price wins over any historical outage marker.
            outage_type = None
            outage_since = None
        elif outage_type is None:
            # Fall back on the aggregate lists when the per-fuel field is empty.
            if label in temporary:
                outage_type = OUTAGE_TEMPORARY
            elif label in definitive:
                outage_type = OUTAGE_DEFINITIVE

        fuels[fuel] = FuelState(
            fuel=fuel,
            price=price,
            updated_at=_parse_datetime(record.get(f"{fuel}_maj")),
            outage_type=outage_type,
            outage_since=outage_since if outage_type else None,
        )

    geom = record.get("geom") or {}
    if not isinstance(geom, dict):
        geom = {}

    return Station(
        id=str(record.get("id")),
        address=str(record.get("adresse") or "").strip(),
        city=str(record.get("ville") or "").strip(),
        postal_code=str(record.get("cp") or "").strip(),
        latitude=geom.get("lat"),
        longitude=geom.get("lon"),
        highway=record.get("pop") == "A",
        fuels=fuels,
        opening_hours=parse_horaires(
            record.get("horaires"), record.get("horaires_automate_24_24")
        ),
        automate_24_24=str(record.get("horaires_automate_24_24") or "").lower()
        == "oui",
    )


class CarburantsApi:
    """Thin async client over the Opendatasoft Explore v2.1 API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with Home Assistant's shared session."""
        self._session = session

    async def _async_query(self, where: str) -> list[dict]:
        """Run one records query and return the raw results."""
        params = {"where": where, "limit": str(SEARCH_LIMIT)}
        try:
            async with asyncio.timeout(API_TIMEOUT):
                response = await self._session.get(API_URL, params=params)
                response.raise_for_status()
                payload = await response.json()
        except TimeoutError as err:
            raise CarburantsApiError("Timeout querying the fuel dataset") from err
        except aiohttp.ClientError as err:
            raise CarburantsApiError(f"Error querying the fuel dataset: {err}") from err

        results = payload.get("results")
        if not isinstance(results, list):
            raise CarburantsApiError("Unexpected payload from the fuel dataset")
        return results

    async def async_fetch(self, station_ids: list[str]) -> list[Station]:
        """Fetch the current state of the given stations in one request."""
        if not station_ids:
            return []
        joined = ",".join(str(station_id) for station_id in station_ids)
        records = await self._async_query(f"id in ({joined})")
        return [parse_station(record) for record in records]

    async def async_search_text(self, query: str) -> list[Station]:
        """Search stations by postal code or by city name."""
        cleaned = query.strip()
        if cleaned.isdigit() and len(cleaned) == 5:
            where = f'cp="{cleaned}"'
        else:
            escaped = cleaned.replace('"', '\\"')
            where = f'search(ville, "{escaped}")'
        records = await self._async_query(where)
        stations = [parse_station(record) for record in records]
        stations.sort(key=lambda station: (station.city, station.address))
        return stations

    async def async_search_geo(
        self, latitude: float, longitude: float, radius_m: int
    ) -> list[Station]:
        """Search stations within `radius_m` metres of a point, nearest first."""
        where = f"distance(geom, geom'POINT({longitude} {latitude})', {radius_m}m)"
        records = await self._async_query(where)

        stations: list[Station] = []
        for record in records:
            station = parse_station(record)
            if station.latitude is None or station.longitude is None:
                stations.append(station)
                continue
            distance = _haversine_km(
                latitude, longitude, station.latitude, station.longitude
            )
            stations.append(replace(station, distance_km=round(distance, 1)))
        stations.sort(
            key=lambda station: (
                station.distance_km if station.distance_km is not None else 1e9
            )
        )
        return stations
