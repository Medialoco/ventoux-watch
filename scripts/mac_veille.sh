#!/usr/bin/env bash
# Lance la veille sur le Mac, en la détachant du terminal qui la lance.
#
# Le détachement n'est pas une précaution de confort : sans lui, la veille
# meurt avec le terminal. « nohup » ne suffit pas, il ne protège que du
# signal de raccrochage ; quand le shell qui a lancé la commande se termine,
# il emporte tout son groupe de processus, veille comprise. Le 27 septembre,
# c'est ainsi qu'elle s'est arrêtée trois fois dans la journée, chaque fois
# quelques secondes après la commande qui l'avait démarrée, sans une ligne
# de journal pour le dire.
#
# setsid() fait du veilleur le chef de sa propre session. Plus personne ne
# l'emporte en partant. Sur le Raspberry c'est systemd qui s'en charge ;
# ici, il faut le demander à la main.
set -euo pipefail

racine="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$racine"

exec .venv/bin/python - <<'PYTHON'
import os

if os.fork() != 0:
    raise SystemExit(0)
os.setsid()
if os.fork() != 0:
    os._exit(0)

journal = os.open("data/watch.log", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
vide = os.open(os.devnull, os.O_RDONLY)
os.dup2(vide, 0)
os.dup2(journal, 1)
os.dup2(journal, 2)
os.execv(".venv/bin/python", [".venv/bin/python", "-u", "-m", "watcher"])
PYTHON
