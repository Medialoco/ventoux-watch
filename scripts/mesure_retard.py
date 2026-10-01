"""Mesure le décalage entre l'heure calculée par la rediffusion et l'heure de la veille.

La rediffusion date chaque image par un calcul : l'heure du dernier segment
publié, moins le recul, plus le compte des images. La veille, elle, date ce
qu'elle voit par l'horloge au moment où l'image lui arrive. Si les deux ne
disent pas la même chose, le rectangle se pose à côté — et un flux qui montre
la veille en train de se tromper alors qu'elle a eu raison est pire qu'un flux
sans rectangle.

La mesure n'a besoin ni de jour ni de circulation. Deux décodages de la même
image source rendent exactement les mêmes pixels : en tirant le flux deux
fois, une fois au bord du direct comme la veille et une fois en retard comme
la diffusion, on retrouve chaque image dans l'autre capture sans ambiguïté.
L'écart des deux datations est alors lu, et non estimé.

    .venv/bin/python -m scripts.mesure_retard --duree 90
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher.config import load_config  # noqa: E402
from watcher.stream import bord_du_direct, playlist_media  # noqa: E402

# Assez petit pour comparer vite, assez grand pour qu'une nuit calme ne rende
# pas deux images différentes identiques.
LARGEUR, HAUTEUR = 160, 90


def _tire(url: str, recul: int | None, duree_s: float, sortie: list) -> None:
    commande = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if recul is not None:
        commande += ["-live_start_index", str(-recul)]
    commande += ["-i", url, "-an", "-vf", f"scale={LARGEUR}:{HAUTEUR},format=gray",
                 "-f", "rawvideo", "-"]
    octets = LARGEUR * HAUTEUR
    process = subprocess.Popen(commande, stdout=subprocess.PIPE, bufsize=10 ** 7)
    debut = time.time()
    try:
        while time.time() - debut < duree_s:
            brut = process.stdout.read(octets)
            if len(brut) < octets:
                break
            sortie.append((time.time(), np.frombuffer(brut, np.uint8).reshape(HAUTEUR, LARGEUR)))
    finally:
        process.kill()


def mesure(cfg: dict, duree_s: float, recul: int) -> None:
    media = playlist_media(cfg["stream_url"])
    dernier, segment = bord_du_direct(media)
    depart = time.time()
    print(f"Segments de {segment:.2f} s, dernier publié il y a {depart - dernier:.1f} s")

    direct: list = []
    retard: list = []
    fils = [
        threading.Thread(target=_tire, args=(cfg["stream_url"], None, duree_s, direct)),
        threading.Thread(target=_tire, args=(cfg["stream_url"], recul, duree_s, retard)),
    ]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join()
    print(f"{len(direct)} images au bord du direct, {len(retard)} en retard")
    if not direct or not retard:
        print("Une des deux captures est vide : rien à mesurer.")
        return

    # L'heure que la rediffusion calculerait pour chaque image retardée.
    fps = cfg.get("stream_fps", 6)
    origine = dernier - (recul - 1) * segment
    calculees = [origine + i / fps for i in range(len(retard))]

    ecarts = []
    exacts = 0
    for quand_direct, image in direct:
        distances = [np.abs(image.astype(np.int16) - autre.astype(np.int16)).mean()
                     for _, autre in retard]
        meilleur = int(np.argmin(distances))
        if distances[meilleur] > 1.0:
            # Pas la même image source : l'appariement serait une invention.
            continue
        if distances[meilleur] < 0.01:
            exacts += 1
        ecarts.append(calculees[meilleur] - quand_direct)

    if not ecarts:
        print("Aucune image commune aux deux captures : le recul est trop grand "
              "ou le serveur a changé de segments.")
        return
    ecarts.sort()
    milieu = ecarts[len(ecarts) // 2]
    print(f"{len(ecarts)} images appariées, dont {exacts} au pixel près")
    print(f"écart médian : {milieu:+.2f} s")
    print(f"étendue : {ecarts[0]:+.2f} s à {ecarts[-1]:+.2f} s")
    print()
    if abs(milieu) < 0.5:
        print("L'heure calculée est celle de la veille : les rectangles tomberont juste.")
    else:
        print(f"Il faut retrancher {milieu:+.2f} s à l'heure calculée pour rejoindre la veille.")


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--duree", type=float, default=90.0)
    parseur.add_argument("--recul", type=int, default=2)
    args = parseur.parse_args(argv)
    mesure(load_config(ROOT), args.duree, args.recul)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
