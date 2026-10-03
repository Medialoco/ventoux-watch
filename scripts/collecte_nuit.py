"""Ramasse des passages de nuit pour pouvoir les reposer cent fois.

Le cadrage du détecteur a été réglé sur cent cinquante-cinq passages de jour.
Un sujet entouré de gris moyen au milieu d'une scène ensoleillée et le même
sujet entouré du même gris au milieu d'une scène noire ne sont pas le même
objet pour un réseau : le second a une tache claire autour de lui qui n'existe
nulle part dans ce qu'il a appris. Il faut donc remesurer à la nuit, et pour
remesurer il faut d'abord ramasser.

Garde l'image entière et la boîte, pas le gros plan : c'est l'image entière
qui permet d'essayer plusieurs cadrages sur le même passage.

    .venv/bin/python scripts/collecte_nuit.py --minutes 12
"""

from __future__ import annotations

import argparse
import json
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

LARGEUR, HAUTEUR = 1920, 1080
CHAUSSEE = {"road", "roundabout", "other"}


def images(url: str, combien: int):
    commande = ["ffmpeg", "-loglevel", "error", "-i", url,
                "-vf", f"fps=1,scale={LARGEUR}:{HAUTEUR}",
                "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
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
    parse.add_argument("--minutes", type=float, default=12.0)
    parse.add_argument("--vers", default="/tmp/nuit")
    parse.add_argument("--max", type=int, default=500)
    args = parse.parse_args()

    vers = Path(args.vers)
    vers.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    zones = load_zones(ROOT / cfg["zones"])
    mouvement = MotionDetector(zones)

    fiches = []
    debut = time.time()
    for numero, frame in enumerate(images(cfg["stream_url"], int(args.minutes * 60))):
        small, echelle = _resize_width(frame, mouvement.motion_width)
        mouvement._seen += 1
        if mouvement._seen <= mouvement.warmup_frames:
            mouvement.bg.apply(small, learningRate=-1)
            continue
        masque = _prepare_mask(mouvement.bg.apply(small, learningRate=0), zones,
                               small.shape[1], small.shape[0])
        gardees = []
        for tache in _blobs(masque, echelle):
            if tache["area_ratio"] < 0.0004:
                continue
            if assign_zone(tache["cx"], tache["cy"], zones) not in CHAUSSEE:
                continue
            gardees.append(tache)
        if not gardees:
            continue
        nom = f"{numero:05d}.jpg"
        cv2.imwrite(str(vers / nom), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        for tache in gardees:
            fiches.append({"image": nom, "bbox": list(tache["bbox"]),
                           "cx": tache["cx"], "cy": tache["cy"],
                           "aire": tache["area_ratio"]})
        if len(fiches) >= args.max:
            break
    (vers / "taches.json").write_text(json.dumps(fiches), encoding="utf-8")
    print(f"{len(fiches)} taches de chaussée ramassées en {(time.time()-debut)/60:.1f} min")
    print(f"dans {vers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
