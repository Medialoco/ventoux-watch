#!/usr/bin/env python3
"""Le contour du pays où regarde la caméra, pris chez OpenStreetMap.

L'encart de droite nomme la commune ; il ne disait pas où elle est. Un nom de
commune française ne dit rien à quelqu'un qui n'est pas français, et la
moitié des spectateurs d'une webcam ne le sont pas. Une silhouette de pays
avec un point dessus se lit sans savoir lire.

Le contour est simplifié à cinq centièmes de degré — environ cinq
kilomètres — ce qui donne cent soixante points pour la France. À la taille où
il est dessiné, cent pixels de côté, c'est déjà plus fin que l'écran.

    python3 scripts/carte_du_pays.py
    python3 scripts/carte_du_pays.py --pays "Switzerland"
    python3 scripts/carte_du_pays.py --pays "California" --sortie assets/carte-californie.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "assets" / "carte-pays.json"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
NAVIGATEUR = ("ventoux-watch/1.0 "
              "(+https://medialoco.github.io/ventoux-watch/)")
# En degrés. Plus fin ne se verrait pas dans un encart de cent pixels, et
# chaque point coûte un trait à dessiner soixante fois par seconde.
FINESSE = 0.05
# On ne garde que les morceaux qui comptent : la France métropolitaine a un
# contour principal et la Corse, et c'est tout ce qu'un œil distingue ici.
MORCEAUX = 2
MINIMUM = 8


def cherche(pays: str) -> dict:
    url = NOMINATIM + "?" + urllib.parse.urlencode({
        "q": pays, "format": "json", "polygon_geojson": 1,
        "polygon_threshold": FINESSE, "limit": 1})
    requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        trouve = json.load(reponse)
    return trouve[0] if trouve else {}


def contours(geojson: dict) -> list[list[list[float]]]:
    """Les anneaux extérieurs, du plus grand au plus petit."""
    forme, points = geojson.get("type"), geojson.get("coordinates") or []
    if forme == "MultiPolygon":
        anneaux = [morceau[0] for morceau in points if morceau]
    elif forme == "Polygon":
        anneaux = [points[0]] if points else []
    else:
        return []
    anneaux.sort(key=len, reverse=True)
    return [a for a in anneaux[:MORCEAUX] if len(a) >= MINIMUM]


def main() -> int:
    sujet = argparse.ArgumentParser(description=__doc__)
    sujet.add_argument("--pays", default="France métropolitaine")
    sujet.add_argument("--sortie", type=Path, default=CIBLE)
    args = sujet.parse_args()

    trouve = cherche(args.pays)
    anneaux = contours(trouve.get("geojson") or {})
    if not anneaux:
        print(f"OpenStreetMap ne rend pas de contour pour « {args.pays} »")
        return 1

    cible = args.sortie if args.sortie.is_absolute() else ROOT / args.sortie
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps({
        "pays": trouve.get("display_name") or args.pays,
        "osm": f"{trouve.get('osm_type')}/{trouve.get('osm_id')}",
        "finesse_deg": FINESSE,
        "contours": [[[round(x, 4), round(y, 4)] for x, y in anneau]
                     for anneau in anneaux],
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{trouve.get('display_name')}")
    print(f"  {len(anneaux)} morceaux, {sum(len(a) for a in anneaux)} points")
    print(f"  écrit dans {cible.relative_to(ROOT)} "
          f"({cible.stat().st_size // 1024} ko)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
