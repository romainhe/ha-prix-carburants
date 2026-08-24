"""Parsing of the dataset's opening-hours payload.

Pure module: no Home Assistant import, so it can be unit-tested standalone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

# How far ahead next_boundary_after() looks for the next transition.
BOUNDARY_LOOKAHEAD_DAYS = 8

DAY_NAMES = {
    1: "Lundi",
    2: "Mardi",
    3: "Mercredi",
    4: "Jeudi",
    5: "Vendredi",
    6: "Samedi",
    7: "Dimanche",
}


@dataclass(frozen=True)
class DaySchedule:
    """One day of the week.

    `closed` is True when the dataset flags the day as closed. An empty
    `slots` on an open day means "open, hours not published" — callers must
    treat that as unknown, not as closed.
    """

    closed: bool
    slots: tuple[tuple[time, time], ...]


@dataclass(frozen=True)
class WeekSchedule:
    """A full week, keyed by ISO weekday (1 = Monday .. 7 = Sunday)."""

    days: dict[int, DaySchedule]
    automate_24_24: bool

    def _day_intervals(
        self, ref: date, tzinfo: tzinfo | None
    ) -> list[tuple[datetime, datetime]]:
        """Return the datetime intervals opened by the day `ref`."""
        day = self.days.get(ref.isoweekday())
        if day is None or day.closed:
            return []

        intervals: list[tuple[datetime, datetime]] = []
        for start, end in day.slots:
            start_dt = datetime.combine(ref, start, tzinfo=tzinfo)
            if end <= start:
                # 00.00-00.00 (24h) or an overnight slot.
                end_dt = datetime.combine(ref + timedelta(days=1), end, tzinfo=tzinfo)
            else:
                end_dt = datetime.combine(ref, end, tzinfo=tzinfo)
            intervals.append((start_dt, end_dt))
        return intervals

    def _intervals(self, moment: datetime) -> list[tuple[datetime, datetime]]:
        """Return datetime intervals covering `moment`'s day and the previous
        day's overnight spill-over."""
        intervals: list[tuple[datetime, datetime]] = []
        for offset in (-1, 0):
            ref = moment.date() + timedelta(days=offset)
            intervals.extend(self._day_intervals(ref, moment.tzinfo))
        return intervals

    def is_open_at(self, moment: datetime) -> bool | None:
        """Return True/False, or None when the schedule cannot answer."""
        day = self.days.get(moment.isoweekday())
        if day is None:
            return None
        if not day.closed and not day.slots:
            return None
        return any(start <= moment < end for start, end in self._intervals(moment))

    def next_boundary_after(self, moment: datetime) -> datetime | None:
        """Return the next opening or closing time strictly after `moment`.

        Looks a full week ahead, so a station closed on Sunday still finds
        Monday's opening. Returns None when the schedule publishes no slot at
        all — the caller must then not schedule anything.
        """
        boundaries: list[datetime] = []
        # Start one day back so an overnight slot's closing time is considered.
        for offset in range(-1, BOUNDARY_LOOKAHEAD_DAYS + 1):
            ref = moment.date() + timedelta(days=offset)
            for start_dt, end_dt in self._day_intervals(ref, moment.tzinfo):
                boundaries.extend(
                    boundary for boundary in (start_dt, end_dt) if boundary > moment
                )
        return min(boundaries) if boundaries else None

    def as_dict(self) -> dict[str, str]:
        """Return a human-readable week, for entity attributes."""
        out: dict[str, str] = {}
        for day_id in sorted(self.days):
            day = self.days[day_id]
            name = DAY_NAMES.get(day_id, str(day_id))
            if day.closed:
                out[name] = "Fermé"
            elif not day.slots:
                out[name] = "Inconnu"
            elif len(day.slots) == 1 and day.slots[0][0] == day.slots[0][1]:
                out[name] = "24h/24"
            else:
                out[name] = ", ".join(
                    f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
                    for start, end in day.slots
                )
        return out


def _parse_time(raw: str | None) -> time | None:
    """Parse an "HH.MM" string from the dataset."""
    if not raw:
        return None
    try:
        hours, _, minutes = raw.strip().partition(".")
        return time(int(hours), int(minutes or 0))
    except ValueError:
        return None


def _parse_slots(raw_horaire: object) -> tuple[tuple[time, time], ...]:
    """Parse the `horaire` key, which may be a single object or a list."""
    if isinstance(raw_horaire, dict):
        entries = [raw_horaire]
    elif isinstance(raw_horaire, list):
        entries = [item for item in raw_horaire if isinstance(item, dict)]
    else:
        return ()

    slots: list[tuple[time, time]] = []
    for entry in entries:
        start = _parse_time(entry.get("@ouverture"))
        end = _parse_time(entry.get("@fermeture"))
        if start is None or end is None:
            continue
        slots.append((start, end))
    return tuple(slots)


def parse_horaires(raw: str | None, automate_raw: str | None) -> WeekSchedule | None:
    """Parse the dataset's `horaires` string into a WeekSchedule.

    Returns None when the station publishes nothing usable.
    """
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    raw_days = payload.get("jour")
    if not isinstance(raw_days, list):
        return None

    days: dict[int, DaySchedule] = {}
    for raw_day in raw_days:
        if not isinstance(raw_day, dict):
            continue
        try:
            day_id = int(raw_day.get("@id"))
        except (TypeError, ValueError):
            continue
        if day_id not in DAY_NAMES:
            continue
        days[day_id] = DaySchedule(
            closed=str(raw_day.get("@ferme") or "").strip() == "1",
            slots=_parse_slots(raw_day.get("horaire")),
        )

    if not days:
        return None

    return WeekSchedule(
        days=days,
        automate_24_24=str(automate_raw or "").strip().lower() == "oui",
    )
