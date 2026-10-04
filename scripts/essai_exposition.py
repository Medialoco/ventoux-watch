#!/usr/bin/env python3
"""Rejoue les mêmes passages sous plusieurs expositions, et compte ce qui se lit.

La nuit, le détecteur ne rend rien. Mesuré sur les passages du 3 octobre : de
jour, soixante-deux pour cent des taches de taille plausible reçoivent au moins
une lecture ; la nuit, neuf. L'explication tenait d'abord au cadrage, mais une
tache de la bonne taille physique échoue tout autant — ce n'est donc pas le
cadrage, c'est que le gros plan part au modèle tel quel, et qu'un gros plan de
nuit est un carré noir.

Un réseau entraîné sur des photographies n'a jamais vu de nuit, parce qu'une
photographie est exposée : le photographe ouvre, ralentit ou pousse les ISO
jusqu'à ce que la scène tombe au milieu de l'échelle. Une webcam à 1 i/s ne fait
rien de tel. On lui rend donc ce que l'appareil photo aurait fait.

On compare ici plusieurs façons de le faire, sur les mêmes images et les mêmes
taches, parce que c'est la seule manière honnête de dire qu'on a amélioré
quelque chose.

    .venv/bin/python scripts/essai_exposition.py /tmp/nuit
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher.detect import SUJET_PART, YoloDetector, _cadre, _letterbox, _nms, _parse  # noqa: E402

VEHICULES = {"car", "truck", "bus", "motorcycle", "bicycle"}


def _luminance(vue: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(vue, cv2.COLOR_BGR2GRAY)


def brut(vue: np.ndarray) -> np.ndarray:
    return vue


def gamma(vue: np.ndarray, cible: float = 0.45) -> np.ndarray:
    """Amène la luminance médiane du gros plan là où le modèle l'attend.

    Une puissance et non un gain : un gain multiplie tout, donc il écrase les
    phares en blanc pur avant d'avoir sorti la carrosserie du noir. Une
    puissance relève les ombres en laissant les hautes lumières où elles sont,
    ce qui est exactement ce que fait une courbe de tonalité.

    Sans seuil, et c'est tout l'intérêt : de jour la médiane est déjà sur la
    cible, donc l'exposant vaut un et la fonction ne fait rien. Elle ne se
    déclenche pas, elle s'annule.
    """
    m = float(np.median(_luminance(vue))) / 255.0
    if m <= 0.004 or m >= 0.996:
        return vue
    g = float(np.log(cible) / np.log(m))
    table = (np.linspace(0, 1, 256) ** g * 255.0).clip(0, 255).astype(np.uint8)
    return cv2.LUT(vue, table)


def clahe(vue: np.ndarray) -> np.ndarray:
    """Égalisation locale sur la clarté, la couleur laissée tranquille."""
    lab = cv2.cvtColor(vue, cv2.COLOR_BGR2LAB)
    outil = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab[:, :, 0] = outil.apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def gamma_clahe(vue: np.ndarray) -> np.ndarray:
    return clahe(gamma(vue))


def egalise(vue: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(vue, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.equalizeHist(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


TRAITEMENTS = {"brut": brut, "gamma": gamma, "clahe": clahe,
               "gamma+clahe": gamma_clahe, "égalisé": egalise}


def lectures(detecteur: YoloDetector, vue: np.ndarray) -> list[tuple[str, float]]:
    blob, _, _ = _letterbox(vue, 640)
    raw = detecteur.session.run(None, {detecteur.input_name: blob})[0]
    return [(nom, conf) for *_, conf, nom in _nms(_parse(raw))]


def main() -> int:
    parse = argparse.ArgumentParser(description=__doc__)
    parse.add_argument("corpus")
    parse.add_argument("--modele", default=str(ROOT / "models" / "yolo11n.onnx"))
    args = parse.parse_args()

    corpus = Path(args.corpus)
    fiches = json.loads((corpus / "taches.json").read_text(encoding="utf-8"))
    detecteur = YoloDetector(args.modele)
    if not detecteur.ready:
        print("modèle introuvable", file=sys.stderr)
        return 1

    cache: dict[str, np.ndarray] = {}
    compte = {nom: {"lu": 0, "vehicule": 0, "conf": []} for nom in TRAITEMENTS}
    mediane_brute = []
    for fiche in fiches:
        if fiche["image"] not in cache:
            cache.clear()
            cache[fiche["image"]] = cv2.imread(str(corpus / fiche["image"]))
        frame = cache[fiche["image"]]
        if frame is None:
            continue
        _, _, vue = _cadre(frame, tuple(fiche["bbox"]), SUJET_PART)
        if vue.size == 0:
            continue
        mediane_brute.append(float(np.median(_luminance(vue))))
        for nom, traite in TRAITEMENTS.items():
            trouve = lectures(detecteur, traite(vue))
            if trouve:
                compte[nom]["lu"] += 1
                compte[nom]["conf"].append(max(c for _, c in trouve))
            if any(n in VEHICULES for n, _ in trouve):
                compte[nom]["vehicule"] += 1

    total = len(mediane_brute)
    if not total:
        print("aucune tache exploitable", file=sys.stderr)
        return 1
    print(f"{total} taches, luminance médiane du gros plan brut : "
          f"{np.median(mediane_brute):.0f}/255\n")
    print(f"{'traitement':14} {'une lecture':>14} {'un véhicule':>14} {'confiance moy.':>15}")
    for nom in TRAITEMENTS:
        c = compte[nom]
        moy = float(np.mean(c["conf"])) if c["conf"] else 0.0
        print(f"{nom:14} {c['lu']:5} ({c['lu']/total*100:3.0f} %) "
              f"{c['vehicule']:5} ({c['vehicule']/total*100:3.0f} %) {moy:14.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
