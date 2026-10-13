#!/usr/bin/env bash
# Tunnel Cloudflare éphémère (trycloudflare.com) — secours si pas de tunnel nommé.
set -euo pipefail
ROOT="/opt/ventoux-watch"
CLOUDFLARED="${CLOUDFLARED:-/usr/local/bin/cloudflared}"
PY="${ROOT}/.venv/bin/python"
SET_URL="${ROOT}/scripts/set_radio_public_url.py"

exec "$CLOUDFLARED" tunnel --no-autoupdate --url http://127.0.0.1:8767 2>&1 | while IFS= read -r line; do
  echo "$line"
  if [[ "$line" =~ (https://[a-zA-Z0-9-]+\.trycloudflare\.com) ]]; then
    url="${BASH_REMATCH[1]}"
    if [[ -x "$PY" && -f "$SET_URL" ]]; then
      "$PY" "$SET_URL" "$url"
      sudo -n systemctl try-restart ventoux-stream.service 2>/dev/null || true
    fi
  fi
done
