"""
Palau de la Música Catalana Scraper
=====================================
Extreu concerts de www.palaumusica.cat/ca/

Estructura HTML:
  <article class="entry" data-palau-dates="2026-05-17-12-00" data-palau-stages="sala-petit-palau --1315--">
    <a class="Link production_link" href="...">
      <img class="production_image" src="...">
      <div class="entry_data">
        <span class="date_text">17 de maig de 2026</span>
        <h1 class="ProductionHeading">
          <div class="production_title"><p>Títol</p></div>
          <div class="production_subtitle"><p>Subtítol</p></div>
        </h1>
      </div>
    </a>
  </article>
"""

import json
import re
import time
import logging
from datetime import datetime, date
from typing import Optional
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.palaumusica.cat"
AGENDA_URL = f"{BASE_URL}/ca/"
REQUEST_DELAY = 1.5

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("palau_scraper")

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

STAGE_NAMES = {
    "sala-gran": "Palau de la Música Catalana",
    "gran-sala": "Palau de la Música Catalana",
    "palau": "Palau de la Música Catalana",
    "sala-petit-palau": "Petit Palau",
    "petit-palau": "Petit Palau",
}


def parse_date_attr(attr: str) -> tuple[Optional[str], Optional[str]]:
    """Parse 'data-palau-dates' attr: '2026-05-17-12-00' → ('2026-05-17', '12:00')"""
    if not attr:
        return None, None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})", attr)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", f"{m.group(4)}:{m.group(5)}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", attr)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", None
    return None, None


def parse_stage(attr: str) -> str:
    """'sala-petit-palau --1315--' → 'Petit Palau'"""
    if not attr:
        return "Palau de la Música Catalana"
    slug = attr.split(" ")[0].lower()
    for key, name in STAGE_NAMES.items():
        if key in slug:
            return name
    return "Palau de la Música Catalana"


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


def parse_card(card) -> Optional[dict]:
    date_str, time_str = parse_date_attr(card.get("data-palau-dates", ""))
    if not date_str:
        return None

    # Skip expired events
    try:
        if card.get("data-palau-expired", "0") == "1":
            return None
    except Exception:
        pass

    link = card.select_one("a.Link")
    href = link["href"] if link else ""

    title_el = card.select_one("div.production_title p")
    if not title_el:
        return None
    title = " ".join(title_el.get_text().split())

    subtitle_el = card.select_one("div.production_subtitle p")
    subtitle = " ".join(subtitle_el.get_text().split()) if subtitle_el else ""

    venue = parse_stage(card.get("data-palau-stages", ""))

    img = card.select_one("img.production_image")
    image_url = img["src"] if img else ""

    return {
        "title": title,
        "subtitle": subtitle,
        "date": date_str,
        "time": time_str or "",
        "venue": venue,
        "venue_address": "C/ Palau de la Música, 4-6, 08003 Barcelona",
        "url": href,
        "image": image_url,
        "type": "music",
        "free": False,
        "price": "",
        "tags": ["music"],
        "source": "Palau de la Música",
    }


def scrape_palau() -> list[dict]:
    log.info("🎶 Iniciant scraper del Palau de la Música...")
    session = requests.Session()
    soup = get(session, AGENDA_URL)
    if not soup:
        log.error("No s'ha pogut accedir al Palau")
        return []

    cards = soup.select("article.entry")
    log.info(f"  {len(cards)} concerts trobats")

    events = []
    today = date.today().isoformat()
    for card in cards:
        e = parse_card(card)
        if e and e["date"] >= today:
            events.append(e)

    log.info(f"  {len(events)} concerts futurs")
    return events


def normalize(events: list[dict]) -> list[dict]:
    TYPE_EMOJI = {"music": "🎵"}
    result = []
    for i, e in enumerate(events):
        tags = list(e.get("tags", ["music"]))
        desc = e.get("subtitle", "") or ""
        result.append({
            "id": i + 1,
            "date": e["date"],
            "date_end": e.get("date_end", ""),
            "time": e.get("time", ""),
            "title": e["title"],
            "venue": e["venue"],
            "venue_address": e.get("venue_address", ""),
            "type": e.get("type", "music"),
            "free": e.get("free", False),
            "price": e.get("price", ""),
            "emoji": "🎶",
            "bg": "#FFF0EB",
            "tags": tags,
            "desc": desc,
            "url": e.get("url", ""),
            "image": e.get("image", ""),
            "source": e.get("source", "Palau de la Música"),
        })
    return sorted(result, key=lambda x: (x["date"], x["time"]))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="palau_events.json")
    args = parser.parse_args()

    raw = scrape_palau()
    normalized = normalize(raw)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"total": len(normalized), "events": normalized}, f, ensure_ascii=False, indent=2)
    log.info(f"\n✅ {len(normalized)} concerts → '{args.output}'")
    for e in normalized[:3]:
        log.info(f"  [{e['date']} {e['time']}] {e['title'][:50]} @ {e['venue']}")
