"""L'heure de prise de vue, lue dans le flux lui-même.

Deux programmes regardent la même webcam et doivent parler de la même seconde :
la veille, qui nomme ce qui passe, et la diffusion, qui pose le rectangle
dessus. Aucun des deux ne voit l'image à l'instant où elle est prise — la
veille la reçoit vingt et une secondes plus tard, la diffusion la montre plus
tard encore, et ces deux retards ne sont pas les mêmes.

Tant que chacun datait à sa propre montre, le rectangle désignait un bout de
route vide. La seule heure sur laquelle les deux peuvent s'accorder est celle
de la prise de vue, et le flux la donne : le HLS porte un
« EXT-X-PROGRAM-DATE-TIME » par segment. On l'ancre une fois au démarrage, et
le compte des images fait le reste — le filtre « fps » de ffmpeg rend
exactement une image par seconde de film, quoi qu'il arrive au réseau, donc
compter les images c'est compter les secondes de la montagne.

Rien ici ne connaît cette caméra : une playlist, des dates, une cadence. La
même lecture vaudra pour la centième webcam comme pour la première.
"""

from __future__ import annotations

import logging
import time
import urllib.request
from datetime import datetime

log = logging.getLogger("ventoux.direct")

# Le temps qu'il faut laisser entre notre lecture de la playlist et celle que
# ffmpeg en fait une fraction de seconde plus tard.
#
# On lui demande de reculer de N segments ; il compte depuis la fin de la
# playlist telle qu'il la voit, lui. Si un segment neuf paraît entre nos deux
# lectures, son N-ième n'est pas le nôtre et toute la suite est décalée d'un
# segment entier — sept secondes, soit bien plus que ce qu'on cherche à
# corriger. Alors on ne part jamais dans les deux dernières secondes d'un
# segment : on attend le suivant, et on a toute sa durée devant soi.
MARGE_DEPART_S = 2.0
PAS_D_ATTENTE_S = 0.5


def _lire(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as reponse:
        return reponse.read().decode("utf-8", "replace")


def playlist_media(url: str) -> str:
    """L'adresse de la liste des segments, sous la liste maîtresse."""
    for ligne in _lire(url).splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#"):
            return ligne if ligne.startswith("http") else url.rsplit("/", 1)[0] + "/" + ligne
    raise RuntimeError("aucune liste de segments dans la playlist maîtresse")


def dates_des_segments(texte: str) -> tuple[list[float], float]:
    """Les heures de prise de vue de chaque segment, et leur durée."""
    dates: list[float] = []
    duree = 7.0
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if ligne.startswith("#EXTINF:"):
            duree = float(ligne.split(":", 1)[1].rstrip(","))
        elif ligne.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            dates.append(datetime.fromisoformat(ligne.split(":", 1)[1]).timestamp())
    if not dates:
        raise RuntimeError("la playlist ne date pas ses segments")
    return dates, duree


def bord_du_direct(media_url: str) -> tuple[float, float]:
    """L'heure du dernier segment publié, et la durée d'un segment."""
    dates, duree = dates_des_segments(_lire(media_url))
    return dates[-1], duree


def depart(media_url: str, recul: int,
           maintenant=time.time, patiente=time.sleep) -> tuple[float, float]:
    """L'heure de la première image qu'on recevra, et la durée d'un segment.

    Reculer de N segments, c'est partir du N-ième avant la fin ; et comme les
    segments se suivent sans trou, son heure est celle du dernier moins N-1
    durées. C'est vérifié et non supposé : l'image que ffmpeg livre avec
    « -live_start_index -7 » est octet pour octet la première de ce segment-là.

    On attend s'il le faut que le segment courant soit jeune, pour que ffmpeg
    lise la même playlist que nous.
    """
    for _ in range(40):
        dates, duree = dates_des_segments(_lire(media_url))
        age = maintenant() - dates[-1]
        if age <= duree - MARGE_DEPART_S:
            recul = max(1, min(recul, len(dates)))
            return dates[-recul], duree
        patiente(PAS_D_ATTENTE_S)
    # Quarante essais et la playlist n'a jamais paru jeune : plutôt que de ne
    # pas démarrer, on part avec ce qu'on a. Un segment d'erreur possible vaut
    # mieux qu'une veille qui refuse de s'ouvrir.
    log.warning("La playlist n'a jamais paru fraîche : départ à une seconde près")
    dates, duree = dates_des_segments(_lire(media_url))
    recul = max(1, min(recul, len(dates)))
    return dates[-recul], duree
