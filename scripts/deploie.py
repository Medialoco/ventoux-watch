"""Déploie sur le Pi sans faire tomber la diffusion.

Deux fois le premier octobre la diffusion YouTube est morte, et les deux fois
c'est le déploiement qui l'a tuée. À neuf heures dix-sept, huit redémarrages
d'affilée provoqués par un 404 de la webcam ; à dix-huit heures, trois
redémarrages manuels en vingt-cinq minutes pour trois corrections que rien
n'obligeait à livrer séparément. YouTube ne supporte pas qu'une arrivée de flux
clignote : il termine la diffusion, puis continue d'accepter les octets dans le
vide, sans une erreur.

La veille peut redémarrer autant qu'on veut — elle écrit des fichiers et ne
touche pas à l'antenne. Le flux, non. Ce programme sépare donc les deux, et
refuse de redémarrer le flux trop souvent, parce que la règle appartient au
code et non à ma mémoire.

    .venv/bin/python -m scripts.deploie
    .venv/bin/python -m scripts.deploie --flux          # si c'est le flux qui change
    .venv/bin/python -m scripts.deploie --flux --quand-meme
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MACHINE = "ventoux@ventoux.local"
DEPOT = "/opt/ventoux-watch"

# Une heure entre deux redémarrages du flux. Ce n'est pas un chiffre de YouTube,
# qui n'en publie aucun : c'est la constatation que trois coupures en vingt-cinq
# minutes terminent la diffusion et qu'une seule par heure ne l'a jamais fait.
# Mieux vaut livrer en retard que livrer dans le vide.
REPOS_FLUX_S = 3600.0
# Le temps qu'il faut à YouTube pour reconnaître une arrivée de flux et
# rouvrir la page en direct. Mesuré, pas supposé.
REPRISE_S = 45.0


def _ssh(commande: str, muet: bool = False) -> str:
    fini = subprocess.run(["ssh", MACHINE, commande], capture_output=True,
                          text=True, check=False)
    if fini.returncode and not muet:
        raise SystemExit(f"Le Pi a refusé « {commande[:60]} » :\n{fini.stderr.strip()}")
    return fini.stdout.strip()


def depuis_quand(service: str) -> float:
    """Depuis combien de secondes ce service tourne sans interruption."""
    brut = _ssh(f"systemctl show {service} -p ActiveEnterTimestampMonotonic --value")
    debut = int(brut or 0) / 1_000_000
    horloge = float(_ssh("cut -d' ' -f1 /proc/uptime") or 0.0)
    return max(0.0, horloge - debut)


def chaine_en_direct() -> bool | None:
    from watcher.stream import direct_visible
    cfg = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    chaine = cfg.get("youtube_chaine")
    return direct_visible(chaine) if chaine else None


def main(argv: list[str] | None = None) -> int:
    partie = argparse.ArgumentParser(description=__doc__)
    partie.add_argument("--flux", action="store_true",
                        help="redémarrer aussi la diffusion (coupe l'antenne)")
    partie.add_argument("--quand-meme", action="store_true",
                        help="passer outre le repos minimum entre deux coupures")
    args = partie.parse_args(argv)

    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=ROOT, check=True)
    # autoStash parce que la veille réécrit view.jpg et learning.json en
    # permanence : sans elle le rebase refuse de partir une fois sur deux.
    _ssh(f"cd {DEPOT} && git -c rebase.autoStash=true pull -q --rebase origin main")
    print("Pi à", _ssh(f"cd {DEPOT} && git log --oneline -1"))

    _ssh("sudo systemctl restart ventoux-watch")
    print("Veille redémarrée.")

    if not args.flux:
        print("Flux laissé tel quel : le code est en place, il partira au "
              "prochain redémarrage. Ajouter --flux si le changement le concerne.")
        return 0

    repos = depuis_quand("ventoux-stream")
    if repos < REPOS_FLUX_S and not args.quand_meme:
        print(f"Flux NON redémarré : il n'émet que depuis {repos / 60:.0f} min, "
              f"et il en faut {REPOS_FLUX_S / 60:.0f}. Trois coupures en "
              f"vingt-cinq minutes ont déjà terminé la diffusion aujourd'hui.\n"
              f"Attendre {(REPOS_FLUX_S - repos) / 60:.0f} min, grouper avec "
              f"les prochains changements, ou forcer avec --quand-meme.")
        return 2

    avant = chaine_en_direct()
    if avant is False:
        print("La chaîne n'est de toute façon pas en direct : redémarrer le "
              "flux n'y changera rien, il faut d'abord rouvrir une diffusion "
              "dans YouTube Studio.")
    _ssh("sudo systemctl restart ventoux-stream")
    print(f"Flux redémarré à {datetime.now().strftime('%H:%M:%S')}, "
          f"on laisse {REPRISE_S:.0f} s à YouTube…")
    time.sleep(REPRISE_S)
    etat = _ssh("systemctl is-active ventoux-stream ventoux-watch", muet=True)
    apres = chaine_en_direct()
    dit = {True: "oui", False: "NON", None: "illisible"}[apres]
    print(f"Services : {etat.replace(chr(10), ' + ')} · en direct : {dit}")
    return 0 if apres is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
