#!/usr/bin/env python3
"""Étiquette les morceaux de la maison pour les déposer sur Dogmazic.

Les seize fichiers sortent de la fabrique sans la moindre étiquette : ni
titre, ni artiste, ni album, ni licence. Tels quels ils arrivent chez
Dogmazic comme seize fichiers anonymes de quinze minutes, et c'est au
déposant de retaper tout à la main, seize fois.

Ce script écrit les étiquettes, colle la pochette, et range le tout dans un
dossier qu'on glisse dans le formulaire. L'envoi lui-même n'est pas ici et
n'y sera pas : l'API de Dogmazic ne permet pas de déposer en dessous du
niveau 75, et le compte est au niveau 25. Il faut le formulaire du site avec
une session ouverte, c'est-à-dire la vôtre.

La licence écrite dans le fichier est celle que le déposant déclarera dans
le formulaire. Les deux doivent dire la même chose : un fichier qui annonce
une licence et une fiche qui en annonce une autre, c'est la fiche qui fait
foi et le fichier qui ment.

    python3 scripts/album_dogmazic.py "~/Desktop/Mont Serein 002"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ALBUM = "Mont Serein 002"
AUTEUR = "thepriben"
GENRE = "Techno"
ANNEE = "2026"
# La licence choisie pour le dépôt. CC BY demande qu'on cite l'auteur et
# n'interdit ni le commerce ni la modification : c'est la plus permissive
# qui garde le nom attaché à l'œuvre.
LICENCE = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
# Le numéro de cette licence chez Dogmazic, à choisir dans le formulaire.
LICENCE_DOGMAZIC = 48

OU = ("Musique écrite pour la veille du Mont Serein, "
      "https://medialoco.github.io/ventoux-watch/")


def tempo_et_titre(nom: str) -> tuple[str, float, int]:
    """Ce que les crédits de la diffusion savent déjà de ce fichier."""
    credits = json.loads((ROOT / "data" / "musique" / "credits.json")
                         .read_text(encoding="utf-8"))
    fiche = credits.get(nom) or {}
    numero = int(nom.rsplit("-", 1)[-1].split(".")[0])
    return (str(fiche.get("titre") or f"{ALBUM}.{numero:02d}"),
            float(fiche.get("tempo") or 0.0), numero)


def etiquette(source: Path, cible: Path, pochette: Path | None,
              titre: str, tempo: float, piste: int, combien: int) -> bool:
    commande = ["ffmpeg", "-v", "error", "-y", "-i", str(source)]
    if pochette is not None:
        commande += ["-i", str(pochette), "-map", "0:a", "-map", "1",
                     "-c:v", "mjpeg", "-disposition:v", "attached_pic",
                     "-metadata:s:v", "title=Album cover",
                     "-metadata:s:v", "comment=Cover (front)"]
    else:
        commande += ["-map", "0:a"]
    commande += ["-c:a", "copy", "-id3v2_version", "3", "-write_id3v1", "1"]
    for champ, valeur in (
            ("title", titre), ("artist", AUTEUR), ("album_artist", AUTEUR),
            ("album", ALBUM), ("genre", GENRE), ("date", ANNEE),
            ("track", f"{piste}/{combien}"), ("copyright", LICENCE),
            ("comment", f"{LICENCE} · {LICENCE_URL} · {OU}"),
            ("TBPM", f"{tempo:.0f}" if tempo else ""),
            ("WXXX", LICENCE_URL)):
        if valeur:
            commande += ["-metadata", f"{champ}={valeur}"]
    commande.append(str(cible))
    return subprocess.run(commande).returncode == 0


def main() -> int:
    sujet = argparse.ArgumentParser(description=__doc__)
    sujet.add_argument("dossier", help="où sont les mp3 à étiqueter")
    sujet.add_argument("--pochette",
                       default="data/musique/pochettes/thepriben.jpg")
    args = sujet.parse_args()

    dossier = Path(args.dossier).expanduser()
    fichiers = sorted(dossier.glob("ventoux-002-*.mp3"))
    if not fichiers:
        print(f"Aucun morceau dans {dossier}")
        return 1
    pochette = ROOT / args.pochette
    if not pochette.is_file():
        print(f"Pas de pochette en {pochette}, les fichiers n'en auront pas")
        pochette = None

    pret = dossier / "pret-a-deposer"
    pret.mkdir(exist_ok=True)
    faits = 0
    for source in fichiers:
        titre, tempo, numero = tempo_et_titre(source.name)
        cible = pret / f"{numero:02d} - {titre}.mp3"
        if etiquette(source, cible, pochette, titre, tempo, numero,
                     len(fichiers)):
            faits += 1
            print(f"  {cible.name}   {tempo:.0f} bpm")
        else:
            print(f"  échec : {source.name}")

    print(f"\n{faits} morceaux étiquetés dans {pret}")
    print(f"Artiste {AUTEUR} · album « {ALBUM} » · genre {GENRE} · {ANNEE}")
    print(f"Licence à choisir dans le formulaire : {LICENCE}")
    print(f"  (numéro {LICENCE_DOGMAZIC} chez Dogmazic)")
    return 0 if faits == len(fichiers) else 1


if __name__ == "__main__":
    sys.exit(main())
