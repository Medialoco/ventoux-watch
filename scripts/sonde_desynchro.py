#!/usr/bin/env python3
"""Mesure de combien le son versé prend de l'avance sur l'image diffusée.

Le crédit musical est écrit sur l'image à partir du compte d'octets déjà
remis à ffmpeg. Mais ffmpeg ne diffuse pas un octet au moment où il le reçoit :
il le range dans la file de son entrée, puis dans l'encodeur. Pendant ce
temps-là l'image, elle, porte déjà le nom du morceau correspondant.

L'écart cherché est donc, au même instant : « secondes de son remises » moins
« secondes d'image remises ». On reconstruit ici les deux tuyaux de la
diffusion, à l'identique, et on le lit.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from watcher.stream import ECHANTILLONS_S, OCTETS_PAR_ECHANTILLON, VOIES  # noqa: E402

DEBIT = ECHANTILLONS_S * VOIES * OCTETS_PAR_ECHANTILLON
LARGEUR, HAUTEUR, IMAGES_S = 1280, 720, 6
TRANCHE = 16384


def main() -> int:
    lecture, ecriture = os.pipe()
    sortie = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-thread_queue_size", "512",
         "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{LARGEUR}x{HAUTEUR}", "-r", str(IMAGES_S), "-i", "pipe:0",
         "-thread_queue_size", "512",
         "-f", "s16le", "-ar", str(ECHANTILLONS_S), "-ac", str(VOIES),
         "-i", f"pipe:{lecture}",
         "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
         "-pix_fmt", "yuv420p", "-b:v", "1800k", "-maxrate", "1800k",
         "-bufsize", "4M", "-r", "15", "-g", "30",
         "-c:a", "aac", "-b:a", "128k",
         "-f", "flv", "/dev/null"],
        stdin=subprocess.PIPE, pass_fds=(lecture,))
    os.close(lecture)

    verses = [0]
    fini = threading.Event()

    def verseur() -> None:
        # Exactement la boucle de _verse_le_son : rien ne règle le débit,
        # l'écriture bloque quand ffmpeg n'absorbe plus.
        while not fini.is_set():
            pose = 0
            morceau = b"\0" * TRANCHE
            while pose < len(morceau) and not fini.is_set():
                try:
                    pose += os.write(ecriture, morceau[pose:])
                except (BrokenPipeError, OSError):
                    return
            verses[0] += TRANCHE

    fil = threading.Thread(target=verseur, daemon=True)
    fil.start()

    image = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8).tobytes()
    debut = time.time()
    vues = 0
    print(f"{'temps':>7} {'son versé':>11} {'image':>9} {'avance du son':>15}")
    try:
        while time.time() - debut < 120:
            attente = debut + vues / IMAGES_S - time.time()
            if attente > 0:
                time.sleep(attente)
            sortie.stdin.write(image)
            vues += 1
            if vues % (IMAGES_S * 10) == 0:
                son = verses[0] / DEBIT
                img = vues / IMAGES_S
                print(f"{time.time() - debut:7.1f} {son:9.2f} s {img:7.2f} s "
                      f"{son - img:+13.2f} s")
    finally:
        fini.set()
        try:
            os.close(ecriture)
        except OSError:
            pass
        if sortie.stdin is not None:
            sortie.stdin.close()
        sortie.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
