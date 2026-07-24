"""
Filtre et republie un emploi du temps ADE (Paris Nanterre) au format ICS.

Ce script :
1. Lit le fichier ICS source, exporté MANUELLEMENT depuis l'application
   ADE de bureau (bouton "Ok", pas "Generate URL" - ce dernier tronque
   le planning au 16/11/2026 côté serveur ADE, bug indépendant de notre
   script). Le fichier attendu s'appelle "source.ics" et doit se trouver
   à la racine du dépôt.
2. Retire les événements dont le titre / la salle / la description contient
   un des mots-clés exclus (définis dans config.yaml).
3. Convertit toutes les dates en UTC et reconstruit le fichier ICS sans les
   blocs VTIMEZONE d'origine. C'est volontaire : plusieurs générateurs ADE
   publient des VTIMEZONE dont la règle de récurrence ne couvre pas toute
   l'année scolaire, ce qui amène Apple Calendar à ignorer silencieusement
   les événements situés au-delà de cette limite. En exprimant directement
   les horaires en UTC, on supprime cette dépendance et on évite la
   troncature.

Pour mettre à jour l'emploi du temps : ré-exportez "source.ics" depuis ADE
et uploadez-le à la racine du dépôt (il remplace l'ancien). Le workflow
GitHub Actions se charge ensuite de refaire le filtrage automatiquement.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml
from icalendar import Calendar

UTC = ZoneInfo("UTC")
PARIS = ZoneInfo("Europe/Paris")

CONFIG_PATH = "config.yaml"
SOURCE_ICS_PATH = "source.ics"
OUTPUT_PATH = os.path.join("docs", "edt_filtre.ics")


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def read_source_ics(path: str = SOURCE_ICS_PATH) -> bytes:
    if not os.path.exists(path):
        sys.exit(
            f"Erreur : fichier source introuvable ({path}). "
            f"Exportez votre emploi du temps depuis ADE (bouton 'Ok') "
            f"et uploadez-le à la racine du dépôt sous le nom '{path}'."
        )
    with open(path, "rb") as f:
        return f.read()


def matches_exclude(event, keywords: list[str]) -> bool:
    if not keywords:
        return False
    parts = []
    for field in ("SUMMARY", "LOCATION", "DESCRIPTION"):
        val = event.get(field)
        if val:
            parts.append(str(val).lower())
    combined = " ".join(parts)
    return any(kw.lower() in combined for kw in keywords)


def force_utc(event, field: str) -> None:
    val = event.get(field)
    if val is None:
        return
    dt = val.dt
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=PARIS)
        dt_utc = dt.astimezone(UTC)
        del event[field]
        event.add(field, dt_utc)
    # si c'est une date seule (événement "journée entière"), rien à faire


def filter_and_rebuild(raw_ics: bytes, exclude_keywords: list[str]) -> bytes:
    source_cal = Calendar.from_ical(raw_ics)

    new_cal = Calendar()
    new_cal.add("prodid", "-//EDT Filtre Paris Nanterre//FR")
    new_cal.add("version", "2.0")
    new_cal.add("calscale", "GREGORIAN")
    new_cal.add("x-wr-calname", "Emploi du temps (filtré)")

    kept, dropped = 0, 0
    for component in source_cal.walk("VEVENT"):
        if matches_exclude(component, exclude_keywords):
            dropped += 1
            continue
        force_utc(component, "DTSTART")
        force_utc(component, "DTEND")
        new_cal.add_component(component)
        kept += 1

    print(f"Événements conservés : {kept} | exclus : {dropped}")
    if kept == 0:
        print(
            "Attention : 0 événement conservé. Vérifiez que les mots-clés "
            "d'exclusion dans config.yaml ne sont pas trop larges."
        )
    return new_cal.to_ical()


def main() -> None:
    config = load_config()
    raw = read_source_ics()
    filtered = filter_and_rebuild(raw, config.get("exclude_keywords", []))

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "wb") as f:
        f.write(filtered)
    print(f"Fichier écrit : {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
