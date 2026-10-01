"""Pose la clé de diffusion YouTube sans qu'elle passe nulle part d'autre.

La clé est un mot de passe : qui l'a peut diffuser sur la chaîne. Tapée dans
une commande, elle resterait dans l'historique du shell et dans la liste des
processus ; collée dans une conversation, elle y resterait pour toujours. Ce
programme la demande sans l'afficher et l'écrit dans « config/local.json »,
que git ignore et que le veilleur seul peut lire.

    .venv/bin/python -m scripts.cle_youtube

La clé se trouve dans YouTube Studio, « Créer » puis « Passer au direct »,
onglet « Paramètres du flux », champ « Clé de flux ».
"""

from __future__ import annotations

import json
import os
import stat
import sys
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    chemin = ROOT / "config" / "local.json"
    cle = getpass("Clé de flux YouTube (rien ne s'affiche) : ").strip()
    if not cle:
        print("Rien saisi, rien écrit.")
        return 1
    if "/" in cle or cle.startswith("rtmp"):
        print("On attend la clé seule, pas l'adresse d'ingestion.")
        return 1

    local = {}
    if chemin.is_file():
        local = json.loads(chemin.read_text(encoding="utf-8"))
    local.setdefault("youtube", {})["key"] = cle
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(chemin, stat.S_IRUSR | stat.S_IWUSR)

    # Ce qu'on confirme : la longueur, jamais le contenu.
    print(f"Clé de {len(cle)} caractères écrite dans {chemin.relative_to(ROOT)}, en mode 600.")
    print("Vérifiez que « config/local.json » est bien ignoré par git :")
    print("    git check-ignore -v config/local.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
