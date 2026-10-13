#!/usr/bin/env bash
# Tunnel nommé (token ou config cloudflared) si présent, sinon quick tunnel.
set -euo pipefail
ROOT="/opt/ventoux-watch"
CLOUDFLARED="${CLOUDFLARED:-/usr/local/bin/cloudflared}"
TOKEN_FILE="${ROOT}/config/radio_tunnel.token"
CONFIG="${ROOT}/config/cloudflared-radio.yml"
PY="${ROOT}/.venv/bin/python"
SYNC="${ROOT}/scripts/sync_radio_public_from_config.py"

if [[ -f "$TOKEN_FILE" ]]; then
  if [[ -x "$PY" && -f "$SYNC" ]]; then
    "$PY" "$SYNC" || true
  fi
  exec "$CLOUDFLARED" tunnel --no-autoupdate run --token "$(tr -d ' \n\r' < "$TOKEN_FILE")"
fi

if [[ -f "$CONFIG" ]]; then
  if [[ -x "$PY" && -f "$SYNC" ]]; then
    "$PY" "$SYNC" || true
  fi
  exec "$CLOUDFLARED" tunnel --no-autoupdate --config "$CONFIG" run
fi

exec "${ROOT}/scripts/radio_tunnel_quick.sh"
