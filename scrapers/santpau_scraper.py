"""
Recinte Modernista de Sant Pau Scraper
========================================
Extreu activitats culturals de santpaubarcelona.org

Estratègia:
  1. Scraping de la homepage (mostra els propers 3-5 events amb data)
  2. Per cada event, fetch de la pàgina de detall per obtenir descripció

Estructura HTML (homepage):
  <li>
    <a href="https://santpaubarcelona.org/activitat/slug/">
      <div class="not-hme-img"><img .../></div>
      <div class="not-hme-cnt">
        <h3>26 de maig de 2026</h3>
        <h2>Títol de l'event</h2>
      </div>
    </a>
  </li>
"""

import json
import re
import time
import logging
from datetime import datetime, date
from typing import Optional
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://santpaubarcelona.org"
HOME_URL = f"{BASE_URL}/"
REQUEST_DELAY = 1.5

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("santpau_scraper")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ca-ES,ca;q=0.9,es;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}

MONTHS_CA = {
    "gener": 1, "febrer": 2, "març": 3, "abril": 4, "maig": 5, "juny": 6,
    "juliol": 7, "agost": 8, "setembre": 9, "octubre": 10, "novembre": 11, "desembre": 12,
}

CATEGORY_KEYWORDS = {
    "concert": "music", "música": "music", "jazz": "music", "orquestra": "music", "life victoria": "music",
    "exposic": "art", "art ": "art", "fotograf": "art",
    "taula rodona": "culture", "conferència": "culture", "jornada": "culture",
    "nit dels museus": "culture", "visita": "culture",
    "taller": "family", "família": "family", "infantil": "family",
}


def parse_date_ca(text: str) -> Optional[str]:
    """'26 de maig de 2026' → '2026-05-26'"""
    if not text:
        return None
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)(?:\s+de)?\s+(\d{4})", text.lower().strip())
    if m:
        day, month_str, year = int(m.group(1)), m.group(2), int(m.group(3))
        month_num = MONTHS_CA.get(month_str)
        if month_num:
            try:
                return date(year, month_num, day).isoformat()
            except ValueError:
                pass
    return None


def classify(title: str, desc: str = "") -> str:
    text = (title + " " + desc).lower()
    for kw, cat in CATEGORY_KEYWORDS.items():
        if kw in text:
            return cat
    return "culture"


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


def scrape_homepage(session: requests.Session) -> list[dict]:
    """Extreu els events listats a la homepage."""
    soup = get(session, HOME_URL)
    if not soup:
        return []

    events = []
    seen_urls = set()

    # Targetes: <li> amb link a /activitat/ que contingui h3 (data) i h2 (títol)
    for item in soup.select("li"):
        link_el = item.select_one("a[href*='/activitat/']")
        if not link_el:
            continue
        url = link_el["href"]
        if url in seen_urls:
            continue

        h3 = item.select_one("h3")
        h2 = item.select_one("h2")
        if not h2 or not h3:
            continue

        date_str = parse_date_ca(h3.get_text(strip=True))
        if not date_str:
            continue

        title = " ".join(h2.get_text().split())
        img_el = item.select_one("img")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src") or ""

        seen_urls.add(url)
        events.append({
            "title": title,
            "date": date_str,
            "time": "",
            "url": url,
            "image": image_url,
            "type": classify(title),
            "desc": "",
            "free": False,
            "price": "",
            "source": "Recinte Modernista Sant Pau",
        })

    return events


def enrich(session: requests.Session, event: dict) -> dict:
    """Visita la pàgina de detall per obtenir descripció i preu."""
    soup = get(session, event["url"])
    if not soup:
        return event

    # Descripció: primer paràgraf del contingut
    for sel in [".entry-content p", ".post-content p", "article p", "main p"]:
        paras = soup.select(sel)
        if paras:
            desc = " ".join(paras[0].get_text().split())[:300]
            if len(desc) > 20:
                event["desc"] = desc
                break

    # Preu i gratuïtat
    full_text = soup.get_text().lower()
    event["free"] = any(w in full_text for w in ["gratuït", "gratuito", "gratis", "entrada lliure", "accés lliure"])
    if event["free"]:
        event["price"] = "Gratuït"

    return event


def scrape_santpau(fetch_details: bool = True) -> list[dict]:
    log.info("🏛  Iniciant scraper del Recinte Modernista Sant Pau...")
    session = requests.Session()

    events = scrape_homepage(session)
    log.info(f"  {len(events)} events trobats a la homepage")

    today = date.today().isoformat()
    future = [e for e in events if e["date"] >= today]

    if fetch_details:
        for e in future:
            log.info(f"  ↳ {e['title'][:50]}")
            enrich(session, e)

    log.info(f"  {len(future)} events futurs")
    return future


def normalize(events: list[dict]) -> list[dict]:
    TYPE_EMOJI = {"music": "🎵", "art": "🎨", "culture": "🏛", "family": "👨‍👩‍👧"}
    TYPE_BG = {"music": "#FFF0EB", "art": "#EBF0FF", "culture": "#F0EBFF", "family": "#FFF5EB"}
    result = []
    for i, e in enumerate(events):
        et = e.get("type", "culture")
        tags = [et] + (["free"] if e.get("free") else [])
        result.append({
            "id": i + 1,
            "date": e.get("date", ""),
            "date_end": "",
            "time": e.get("time", ""),
            "title": e["title"],
            "venue": "Recinte Modernista Sant Pau",
            "venue_address": "C/ Sant Antoni Maria Claret, 167, 08025 Barcelona",
            "type": et,
            "free": e.get("free", False),
            "price": e.get("price", ""),
            "emoji": TYPE_EMOJI.get(et, "🏛"),
            "bg": TYPE_BG.get(et, "#F0EBFF"),
            "tags": tags,
            "desc": e.get("desc", ""),
            "url": e.get("url", ""),
            "image": e.get("image", ""),
            "source": "Recinte Modernista Sant Pau",
        })
    return sorted(result, key=lambda x: (x["date"], x["time"]))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="santpau_events.json")
    parser.add_argument("--no-details", action="store_true")
    args = parser.parse_args()

    raw = scrape_santpau(fetch_details=not args.no_details)
    normalized = normalize(raw)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"total": len(normalized), "events": normalized}, f, ensure_ascii=False, indent=2)
    log.info(f"\n✅ {len(normalized)} events → '{args.output}'")
    for e in normalized:
        log.info(f"  [{e['date']} {e['time']}] {e['title'][:55]}")
