"""Ce que le plancher de taille laisse passer, et ce qu'il jette.

L'étage mouvement refuse toute tache occupant moins de 0,0004 de l'aire de
l'image. C'est une part du cadrage, pas une taille : au rond-point elle vaut
soixante-dix centimètres de large, sur la route quarante mètres plus loin elle
en vaut un et demi, et sur la pente d'en face quinze. Un chien au rond-point
est pile sur la ligne, et c'est pour ça qu'on en voit un sur deux.

Ce script lit la webcam en direct, relève chaque tache que la soustraction de
fond produit — y compris celles que le plancher écarte — et dit ce qu'elles
mesureraient au sol. Il ne touche à rien : il regarde.

    .venv/bin/python scripts/mesure_plancher.py --minutes 6
"""

from __future__ import annotations

import argparse
import collections
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher.config import load_config  # noqa: E402
from watcher.geometry import assign_zone, load_zones  # noqa: E402
from watcher.motion import MotionDetector, _blobs, _prepare_mask, _resize_width  # noqa: E402
from watcher.scenemap import SceneMap  # noqa: E402

PLANCHER = 0.0004
# Le plus petit animal qu'on veuille nommer, et ce qu'il faut de pixels pour le lire.
PLUS_PETIT_M = 0.3
LISIBLE = 12
LARGEUR = 1920
HAUTEUR = 1080


def images(url: str, combien: int):
    """Une image par seconde, en brut, telle que le veilleur les reçoit."""
    commande = [
        "ffmpeg", "-loglevel", "error", "-i", url,
        "-vf", f"fps=1,scale={LARGEUR}:{HAUTEUR}",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ]
    taille = LARGEUR * HAUTEUR * 3
    proc = subprocess.Popen(commande, stdout=subprocess.PIPE)
    try:
        for _ in range(combien):
            brut = proc.stdout.read(taille)
            if len(brut) < taille:
                return
            yield np.frombuffer(brut, np.uint8).reshape(HAUTEUR, LARGEUR, 3)
    finally:
        proc.kill()


def main() -> int:
    parse = argparse.ArgumentParser(description=__doc__)
    parse.add_argument("--minutes", type=float, default=6.0)
    args = parse.parse_args()

    cfg = load_config()
    carte = SceneMap.load(ROOT / "config" / "scene.json")
    zones = load_zones(ROOT / cfg["zones"])
    det = MotionDetector(zones)

    combien = int(args.minutes * 60)
    sous = collections.Counter()
    exemples = []
    taches = 0
    vues = 0
    debut = time.time()
    for frame in images(cfg["stream_url"], combien):
        vues += 1
        small, echelle = _resize_width(frame, det.motion_width)
        det._seen += 1
        if det._seen <= det.warmup_frames:
            det.bg.apply(small, learningRate=-1)
            continue
        masque = det.bg.apply(small, learningRate=0)
        hauteur, largeur = small.shape[:2]
        masque = _prepare_mask(masque, zones, largeur, hauteur)
        for tache in _blobs(masque, echelle):
            taches += 1
            zone = assign_zone(tache["cx"], tache["cy"], zones)
            if zone == "sky":
                continue
            x, y, w, h = tache["bbox"]
            boite = (x / LARGEUR, y / HAUTEUR, w / LARGEUR, h / HAUTEUR)
            large = carte.metres_across(boite)
            haut = carte.metres_tall(boite)
            passe = tache["area_ratio"] >= PLANCHER
            sous["gardée" if passe else "jetée"] += 1
            surface = carte.surface_at(tache["cx"], tache["cy"])
            if not passe:
                sous[f"jetée · {surface or 'sol inconnu'}"] += 1
                # La règle qu'on envisage, et qui n'a qu'un seul nombre libre :
                # il faut LISIBLE pixels pour qu'une chose soit lisible. Là où
                # le plus petit animal qu'on veuille nommer en fait autant, le
                # plancher devient sa propre taille. Là où il n'en fait pas
                # assez — plus loin que trente mètres ici — le relâcher
                # n'apporterait rien à lire et seulement des arbres qui bougent,
                # donc on n'y touche pas.
                par_x, par_y = carte.share_per_metre(tache["cx"], tache["cy"])
                px_large = PLUS_PETIT_M * par_x * LARGEUR
                px_haut = PLUS_PETIT_M * par_y * HAUTEUR
                if min(px_large, px_haut) >= LISIBLE:
                    seuil = (px_large * px_haut) / float(LARGEUR * HAUTEUR)
                    if tache["area_ratio"] >= seuil:
                        sous["RETENUE : assez près pour qu'un chat soit lisible"] += 1
                        exemples.append((round(large, 2), round(haut, 2), zone, surface,
                                         w, h, round(tache["area_ratio"], 6)))

    ecoule = time.time() - debut
    print(f"{vues} images lues en {ecoule / 60:.1f} min, {taches} taches hors ciel")
    for cle, valeur in sous.most_common():
        print(f"  {cle:46} {valeur}")
    if exemples:
        print()
        print("Ce qu'on jetait et qui tient dans la fourchette :")
        print(f"{'large':>7} {'haut':>7} {'zone':12} {'surface':12} {'px (1920)':>12} {'part':>9}")
        for large, haut, zone, surface, w, h, part in sorted(exemples, reverse=True)[:40]:
            print(f"{large:6.2f}m {haut:6.2f}m {zone:12} {str(surface):12} {w:5}x{h:<5} {part:9.6f}")
        par_minute = sous["RETENUE : assez près pour qu'un chat soit lisible"] / max(ecoule / 60, 0.01)
        print()
        print(f"Soit {par_minute:.1f} regards de plus par minute à donner au détecteur,")
        print(f"à 0,334 s le regard : {par_minute * 0.334 / 60:.1%} d'un cœur du Raspberry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
