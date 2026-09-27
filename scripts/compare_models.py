"""Compare les tailles de YOLO11 sur du mouvement réellement observé.

La question posée est précise : le modèle nano est muet sur 88 % des objets
vus de jour sur la route. Un modèle plus gros y changerait-il quelque chose,
et à quel prix sur un Raspberry ?

Le jeu d'essai vient de scripts/collect_crops.py, qui garde tout ce qui bouge
sans demander son avis au modèle.

    .venv/bin/python scripts/compare_models.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher.detect import YoloDetector  # noqa: E402

CROPS = ROOT / "data" / "crops"
# Les zones où la reconnaissance compte : le ciel est plein de bancs de
# brouillard qu'on ne cherche pas à nommer.
ZONES = {"road", "roundabout", "other", "slope"}


def main() -> None:
    carnet = json.loads((CROPS / "carnet.json").read_text())
    cas = [c for c in carnet if c["zone"] in ZONES and (CROPS / c["fichier"]).exists()]
    if not cas:
        print("Aucun morceau à comparer : lancer d'abord collect_crops.py")
        return
    print(f"{len(cas)} objets, zones {sorted({c['zone'] for c in cas})}\n")

    images = {c["fichier"]: cv2.imread(str(CROPS / c["fichier"])) for c in cas}

    for taille in ("n", "s", "m"):
        chemin = ROOT / "models" / f"yolo11{taille}.onnx"
        if not chemin.exists():
            continue
        moteur = YoloDetector(str(chemin))
        vus, confs, temps = 0, [], []
        noms: dict[str, int] = {}
        for c in cas:
            frame = images[c["fichier"]]
            if frame is None:
                continue
            debut = time.perf_counter()
            trouve = moteur.detect(frame, tuple(c["bbox"]))
            temps.append(time.perf_counter() - debut)
            if trouve:
                vus += 1
                meilleur = max(trouve, key=lambda d: d.conf)
                confs.append(meilleur.conf)
                noms[meilleur.cls] = noms.get(meilleur.cls, 0) + 1
        part = 100 * vus / len(cas)
        mediane = statistics.median(confs) if confs else 0.0
        print(f"yolo11{taille}  {chemin.stat().st_size / 1048576:5.1f} Mo   "
              f"reconnait {vus:3d}/{len(cas)} soit {part:5.1f} %   "
              f"confiance mediane {mediane:.2f}   "
              f"{1000 * statistics.median(temps):6.1f} ms par objet")
        if noms:
            print("           " + ", ".join(f"{k} x{v}" for k, v in
                                            sorted(noms.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
