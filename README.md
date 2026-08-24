# Carburants

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/romainhe/ha-prix-carburants)](https://github.com/romainhe/ha-prix-carburants/releases)
[![License](https://img.shields.io/github/license/romainhe/ha-prix-carburants)](LICENSE)

Intégration Home Assistant qui suit les prix des carburants de stations françaises à partir du flux ouvert [`prix-carburants.gouv.fr`](https://www.prix-carburants.gouv.fr/) (dataset Opendatasoft du ministère de l'Économie). Aucune clé d'API, aucun compte requis.

## Installation

### HACS (dépôt custom)

1. HACS → Intégrations → ⋮ → Dépôts personnalisés.
2. Ajouter `https://github.com/romainhe/ha-prix-carburants`, catégorie **Integration**.
3. Installer, puis redémarrer Home Assistant.

### Manuelle

Copier `custom_components/carburants/` dans `config/custom_components/` de votre instance, puis redémarrer Home Assistant.

## Configuration

Depuis **Paramètres → Appareils et services → Ajouter une intégration → Carburants**, deux méthodes de recherche sont proposées :

- **Rechercher par code postal ou ville** — saisir un code postal à 5 chiffres ou un nom de ville.
- **Rechercher autour d'un point** — choisir une position sur la carte et un rayon (10 km par défaut, 1 à 50 km).

Dans les deux cas, un écran de sélection multiple affiche les stations trouvées (adresse, distance le cas échéant, prix connus) : cocher les stations à surveiller.

Une seule entrée de configuration existe pour toute l'instance. L'ajout ou le retrait de stations se fait ensuite via **Configurer → Ajouter ou retirer des stations**, qui réutilise les deux mêmes méthodes de recherche puis fusionne le résultat avec les stations déjà suivies.

## Entités créées

Un device est créé par station suivie, avec les entités suivantes :

| Entité | Domaine | Description |
|---|---|---|
| `sensor.<station>_<carburant>` | `sensor` | Prix du carburant (`€/L`) |
| `binary_sensor.<station>_<carburant>_outage` (en) / `binary_sensor.<station>_rupture_<carburant>` (fr) | `binary_sensor` | Rupture de stock sur ce carburant |
| `binary_sensor.<station>_open` (en) / `binary_sensor.<station>_ouvert` (fr) | `binary_sensor` | Station ouverte ou fermée |
| `sensor.<station>_last_update` (en) / `sensor.<station>_derniere_mise_a_jour` (fr) | `sensor` | Diagnostic : horodatage de la dernière mise à jour de prix |

L'`object_id` de chaque entité est le slug du nom de l'entité *traduit*, qui suit donc la langue de l'instance Home Assistant : par exemple l'entité de rupture du gazole est `binary_sensor.<station>_gazole_outage` sur une instance en anglais, `binary_sensor.<station>_rupture_gazole` sur une instance en français. Voir `tests/test_binary_sensor.py` pour les formes anglaises exactes.

Seuls les carburants effectivement distribués par la station reçoivent des entités : un carburant en rupture *définitive* (la station ne le vend pas) n'a pas d'entité.

Le jeu d'entités est figé au chargement de l'entrée : un carburant qu'une station ne commence à vendre qu'après coup, ou une station absente du tout premier relevé, n'obtient ses entités qu'après un rechargement de l'intégration (redémarrage de Home Assistant, ou rechargement manuel de l'entrée).

## Events

Deux `event_type` sont émis sur le bus Home Assistant à chaque relevé où un changement est détecté (aucun event n'est émis au premier chargement de l'intégration).

### `carburants_price_changed`

Émis quand le prix d'un carburant varie d'au moins le seuil configuré.

| Champ | Description |
|---|---|
| `station_id` | Identifiant de la station |
| `station_name` | Adresse et ville de la station |
| `address` | Adresse |
| `city` | Ville |
| `latitude` / `longitude` | Coordonnées de la station |
| `fuel` | Clé du carburant (`gazole`, `sp95`, …) |
| `fuel_label` | Libellé du carburant |
| `entity_id` | `entity_id` du capteur de prix concerné, ou `None` si cette entité n'a jamais été créée (voir « Limites connues » : jeu d'entités figé au chargement) |
| `direction` | `"up"` ou `"down"` |
| `old_price` / `new_price` | Ancien et nouveau prix (`€/L`) |
| `delta` | Variation (`€/L`), signée |
| `delta_percent` | Variation en pourcentage |
| `updated_at` | Horodatage ISO 8601 du nouveau prix |

### `carburants_fuel_outage`

Émis quand une rupture de stock commence ou se termine.

| Champ | Description |
|---|---|
| `station_id` | Identifiant de la station |
| `station_name` | Adresse et ville de la station |
| `address` | Adresse |
| `city` | Ville |
| `latitude` / `longitude` | Coordonnées de la station |
| `fuel` | Clé du carburant |
| `fuel_label` | Libellé du carburant |
| `entity_id` | `entity_id` du capteur de rupture concerné, ou `None` si cette entité n'a jamais été créée (voir « Limites connues » : jeu d'entités figé au chargement) |
| `state` | `"start"` ou `"end"` |
| `outage_type` | Type de rupture (`temporaire` ou `definitive`) |
| `since` | Horodatage ISO 8601 du début de la rupture |

### Exemple « baisse de prix »

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
              {% if trigger.event.data.entity_id %}/history?entity_id={{ trigger.event.data.entity_id }}{% endif %}
```

### Exemple « rupture »

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

## Réglages

Accessibles via **Configurer → Réglages** :

- **Intervalle de relève** : 60 minutes par défaut, réglable de 15 à 1440 minutes.
- **Seuil de variation de prix** : 0,001 €/L par défaut ; en dessous, `carburants_price_changed` n'est pas émis.

## Limites connues

- Le dataset ne fournit ni enseigne ni marque : l'identité d'une station, c'est son adresse et sa ville.
- Les horaires ne sont pas publiés par toutes les stations. Quand ce n'est pas le cas, le capteur *Ouvert* reste `unknown` plutôt que de deviner.
- Le jeu d'entités est figé au chargement de l'entrée : un carburant qu'une station ne commence à vendre qu'après coup, ou une station absente du tout premier relevé, n'obtient ses entités qu'après un rechargement de l'intégration.
- Les variations survenues pendant un arrêt de Home Assistant ne sont pas rejouées au redémarrage.
