"""Constants for the Carburants integration."""

from __future__ import annotations

DOMAIN = "carburants"

API_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "prix-des-carburants-en-france-flux-instantane-v2/records"
)
API_TIMEOUT = 10
SEARCH_LIMIT = 100

# Fuel key -> label as spelled by the dataset.
FUELS: dict[str, str] = {
    "gazole": "Gazole",
    "sp95": "SP95",
    "sp98": "SP98",
    "e10": "E10",
    "e85": "E85",
    "gplc": "GPLc",
}

OUTAGE_TEMPORARY = "temporaire"
OUTAGE_DEFINITIVE = "definitive"

CONF_STATIONS = "stations"
CONF_QUERY = "query"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_PRICE_EVENT_THRESHOLD = "price_event_threshold"

DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 15
MAX_SCAN_INTERVAL = 1440

DEFAULT_RADIUS_M = 10000
MIN_RADIUS_M = 1000
MAX_RADIUS_M = 50000

DEFAULT_PRICE_EVENT_THRESHOLD = 0.001

EVENT_PRICE_CHANGED = "carburants_price_changed"
EVENT_FUEL_OUTAGE = "carburants_fuel_outage"


def price_unique_id(station_id: str, fuel: str) -> str:
    """Return the unique_id of a fuel price sensor."""
    return f"{station_id}_{fuel}"


def outage_unique_id(station_id: str, fuel: str) -> str:
    """Return the unique_id of a fuel outage binary sensor."""
    return f"{station_id}_{fuel}_outage"


def open_unique_id(station_id: str) -> str:
    """Return the unique_id of the open/closed binary sensor."""
    return f"{station_id}_open"


def last_update_unique_id(station_id: str) -> str:
    """Return the unique_id of the last-update diagnostic sensor."""
    return f"{station_id}_last_update"
