"""Retrouve les bâtiments du paysage et les range dans scene.json.

Même recette que la piste de ski, et pour la même raison : rien n'est dessiné
à la main. OpenStreetMap connaît l'emprise au sol de la bergerie et du chalet
du Mont Serein ; la pose de la caméra et le modèle d'altitude savent où ça
tombe dans l'image. Sur une autre caméra dont on aura l'OSM local, la recette
rendra ses bâtiments à elle sans qu'on règle un pixel.

CE QU'ON DESSINE, ET POURQUOI PAS SEULEMENT L'EMPRISE
-----------------------------------------------------
L'emprise au sol projetée donne le pied des murs, ce qui est exact et ce qui
ne ressemble à rien : un quadrilatère posé à plat au milieu de l'herbe. Un
bâtiment se reconnaît à son volume. On projette donc l'emprise deux fois, au
sol et à la hauteur du toit, et on relie les coins : c'est un fil de fer, et
un fil de fer se lit tout de suite comme un bâtiment.

La hauteur vient d'OSM quand elle y est (« height », ou « building:levels »
multiplié par la hauteur d'un étage) et vaut six mètres sinon — deux niveaux,
ce qu'est une bergerie.

CE QU'ON GARDE
--------------
Ceux qui ont au moins trois coins bien dans le cadre et qui occupent assez de
place pour qu'on les voie : un bâtiment à quatre pixels de large n'est pas un
bâtiment, c'est une poussière, et un fil de fer dessus est un défaut d'image.

    .venv/bin/python -m scripts.build_batiments
    .venv/bin/python -m scripts.build_batiments --apercu /tmp/batiments.jpg
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher import frustum  # noqa: E402

OVERPASS = "https://overpass-api.de/api/interpreter"
# Plus serré que pour les pistes : un bâtiment à trois kilomètres tient dans
# dix pixels, et dix pixels de fil de fer sont une rayure.
AUTOUR_M = 900
ETAGE_M = 3.0
HAUTEUR_PAR_DEFAUT_M = 6.0
MINI_COINS = 3
# En part de largeur d'image. En dessous, le fil de fer n'est plus lisible
# comme un volume et devient une tache de traits.
MINI_LARGE = 0.035


def demande(lat: float, lon: float) -> list[dict]:
    """Les bâtiments autour d'un point, par Overpass."""
    question = (f"[out:json][timeout:60];\n"
                f'(way(around:{AUTOUR_M},{lat},{lon})["building"];);\nout geom;')
    requete = urllib.request.Request(
        OVERPASS, data=urllib.parse.urlencode({"data": question}).encode(),
        headers={"User-Agent": "ventoux-watch/1.0"})
    with urllib.request.urlopen(requete, timeout=120) as reponse:
        return json.load(reponse).get("elements") or []


def sol(altitudes: list[tuple[float, float, float]], lat: float, lon: float) -> float:
    """L'altitude du relevé le plus proche, comme pour la piste."""
    return min(altitudes, key=lambda p: (p[0] - lat) ** 2 + (p[1] - lon) ** 2)[2]


def hauteur_de(etiquettes: dict) -> float:
    """Ce qu'OSM dit de la hauteur, ou ce qu'une bergerie fait en général."""
    brut = etiquettes.get("height") or etiquettes.get("building:height")
    if brut:
        try:
            return float(str(brut).replace("m", "").strip())
        except ValueError:
            pass
    niveaux = etiquettes.get("building:levels")
    if niveaux:
        try:
            return float(niveaux) * ETAGE_M
        except ValueError:
            pass
    return HAUTEUR_PAR_DEFAUT_M


def candidats(pose, altitudes, elements) -> list[dict]:
    """Les bâtiments qui tombent dans le cadre, avec leur fil de fer."""
    trouves = []
    for element in elements:
        etiquettes = element.get("tags") or {}
        points = element.get("geometry") or []
        if len(points) < 4:
            continue
        # Le dernier point d'un contour fermé répète le premier : on l'enlève,
        # sinon le fil de fer porte une arête verticale en double.
        if points[0] == points[-1]:
            points = points[:-1]
        haut_m = hauteur_de(etiquettes)
        pied, toit = [], []
        for point in points:
            base = sol(altitudes, point["lat"], point["lon"])
            bas = frustum.project(pose, point["lat"], point["lon"], base)
            sommet = frustum.project(pose, point["lat"], point["lon"], base + haut_m)
            if not bas or not sommet:
                pied, toit = [], []
                break
            pied.append(list(bas))
            toit.append(list(sommet))
        if len(pied) < MINI_COINS:
            continue
        dedans = [p for p in pied + toit
                  if 0.0 <= p[0] <= 1.0 and 0.0 <= p[1] <= 1.0]
        if len(dedans) < MINI_COINS:
            continue
        xs = [p[0] for p in pied + toit]
        ys = [p[1] for p in pied + toit]
        large = max(xs) - min(xs)
        if large < MINI_LARGE:
            continue
        trouves.append({
            "name": etiquettes.get("name") or etiquettes.get("building") or "(sans nom)",
            "osm_way": element["id"],
            "height_m": round(haut_m, 1),
            "foot": [[round(x, 5), round(y, 5)] for x, y in pied],
            "roof": [[round(x, 5), round(y, 5)] for x, y in toit],
            "width": round(large, 4),
            # Où il est dans l'image, pour pouvoir choisir « celui de droite »
            # sans rouvrir le fichier à la main.
            "cx": round(sum(xs) / len(xs), 4),
            "cy": round(sum(ys) / len(ys), 4),
        })
    return trouves


def main() -> int:
    partie = argparse.ArgumentParser(description=__doc__)
    partie.add_argument("--image", default="data/view.jpg")
    partie.add_argument("--apercu", default="")
    partie.add_argument("--essai", action="store_true")
    args = partie.parse_args()

    chemin = ROOT / "config" / "scene.json"
    scene = json.loads(chemin.read_text(encoding="utf-8"))
    pose = frustum.Pose(**{c: v for c, v in scene["pose"].items()
                           if c in frustum.Pose.__dataclass_fields__})
    releves = json.loads((ROOT / "data" / "osm" / "elevation.json")
                         .read_text(encoding="utf-8"))
    altitudes = [(float(k.split(",")[0]), float(k.split(",")[1]), v)
                 for k, v in releves.items()]

    print(f"Bâtiments autour de {pose.lat:.4f}, {pose.lon:.4f}")
    trouves = candidats(pose, altitudes, demande(pose.lat, pose.lon))
    for bati in sorted(trouves, key=lambda b: -b["width"]):
        print(f"  {bati['name'][:26]:26s} way {bati['osm_way']:<12d} "
              f"{len(bati['foot']):2d} coins  h {bati['height_m']:4.1f} m  "
              f"large {bati['width']:.3f}  centre ({bati['cx']:.2f}, {bati['cy']:.2f})")

    if args.apercu:
        image = cv2.imread(str(ROOT / args.image))
        if image is not None:
            apercu = image.copy()
            hauteur, largeur = apercu.shape[:2]
            for rang, bati in enumerate(sorted(trouves, key=lambda b: -b["width"])[:6]):
                teinte = (0, 255 - rang * 35, 60 + rang * 35)
                for contour in (bati["foot"], bati["roof"]):
                    pts = np.int32([[x * largeur, y * hauteur] for x, y in contour])
                    cv2.polylines(apercu, [pts], True, teinte, 2, cv2.LINE_AA)
                for bas, haut in zip(bati["foot"], bati["roof"]):
                    cv2.line(apercu, (int(bas[0] * largeur), int(bas[1] * hauteur)),
                             (int(haut[0] * largeur), int(haut[1] * hauteur)),
                             teinte, 2, cv2.LINE_AA)
                cv2.putText(apercu, f"{rang + 1}. {bati['name']}", (14, 30 + rang * 26),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
                cv2.putText(apercu, f"{rang + 1}. {bati['name']}", (14, 30 + rang * 26),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, teinte, 2, cv2.LINE_AA)
            cv2.imwrite(args.apercu, apercu)
            print(f"  aperçu : {args.apercu}")

    if not trouves:
        print("Aucun bâtiment ne tombe dans le cadre")
        return 1
    if args.essai:
        return 0
    scene["buildings"] = sorted(trouves, key=lambda b: -b["width"])
    chemin.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"Écrits dans {chemin.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
