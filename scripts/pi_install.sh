#!/usr/bin/env bash
# Installe le veilleur sur un Raspberry Pi fraîchement démarré.
#
# Le script est rejouable : on peut le relancer sur une machine déjà installée
# sans rien casser. C'est la condition pour en équiper cent, puis mille.
#
#   ssh ventoux 'bash -s' < scripts/pi_install.sh
set -euo pipefail

DEPOT="${DEPOT:-git@github.com:Medialoco/ventoux-watch.git}"
RACINE="${RACINE:-/opt/ventoux-watch}"
CLE="$HOME/.ssh/id_ed25519_ventoux_deploy"

dire() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

dire "Paquets système"
sudo apt-get update -qq
# ffmpeg lit le flux HLS ; libGL et libglib sont réclamés par OpenCV même en
# version « headless » ; git est le moyen de publication du veilleur.
sudo apt-get install -y -qq git ffmpeg python3-venv python3-dev \
    libgl1 libglib2.0-0 rsync gdisk

dire "Fuseau horaire"
# Les horodatages du site sont lus par un humain sur place.
sudo timedatectl set-timezone Europe/Paris

dire "Journaux bornés"
# Le journal système écrit en continu ; sur une carte SD c'est la première
# chose qui l'use. On le plafonne à 50 Mo.
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=50M\n' | sudo tee /etc/systemd/journald.conf.d/taille.conf >/dev/null
sudo systemctl restart systemd-journald

dire "Clé de déploiement"
if [ ! -f "$CLE" ]; then
    ssh-keygen -t ed25519 -f "$CLE" -N "" -C "ventoux-pi -> depot" >/dev/null
fi
if ! grep -q "ventoux-deploy" "$HOME/.ssh/config" 2>/dev/null; then
    cat >> "$HOME/.ssh/config" <<EOF

# ventoux-deploy
Host github.com
  IdentityFile $CLE
  IdentitiesOnly yes
EOF
fi
ssh-keyscan -t ed25519 github.com 2>/dev/null >> "$HOME/.ssh/known_hosts"
sort -u -o "$HOME/.ssh/known_hosts" "$HOME/.ssh/known_hosts"

if ! ssh -o BatchMode=yes -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    dire "ACTION REQUISE"
    echo "Cette clé publique doit être déclarée dans le dépôt, en écriture :"
    echo
    cat "$CLE.pub"
    echo
    echo "Puis relancer ce script."
    exit 3
fi

dire "Dépôt"
sudo mkdir -p "$RACINE"
sudo chown "$USER:$USER" "$RACINE"
if [ -d "$RACINE/.git" ]; then
    git -C "$RACINE" pull --rebase --autostash
else
    # Clone superficiel : l'historique pèse plus de 400 Mo et n'apporte rien à
    # une machine qui ne fait qu'ajouter des événements.
    git clone --depth 1 "$DEPOT" "$RACINE"
fi
git -C "$RACINE" config user.name "Veilleur Ventoux"
git -C "$RACINE" config user.email "veilleur@medialoco.invalid"

dire "Environnement Python"
[ -d "$RACINE/.venv" ] || python3 -m venv "$RACINE/.venv"
"$RACINE/.venv/bin/pip" install -qU pip
"$RACINE/.venv/bin/pip" install -qr "$RACINE/requirements.txt"

dire "Service"
sudo tee /etc/systemd/system/ventoux-watch.service >/dev/null <<EOF
[Unit]
Description=Veille webcam Mont Serein
After=network-online.target
Wants=network-online.target
# Quand data/ sera un disque externe, le veilleur attendra qu'il soit monté
# plutôt que d'écrire sur la carte SD sous le point de montage.
RequiresMountsFor=$RACINE/data

[Service]
Type=simple
User=$USER
WorkingDirectory=$RACINE
ExecStart=$RACINE/.venv/bin/python -m watcher
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable ventoux-watch >/dev/null

dire "État"
if [ ! -f "$RACINE/config/local.json" ]; then
    echo "config/local.json absent : les identifiants OpenSky n'ont pas encore"
    echo "été copiés depuis le Mac. Le veilleur tournera sans les avions."
fi
echo "Installé dans $RACINE. Démarrer avec : sudo systemctl start ventoux-watch"
