#!/usr/bin/env python3
"""L'avatar de la chaîne : le pantin du flux, et rien d'autre.

Le bonhomme désarticulé est devenu la signature du projet. Il danse dans les
tranches noires, il traverse le ciel sur un tapis, il descend la piste de ski
en surf. Un logo dessiné à part serait un deuxième emblème pour une seule
chose ; celui-ci est tracé par « _danseur », la fonction même qui le dessine
à l'écran vingt-quatre heures sur vingt-quatre.

Deux contraintes viennent de YouTube et non du goût. L'avatar est rogné en
cercle, donc tout ce qui dépasse du disque inscrit disparaît. Et il s'affiche
à quarante-huit pixels dans les commentaires : un pantin en fil de fer y
devient une poussière. D'où un bonhomme large dans son cadre et des membres
épais — ce qui se lit à quarante-huit pixels se lit aussi à huit cents.

    python3 scripts/logo_chaine.py --planche    (les candidats, à choisir)
    python3 scripts/logo_chaine.py --phase 2.1  (celui qu'on garde)
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from watcher.stream import _danseur, BLANC, CYAN  # noqa: E402

COTE = 800
FOND = (26, 22, 18)
# Ni noir pur ni gris : sur le thème sombre de YouTube un avatar noir n'a plus
# de contour et se confond avec la page, et sur le thème clair un avatar gris
# a l'air délavé. Ce bleu très sombre se détache des deux.
ANNEAU = 0.055      # l'épaisseur du cercle, en parts du côté
MARGE = 0.045       # ce qu'on laisse respirer entre le pantin et le bord
# Les poses proposées. Elles ne sont pas prises au hasard : la phase est le
# seul paramètre du pantin, et celles-ci sont les quatre où les quatre membres
# partent dans quatre directions différentes. Un pantin dont les deux bras
# tombent du même côté ressemble à quelqu'un qui a froid.
POSES = (0.8, 2.1, 3.9, 5.2)
# Les trois habillages essayés, et celui qu'on garde en tête de liste.
#
# L'avatar est cyan sur fond sombre partout ailleurs dans le projet ; ici
# c'est l'inverse, pantin sombre sur disque cyan. Ce n'est pas une fantaisie :
# à quarante-huit pixels, un trait clair sur fond sombre se délave, alors
# qu'une silhouette sombre sur une pastille vive se lit du premier coup. Et
# une pastille cyan ne ressemble à aucune vignette de webcam, qui sont toutes
# vertes et grises — l'avatar doit se détacher d'elles, pas leur ressembler.
HABITS = {
    "pastille": (CYAN, (20, 18, 16), None),
    "badge": (FOND, BLANC, CYAN),
    "discret": (FOND, CYAN, None),
}


def pantin(phase: float, taille: float, fond: tuple,
           trait: tuple) -> np.ndarray:
    """Le bonhomme seul, rogné au plus juste sur ce qu'il occupe vraiment.

    Sa taille nominale ne dit pas son encombrement : selon la phase, un bras
    levé monte bien au-dessus du crâne et deux bras écartés le rendent plus
    large que haut. Le mesurer est le seul moyen de le centrer — au premier
    essai je l'avais posé à sa taille nominale et il sortait du cercle par
    les mains.
    """
    grand = int(taille * 3)
    toile = np.zeros((grand, grand, 3), np.uint8)
    toile[:] = fond
    _danseur(toile, grand // 2, int(grand * 0.72), taille, phase, trait)
    encre = np.argwhere((toile.astype(np.int16)
                         - np.array(fond, np.int16)).any(axis=2))
    haut, gauche = encre.min(axis=0)
    bas, droite = encre.max(axis=0)
    return toile[haut:bas + 1, gauche:droite + 1]


def logo(phase: float, cote: int = COTE, fond: tuple = FOND,
         trait: tuple = BLANC, anneau: tuple | None = CYAN) -> np.ndarray:
    """Un avatar carré, dont tout le dessin tient dans le disque inscrit."""
    image = np.zeros((cote, cote, 3), np.uint8)
    rayon = cote // 2
    cv2.circle(image, (rayon, rayon), rayon, fond, -1, cv2.LINE_AA)
    epais = max(2, int(cote * ANNEAU)) if anneau else 0
    if anneau:
        cv2.circle(image, (rayon, rayon), rayon - epais // 2, anneau,
                   epais, cv2.LINE_AA)

    bout = pantin(phase, cote * 0.5, fond, trait)
    haut, large = bout.shape[:2]
    # Le rectangle doit tenir dans le disque, pas dans le carré : ce sont ses
    # coins qui touchent le bord, donc c'est sa diagonale qu'on compare au
    # diamètre utile. Le comparer au côté le laisserait déborder en biais.
    libre = rayon - epais - cote * MARGE
    facteur = 2 * libre / math.hypot(large, haut)
    bout = cv2.resize(bout, (max(1, round(large * facteur)),
                             max(1, round(haut * facteur))),
                      interpolation=cv2.INTER_AREA)
    haut, large = bout.shape[:2]
    y, x = rayon - haut // 2, rayon - large // 2
    image[y:y + haut, x:x + large] = bout
    return image


def planche(cote: int) -> np.ndarray:
    """Les candidats côte à côte, et chacun en tout petit en dessous.

    La vignette de quarante-huit pixels n'est pas un détail à vérifier après
    coup : c'est la taille à laquelle l'avatar sera vu le plus souvent, et
    une pose qui ne tient pas là ne tient pas.
    """
    rangs = []
    for fond, trait, anneau in HABITS.values():
        cases = []
        for phase in POSES:
            grand = logo(phase, cote, fond, trait, anneau)
            petit = cv2.resize(grand, (48, 48), interpolation=cv2.INTER_AREA)
            case = np.zeros((cote, cote, 3), np.uint8)
            case[:] = grand
            gros_petit = cv2.resize(petit, (cote // 5, cote // 5),
                                    interpolation=cv2.INTER_NEAREST)
            case[-cote // 5:, -cote // 5:] = gros_petit
            cases.append(case)
        rangs.append(np.hstack(cases))
    return np.vstack(rangs)


def main() -> int:
    plaidoyer = argparse.ArgumentParser(description=__doc__)
    plaidoyer.add_argument("--phase", type=float, default=POSES[0])
    plaidoyer.add_argument("--cote", type=int, default=COTE)
    plaidoyer.add_argument("--habit", choices=sorted(HABITS), default="pastille")
    plaidoyer.add_argument("--planche", action="store_true")
    plaidoyer.add_argument("--sortie", default="")
    options = plaidoyer.parse_args()

    if options.planche:
        image = planche(options.cote // 2)
        chemin = Path(options.sortie or "/tmp/logo-planche.png")
    else:
        image = logo(options.phase, options.cote, *HABITS[options.habit])
        chemin = Path(options.sortie or ROOT / "assets" / "logo-chaine.png")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(chemin), image)
    print(f"{chemin}  {image.shape[1]}x{image.shape[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
