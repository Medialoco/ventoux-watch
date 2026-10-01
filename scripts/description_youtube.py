"""Écrit la description de la chaîne, en anglais, avec tout ce qui peut passer.

La licence demande qu'on cite. Le flux le fait déjà à l'écran, titre par titre,
mais un bandeau n'est pas une trace : il s'efface, il n'est pas cherchable, et
personne ne peut y cliquer. La description, elle, reste — et c'est là qu'on
peut mettre le lien vers le morceau et vers sa licence, ce qu'un pixel ne sait
pas faire.

Rangé par artiste et non par titre : c'est l'artiste qu'on crédite, et c'est
sous son nom qu'un auditeur ira chercher le reste.

    .venv/bin/python -m scripts.description_youtube > description.txt
    .venv/bin/python -m scripts.description_youtube --credits data/musique/credits.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# YouTube coupe à cinq mille caractères. On écrit donc la liste complète tant
# qu'elle tient, et on dit franchement combien manquent sinon — plutôt que de
# s'arrêter au milieu d'un nom, ce qui serait un crédit tronqué, c'est-à-dire
# pas un crédit.
LIMITE = 5000

ENTETE = """\
A computer watches a mountain road at 1,389 m on Mont Ventoux, in Provence, and
tells you what it sees. Cars, vans, walkers, the occasional aircraft overhead.
When nothing happens for twenty minutes, it says so. It is honest about being
bored.

Everything on screen is measured, not guessed: distances in metres, the sun's
position from the date and the latitude, and the ridge line from a terrain
model — which is why the overlay can tell you that the slope falls into the
shadow of the Ventoux a good hour before the sun actually sets.

WHAT THE BADGES MEAN
LIVE      the webcam, a few seconds behind real time
REPLAY    something caught earlier, that a human confirmed
3D MODEL  a slow turn around the terrain, when nothing is moving

THE MUSIC
Free music only, and the licence is on screen for every track. Nothing here
restricts commercial use or forbids editing, because this stream is cut into
slices and ducked under a voice — both of which are edits. Most of it comes
from Dogmazic, a French free-music library running since 2004; the rest is
written for this channel and released under CC0.
"""

# Quinze et pas un de plus : YouTube n'affiche que les trois premiers au-dessus
# du titre, et au-delà de quinze il cesse d'en tenir compte — tous, pas
# seulement les derniers. « Nombreux » s'arrête donc là où ils comptent encore.
MOTS_DIESE = (
    "#MontVentoux #SlowTV #LiveCam #Provence #France #Mountain #Webcam #Nature "
    "#ComputerVision #RaspberryPi #OpenSource #CreativeCommons #FreeMusic "
    "#Ambient #Relaxing"
)

MAX_DIESE = 15


def mots_diese(corps: str, choisis: str = "") -> str:
    """Nos mots-dièse, moins ceux que les noms d'artistes ont déjà consommés.

    « #NarNaöud# » est un nom d'artiste, mais YouTube y lit un mot-dièse comme
    dans n'importe quel texte. Au-delà de quinze il cesse de tous les prendre
    en compte, les nôtres compris — un nom propre peut donc annuler la liste
    entière. On compte ce que le corps a déjà pris et on s'arrête avant.
    """
    deja = len(re.findall(r"#\w", corps))
    mots = (choisis or MOTS_DIESE).split()
    return " ".join(mots[:max(0, MAX_DIESE - deja)])


PIED = """\
Webcam: Vision Environnement, Mont Serein.
Terrain and place names: OpenStreetMap contributors and public elevation data.
Aircraft: the OpenSky Network.
Weather: Open-Meteo.

This channel is a camera and a curiosity. It is not a monitoring service, it
raises no alarm of any kind, and nothing it says should be acted upon.

"""


def charge(chemin: Path) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))


def par_artiste(credits: dict, source: str | None = None) -> dict[str, list[dict]]:
    groupes: dict[str, list[dict]] = defaultdict(list)
    for fiche in credits.values():
        if source is not None and fiche.get("source", "") != source:
            continue
        groupes[fiche.get("auteur") or "Unknown"].append(fiche)
    return dict(sorted(groupes.items(), key=lambda couple: couple[0].lower()))


def _licence_courte(nom: str) -> str:
    """« Creative Commons - by 2.0 » devient « CC BY 2.0 ».

    Pas par coquetterie : la liste tient quatre-vingts lignes, et la forme
    longue répétée cent fois mangerait le quota de caractères qu'on veut
    donner aux titres.
    """
    propre = (nom or "").strip()
    bas = propre.lower()
    if bas.startswith("creative commons"):
        reste = propre.split("-", 1)[1].strip() if "-" in propre else ""
        return ("CC " + reste.upper()).replace("CC BY", "CC BY").strip()
    return propre


def lignes_musique(credits: dict) -> list[str]:
    """Un artiste par ligne, ses titres, sa licence. Pas de lien par morceau.

    Cent vingt-neuf adresses de soixante caractères font huit mille signes à
    elles seules, et YouTube coupe à cinq mille : la liste s'arrêtait au quart
    et quatre-vingt-dix artistes n'avaient aucun crédit du tout. Un lien par
    artiste coûtait encore mille sept cents signes, et huit restaient dehors.

    L'obligation est de nommer l'auteur, le titre et la licence, et de lier
    « quand c'est raisonnablement possible ». Nommer tout le monde avec
    l'adresse de la médiathèque, où l'on cherche par artiste, remplit mieux
    cette obligation que lier vingt personnes en en taisant huit.
    """
    lignes: list[str] = []
    dogmazic = par_artiste(credits, "Dogmazic")
    maison = par_artiste(credits, None)
    maison = {nom: fiches for nom, fiches in maison.items()
              if all(f.get("source") != "Dogmazic" for f in fiches)}
    if dogmazic:
        total = sum(len(f) for f in dogmazic.values())
        lignes.append(f"FROM DOGMAZIC — {total} tracks by {len(dogmazic)} artists")
        lignes.append("Search any name below at https://play.dogmazic.net")
        lignes.append("")
        for nom, fiches in dogmazic.items():
            rangees = sorted(fiches, key=lambda f: (f.get("titre") or "").lower())
            licences = sorted({_licence_courte(f.get("licence", "")) for f in rangees})
            lignes.append(f"{nom} — {', '.join(licences)}")
            lignes.append("  " + ", ".join(f.get("titre", "?") for f in rangees))
            lignes.append("")
    if maison:
        lignes.append("WRITTEN FOR THIS CHANNEL")
        for nom, fiches in maison.items():
            titres = sorted((f.get("titre") or "?") for f in fiches)
            licence = _licence_courte(fiches[0].get("licence", ""))
            lignes.append(f"{nom} — {len(titres)} tracks, {licence}")
            lignes.append(f"  {titres[0]} … {titres[-1]}")
        lignes.append("")
    return lignes


def description(credits: dict, limite: int = LIMITE) -> str:
    corps = lignes_musique(credits)
    tronc = ENTETE + "\n" + "\n".join(corps) + "\n" + PIED
    texte = tronc + "\n" + mots_diese(tronc) + "\n"
    if len(texte) <= limite:
        return texte
    # Trop long : on coupe à l'artiste, jamais au milieu d'un nom, et on dit
    # combien manquent avec l'adresse où les trouver tous.
    gardees: list[str] = []
    place = limite - len(ENTETE) - len(PIED) - 200
    for ligne in corps:
        if sum(len(l) + 1 for l in gardees) + len(ligne) > place:
            break
        gardees.append(ligne)
    restants = len(credits) - sum(1 for l in gardees if l.startswith("  · "))
    gardees += ["", f"… and {restants} more tracks, all free-licensed, each one",
                "credited on screen while it plays."]
    tronc = ENTETE + "\n" + "\n".join(gardees) + "\n" + PIED
    return tronc + "\n" + mots_diese(tronc) + "\n"


def main() -> int:
    partie = argparse.ArgumentParser(description=__doc__)
    partie.add_argument("--credits", default="data/musique/credits.json")
    partie.add_argument("--limite", type=int, default=LIMITE)
    args = partie.parse_args()
    chemin = Path(args.credits)
    if not chemin.is_absolute():
        chemin = ROOT / chemin
    texte = description(charge(chemin), args.limite)
    sys.stdout.write(texte)
    print(f"\n[{len(texte)} caractères sur {args.limite}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
