#!/usr/bin/env python3
"""Une image du flux telle qu'un spectateur la voit, sans diffuser.

Jusqu'ici, pour juger d'un encart il fallait soit regarder YouTube avec une
minute de retard, soit écrire à la main un bout de script qui appelle les
trois ou quatre fonctions qui nous intéressent. Les deux sont mauvais : le
premier est lent, le second ne montre jamais l'image entière et c'est
justement l'image entière qu'on veut juger — un encart n'est pas trop gros
dans l'absolu, il est trop gros à côté des autres.

    python3 scripts/apercu.py
    python3 scripts/apercu.py --nuit --sortie /tmp/nuit.jpg
    python3 scripts/apercu.py --large 1920
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from watcher import stream  # noqa: E402

# Un instant arbitraire mais fixe, pour que deux aperçus se comparent.
QUAND = 1_790_000_000.0


def une_vue(nuit: bool) -> np.ndarray:
    """Une image de la webcam prise dans les archives."""
    dossier = ROOT / "data" / "thumbs"
    prises = sorted(dossier.glob("*.jpg"))
    if not prises:
        return np.full((1080, 1920, 3), 40, np.uint8)
    # De nuit on cherche la plus sombre, de jour la plus claire : c'est le
    # seul moyen honnête de voir si un encart tient sur les deux fonds.
    note = {p: float(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE).mean())
            for p in prises[-60:]}
    choisi = min(note, key=note.get) if nuit else max(note, key=note.get)
    return cv2.imread(str(choisi))


def compose(largeur: int, nuit: bool, musique: bool = True) -> np.ndarray:
    hauteur = largeur * 9 // 16
    cfg = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    scene = json.loads((ROOT / "config" / "scene.json").read_text(encoding="utf-8"))
    site = scene.get("site") or {}

    toile = stream.cadre(une_vue(nuit), largeur, hauteur)
    cadrage = stream.fenetre(une_vue(nuit).shape[:2], largeur, hauteur)
    stream.pose_danseurs(toile, 3.0, 0.2, vue=cadrage)

    stream.pose_ruban(toile, [("VENTOUX WATCH   ", stream.CYAN),
                              ("MONT SEREIN 1390 M   ", stream.BLANC),
                              ("OPEN DATA   ", stream.VERT)], 0.0)
    stream.pose_machine(toile, {"degres": 46.2, "charge": 0.31,
                                "libre": 142e9, "debout": 191_000},
                        cv2.imread(str(ROOT / "assets" / "machine.jpg")),
                        str((cfg.get("machine") or {}).get("ville") or ""))
    carte = json.loads((ROOT / "assets" / "carte-pays.json")
                       .read_text(encoding="utf-8")).get("contours")
    pose = scene.get("pose") or {}
    stream.pose_horloge(toile, QUAND, True, commune=str(site.get("commune") or ""),
                        carte=carte, ou=(float(pose["lat"]), float(pose["lon"])))

    if musique:
        credits = ROOT / "data" / "musique" / "credits.json"
        if credits.is_file():
            fiches = json.loads(credits.read_text(encoding="utf-8"))
            trio = list(fiches.values())[:3]
            stream.pose_bloc_musique(toile, tuple(trio), credits.parent)
    feuille = ROOT / "data" / "sport.json"
    if feuille.is_file():
        sport = json.loads(feuille.read_text(encoding="utf-8"))
        stream.pose_sport(toile, (sport.get("joues") or []) + (sport.get("a_venir") or []),
                          str(sport.get("ligue") or ""), 0.0)
    machine = cfg.get("machine") or {}
    if machine.get("lat") is not None:
        km = stream.a_vol_d_oiseau((float(machine["lat"]), float(machine["lon"])),
                                   (float(pose["lat"]), float(pose["lon"])))
        stream.pose_distance(
            toile,
            f"{str(machine['ville']).upper()} - {str(site.get('commune','')).upper()}"
            f"  {km:,.0f} KM AS THE CROW FLIES".replace(",", " "),
            cadrage)
    return toile


def main() -> int:
    sujet = argparse.ArgumentParser(description=__doc__)
    sujet.add_argument("--large", type=int, default=1280)
    sujet.add_argument("--nuit", action="store_true")
    sujet.add_argument("--sans-musique", action="store_true")
    sujet.add_argument("--sortie", default="/tmp/apercu.jpg")
    args = sujet.parse_args()

    image = compose(args.large, args.nuit, not args.sans_musique)
    cv2.imwrite(args.sortie, image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    print(f"{args.sortie}  {image.shape[1]}x{image.shape[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
