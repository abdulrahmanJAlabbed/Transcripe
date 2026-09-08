#!/usr/bin/env bash
# Deploy the studio to alabed.site — the site at /transcripe/ and the engine
# behind /api/. Safe to re-run; every deploy backs up what it replaces.
#
#   ./deploy.sh            # site + engine
#   ./deploy.sh site       # just the built UI
#   ./deploy.sh engine     # just the API
#
# Needs gcloud auth (the `essore` alias uses the same VM).
set -euo pipefail

ZONE=${TRANSCRIPE_DEPLOY_ZONE:-us-central1-a}
VM=${TRANSCRIPE_DEPLOY_VM:-portfolio-vm}
PROJECT=${TRANSCRIPE_DEPLOY_PROJECT:-cella-b04d1}
SITE_DIR=${TRANSCRIPE_SITE_DIR:-/var/www/portfolio/transcripe}
API_DIR=${TRANSCRIPE_API_DIR:-/opt/transcripe-api}

WHAT=${1:-all}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$HERE"

run() { gcloud compute ssh --zone "$ZONE" "$VM" --project "$PROJECT" --command "$1"; }
put() { gcloud compute scp --zone "$ZONE" --project "$PROJECT" "$1" "$VM:$2"; }

deploy_site() {
  echo "→ building the hosted bundle"
  # VITE_HOSTED=1 swaps in copy that admits conversions happen on the server.
  ( cd web && VITE_HOSTED=1 npm run build -- --outDir dist-hosted >/dev/null )
  tar czf /tmp/transcripe-site.tar.gz -C web/dist-hosted .
  put /tmp/transcripe-site.tar.gz /tmp/transcripe-site.tar.gz
  run "set -e
    sudo mkdir -p /var/backups
    sudo tar czf /var/backups/transcripe-site-\$(date +%Y%m%d-%H%M%S).tar.gz -C '$SITE_DIR' .
    TMP=\$(mktemp -d); tar xzf /tmp/transcripe-site.tar.gz -C \"\$TMP\"
    sudo rsync -a --delete \"\$TMP\"/ '$SITE_DIR'/
    sudo chown -R www-data:www-data '$SITE_DIR'
    rm -rf \"\$TMP\" /tmp/transcripe-site.tar.gz"
  rm -f /tmp/transcripe-site.tar.gz
  echo "✓ site deployed"
}

deploy_engine() {
  echo "→ building the wheel"
  rm -f dist/*.whl
  # The project venv is where `build` lives; system python usually lacks it.
  PY=python3
  for candidate in .venv/bin/python venv/bin/python; do
    [ -x "$candidate" ] && PY="$candidate" && break
  done
  "$PY" -m build --wheel >/dev/null
  WHEEL=$(ls dist/*.whl | head -1)
  put "$WHEEL" "/tmp/$(basename "$WHEEL")"
  run "set -e
    sudo cp '$API_DIR/server.py' /var/backups/transcripe-server-\$(date +%Y%m%d-%H%M%S).py 2>/dev/null || true
    # --force-reinstall: the version rarely changes between deploys, and pip
    # would otherwise decide it already has this one.
    '$API_DIR/venv/bin/pip' install -q --force-reinstall --no-deps '/tmp/$(basename "$WHEEL")'
    # cairosvg reads SVG, which Pillow cannot; without it every .svg input
    # fails on the server while working fine locally. faster-whisper is the
    # transcription model runner — the VM pins TRANSCRIPE_MODEL=base in its
    # systemd unit, since the package default of large-v3 wants 4 GB it
    # hasn't got.
    '$API_DIR/venv/bin/pip' install -q 'fastapi>=0.115' uvicorn python-multipart yt-dlp Pillow pillow-heif cairosvg faster-whisper
    rm -f '/tmp/$(basename "$WHEEL")'
    sudo systemctl restart transcripe-api
    sleep 4
    systemctl is-active transcripe-api"
  echo "✓ engine deployed"
}

case "$WHAT" in
  site)   deploy_site ;;
  engine) deploy_engine ;;
  all)    deploy_site; deploy_engine ;;
  *)      echo "usage: $0 [all|site|engine]" >&2; exit 2 ;;
esac

echo "→ verifying"
curl -fsS -o /dev/null -w "  /transcripe/ -> %{http_code}\n" https://alabed.site/transcripe/
printf "  /api/health  -> "; curl -fsS https://alabed.site/api/health; echo
