#!/usr/bin/env python3
"""Caler la vue sur l'horizon, qui vaut mille repères.

Trois amers pointés à la main ne suffisent pas à fixer six inconnues : le
calage les fait tomber juste et se trompe ailleurs, sans rien pour le dire.
L'horizon, lui, donne un point par colonne de l'image, et il est gratuit.

La règle est physique et tient pour n'importe quelle caméra :

    le sol nu ne peut jamais se voir plus haut que la crête qu'on observe,
    et il peut se voir plus bas d'au plus la hauteur de ce qui s'y dresse.

Un arbre, un pylône, un chalet montent la ligne d'horizon ; rien ne la
descend. On marche donc deux fois sur le relief — une fois au sol, une fois
avec une canopée partout — et on demande que la crête mesurée dans l'image
tombe entre les deux. Ce qui sort de la fourchette coûte, ce qui est dedans
est gratuit : on n'invente pas une précision qu'on n'a pas.

Rien ici ne connaît le Ventoux.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from watcher import frustum  # noqa: E402
from watcher.frustum import Pose  # noqa: E402

# Ce qui se dresse sur une crête et qu'aucun modèle de terrain ne porte :
# un pin mûr, un pylône de téléski, un chalet. Vingt mètres couvrent les trois.
CANOPEE_M = 20.0
PAS_M = 20.0
DEPART_M = 120.0
PAS_DEG = 0.25
BALAYAGE_DEG = 60.0
# Le ciel est uni en haut de colonne ; la crête est la première chute franche.
# Médiane, pas moyenne : un soleil dans les douze pixels du haut tirerait
# la référence vers le blanc, et le ciel lui-même passerait pour une crête.
# Et la chute doit tenir : un fil, un oiseau, un flare ne font pas un versant.
CHUTE = 28.0
HAUT_DE_COLONNE = 12
CHUTE_TIENT = 5
# Un amer pointé à la main vaut largement une colonne d'image parmi mille.
POIDS_AMER = 400.0


class Relief:
    """Le sol autour de la caméra, en mètres au-dessus de l'œil."""

    def __init__(self, bloc: dict):
        self.pas = float(bloc["step_m"])
        self.portee = float(bloc["reach_m"])
        self.grille = np.array(bloc["grid"], dtype=np.float64)
        self.cote = self.grille.shape[0]

    def hauteur(self, est: float, nord: float) -> float | None:
        colonne = (est + self.portee) / self.pas
        ligne = (self.portee - nord) / self.pas
        if not (0 <= colonne <= self.cote - 1 and 0 <= ligne <= self.cote - 1):
            return None
        c0 = min(self.cote - 2, int(colonne))
        l0 = min(self.cote - 2, int(ligne))
        fc, fl = colonne - c0, ligne - l0
        haut = self.grille[l0, c0] * (1 - fc) + self.grille[l0, c0 + 1] * fc
        bas = self.grille[l0 + 1, c0] * (1 - fc) + self.grille[l0 + 1, c0 + 1] * fc
        return float(haut * (1 - fl) + bas * fl)

    def horizon(self, cap: float, pousse_m: float = 0.0) -> tuple[float, float] | None:
        """Le plus grand angle rencontré en s'éloignant, et sa distance."""
        est = math.sin(math.radians(cap))
        nord = math.cos(math.radians(cap))
        angle, loin = None, 0.0
        distance = DEPART_M
        while distance <= self.portee:
            monte = self.hauteur(est * distance, nord * distance)
            if monte is None:
                break
            vu = math.degrees(math.atan2(monte + pousse_m, distance))
            if angle is None or vu > angle:
                angle, loin = vu, distance
            distance += PAS_M
        return None if angle is None else (angle, loin)


def releve_image(chemins: list[Path]) -> np.ndarray:
    """La crête vue, en y normalisé par colonne, médiane sur plusieurs images.

    Plusieurs images parce qu'un nuage posé sur une épaule déplace la ligne ;
    la médiane écarte l'accident sans rien lisser de ce qui est stable.
    """
    releves = []
    for chemin in chemins:
        image = cv2.imread(str(chemin))
        if image is None:
            continue
        hauteur, largeur = image.shape[:2]
        gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        ligne = np.full(largeur, np.nan)
        for colonne in range(largeur):
            pile = gris[:, colonne]
            ref = float(np.median(pile[:HAUT_DE_COLONNE]))
            sous = pile < ref - CHUTE
            # La première plage assez longue pour être un versant, pas un fil.
            tient = np.convolve(sous.astype(np.uint8),
                                np.ones(CHUTE_TIENT, np.uint8), mode="valid")
            debut = np.nonzero(tient >= CHUTE_TIENT)[0]
            if len(debut):
                ligne[colonne] = debut[0] / hauteur
        releves.append(ligne)
    if not releves:
        raise SystemExit("Aucune image lisible pour relever la crête.")
    return np.nanmedian(np.array(releves), axis=0)


def fourchette(relief: Relief, yaw: float) -> list[tuple[float, float, float, float, float]]:
    """Par cap : angle du sol nu, sa distance, angle avec la canopée, sa distance.

    Calculé une fois pour toutes : la marche sur le relief ne dépend pas de
    l'orientation de la caméra, seulement de l'endroit où elle est posée.
    """
    table = []
    cap = yaw - BALAYAGE_DEG
    while cap <= yaw + BALAYAGE_DEG:
        nu = relief.horizon(cap)
        haut = relief.horizon(cap, CANOPEE_M)
        if nu is not None and haut is not None:
            table.append((cap, nu[0], nu[1], haut[0], haut[1]))
        cap += PAS_DEG
    return table


def _point(pose: Pose, lat0: float, lon0: float, cap: float, angle: float, distance: float):
    est = math.sin(math.radians(cap)) * distance
    nord = math.cos(math.radians(cap)) * distance
    lat = lat0 + nord / frustum.EARTH_M_PER_DEG_LAT
    lon = lon0 + est / (frustum.EARTH_M_PER_DEG_LON * math.cos(math.radians(lat0)))
    hauteur = pose.ele + pose.height_m + math.tan(math.radians(angle)) * distance
    return frustum.project(pose, lat, lon, hauteur)


def cout(pose: Pose, table, vu: np.ndarray, marques: list[dict],
         lat0: float, lon0: float) -> float:
    """Ce que coûte une pose : ses amers, puis tout ce qui sort de la fourchette."""
    total = 0.0
    for marque in marques:
        place = frustum.project(pose, marque["lat"], marque["lon"], marque["ele"])
        if place is None:
            return 1e9
        total += POIDS_AMER * ((place[0] - marque["x"]) ** 2 + (place[1] - marque["y"]) ** 2)

    largeur = len(vu)
    for cap, a_nu, d_nu, a_haut, d_haut in table:
        bas = _point(pose, lat0, lon0, cap, a_nu, d_nu)
        if bas is None:
            continue
        if not (0.0 <= bas[0] <= 1.0):
            continue
        colonne = min(largeur - 1, max(0, int(bas[0] * largeur)))
        mesure = vu[colonne]
        if math.isnan(mesure):
            continue
        haut = _point(pose, lat0, lon0, cap, a_haut, d_haut)
        plafond = haut[1] if haut is not None else bas[1]
        # Le sol nu sous la crête mesurée : impossible, la montagne manquerait.
        if bas[1] < mesure:
            total += (mesure - bas[1]) ** 2
        # Au-dessus de ce que la canopée explique : il manque de la montagne.
        elif mesure < plafond:
            total += (plafond - mesure) ** 2
    return total


def affine(pose: Pose, table, vu, marques, lat0, lon0) -> Pose:
    pas = {"yaw": 6.0, "pitch": 6.0, "roll": 5.0, "hfov": 16.0, "k1": 0.14}
    meilleur, score = pose, cout(pose, table, vu, marques, lat0, lon0)
    for _ in range(9):
        for _balayage in range(40):
            bouge = False
            for cle, taille in pas.items():
                for sens in (1, -1):
                    essai = frustum._shift(meilleur, cle, sens * taille)
                    valeur = cout(essai, table, vu, marques, lat0, lon0)
                    if valeur < score - 1e-12:
                        meilleur, score, bouge = essai, valeur, True
            if not bouge:
                break
        pas = {cle: taille / 2.5 for cle, taille in pas.items()}
    return meilleur


def ecrit_pose(pose: Pose) -> None:
    """Écrit la pose calée là où le flux et le relief la lisent.

    Sans ça le script ne faisait que parler : on calait, on relançait, et
    la caméra n'avait rien appris. Les deux fichiers portent la même pose —
    c'est le même œil.
    """
    champs = pose.as_dict()
    for chemin in (RACINE / "config" / "scene.json", RACINE / "config" / "relief.json"):
        brut = json.loads(chemin.read_text(encoding="utf-8"))
        actuel = brut.get("pose") or {}
        actuel.update(champs)
        brut["pose"] = actuel
        chemin.write_text(json.dumps(brut, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        print(f"Écrit dans {chemin.relative_to(RACINE)}")


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--ecrit"]
    ecrire = "--ecrit" in sys.argv[1:]
    relief_brut = json.loads((RACINE / "config" / "relief.json").read_text(encoding="utf-8"))
    config = json.loads((RACINE / "config" / "config.json").read_text(encoding="utf-8"))
    marques = (config.get("camera") or {}).get("marks") or []
    p = relief_brut["pose"]
    depart = Pose(lat=p["lat"], lon=p["lon"], ele=p["ele"], yaw=p["yaw"],
                  pitch=p["pitch"], hfov=p["hfov"], height_m=p["height_m"],
                  roll=p.get("roll", 0.0), k1=p.get("k1", 0.0))
    relief = Relief(relief_brut["terrain"])

    chemins = [Path(nom) for nom in args]
    if not chemins:
        raise SystemExit("Donne au moins une image dégagée en argument.")
    vu = releve_image(chemins)
    table = fourchette(relief, depart.yaw)
    print(f"Horizon : {len(table)} caps relevés, {int((~np.isnan(vu)).sum())} colonnes mesurées")

    avant = cout(depart, table, vu, marques, p["lat"], p["lon"])
    apres_pose = affine(depart, table, vu, marques, p["lat"], p["lon"])
    apres = cout(apres_pose, table, vu, marques, p["lat"], p["lon"])
    print(f"Départ  : cap {depart.yaw:.3f}  site {depart.pitch:.3f}  roulis {depart.roll:.3f}"
          f"  champ {depart.hfov:.3f}  courbure {depart.k1:+.4f}  coût {avant:.4f}")
    print(f"Calé    : cap {apres_pose.yaw:.3f}  site {apres_pose.pitch:.3f}  roulis {apres_pose.roll:.3f}"
          f"  champ {apres_pose.hfov:.3f}  courbure {apres_pose.k1:+.4f}  coût {apres:.4f}")
    for marque in marques:
        a = frustum.project(depart, marque["lat"], marque["lon"], marque["ele"])
        b = frustum.project(apres_pose, marque["lat"], marque["lon"], marque["ele"])
        print(f"  {marque['name']:<20} visé ({marque['x']:.3f}, {marque['y']:.3f})"
              f"  avant ({a[0]:.3f}, {a[1]:.3f})  après ({b[0]:.3f}, {b[1]:.3f})")
    if ecrire:
        if apres >= avant:
            print("Coût pas meilleur : on n'écrit rien.")
            return 0
        ecrit_pose(apres_pose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
