"""
Filtre et republie un emploi du temps ADE (Paris Nanterre) au format ICS.

Ce script :
1. Télécharge le fichier ICS source (URL d'abonnement ADE).
2. Retire les événements dont le titre / la salle / la description contient
   un des mots-clés exclus (définis dans config.yaml).
3. Convertit toutes les dates en UTC et reconstruit le fichier ICS sans les
   blocs VTIMEZONE d'origine. C'est volontaire : plusieurs générateurs ADE
   publient des VTIMEZONE dont la règle de récurrence ne couvre pas toute
   l'année scolaire, ce qui amène Apple Calendar à ignorer silencieusement
   les événements situés au-delà de cette limite. En exprimant directement
   les horaires en UTC, on supprime cette dépendance et on évite la
   troncature.

L'URL source est lue dans la variable d'environnement EDT_SOURCE_URL
(définie comme secret GitHub Actions) pour éviter de la stocker en clair
dans le dépôt. Si elle est absente, le script se rabat sur config.yaml
(pratique pour un test en local).
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import yaml
from icalendar import Calendar

UTC = ZoneInfo("UTC")
PARIS = ZoneInfo("Europe/Paris")

CONFIG_PATH = "config.yaml"
OUTPUT_PATH = os.path.join("docs", "edt_filtre.ics")


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_source_url(config: dict) -> str:
    url = os.environ.get("EDT_SOURCE_URL") or config.get("source_url")
    if not url:
        sys.exit(
            "Erreur : aucune URL source trouvée. "
            "Définissez le secret EDT_SOURCE_URL ou renseignez "
            "'source_url' dans config.yaml pour un test local."
        )

    # Nettoyage défensif : espaces/retours à la ligne parasites, guillemets
    # ajoutés par erreur en collant l'URL, et préfixe "webcal://" (utilisé
    # par certains calendriers mais non supporté par la librairie requests).
    url = url.strip().strip('"').strip("'").strip()
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]

    if not (url.startswith("http://") or url.startswith("https://")):
        sys.exit(
            f"Erreur : l'URL source ne commence ni par http:// ni par "
            f"https:// une fois nettoyée : {url!r}. Vérifiez le contenu "
            f"exact du secret EDT_SOURCE_URL."
        )
    return url


def fetch_ics(url: str) -> bytes:
    headers = {
        "Accept": "text/calendar,text/plain,*/*",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    }
    try:
        from curl_cffi import requests as curl_requests

        resp = curl_requests.get(
            url, timeout=30, headers=headers, impersonate="safari17_0"
        )
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"Échec avec curl_cffi (empreinte Safari) : {e}")
        # Repli sur requests classique, au cas où le blocage venait d'autre chose
        fallback_headers = {
            **headers,
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Safari/605.1.15"
            ),
        }
        resp = requests.get(url, timeout=30, headers=fallback_headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e2:
            print(f"Échec aussi avec requests classique : {e2}")
            print(f"Code HTTP : {resp.status_code}")
            print(f"Début de la réponse du serveur : {resp.text[:500]!r}")
            raise
        return resp.content


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
    source_url = get_source_url(config)
    raw = fetch_ics(source_url)
    filtered = filter_and_rebuild(raw, config.get("exclude_keywords", []))

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "wb") as f:
        f.write(filtered)
    print(f"Fichier écrit : {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_source_url(config: dict) -> str:
    url = os.environ.get("EDT_SOURCE_URL") or config.get("source_url")
    if not url:
        sys.exit(
            "Erreur : aucune URL source trouvée. "
            "Définissez le secret EDT_SOURCE_URL ou renseignez "
            "'source_url' dans config.yaml pour un test local."
        )
    return url


def fetch_ics(url: str) -> bytes:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Safari/605.1.15"
        ),
        "Accept": "text/calendar,text/plain,*/*",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(url, timeout=30, headers=headers)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"Échec de la récupération : {e}")
        print(f"Code HTTP : {resp.status_code}")
        print(f"Début de la réponse du serveur : {resp.text[:500]!r}")
        raise
    return resp.content


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
    source_url = get_source_url(config)
    raw = fetch_ics(source_url)
    filtered = filter_and_rebuild(raw, config.get("exclude_keywords", []))

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "wb") as f:
        f.write(filtered)
    print(f"Fichier écrit : {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
