#!/usr/bin/env python3
"""Le nom de la commune où se trouve la caméra, demandé à OpenStreetMap.

L'horloge disait « PARIS », qui était le fuseau et que personne ne lisait
comme tel : sur une image du Ventoux, un spectateur lit un lieu. Elle dit
maintenant la commune, qui est vraie et qui est l'information qu'on cherchait
à donner. Le fuseau n'est pas perdu pour autant, la commune est en France.

On ne va pas demander ça au réseau à chaque image : la caméra ne bouge pas.
Le nom est résolu une fois ici, depuis la position de config/scene.json, et
écrit à côté d'elle. Pour la caméra suivante, c'est une commande.

    python3 scripts/commune_du_site.py
    python3 scripts/commune_du_site.py --montre   (sans rien écrire)
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENE = ROOT / "config" / "scene.json"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
# Nominatim demande qu'on se nomme, et il a raison.
NAVIGATEUR = ("ventoux-watch/1.0 "
              "(+https://medialoco.github.io/ventoux-watch/)")
# Le rang 10 est celui de la commune. Plus fin, on tombe sur le lieu-dit ;
# plus large, sur l'intercommunalité.
RANG = 10
# Au rang 10, l'objet trouvé est la commune elle-même et son nom est dans
# « name » : c'est celui-là qu'il faut lire. Les champs de l'adresse sont un
# piège en France — « municipality » y est l'arrondissement, et pour cette
# caméra il vaut Carpentras, qui est à vingt kilomètres et qui n'est pas la
# commune. On ne descend dans l'adresse que si « name » manque, et jamais
# par « municipality ».
NOMS = ("village", "town", "city", "hamlet")


def demande(lat: float, lon: float) -> dict:
    url = NOMINATIM + "?" + urllib.parse.urlencode({
        "format": "json", "lat": f"{lat:.10f}", "lon": f"{lon:.10f}",
        "zoom": RANG, "addressdetails": 1})
    requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        return json.load(reponse)


def main() -> int:
    sujet = argparse.ArgumentParser(description=__doc__)
    sujet.add_argument("--montre", action="store_true",
                       help="affiche sans écrire dans scene.json")
    args = sujet.parse_args()

    scene = json.loads(SCENE.read_text(encoding="utf-8"))
    pose = scene.get("pose") or {}
    lat, lon = float(pose.get("lat")), float(pose.get("lon"))
    reponse = demande(lat, lon)
    adresse = reponse.get("address") or {}
    commune = str(reponse.get("name") or "") or next(
        (adresse[c] for c in NOMS if adresse.get(c)), "")
    if not commune:
        print(f"OpenStreetMap ne nomme pas de commune en {lat}, {lon}")
        return 1

    site = {
        "commune": commune,
        "departement": adresse.get("county") or "",
        "code_postal": adresse.get("postcode") or "",
        "osm": f"{reponse.get('osm_type')}/{reponse.get('osm_id')}",
    }
    for champ, valeur in site.items():
        print(f"  {champ:12s} {valeur}")
    if args.montre:
        return 0
    scene["site"] = site
    SCENE.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    print(f"\nécrit dans {SCENE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
