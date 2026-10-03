"""La tache contre son cœur : ce que le détecteur lit sur l'une et sur l'autre.

La nuit, une tache de mouvement est surtout la flaque des phares sur le
bitume. Mesuré sur le journal du 3 octobre, entre vingt heures et cinq heures
du matin, pas un seul passage de chaussée n'a reçu la moindre lecture — zéro
sur quatre-vingts — pendant que la largeur moyenne des taches montait de 4,5 m
à plus de 10 m. Ce ne sont pas des voitures de dix mètres : c'est leur lumière.

Ce script lit la webcam en direct et compare, pour chaque tache, ce que le
détecteur répond sur la boîte entière et sur la boîte du cœur — la partie où
le décor d'avant a vraiment disparu. Il ne touche à rien.

    .venv/bin/python scripts/mesure_coeur.py --minutes 8
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

import watcher.detect as D  # noqa: E402
from watcher.config import load_config  # noqa: E402
from watcher.geometry import assign_zone, load_zones  # noqa: E402
from watcher.motion import MotionDetector, _blobs, _coeur, _prepare_mask, _resize_width  # noqa: E402
from watcher.scenemap import SceneMap  # noqa: E402

LARGEUR, HAUTEUR = 1920, 1080
CHAUSSEE = {"road", "roundabout", "other"}


def images(url: str, combien: int):
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


def lis(det: D.YoloDetector, frame: np.ndarray, boite) -> tuple[str, float]:
    lus = det.detect(frame, bbox=boite)
    if not lus:
        return "rien", 0.0
    meilleur = max(lus, key=lambda d: d.conf)
    return meilleur.cls, meilleur.conf


def main() -> int:
    parse = argparse.ArgumentParser(description=__doc__)
    parse.add_argument("--minutes", type=float, default=8.0)
    args = parse.parse_args()

    cfg = load_config()
    zones = load_zones(ROOT / cfg["zones"])
    carte = SceneMap.load(ROOT / "config" / "scene.json")
    mouvement = MotionDetector(zones)
    det = D.YoloDetector(str(ROOT / "models" / "yolo11n.onnx"))

    compte = collections.Counter()
    lignes = []
    debut = time.time()
    for frame in images(cfg["stream_url"], int(args.minutes * 60)):
        small, echelle = _resize_width(frame, mouvement.motion_width)
        mouvement._seen += 1
        if mouvement._seen <= mouvement.warmup_frames:
            mouvement.bg.apply(small, learningRate=-1)
            continue
        fond = mouvement.bg.getBackgroundImage()
        masque = mouvement.bg.apply(small, learningRate=0)
        h, l = small.shape[:2]
        masque = _prepare_mask(masque, zones, l, h)
        for tache in _blobs(masque, echelle):
            if tache["area_ratio"] < 0.0004:
                continue
            if assign_zone(tache["cx"], tache["cy"], zones) not in CHAUSSEE:
                continue
            x, y, w, hb = tache["bbox"]
            # Les deux vues du même endroit, à la taille réduite où le fond vit.
            rx, ry = int(x * echelle), int(y * echelle)
            rw, rh = max(1, int(w * echelle)), max(1, int(hb * echelle))
            x0, y0 = max(0, rx), max(0, ry)
            x1, y1 = min(l, rx + rw), min(h, ry + rh)
            if x1 - x0 < 3 or y1 - y0 < 3 or fond is None:
                continue
            maintenant = cv2.cvtColor(small[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
            avant = cv2.cvtColor(fond[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
            coeur = _coeur(maintenant, avant)
            compte["taches"] += 1
            if coeur is None:
                compte["sans coeur"] += 1
                continue
            cx, cy, cw, ch = coeur
            petite = (int((x0 + cx) / echelle), int((y0 + cy) / echelle),
                      max(1, int(cw / echelle)), max(1, int(ch / echelle)))
            large_avant = carte.metres_across((x / LARGEUR, y / HAUTEUR, w / LARGEUR, hb / HAUTEUR))
            large_apres = carte.metres_across((petite[0] / LARGEUR, petite[1] / HAUTEUR,
                                               petite[2] / LARGEUR, petite[3] / HAUTEUR))
            av_cls, av_conf = lis(det, frame, (x, y, w, hb))
            ap_cls, ap_conf = lis(det, frame, petite)
            if av_cls == "rien" and ap_cls != "rien":
                compte["GAGNÉ : muet avant, lu après"] += 1
            elif av_cls != "rien" and ap_cls == "rien":
                compte["PERDU : lu avant, muet après"] += 1
            elif av_cls != "rien":
                compte["lu dans les deux cas"] += 1
            else:
                compte["muet dans les deux cas"] += 1
            lignes.append((large_avant, large_apres, w, hb, petite[2], petite[3],
                           av_cls, av_conf, ap_cls, ap_conf))

    ecoule = (time.time() - debut) / 60
    print(f"{ecoule:.1f} min de webcam")
    for cle, valeur in compte.most_common():
        print(f"  {cle:30} {valeur}")
    if lignes:
        print()
        print(f"{'large avant':>12} {'après':>8} {'px avant':>12} {'px après':>12}  "
              f"{'lu sur la tache':>22}  {'lu sur le cœur':>22}")
        for a, b, w, hb, cw, ch, ac, aconf, pc, pconf in lignes[-60:]:
            print(f"{a:11.1f}m {b:7.1f}m {w:5}x{hb:<6} {cw:5}x{ch:<6}  "
                  f"{ac + ' ' + format(aconf, '.2f'):>22}  {pc + ' ' + format(pconf, '.2f'):>22}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
