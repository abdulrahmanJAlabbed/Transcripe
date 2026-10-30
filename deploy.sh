#!/usr/bin/env bash
# Deploy the studio to alabed.site — the site at /transcripe/ and the engine
# behind /api/. Safe to re-run; every deploy backs up what it replaces.
#
#   ./deploy.sh            # site + engine
#   ./deploy.sh site       # just the built UI
#   ./deploy.sh engine     # just the API
#   ./deploy.sh pi         # the Pi's Whisper worker, and the server's link to it
#   ./deploy.sh pc         # the same for this PC's GPU, run on the PC itself
#
# Needs gcloud auth (the `essore` alias uses the same VM), and for `pi` an SSH
# key the Pi accepts (it is reached over Tailscale).
set -euo pipefail

ZONE=${TRANSCRIPE_DEPLOY_ZONE:-us-central1-a}
VM=${TRANSCRIPE_DEPLOY_VM:-portfolio-vm}
PROJECT=${TRANSCRIPE_DEPLOY_PROJECT:-cella-b04d1}
SITE_DIR=${TRANSCRIPE_SITE_DIR:-/var/www/portfolio/transcripe}
API_DIR=${TRANSCRIPE_API_DIR:-/opt/transcripe-api}
PI=${TRANSCRIPE_PI:-cella@100.80.127.103}
# Best first: the server takes the first that answers. Each is a reverse tunnel.
REMOTES=http://127.0.0.1:8111,http://127.0.0.1:8110
TUNNEL_HOST=136.111.79.139
TUNNEL_HOST_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICX5jcLWJ3H90O0RWMXuo1VfYTYpoFjONbm4raAo+6wN"

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

build_wheel() {
  echo "→ building the wheel"
  rm -f dist/*.whl
  # The project venv is where `build` lives; system python usually lacks it.
  PY=python3
  for candidate in .venv/bin/python venv/bin/python; do
    [ -x "$candidate" ] && PY="$candidate" && break
  done
  "$PY" -m build --wheel >/dev/null
  WHEEL=$(ls dist/*.whl | head -1)
}

deploy_engine() {
  build_wheel
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
    # av<19: PyAV 19 dropped an argument faster-whisper 1.2 still passes, and
    # every transcription dies with a TypeError.
    '$API_DIR/venv/bin/pip' install -q 'fastapi>=0.115' uvicorn python-multipart yt-dlp Pillow pillow-heif cairosvg faster-whisper 'av<19'
    # YouTube changes under yt-dlp every few weeks and a plain install never
    # upgrades what is already there: the server sat on a 4-month-old copy.
    '$API_DIR/venv/bin/pip' install -q -U yt-dlp
    rm -f '/tmp/$(basename "$WHEEL")'
    sudo systemctl restart transcripe-api
    sleep 4
    systemctl is-active transcripe-api"
  echo "✓ engine deployed"
}

deploy_pi() {
  build_wheel
  scp -q "$WHEEL" deploy/pi/transcripe-worker.service deploy/pi/transcripe-tunnel.service "$PI:/tmp/"
  # The SD card failed once: pip's scratch and cache stay in tmpfs, and the
  # only lasting writes are the venv and the model, each written once.
  ssh "$PI" "set -e
    D=\$HOME/transcripe-worker
    mkdir -p \$D ~/.config/transcripe ~/.config/systemd/user
    [ -x \$D/venv/bin/python ] || python3 -m venv \$D/venv
    export TMPDIR=/tmp PIP_NO_CACHE_DIR=1
    # --force-reinstall: the version rarely changes between deploys. Then the
    # package's own metadata pulls in everything else — a hand-kept list
    # missed rich, and the worker died on import.
    \$D/venv/bin/pip install -q --force-reinstall --no-deps '/tmp/$(basename "$WHEEL")'
    \$D/venv/bin/pip install -q '/tmp/$(basename "$WHEEL")[whisper]' 'fastapi>=0.115' uvicorn python-multipart
    rm -f '/tmp/$(basename "$WHEEL")'
    if [ ! -s ~/.config/transcripe/worker.env ]; then
      ( umask 077; echo TRANSCRIPE_TOKEN=\$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))') > ~/.config/transcripe/worker.env )
    fi
    mv /tmp/transcripe-worker.service /tmp/transcripe-tunnel.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --quiet transcripe-worker transcripe-tunnel
    systemctl --user restart transcripe-worker transcripe-tunnel"

  # The server learns where the worker is and the token it wants. stdin, so
  # the token never sits in a process list on either end.
  { echo "TRANSCRIPE_REMOTE_URL=$REMOTES"
    ssh "$PI" cat .config/transcripe/worker.env | sed 's/^TRANSCRIPE_TOKEN=/TRANSCRIPE_REMOTE_TOKEN=/'
  } | run "set -e
    UNIT=/etc/systemd/system/transcripe-api.service
    sudo install -d -m 755 /etc/transcripe
    cat > /tmp/remote.env; chmod 600 /tmp/remote.env
    changed=0
    sudo cmp -s /tmp/remote.env /etc/transcripe/remote.env || { sudo install -m 600 -o root /tmp/remote.env /etc/transcripe/remote.env; changed=1; }
    rm -f /tmp/remote.env
    if ! grep -q remote.env \$UNIT; then
      sudo sed -i '/^ExecStart=/i EnvironmentFile=-/etc/transcripe/remote.env' \$UNIT
      sudo systemctl daemon-reload; changed=1
    fi
    # Restarting drops jobs in flight, so only when something changed.
    [ \$changed = 1 ] && sudo systemctl restart transcripe-api && sleep 4 || true
    systemctl is-active transcripe-api"
  echo "✓ pi worker deployed"
}

deploy_pc() {
  mkdir -p ~/.config/transcripe ~/.config/systemd/user
  [ -f ~/.ssh/transcripe_tunnel ] || ssh-keygen -q -t ed25519 -N "" -C "transcripe-tunnel@pc" -f ~/.ssh/transcripe_tunnel
  echo "$TUNNEL_HOST $TUNNEL_HOST_KEY" > ~/.ssh/transcripe_known_hosts
  # This key may open port 8111 on the server and nothing else. The worker's
  # token comes from the server, over stdout, so the Pi needn't be on for this.
  cat ~/.ssh/transcripe_tunnel.pub | run "set -e
    KEYS=/var/lib/transcripetunnel/.ssh/authorized_keys
    read -r PUB
    sudo grep -qF \"\$PUB\" \$KEYS || echo \"restrict,port-forwarding,permitlisten=\\\"127.0.0.1:8111\\\",permitopen=\\\"127.0.0.1:9\\\",command=\\\"/usr/sbin/nologin\\\" \$PUB\" | sudo tee -a \$KEYS >/dev/null"
  ( umask 077; run "sudo sed -n 's/^TRANSCRIPE_REMOTE_TOKEN=/TRANSCRIPE_TOKEN=/p' /etc/transcripe/remote.env" | grep '^TRANSCRIPE_TOKEN=' > ~/.config/transcripe/worker.env ) || true
  grep -q '^TRANSCRIPE_TOKEN=.' ~/.config/transcripe/worker.env || { echo "no token on the server: run ./deploy.sh pi first" >&2; exit 1; }
  "${PY:-.venv/bin/python}" -m pip install -q -e ".[whisper,gpu,studio]"
  cp deploy/pc/transcripe-worker.service deploy/pc/transcripe-tunnel.service ~/.config/systemd/user/
  systemctl --user daemon-reload
  systemctl --user enable --quiet transcripe-worker transcripe-tunnel
  systemctl --user restart transcripe-worker transcripe-tunnel
  # The server's list of workers; a restart only if it changed.
  run "set -e
    sudo sed 's#^TRANSCRIPE_REMOTE_URL=.*#TRANSCRIPE_REMOTE_URL=$REMOTES#' /etc/transcripe/remote.env > /tmp/remote.env
    if ! sudo cmp -s /tmp/remote.env /etc/transcripe/remote.env; then
      sudo install -m 600 -o root /tmp/remote.env /etc/transcripe/remote.env
      sudo systemctl restart transcripe-api
    fi
    rm -f /tmp/remote.env"
  echo "✓ pc worker deployed"
}

case "$WHAT" in
  site)   deploy_site ;;
  engine) deploy_engine ;;
  pi)     deploy_pi ;;
  pc)     deploy_pc ;;
  all)    deploy_site; deploy_engine ;;
  *)      echo "usage: $0 [all|site|engine|pi|pc]" >&2; exit 2 ;;
esac

echo "→ verifying"
# A restarted engine takes a few seconds to bind; don't report that as a 502.
curl -fsS --retry 6 --retry-delay 2 --retry-all-errors -o /dev/null -w "  /transcripe/ -> %{http_code}\n" https://alabed.site/transcripe/
printf "  /api/health  -> "; curl -fsS --retry 6 --retry-delay 2 --retry-all-errors https://alabed.site/api/health; echo
