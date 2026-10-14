#!/usr/bin/env bash
# Tunnel Cloudflare éphémère. Écrit l'URL publique sans relancer YouTube.
set -euo pipefail
ROOT="/opt/ventoux-watch"
CLOUDFLARED="${CLOUDFLARED:-/usr/local/bin/cloudflared}"
PY="${ROOT}/.venv/bin/python"

publie() {
  local url="$1"
  "$PY" "$ROOT/scripts/set_radio_public_url.py" "$url" || true
  "$PY" -c "
from pathlib import Path
from watcher.radio_serveur import note_radio
from watcher.publish import publish
note_radio(Path('$ROOT'), live=True, public_base='$url')
publish(Path('$ROOT'))
" || true
}

exec "$CLOUDFLARED" tunnel --no-autoupdate --url http://127.0.0.1:8767 2>&1 | while IFS= read -r line; do
  echo "$line"
  if [[ "$line" =~ (https://[a-zA-Z0-9-]+\.trycloudflare\.com) ]]; then
    publie "${BASH_REMATCH[1]}"
  fi
done
