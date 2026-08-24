"""Tests for the const module."""

from custom_components.carburants.const import (
    DOMAIN,
    EVENT_FUEL_OUTAGE,
    EVENT_PRICE_CHANGED,
    FUELS,
    last_update_unique_id,
    open_unique_id,
    outage_unique_id,
    price_unique_id,
)


def test_domain_and_event_names():
    assert DOMAIN == "carburants"
    assert EVENT_PRICE_CHANGED == "carburants_price_changed"
    assert EVENT_FUEL_OUTAGE == "carburants_fuel_outage"


def test_fuels_table_is_ordered_and_labelled():
    assert list(FUELS) == ["gazole", "sp95", "sp98", "e10", "e85", "gplc"]
    assert FUELS["gplc"] == "GPLc"
    assert FUELS["e10"] == "E10"


def test_unique_id_builders():
    assert price_unique_id("67000002", "gazole") == "67000002_gazole"
    assert outage_unique_id("67000002", "e10") == "67000002_e10_outage"
    assert open_unique_id("67000002") == "67000002_open"
    assert last_update_unique_id("67000002") == "67000002_last_update"
