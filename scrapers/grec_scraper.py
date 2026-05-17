"""
Festival Grec de Barcelona Scraper
=====================================
Extreu espectacles de www.barcelona.cat/grec/ca/

Estratègia:
  1. Llegir sitemap.xml → URLs de /ca/espectacle/{slug}
  2. Per cada URL, fer scraping del detall:
     - Títol: h1 dins .wrapper-title-subheader-activity
     - Data: .date-subheader-activity ("Del 29 de juny a l'1 de juliol")
     - Preu: [class*=price]
     - Descripció: .description-subheader-activity
"""

import json
import re
import time
import logging
from datetime import datetime, date
from typing import Optional
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.barcelona.cat"
SITEMAP_URL = f"{BASE_URL}/grec/sitemap.xml"
REQUEST_DELAY = 1.0
MAX_EVENTS = 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("grec_scraper")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ca-ES,ca;q=0.9,es;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}

MONTHS_CA = {
    "gener": 1, "febrer": 2, "març": 3, "abril": 4, "maig": 5, "juny": 6,
    "juliol": 7, "agost": 8, "setembre": 9, "octubre": 10, "novembre": 11, "desembre": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

KNOWN_VENUES = [
    "Teatre Grec", "Teatre Lliure", "Mercat de les Flors", "CCCB",
    "Palau de la Música", "TNC", "Sala Beckett", "Fabra i Coats",
    "Teatre Nacional de Catalunya", "Parc de Montjuïc",
]

CATEGORY_MAP = {
    "teatre": "culture", "dansa": "culture", "música": "music", "circ": "culture",
    "concert": "music", "òpera": "music", "familiar": "family", "titelles": "family",
    "performance": "culture", "cabaret": "culture",
}


def parse_date_ca(text: str) -> Optional[str]:
    """Parse 'Del 29 de juny a l'1 de juliol' → start date ISO"""
    if not text:
        return None
    text = text.lower().strip()
    year = date.today().year

    # "Del X de mes a/al Y de mes" — agafem la primera data
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)", text)
    if m:
        day, month_str = int(m.group(1)), m.group(2)
        month_num = MONTHS_CA.get(month_str)
        if month_num:
            try:
                return date(year, month_num, day).isoformat()
            except ValueError:
                pass

    # Format "X mes" sense "de"
    m = re.search(r"(\d{1,2})\s+(\w+)", text)
    if m:
        day, month_str = int(m.group(1)), m.group(2)
        month_num = MONTHS_CA.get(month_str)
        if month_num:
            try:
                return date(year, month_num, day).isoformat()
            except ValueError:
                pass
    return None


def parse_date_end_ca(text: str) -> Optional[str]:
    """Parse 'Del 29 de juny a l'1 de juliol' → end date ISO"""
    if not text:
        return None
    text = text.lower().strip()
    year = date.today().year

    # Busca l'última data del rang
    matches = list(re.finditer(r"(\d{1,2})\s+de\s+(\w+)", text))
    if len(matches) >= 2:
        m = matches[-1]
        day, month_str = int(m.group(1)), m.group(2)
        month_num = MONTHS_CA.get(month_str)
        if month_num:
            try:
                return date(year, month_num, day).isoformat()
            except ValueError:
                pass
    return None


def get(session: requests.Session, url: str) -> Optional[BeautifulSoup]:
    for attempt in range(3):
        try:
            time.sleep(REQUEST_DELAY)
            r = session.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            log.warning(f"HTTP {r.status_code}: {url}")
        except requests.RequestException as e:
            log.warning(f"Intent {attempt+1}/3: {e}")
    return None


def get_event_urls() -> list[str]:
    """Llegeix el sitemap i retorna les URLs de /ca/espectacle/ úniques."""
    try:
        r = requests.get(SITEMAP_URL, headers=HEADERS, timeout=20)
        urls = re.findall(r"<loc>(https://www\.barcelona\.cat/grec/(?:index\.php/)?ca/espectacle/[^<]+)</loc>", r.text)
        # Deduplicar mantenint ordre
        seen = set()
        unique = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        log.info(f"  Sitemap: {len(unique)} espectacles trobats")
        return unique
    except Exception as e:
        log.error(f"Error llegint sitemap: {e}")
        return []


def scrape_show(session: requests.Session, url: str) -> Optional[dict]:
    soup = get(session, url)
    if not soup:
        return None

    # Títol
    title_el = soup.select_one(".wrapper-title-subheader-activity h1")
    if not title_el:
        title_el = soup.select_one("h1")
    if not title_el:
        return None
    title = " ".join(title_el.get_text().split())
    if not title:
        return None

    # Data
    date_el = soup.select_one(".date-subheader-activity")
    date_raw = " ".join(date_el.get_text().split()) if date_el else ""
    date_start = parse_date_ca(date_raw)
    date_end = parse_date_end_ca(date_raw)

    if not date_start:
        return None  # sense data, skip

    # Venue: buscar al text complet
    full_text = soup.get_text()
    venue = "Festival Grec Barcelona"
    for v in KNOWN_VENUES:
        if v in full_text:
            venue = v
            break

    # Categoria
    tag_els = soup.select("[class*=tag]")
    tags_text = " ".join(el.get_text(strip=True).lower() for el in tag_els)
    event_type = "culture"
    for kw, cat in CATEGORY_MAP.items():
        if kw in tags_text or kw in title.lower():
            event_type = cat
            break

    # Preu
    price_el = soup.select_one("[class*=price]")
    price_raw = " ".join(price_el.get_text().split()) if price_el else ""
    price_clean = re.sub(r"^Preus?\s*", "", price_raw).strip()
    is_free = any(w in price_raw.lower() for w in ["gratuï", "gratis", "lliure", "0 €"])

    # Descripció
    desc_el = soup.select_one(".description-subheader-activity")
    desc = " ".join(desc_el.get_text().split())[:300] if desc_el else ""

    # Imatge
    img = soup.select_one("img.lazyload, img[data-src], img")
    image_url = ""
    if img:
        image_url = img.get("data-src") or img.get("src") or ""
        if image_url.startswith("/"):
            image_url = BASE_URL + image_url

    return {
        "title": title,
        "date": date_start,
        "date_end": date_end or "",
        "time": "",
        "venue": venue,
        "venue_address": "Parc de Montjuïc, Barcelona",
        "type": event_type,
        "free": is_free,
        "price": price_clean,
        "desc": desc,
        "url": url,
        "image": image_url,
        "source": "Festival Grec",
        "tags": [event_type] + (["free"] if is_free else []),
    }


def scrape_grec() -> list[dict]:
    log.info("🎭 Iniciant scraper del Festival Grec...")
    session = requests.Session()

    urls = get_event_urls()
    if not urls:
        return []

    today = date.today().isoformat()
    events = []
    for i, url in enumerate(urls[:MAX_EVENTS]):
        log.info(f"  [{i+1}/{min(len(urls), MAX_EVENTS)}] {url.split('/')[-1][:50]}")
        e = scrape_show(session, url)
        if e and e["date"] >= today:
            events.append(e)

    log.info(f"  {len(events)} espectacles futurs")
    return events


def normalize(events: list[dict]) -> list[dict]:
    TYPE_EMOJI = {"music": "🎵", "art": "🎨", "culture": "🎭", "family": "👨‍👩‍👧"}
    TYPE_BG = {"music": "#FFF0EB", "art": "#EBF0FF", "culture": "#F0EBFF", "family": "#FFF5EB"}
    result = []
    for i, e in enumerate(events):
        et = e.get("type", "culture")
        result.append({
            "id": i + 1,
            "date": e["date"],
            "date_end": e.get("date_end", ""),
            "time": e.get("time", ""),
            "title": e["title"],
            "venue": e["venue"],
            "venue_address": e.get("venue_address", ""),
            "type": et,
            "free": e.get("free", False),
            "price": e.get("price", ""),
            "emoji": TYPE_EMOJI.get(et, "🎭"),
            "bg": TYPE_BG.get(et, "#F0EBFF"),
            "tags": e.get("tags", [et]),
            "desc": e.get("desc", ""),
            "url": e.get("url", ""),
            "image": e.get("image", ""),
            "source": e.get("source", "Festival Grec"),
        })
    return sorted(result, key=lambda x: (x["date"], x["time"]))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="grec_events.json")
    parser.add_argument("--max", type=int, default=MAX_EVENTS)
    args = parser.parse_args()
    MAX_EVENTS = args.max

    raw = scrape_grec()
    normalized = normalize(raw)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"total": len(normalized), "events": normalized}, f, ensure_ascii=False, indent=2)
    log.info(f"\n✅ {len(normalized)} espectacles → '{args.output}'")
    for e in normalized[:3]:
        log.info(f"  [{e['date']}] {e['title'][:50]} @ {e['venue']}")
