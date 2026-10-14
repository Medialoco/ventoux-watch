#!/usr/bin/env bash
# Connecteur nommé en arrière-plan (URL stable dès que le hostname existe),
# et tunnel public au premier plan tant que radio.benoit-prieur.fr n'est pas routé.
set -euo pipefail
ROOT="/opt/ventoux-watch"
CLOUDFLARED="${CLOUDFLARED:-/usr/local/bin/cloudflared}"
TOKEN_FILE="${ROOT}/config/radio_tunnel.token"
CONFIG="${ROOT}/config/cloudflared-radio.yml"

named_pid=""
cleanup() {
  if [[ -n "${named_pid}" ]]; then
    kill "${named_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ -f "$TOKEN_FILE" ]]; then
  "$CLOUDFLARED" tunnel --no-autoupdate run --token "$(tr -d ' \n\r' < "$TOKEN_FILE")" &
  named_pid=$!
elif [[ -f "$CONFIG" ]]; then
  "$CLOUDFLARED" tunnel --no-autoupdate --config "$CONFIG" run &
  named_pid=$!
fi

exec "${ROOT}/scripts/radio_tunnel_quick.sh"
