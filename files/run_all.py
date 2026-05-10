"""
BCN Agenda — Agregador Principal
=================================
Combina tots els scrapers i genera un únic JSON per al frontend.

Scrapers inclosos:
  - CCCB             (cccb_scraper.py)
  - Antiga Fàbrica   (estrelladamm_scraper.py)
  - Mercadillos BCN  (inline — Time Out, agenda BCN, etc.)

Execució:
    python run_all.py                    # tot
    python run_all.py --sources cccb     # només CCCB
    python run_all.py --no-details       # ràpid, sense pàgines de detall
    python run_all.py --output api.json  # output personalitzat
"""

import json
import logging
import argparse
import importlib
import sys
from datetime import datetime, date
from pathlib import Path

log = logging.getLogger("bcn_agenda")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")


# ─── MERCADILLOS ──────────────────────────────────────────────────────────────
# Fonts de mercadillos: Time Out BCN, Agenda BCN, mercatsbcn.com
# Per ara hardcoded com a base — afegir scraper específic si cal

MERCADILLOS_RECURRENTS = [
    {
        "title": "Mercat de Glòries",
        "venue": "Mercat de Glòries",
        "venue_address": "Pl. de les Glòries Catalanes, 08018 Barcelona",
        "type": "food",
        "free": True,
        "price": "Gratuït",
        "recurrence": "Dissabtes 9h–15h",
        "description": "Mercat tradicional al carrer a la Plaça de les Glòries. Productes de proximitat, roba vintage, artesania i menjar de mercat.",
        "tags": ["food", "free"],
        "emoji": "🛒",
        "bg": "#EBF5E8",
        "source": "Mercats BCN",
    },
    {
        "title": "Mercat dels Encants",
        "venue": "Encants Vells",
        "venue_address": "Carrer dels Castillejos, 158, 08013 Barcelona",
        "type": "food",
        "free": True,
        "price": "Gratuït",
        "recurrence": "Dil·luns, Dimecres, Divendres i Dissabte 9h–20h",
        "description": "El mercat de segona mà més gran de Barcelona, sota una coberta espectacular al costat de Glòries. Roba, mobles, col·leccionisme i rareses.",
        "tags": ["food", "free"],
        "emoji": "🏺",
        "bg": "#EBF5E8",
        "source": "Mercats BCN",
    },
    {
        "title": "Mercat de l'Avinguda Gaudí",
        "venue": "Avinguda Gaudí",
        "venue_address": "Avinguda de Gaudí, 08025 Barcelona",
        "type": "food",
        "free": True,
        "price": "Gratuït",
        "recurrence": "Diumenges",
        "description": "Mercat de puestos de proximitat, artesania i productes locals al passeig de l'Avinguda Gaudí, entre la Sagrada Família i el recinte modernista.",
        "tags": ["food", "free"],
        "emoji": "🌿",
        "bg": "#EBF5E8",
        "source": "Mercats BCN",
    },
]


def get_next_occurrence(recurrence_str: str) -> str:
    """Calcula la propera data d'un mercat recurrent."""
    today = date.today()
    day_map = {
        "dilluns": 0, "dimarts": 1, "dimecres": 2, "dijous": 3,
        "divendres": 4, "dissabte": 5, "diumenge": 6,
    }
    lower = recurrence_str.lower()
    for day_name, weekday in day_map.items():
        if day_name in lower:
            days_ahead = (weekday - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 0  # avui
            next_date = today.replace(day=today.day + days_ahead)
            try:
                next_date = date(today.year, today.month, today.day)
                import datetime as dt_module
                delta = (weekday - today.weekday()) % 7
                next_date = today + dt_module.timedelta(days=delta)
                return next_date.isoformat()
            except Exception:
                pass
    return today.isoformat()


def build_mercadillos_events() -> list[dict]:
    """Genera events de mercadillos recurrents amb dates properes."""
    events = []
    import datetime as dt_module

    today = date.today()
    day_map = {
        "dilluns": 0, "dimarts": 1, "dimecres": 2, "dijous": 3,
        "divendres": 4, "dissabte": 5, "diumenge": 6,
    }

    for i, m in enumerate(MERCADILLOS_RECURRENTS):
        recurrence = m.get("recurrence", "").lower()

        # Trobem els dies de la setmana que té
        active_days = [wd for day_name, wd in day_map.items() if day_name in recurrence]

        if not active_days:
            active_days = [6]  # diumenge per defecte

        # Genera les properes 4 setmanes
        for week in range(4):
            for wd in active_days:
                days_ahead = (wd - today.weekday()) % 7 + (week * 7)
                event_date = today + dt_module.timedelta(days=days_ahead)
                event = {**m}
                event["date"] = event_date.isoformat()
                event["date_end"] = event_date.isoformat()
                hour_match = __import__("re").search(r"(\d{1,2})h", recurrence)
                event["time"] = f"{int(hour_match.group(1)):02d}:00" if hour_match else ""
                event["id"] = f"mercat_{i}_{week}_{wd}"
                events.append(event)

    return events


# ─── MERGE & DEDUP ───────────────────────────────────────────────────────────

def merge_events(sources: list[list[dict]]) -> list[dict]:
    """Combina i deduplicar events de múltiples fonts."""
    all_events = []
    seen = set()

    for event_list in sources:
        for event in event_list:
            # Clau de deduplicació: títol normalitzat + data
            title_key = event.get("title", "").lower().strip()[:40]
            date_key = event.get("date", "")
            key = f"{title_key}|{date_key}"

            if key not in seen:
                seen.add(key)
                all_events.append(event)

    # Ordenar per data, events sense data al final
    def sort_key(e):
        d = e.get("date") or "9999"
        t = e.get("time") or "00:00"
        return f"{d}_{t}"

    return sorted(all_events, key=sort_key)


def assign_ids(events: list[dict]) -> list[dict]:
    """Assigna IDs numèrics correlatius."""
    for i, e in enumerate(events):
        e["id"] = i + 1
    return events


# ─── RUNNER ──────────────────────────────────────────────────────────────────

def run_scraper(module_name: str, fetch_details: bool) -> list[dict]:
    """Executa un scraper dinàmicament."""
    try:
        mod = importlib.import_module(module_name)
        log.info(f"▶ Executant {module_name}...")

        if module_name == "cccb_scraper":
            raw = mod.scrape_cccb(fetch_details=fetch_details)
            return mod.normalize_for_frontend(raw)
        elif module_name == "estrelladamm_scraper":
            raw = mod.scrape_damm(fetch_details=fetch_details)
            return mod.normalize(raw)
        elif module_name == "timeout_scraper":
            raw = mod.scrape_timeout(fetch_details=fetch_details)
            return mod.normalize(raw)
        else:
            log.warning(f"Scraper '{module_name}' no reconegut")
            return []
    except ImportError:
        log.warning(f"No s'ha trobat el mòdul '{module_name}' — assegura't que el fitxer existeix")
        return []
    except Exception as e:
        log.error(f"Error executant {module_name}: {e}")
        return []


# ─── STATS ───────────────────────────────────────────────────────────────────

def print_stats(events: list[dict]):
    from collections import Counter

    log.info("\n─── ESTADÍSTIQUES ───────────────────────────────")
    log.info(f"  Total events: {len(events)}")

    by_source = Counter(e.get("source", "?") for e in events)
    log.info("  Per font:")
    for src, count in by_source.most_common():
        log.info(f"    {src}: {count}")

    by_type = Counter(e.get("type", "?") for e in events)
    log.info("  Per tipus:")
    for t, count in by_type.most_common():
        log.info(f"    {t}: {count}")

    free_count = sum(1 for e in events if e.get("free"))
    log.info(f"  Gratuïts: {free_count} ({100*free_count//max(len(events),1)}%)")

    # Dates
    dates = sorted(set(e["date"] for e in events if e.get("date")))
    if dates:
        log.info(f"  Rang dates: {dates[0]} → {dates[-1]}")

    log.info("─────────────────────────────────────────────────\n")


# ─── MAIN ────────────────────────────────────────────────────────────────────

AVAILABLE_SOURCES = ["cccb", "damm", "timeout", "mercadillos"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BCN Agenda — Agregador Principal")
    parser.add_argument(
        "--sources", nargs="+", choices=AVAILABLE_SOURCES, default=AVAILABLE_SOURCES,
        help="Fonts a scrapejar (per defecte: totes)"
    )
    parser.add_argument("--no-details", action="store_true", help="Sense pàgines de detall (més ràpid)")
    parser.add_argument("--output", default="bcn_agenda.json", help="Fitxer JSON de sortida")
    parser.add_argument("--pretty", action="store_true", default=True, help="JSON indentat")
    args = parser.parse_args()

    fetch_details = not args.no_details

    all_event_lists = []

    # ── CCCB ────────────────────────────────────────────────────────────────
    if "cccb" in args.sources:
        cccb_events = run_scraper("cccb_scraper", fetch_details)
        log.info(f"CCCB: {len(cccb_events)} events")
        all_event_lists.append(cccb_events)

    # ── Antiga Fàbrica Estrella Damm ─────────────────────────────────────
    if "damm" in args.sources:
        damm_events = run_scraper("estrelladamm_scraper", fetch_details)
        log.info(f"Antiga Fàbrica: {len(damm_events)} events")
        all_event_lists.append(damm_events)

    # ── Time Out Barcelona ───────────────────────────────────────────────
    if "timeout" in args.sources:
        timeout_events = run_scraper("timeout_scraper", fetch_details)
        log.info(f"Time Out: {len(timeout_events)} events")
        all_event_lists.append(timeout_events)

    # ── Mercadillos ─────────────────────────────────────────────────────
    if "mercadillos" in args.sources:
        mercat_events = build_mercadillos_events()
        log.info(f"Mercadillos: {len(mercat_events)} events")
        all_event_lists.append(mercat_events)

    # ── Merge ────────────────────────────────────────────────────────────
    merged = merge_events(all_event_lists)
    final = assign_ids(merged)

    print_stats(final)

    output = {
        "generated_at": datetime.now().isoformat(),
        "sources": args.sources,
        "total": len(final),
        "events": final,
    }

    indent = 2 if args.pretty else None
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=indent)

    log.info(f"✅ {len(final)} events guardats a '{args.output}'")
    log.info("   → Ara pots servir aquest JSON al frontend BCN Agenda")
