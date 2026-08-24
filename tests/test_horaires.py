"""Tests for the opening-hours parser."""

import json
from datetime import UTC, datetime, time

from custom_components.carburants.horaires import parse_horaires


def _raw(days: list[dict], automate: str = "") -> str:
    return json.dumps({"@automate-24-24": automate, "jour": days})


def _day(day_id: int, name: str, ferme: str = "", horaire=None) -> dict:
    day = {"@id": str(day_id), "@nom": name, "@ferme": ferme}
    if horaire is not None:
        day["horaire"] = horaire
    return day


def test_missing_hours_returns_none():
    assert parse_horaires(None, "Non") is None
    assert parse_horaires("", "Non") is None


def test_automate_flag_is_read_from_dedicated_field():
    week = parse_horaires(_raw([_day(1, "Lundi")]), "Oui")
    assert week.automate_24_24 is True
    week = parse_horaires(_raw([_day(1, "Lundi")]), "Non")
    assert week.automate_24_24 is False


def test_day_without_horaire_is_unknown():
    week = parse_horaires(_raw([_day(1, "Lundi")]), "Non")
    monday_noon = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)  # a Monday
    assert week.is_open_at(monday_noon) is None


def test_single_slot_object():
    week = parse_horaires(
        _raw(
            [_day(1, "Lundi", horaire={"@ouverture": "06.30", "@fermeture": "20.30"})]
        ),
        "Oui",
    )
    assert week.days[1].slots == ((time(6, 30), time(20, 30)),)
    assert week.is_open_at(datetime(2026, 8, 24, 12, 0, tzinfo=UTC)) is True
    assert week.is_open_at(datetime(2026, 8, 24, 5, 0, tzinfo=UTC)) is False


def test_multiple_slots_list():
    week = parse_horaires(
        _raw(
            [
                _day(
                    1,
                    "Lundi",
                    horaire=[
                        {"@ouverture": "08.00", "@fermeture": "12.00"},
                        {"@ouverture": "14.00", "@fermeture": "19.00"},
                    ],
                )
            ]
        ),
        "Non",
    )
    assert len(week.days[1].slots) == 2
    assert week.is_open_at(datetime(2026, 8, 24, 13, 0, tzinfo=UTC)) is False
    assert week.is_open_at(datetime(2026, 8, 24, 15, 0, tzinfo=UTC)) is True


def test_zero_to_zero_means_open_all_day():
    week = parse_horaires(
        _raw(
            [_day(1, "Lundi", horaire={"@ouverture": "00.00", "@fermeture": "00.00"})]
        ),
        "Oui",
    )
    assert week.is_open_at(datetime(2026, 8, 24, 3, 0, tzinfo=UTC)) is True
    assert week.is_open_at(datetime(2026, 8, 24, 23, 59, tzinfo=UTC)) is True


def test_closed_day():
    week = parse_horaires(
        _raw(
            [
                _day(
                    1,
                    "Lundi",
                    ferme="1",
                    horaire={"@ouverture": "08.00", "@fermeture": "19.00"},
                )
            ]
        ),
        "Non",
    )
    assert week.days[1].closed is True
    assert week.is_open_at(datetime(2026, 8, 24, 12, 0, tzinfo=UTC)) is False


def test_overnight_slot_spills_into_next_day():
    week = parse_horaires(
        _raw(
            [
                _day(
                    7,
                    "Dimanche",
                    horaire={"@ouverture": "22.00", "@fermeture": "06.00"},
                ),
                _day(1, "Lundi", ferme="1"),
            ]
        ),
        "Non",
    )
    # Sunday 23:00 -> open
    assert week.is_open_at(datetime(2026, 8, 23, 23, 0, tzinfo=UTC)) is True
    # Monday 02:00 -> still inside Sunday's overnight slot
    assert week.is_open_at(datetime(2026, 8, 24, 2, 0, tzinfo=UTC)) is True
    # Monday 09:00 -> Monday is closed
    assert week.is_open_at(datetime(2026, 8, 24, 9, 0, tzinfo=UTC)) is False


def test_unparseable_payload_returns_none():
    assert parse_horaires("not json", "Non") is None
    assert parse_horaires(json.dumps({"jour": "nope"}), "Non") is None


def test_as_dict_is_human_readable():
    week = parse_horaires(
        _raw(
            [
                _day(
                    1,
                    "Lundi",
                    horaire={"@ouverture": "06.30", "@fermeture": "20.30"},
                ),
                _day(2, "Mardi", ferme="1"),
                _day(3, "Mercredi"),
            ]
        ),
        "Non",
    )
    assert week.as_dict() == {
        "Lundi": "06:30-20:30",
        "Mardi": "Fermé",
        "Mercredi": "Inconnu",
    }


def test_next_boundary_inside_a_slot_is_the_closing_time():
    week = parse_horaires(
        _raw(
            [_day(1, "Lundi", horaire={"@ouverture": "06.30", "@fermeture": "20.30"})]
        ),
        "Non",
    )
    assert week.next_boundary_after(
        datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    ) == datetime(2026, 8, 24, 20, 30, tzinfo=UTC)


def test_next_boundary_while_closed_is_the_next_opening():
    week = parse_horaires(
        _raw(
            [_day(1, "Lundi", horaire={"@ouverture": "06.30", "@fermeture": "20.30"})]
        ),
        "Non",
    )
    assert week.next_boundary_after(
        datetime(2026, 8, 24, 5, 0, tzinfo=UTC)
    ) == datetime(2026, 8, 24, 6, 30, tzinfo=UTC)


def test_next_boundary_rolls_over_to_the_next_day():
    week = parse_horaires(
        _raw(
            [
                _day(
                    1, "Lundi", horaire={"@ouverture": "06.30", "@fermeture": "20.30"}
                ),
                _day(
                    2, "Mardi", horaire={"@ouverture": "08.00", "@fermeture": "19.00"}
                ),
            ]
        ),
        "Non",
    )
    assert week.next_boundary_after(
        datetime(2026, 8, 24, 21, 0, tzinfo=UTC)
    ) == datetime(2026, 8, 25, 8, 0, tzinfo=UTC)


def test_next_boundary_on_a_24h_slot_is_the_next_midnight():
    week = parse_horaires(
        _raw(
            [_day(1, "Lundi", horaire={"@ouverture": "00.00", "@fermeture": "00.00"})]
        ),
        "Oui",
    )
    assert week.next_boundary_after(
        datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    ) == datetime(2026, 8, 25, 0, 0, tzinfo=UTC)


def test_next_boundary_skips_a_closed_day():
    week = parse_horaires(
        _raw(
            [
                _day(7, "Dimanche", ferme="1"),
                _day(
                    1, "Lundi", horaire={"@ouverture": "06.30", "@fermeture": "20.30"}
                ),
            ]
        ),
        "Non",
    )
    # Sunday noon -> Monday morning, the Sunday slots being ignored.
    assert week.next_boundary_after(
        datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    ) == datetime(2026, 8, 24, 6, 30, tzinfo=UTC)


def test_next_boundary_without_published_slots_is_none():
    week = parse_horaires(_raw([_day(1, "Lundi"), _day(2, "Mardi")]), "Non")
    assert week.next_boundary_after(datetime(2026, 8, 24, 12, 0, tzinfo=UTC)) is None
