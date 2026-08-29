#!/usr/bin/env python3
"""
Vigietaxi — génération quotidienne de data.json

Reconstruit le fichier data.json de la PWA à partir de plusieurs sources :

1. Le GTFS officiel SNCF Open Data (grandes lignes : TGV INOUI, OUIGO, Intercités,
   Intercités de nuit, TGV Lyria, ICE) pour les 6 gares parisiennes suivies.
   Le flux "International (Eurostar/Thalys)" que la SNCF publie elle-même pour
   Gare du Nord est volontairement IGNORÉ : on l'a comparé au vrai site eurostar.com
   le 28-29/08/2026 et il ne représentait qu'une poignée de trains sur la
   quarantaine qui circulent réellement (voir points 2 à 4).

2. eurostar.com (scraping HTTP simple, sans navigateur, car les horaires sont
   rendus côté serveur) pour QUATRE lignes qui desservent Paris Gare du Nord :
   Londres St Pancras, Bruxelles-Midi, Amsterdam Centraal, Cologne Hbf. Un même
   train physique (ex: un Amsterdam → Paris) apparaît sur plusieurs de ces
   pages puisqu'il passe par Bruxelles : on déduplique en gardant l'origine la
   plus lointaine (Cologne > Amsterdam > Bruxelles).

   ATTENTION : seule la ligne Londres a été testée en conditions réelles avant
   la mise en place de cette Action (elle tournait déjà depuis fin août 2026).
   Les 3 nouvelles lignes (Bruxelles/Amsterdam/Cologne) réutilisent le même
   principe d'extraction mais n'ont été vérifiées que via des relectures
   manuelles de ces pages, pas via un test automatisé de ce script précis.
   Le premier run réel sur GitHub Actions sera le vrai test. En cas d'échec sur
   une ligne, celle-ci est simplement ignorée (dégradation silencieuse) sans
   bloquer le reste.

3. Trenitalia Frecciarossa Milan → Paris Gare de Lyon : PAS de scraping (pas de
   page horaires par date comme eurostar.com). Horaire FIXE codé en dur
   (2 trains/jour, confirmé sur trenitalia.com le 03/08/2026), avec une fenêtre
   de suspension connue (travaux tunnel du Mont-Cenis, 11/09 → 09/10/2026). À
   vérifier de temps en temps manuellement si Trenitalia change ses horaires.

4. European Sleeper (train de nuit Paris ↔ Berlin, Gare du Nord) : PAS de
   scraping non plus. Le train Berlin → Paris (ES 474) circule les nuits de
   lundi/mercredi/vendredi (arrivée à Paris le mardi/jeudi/samedi à 11:28),
   confirmé sur europeansleeper.eu le 29/08/2026. Calculé ici à partir du jour
   de la semaine de la date cible.

Écrit data.json à la racine du dépôt (à côté d'index.html).

Usage :
    python scripts/generate_data.py [YYYY-MM-DD]

Sans argument, utilise "aujourd'hui" en heure de Paris.
"""

import io
import json
import re
import sys
import zipfile
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

PARIS_TZ = ZoneInfo("Europe/Paris")

GTFS_URL = "https://eu.ftp.opendatasoft.com/sncf/plandata/Export_OpenData_SNCF_GTFS_NewTripId.zip"

OUTPUT_PATH = "data.json"

STATIONS = [
    "Paris Gare de Lyon",
    "Paris Gare de l'Est",
    "Paris Montparnasse",
    "Paris Gare du Nord",
    "Paris Austerlitz",
    "Paris Bercy",
]

STATION_AREAS = {
    "Paris Gare de Lyon": ["StopArea:OCE87686006"],
    "Paris Gare de l'Est": ["StopArea:OCE87113001"],
    "Paris Montparnasse": ["StopArea:OCE87391003", "StopArea:OCE87391102"],
    "Paris Gare du Nord": ["StopArea:OCE87271007"],
    "Paris Austerlitz": ["StopArea:OCE87547000"],
    "Paris Bercy": ["StopArea:OCE87686667"],
}

EXCLUDE_MODES = {"Train TER", "Car TER", "Car à réservation"}

MODE_LABEL = {
    "TGV INOUI": "TGV INOUI",
    "OUIGO": "OUIGO",
    "INTERCITES": "Intercités",
    "INTERCITES de nuit": "Intercités de nuit",
    "Lyria": "TGV Lyria (international)",
    "ICE": "ICE (international)",
    "Train": "International (Eurostar/Thalys)",  # volontairement écarté, voir compute_sncf_arrivals
}


def log(msg):
    print(f"[generate_data] {msg}", flush=True)


# --------------------------------------------------------------------------
# SNCF (GTFS)
# --------------------------------------------------------------------------

def download_gtfs():
    log("Téléchargement du GTFS SNCF Open Data...")
    resp = requests.get(GTFS_URL, timeout=120)
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    dfs = {}
    for name in ["stops.txt", "calendar_dates.txt", "trips.txt", "routes.txt", "stop_times.txt"]:
        with zf.open(name) as f:
            dfs[name] = pd.read_csv(f, dtype=str, keep_default_na=False)
    log("GTFS téléchargé et chargé.")
    return dfs


def build_stop_mapping(stops):
    stop_to_gare, stop_mode = {}, {}
    for gare, areas in STATION_AREAS.items():
        for area in areas:
            for _, row in stops[stops["parent_station"] == area].iterrows():
                sid = row["stop_id"]
                core = sid.split(":", 1)[1][3:]  # strip "StopPoint:OCE"
                mode = core.rsplit("-", 1)[0]
                if mode in EXCLUDE_MODES:
                    continue
                stop_to_gare[sid] = gare
                stop_mode[sid] = mode
    return stop_to_gare, stop_mode


def compute_sncf_arrivals(dfs, target_date):
    """target_date: 'YYYYMMDD' string. Returns a DataFrame with columns matching
    Gare d'arrivée / Heure d'arrivée / Numéro de train / Type de train / Origine / Ligne
    """
    stops = dfs["stops.txt"]
    cal = dfs["calendar_dates.txt"]
    trips = dfs["trips.txt"]
    routes = dfs["routes.txt"]
    stop_times = dfs["stop_times.txt"]

    stop_to_gare, stop_mode = build_stop_mapping(stops)
    target_stop_ids = set(stop_to_gare.keys())

    active_today = cal[(cal["date"] == target_date) & (cal["exception_type"] == "1")]
    active_service_ids = set(active_today["service_id"])
    trips_today = trips[trips["service_id"].isin(active_service_ids)]
    active_trip_ids = set(trips_today["trip_id"])
    log(f"Services actifs le {target_date} : {len(active_service_ids)} ; trips : {len(active_trip_ids)}")

    st = stop_times[stop_times["trip_id"].isin(active_trip_ids)].copy()
    st["stop_sequence"] = st["stop_sequence"].astype(int)

    arrivals = st[st["stop_id"].isin(target_stop_ids)].copy()
    log(f"Lignes d'arrivée brutes (avant filtre terminus) : {len(arrivals)}")

    needed_trip_ids = set(arrivals["trip_id"])
    trip_stops = st[st["trip_id"].isin(needed_trip_ids)]

    # origine = premier arrêt (stop_sequence minimal) de chaque trip
    idx_min = trip_stops.groupby("trip_id")["stop_sequence"].idxmin()
    origins = trip_stops.loc[idx_min, ["trip_id", "stop_id"]].rename(columns={"stop_id": "origin_stop_id"})
    stopid_to_name = dict(zip(stops["stop_id"], stops["stop_name"]))
    origins["Origine"] = origins["origin_stop_id"].map(stopid_to_name)

    # ne garder que les vraies arrivées terminus (dernier arrêt du trip)
    idx_max = trip_stops.groupby("trip_id")["stop_sequence"].idxmax()
    last_stops = trip_stops.loc[idx_max, ["trip_id", "stop_sequence"]].rename(columns={"stop_sequence": "last_seq"})
    arrivals = arrivals.merge(last_stops, on="trip_id", how="left")
    arrivals = arrivals[arrivals["stop_sequence"] == arrivals["last_seq"]]
    log(f"Arrivées terminus retenues : {len(arrivals)}")

    df = arrivals.merge(trips[["trip_id", "route_id", "trip_headsign"]], on="trip_id", how="left")
    df = df.merge(routes[["route_id", "route_long_name"]], on="route_id", how="left")
    df = df.merge(origins[["trip_id", "Origine"]], on="trip_id", how="left")

    df["Gare d'arrivée"] = df["stop_id"].map(stop_to_gare)
    df["Mode"] = df["stop_id"].map(stop_mode)
    df["Type de train"] = df["Mode"].map(MODE_LABEL)
    df["Numéro de train"] = df["trip_headsign"]
    df["Heure d'arrivée"] = df["arrival_time"]
    df["Ligne"] = df["route_long_name"]

    final = df[["Gare d'arrivée", "Heure d'arrivée", "Numéro de train", "Type de train", "Origine", "Ligne"]]
    final = final.drop_duplicates().sort_values(["Gare d'arrivée", "Heure d'arrivée"]).reset_index(drop=True)

    # Le flux SNCF "International (Eurostar/Thalys)" pour Gare du Nord ne
    # contient qu'une poignée de trains Bruxelles (vu le 28-29/08/2026: 3
    # trains, avec des horaires ne correspondant à AUCUN train réel trouvé sur
    # eurostar.com). On l'écarte entièrement : Bruxelles/Amsterdam/Cologne
    # sont reconstruits proprement via fetch_eurostar_route() ci-dessous.
    before = len(final)
    final = final[~((final["Gare d'arrivée"] == "Paris Gare du Nord") &
                     (final["Type de train"] == "International (Eurostar/Thalys)"))]
    if before != len(final):
        log(f"{before - len(final)} lignes SNCF 'International' pour Gare du Nord écartées "
            f"(remplacées par le scraping eurostar.com, plus complet et plus fiable).")

    return final


# --------------------------------------------------------------------------
# Eurostar / Thalys — 4 lignes qui arrivent à Paris Gare du Nord
# --------------------------------------------------------------------------

# code gare Eurostar, slug URL, nom d'origine affiché — Paris Gare du Nord = 8727100
EUROSTAR_ROUTES = [
    # (clé priorité, code, slug, nom affiché)
    ("cologne", "8015458", "cologne-hbf", "Cologne Hbf"),
    ("amsterdam", "8400058", "amsterdam-centraal", "Amsterdam Centraal"),
    ("bruxelles", "8814001", "brussels-midi", "Bruxelles Midi"),
    ("londres", "7015400", "londres-st-pancras-intl", "Londres St Pancras"),
]
# ordre de priorité pour la déduplication : un train Amsterdam/Cologne passe
# aussi par Bruxelles, on garde l'origine la plus lointaine.
ORIGIN_PRIORITY = ["cologne", "amsterdam", "bruxelles", "londres"]

EUROSTAR_URL_TMPL = (
    "https://www.eurostar.com/fr-fr/voyage/horaires/{code}/8727100/{slug}/paris-gare-du-nord?date={date}"
)


def fetch_eurostar_route(date_iso, code, slug):
    """Scrape les horaires d'une ligne Eurostar/Thalys vers Paris Gare du Nord.
    Renvoie une liste de dicts {numero, heure_depart, heure_arrivee, cancelled}
    ou [] en cas d'échec (dégradation silencieuse par ligne : les 3 autres
    lignes et le reste des données ne sont pas affectés).
    """
    url = EUROSTAR_URL_TMPL.format(code=code, slug=slug, date=date_iso)
    try:
        resp = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (compatible; VigietaxiBot/1.0)"},
        )
        resp.raise_for_status()
    except Exception as exc:
        log(f"AVERTISSEMENT : échec de récupération eurostar.com ({slug}, {exc}). "
            f"Cette ligne sera omise pour cette exécution.")
        return []

    html = resp.text
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    # Découpe le texte en blocs par train : "Numéro du train: ES/ER/TH 1234"
    blocks = re.split(r"(?=Num[ée]ro du train\s*:?\s*(?:ES|ER|TH)?\s*\d{3,5})", text)
    results = []
    for block in blocks:
        m_num = re.search(r"Num[ée]ro du train\s*:?\s*(ES|ER|TH)?\s*(\d{3,5})", block)
        if not m_num:
            continue
        window = block[:400]
        times = re.findall(r"\b(\d{2}:\d{2})\b", window)
        if len(times) < 2:
            continue
        depart, arrivee = times[0], times[1]
        cancelled = bool(re.search(r"annul[ée]", window, re.IGNORECASE))
        prefix = m_num.group(1) or "ER"
        results.append({
            "numero": f"{prefix} {m_num.group(2)}",
            "heure_depart": depart,
            "heure_arrivee": arrivee,
            "cancelled": cancelled,
        })

    if not results:
        log(f"AVERTISSEMENT : 0 train extrait pour {slug} — page probablement changée "
            f"ou format inattendu. Cette ligne sera omise pour cette exécution.")
    else:
        log(f"{slug} : {len(results)} trains extraits (bruts, avant filtrage/dédoublonnage).")
    return results


def fetch_all_eurostar(date_iso):
    """Récupère les 4 lignes et fusionne en une seule liste d'arrivées à Gare
    du Nord, en gardant l'origine la plus lointaine pour chaque train physique
    (déduplication par heure d'arrivée, un train Amsterdam/Cologne repassant
    par Bruxelles avec la même heure d'arrivée à Paris)."""
    by_key = {k: fetch_eurostar_route(date_iso, code, slug) for k, code, slug, _ in EUROSTAR_ROUTES}
    label_by_key = {k: label for k, _, _, label in EUROSTAR_ROUTES}

    claimed_arrivals = set()
    final_rows = []
    for key in ORIGIN_PRIORITY:
        rows = by_key.get(key, [])
        # dédoublonnage intra-ligne : deux numéros différents peuvent être le
        # même train physique (codeshare Eurostar/Thalys), reconnaissable à
        # une heure d'arrivée identique. On garde une entrée non-annulée si
        # possible.
        by_arrival = {}
        for r in rows:
            arr = r["heure_arrivee"]
            if arr not in by_arrival or (by_arrival[arr]["cancelled"] and not r["cancelled"]):
                by_arrival[arr] = r
        for arr, r in by_arrival.items():
            if r["cancelled"]:
                continue
            if arr in claimed_arrivals:
                continue  # déjà compté via une ligne plus "en amont" (Cologne/Amsterdam)
            claimed_arrivals.add(arr)
            origine = label_by_key[key] if key != "londres" else "Londres St Pancras"
            train_type = "Eurostar (Londres)" if key == "londres" else "International (Eurostar/Thalys)"
            ligne = (f"Londres - Paris (Eurostar)" if key == "londres"
                     else f"{origine} - Paris (Eurostar/Thalys)")
            final_rows.append({
                "heure": arr,
                "numero": r["numero"],
                "type": train_type,
                "origine": origine,
                "ligne": ligne,
            })

    log(f"Eurostar/Thalys total après dédoublonnage : {len(final_rows)} trains vers Gare du Nord.")
    return final_rows


# --------------------------------------------------------------------------
# Trenitalia Frecciarossa (Milan -> Paris Gare de Lyon) — horaire fixe
# --------------------------------------------------------------------------

# Confirmé sur trenitalia.com (page "il-frecciarossa-arriva-a-parigi", màj le
# 03/08/2026) : 2 trains/jour, horaire stable. Pas de page horaires par date
# comme eurostar.com -> codé en dur, à revérifier périodiquement à la main.
FRECCIAROSSA_TRAINS = [
    {"numero": "FR 9292", "heure": "13:22", "origine": "Milano Centrale",
     "type": "Frecciarossa (Trenitalia)", "ligne": "Milan - Paris (Frecciarossa)"},
    {"numero": "FR 9296", "heure": "22:37", "origine": "Milano Centrale",
     "type": "Frecciarossa (Trenitalia)", "ligne": "Milan - Paris (Frecciarossa)"},
]
# Suspension connue : travaux tunnel du Mont-Cenis, aucun train direct.
FRECCIAROSSA_SUSPENDED_FROM = date(2026, 9, 11)
FRECCIAROSSA_SUSPENDED_TO = date(2026, 10, 9)


def get_frecciarossa_trains(date_obj):
    d = date_obj.date()
    if FRECCIAROSSA_SUSPENDED_FROM <= d <= FRECCIAROSSA_SUSPENDED_TO:
        log("Frecciarossa Milan-Paris suspendu (travaux tunnel Mont-Cenis) pour cette date.")
        return []
    return [dict(t) for t in FRECCIAROSSA_TRAINS]


# --------------------------------------------------------------------------
# European Sleeper (train de nuit Berlin -> Paris Gare du Nord) — horaire fixe
# --------------------------------------------------------------------------

# Confirmé sur europeansleeper.eu le 29/08/2026 : ES 474 part de Berlin
# Gesundbrunnen les nuits de lundi/mercredi/vendredi (17:25) et arrive à Paris
# Gare du Nord le lendemain (mardi/jeudi/samedi) à 11:28. Pas de page horaires
# par date -> horaire fixe codé en dur, à revérifier périodiquement.
EUROPEAN_SLEEPER_ARRIVAL_WEEKDAYS = {1, 3, 5}  # Monday=0 -> mardi=1, jeudi=3, samedi=5


def get_european_sleeper_train(date_obj):
    if date_obj.weekday() not in EUROPEAN_SLEEPER_ARRIVAL_WEEKDAYS:
        return None
    return {
        "heure": "11:28",
        "numero": "ES 474",
        "type": "Train de nuit (European Sleeper)",
        "origine": "Berlin Gesundbrunnen",
        "ligne": "Berlin - Paris (European Sleeper, nuit)",
    }


# --------------------------------------------------------------------------
# Agrégation par créneaux + résumé (identique à la structure attendue par app.js)
# --------------------------------------------------------------------------

def to_minutes(hhmm):
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def slot_label(start_min, size):
    h, m = start_min // 60, start_min % 60
    end_min = start_min + size
    eh, em = (end_min // 60) % 24, end_min % 60
    return f"{h:02d}:{m:02d}", f"{eh:02d}:{em:02d}"


def build_dataset(sncf_df, extra_by_station, date_iso):
    trains_by_station = {}
    slots30_by_station = {}
    slots60_by_station = {}
    summary_by_station = {}

    for gare in STATIONS:
        sub = sncf_df[sncf_df["Gare d'arrivée"] == gare].sort_values("Heure d'arrivée")
        trains = []
        for _, r in sub.iterrows():
            trains.append({
                "heure": r["Heure d'arrivée"][:5],
                "numero": str(r["Numéro de train"]),
                "type": r["Type de train"],
                "origine": r["Origine"],
                "ligne": r["Ligne"],
            })

        for ev in extra_by_station.get(gare, []):
            trains.append(dict(ev))

        trains.sort(key=lambda t: to_minutes(t["heure"] + ":00" if len(t["heure"]) == 5 else t["heure"]))
        trains_by_station[gare] = trains

        def in_range(tstr, start, size):
            mins = to_minutes(tstr)
            return start <= mins < start + size

        slots30 = []
        for i in range(48):
            start = i * 30
            s_lbl, e_lbl = slot_label(start, 30)
            items = [t for t in trains if in_range(t["heure"], start, 30)]
            slots30.append({"start": s_lbl, "end": e_lbl, "count": len(items), "trains": items})
        slots30_by_station[gare] = slots30

        slots60 = []
        for i in range(24):
            start = i * 60
            s_lbl, e_lbl = slot_label(start, 60)
            items = [t for t in trains if in_range(t["heure"], start, 60)]
            slots60.append({"start": s_lbl, "end": e_lbl, "count": len(items), "trains": items})
        slots60_by_station[gare] = slots60

        overnight = [t for t in trains if to_minutes(t["heure"]) >= 24 * 60]

        top60 = sorted([s for s in slots60 if s["count"] > 0], key=lambda s: -s["count"])[:3]
        top30 = sorted([s for s in slots30 if s["count"] > 0], key=lambda s: -s["count"])[:3]
        daytime60 = [s for s in slots60 if 6 * 60 <= to_minutes(s["start"]) <= 23 * 60]
        low60 = sorted([s for s in daytime60 if s["count"] > 0], key=lambda s: s["count"])[:2]

        summary_by_station[gare] = {
            "total": len(trains),
            "bestHour": [{"start": s["start"], "end": s["end"], "count": s["count"]} for s in top60],
            "bestHalfHour": [{"start": s["start"], "end": s["end"], "count": s["count"]} for s in top30],
            "quietHour": [{"start": s["start"], "end": s["end"], "count": s["count"]} for s in low60],
            "overnightCount": len(overnight),
        }

    data = {
        "date": date_iso,
        "stations": STATIONS,
        "trains": trains_by_station,
        "slots30": slots30_by_station,
        "slots60": slots60_by_station,
        "summary": summary_by_station,
    }

    def fr_slot(s):
        return f'{s["start"]}–{s["end"]}'

    for gare, summ in data["summary"].items():
        best60 = summ["bestHour"]
        if best60:
            parts = [f'{fr_slot(s)} ({s["count"]} arrivées)' for s in best60[:2]]
            txt = f"Les créneaux les plus chargés à {gare} sont " + " et ".join(parts) + "."
        else:
            txt = f"Aucune arrivée grandes lignes recensée à {gare} aujourd'hui."
        if summ["overnightCount"] > 0:
            txt += f" (+{summ['overnightCount']} arrivées de nuit après minuit, comptées à part.)"
        summ["text"] = txt

    ranking = sorted(STATIONS, key=lambda g: -data["summary"][g]["total"])
    top_combo = None
    for gare in STATIONS:
        for s in data["summary"][gare]["bestHour"]:
            if top_combo is None or s["count"] > top_combo["count"]:
                top_combo = {"gare": gare, **s}

    data["global"] = {
        "totalAll": sum(data["summary"][g]["total"] for g in STATIONS),
        "ranking": [{"gare": g, "total": data["summary"][g]["total"]} for g in ranking],
        "topCombo": top_combo,
        "text": (
            f"Sur les 6 gares, le pic d'affluence le plus marqué est {top_combo['gare']} "
            f"entre {top_combo['start']} et {top_combo['end']} avec {top_combo['count']} arrivées."
        ) if top_combo else "",
    }
    return data


def main():
    if len(sys.argv) > 1:
        date_obj = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=PARIS_TZ)
    else:
        date_obj = datetime.now(PARIS_TZ)

    date_iso = date_obj.strftime("%Y-%m-%d")
    date_gtfs = date_obj.strftime("%Y%m%d")
    log(f"Génération des données pour le {date_iso} (heure de Paris)")

    dfs = download_gtfs()
    sncf_df = compute_sncf_arrivals(dfs, date_gtfs)

    eurostar_rows = fetch_all_eurostar(date_iso)

    frecciarossa_rows = get_frecciarossa_trains(date_obj)
    if frecciarossa_rows:
        log(f"Frecciarossa : {len(frecciarossa_rows)} trains ajoutés à Gare de Lyon.")

    sleeper_train = get_european_sleeper_train(date_obj)
    gdn_extra = list(eurostar_rows)
    if sleeper_train:
        gdn_extra.append(sleeper_train)
        log("European Sleeper : 1 train de nuit ajouté à Gare du Nord (Berlin -> Paris).")

    extra_by_station = {
        "Paris Gare du Nord": gdn_extra,
        "Paris Gare de Lyon": frecciarossa_rows,
    }

    data = build_dataset(sncf_df, extra_by_station, date_iso)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    log(f"OK : {data['global']['totalAll']} arrivées écrites dans {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
