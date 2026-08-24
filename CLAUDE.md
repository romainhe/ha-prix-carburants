# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant **custom integration** (`custom_components/carburants/`) that polls the French ministry's open dataset [`prix-carburants.gouv.fr`](https://www.prix-carburants.gouv.fr/) (Opendatasoft Explore v2.1 API, no authentication) and exposes each monitored fuel station as a device with a price sensor per fuel, an outage binary sensor per fuel, an open/closed binary sensor, and a diagnostic last-update sensor.

There is no library code outside the integration. The repo root only adds dev tooling (`scripts/`, `.devcontainer/`) and a working HA `config/` directory for local testing.

## Dev loop

```bash
./scripts/setup     # idempotent — installs HA + ruff + test deps, symlinks custom_components into config/, writes config/configuration.yaml
./scripts/develop   # runs `hass --config ./config --debug`
```

- On macOS host, `scripts/setup` creates and uses `./.venv`. Inside the devcontainer (`REMOTE_CONTAINERS=true` or `/.dockerenv`), it installs into the container's Python directly — no venv.
- `config/custom_components` is a **symlink** to `custom_components/`, so editing source under `custom_components/carburants/` is picked up live by the running HA. Restart HA (or kill `hass`) after Python changes; `strings.json` / `translations/*.json` changes need a reload of the integration.
- HA debug logs for this integration are enabled by default via the auto-generated `config/configuration.yaml` (`custom_components.carburants: debug`).
- Linter/formatter is **ruff**: `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`.
- Tests: `.venv/bin/python -m pytest -q`.

## Architecture

- **One coordinator per config entry.** There is a single config entry for the whole instance (`async_set_unique_id(DOMAIN)` + `_abort_if_unique_id_configured`); `CarburantsCoordinator` (`coordinator.py`) polls every station tracked by that entry in one shot.
- **One API request per poll.** `CarburantsApi.async_fetch` builds a single `id in (id1,id2,...)` `where` clause and fetches every station's current state in one HTTP call, regardless of how many stations or fuels are tracked.
- **Event detection is a diff against the previous poll, with silent priming.** `CarburantsCoordinator._process_events` keeps the previous poll's `FuelState` per station/fuel. The very first poll only primes `self._previous` / `self._previous_tracked` and returns — no events fire on integration startup or reload, however different the freshly-fetched state looks from nothing. From the second poll on, each fuel present in either the old or new `tracked_fuels` is diffed: a price move ≥ the configured threshold fires `carburants_price_changed`; an `in_outage` flip fires `carburants_fuel_outage`. Both payloads carry a `station_id`/`fuel` pointer *and* a resolved `entity_id` (via `entity_registry.async_get_entity_id`), so a notification action can deep-link straight to the entity — `entity_id` is `None` only if the corresponding entity was never registered.

## Ce qui a l'air faux mais est intentionnel

- **Les champs `latitude` / `longitude` de premier niveau du dataset sont ignorés au profit de `geom`.** `parse_station` (`api.py`) ne lit jamais `record["latitude"]` / `record["longitude"]` : ces champs top-level existent dans le dataset mais sont dans une projection inexploitable. Les coordonnées utilisées partout (distance, payload d'events, device info implicite) viennent de `record["geom"]["lat"/"lon"]`.
- **Les capteurs de prix n'ont pas de `device_class`.** `CarburantsFuelPriceSensor` (`sensor.py`) fixe `native_unit_of_measurement = "€/L"` et `state_class = MEASUREMENT`, mais pas de `device_class`. `SensorDeviceClass.MONETARY` exigerait un code devise ISO 4217 (`native_unit_of_measurement` serait alors contraint à un code devise, pas `"€/L"`) et **interdit** `state_class: measurement` côté HA — les deux sont incompatibles avec ce qu'on veut afficher (un prix au litre, avec historique de mesure). Rester sans `device_class` est le choix correct, pas un oubli.
- **Une rupture `definitive` ne crée aucune entité.** `Station.tracked_fuels` (`api.py`) exclut un carburant dont l'état est `outage_type == OUTAGE_DEFINITIVE` : ce n'est pas une rupture de stock temporaire, c'est le signal que la station ne distribue pas ce carburant du tout. Seule une rupture `temporaire` (ou un prix publié) garde le carburant dans `tracked_fuels`, donc dans les entités créées par `sensor.py` / `binary_sensor.py`.
- **Le capteur *Ouvert* ne se rafraîchit pas à intervalle fixe.** `CarburantsOpenBinarySensor` (`binary_sensor.py`) n'a pas de polling propre : il s'arme sur `WeekSchedule.next_boundary_after` (`horaires.py`) via `async_track_point_in_time`, purement en local — aucun appel API n'est fait pour recalculer l'état. Cela donne 2 à 4 réveils par jour et par station (au lieu de 1440 avec un polling minute par minute) et une transition exacte à la seconde près, pas approximée au prochain relevé du coordinator. `_handle_coordinator_update` ré-arme quand même le timer à chaque poll, au cas où les horaires publiés aient changé. **Aucun timer n'est armé** quand la station ne publie pas d'horaires (`opening_hours is None` ou `next_boundary_after` renvoie `None`) : l'état reste alors figé à ce que la dernière évaluation a produit — `unknown` si le schedule ne peut pas répondre (`WeekSchedule.is_open_at` retourne `None` quand le jour est ouvert mais sans créneaux publiés).

## i18n

- User-facing strings live in `strings.json` (English baseline) and `translations/<lang>.json` (`en.json`, `fr.json`).
- Toute clé ajoutée à `strings.json` doit exister à l'identique dans `translations/en.json` **et** `translations/fr.json`, sinon HA retombe sur la clé brute dans les langues non couvertes. Réutiliser `[%key:common::...%]` pour les libellés HA standards plutôt que les retraduire.
