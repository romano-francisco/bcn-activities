#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# BCN Activities — arranque local
#
# Uso:
#   ./scripts/run_local.sh            # scraping completo + servidor web
#   ./scripts/run_local.sh --no-scrape   # solo servidor (datos ya existen)
#   ./scripts/run_local.sh --fast        # scraping rápido (sin detalle de evento)
# ─────────────────────────────────────────────────────────────────────────────

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$ROOT/data"
FRONTEND_DIR="$ROOT/frontend"
SCRAPERS_DIR="$ROOT/scrapers"
PORT=3000

NO_SCRAPE=false
FAST=false

for arg in "$@"; do
  case $arg in
    --no-scrape) NO_SCRAPE=true ;;
    --fast)      FAST=true ;;
  esac
done

echo ""
echo "🏙  BCN Activities — arranque local"
echo "    Carpeta: $ROOT"
echo ""

# ── 1. Entorno virtual ───────────────────────────────────────────────────────
if [ ! -d "$ROOT/venv" ]; then
  echo "📦 Creando entorno virtual..."
  python3 -m venv "$ROOT/venv"
fi

source "$ROOT/venv/bin/activate"
pip install -q -r "$ROOT/requirements.txt"

# ── 2. Scraping ──────────────────────────────────────────────────────────────
if [ "$NO_SCRAPE" = false ]; then
  echo "🕷  Ejecutando scrapers..."

  SCRAPE_ARGS=""
  if [ "$FAST" = true ]; then
    SCRAPE_ARGS="--no-details"
    echo "   Modo rápido (sin páginas de detalle)"
  fi

  cd "$SCRAPERS_DIR"
  python run_all.py $SCRAPE_ARGS --output "$DATA_DIR/bcn_agenda.json"
  cd "$ROOT"

  echo "   ✅ Datos guardados en data/bcn_agenda.json"
else
  echo "⏭  Saltando scraping (--no-scrape)"
  if [ ! -f "$DATA_DIR/bcn_agenda.json" ]; then
    echo "   ⚠️  No existe data/bcn_agenda.json — ejecuta sin --no-scrape primero"
    exit 1
  fi
fi

# ── 3. Servidor web local ─────────────────────────────────────────────────────
echo ""
echo "🌐 Iniciando servidor en http://localhost:$PORT"
echo "   Pulsa Ctrl+C para parar"
echo ""

# Servimos desde la raíz para que el frontend pueda leer ../data/bcn_agenda.json
cd "$ROOT"
python3 -m http.server $PORT --directory .
