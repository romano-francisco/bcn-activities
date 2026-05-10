# BCN Activities 🏙

Agregador de events culturals de Barcelona. Scraping automatitzat de:
- CCCB
- Antiga Fàbrica Estrella Damm
- Time Out Barcelona
- Mercadillos de Glòries, Avinguda Gaudí i altres

## Estructura

```
bcn-activities/
├── scrapers/
│   ├── cccb_scraper.py
│   ├── estrelladamm_scraper.py
│   ├── timeout_scraper.py
│   └── run_all.py          ← punt d'entrada principal
├── frontend/
│   └── index.html          ← el calendari
├── data/
│   └── bcn_agenda.json     ← generat pels scrapers (no versionat)
├── scripts/
│   └── run_local.sh        ← arrenca tot localment
└── .github/workflows/
    └── scraping.yml        ← cron nocturn automàtic
```

## Arrancada ràpida

```bash
# Clonar
git clone https://github.com/romano-francisco/bcn-activities.git
cd bcn-activities

# Instal·lar dependències
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Scraping + servidor local
./scripts/run_local.sh

# Obre http://localhost:3000/frontend/
```

## Scraping manual

```bash
cd scrapers

# Tot (lent, amb pàgines de detall)
python run_all.py --output ../data/bcn_agenda.json

# Ràpid
python run_all.py --no-details --output ../data/bcn_agenda.json

# Só una font
python run_all.py --sources cccb --output ../data/bcn_agenda.json
```

## Afegir nous venues

1. Crea `scrapers/nou_venue_scraper.py` seguint el patró dels existents
2. Afegeix-lo a `run_all.py` al bloc de sources
3. Actualitza `AVAILABLE_SOURCES` i el runner

## Automatització (GitHub Actions)

El workflow `.github/workflows/scraping.yml` executa els scrapers cada nit a les 3h i fa commit del JSON actualitzat.

Per activar-lo: `Settings → Actions → Allow all actions` al repo de GitHub.
