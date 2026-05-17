"""
CCCB Scraper — Centre de Cultura Contemporània de Barcelona
============================================================
Extreu events de www.cccb.org/ca/programa

Execució:
    pip install requests beautifulsoup4
    python cccb_scraper.py

Sortida:
    cccb_events.json   →  llista d'events normalitzats
"""

import json
import time
import logging
import re
from datetime import datetime, date
from typing import Optional
import requests
from bs4 import BeautifulSoup

# ─── CONFIG ─────────────────────────────────────────────────────────────────

BASE_URL = "https://www.cccb.org"
AGENDA_URL = f"{BASE_URL}/ca/programa"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ca-ES,ca;q=0.9,es;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Delay between requests (be polite to the server)
REQUEST_DELAY = 1.5

# How many pages to scrape (CCCB paginates by ~12 events)
MAX_PAGES = 10

# ─── LOGGING ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cccb_scraper")

# ─── CATEGORY MAPPING ────────────────────────────────────────────────────────

CATEGORY_MAP = {
    "exposicio": "art",
    "exposición": "art",
    "exhibition": "art",
    "concert": "music",
    "concerto": "music",
    "musica": "music",
    "música": "music",
    "debat": "culture",
    "debate": "culture",
    "conferencia": "culture",
    "conferència": "culture",
    "cinema": "culture",
    "film": "culture",
    "taller": "family",
    "workshop": "family",
    "familia": "family",
    "família": "family",
    "festival": "music",
    "teatre": "culture",
    "teatro": "culture",
    "dansa": "culture",
    "performance": "culture",
    "visita": "culture",
}


def map_category(raw_type: str) -> str:
    """Normalitza la categoria del CCCB a la nostra taxonomia."""
    if not raw_type:
        return "culture"
    lower = raw_type.lower().strip()
    for key, val in CATEGORY_MAP.items():
        if key in lower:
            return val
    return "culture"


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def get(session: requests.Session, url: str) -> Optional[BeautifulSoup]:
    """Petició HTTP amb reintentos i delay."""
    for attempt in range(3):
        try:
            time.sleep(REQUEST_DELAY)
            r = session.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            log.warning(f"Intent {attempt+1}/3 fallat per {url}: {e}")
            time.sleep(REQUEST_DELAY * (attempt + 1))
    log.error(f"No s'ha pogut obtenir: {url}")
    return None


def parse_date_ca(text: str) -> Optional[str]:
    """
    Converteix textos de data en català/castellà a format ISO YYYY-MM-DD.
    Exemples: '10 de maig de 2025', '10 maig 2025', '10/05/2025'
    """
    if not text:
        return None

    MONTHS = {
        "gener": 1, "febrer": 2, "març": 3, "abril": 4,
        "maig": 5, "juny": 6, "juliol": 7, "agost": 8,
        "setembre": 9, "octubre": 10, "novembre": 11, "desembre": 12,
        "enero": 1, "febrero": 2, "marzo": 3, "mayo": 5,
        "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
        "octubre": 10, "noviembre": 11, "diciembre": 12,
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }

    text = text.lower().strip()

    # Try DD/MM/YYYY
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass

    # Try "10 de maig de 2025" or "10 maig 2025"
    m = re.search(r"(\d{1,2})\s+(?:de\s+)?(\w+)(?:\s+de)?\s+(\d{4})", text)
    if m:
        day, month_str, year = int(m.group(1)), m.group(2), int(m.group(3))
        month_num = MONTHS.get(month_str)
        if month_num:
            try:
                return date(year, month_num, day).isoformat()
            except ValueError:
                pass

    # Try ISO already
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return None


def parse_time(text: str) -> Optional[str]:
    """Extreu hora en format HH:MM."""
    if not text:
        return None
    m = re.search(r"(\d{1,2})[:\.](\d{2})", text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def is_free(text: str) -> bool:
    """Detecta si l'event és gratuït."""
    free_words = ["gratuït", "gratuïta", "gratuito", "gratis", "free", "entrada lliure", "entrada gratuïta"]
    lower = text.lower()
    return any(w in lower for w in free_words)


def clean_text(text: str) -> str:
    """Neteja espais i salts de línia."""
    return " ".join(text.split()).strip() if text else ""


# ─── SCRAPER ─────────────────────────────────────────────────────────────────

def parse_event_card(card, base_url: str) -> Optional[dict]:
    """
    Extreu les dades d'una targeta d'event del llistat.
    
    El CCCB utilitza diversos layouts, intentem els selectors més probables.
    Revisa a https://www.cccb.org/ca/programa i adapta els selectors si cal.
    """
    event = {
        "source": "CCCB",
        "venue": "CCCB",
        "venue_address": "Montalegre, 5, 08001 Barcelona",
        "scraped_at": datetime.now().isoformat(),
    }

    # ── Títol i URL ────────────────────────────────────────────────────────
    # Estructura actual: <li><a href="..."><p class="agenda-card-title">Títol</p></a></li>
    link_el = card.select_one("a[href]")
    title_el = (
        card.select_one("p.agenda-card-title") or
        card.select_one("h2.activity-title") or
        card.select_one("h3.activity-title") or
        card.select_one(".title") or
        card.select_one("h2") or
        card.select_one("h3")
    )
    if not title_el:
        return None

    event["title"] = clean_text(title_el.get_text())
    if link_el:
        href = link_el.get("href", "")
        event["url"] = base_url + href if href.startswith("/") else href

    # ── Dates ──────────────────────────────────────────────────────────────
    date_el = (
        card.select_one(".activity-date") or
        card.select_one(".date") or
        card.select_one("time") or
        card.select_one(".dates") or
        card.select_one("[class*='date']")
    )

    if date_el:
        # Preferim l'atribut datetime si existeix
        raw_date = date_el.get("datetime") or date_el.get_text()
        parsed = parse_date_ca(raw_date)
        if parsed:
            event["date_start"] = parsed
        else:
            event["date_raw"] = clean_text(raw_date)

        # Busquem data fi (p. ex. "Del 10 al 20 de maig")
        full_text = date_el.get_text()
        dates_found = re.findall(r"\d{1,2}(?:\s+de\s+\w+)?(?:\s+de\s+\d{4})?", full_text)
        if len(dates_found) >= 2:
            end_parsed = parse_date_ca(dates_found[-1] + " " + str(date.today().year))
            if end_parsed:
                event["date_end"] = end_parsed

    # ── Hora ───────────────────────────────────────────────────────────────
    time_el = (
        card.select_one(".activity-time") or
        card.select_one(".time") or
        card.select_one("[class*='time']")
    )
    if time_el:
        event["time"] = parse_time(time_el.get_text()) or clean_text(time_el.get_text())

    # ── Tipus / categoria ──────────────────────────────────────────────────
    # Estructura actual: <p class="agenda-card-pretitle"><span>Audiovisuals</span> DocsBarcelona</p>
    type_el = (
        card.select_one("p.agenda-card-pretitle span") or
        card.select_one(".activity-type") or
        card.select_one(".type") or
        card.select_one(".category") or
        card.select_one("[class*='type']") or
        card.select_one(".tag")
    )
    raw_type = clean_text(type_el.get_text()) if type_el else ""
    event["type_raw"] = raw_type
    event["type"] = map_category(raw_type)

    # ── Preu ───────────────────────────────────────────────────────────────
    price_el = (
        card.select_one(".activity-price") or
        card.select_one(".price") or
        card.select_one("[class*='price']")
    )
    raw_price = clean_text(price_el.get_text()) if price_el else ""
    event["price_raw"] = raw_price
    event["free"] = is_free(raw_price) if raw_price else False

    # ── Descripció curta ───────────────────────────────────────────────────
    desc_el = (
        card.select_one(".activity-description") or
        card.select_one(".description") or
        card.select_one("p.excerpt") or
        card.select_one(".excerpt") or
        card.select_one("p")
    )
    event["description"] = clean_text(desc_el.get_text()) if desc_el else ""

    # ── Imatge ─────────────────────────────────────────────────────────────
    img_el = card.select_one("img")
    if img_el:
        src = img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy-src", "")
        event["image_url"] = base_url + src if src.startswith("/") else src

    return event


def scrape_event_detail(session: requests.Session, event: dict) -> dict:
    """
    Visita la pàgina de detall d'un event per obtenir més info
    (descripció completa, hora exacta, preu).
    """
    url = event.get("url")
    if not url:
        return event

    soup = get(session, url)
    if not soup:
        return event

    log.info(f"  Detall: {event.get('title', '')[:50]}")

    # Descripció completa
    desc_el = (
        soup.select_one(".mp-formated-content") or
        soup.select_one(".activity-body") or
        soup.select_one(".activity-description") or
        soup.select_one(".description") or
        soup.select_one("article .content") or
        soup.select_one(".intro")
    )
    if desc_el:
        event["description_full"] = clean_text(desc_el.get_text())

    # Data del detall (estructura actual: <div class="subhero-card-text"><span>7 - 17 de maig 2026</span>)
    if not event.get("date_start"):
        date_span = soup.select_one("div.subhero-card-text span")
        if date_span:
            raw = clean_text(date_span.get_text())
            event["date_raw"] = raw
            # Format "7 - 17 de maig 2026" → agafem la data d'inici
            parts = re.split(r"\s*[-–]\s*", raw)
            if len(parts) >= 2:
                # "17 de maig 2026" és la data final; construïm la inicial afegint el mes/any
                end_str = parts[-1].strip()
                month_year = re.search(r"(?:de\s+)?(\w+)(?:\s+de\s+|\s+)(\d{4})", end_str, re.IGNORECASE)
                if month_year:
                    start_day = re.search(r"^\d+", parts[0].strip())
                    if start_day:
                        event["date_start"] = parse_date_ca(f"{start_day.group()} de {month_year.group(1)} {month_year.group(2)}")
                event["date_end"] = parse_date_ca(end_str)
            else:
                event["date_start"] = parse_date_ca(raw)

    # JSON-LD (molt útil si el CCCB el genera)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            if data.get("@type") in ("Event", "MusicEvent", "TheaterEvent"):
                if data.get("startDate"):
                    dt = data["startDate"]
                    event["date_start"] = dt[:10]  # YYYY-MM-DD
                    if "T" in dt:
                        event["time"] = dt[11:16]
                if data.get("endDate"):
                    event["date_end"] = data["endDate"][:10]
                if data.get("name"):
                    event["title"] = data["name"]
                if data.get("description"):
                    event["description"] = data["description"]
                if data.get("offers"):
                    offers = data["offers"]
                    if isinstance(offers, list):
                        offers = offers[0]
                    price = offers.get("price", "")
                    if str(price) == "0" or price == 0:
                        event["free"] = True
                        event["price_raw"] = "Gratuït"
                    elif price:
                        event["price_raw"] = f"{price} {offers.get('priceCurrency', '€')}"
                if data.get("image"):
                    event["image_url"] = data["image"]
                break
        except (json.JSONDecodeError, AttributeError):
            continue

    # Hora si no la tenim
    if "time" not in event:
        time_el = soup.select_one(".time") or soup.select_one("[class*='time']")
        if time_el:
            event["time"] = parse_time(time_el.get_text()) or clean_text(time_el.get_text())

    # Preu si no el tenim
    if not event.get("price_raw"):
        price_el = soup.select_one(".price") or soup.select_one("[class*='price']")
        if price_el:
            raw_price = clean_text(price_el.get_text())
            event["price_raw"] = raw_price
            event["free"] = is_free(raw_price)

    return event


def scrape_listing_page(session: requests.Session, page: int = 1) -> tuple[list[dict], bool]:
    """
    Scrapes una pàgina del llistat de programa del CCCB.
    Retorna (events, has_next_page).
    
    NOTA: Ajusta l'URL de paginació si el CCCB utilitza ?page=N, ?p=N, etc.
    """
    if page == 1:
        url = AGENDA_URL
    else:
        # Prova el patró de paginació del CCCB — comprova a la web si cal ajustar
        url = f"{AGENDA_URL}?page={page}"

    log.info(f"Scraping pàgina {page}: {url}")
    soup = get(session, url)
    if not soup:
        return [], False

    # ── Cercar contenidor principal ─────────────────────────────────────────
    # Selectors probables per al CCCB — ajusta si veus que no funciona
    CARD_SELECTORS = [
        "li.agenda-card-item",  # selector actual (2025-2026)
        "article.activity-item",
        "article.activity",
        ".activity-card",
        ".activity-list-item",
        "li.activity",
        ".program-item",
        ".event-item",
        "article",
    ]

    cards = []
    for sel in CARD_SELECTORS:
        cards = soup.select(sel)
        if cards:
            log.info(f"  Selector '{sel}' → {len(cards)} targetes")
            break

    if not cards:
        log.warning("  No s'han trobat targetes — comprova els selectors")
        # Debug: mostra l'estructura HTML
        body = soup.find("main") or soup.find("body")
        if body:
            log.debug("  Primeres 500 chars del body: " + body.get_text()[:500])
        return [], False

    events = []
    for card in cards:
        event = parse_event_card(card, BASE_URL)
        if event and event.get("title"):
            events.append(event)

    # ── Comprovar si hi ha pàgina següent ──────────────────────────────────
    next_btn = (
        soup.select_one("a[rel='next']") or
        soup.select_one(".pagination .next") or
        soup.select_one("a.next-page") or
        soup.select_one(".pager-next a")
    )
    has_next = next_btn is not None

    return events, has_next


def scrape_cccb(fetch_details: bool = True) -> list[dict]:
    """
    Entry point principal. Scrapes tot el programa del CCCB.
    
    Args:
        fetch_details: Si True, visita cada event per obtenir més info.
                       Poseu-lo a False per a un scraping ràpid.
    """
    session = requests.Session()
    all_events = []
    seen_urls = set()

    for page in range(1, MAX_PAGES + 1):
        events, has_next = scrape_listing_page(session, page)

        # Deduplicar per URL
        new_events = []
        for e in events:
            url = e.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                new_events.append(e)
            elif not url:
                new_events.append(e)

        if fetch_details:
            enriched = []
            for e in new_events:
                enriched.append(scrape_event_detail(session, e))
            all_events.extend(enriched)
        else:
            all_events.extend(new_events)

        log.info(f"  Total acumulat: {len(all_events)} events")

        if not has_next:
            log.info(f"Última pàgina ({page}). Finalitzant.")
            break

    # Ordenar per data
    def sort_key(e):
        return e.get("date_start") or e.get("date_raw") or ""

    all_events.sort(key=sort_key)

    return all_events


def normalize_for_frontend(events: list[dict]) -> list[dict]:
    """
    Converteix al format esperat pel frontend de BCN Agenda.
    """
    normalized = []
    TYPE_EMOJI = {
        "music": "🎵",
        "art": "🎨",
        "culture": "🏛",
        "family": "👨‍👩‍👧",
        "food": "🍜",
    }
    TYPE_BG = {
        "music": "#FFF0EB",
        "art": "#EBF0FF",
        "culture": "#F0EBFF",
        "family": "#FFF5EB",
        "food": "#EBF5E8",
    }

    for i, e in enumerate(events):
        tags = [e.get("type", "culture")]
        if e.get("free"):
            tags.append("free")

        normalized.append({
            "id": i + 1,
            "date": e.get("date_start", ""),
            "time": e.get("time", ""),
            "title": e.get("title", ""),
            "venue": "CCCB",
            "type": e.get("type", "culture"),
            "free": e.get("free", False),
            "price": e.get("price_raw", ""),
            "emoji": TYPE_EMOJI.get(e.get("type", "culture"), "🏛"),
            "bg": TYPE_BG.get(e.get("type", "culture"), "#F0EBFF"),
            "tags": tags,
            "desc": e.get("description_full") or e.get("description", ""),
            "url": e.get("url", ""),
            "image": e.get("image_url", ""),
            "source": "CCCB",
        })

    return normalized


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scraper d'events del CCCB")
    parser.add_argument("--no-details", action="store_true", help="Salta les pàgines de detall (més ràpid)")
    parser.add_argument("--output", default="cccb_events.json", help="Fitxer de sortida JSON")
    parser.add_argument("--pages", type=int, default=MAX_PAGES, help="Màxim de pàgines a scrapejar")
    args = parser.parse_args()

    MAX_PAGES = args.pages

    log.info("🏛  Iniciant scraper del CCCB...")
    log.info(f"   URL base: {AGENDA_URL}")
    log.info(f"   Màx pàgines: {MAX_PAGES}")
    log.info(f"   Detalls: {'No' if args.no_details else 'Sí'}")

    raw_events = scrape_cccb(fetch_details=not args.no_details)
    frontend_events = normalize_for_frontend(raw_events)

    output = {
        "scraped_at": datetime.now().isoformat(),
        "source": "CCCB",
        "total": len(frontend_events),
        "events": frontend_events,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info(f"\n✅ {len(frontend_events)} events guardats a '{args.output}'")

    # Preview
    if frontend_events:
        log.info("\n📋 Primers 3 events:")
        for e in frontend_events[:3]:
            log.info(f"   [{e['date']}] {e['title']} — {e['price'] or 'preu pendent'}")
