#!/usr/bin/env python3
"""La ligne de crête, relevée dans le modèle de terrain et confrontée à l'image.

Pour chaque direction, on marche sur le sol en s'éloignant et on garde le plus
grand angle rencontré : une butte proche peut cacher un sommet lointain, et
seul le plus grand compte. C'est l'horizon tel que le relief le donne.

Mais un horizon calculé n'a de valeur que s'il tombe sur celui qu'on voit, et
le nôtre ne le fait pas partout : il colle au milieu du cadre et s'en écarte
jusqu'à huit pour cent de la hauteur d'image dans le quart droit. Aucun
déplacement de la pose ne rattrape cet écart — ni cap, ni site, ni roulis, ni
champ, ni courbure d'objectif — et le terrain, lui, est juste à trois mètres
près. Ce qui reste est une faiblesse du modèle d'objectif, loin de l'axe et
haut dans l'image, c'est-à-dire exactement là où vit l'horizon.

On ne trace donc que ce qu'on sait. Le critère est physique et vaut pour
n'importe quelle caméra :

    le sol nu ne peut jamais se voir plus haut que la crête qu'on observe,
    et il peut se voir plus bas d'au plus la hauteur de ce qui s'y dresse.

Un arbre, un pylône, un chalet montent la ligne d'horizon ; rien ne la
descend. On marche donc deux fois sur le relief — une fois au sol, une fois
avec une canopée partout — et on ne garde que les directions où la crête
mesurée dans l'image tombe entre les deux. Les bandes noires, où aucune image
ne peut confirmer quoi que ce soit, ne sont prolongées qu'à partir d'un pan
déjà corroboré, et seulement sur la largeur d'une bande.

Rien ici ne connaît le Ventoux.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from watcher import frustum  # noqa: E402
from watcher.frustum import Pose  # noqa: E402
from watcher.stream import fenetre  # noqa: E402
from scripts.cale_horizon import CANOPEE_M, Relief, fourchette, releve_image  # noqa: E402

PAS_DEG = 0.12
# La toile de référence : celle du flux, pas celle de cette webcam-ci.
# fenetre() dit où l'image se pose ; hors de cette fenêtre ce sont les
# bandes noires, et on n'y prolonge une crête que si l'image l'a déjà
# confirmée. Recalculé, pas écrit en dur : une autre carte, un autre
# bandeau, et les nombres changent tout seuls.
TOILE_REF = (1600, 900)
TOILE_CAM = (1080, 1920)
# Deux points voisins qui sautent de plus que ça ne sont pas la même crête :
# c'est un sommet lointain qui en remplace un proche, et le trait doit se
# couper là plutôt que de tomber à la verticale sur rien.
SAUT = 0.05
# Un pan de moins de cinq pour cent de la toile ne se lit pas comme un relief,
# seulement comme une rayure.
PAN_MINI = 0.05


def toile_en_camera(forme: tuple[int, int] = TOILE_CAM,
                    largeur: int = TOILE_REF[0],
                    hauteur: int = TOILE_REF[1]) -> tuple[float, float, float, float]:
    """Les bords de la toile, en parts du cadre caméra.

    (0, 0) à (1, 1) est l'image. En dehors, les bandes. Dérivé de fenetre(),
    donc d'une géométrie d'écran, pas d'un cadrage trouvé sur le Ventoux.
    """
    x, y, large, haut = fenetre(forme, largeur, hauteur)
    return (-x / large, (largeur - x) / large,
            -y / haut, (hauteur - y) / haut)


def _point(pose: Pose, lat0: float, lon0: float, cap: float, angle: float, distance: float):
    est = math.sin(math.radians(cap)) * distance
    nord = math.cos(math.radians(cap)) * distance
    lat = lat0 + nord / frustum.EARTH_M_PER_DEG_LAT
    lon = lon0 + est / (frustum.EARTH_M_PER_DEG_LON * math.cos(math.radians(lat0)))
    hauteur = pose.ele + pose.height_m + math.tan(math.radians(angle)) * distance
    return frustum.project(pose, lat, lon, hauteur)


def corrobore(pose, lat0, lon0, table, vu) -> list[tuple[float, float, bool]]:
    """Chaque cap du balayage, sa place dans l'image, et si l'image le confirme.

    Hors du cadre il n'y a rien à confirmer : la réponse est None, et c'est au
    découpage en pans de décider ce qu'il en fait.
    """
    largeur = len(vu)
    dehors = []
    bord_g, bord_d, bord_h, bord_b = toile_en_camera()
    for cap, a_nu, d_nu, a_haut, d_haut in table:
        bas = _point(pose, lat0, lon0, cap, a_nu, d_nu)
        if bas is None:
            continue
        x, y = bas
        if not (bord_g <= x <= bord_d and bord_h <= y <= bord_b):
            continue
        if not (0.0 <= x < 1.0):
            dehors.append((x, y, None))
            continue
        mesure = vu[min(largeur - 1, int(x * largeur))]
        if math.isnan(mesure):
            dehors.append((x, y, None))
            continue
        haut = _point(pose, lat0, lon0, cap, a_haut, d_haut)
        plafond = haut[1] if haut is not None else y
        dehors.append((x, y, bool(plafond <= mesure <= y)))
    return sorted(dehors)


def pans(points) -> list[list[list[float]]]:
    """Découper en traits continus, en ne gardant que ce que l'image confirme.

    Une direction hors cadre est rattachée au pan en cours s'il y en a un :
    c'est le prolongement dans la bande noire d'une crête déjà corroborée.
    Elle n'ouvre jamais un pan à elle seule.
    """
    sortie, pan = [], []
    for x, y, bon in points:
        if bon is False:
            if len(pan) > 1:
                sortie.append(pan)
            pan = []
            continue
        if bon is None and not pan:
            continue
        if pan and abs(y - pan[-1][1]) > SAUT:
            if len(pan) > 1:
                sortie.append(pan)
            pan = []
        pan.append([round(x, 5), round(y, 5)])
    if len(pan) > 1:
        sortie.append(pan)
    return [p for p in sortie if p[-1][0] - p[0][0] >= PAN_MINI]


def main() -> int:
    chemins = [Path(nom) for nom in sys.argv[1:]]
    if not chemins:
        raise SystemExit("Donne au moins une image dégagée en argument.")

    relief_brut = json.loads((RACINE / "config" / "relief.json").read_text(encoding="utf-8"))
    p = relief_brut["pose"]
    pose = Pose(lat=p["lat"], lon=p["lon"], ele=p["ele"], yaw=p["yaw"],
                pitch=p["pitch"], hfov=p["hfov"], height_m=p["height_m"],
                roll=p.get("roll", 0.0), k1=p.get("k1", 0.0))
    relief = Relief(relief_brut["terrain"])

    vu = releve_image(chemins)
    table = fourchette(relief, pose.yaw)
    points = corrobore(pose, p["lat"], p["lon"], table, vu)
    dedans = [b for _, _, b in points if b is not None]
    print(f"Crête : {len(points)} directions, {sum(dedans)}/{len(dedans)} confirmées par l'image"
          f" (canopée de {CANOPEE_M:.0f} m)")

    traits = pans(points)
    total = sum(len(trait) for trait in traits)
    print(f"        {len(traits)} pans retenus, {total} points")
    for i, trait in enumerate(traits):
        xs = [pt[0] for pt in trait]
        ys = [pt[1] for pt in trait]
        print(f"  pan {i}: x {min(xs):+.3f}..{max(xs):+.3f}  y {min(ys):+.3f}..{max(ys):+.3f}"
              f"  ({len(trait)} pts)")

    chemin = RACINE / "config" / "scene.json"
    scene = json.loads(chemin.read_text(encoding="utf-8"))
    scene["crete"] = {"reach_m": relief.portee, "canopee_m": CANOPEE_M, "pans": traits}
    chemin.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Écrit dans {chemin.relative_to(RACINE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
