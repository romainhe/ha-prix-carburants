# ha-carburants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une intégration custom Home Assistant qui surveille le prix des carburants de stations-service françaises choisies par l'utilisateur et émet des events sur les baisses, hausses et ruptures.

**Architecture :** Un client HTTP mince au-dessus de l'API Opendatasoft du ministère de l'Économie, un `DataUpdateCoordinator` unique qui rafraîchit toutes les stations en une requête et calcule les events par diff avec le poll précédent, puis deux plateformes d'entités (`sensor`, `binary_sensor`) montées sur un device par station. Toute la logique de parsing est isolée dans des fonctions pures testables sans Home Assistant.

**Tech Stack :** Python 3.13, Home Assistant ≥ 2024.11, `aiohttp` (session partagée de HA), `voluptuous`, ruff, `pytest-homeassistant-custom-component`.

**Spec :** `docs/superpowers/specs/2026-08-24-ha-carburants-design.md`

## Global Constraints

- Domaine de l'intégration : `carburants`. Tous les préfixes d'events, clés de traduction et chemins en découlent.
- Version minimale de Home Assistant : `2024.11.0` (déclarée dans `hacs.json`). C'est la première version où `OptionsFlow.config_entry` est renseigné par le framework — le flow ne doit donc jamais l'assigner lui-même.
- Aucune dépendance Python externe : `manifest.json` garde `"requirements": []`. Utiliser la session `aiohttp` de HA via `async_get_clientsession`.
- Endpoint unique : `https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/records`. Timeout 10 s, `limit=100`.
- Carburants gérés, dans cet ordre, avec ces libellés exacts (ce sont ceux du dataset) : `gazole`→`Gazole`, `sp95`→`SP95`, `sp98`→`SP98`, `e10`→`E10`, `e85`→`E85`, `gplc`→`GPLc`.
- Un carburant est **suivi** pour une station si `prix != None` **ou** si sa rupture est `temporaire`. Une rupture `definitive` signifie que la station ne distribue pas ce carburant : aucune entité n'est créée.
- Ne jamais utiliser les champs de premier niveau `latitude` / `longitude` du dataset (chaînes en projection non-WGS84). Seul `geom` (`{"lon": float, "lat": float}`) fait foi.
- Types d'events : `carburants_price_changed` et `carburants_fuel_outage`. La direction est un champ de données, pas un type d'event.
- Le premier poll après démarrage amorce l'état en silence : aucun event n'est émis.
- Formateur et linter : `ruff`. Toute tâche se termine avec `ruff check .` et `ruff format --check .` au vert.
- Chaque tâche se termine par un commit. Messages en anglais, style Conventional Commits.

---

## File Structure

| Fichier | Responsabilité |
|---|---|
| `custom_components/carburants/const.py` | Domaine, URL, table des carburants, clés de config, valeurs par défaut, types d'events, constructeurs d'`unique_id` |
| `custom_components/carburants/horaires.py` | Parsing des horaires du dataset et calcul « ouvert à l'instant T ». Pur, sans import HA |
| `custom_components/carburants/api.py` | Client HTTP, construction des requêtes ODS, normalisation d'un enregistrement brut en `Station` |
| `custom_components/carburants/coordinator.py` | `DataUpdateCoordinator`, diff entre polls, émission des events |
| `custom_components/carburants/config_flow.py` | Config flow (recherche CP/ville ou rayon) et options flow (stations, réglages) |
| `custom_components/carburants/__init__.py` | `async_setup_entry` / `async_unload_entry`, `runtime_data`, `update_listener` |
| `custom_components/carburants/sensor.py` | Capteurs de prix par carburant + capteur diagnostic « dernière mise à jour » |
| `custom_components/carburants/binary_sensor.py` | Capteurs de rupture par carburant + capteur ouvert/fermé |
| `custom_components/carburants/strings.json`, `translations/{en,fr}.json` | Libellés du config flow et des entités |
| `tests/` | Suite pytest : parsing horaires, normalisation API, détection d'events, config flow |
| `scripts/{setup,develop}`, `.devcontainer/` | Boucle de dev locale, calquée sur `ha-powens` |
| `.github/workflows/{hassfest,hacs}.yml`, `hacs.json` | Validation CI et distribution HACS |

---

## Task 1: Scaffold, boucle de dev et harnais de test

**Files:**
- Create: `custom_components/carburants/__init__.py`
- Create: `custom_components/carburants/const.py`
- Create: `custom_components/carburants/manifest.json`
- Create: `hacs.json`
- Create: `pyproject.toml`
- Create: `requirements-test.txt`
- Create: `scripts/setup`, `scripts/develop`
- Create: `.devcontainer/devcontainer.json`
- Create: `.github/workflows/hassfest.yml`, `.github/workflows/hacs.yml`
- Create: `LICENSE`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_const.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: rien.
- Produces: `custom_components.carburants.const` exposant `DOMAIN: str`, `API_URL: str`, `API_TIMEOUT: int`, `SEARCH_LIMIT: int`, `FUELS: dict[str, str]`, `CONF_STATIONS`, `CONF_QUERY`, `CONF_SCAN_INTERVAL`, `CONF_PRICE_EVENT_THRESHOLD`, `DEFAULT_SCAN_INTERVAL`, `MIN_SCAN_INTERVAL`, `MAX_SCAN_INTERVAL`, `DEFAULT_RADIUS_M`, `MIN_RADIUS_M`, `MAX_RADIUS_M`, `DEFAULT_PRICE_EVENT_THRESHOLD`, `EVENT_PRICE_CHANGED`, `EVENT_FUEL_OUTAGE`, `OUTAGE_TEMPORARY`, `OUTAGE_DEFINITIVE`, et les fonctions `price_unique_id`, `outage_unique_id`, `open_unique_id`, `last_update_unique_id`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/__init__.py` (fichier vide) puis `tests/test_const.py` :

```python
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
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest tests/test_const.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'custom_components.carburants'` (ou une erreur de collecte pytest si les dépendances ne sont pas encore installées — installer d'abord via l'étape 3, puis relancer).

- [ ] **Step 3: Créer l'outillage et le scaffold**

`pyproject.toml` :

```toml
[tool.ruff]
target-version = "py313"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

`requirements-test.txt` :

```
homeassistant
pytest
pytest-homeassistant-custom-component
ruff
```

`tests/conftest.py` :

```python
"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    yield
```

`custom_components/carburants/manifest.json` :

```json
{
  "domain": "carburants",
  "name": "Carburants",
  "version": "0.1.0",
  "config_flow": true,
  "documentation": "https://github.com/romainhe/ha-carburants",
  "issue_tracker": "https://github.com/romainhe/ha-carburants/issues",
  "codeowners": ["@romainhe"],
  "iot_class": "cloud_polling",
  "integration_type": "service",
  "requirements": [],
  "dependencies": []
}
```

`hacs.json` :

```json
{
  "name": "Carburants",
  "render_readme": true,
  "homeassistant": "2024.11.0"
}
```

`custom_components/carburants/__init__.py` — pour l'instant un simple docstring, le câblage arrive en Task 6 :

```python
"""The Carburants integration."""
```

`custom_components/carburants/const.py` :

```python
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
```

`scripts/setup` (chmod +x) — copie adaptée de `ha-powens` :

```bash
#!/usr/bin/env bash
# Provision a local Home Assistant for the carburants integration.
#
# Works in two contexts:
#   - On a Mac host: creates ./.venv to keep installs out of system Python.
#   - In the devcontainer: uses the container's Python directly (no venv).
#
# Side effects:
#   - Installs (or upgrades) homeassistant, ruff and the test requirements.
#   - Symlinks ./custom_components into ./config/custom_components.
#   - Writes a minimal ./config/configuration.yaml with debug logging.

set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON:-python3}"

if [ -n "${REMOTE_CONTAINERS:-}" ] || [ -f /.dockerenv ]; then
  echo "[setup] Running inside a container — installing into container Python."
  PIP=("$PYTHON_BIN" -m pip)
else
  if [ ! -d .venv ]; then
    echo "[setup] Creating local virtualenv at .venv (host install)."
    "$PYTHON_BIN" -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  PIP=(python -m pip)
fi

"${PIP[@]}" install --upgrade pip
"${PIP[@]}" install --upgrade -r requirements-test.txt

mkdir -p config
if [ ! -e config/custom_components ]; then
  ln -s "$(pwd)/custom_components" config/custom_components
fi

if [ ! -f config/configuration.yaml ]; then
  cat > config/configuration.yaml <<'YAML'
default_config:

logger:
  default: info
  logs:
    custom_components.carburants: debug
YAML
fi

echo "[setup] Done. Run scripts/develop to start Home Assistant."
```

`scripts/develop` (chmod +x) :

```bash
#!/usr/bin/env bash
# Run a local Home Assistant instance against ./config with debug logging.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d config ]; then
  bash scripts/setup
fi

if [ -z "${REMOTE_CONTAINERS:-}" ] && [ ! -f /.dockerenv ]; then
  if [ ! -d .venv ]; then
    echo "Run scripts/setup first." >&2
    exit 1
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

exec hass --config ./config --debug
```

`.devcontainer/devcontainer.json` : copier celui de `ha-powens` en remplaçant `"name": "ha-powens"` par `"name": "ha-carburants"`.

`.github/workflows/hassfest.yml` :

```yaml
name: Validate with hassfest

on:
  push:
  pull_request:
  schedule:
    - cron: "0 4 * * *"

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: home-assistant/actions/hassfest@master
```

`.github/workflows/hacs.yml` :

```yaml
name: HACS validation

on:
  push:
  pull_request:
  schedule:
    - cron: "0 4 * * *"

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hacs/action@main
        with:
          category: integration
```

`LICENSE` : MIT, titulaire « Romain Henriques », année 2026.

Ajouter à `.gitignore` (le fichier existe déjà) les entrées manquantes : `.pytest_cache/`, `.mypy_cache/`, `htmlcov/`, `.coverage`.

Puis installer l'environnement : `bash scripts/setup`.

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `source .venv/bin/activate && python -m pytest tests/test_const.py -v && ruff check . && ruff format --check .`
Expected: 3 tests PASS, ruff sans erreur.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: scaffold integration, dev loop and test harness"
```

---

## Task 2: Parsing des horaires (`horaires.py`)

**Files:**
- Create: `custom_components/carburants/horaires.py`
- Test: `tests/test_horaires.py`

**Interfaces:**
- Consumes: rien (module pur, aucun import Home Assistant).
- Produces:
  - `DaySchedule(closed: bool, slots: tuple[tuple[time, time], ...])`
  - `WeekSchedule(days: dict[int, DaySchedule], automate_24_24: bool)` avec `is_open_at(moment: datetime) -> bool | None`, `next_boundary_after(moment: datetime) -> datetime | None` et `as_dict() -> dict[str, str]`
  - `parse_horaires(raw: str | None, automate_raw: str | None) -> WeekSchedule | None`

Règles issues du flux réel :

- `raw` vaut `None` ou `""` → `parse_horaires` renvoie `None` (la station ne publie pas d'horaires).
- `raw` est une **chaîne** contenant du JSON : `{"@automate-24-24": "1", "jour": [{"@id": "1", "@nom": "Lundi", "@ferme": "", "horaire": {...}}, ...]}`.
- `"@ferme"` vaut `"1"` quand le jour est fermé, `""` sinon.
- `horaire` est **soit un objet unique soit une liste d'objets** `{"@ouverture": "06.30", "@fermeture": "20.30"}`. Le séparateur décimal est un point, pas deux-points.
- Un jour ouvert sans clé `horaire` signifie « ouvert, horaires non publiés » → `slots` vide → `is_open_at` renvoie `None` pour ce jour.
- `00.00 → 00.00` signifie ouvert 24 h.
- Une fermeture antérieure à l'ouverture (`22.00 → 06.00`) déborde sur le lendemain.
- `automate_raw` est la chaîne `"Oui"` / `"Non"` du champ `horaires_automate_24_24`.

`next_boundary_after(moment)` renvoie le plus petit début ou fin de créneau
strictement postérieur à `moment`, déduit des mêmes intervalles que ceux servant
à `is_open_at`. La recherche dépasse le jour courant — une station fermée le
dimanche doit trouver l'ouverture du lundi — et renvoie `None` quand aucune
transition n'est connue : jour ouvert sans créneau publié, ou station sans
horaires. C'est cette valeur qui arme le réveil du capteur ouvert/fermé en
Task 7.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_horaires.py` :

```python
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
        _raw([_day(1, "Lundi", horaire={"@ouverture": "06.30", "@fermeture": "20.30"})]),
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
        _raw([_day(1, "Lundi", horaire={"@ouverture": "00.00", "@fermeture": "00.00"})]),
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
                    7, "Dimanche", horaire={"@ouverture": "22.00", "@fermeture": "06.00"}
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
        _raw([_day(1, "Lundi", horaire={"@ouverture": "06.30", "@fermeture": "20.30"})]),
        "Non",
    )
    assert week.next_boundary_after(
        datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    ) == datetime(2026, 8, 24, 20, 30, tzinfo=UTC)


def test_next_boundary_while_closed_is_the_next_opening():
    week = parse_horaires(
        _raw([_day(1, "Lundi", horaire={"@ouverture": "06.30", "@fermeture": "20.30"})]),
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
        _raw([_day(1, "Lundi", horaire={"@ouverture": "00.00", "@fermeture": "00.00"})]),
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
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest tests/test_horaires.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'custom_components.carburants.horaires'`

- [ ] **Step 3: Implémenter `horaires.py`**

```python
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
                    boundary
                    for boundary in (start_dt, end_dt)
                    if boundary > moment
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
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest tests/test_horaires.py -v && ruff check . && ruff format --check .`
Expected: 16 tests PASS

- [ ] **Step 5: Commit**

```bash
git add custom_components/carburants/horaires.py tests/test_horaires.py
git commit -m "feat: parse station opening hours and next transition"
```

---

## Task 3: Client API et normalisation (`api.py`)

**Files:**
- Create: `custom_components/carburants/api.py`
- Create: `tests/fixtures/__init__.py`, `tests/fixtures/records.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `const.API_URL`, `const.API_TIMEOUT`, `const.SEARCH_LIMIT`, `const.FUELS`, `const.OUTAGE_TEMPORARY`, `const.OUTAGE_DEFINITIVE` ; `horaires.parse_horaires`, `horaires.WeekSchedule`.
- Produces:
  - `CarburantsApiError(Exception)`
  - `FuelState(fuel: str, price: float | None, updated_at: datetime | None, outage_type: str | None, outage_since: datetime | None)` avec `in_outage: bool`
  - `Station(id: str, address: str, city: str, postal_code: str, latitude: float | None, longitude: float | None, highway: bool, fuels: dict[str, FuelState], opening_hours: WeekSchedule | None, automate_24_24: bool, distance_km: float | None)` avec `name: str`, `tracked_fuels: dict[str, FuelState]`, `last_update: datetime | None`
  - `parse_station(record: dict) -> Station`
  - `CarburantsApi(session)` avec `async_search_text(query: str) -> list[Station]`, `async_search_geo(latitude: float, longitude: float, radius_m: int) -> list[Station]`, `async_fetch(station_ids: list[str]) -> list[Station]`

Règles de normalisation, toutes validées sur le flux réel :

- `id` est un entier dans le JSON → toujours le convertir en `str`.
- La position vient de `geom` (`{"lon": ..., "lat": ...}`), jamais des champs `latitude` / `longitude`.
- `<fuel>_prix` est un float ou `null` ; `<fuel>_maj`, `<fuel>_rupture_debut` sont des dates ISO avec offset ou `null`.
- **Rupture en cours** pour un carburant : `<fuel>_rupture_type` non nul **et** `<fuel>_prix` nul. Si `<fuel>_rupture_type` est nul alors que le libellé du carburant apparaît dans `carburants_rupture_temporaire` ou `carburants_rupture_definitive` (chaînes `;`-séparées), on retient respectivement `temporaire` / `definitive`. Sinon pas de rupture.
- `tracked_fuels` = carburants avec un prix **ou** en rupture `temporaire`. Une rupture `definitive` signifie « non distribué » → exclu.
- `highway` = `pop == "A"`.
- `distance_km` n'est renseigné que par `async_search_geo`, calculé côté client par haversine à partir de `geom`, et les résultats sont triés par distance croissante.
- Toute erreur `aiohttp`, tout timeout et tout statut non-2xx lèvent `CarburantsApiError`.
- Dans les tests, `aioclient_mock.mock_calls[i]` est un tuple `(method, url, data, headers)` où `url` est une `yarl.URL` incluant la query string : les paramètres se relisent via `mock_calls[i][1].query["where"]`.

- [ ] **Step 1: Écrire les fixtures et les tests qui échouent**

Créer `tests/fixtures/__init__.py` (vide) puis `tests/fixtures/records.py` — trois enregistrements capturés depuis l'API réelle, réduits aux champs utiles :

```python
"""Raw API records captured from the live dataset (trimmed to used fields)."""

# Station selling Gazole, E10 temporarily out, SP95/E85/GPLc definitively out.
STATION_WITH_PRICES = {
    "id": 67000002,
    "cp": "67000",
    "pop": "R",
    "adresse": "Route de la Wantzenau",
    "ville": "Strasbourg",
    "geom": {"lon": 7.7822163708573, "lat": 48.611993985705006},
    "horaires": (
        '{"@automate-24-24": "", "jour": [{"@id": "1", "@nom": "Lundi", '
        '"@ferme": "", "horaire": {"@ouverture": "06.30", "@fermeture": "20.30"}}]}'
    ),
    "horaires_automate_24_24": "Non",
    "gazole_prix": 2.299,
    "gazole_maj": "2026-08-24T10:25:29+00:00",
    "sp95_prix": None,
    "sp95_maj": None,
    "sp98_prix": None,
    "sp98_maj": None,
    "e10_prix": None,
    "e10_maj": None,
    "e85_prix": None,
    "e85_maj": None,
    "gplc_prix": None,
    "gplc_maj": None,
    "e10_rupture_type": "temporaire",
    "e10_rupture_debut": "2026-08-24T08:38:17+00:00",
    "sp98_rupture_type": "temporaire",
    "sp98_rupture_debut": "2026-08-19T09:31:37+00:00",
    "sp95_rupture_type": "definitive",
    "sp95_rupture_debut": "2020-12-19T08:46:10+00:00",
    "e85_rupture_type": "definitive",
    "e85_rupture_debut": "2020-12-19T08:46:10+00:00",
    "gplc_rupture_type": "definitive",
    "gplc_rupture_debut": "2020-12-19T08:46:10+00:00",
    "gazole_rupture_type": None,
    "gazole_rupture_debut": None,
    "carburants_rupture_temporaire": "E10;SP98",
    "carburants_rupture_definitive": "SP95;E85;GPLc",
}

# Station publishing no hours, no prices, and only the aggregate outage lists.
STATION_NO_HOURS = {
    "id": 67000026,
    "cp": "67000",
    "pop": "A",
    "adresse": "49 RTE DU RHIN",
    "ville": "Strasbourg",
    "geom": {"lon": 7.78835, "lat": 48.57287},
    "horaires": None,
    "horaires_automate_24_24": "Non",
    "gazole_prix": None,
    "gazole_maj": None,
    "sp95_prix": None,
    "sp95_maj": None,
    "sp98_prix": None,
    "sp98_maj": None,
    "e10_prix": None,
    "e10_maj": None,
    "e85_prix": None,
    "e85_maj": None,
    "gplc_prix": None,
    "gplc_maj": None,
    "gazole_rupture_type": None,
    "gazole_rupture_debut": None,
    "e10_rupture_type": None,
    "e10_rupture_debut": None,
    "carburants_rupture_temporaire": "Gazole;E10",
    "carburants_rupture_definitive": None,
}

# Minimal record: no geom, no outage information at all.
STATION_MINIMAL = {
    "id": 60350003,
    "cp": "60350",
    "pop": "R",
    "adresse": "1 rue de la Gare",
    "ville": "Cuise-la-Motte",
    "geom": None,
    "horaires": None,
    "horaires_automate_24_24": None,
    "gazole_prix": 2.207,
    "gazole_maj": "2026-08-24T06:00:00+00:00",
    "e10_prix": 1.99,
    "e10_maj": "2026-08-24T07:00:00+00:00",
    "carburants_rupture_temporaire": None,
    "carburants_rupture_definitive": None,
}
```

Créer `tests/test_api.py` :

```python
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
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'custom_components.carburants.api'`

- [ ] **Step 3: Implémenter `api.py`**

```python
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
        where = (
            f"distance(geom, geom'POINT({longitude} {latitude})', {radius_m}m)"
        )
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
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest tests/test_api.py -v && ruff check . && ruff format --check .`
Expected: 15 tests PASS

- [ ] **Step 5: Commit**

```bash
git add custom_components/carburants/api.py tests/test_api.py tests/fixtures
git commit -m "feat: add dataset API client and record normalisation"
```

---

## Task 4: Coordinator et émission des events

**Files:**
- Create: `custom_components/carburants/coordinator.py`
- Test: `tests/test_coordinator.py`

**Interfaces:**
- Consumes: `api.CarburantsApi`, `api.CarburantsApiError`, `api.Station`, `api.FuelState` ; `const.{DOMAIN, EVENT_PRICE_CHANGED, EVENT_FUEL_OUTAGE, FUELS, price_unique_id, outage_unique_id}`.
- Produces: `CarburantsCoordinator(hass, entry, api, station_ids, scan_interval, price_threshold)`, sous-classe de `DataUpdateCoordinator[dict[str, Station]]`. `coordinator.data` est un `dict[station_id, Station]`. Attribut public `station_ids: list[str]`.

Comportement :

1. Chaque poll appelle `api.async_fetch(self.station_ids)`. Une `CarburantsApiError` est convertie en `UpdateFailed`.
2. Le premier poll enregistre l'état et n'émet rien (`_primed`).
3. Ensuite, pour chaque station présente **dans les deux** snapshots, et pour chaque carburant présent dans `tracked_fuels` du nouveau snapshot :
   - **prix** : si l'ancien et le nouveau prix sont tous deux non nuls et que `abs(delta) >= price_threshold`, émettre `carburants_price_changed` ;
   - **rupture** : si `in_outage` bascule, émettre `carburants_fuel_outage` avec `state` = `start` ou `end`.
4. `entity_id` est résolu au moment de l'émission via le registre d'entités ; il vaut `None` si l'entité n'existe pas encore.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_coordinator.py` :

```python
"""Tests for the coordinator's polling and event detection."""

from datetime import UTC, datetime, timedelta

import pytest
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
from homeassistant.helpers.update_coordinator import UpdateFailed


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
    coordinator = _coordinator(
        hass, FakeApi([[_station(1.899)], [_station(1.859)]])
    )

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
    coordinator = _coordinator(
        hass, FakeApi([[_station(1.859)], [_station(1.899)]])
    )

    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["direction"] == "up"


async def test_change_below_threshold_is_ignored(hass):
    events = async_capture_events(hass, EVENT_PRICE_CHANGED)
    coordinator = _coordinator(
        hass, FakeApi([[_station(1.8990)], [_station(1.8995)]])
    )

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
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest tests/test_coordinator.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'custom_components.carburants.coordinator'`

- [ ] **Step 3: Implémenter `coordinator.py`**

```python
"""Data update coordinator and event emission for Carburants."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CarburantsApi, CarburantsApiError, FuelState, Station
from .const import (
    DOMAIN,
    EVENT_FUEL_OUTAGE,
    EVENT_PRICE_CHANGED,
    FUELS,
    outage_unique_id,
    price_unique_id,
)

_LOGGER = logging.getLogger(__name__)


class CarburantsCoordinator(DataUpdateCoordinator[dict[str, Station]]):
    """Poll every configured station in one request and diff the result."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: CarburantsApi,
        station_ids: list[str],
        scan_interval: timedelta,
        price_threshold: float,
    ) -> None:
        """Initialise the coordinator."""
        self.api = api
        self.station_ids = station_ids
        self._price_threshold = price_threshold
        self._previous: dict[str, dict[str, FuelState]] = {}
        self._primed = False

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Station]:
        """Fetch every station and emit events for what changed."""
        try:
            stations = await self.api.async_fetch(self.station_ids)
        except CarburantsApiError as err:
            raise UpdateFailed(str(err)) from err

        data = {station.id: station for station in stations}
        self._process_events(data)
        return data

    def _process_events(self, data: dict[str, Station]) -> None:
        """Diff against the previous poll and fire the resulting events."""
        previous = self._previous
        self._previous = {
            station_id: dict(station.fuels) for station_id, station in data.items()
        }

        if not self._primed:
            self._primed = True
            return

        for station_id, station in data.items():
            old_fuels = previous.get(station_id)
            if old_fuels is None:
                continue
            for fuel, state in station.tracked_fuels.items():
                old_state = old_fuels.get(fuel)
                if old_state is None:
                    continue
                self._fire_price_event(station, fuel, old_state, state)
                self._fire_outage_event(station, fuel, old_state, state)

    def _entity_id(self, platform: str, unique_id: str) -> str | None:
        """Resolve an entity_id from a unique_id, or None if not registered."""
        registry = er.async_get(self.hass)
        return registry.async_get_entity_id(platform, DOMAIN, unique_id)

    def _base_payload(self, station: Station, fuel: str) -> dict:
        """Build the station/fuel fields shared by both event types."""
        return {
            "station_id": station.id,
            "station_name": station.name,
            "address": station.address,
            "city": station.city,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "fuel": fuel,
            "fuel_label": FUELS[fuel],
        }

    def _fire_price_event(
        self, station: Station, fuel: str, old: FuelState, new: FuelState
    ) -> None:
        """Fire carburants_price_changed when the price moved enough."""
        if old.price is None or new.price is None:
            return
        delta = round(new.price - old.price, 4)
        if abs(delta) < self._price_threshold:
            return

        payload = self._base_payload(station, fuel) | {
            "entity_id": self._entity_id(
                "sensor", price_unique_id(station.id, fuel)
            ),
            "direction": "down" if delta < 0 else "up",
            "old_price": old.price,
            "new_price": new.price,
            "delta": delta,
            "delta_percent": round(delta / old.price * 100, 2),
            "updated_at": new.updated_at.isoformat() if new.updated_at else None,
        }
        _LOGGER.debug("Firing %s: %s", EVENT_PRICE_CHANGED, payload)
        self.hass.bus.async_fire(EVENT_PRICE_CHANGED, payload)

    def _fire_outage_event(
        self, station: Station, fuel: str, old: FuelState, new: FuelState
    ) -> None:
        """Fire carburants_fuel_outage when the outage flag flipped."""
        if old.in_outage == new.in_outage:
            return

        since = new.outage_since or old.outage_since
        payload = self._base_payload(station, fuel) | {
            "entity_id": self._entity_id(
                "binary_sensor", outage_unique_id(station.id, fuel)
            ),
            "state": "start" if new.in_outage else "end",
            "outage_type": new.outage_type or old.outage_type,
            "since": since.isoformat() if since else None,
        }
        _LOGGER.debug("Firing %s: %s", EVENT_FUEL_OUTAGE, payload)
        self.hass.bus.async_fire(EVENT_FUEL_OUTAGE, payload)
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest tests/test_coordinator.py -v && ruff check . && ruff format --check .`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add custom_components/carburants/coordinator.py tests/test_coordinator.py
git commit -m "feat: add coordinator with price and outage events"
```

---

## Task 5: Config flow, options flow et traductions

**Files:**
- Create: `custom_components/carburants/config_flow.py`
- Create: `custom_components/carburants/strings.json`
- Create: `custom_components/carburants/translations/en.json`
- Create: `custom_components/carburants/translations/fr.json`
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `api.CarburantsApi`, `api.CarburantsApiError`, `api.Station` ; `const.*`.
- Produces: `CarburantsConfigFlow(ConfigFlow, domain=DOMAIN)` avec `VERSION = 1`, et `CarburantsOptionsFlow(OptionsFlow)`. L'entrée créée porte `data = {CONF_STATIONS: list[str]}` et `options = {CONF_SCAN_INTERVAL: int, CONF_PRICE_EVENT_THRESHOLD: float}`.

Parcours :

- `user` → `async_show_menu(menu_options=["recherche", "proximite"])`
- `recherche` → champ `query` (texte). Résultats stockés sur le flow, puis `stations`.
- `proximite` → champ `location` (`selector.LocationSelector` avec `radius=True`), pré-rempli depuis `hass.config`, rayon `DEFAULT_RADIUS_M` mètres borné à `[MIN_RADIUS_M, MAX_RADIUS_M]`. Puis `stations`.
- `stations` → `cv.multi_select` des résultats. Sélection vide → erreur `no_station_selected`. Zéro résultat → l'étape de recherche est réaffichée avec l'erreur `no_results`.
- Erreur API pendant une recherche → erreur `cannot_connect` sur le formulaire de recherche.
- L'entrée est unique : `async_set_unique_id(DOMAIN)` puis `_abort_if_unique_id_configured()`.

Options flow : `init` → `async_show_menu(["stations", "reglages"])`. La branche `stations` rejoue les mêmes étapes de recherche puis affiche un `multi_select` fusionnant les stations déjà suivies (pré-cochées) et les nouveaux résultats. La branche `reglages` écrit `scan_interval` et `price_event_threshold` dans les options.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_config_flow.py` :

```python
"""Tests for the config and options flows."""

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.carburants.api import CarburantsApiError
from custom_components.carburants.const import (
    CONF_PRICE_EVENT_THRESHOLD,
    CONF_SCAN_INTERVAL,
    CONF_STATIONS,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from tests.fixtures.records import STATION_NO_HOURS, STATION_WITH_PRICES

from custom_components.carburants.api import parse_station

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
    with patch(
        "custom_components.carburants.config_flow.CarburantsApi.async_search_text",
        AsyncMock(return_value=[STATIONS[0]]),
    ), patch(
        "custom_components.carburants.config_flow.CarburantsApi.async_fetch",
        AsyncMock(return_value=[STATIONS[1]]),
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
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest tests/test_config_flow.py -v`
Expected: FAIL — le flow n'existe pas, `async_init` renvoie une erreur de handler inconnu.

- [ ] **Step 3: Implémenter `config_flow.py` et les traductions**

```python
"""Config and options flows for Carburants."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LOCATION
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CarburantsApi, CarburantsApiError, Station
from .const import (
    CONF_PRICE_EVENT_THRESHOLD,
    CONF_QUERY,
    CONF_SCAN_INTERVAL,
    CONF_STATIONS,
    DEFAULT_PRICE_EVENT_THRESHOLD,
    DEFAULT_RADIUS_M,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FUELS,
    MAX_RADIUS_M,
    MAX_SCAN_INTERVAL,
    MIN_RADIUS_M,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _station_label(station: Station) -> str:
    """Build the label shown in the station picker."""
    parts = [f"{station.address}, {station.city}"]
    if station.distance_km is not None:
        parts.append(f"{station.distance_km:.1f} km".replace(".", ","))
    priced = [
        f"{FUELS[fuel]} {state.price:.3f} €".replace(".", ",")
        for fuel, state in station.tracked_fuels.items()
        if state.price is not None
    ]
    if priced:
        parts.append(" · ".join(priced))
    return " · ".join(parts)


class _SearchMixin:
    """Shared search steps for the config and options flows."""

    hass: Any
    _results: dict[str, Station]

    def _api(self) -> CarburantsApi:
        return CarburantsApi(async_get_clientsession(self.hass))

    async def _async_run_search(
        self, coro
    ) -> tuple[dict[str, str], list[Station]]:
        """Run a search coroutine, mapping API failures to form errors."""
        try:
            stations = await coro
        except CarburantsApiError:
            return {"base": "cannot_connect"}, []
        if not stations:
            return {"base": "no_results"}, []
        return {}, stations


class CarburantsConfigFlow(ConfigFlow, _SearchMixin, domain=DOMAIN):
    """Handle the initial configuration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._results: dict[str, Station] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return CarburantsOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the two search methods."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_show_menu(
            step_id="user", menu_options=["recherche", "proximite"]
        )

    async def async_step_recherche(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search by postal code or city."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, stations = await self._async_run_search(
                self._api().async_search_text(user_input[CONF_QUERY])
            )
            if not errors:
                self._results = {station.id: station for station in stations}
                return await self.async_step_stations()

        return self.async_show_form(
            step_id="recherche",
            data_schema=vol.Schema({vol.Required(CONF_QUERY): cv.string}),
            errors=errors,
        )

    async def async_step_proximite(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search within a radius of a point."""
        errors: dict[str, str] = {}
        if user_input is not None:
            location = user_input[CONF_LOCATION]
            radius = int(
                min(max(location.get("radius", DEFAULT_RADIUS_M), MIN_RADIUS_M),
                    MAX_RADIUS_M)
            )
            errors, stations = await self._async_run_search(
                self._api().async_search_geo(
                    location["latitude"], location["longitude"], radius
                ),
            )
            if not errors:
                self._results = {station.id: station for station in stations}
                return await self.async_step_stations()

        return self.async_show_form(
            step_id="proximite",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOCATION,
                        default={
                            "latitude": self.hass.config.latitude,
                            "longitude": self.hass.config.longitude,
                            "radius": DEFAULT_RADIUS_M,
                        },
                    ): selector.LocationSelector(
                        selector.LocationSelectorConfig(radius=True)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_stations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the stations to monitor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get(CONF_STATIONS) or []
            if not selected:
                errors["base"] = "no_station_selected"
            else:
                return self.async_create_entry(
                    title="Carburants", data={CONF_STATIONS: list(selected)}
                )

        options = {
            station_id: _station_label(station)
            for station_id, station in self._results.items()
        }
        return self.async_show_form(
            step_id="stations",
            data_schema=vol.Schema(
                {vol.Required(CONF_STATIONS, default=[]): cv.multi_select(options)}
            ),
            errors=errors,
        )


class CarburantsOptionsFlow(OptionsFlow, _SearchMixin):
    """Handle station management and settings."""

    def __init__(self) -> None:
        """Initialise flow state."""
        self._results: dict[str, Station] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the two option branches."""
        return self.async_show_menu(
            step_id="init", menu_options=["stations", "reglages"]
        )

    async def async_step_stations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the two search methods for adding stations."""
        return self.async_show_menu(
            step_id="stations", menu_options=["recherche", "proximite"]
        )

    async def async_step_recherche(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search by postal code or city."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, stations = await self._async_run_search(
                self._api().async_search_text(user_input[CONF_QUERY])
            )
            if not errors:
                self._results = {station.id: station for station in stations}
                return await self.async_step_selection()

        return self.async_show_form(
            step_id="recherche",
            data_schema=vol.Schema({vol.Required(CONF_QUERY): cv.string}),
            errors=errors,
        )

    async def async_step_proximite(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search within a radius of a point."""
        errors: dict[str, str] = {}
        if user_input is not None:
            location = user_input[CONF_LOCATION]
            radius = int(
                min(max(location.get("radius", DEFAULT_RADIUS_M), MIN_RADIUS_M),
                    MAX_RADIUS_M)
            )
            errors, stations = await self._async_run_search(
                self._api().async_search_geo(
                    location["latitude"], location["longitude"], radius
                ),
            )
            if not errors:
                self._results = {station.id: station for station in stations}
                return await self.async_step_selection()

        return self.async_show_form(
            step_id="proximite",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOCATION,
                        default={
                            "latitude": self.hass.config.latitude,
                            "longitude": self.hass.config.longitude,
                            "radius": DEFAULT_RADIUS_M,
                        },
                    ): selector.LocationSelector(
                        selector.LocationSelectorConfig(radius=True)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_selection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Merge already-tracked stations with the new search hits."""
        current: list[str] = list(self.config_entry.data.get(CONF_STATIONS, []))

        if user_input is not None:
            selected = user_input.get(CONF_STATIONS) or []
            if not selected:
                return await self._async_show_selection(
                    current, {"base": "no_station_selected"}
                )
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_STATIONS: list(selected)},
            )
            return self.async_create_entry(data=dict(self.config_entry.options))

        return await self._async_show_selection(current, {})

    async def _async_show_selection(
        self, current: list[str], errors: dict[str, str]
    ) -> ConfigFlowResult:
        """Render the merged station picker."""
        options = dict(self._results)
        missing = [station_id for station_id in current if station_id not in options]
        if missing:
            try:
                for station in await self._api().async_fetch(missing):
                    options[station.id] = station
            except CarburantsApiError:
                _LOGGER.debug("Could not refresh labels for tracked stations")

        labels = {
            station_id: _station_label(station)
            for station_id, station in options.items()
        }
        for station_id in current:
            labels.setdefault(station_id, station_id)

        return self.async_show_form(
            step_id="selection",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STATIONS, default=current): cv.multi_select(
                        labels
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reglages(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit polling interval and price-event threshold."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="reglages",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                    vol.Required(
                        CONF_PRICE_EVENT_THRESHOLD,
                        default=options.get(
                            CONF_PRICE_EVENT_THRESHOLD,
                            DEFAULT_PRICE_EVENT_THRESHOLD,
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=0.5)),
                }
            ),
        )
```

`custom_components/carburants/strings.json` :

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Carburants",
        "description": "How do you want to find the stations to monitor?",
        "menu_options": {
          "recherche": "Search by postal code or city",
          "proximite": "Search around a location"
        }
      },
      "recherche": {
        "title": "Search a station",
        "data": { "query": "Postal code or city" }
      },
      "proximite": {
        "title": "Search around a location",
        "data": { "location": "Location and radius" }
      },
      "stations": {
        "title": "Stations to monitor",
        "data": { "stations": "Stations" }
      }
    },
    "error": {
      "cannot_connect": "[%key:common::config_flow::error::cannot_connect%]",
      "no_results": "No station found for this search.",
      "no_station_selected": "Select at least one station."
    },
    "abort": {
      "single_instance_allowed": "[%key:common::config_flow::abort::single_instance_allowed%]"
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "Carburants",
        "menu_options": {
          "stations": "Add or remove stations",
          "reglages": "Settings"
        }
      },
      "stations": {
        "title": "Add or remove stations",
        "menu_options": {
          "recherche": "Search by postal code or city",
          "proximite": "Search around a location"
        }
      },
      "recherche": {
        "title": "Search a station",
        "data": { "query": "Postal code or city" }
      },
      "proximite": {
        "title": "Search around a location",
        "data": { "location": "Location and radius" }
      },
      "selection": {
        "title": "Stations to monitor",
        "description": "Unchecking a station removes it and its entities.",
        "data": { "stations": "Stations" }
      },
      "reglages": {
        "title": "Settings",
        "data": {
          "scan_interval": "Polling interval (minutes)",
          "price_event_threshold": "Minimum price change to fire an event (€/L)"
        }
      }
    },
    "error": {
      "cannot_connect": "[%key:common::config_flow::error::cannot_connect%]",
      "no_results": "No station found for this search.",
      "no_station_selected": "Select at least one station."
    }
  },
  "entity": {
    "sensor": {
      "gazole": { "name": "Gazole" },
      "sp95": { "name": "SP95" },
      "sp98": { "name": "SP98" },
      "e10": { "name": "E10" },
      "e85": { "name": "E85" },
      "gplc": { "name": "GPLc" },
      "last_update": { "name": "Last update" }
    },
    "binary_sensor": {
      "gazole_outage": { "name": "Gazole outage" },
      "sp95_outage": { "name": "SP95 outage" },
      "sp98_outage": { "name": "SP98 outage" },
      "e10_outage": { "name": "E10 outage" },
      "e85_outage": { "name": "E85 outage" },
      "gplc_outage": { "name": "GPLc outage" },
      "open": { "name": "Open" }
    }
  }
}
```

`translations/en.json` : copie conforme de `strings.json`.

`translations/fr.json` : même structure, textes français —
`user.description` : « Comment voulez-vous trouver les stations à surveiller ? » ;
`recherche` : « Rechercher une station » / `query` : « Code postal ou ville » ;
`proximite` : « Rechercher autour d'un point » / `location` : « Position et rayon » ;
`stations` / `selection` : « Stations à surveiller », description « Décocher une station la retire ainsi que ses entités. » ;
`reglages` : « Réglages », `scan_interval` : « Intervalle de relève (minutes) », `price_event_threshold` : « Variation minimale pour émettre un event (€/L) » ;
erreurs : `no_results` « Aucune station trouvée pour cette recherche. », `no_station_selected` « Sélectionnez au moins une station. » ;
entités : `last_update` « Dernière mise à jour », `<fuel>_outage` « Rupture <Label> », `open` « Ouvert ».
Conserver les références `[%key:common::...%]` telles quelles pour `cannot_connect` et `single_instance_allowed`.

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest tests/test_config_flow.py -v && ruff check . && ruff format --check .`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add custom_components/carburants/config_flow.py custom_components/carburants/strings.json custom_components/carburants/translations tests/test_config_flow.py
git commit -m "feat: add config and options flows"
```

---

## Task 6: Câblage de l'entrée et plateforme `sensor`

**Files:**
- Modify: `custom_components/carburants/__init__.py`
- Create: `custom_components/carburants/entity.py`
- Create: `custom_components/carburants/sensor.py`
- Test: `tests/test_sensor.py`

**Interfaces:**
- Consumes: `coordinator.CarburantsCoordinator`, `api.CarburantsApi`, `api.Station`, `const.*`.
- Produces:
  - `__init__`: `CarburantsRuntimeData(coordinator)`, `CarburantsConfigEntry = ConfigEntry[CarburantsRuntimeData]`, `async_setup_entry`, `async_unload_entry`, `PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]`
  - `entity.py`: `CarburantsStationEntity(CoordinatorEntity[CarburantsCoordinator])` exposant `station: Station | None`, `available`, `device_info`, et le constructeur `(coordinator, station_id, unique_id)`
  - `sensor.py`: `CarburantsFuelPriceSensor`, `CarburantsLastUpdateSensor`

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_sensor.py` :

```python
"""Tests for the sensor platform."""

from unittest.mock import AsyncMock, patch

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

    state = hass.states.get(
        "sensor.route_de_la_wantzenau_strasbourg_last_update"
    )
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
    assert hass.states.get("sensor.route_de_la_wantzenau_strasbourg_gazole") is None
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest tests/test_sensor.py -v`
Expected: FAIL — `async_setup` renvoie False, aucune entité n'est créée.

- [ ] **Step 3: Implémenter le câblage, `entity.py` et `sensor.py`**

`custom_components/carburants/__init__.py` :

```python
"""The Carburants integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CarburantsApi
from .const import (
    CONF_PRICE_EVENT_THRESHOLD,
    CONF_SCAN_INTERVAL,
    CONF_STATIONS,
    DEFAULT_PRICE_EVENT_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import CarburantsCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


@dataclass
class CarburantsRuntimeData:
    """Runtime objects attached to the config entry."""

    coordinator: CarburantsCoordinator


CarburantsConfigEntry = ConfigEntry[CarburantsRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: CarburantsConfigEntry
) -> bool:
    """Set up Carburants from a config entry."""
    api = CarburantsApi(async_get_clientsession(hass))
    coordinator = CarburantsCoordinator(
        hass,
        entry,
        api,
        list(entry.data.get(CONF_STATIONS, [])),
        timedelta(
            minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        ),
        entry.options.get(
            CONF_PRICE_EVENT_THRESHOLD, DEFAULT_PRICE_EVENT_THRESHOLD
        ),
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = CarburantsRuntimeData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: CarburantsConfigEntry
) -> None:
    """Reload the entry when stations or settings change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: CarburantsConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

`custom_components/carburants/entity.py` :

```python
"""Shared entity base for Carburants."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Station
from .const import DOMAIN
from .coordinator import CarburantsCoordinator


class CarburantsStationEntity(CoordinatorEntity[CarburantsCoordinator]):
    """Base entity bound to one station device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CarburantsCoordinator,
        station_id: str,
        unique_id: str,
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._station_id = station_id
        self._attr_unique_id = unique_id

        station = coordinator.data.get(station_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, station_id)},
            name=station.name if station else station_id,
            manufacturer="Ministère de l'Économie",
            model="prix-carburants.gouv.fr",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.prix-carburants.gouv.fr/",
        )

    @property
    def station(self) -> Station | None:
        """Return the current station data, or None if it vanished."""
        return self.coordinator.data.get(self._station_id)

    @property
    def available(self) -> bool:
        """Return True when the station is present in the last poll."""
        return super().available and self.station is not None
```

`custom_components/carburants/sensor.py` :

```python
"""Sensor platform for Carburants."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CarburantsConfigEntry
from .const import FUELS, last_update_unique_id, price_unique_id
from .coordinator import CarburantsCoordinator
from .entity import CarburantsStationEntity

FUEL_ICONS = {
    "gazole": "mdi:fuel",
    "sp95": "mdi:fuel",
    "sp98": "mdi:fuel",
    "e10": "mdi:fuel",
    "e85": "mdi:leaf",
    "gplc": "mdi:gas-cylinder",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CarburantsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for every configured station."""
    coordinator = entry.runtime_data.coordinator

    entities: list[SensorEntity] = []
    for station_id, station in coordinator.data.items():
        entities.append(CarburantsLastUpdateSensor(coordinator, station_id))
        entities.extend(
            CarburantsFuelPriceSensor(coordinator, station_id, fuel)
            for fuel in station.tracked_fuels
        )

    async_add_entities(entities)


class CarburantsFuelPriceSensor(CarburantsStationEntity, SensorEntity):
    """Price of one fuel at one station."""

    _attr_native_unit_of_measurement = "€/L"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 3

    def __init__(
        self, coordinator: CarburantsCoordinator, station_id: str, fuel: str
    ) -> None:
        """Initialise the price sensor."""
        super().__init__(coordinator, station_id, price_unique_id(station_id, fuel))
        self._fuel = fuel
        self._attr_translation_key = fuel
        self._attr_icon = FUEL_ICONS.get(fuel, "mdi:fuel")

    @property
    def native_value(self) -> float | None:
        """Return the current price, or None while out of stock."""
        station = self.station
        if station is None:
            return None
        state = station.fuels.get(self._fuel)
        return state.price if state else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the price timestamp and the station id."""
        station = self.station
        if station is None:
            return {}
        state = station.fuels.get(self._fuel)
        return {
            "station_id": station.id,
            "fuel_label": FUELS[self._fuel],
            "updated_at": (
                state.updated_at.isoformat()
                if state and state.updated_at
                else None
            ),
        }


class CarburantsLastUpdateSensor(CarburantsStationEntity, SensorEntity):
    """Most recent price update across all fuels of a station."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_update"

    def __init__(
        self, coordinator: CarburantsCoordinator, station_id: str
    ) -> None:
        """Initialise the diagnostic sensor."""
        super().__init__(
            coordinator, station_id, last_update_unique_id(station_id)
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the most recent update timestamp."""
        station = self.station
        return station.last_update if station else None
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest tests/test_sensor.py -v && ruff check . && ruff format --check .`
Expected: 6 tests PASS

Si un `entity_id` attendu diffère (le slug est dérivé du nom du device et de la clé de traduction), lire l'`entity_id` réel via `hass.states.async_entity_ids("sensor")` et corriger les constantes du test, pas l'implémentation.

- [ ] **Step 5: Commit**

```bash
git add custom_components/carburants/__init__.py custom_components/carburants/entity.py custom_components/carburants/sensor.py tests/test_sensor.py
git commit -m "feat: wire up the config entry and add price sensors"
```

---

## Task 7: Plateforme `binary_sensor` (ruptures et ouverture)

**Files:**
- Create: `custom_components/carburants/binary_sensor.py`
- Test: `tests/test_binary_sensor.py`

**Interfaces:**
- Consumes: `entity.CarburantsStationEntity`, `const.{outage_unique_id, open_unique_id, FUELS}`, `horaires.WeekSchedule`.
- Produces: `CarburantsFuelOutageBinarySensor`, `CarburantsOpenBinarySensor`.

Le capteur d'ouverture s'appuie sur `station.opening_hours.is_open_at(dt_util.now())` et renvoie `None` (donc `unknown`) quand la station ne publie pas d'horaires.

Son réveil est **programmé sur la prochaine transition d'horaire**, via
`async_track_point_in_time` armé sur `WeekSchedule.next_boundary_after` :

- armé à l'ajout de l'entité ;
- au déclenchement : écriture du nouvel état, puis réarmement sur la transition suivante ;
- réarmé à chaque mise à jour du coordinator, puisque les horaires publiés peuvent changer — en désabonnant le timer précédent d'abord ;
- désabonné dans `async_will_remove_from_hass`, et enregistré via `self.async_on_remove` ;
- si `next_boundary_after` renvoie `None`, **aucun timer n'est armé** : l'état reste celui calculé au dernier poll.

Le temps courant et le fuseau viennent de `homeassistant.util.dt`, jamais de `datetime.now()`.

Ce mécanisme est purement local et ne déclenche **aucun appel API** : il recalcule l'état à partir du `WeekSchedule` déjà en mémoire. Le seul trafic réseau reste le poll du coordinator. Face à une réévaluation chaque minute, il fait passer de 1440 réveils par jour et par station à 2–4, avec une transition exacte à la seconde.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_binary_sensor.py` :

```python
"""Tests for the binary sensor platform."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.carburants.api import parse_station
from custom_components.carburants.const import CONF_STATIONS, DOMAIN
from tests.fixtures.records import STATION_NO_HOURS, STATION_WITH_PRICES


async def _setup(hass, record) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={CONF_STATIONS: [str(record["id"])]},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.carburants.CarburantsApi.async_fetch",
        AsyncMock(return_value=[parse_station(record)]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_outage_sensor_reflects_state(hass):
    await _setup(hass, STATION_WITH_PRICES)

    out = hass.states.get(
        "binary_sensor.route_de_la_wantzenau_strasbourg_e10_outage"
    )
    assert out.state == "on"
    assert out.attributes["device_class"] == "problem"
    assert out.attributes["outage_type"] == "temporaire"
    assert out.attributes["since"] == "2026-08-24T08:38:17+00:00"

    ok = hass.states.get(
        "binary_sensor.route_de_la_wantzenau_strasbourg_gazole_outage"
    )
    assert ok.state == "off"


async def test_no_outage_sensor_for_definitive_outages(hass):
    await _setup(hass, STATION_WITH_PRICES)
    assert (
        hass.states.get(
            "binary_sensor.route_de_la_wantzenau_strasbourg_sp95_outage"
        )
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

    # The timer must now fire on the new 13:00 boundary, not the old 20:30.
    freezer.move_to(datetime(2026, 8, 24, 13, 0, tzinfo=UTC))
    async_fire_time_changed(hass, datetime(2026, 8, 24, 13, 0, tzinfo=UTC))
    await hass.async_block_till_done()

    assert (
        hass.states.get("binary_sensor.route_de_la_wantzenau_strasbourg_open").state
        == "off"
    )
```

Note pour l'implémenteur : ces tests supposent que le fuseau de l'instance de test est UTC (c'est le défaut de `pytest-homeassistant-custom-component`). Si un slug d'`entity_id` diffère, le relever via `hass.states.async_entity_ids("binary_sensor")` et corriger la constante du test, pas l'implémentation.

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest tests/test_binary_sensor.py -v`
Expected: FAIL — aucune entité `binary_sensor` n'existe.

- [ ] **Step 3: Implémenter `binary_sensor.py`**

```python
"""Binary sensor platform for Carburants."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from . import CarburantsConfigEntry
from .const import FUELS, open_unique_id, outage_unique_id
from .coordinator import CarburantsCoordinator
from .entity import CarburantsStationEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CarburantsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors for every configured station."""
    coordinator = entry.runtime_data.coordinator

    entities: list[BinarySensorEntity] = []
    for station_id, station in coordinator.data.items():
        entities.append(CarburantsOpenBinarySensor(coordinator, station_id))
        entities.extend(
            CarburantsFuelOutageBinarySensor(coordinator, station_id, fuel)
            for fuel in station.tracked_fuels
        )

    async_add_entities(entities)


class CarburantsFuelOutageBinarySensor(CarburantsStationEntity, BinarySensorEntity):
    """Out-of-stock flag for one fuel at one station."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator: CarburantsCoordinator, station_id: str, fuel: str
    ) -> None:
        """Initialise the outage sensor."""
        super().__init__(coordinator, station_id, outage_unique_id(station_id, fuel))
        self._fuel = fuel
        self._attr_translation_key = f"{fuel}_outage"

    @property
    def is_on(self) -> bool | None:
        """Return True when the fuel is currently out of stock."""
        station = self.station
        if station is None:
            return None
        state = station.fuels.get(self._fuel)
        return state.in_outage if state else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the outage type and start date."""
        station = self.station
        if station is None:
            return {}
        state = station.fuels.get(self._fuel)
        return {
            "station_id": station.id,
            "fuel_label": FUELS[self._fuel],
            "outage_type": state.outage_type if state else None,
            "since": (
                state.outage_since.isoformat()
                if state and state.outage_since
                else None
            ),
        }


class CarburantsOpenBinarySensor(CarburantsStationEntity, BinarySensorEntity):
    """Whether the station is open right now."""

    _attr_translation_key = "open"
    _attr_icon = "mdi:store-clock"

    def __init__(
        self, coordinator: CarburantsCoordinator, station_id: str
    ) -> None:
        """Initialise the open/closed sensor."""
        super().__init__(coordinator, station_id, open_unique_id(station_id))
        self._unsub_boundary: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        """Arm the wake-up on the next opening or closing time."""
        await super().async_added_to_hass()
        self.async_on_remove(self._async_cancel_boundary)
        self._async_schedule_boundary()

    async def async_will_remove_from_hass(self) -> None:
        """Drop the pending wake-up before the entity goes away."""
        self._async_cancel_boundary()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Re-arm on every poll: the published hours may have changed."""
        self._async_schedule_boundary()
        super()._handle_coordinator_update()

    @callback
    def _async_cancel_boundary(self) -> None:
        """Cancel the pending wake-up, if any."""
        if self._unsub_boundary is not None:
            self._unsub_boundary()
            self._unsub_boundary = None

    @callback
    def _async_schedule_boundary(self) -> None:
        """Schedule a wake-up on the next transition, if one is known.

        Purely local: this only recomputes the state from the WeekSchedule
        already in memory, and never hits the API. When the schedule knows of
        no upcoming transition, nothing is armed and the state stays as
        computed at the last poll.
        """
        self._async_cancel_boundary()

        station = self.station
        if station is None or station.opening_hours is None:
            return

        boundary = station.opening_hours.next_boundary_after(dt_util.now())
        if boundary is None:
            return

        self._unsub_boundary = async_track_point_in_time(
            self.hass, self._handle_boundary, boundary
        )

    @callback
    def _handle_boundary(self, _now) -> None:
        """Write the new state, then arm the following transition."""
        self._unsub_boundary = None
        self.async_write_ha_state()
        self._async_schedule_boundary()

    @property
    def is_on(self) -> bool | None:
        """Return True/False, or None when the station publishes no hours."""
        station = self.station
        if station is None or station.opening_hours is None:
            return None
        return station.opening_hours.is_open_at(dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the weekly schedule and the 24/7 automat flag."""
        station = self.station
        if station is None:
            return {}
        return {
            "station_id": station.id,
            "automate_24_24": station.automate_24_24,
            "horaires_semaine": (
                station.opening_hours.as_dict() if station.opening_hours else None
            ),
            "ferme_aujourdhui": (
                station.opening_hours.days[
                    dt_util.now().isoweekday()
                ].closed
                if station.opening_hours
                and dt_util.now().isoweekday() in station.opening_hours.days
                else None
            ),
        }
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest -v && ruff check . && ruff format --check .`
Expected: toute la suite PASS (7 tests dans ce fichier, ~56 au total)

- [ ] **Step 5: Commit**

```bash
git add custom_components/carburants/binary_sensor.py tests/test_binary_sensor.py
git commit -m "feat: add outage and open/closed binary sensors"
```

---

## Task 8: Documentation, essai réel et préparation de la release

**Files:**
- Create: `README.md`
- Create: `CLAUDE.md`
- Test: essai manuel dans l'instance HA locale

**Interfaces:**
- Consumes: tout ce qui précède.
- Produces: rien de code.

- [ ] **Step 1: Écrire le README**

`README.md` couvre, dans cet ordre :

1. Badges HACS / release / licence, sur le modèle de `ha-strasbourg-parkings`.
2. Un paragraphe de présentation : suivi des prix carburants de stations françaises, données `prix-carburants.gouv.fr`, aucune clé d'API.
3. **Installation** : HACS en dépôt custom (`https://github.com/romainhe/ha-carburants`, catégorie *Integration*), puis copie manuelle de `custom_components/carburants/` en alternative.
4. **Configuration** : les deux méthodes de recherche, le choix multiple, puis l'ajout ou le retrait de stations via *Configurer*.
5. **Entités créées**, avec le tableau de la spec (prix, rupture, ouvert, dernière mise à jour) et la mention explicite qu'un carburant apparaissant après la configuration nécessite un rechargement de l'intégration.
6. **Events** : les deux `event_type`, la table complète des champs de données, et les deux exemples d'automatisation ci-dessous.
7. **Réglages** : intervalle de relève (défaut 60 min, 15–1440) et seuil de variation (défaut 0,001 €/L).
8. **Limites connues** : le dataset ne fournit ni enseigne ni marque ; les horaires ne sont pas publiés par toutes les stations, auquel cas le capteur *Ouvert* reste `unknown` ; les variations survenues pendant un arrêt de HA ne sont pas rejouées au redémarrage.

Exemple « baisse de prix » :

```yaml
automation:
  - alias: Alerte baisse gazole
    trigger:
      - platform: event
        event_type: carburants_price_changed
        event_data:
          direction: "down"
          fuel: "gazole"
    action:
      - service: notify.mobile_app
        data:
          title: "Gazole en baisse"
          message: >-
            {{ trigger.event.data.new_price }} € chez
            {{ trigger.event.data.station_name }}
            ({{ trigger.event.data.delta }} €)
          data:
            url: >-
              /history?entity_id={{ trigger.event.data.entity_id }}
```

Exemple « rupture » :

```yaml
automation:
  - alias: Alerte rupture carburant
    trigger:
      - platform: event
        event_type: carburants_fuel_outage
        event_data:
          state: "start"
    action:
      - service: notify.mobile_app
        data:
          message: >-
            Rupture {{ trigger.event.data.outage_type }} de
            {{ trigger.event.data.fuel_label }} chez
            {{ trigger.event.data.station_name }}
```

- [ ] **Step 2: Écrire le CLAUDE.md**

Sur le modèle de celui de `ha-powens`, documenter :

- ce qu'est le dépôt et la boucle de dev (`scripts/setup`, `scripts/develop`, symlink `config/custom_components`, ruff, `pytest`) ;
- l'architecture : un coordinator unique pour toute l'entrée, une requête `id in (...)` par poll, la détection d'events par diff avec amorçage silencieux ;
- la section **« Ce qui a l'air faux mais est intentionnel »** :
  - les champs `latitude` / `longitude` de premier niveau du dataset sont ignorés au profit de `geom` — ils sont dans une projection inexploitable,
  - les capteurs de prix n'ont **pas** de `device_class` (`monetary` exigerait un code devise et interdirait `state_class: measurement`),
  - une rupture `definitive` ne crée aucune entité : elle signifie que la station ne distribue pas ce carburant,
  - le capteur *Ouvert* ne se rafraîchit pas à intervalle fixe : il s'arme sur `WeekSchedule.next_boundary_after` via `async_track_point_in_time`, purement en local, sans appel API — 2 à 4 réveils par jour et par station au lieu de 1440, avec une transition exacte à la seconde. Aucun timer n'est armé quand la station ne publie pas d'horaires,
- la règle i18n : toute clé ajoutée à `strings.json` doit exister dans `translations/en.json` **et** `translations/fr.json`.

- [ ] **Step 3: Essai réel dans Home Assistant**

```bash
bash scripts/develop
```

Puis, dans l'UI sur `http://localhost:8123` :

1. Ajouter l'intégration **Carburants**, choisir « Rechercher autour d'un point », valider le rayon par défaut, sélectionner deux stations.
2. Vérifier que deux devices apparaissent, avec les capteurs de prix, de rupture, d'ouverture et le diagnostic de dernière mise à jour.
3. Dans **Outils de développement → Events**, écouter `carburants_price_changed` et `carburants_fuel_outage` ; confirmer qu'aucun event n'est émis au premier chargement.
4. Ouvrir *Configurer* → *Réglages*, passer l'intervalle à 15 minutes, vérifier que l'entrée se recharge.
5. Ouvrir *Configurer* → *Ajouter ou retirer des stations*, décocher une station, vérifier que ses entités disparaissent.
6. Relire `config/home-assistant.log` : aucune trace `ERROR` ni `WARNING` en provenance de `custom_components.carburants`.

- [ ] **Step 4: Lancer la suite complète**

Run: `python -m pytest -v && ruff check . && ruff format --check .`
Expected: tout au vert

- [ ] **Step 5: Commit et tag**

```bash
git add README.md CLAUDE.md
git commit -m "docs: add README and repository guide"
git tag v0.1.0
```

---

## Self-Review

**Couverture de la spec :**

| Section de la spec | Tâche |
|---|---|
| §2 Source de données, champs, pièges du flux | Task 3 (`api.py`, fixtures réelles) |
| §3 Structure du dépôt, dev loop, HACS, CI | Task 1, Task 8 |
| §4 Couche API, trois méthodes, haversine | Task 3 |
| §5 Config flow, options flow, bornes | Task 5 |
| §6 Entités, device, unique_ids, règle des carburants suivis | Task 1 (`unique_id`), Task 6 (sensors), Task 7 (binary sensors) |
| §6 Réveil du capteur d'ouverture sur `next_boundary_after` | Task 2 (`horaires.py`), Task 7 (`async_track_point_in_time`) |
| §7 Coordinator, amorçage silencieux, deux events, résolution d'`entity_id` | Task 4 |
| §8 Gestion des erreurs (`UpdateFailed`, station disparue, `cannot_connect`) | Task 3, Task 4, Task 5, Task 6 |
| §9 Tests | Tasks 2 à 7 |
| §10 i18n | Task 5, rappel dans le `CLAUDE.md` de la Task 8 |

**Cohérence des types :** `price_unique_id` / `outage_unique_id` / `open_unique_id` / `last_update_unique_id` sont définis en Task 1 et consommés à l'identique en Tasks 4, 6 et 7. `Station.tracked_fuels` est défini en Task 3 et utilisé en Tasks 4, 5, 6 et 7. `WeekSchedule.next_boundary_after` est défini en Task 2 et consommé en Task 7. `CarburantsStationEntity(coordinator, station_id, unique_id)` est défini en Task 6 et sous-classé en Task 7. `entry.runtime_data.coordinator` est produit en Task 6 et consommé par les deux plateformes.
