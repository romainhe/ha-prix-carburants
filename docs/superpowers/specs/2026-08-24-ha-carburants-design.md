# ha-carburants — design

Date : 2026-08-24
Statut : validé

## 1. Objectif

Intégration custom Home Assistant permettant de surveiller le prix des carburants
d'une ou plusieurs stations-service françaises sélectionnées par l'utilisateur, et
de déclencher des automatisations sur les baisses, hausses et ruptures de carburant.

Non-objectifs (YAGNI explicite) :

- pas de comparatif de secteur (« station la moins chère dans X km ») ;
- pas d'historique de prix maintenu par l'intégration (le recorder HA suffit) ;
- pas de cartographie ni de calcul d'itinéraire.

## 2. Source de données

Dataset Opendatasoft `prix-des-carburants-en-france-flux-instantane-v2`, exposé
par `data.economie.gouv.fr` via l'API Explore v2.1 :

```
https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/records
```

Pas d'authentification, pas de quota déclaré. Champs utilisés :

| Champ | Usage |
|---|---|
| `id` | identifiant stable de la station (ex. `67000002`) |
| `adresse`, `ville`, `cp` | identité et libellé de la station |
| `geom` (`{lon, lat}`) | filtre géographique et attributs de position |
| `<fuel>_prix` | prix courant, en euros par litre (float) |
| `<fuel>_maj` | horodatage ISO de la dernière mise à jour du prix |
| `<fuel>_rupture_debut`, `<fuel>_rupture_type` | état de rupture (`temporaire` / `definitive`) |
| `carburants_rupture_temporaire`, `carburants_rupture_definitive` | listes `;`-séparées, servent de garde-fou |
| `horaires` | JSON encodé en chaîne, horaires par jour |
| `horaires_automate_24_24` | `"Oui"` / `"Non"` |
| `pop` | `R` (route) / `A` (autoroute), attribut informatif |

`<fuel>` ∈ `gazole`, `sp95`, `sp98`, `e10`, `e85`, `gplc`.

Remarques vérifiées sur le flux réel :

- **il n'existe pas de champ marque / enseigne** ; l'identité lisible d'une
  station est `adresse — ville` ;
- les champs `latitude` / `longitude` de premier niveau sont des chaînes en
  projection Lambert-like (`"4857287"`) : **ne pas les utiliser**, seul `geom`
  porte des coordonnées WGS84 exploitables ;
- `horaires` peut être `null`, ou un JSON dont chaque jour possède
  `"@ferme"` (`""` = ouvert, `"1"` = fermé) et un `horaire` **soit objet unique
  soit liste de créneaux** (`{"@ouverture": "06.30", "@fermeture": "20.30"}`,
  séparateur décimal `.`) ;
- un `horaire` `00.00 → 00.00` signifie ouvert en continu ;
- le filtre `where=id in (a,b,c)` fonctionne : **une seule requête** suffit pour
  rafraîchir toutes les stations surveillées.

## 3. Structure du dépôt

```
ha-carburants/
├── custom_components/carburants/
│   ├── __init__.py          # setup/unload entry, runtime_data
│   ├── api.py               # client HTTP + normalisation Station
│   ├── const.py             # DOMAIN, FUELS, defaults, event types
│   ├── coordinator.py       # DataUpdateCoordinator + détection d'events
│   ├── config_flow.py       # config flow + options flow
│   ├── horaires.py          # parsing horaires (pur, testable)
│   ├── sensor.py            # prix par carburant + dernière maj
│   ├── binary_sensor.py     # ruptures + ouvert/fermé
│   ├── manifest.json
│   ├── strings.json
│   └── translations/{en.json,fr.json}
├── tests/                   # pytest-homeassistant-custom-component
├── .devcontainer/devcontainer.json
├── scripts/{setup,develop}
├── config/                  # instance HA de test, gitignored
├── .github/workflows/{hassfest.yml,hacs.yml}
├── hacs.json
├── README.md
├── LICENSE
└── CLAUDE.md
```

`domain = "carburants"`. Boucle de dev calquée sur `ha-powens` :
`scripts/setup` idempotent (venv sur macOS hôte, Python du conteneur en
devcontainer, symlink `config/custom_components` → `custom_components/`,
génération de `config/configuration.yaml` avec le logger en debug), puis
`scripts/develop` lançant `hass --config ./config --debug`.

Distribution HACS : dépôt custom classique (`hacs.json` **sans**
`content_in_root`, l'intégration vivant sous `custom_components/`). Les workflows
hassfest et HACS-validate sont en place dès le premier commit pour que la mise à
disposition ne demande aucune refonte ultérieure.

## 4. Couche API (`api.py`)

Client mince au-dessus de la session `aiohttp` partagée de HA
(`async_get_clientsession`), timeout 10 s.

```python
@dataclass(frozen=True)
class FuelState:
    fuel: str              # "gazole"
    price: float | None    # €/L
    updated_at: datetime | None
    outage_type: str | None    # "temporaire" | "definitive" | None
    outage_since: datetime | None

@dataclass(frozen=True)
class Station:
    id: str
    address: str
    city: str
    postal_code: str
    latitude: float | None
    longitude: float | None
    highway: bool              # pop == "A"
    fuels: dict[str, FuelState]
    opening_hours: WeekSchedule | None
    automate_24_24: bool
    @property
    def name(self) -> str: ...      # "49 rte du Rhin — Strasbourg"
```

Trois méthodes :

| Méthode | Requête |
|---|---|
| `async_search_text(query)` | `where=cp="<q>" or search(ville, "<q>")`, `limit=100` |
| `async_search_geo(lat, lon, km)` | `where=distance(geom, geom'POINT(lon lat)', <km>km)`, `limit=100`, tri haversine côté client |
| `async_fetch(ids)` | `where=id in (<ids>)`, `limit=100` |

Toutes renvoient des `Station`. Le parsing des champs bruts (JSON encodé,
booléens texte, dates) est isolé dans des fonctions pures pour être testable
sans HA. Les erreurs réseau et HTTP remontent sous forme de
`CarburantsApiError`.

## 5. Config flow

`VERSION = 1`. **Une seule entrée de configuration** (`unique_id = DOMAIN`,
`_abort_if_unique_id_configured`) ; l'ajout et le retrait de stations passent
ensuite par l'options flow.

Étapes :

1. `async_step_user` — `async_show_menu` : `recherche` (CP / ville) ou
   `proximite` (autour d'un point).
2. `async_step_recherche` — champ texte unique `query`. Une valeur purement
   numérique de 5 chiffres est traitée comme un code postal, sinon comme une
   ville. Résultats mis de côté sur le flow.
3. `async_step_proximite` — `latitude` / `longitude` pré-remplis depuis
   `hass.config`, `radius` en km (défaut 10, bornes 1–50).
4. `async_step_stations` — `cv.multi_select` des résultats. Libellé :
   `49 rte du Rhin, Strasbourg · 2,3 km · Gazole 1,799 €` (la distance
   n'apparaît que pour la recherche géographique). Sélection vide →
   erreur `no_station_selected`. Aucun résultat → erreur `no_results` avec
   retour à l'étape de recherche.
5. `async_create_entry(title="Carburants", data={CONF_STATIONS: [...]})`.

Options flow, menu à deux branches :

- **Stations** — rejoue les mêmes étapes de recherche, puis affiche un
  `multi_select` fusionnant les stations déjà surveillées (pré-cochées, donc
  décocher = retirer) et les nouveaux résultats. Écrit la liste dans
  `entry.data` et recharge l'entrée.
- **Réglages** — `scan_interval` en minutes (défaut 60, bornes 15–1440) et
  `price_event_threshold` en €/L (défaut 0.001, bornes 0–0.5), écrits dans
  `entry.options`.

Un `update_listener` recharge l'entrée à chaque changement d'options.

**Purge du registre.** Retirer une station de la sélection ne suffit pas à faire
disparaître ses entités : Home Assistant conserve les devices et entités déjà
enregistrés, qui resteraient indéfiniment `unavailable`. `async_setup_entry`
purge donc, à chaque chargement, les devices de l'entrée dont l'identifiant
`(DOMAIN, station_id)` ne figure plus dans `CONF_STATIONS` ; la suppression du
device emporte ses entités. Sans cela, le texte de l'options flow — « Décocher
une station la retire ainsi que ses entités » — serait faux.

## 6. Entités

Un **device par station** (`identifiers = {(DOMAIN, station_id)}`,
`name = "<adresse> — <ville>"`, `manufacturer = "Ministère de l'Économie"`,
`model = "prix-carburants.gouv.fr"`, `entry_type = service`).
`_attr_has_entity_name = True` + `_attr_translation_key`, libellés dans
`strings.json` / `translations/`.

Les entités d'un carburant ne sont créées que si la station le distribue,
c'est-à-dire si le premier poll expose pour ce carburant un prix **ou** une
information de rupture. Un carburant apparaissant plus tard nécessite un
rechargement de l'entrée ; ce comportement est documenté dans le README.

| Entité | `unique_id` | Détail |
|---|---|---|
| `sensor.<station>_<fuel>` | `{station_id}_{fuel}` | `native_value` = prix ; `native_unit_of_measurement = "€/L"` ; `state_class = MEASUREMENT` ; `suggested_display_precision = 3`. **Pas de `device_class`** : `monetary` impose un code devise et interdit `state_class = measurement`, incompatible avec un prix au litre. Attributs : `updated_at`, `station_id`. `None` si la station ne publie pas de prix (rupture) |
| `binary_sensor.<station>_<fuel>_rupture` | `{station_id}_{fuel}_outage` | `device_class = PROBLEM`, `is_on` = rupture en cours. Attributs : `outage_type`, `since` |
| `binary_sensor.<station>_ouvert` | `{station_id}_open` | calculé depuis `opening_hours` dans le fuseau local ; `None` (unknown) si la station ne publie pas d'horaires. Attributs : `automate_24_24`, `horaires_semaine`, `ferme_aujourdhui` |
| `sensor.<station>_derniere_maj` | `{station_id}_last_update` | `device_class = TIMESTAMP`, `entity_category = DIAGNOSTIC`, = max des `*_maj` de la station |

### Réveil du capteur d'ouverture

Les transitions ouverture/fermeture ne doivent pas dépendre de l'intervalle de
polling. Le capteur s'arme donc sur **la prochaine transition d'horaire connue**,
via `async_track_point_in_time`.

`WeekSchedule` expose pour cela `next_boundary_after(moment) -> datetime | None` :
le plus petit début ou fin de créneau strictement postérieur à `moment`, déduit
des mêmes intervalles que ceux servant à `is_open_at`. La recherche dépasse le
jour courant — une station fermée le dimanche trouve l'ouverture du lundi — et
renvoie `None` quand aucune transition n'est connue : jour ouvert sans créneau
publié, ou station sans horaires du tout.

Cycle de vie du timer :

- armé à l'ajout de l'entité, sur `next_boundary_after(dt_util.now())` ;
- au déclenchement : écriture du nouvel état, puis réarmement sur la transition
  suivante ;
- réarmé à chaque mise à jour du coordinator, puisque les horaires publiés
  peuvent changer — en désabonnant le timer précédent d'abord ;
- désabonné dans `async_will_remove_from_hass`, et enregistré via
  `self.async_on_remove` ;
- si `next_boundary_after` renvoie `None`, **aucun timer n'est armé** : l'état
  reste celui calculé au dernier poll (`unknown` dans le cas « pas d'horaires
  publiés »).

Le temps courant et le fuseau viennent de `homeassistant.util.dt`, jamais de
`datetime.now()`.

**Ce mécanisme est purement local et ne déclenche aucun appel API** : il se
contente de recalculer l'état à partir du `WeekSchedule` déjà en mémoire. Le seul
trafic réseau reste le poll du coordinator toutes les 60 minutes. Face à une
réévaluation à intervalle d'une minute, le point-in-time fait passer de 1440
réveils par jour et par station à 2–4, avec une transition exacte à la seconde
plutôt qu'à la minute.

## 7. Coordinator et events

`CarburantsCoordinator(DataUpdateCoordinator[dict[str, Station]])`, **unique pour
toute l'entrée** : un poll = une requête `id in (...)`. Intervalle
`entry.options[CONF_SCAN_INTERVAL]` (défaut 60 min).

Détection d'events par diff entre le snapshot précédent et le nouveau, avec un
drapeau `_primed` : **le premier poll après démarrage amorce l'état en silence**,
sur le modèle de `powens_new_transaction`. Les variations survenues pendant un
arrêt de HA ne sont donc pas rejouées.

Les carburants examinés à chaque diff sont l'**union** des `tracked_fuels` des deux
snapshots, et non ceux du seul nouveau. Un carburant que la station vendait et qui
bascule en rupture `definitive` quitte `tracked_fuels` : ne regarder que le nouveau
snapshot rendrait l'intégration muette sur cette rupture, alors que c'est
précisément ce qu'elle promet de signaler. Un carburant jamais distribué n'est dans
aucun des deux snapshots, donc le bruit reste écarté.

Deux `event_type`, la direction étant un champ de données (filtrable en une ligne
dans un `trigger`) :

### `carburants_price_changed`

Émis pour chaque carburant dont le prix change de `|delta| >= price_event_threshold`.
Une transition depuis ou vers « pas de prix » n'émet pas cet event (c'est une
rupture, couverte ci-dessous).

```yaml
station_id: "67000002"
station_name: "Route de la Wantzenau — Strasbourg"
address: "Route de la Wantzenau"
city: "Strasbourg"
latitude: 48.611994
longitude: 7.782216
entity_id: "sensor.route_de_la_wantzenau_strasbourg_gazole"
fuel: "gazole"
fuel_label: "Gazole"
direction: "down"        # "down" | "up"
old_price: 2.319
new_price: 2.299
delta: -0.02
delta_percent: -0.86
updated_at: "2026-08-24T10:25:29+00:00"
```

### `carburants_fuel_outage`

```yaml
station_id: "67000002"
station_name: "Route de la Wantzenau — Strasbourg"
address: "Route de la Wantzenau"
city: "Strasbourg"
entity_id: "binary_sensor.route_de_la_wantzenau_strasbourg_e10_rupture"
fuel: "e10"
fuel_label: "E10"
state: "start"           # "start" | "end"
outage_type: "temporaire"
since: "2026-08-24T08:38:17+00:00"
```

`entity_id` est résolu au moment de l'émission via
`entity_registry.async_get_entity_id(<domain>, DOMAIN, <unique_id>)`, ce qui
permet `{{ trigger.event.data.entity_id }}` dans un message de notification et
un lien cliquable vers l'entité. Le champ vaut `None` si l'entité n'est pas (ou
plus) enregistrée.

Exemple d'automatisation cible :

```yaml
trigger:
  platform: event
  event_type: carburants_price_changed
  event_data:
    direction: "down"
action:
  service: notify.mobile_app
  data:
    message: >-
      {{ trigger.event.data.fuel_label }} à {{ trigger.event.data.new_price }} €
      chez {{ trigger.event.data.station_name }}
      ({{ trigger.event.data.delta }} €)
```

## 8. Gestion des erreurs

- Erreur réseau, timeout ou statut HTTP non-2xx sur le poll → `UpdateFailed`.
  Les entités passent `unavailable`, le coordinator retente au cycle suivant.
- Station absente de la réponse alors qu'elle est surveillée → **seules ses
  entités** deviennent indisponibles (`available` renvoie `False` si l'`id`
  manque dans `coordinator.data`) ; l'entrée et les autres stations restent
  vivantes.
- Erreur pendant une recherche du config flow → `cannot_connect` affiché sur le
  formulaire, la saisie est conservée.
- Aucun mécanisme d'authentification, donc pas de flux de reauth.

## 9. Tests

Suite `pytest-homeassistant-custom-component` limitée aux parties à risque, sur
des fixtures JSON capturées depuis l'API réelle :

- `horaires.py` — jour fermé, `horaire` objet unique, `horaire` liste de
  créneaux, `00.00 → 00.00`, `horaires` absent, automate 24/24 ;
- `WeekSchedule.next_boundary_after` — depuis le milieu d'un créneau (→ l'heure
  de fermeture), depuis une période fermée (→ la prochaine ouverture), en fin de
  journée avec passage au lendemain, sur un créneau `00.00 → 00.00`, sur un jour
  marqué fermé, et sur un `WeekSchedule` sans créneau publié (→ `None`) ;
- normalisation `api.py` — prix absent, rupture temporaire vs définitive, `geom`
  manquant, dates ISO ;
- détection d'events du coordinator — amorçage silencieux au premier poll,
  hausse, baisse, variation sous le seuil, début et fin de rupture, station
  disparue du flux ;
- config flow — chemin CP/ville, chemin rayon, sélection vide, aucun résultat,
  options flow fusionnant stations existantes et nouveaux résultats.

## 10. i18n

`strings.json` en anglais comme référence, `translations/fr.json` et
`translations/en.json`. Toute clé d'erreur ajoutée à `strings.json` doit exister
dans chaque fichier de traduction, faute de quoi HA affiche la clé brute.
