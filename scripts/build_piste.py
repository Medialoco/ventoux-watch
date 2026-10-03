"""Retrouve une piste de ski dans le paysage et la range dans scene.json.

Le tracé n'est pas dessiné à la main. OpenStreetMap sait où sont les pistes du
Mont Serein, avec leur nom et leur difficulté ; la pose de la caméra et le
modèle d'altitude savent où ça tombe dans l'image. Les deux ensemble donnent
une piste là où la piste est vraiment, et la même recette sur une autre caméra
donnera la sienne — c'est tout l'intérêt de ne rien régler à l'œil.

CE QUE LE SCRIPT DÉCIDE, ET SUR QUOI
------------------------------------
Il y a trente-neuf pistes et remontées autour du Mont Serein, et une douzaine
tombe dans le cadre. Trois critères, dans cet ordre :

- elle doit avoir au moins trois points bien dans l'image, sinon ce n'est pas
  une descente, c'est un bout de descente ;
- elle doit être plus claire que ses abords. Une piste est une trouée dans la
  forêt : même en été, sans neige, l'herbe rase y est plus claire que les
  pins. C'est la vérification que la projection tombe juste — si le tracé
  calculé ne passe pas sur une trouée, c'est que la pose est fausse, et on
  préfère le savoir ;
- à égalité, la plus longue à l'écran. On regarde une descente, pas un virage.

Et on la coupe là où elle entre dans la route ou le rond-point. La vraie piste
finit au parking du Mont Serein, qui est précisément ce que la veille
surveille : personne ne surfe par-dessus.

    .venv/bin/python -m scripts.build_piste
    .venv/bin/python -m scripts.build_piste --apercu /tmp/pistes.jpg
"""

from __future__ import annotations

import argparse
import json
import math
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
# Trois kilomètres : au-delà, le relief cache tout et la projection n'a plus
# de sens. C'est aussi un peu plus que le « reach_m » de la pose.
AUTOUR_M = 3000
# De part et d'autre du tracé, en parts de largeur d'image, pour mesurer si la
# piste est une trouée. Vingt pixels sur mille deux cent quatre-vingts : assez
# pour sortir de la trouée, pas assez pour tomber dans la suivante.
COTE = 0.020
MINI_POINTS = 3


def demande(lat: float, lon: float) -> list[dict]:
    """Les pistes et les remontées autour d'un point, par Overpass."""
    question = (f"[out:json][timeout:60];\n"
                f'(way(around:{AUTOUR_M},{lat},{lon})["piste:type"];);\nout geom;')
    requete = urllib.request.Request(
        OVERPASS, data=urllib.parse.urlencode({"data": question}).encode(),
        headers={"User-Agent": "ventoux-watch/1.0"})
    with urllib.request.urlopen(requete, timeout=120) as reponse:
        return json.load(reponse).get("elements") or []


def sol(altitudes: list[tuple[float, float, float]], lat: float, lon: float) -> float:
    """L'altitude du point de relevé le plus proche.

    Au plus proche et non par interpolation : les relevés sont à quarante
    mètres les uns des autres et une piste fait trente mètres de large. Une
    interpolation bilinéaire serait plus savante et pas plus juste.
    """
    return min(altitudes, key=lambda p: (p[0] - lat) ** 2 + (p[1] - lon) ** 2)[2]


def trouee(gris: np.ndarray, trace: list[list[float]]) -> float:
    """De combien le tracé est plus clair que ses abords, en niveaux de gris.

    C'est la vérification que la projection tombe juste. Une piste est une
    trouée dans la forêt ; si le tracé calculé n'y passe pas, ce n'est pas la
    piste qui a bougé.
    """
    hauteur, largeur = gris.shape[:2]
    points = np.array(trace, dtype=np.float64)
    pas = np.linspace(0, len(points) - 1, 200)
    x = np.interp(pas, range(len(points)), points[:, 0])
    y = np.interp(pas, range(len(points)), points[:, 1])
    ys = np.clip((y * hauteur).astype(int), 0, hauteur - 1)

    def clarte(decale: float) -> float:
        xs = np.clip(((x + decale) * largeur).astype(int), 0, largeur - 1)
        return float(gris[ys, xs].mean())

    return clarte(0.0) - (clarte(-COTE) + clarte(COTE)) / 2


def dehors(polygones: dict, x: float, y: float) -> bool:
    """Ce point est-il hors de la route et du rond-point ?"""
    for nom in ("road", "roundabout"):
        contour = polygones.get(nom)
        if contour and cv2.pointPolygonTest(np.float32(contour),
                                            (float(x), float(y)), False) >= 0:
            return False
    return True


def longueur(trace: list[list[float]]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(trace, trace[1:]))


def candidates(pose, altitudes, elements, polygones) -> list[dict]:
    """Les pistes qui tombent dans le cadre, chacune avec son tracé coupé."""
    trouvees = []
    for element in elements:
        etiquettes = element.get("tags") or {}
        if etiquettes.get("piste:type") != "downhill":
            continue
        trace = []
        for point in element.get("geometry") or []:
            vu = frustum.project(pose, point["lat"], point["lon"],
                                 sol(altitudes, point["lat"], point["lon"]))
            trace.append(list(vu) if vu else None)
        # Le plus long morceau d'affilée qui tienne dans le cadre, et non
        # tous les points qui y tiennent : une piste qui sort du champ et y
        # revient donnerait un tracé qui saute par-dessus le vide, et le
        # surfeur traverserait l'image en ligne droite au milieu.
        dedans: list[list[float]] = []
        courant: list[list[float]] = []
        for point in trace:
            if point and 0.02 <= point[0] <= 0.98 and 0.02 <= point[1] <= 0.98:
                courant.append(point)
            else:
                dedans = max(dedans, courant, key=len)
                courant = []
        dedans = max(dedans, courant, key=len)
        if len(dedans) < MINI_POINTS:
            continue
        # Du haut vers le bas : on descend une piste.
        if dedans[0][1] > dedans[-1][1]:
            dedans.reverse()
        coupe = []
        for x, y in dedans:
            if not dehors(polygones, x, y):
                break
            coupe.append([round(x, 5), round(y, 5)])
        if len(coupe) < MINI_POINTS:
            continue
        trouvees.append({
            "name": etiquettes.get("name") or "(sans nom)",
            "difficulty": etiquettes.get("piste:difficulty"),
            "osm_way": element["id"],
            "trace": coupe,
        })
    return trouvees


def main() -> int:
    partie = argparse.ArgumentParser(description=__doc__)
    partie.add_argument("--image", default="data/view.jpg",
                        help="l'image de JOUR sur laquelle on vérifie la trouée")
    partie.add_argument("--apercu", default="",
                        help="où écrire un aperçu des candidates")
    partie.add_argument("--essai", action="store_true",
                        help="classer sans rien écrire dans scene.json")
    args = partie.parse_args()

    chemin = ROOT / "config" / "scene.json"
    scene = json.loads(chemin.read_text(encoding="utf-8"))
    pose = frustum.Pose(**{c: v for c, v in scene["pose"].items()
                           if c in frustum.Pose.__dataclass_fields__})
    releves = json.loads((ROOT / "data" / "osm" / "elevation.json")
                         .read_text(encoding="utf-8"))
    altitudes = [(float(k.split(",")[0]), float(k.split(",")[1]), v)
                 for k, v in releves.items()]
    polygones = json.loads((ROOT / "config" / "zones.json")
                           .read_text(encoding="utf-8")).get("polygons") or {}

    image = cv2.imread(str(ROOT / args.image))
    if image is None:
        print(f"Pas d'image à {args.image} : on ne peut pas vérifier la trouée")
        return 1
    gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    # Il faut une image de jour. De nuit, la forêt et la trouée sont noires
    # toutes les deux, l'écart tombe dans le bruit, et le classement se fait
    # alors sur la longueur seule — en croyant l'avoir vérifié.
    if float(gris.mean()) < 60.0:
        print(f"{args.image} est trop sombre ({gris.mean():.0f}/255) : "
              "une trouée ne se voit pas de nuit")
        return 1

    print(f"Pistes autour de {pose.lat:.4f}, {pose.lon:.4f}")
    trouvees = candidates(pose, altitudes, demande(pose.lat, pose.lon), polygones)
    for piste in trouvees:
        piste["contrast"] = round(trouee(gris, piste["trace"]), 2)
        piste["length"] = round(longueur(piste["trace"]), 4)
    # Plus claire que ses abords d'abord, la plus longue ensuite.
    claires = [p for p in trouvees if p["contrast"] > 0]
    classe = sorted(claires, key=lambda p: -p["length"])
    for piste in sorted(trouvees, key=lambda p: -p["length"])[:10]:
        marque = "clair" if piste["contrast"] > 0 else "     "
        print(f"  {marque} {piste['name'][:24]:24s} {piste['difficulty'] or '':12s} "
              f"{len(piste['trace']):2d} pts  long {piste['length']:.3f}  "
              f"trouée {piste['contrast']:+5.1f}")

    if args.apercu:
        apercu = image.copy()
        hauteur, largeur = apercu.shape[:2]
        for rang, piste in enumerate(classe[:5]):
            teinte = (0, 255 - rang * 45, 60 + rang * 45)
            points = np.int32([[x * largeur, y * hauteur] for x, y in piste["trace"]])
            cv2.polylines(apercu, [points], False, teinte, 2, cv2.LINE_AA)
            cv2.putText(apercu, f"{rang + 1}. {piste['name']}", (14, 30 + rang * 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(apercu, f"{rang + 1}. {piste['name']}", (14, 30 + rang * 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, teinte, 2, cv2.LINE_AA)
        cv2.imwrite(args.apercu, apercu)
        print(f"  aperçu : {args.apercu}")

    if not classe:
        print("Aucune piste ne passe sur une trouée : la pose est à revoir")
        return 1
    gagnante = classe[0]
    print(f"Retenue : {gagnante['name']} ({gagnante['difficulty']}), "
          f"{len(gagnante['trace'])} points")
    if args.essai:
        return 0
    scene["piste"] = {**gagnante, "clipped_by": ["road", "roundabout"]}
    chemin.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"Écrite dans {chemin.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
