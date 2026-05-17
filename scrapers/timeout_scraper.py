"""
Time Out Barcelona Scraper
============================
Extreu events de dues fonts de Time Out:

  1. timeout.com/barcelona/things-to-do   → Agenda editorial (tota la ciutat)
  2. timeout.com/time-out-market-barcelona/things-to-do  → Market events

Time Out és especialment valuós perquè ja actua d'agregador:
els seus editors seleccionen el millor de tota Barcelona, cosa que cobreix
venues que no tenim scrapers propis (Palau de la Música, Grec, Sónar, etc.)

Execució:
    pip install requests beautifulsoup4
    python timeout_scraper.py

    # Només Market (més ràpid, events molt freqüents i gratuïts)
    python timeout_scraper.py --source market

    # Agenda editorial completa
    python timeout_scraper.py --source editorial

Sortida:
    timeout_events.json
"""

import json
import re
import time
import logging
from datetime import datetime, date
from typing import Optional
import requests
from bs4 import BeautifulSoup

# ─── CONFIG ──────────────────────────────────────────────────────────────────

BASE_URL = "https://www.timeout.com"

SOURCES = {
    "editorial": {
        "url": f"{BASE_URL}/barcelona/things-to-do",
        "label": "Time Out Barcelona",
        "venue": "Diversos espais de Barcelona",
    },
    "market": {
        "url": f"{BASE_URL}/time-out-market-barcelona/things-to-do",
        "label": "Time Out Market Barcelona",
        "venue": "Time Out Market Barcelona",
        "venue_address": "Moll d'Espanya del Port Vell, s/n, 08039 Barcelona",
    },
    # Subcategories útils de l'agenda editorial
    "music": {
        "url": f"{BASE_URL}/barcelona/music",
        "label": "Time Out Barcelona — Música",
        "venue": "Diversos espais de Barcelona",
    },
    "art": {
        "url": f"{BASE_URL}/barcelona/art",
        "label": "Time Out Barcelona — Art",
        "venue": "Diversos espais de Barcelona",
    },
    "food": {
        "url": f"{BASE_URL}/barcelona/restaurants",
        "label": "Time Out Barcelona — Food",
        "venue": "Diversos espais de Barcelona",
    },
    "free": {
        "url": f"{BASE_URL}/barcelona/things-to-do/free-things-to-do-in-barcelona",
        "label": "Time Out Barcelona — Gratuïts",
        "venue": "Diversos espais de Barcelona",
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,ca;q=0.8,es;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Referer": BASE_URL,
}

REQUEST_DELAY = 1.5
MAX_PAGES = 8

# ─── LOGGING ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("timeout_scraper")

# ─── CATEGORY MAPPING ────────────────────────────────────────────────────────

KEYWORD_TO_TYPE = {
    "concert": "music", "concierto": "music", "música": "music",
    "music": "music", "festival": "music", "gig": "music",
    "live": "music", "dj": "music", "jazz": "music",
    "indie": "music", "rock": "music", "electro": "music",
    "food": "food", "gastro": "food", "market": "food",
    "mercat": "food", "mercado": "food", "restaurant": "food",
    "chef": "food", "cook": "food", "cuina": "food",
    "art": "art", "exhibition": "art", "exposic": "art",
    "gallery": "art", "design": "art", "disseny": "art",
    "photo": "art", "illustration": "art", "museum": "art",
    "kids": "family", "family": "family", "children": "family",
    "familia": "family", "nens": "family", "taller": "family",
    "theatre": "culture", "teatre": "culture", "dance": "culture",
    "dansa": "culture", "cinema": "culture", "film": "culture",
    "talk": "culture", "debate": "culture", "conference": "culture",
}

def classify(title: str, desc: str = "", section: str = "") -> str:
    text = (title + " " + desc + " " + section).lower()
    for kw, cat in KEYWORD_TO_TYPE.items():
        if kw in text:
            return cat
    return "culture"


# ─── DATE / TIME PARSING ─────────────────────────────────────────────────────

MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

def parse_date(text: str) -> Optional[str]:
    if not text:
        return None
    text = text.strip()

    # ISO
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # DD/MM/YYYY
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass

    lower = text.lower()

    # "May 10, 2025" or "10 May 2025"
    for pattern in [
        r"(\w+)\s+(\d{1,2}),?\s+(\d{4})",   # Month DD YYYY
        r"(\d{1,2})\s+(\w+)\s+(\d{4})",      # DD Month YYYY
    ]:
        m = re.search(pattern, lower)
        if m:
            g = m.groups()
            if g[0].isdigit():
                day, month_str, year = int(g[0]), g[1], int(g[2])
            else:
                month_str, day, year = g[0], int(g[1]), int(g[2])
            month_num = MONTHS_EN.get(month_str[:3])
            if month_num:
                try:
                    return date(year, month_num, day).isoformat()
                except ValueError:
                    pass

    # "until May 25" / "through June 10" (date range end)
    m = re.search(r"(?:until|through|–|-)\s+(\w+)\s+(\d{1,2})", lower)
    if m:
        month_num = MONTHS_EN.get(m.group(1)[:3])
        if month_num:
            try:
                today = date.today()
                return date(today.year, month_num, int(m.group(2))).isoformat()
            except ValueError:
                pass

    return None


def parse_time(text: str) -> Optional[str]:
    if not text:
        return None
    # "7:30pm", "7pm", "19:30", "7.30pm"
    m = re.search(r"(\d{1,2})[:\.]?(\d{2})?\s*(am|pm)", text.lower())
    if m:
        h = int(m.group(1))
        mins = m.group(2) or "00"
        ampm = m.group(3)
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:{mins}"
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def is_free(text: str) -> bool:
    return any(w in text.lower() for w in ["free", "gratuï", "gratuito", "gratis", "no cost"])


def clean(text: str) -> str:
    return " ".join(text.split()).strip() if text else ""


# ─── HTTP ─────────────────────────────────────────────────────────────────────

def get(session: requests.Session, url: str) -> Optional[BeautifulSoup]:
    for attempt in range(3):
        try:
            time.sleep(REQUEST_DELAY)
            r = session.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            log.warning(f"HTTP {r.status_code}: {url}")
        except requests.RequestException as e:
            log.warning(f"Intent {attempt+1}/3 per {url}: {e}")
            time.sleep(REQUEST_DELAY * 2)
    return None


# ─── CARD PARSER ─────────────────────────────────────────────────────────────

def parse_card(card: BeautifulSoup, source_meta: dict) -> Optional[dict]:
    """
    Time Out utilitza diversos layouts depenent de la secció.

    Layout editorial típic:
      <article data-testid="tile">
        <a href="/barcelona/things-to-do/event-slug">
          <img ... />
          <div class="tile-header">
            <h3>Títol de l'event</h3>
            <p class="tile-description">Descripció...</p>
          </div>
          <div class="tile-meta">
            <span class="tile-date">May 10–June 5</span>
            <span class="tile-price">Free</span>
          </div>
        </a>
      </article>

    Layout Market (més senzill):
      <div class="event-card">
        <h2>Títol</h2>
        <time>Dissabte 10 de maig</time>
        <p>...</p>
      </div>
    """
    event = {
        "source": source_meta["label"],
        "venue": source_meta["venue"],
        "venue_address": source_meta.get("venue_address", "Barcelona"),
        "scraped_at": datetime.now().isoformat(),
    }

    # ── Títol ──────────────────────────────────────────────────────────────
    title_el = (
        card.select_one("h3 a") or card.select_one("h2 a") or
        card.select_one("[data-testid='tile-title'] a") or
        card.select_one(".tile-title a") or card.select_one(".card-title a") or
        card.select_one("h3") or card.select_one("h2") or
        card.select_one("a[class*='title']")
    )
    if not title_el:
        return None

    event["title"] = clean(title_el.get_text())

    # URL de detall
    link_el = title_el if title_el.name == "a" else card.select_one("a[href]")
    if link_el:
        href = link_el.get("href", "")
        event["url"] = BASE_URL + href if href.startswith("/") else href

    if not event.get("title"):
        return None

    # ── Descripció ─────────────────────────────────────────────────────────
    desc_el = (
        card.select_one("[data-testid='tile-description']") or
        card.select_one(".tile-description") or
        card.select_one(".card-description") or
        card.select_one("p.description") or
        card.select_one("p")
    )
    event["description"] = clean(desc_el.get_text()) if desc_el else ""

    # ── Data ───────────────────────────────────────────────────────────────
    date_el = (
        card.select_one("time") or
        card.select_one("[data-testid='tile-date']") or
        card.select_one(".tile-date") or card.select_one(".date") or
        card.select_one("[class*='date']") or card.select_one("[class*='Date']")
    )
    if date_el:
        raw = date_el.get("datetime") or date_el.get_text()
        parsed = parse_date(raw)
        if parsed:
            event["date_start"] = parsed
        else:
            event["date_raw"] = clean(raw)
            # Intenta extreure almenys alguna data del text
            parsed_attempt = parse_date(clean(raw))
            if parsed_attempt:
                event["date_start"] = parsed_attempt

    # ── Hora ───────────────────────────────────────────────────────────────
    time_el = card.select_one(".time, [class*='time'], [class*='Time'], .schedule")
    if time_el:
        t = parse_time(time_el.get_text())
        if t:
            event["time"] = t
    # Busca hora al text de data
    if not event.get("time") and date_el:
        t = parse_time(date_el.get_text())
        if t:
            event["time"] = t

    # ── Categoria / section ────────────────────────────────────────────────
    section_el = (
        card.select_one("[data-testid='tile-category']") or
        card.select_one(".tile-category") or card.select_one(".category") or
        card.select_one(".section") or card.select_one("[class*='category']")
    )
    section = clean(section_el.get_text()) if section_el else ""
    event["section_raw"] = section
    event["type"] = classify(event["title"], event["description"], section)

    # ── Preu ───────────────────────────────────────────────────────────────
    price_el = (
        card.select_one("[data-testid='tile-price']") or
        card.select_one(".tile-price") or card.select_one(".price") or
        card.select_one("[class*='price']") or card.select_one("[class*='Price']")
    )
    if price_el:
        raw_price = clean(price_el.get_text())
        event["price_raw"] = raw_price
        event["free"] = is_free(raw_price)
    else:
        full = event["title"] + " " + event["description"]
        event["free"] = is_free(full)
        event["price_raw"] = "Free" if event["free"] else ""

    # ── Imatge ─────────────────────────────────────────────────────────────
    img = card.select_one("img")
    if img:
        src = (img.get("src") or img.get("data-src") or
               img.get("data-lazy-src") or img.get("srcset", "").split(" ")[0])
        if src and not src.startswith("data:"):
            event["image_url"] = src

    return event


# ─── DETAIL PAGE ─────────────────────────────────────────────────────────────

def enrich(session: requests.Session, event: dict) -> dict:
    """Visita pàgina de detall per obtenir data exacta, hora i descripció completa."""
    url = event.get("url")
    if not url or "timeout.com" not in url:
        return event

    log.info(f"  ↳ {event.get('title','')[:55]}")
    soup = get(session, url)
    if not soup:
        return event

    # JSON-LD (Time Out sí que l'inclou per a events)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            items = data if isinstance(data, list) else [data]
            for item in items:
                t = item.get("@type", "")
                if t in ("Event", "MusicEvent", "TheaterEvent", "ExhibitionEvent",
                         "FoodEvent", "SocialEvent", "ScreeningEvent"):
                    if item.get("startDate"):
                        dt = item["startDate"]
                        event["date_start"] = dt[:10]
                        if "T" in dt:
                            event["time"] = dt[11:16]
                    if item.get("endDate"):
                        event["date_end"] = item["endDate"][:10]
                    if item.get("description"):
                        event["description_full"] = clean(item["description"])
                    if item.get("location"):
                        loc = item["location"]
                        if isinstance(loc, dict):
                            event["venue"] = loc.get("name", event["venue"])
                            addr = loc.get("address", {})
                            if isinstance(addr, dict):
                                street = addr.get("streetAddress", "")
                                city = addr.get("addressLocality", "")
                                event["venue_address"] = f"{street}, {city}".strip(", ")
                    offers = item.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price = str(offers.get("price", ""))
                    currency = offers.get("priceCurrency", "€")
                    if price in ("0", "0.0", ""):
                        pass  # no canviem si no hi ha info
                    elif price:
                        event["price_raw"] = f"{price} {currency}"
                        event["free"] = False
                    break
        except (json.JSONDecodeError, AttributeError):
            continue

    # Descripció llarga (si no ve del JSON-LD)
    if not event.get("description_full"):
        body = (
            soup.select_one("[data-testid='article-body']") or
            soup.select_one(".article-body") or
            soup.select_one(".content-body") or
            soup.select_one("article .body") or
            soup.select_one("main article p")
        )
        if body:
            # Agafa els primers 3 paràgrafs
            paras = [clean(p.get_text()) for p in body.select("p")[:3]]
            event["description_full"] = " ".join(p for p in paras if p)

    # Venue (pot estar a la pàgina de detall)
    if event["venue"] == "Diversos espais de Barcelona":
        venue_el = (
            soup.select_one("[data-testid='venue-name']") or
            soup.select_one(".venue-name") or
            soup.select_one("[class*='venue']")
        )
        if venue_el:
            event["venue"] = clean(venue_el.get_text())

    return event


# ─── LISTING PAGE ────────────────────────────────────────────────────────────

def scrape_page(
    session: requests.Session,
    url: str,
    source_meta: dict
) -> tuple[list[dict], Optional[str]]:

    log.info(f"Fetching: {url}")
    soup = get(session, url)
    if not soup:
        return [], None

    # Time Out utilitza data-testid="tile" per a les targetes editorials
    SELECTORS = [
        "[data-testid='tile']",
        "[data-testid='card']",
        "article.tile",
        "article.card",
        ".event-card",
        ".tile",
        ".card",
        "article",
    ]

    cards = []
    for sel in SELECTORS:
        candidates = soup.select(sel)
        if candidates:
            # Filtra elements que tinguin un títol
            valid = [c for c in candidates if c.select_one("h2, h3, h4, [class*='title']")]
            if valid:
                log.info(f"  '{sel}' → {len(valid)} targetes")
                cards = valid
                break

    if not cards:
        log.warning("  Sense targetes — Time Out pot requerir JS. Guardant debug_timeout.html")
        with open("debug_timeout.html", "w", encoding="utf-8") as f:
            f.write(str(soup))
        return [], None

    events = []
    for card in cards:
        e = parse_card(card, source_meta)
        if e and e.get("title"):
            events.append(e)

    # Paginació
    next_url = None
    next_el = (
        soup.select_one("a[aria-label='Next page']") or
        soup.select_one("a[rel='next']") or
        soup.select_one(".pagination-next a") or
        soup.select_one("[data-testid='pagination-next']")
    )
    if next_el and next_el.get("href"):
        href = next_el["href"]
        next_url = BASE_URL + href if href.startswith("/") else href

    return events, next_url


# ─── MAIN SCRAPER ────────────────────────────────────────────────────────────

def scrape_timeout(
    sources: list[str] = None,
    fetch_details: bool = True,
) -> list[dict]:

    if sources is None:
        sources = ["editorial", "market", "free"]  # per defecte les més útils

    session = requests.Session()
    session.headers.update(HEADERS)

    all_events = []
    seen = set()

    for source_key in sources:
        if source_key not in SOURCES:
            log.warning(f"Font desconeguda: {source_key}")
            continue

        meta = SOURCES[source_key]
        log.info(f"\n▶ {meta['label']}")

        current_url = meta["url"]
        pages = 0

        while current_url and pages < MAX_PAGES:
            events, next_url = scrape_page(session, current_url, meta)
            pages += 1

            new_events = []
            for e in events:
                key = (e.get("title", "").lower()[:40] + "|" + e.get("date_start", "") +
                       "|" + e.get("url", "")[-30:])
                if key not in seen:
                    seen.add(key)
                    new_events.append(e)

            if fetch_details:
                enriched = [enrich(session, e) for e in new_events]
                all_events.extend(enriched)
            else:
                all_events.extend(new_events)

            log.info(f"  Pàg {pages}: +{len(new_events)} (total: {len(all_events)})")
            current_url = next_url

    return all_events


# ─── NORMALITZAR ─────────────────────────────────────────────────────────────

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
        et = e.get("type", "culture")
        tags = [et] + (["free"] if e.get("free") else [])
        result.append({
            "id": i + 1,
            "date": e.get("date_start", ""),
            "date_end": e.get("date_end", ""),
            "time": e.get("time", ""),
            "title": e.get("title", ""),
            "venue": e.get("venue", "Barcelona"),
            "venue_address": e.get("venue_address", ""),
            "type": et,
            "free": e.get("free", False),
            "price": e.get("price_raw", ""),
            "emoji": TYPE_EMOJI.get(et, "🗓"),
            "bg": TYPE_BG.get(et, "#F5F0E8"),
            "tags": tags,
            "desc": e.get("description_full") or e.get("description", ""),
            "url": e.get("url", ""),
            "image": e.get("image_url", ""),
            "source": e.get("source", "Time Out Barcelona"),
        })
    return sorted(result, key=lambda x: x.get("date") or "9999")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    valid_sources = list(SOURCES.keys())
    parser = argparse.ArgumentParser(description="Time Out Barcelona Scraper")
    parser.add_argument(
        "--source", nargs="+", choices=valid_sources,
        default=["editorial", "market", "free"],
        help=f"Fonts a scrapejar. Opcions: {', '.join(valid_sources)}"
    )
    parser.add_argument("--no-details", action="store_true")
    parser.add_argument("--output", default="timeout_events.json")
    parser.add_argument("--pages", type=int, default=MAX_PAGES)
    args = parser.parse_args()

    MAX_PAGES = args.pages

    log.info("⏱  Iniciant scraper Time Out Barcelona...")
    log.info(f"   Fonts: {', '.join(args.source)}")

    raw = scrape_timeout(sources=args.source, fetch_details=not args.no_details)
    normalized = normalize(raw)

    output = {
        "scraped_at": datetime.now().isoformat(),
        "sources": args.source,
        "total": len(normalized),
        "events": normalized,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info(f"\n✅ {len(normalized)} events → '{args.output}'")
    if normalized:
        log.info("\nPreview:")
        for e in normalized[:5]:
            log.info(f"  [{e['date'] or '??'}] {e['title'][:50]} @ {e['venue'][:30]}")
