"""
Antiga Fàbrica Estrella Damm Scraper
======================================
Extreu events de www.estrelladamm.com/la-agenda

La web de Damm té dues complexitats:
  1. Porta edat gate (cookie de majoria d'edat)
  2. Alguns events es carreguen via JS — el scraper gestiona les dues situacions

Execució:
    pip install requests beautifulsoup4
    python estrelladamm_scraper.py

Sortida:
    estrelladamm_events.json
"""

import json
import time
import logging
import re
from datetime import datetime, date
from typing import Optional
import requests
from bs4 import BeautifulSoup

# ─── CONFIG ──────────────────────────────────────────────────────────────────

BASE_URL = "https://www.estrelladamm.com"

# La Fàbrica té agenda en castellà i anglès
AGENDA_URLS = [
    f"{BASE_URL}/la-agenda",           # castellà (principal)
    f"{BASE_URL}/en/the-calendar",     # anglès (fallback)
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ca-ES,ca;q=0.9,es;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": BASE_URL,
}

# Cookie que accepta la verificació de majoria d'edat (imprescindible)
AGE_GATE_COOKIES = {
    "edad": "true",
    "age_gate": "1",
    "legal_age": "true",
    "isLegal": "true",
}

REQUEST_DELAY = 1.5
MAX_PAGES = 15

# ─── LOGGING ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("damm_scraper")

# ─── CATEGORY MAPPING ────────────────────────────────────────────────────────

KEYWORD_TO_TYPE = {
    # Música
    "concert": "music", "concierto": "music", "música": "music",
    "musica": "music", "festival": "music", "indie": "music",
    "jazz": "music", "rock": "music", "pop": "music", "folk": "music",
    "dj": "music", "actuació": "music", "actuacion": "music",
    "directo": "music", "live": "music", "sant jordi musical": "music",
    "la mercè": "music", "merce": "music",

    # Food & markets
    "market": "food", "mercado": "food", "mercat": "food",
    "gastro": "food", "food": "food", "cuina": "food",
    "cocina": "food", "chef": "food", "food truck": "food",
    "foodtruck": "food", "gastronomic": "food",

    # Art & disseny
    "disseny": "art", "diseño": "art", "design": "art",
    "il·lustració": "art", "ilustración": "art", "illustration": "art",
    "exposici": "art", "exhibición": "art", "exhibition": "art",
    "art": "art", "fotografia": "art", "photo": "art",

    # Família
    "familiar": "family", "familia": "family", "famille": "family",
    "nens": "family", "niños": "family", "kids": "family",
    "taller": "family", "workshop": "family",

    # Cultura general
    "charla": "culture", "xerrada": "culture", "debat": "culture",
    "debate": "culture", "conferencia": "culture", "taula": "culture",
    "cinema": "culture", "film": "culture", "teatre": "culture",
}

def classify_event(title: str, description: str = "") -> str:
    text = (title + " " + description).lower()
    for keyword, category in KEYWORD_TO_TYPE.items():
        if keyword in text:
            return category
    return "culture"


# ─── DATE PARSING ────────────────────────────────────────────────────────────

MONTH_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
    "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
}
MONTH_CA = {
    "gener": 1, "febrer": 2, "març": 3, "abril": 4, "maig": 5,
    "juny": 6, "juliol": 7, "agost": 8, "setembre": 9,
    "octubre": 10, "novembre": 11, "desembre": 12,
}
MONTHS = {**MONTH_ES, **MONTH_CA}


def parse_date(text: str) -> Optional[str]:
    if not text:
        return None
    text = text.lower().strip()

    # ISO o DD/MM/YYYY
    for pattern in [
        r"(\d{4})-(\d{2})-(\d{2})",
        r"(\d{2})[/\-.](\d{2})[/\-.](\d{4})",
    ]:
        m = re.search(pattern, text)
        if m:
            try:
                if len(m.group(1)) == 4:
                    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                else:
                    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
            except ValueError:
                pass

    # "19 de marzo de 2025" / "19 marzo 2025" / "19 de marzo"
    m = re.search(r"(\d{1,2})\s+(?:de\s+)?(\w+)(?:\s+(?:de\s+)?(\d{4}))?", text)
    if m:
        day = int(m.group(1))
        month_str = m.group(2)
        year = int(m.group(3)) if m.group(3) else datetime.now().year
        month_num = MONTHS.get(month_str)
        if month_num:
            try:
                return date(year, month_num, day).isoformat()
            except ValueError:
                pass
    return None


def parse_time(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(\d{1,2})[:\.](\d{2})\s*(?:h|hrs?)?", text.lower())
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    # Formats tipus "20h", "20h30"
    m = re.search(r"(\d{1,2})h(\d{2})?", text.lower())
    if m:
        mins = m.group(2) or "00"
        return f"{int(m.group(1)):02d}:{mins}"
    return None


def is_free(text: str) -> bool:
    markers = ["gratuito", "gratuïta", "gratuït", "gratis", "free",
               "entrada libre", "entrada gratuita", "entrada lliure"]
    lower = text.lower()
    return any(m in lower for m in markers)


def clean(text: str) -> str:
    return " ".join(text.split()).strip() if text else ""


# ─── HTTP ────────────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    """Crea sessió amb cookies d'edat acceptada."""
    s = requests.Session()
    s.headers.update(HEADERS)
    # Acceptar edat gate
    for k, v in AGE_GATE_COOKIES.items():
        s.cookies.set(k, v, domain="www.estrelladamm.com")
    # Primera visita per obtenir cookies reals del servidor
    try:
        time.sleep(REQUEST_DELAY)
        r = s.get(BASE_URL, timeout=12)
        log.info(f"Home: {r.status_code} | Cookies: {list(s.cookies.keys())}")
    except requests.RequestException as e:
        log.warning(f"No s'ha pogut fer la primera visita: {e}")
    return s


def get(session: requests.Session, url: str) -> Optional[BeautifulSoup]:
    for attempt in range(3):
        try:
            time.sleep(REQUEST_DELAY)
            r = session.get(url, timeout=15)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            log.warning(f"HTTP {r.status_code} per {url}")
        except requests.RequestException as e:
            log.warning(f"Intent {attempt+1}/3: {e}")
            time.sleep(REQUEST_DELAY * 2)
    return None


# ─── PARSERS ─────────────────────────────────────────────────────────────────

def parse_card(card: BeautifulSoup, base_url: str) -> Optional[dict]:
    """
    Extreu dades d'una targeta d'event.

    Estructura típica de Damm (comprova a la web i ajusta si cal):

      <article class="event-item">
        <a href="/la-agenda/nom-event">
          <img src="..." />
          <div class="event-date">19 de marzo de 2025</div>
          <h2 class="event-title">Nom de l'event</h2>
          <p class="event-description">...</p>
          <span class="event-tag">Concierto</span>
        </a>
      </article>
    """
    event = {
        "source": "Antiga Fàbrica Estrella Damm",
        "venue": "Antiga Fàbrica Estrella Damm",
        "venue_address": "Carrer de Rosselló, 515, 08025 Barcelona",
        "scraped_at": datetime.now().isoformat(),
    }

    # ── Títol i URL ────────────────────────────────────────────────────────
    title_el = (
        card.select_one("h2 a") or card.select_one("h3 a") or
        card.select_one(".event-title") or card.select_one(".title") or
        card.select_one("h2") or card.select_one("h3") or
        card.select_one("a[class*='title']")
    )

    link_el = card.select_one("a[href]")
    if not title_el and not link_el:
        return None

    if title_el:
        event["title"] = clean(title_el.get_text())
        href = title_el.get("href") or (link_el.get("href") if link_el else "")
    else:
        event["title"] = clean(link_el.get_text())
        href = link_el.get("href", "")

    if href:
        event["url"] = base_url + href if href.startswith("/") else href

    if not event.get("title"):
        return None

    # ── Data ───────────────────────────────────────────────────────────────
    date_el = (
        card.select_one(".event-date") or card.select_one(".date") or
        card.select_one("time") or card.select_one("[class*='date']") or
        card.select_one(".fecha") or card.select_one(".data")
    )
    if date_el:
        raw = date_el.get("datetime") or date_el.get_text()
        parsed = parse_date(raw)
        if parsed:
            event["date_start"] = parsed
        else:
            event["date_raw"] = clean(raw)

    # ── Hora ───────────────────────────────────────────────────────────────
    time_el = (
        card.select_one(".event-time") or card.select_one(".time") or
        card.select_one(".hora") or card.select_one("[class*='time']")
    )
    if time_el:
        t = parse_time(time_el.get_text())
        if t:
            event["time"] = t

    # ── Descripció ─────────────────────────────────────────────────────────
    desc_el = (
        card.select_one(".event-description") or card.select_one(".description") or
        card.select_one("p.excerpt") or card.select_one(".excerpt") or
        card.select_one("p")
    )
    event["description"] = clean(desc_el.get_text()) if desc_el else ""

    # ── Tag / categoria del Damm ───────────────────────────────────────────
    tag_el = (
        card.select_one(".event-tag") or card.select_one(".tag") or
        card.select_one(".category") or card.select_one("[class*='tag']")
    )
    event["tag_raw"] = clean(tag_el.get_text()) if tag_el else ""
    event["type"] = classify_event(event["title"], event["description"])

    # ── Preu ───────────────────────────────────────────────────────────────
    price_el = (
        card.select_one(".event-price") or card.select_one(".price") or
        card.select_one("[class*='price']") or card.select_one(".precio")
    )
    if price_el:
        raw_price = clean(price_el.get_text())
        event["price_raw"] = raw_price
        event["free"] = is_free(raw_price)
    else:
        # Buscar "gratuito" al títol o descripció
        full_text = event["title"] + " " + event.get("description", "")
        event["free"] = is_free(full_text)
        event["price_raw"] = "Gratuït" if event["free"] else ""

    # ── Imatge ─────────────────────────────────────────────────────────────
    img_el = card.select_one("img")
    if img_el:
        src = img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy-src", "")
        if src:
            event["image_url"] = base_url + src if src.startswith("/") else src

    return event


def enrich_event(session: requests.Session, event: dict) -> dict:
    """Visita la pàgina de detall per obtenir hora, preu complet i descripció."""
    url = event.get("url")
    if not url:
        return event

    log.info(f"  ↳ Detall: {event.get('title', '')[:55]}")
    soup = get(session, url)
    if not soup:
        return event

    # JSON-LD → font més fiable
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            # Pot ser un array o un objecte
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") in ("Event", "MusicEvent", "TheaterEvent", "SocialEvent"):
                    if item.get("startDate"):
                        dt = item["startDate"]
                        event["date_start"] = dt[:10]
                        if "T" in dt:
                            event["time"] = dt[11:16]
                    if item.get("endDate"):
                        event["date_end"] = item["endDate"][:10]
                    if item.get("name") and not event.get("title"):
                        event["title"] = item["name"]
                    if item.get("description"):
                        event["description_full"] = clean(item["description"])
                    if item.get("image"):
                        img = item["image"]
                        event["image_url"] = img[0] if isinstance(img, list) else img
                    offers = item.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price = offers.get("price", "")
                    currency = offers.get("priceCurrency", "€")
                    if str(price) in ("0", "0.0", ""):
                        event["free"] = True
                        event["price_raw"] = "Gratuït"
                    elif price:
                        event["price_raw"] = f"{price}{currency}"
                        event["free"] = False
                    break
        except (json.JSONDecodeError, AttributeError, KeyError):
            continue

    # Descripció llarga si no la tenim
    if not event.get("description_full"):
        body_el = (
            soup.select_one(".event-body") or
            soup.select_one(".event-content") or
            soup.select_one(".event-description") or
            soup.select_one("article .content") or
            soup.select_one(".body-text") or
            soup.select_one("main p")
        )
        if body_el:
            event["description_full"] = clean(body_el.get_text())

    # Hora si no la tenim
    if not event.get("time"):
        for el in soup.select("[class*='time'], [class*='hora'], [class*='schedule']"):
            t = parse_time(el.get_text())
            if t:
                event["time"] = t
                break

    # Preu si no el tenim
    if not event.get("price_raw"):
        for el in soup.select("[class*='price'], [class*='precio'], [class*='preu']"):
            raw = clean(el.get_text())
            if raw:
                event["price_raw"] = raw
                event["free"] = is_free(raw)
                break

    return event


# ─── LISTING PAGE ────────────────────────────────────────────────────────────

def scrape_page(session: requests.Session, url: str) -> tuple[list[dict], Optional[str]]:
    """
    Scrapes una pàgina de listing. Retorna (events, next_page_url).

    Damm pot usar:
      - Paginació clàssica: ?page=N
      - "Carrega més" (Load more): botó que llança petició Ajax
    """
    log.info(f"Fetching: {url}")
    soup = get(session, url)
    if not soup:
        return [], None

    # ── Cercar targetes ────────────────────────────────────────────────────
    SELECTORS = [
        "article.event-item",
        "article.event",
        ".event-card",
        ".agenda-item",
        ".calendar-item",
        "li.event",
        ".event-list-item",
        "article",          # fallback
    ]

    cards = []
    for sel in SELECTORS:
        candidates = soup.select(sel)
        # Filtra articles que semblen events (tenen un link a /la-agenda/ o /the-calendar/)
        valid = [c for c in candidates if c.select_one("a[href*='agenda'], a[href*='calendar']")]
        if valid:
            log.info(f"  Selector '{sel}' → {len(valid)} events")
            cards = valid
            break
        elif candidates:
            # Pren-los igualment si no en trobem de millors
            if not cards:
                cards = candidates

    if not cards:
        log.warning("  Sense targetes — revisa els selectors o comprova si la pàgina usa JS")
        # Debug: guarda HTML per inspecció
        with open("debug_damm.html", "w", encoding="utf-8") as f:
            f.write(str(soup))
        log.info("  HTML guardat a debug_damm.html per inspecció manual")
        return [], None

    events = []
    for card in cards:
        event = parse_card(card, BASE_URL)
        if event and event.get("title"):
            events.append(event)

    # ── Pàgina següent ─────────────────────────────────────────────────────
    next_url = None
    next_el = (
        soup.select_one("a[rel='next']") or
        soup.select_one(".pagination .next a") or
        soup.select_one("a.next-page") or
        soup.select_one(".pager-next a") or
        soup.select_one("a[aria-label='Siguiente']") or
        soup.select_one("a[aria-label='Next']")
    )
    if next_el and next_el.get("href"):
        href = next_el["href"]
        next_url = BASE_URL + href if href.startswith("/") else href

    # Fallback: paginació per query string
    if not next_url:
        current_page = 1
        m = re.search(r"[?&]page=(\d+)", url)
        if m:
            current_page = int(m.group(1))
        # Comprova si hi ha indicador de més contingut
        load_more = soup.select_one("[class*='load-more'], [class*='loadmore']")
        if load_more:
            sep = "&" if "?" in url else "?"
            next_url = f"{url}{sep}page={current_page + 1}"

    return events, next_url


# ─── MAIN SCRAPER ────────────────────────────────────────────────────────────

def scrape_damm(fetch_details: bool = True) -> list[dict]:
    session = make_session()
    all_events = []
    seen_urls = set()

    # Prova ambdues URLs (castellà i anglès)
    start_url = None
    for agenda_url in AGENDA_URLS:
        log.info(f"Provant: {agenda_url}")
        time.sleep(REQUEST_DELAY)
        try:
            r = session.get(agenda_url, timeout=12)
            if r.status_code == 200:
                start_url = agenda_url
                log.info(f"✓ Agenda accessible: {agenda_url}")
                break
            log.warning(f"  HTTP {r.status_code}")
        except Exception as e:
            log.warning(f"  Error: {e}")

    if not start_url:
        log.error("No s'ha pogut accedir a cap URL de l'agenda. Comprova la connexió.")
        return []

    current_url = start_url
    pages_scraped = 0

    while current_url and pages_scraped < MAX_PAGES:
        events, next_url = scrape_page(session, current_url)
        pages_scraped += 1

        # Deduplicar
        new_events = []
        for e in events:
            url = e.get("url", "")
            key = url or e.get("title", "")
            if key not in seen_urls:
                seen_urls.add(key)
                new_events.append(e)

        if fetch_details:
            enriched = [enrich_event(session, e) for e in new_events]
            all_events.extend(enriched)
        else:
            all_events.extend(new_events)

        log.info(f"  Pàgina {pages_scraped}: +{len(new_events)} events (total: {len(all_events)})")

        current_url = next_url

    log.info(f"Finalitzat. Total: {len(all_events)} events en {pages_scraped} pàgines.")
    return all_events


# ─── NORMALITZAR per al frontend ─────────────────────────────────────────────

def normalize(events: list[dict]) -> list[dict]:
    TYPE_EMOJI = {
        "music": "🎵", "art": "🎨", "culture": "🏛",
        "family": "👨‍👩‍👧", "food": "🍜",
    }
    TYPE_BG = {
        "music": "#FFF0EB", "art": "#EBF0FF", "culture": "#F0EBFF",
        "family": "#FFF5EB", "food": "#EBF5E8",
    }

    result = []
    for i, e in enumerate(events):
        event_type = e.get("type", "culture")
        tags = [event_type]
        if e.get("free"):
            tags.append("free")

        result.append({
            "id": i + 1,
            "date": e.get("date_start", ""),
            "date_end": e.get("date_end", ""),
            "time": e.get("time", ""),
            "title": e.get("title", ""),
            "venue": "Antiga Fàbrica Estrella Damm",
            "type": event_type,
            "free": e.get("free", False),
            "price": e.get("price_raw", ""),
            "emoji": TYPE_EMOJI.get(event_type, "🎪"),
            "bg": TYPE_BG.get(event_type, "#F5F0E8"),
            "tags": tags,
            "desc": e.get("description_full") or e.get("description", ""),
            "url": e.get("url", ""),
            "image": e.get("image_url", ""),
            "source": "Antiga Fàbrica Estrella Damm",
        })

    return sorted(result, key=lambda x: x.get("date") or "")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scraper Antiga Fàbrica Estrella Damm")
    parser.add_argument("--no-details", action="store_true", help="Salta pàgines de detall")
    parser.add_argument("--output", default="estrelladamm_events.json")
    parser.add_argument("--pages", type=int, default=MAX_PAGES)
    args = parser.parse_args()

    MAX_PAGES = args.pages

    log.info("🍺 Iniciant scraper Antiga Fàbrica Estrella Damm...")
    raw = scrape_damm(fetch_details=not args.no_details)
    normalized = normalize(raw)

    output = {
        "scraped_at": datetime.now().isoformat(),
        "source": "Antiga Fàbrica Estrella Damm",
        "total": len(normalized),
        "events": normalized,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info(f"\n✅ {len(normalized)} events guardats a '{args.output}'")

    if normalized:
        log.info("\n📋 Preview:")
        for e in normalized[:5]:
            free_str = "GRATUÏT" if e["free"] else e.get("price", "?")
            log.info(f"  [{e['date'] or '??-??-??'}] {e['title'][:50]} — {free_str}")
