"""Enregistre les quelques mots que le flux dit quand il ne se passe rien.

La machine du Ventoux n'a aucune synthèse vocale et n'en aura pas : elle tourne
déjà à la limite thermique, et installer un moteur de parole pour cinq secondes
de son par vingt minutes serait payer cher une plaisanterie. On enregistre donc
ici, une fois, et on ne livre là-bas que des fichiers.

Le format de sortie est celui que la diffusion manipule déjà — PCM brut, 44 100
hertz, deux voies, seize bits signés — pour qu'au moment de parler il n'y ait
rien à convertir : seulement des octets à additionner.

    .venv/bin/python -m scripts.voix_ennui
    .venv/bin/python -m scripts.voix_ennui --ecoute

Les voix employées sont celles de macOS. Elles conviennent pour la mise au
point ; si la chaîne doit vivre, enregistrer les mêmes phrases soi-même règle à
la fois la question du droit et celle du ton.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ECHANTILLONS_S = 44100
VOIES = 2

# Plusieurs phrases, et plusieurs voix. La même réplique toutes les vingt
# minutes pendant une nuit entière cesse d'être une blague et devient une
# alarme ; c'est la variation qui fait qu'on sourit encore à la cinquième.
# Deux occasions de parler, et deux tons. L'ennui traîne, la prise claque :
# la même voix pour les deux ferait du « good catch » une remarque de plus
# alors que c'est le seul moment où la machine a réussi quelque chose.
REPLIQUES = [
    ("ennui", "Bubbles", "Boooooooring"),
    ("ennui", "Bad News", "Still nothing"),
    ("ennui", "Boing", "So boooring"),
    ("ennui", "Bubbles", "Nothing. Again"),
    ("ennui", "Bad News", "Absolutely nothing is happening"),
    ("ennui", "Boing", "Boooooring"),
    ("attrape", "Boing", "Good catch!"),
    ("attrape", "Bubbles", "Good catch!"),
    ("attrape", "Boing", "Got one!"),
    ("attrape", "Bubbles", "Nice one!"),
    ("matin", "Boing", "Goooood morning Ventoux!"),
    ("matin", "Bubbles", "Goooood morning Ventoux!"),
]


def _nom(voix: str, texte: str) -> str:
    return re.sub(r"[^\w]+", "_", f"{voix}-{texte}").strip("_").lower()[:60] + ".raw"


def grave(voix: str, texte: str, cible: Path) -> float:
    """Dit la phrase et la pose en PCM brut. Rend sa durée en secondes."""
    with tempfile.TemporaryDirectory() as dossier:
        brut = Path(dossier) / "dit.aiff"
        subprocess.run(["say", "-v", voix, "-o", str(brut), texte], check=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(brut),
             # Un peu de marge sous le maximum : la voix va s'additionner à la
             # musique, et deux signaux au plafond font un écrêtage.
             "-af", f"volume=0.85,aresample={ECHANTILLONS_S}",
             "-f", "s16le", "-ar", str(ECHANTILLONS_S), "-ac", str(VOIES), str(cible)],
            check=True)
    return cible.stat().st_size / (ECHANTILLONS_S * VOIES * 2)


def enregistre(dossier: Path, ecoute: bool = False) -> int:
    if shutil.which("say") is None:
        print("« say » n'existe que sur macOS : à lancer depuis le Mac, pas depuis le Pi.")
        return 1
    dossier.mkdir(parents=True, exist_ok=True)
    fiches = []
    for quand, voix, texte in REPLIQUES:
        cible = dossier / _nom(f"{quand}-{voix}", texte)
        duree = grave(voix, texte, cible)
        fiches.append({"fichier": cible.name, "texte": texte, "voix": voix,
                       "quand": quand, "duree": round(duree, 3)})
        print(f"  {duree:4.1f} s  {quand:8s} {voix:10s} « {texte} »")
        if ecoute:
            subprocess.run(["ffplay", "-hide_banner", "-loglevel", "error", "-autoexit",
                            "-f", "s16le", "-ar", str(ECHANTILLONS_S), "-ac", str(VOIES),
                            str(cible)], check=False)
    (dossier / "voix.json").write_text(
        json.dumps(fiches, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(fiches)} répliques dans {dossier}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--dossier", default=str(ROOT / "data" / "voix"))
    parseur.add_argument("--ecoute", action="store_true", help="les jouer en les gravant")
    args = parseur.parse_args(argv)
    return enregistre(Path(args.dossier), args.ecoute)


if __name__ == "__main__":
    raise SystemExit(main())
