#!/usr/bin/env python3
"""Copies d'écran du flux pour la galerie du site.

Chaque image est le même cadre que le spectateur voit, avec un numéro ou un
effet à l'endroit où il passe vraiment. On les écrit dans site/stills/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import apercu  # noqa: E402
from watcher import stream  # noqa: E402

SORTIE = ROOT / "site" / "stills"
LARGE = 960


def instant(nom: str, cible: float = 0.45) -> float:
    """Une seconde où ce numéro est vraiment en scène, au milieu de son geste."""
    fiche = next((p, d, r) for a, p, d, r in stream.PLATEAU if a == nom)
    periode, duree, retard = fiche
    vise = cible * duree
    for s in range(int(retard), int(retard + periode * 3)):
        phase = stream.en_scene(nom, float(s))
        if phase is not None and abs(phase - vise) < 0.8:
            return float(s)
    for s in range(0, int(periode * 3)):
        phase = stream.en_scene(nom, float(s))
        if phase is not None:
            return float(s)
    return retard + vise


def ciel() -> list:
    zones = json.loads((ROOT / "config" / "zones.json").read_text(encoding="utf-8"))
    return (zones.get("polygons") or {}).get("sky") or []


def decor() -> tuple[list | None, list]:
    scene = json.loads((ROOT / "config" / "scene.json").read_text(encoding="utf-8"))
    return (scene.get("piste") or {}).get("trace"), scene.get("buildings") or []


def ecrire(nom: str, image: np.ndarray) -> None:
    SORTIE.mkdir(parents=True, exist_ok=True)
    chemin = SORTIE / f"{nom}.jpg"
    cv2.imwrite(str(chemin), image, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    print(f"{chemin.name}  {image.shape[1]}x{image.shape[0]}")


def main() -> int:
    piste, batis = decor()
    contour = ciel()
    ours = stream.charge_vignette(ROOT / "data" / "ours.png")
    preuve = cv2.imread(str(ROOT / "assets" / "ours-maison.jpg"))
    marin = stream.charge_vignette(ROOT / "assets" / "sous-marin.png")
    thumbs = sorted((ROOT / "data" / "thumbs").glob("*.jpg"))
    photo = next((p for p in reversed(thumbs) if p.stat().st_size > 8000), thumbs[-1] if thumbs else None)

    console = apercu.compose(LARGE, False, forme="")
    ecrire("console", console)

    cadrage = stream.fenetre(apercu.une_vue(False).shape[:2], LARGE, LARGE * 9 // 16)
    gauche, cime, large_vue, haute_vue = cadrage
    for forme in ("pixel", "gris", "ondule"):
        toile = apercu.compose(LARGE, False, forme=forme)
        fen = toile[cime:cime + haute_vue, gauche:gauche + large_vue].copy()
        stream.applique_effet(fen, forme, 0.85, 3.0)
        toile[cime:cime + haute_vue, gauche:gauche + large_vue] = fen
        ecrire(forme, toile)

    ecrire("rencontre", apercu.compose(LARGE, False, rencontre=True))
    ecrire("eclat", apercu.compose(LARGE, False, eclat=0.35, nom="Voiture"))

    toile = apercu.compose(LARGE, False)
    cadrage = stream.fenetre(apercu.une_vue(False).shape[:2], LARGE, LARGE * 9 // 16)
    stream.pose_soleil_dessine(toile, (0.72, 0.22), 4.0)
    ecrire("soleil", toile)

    actes = [
        ("tapis", lambda t, s: stream.pose_tapis(t, s, 0.4, ciel=contour, vue=cadrage)),
        ("sous-marin", lambda t, s: stream.pose_sous_marin(t, s, marin, ciel=contour, vue=cadrage)),
        ("piste", lambda t, s: stream.pose_piste(t, s, piste, vue=cadrage)),
        ("elephant", lambda t, s: stream.pose_elephant(t, s, 0.4, vue=cadrage, heure=3)),
        ("batiment", lambda t, s: stream.pose_batiments(t, s, batis, vue=cadrage)),
        ("ours", lambda t, s: stream.pose_ours(t, s, ours, vue=cadrage, preuve=preuve)),
    ]
    for nom, pose in actes:
        toile = apercu.compose(LARGE, False)
        ok = pose(toile, instant(nom))
        if ok in (False, None):
            print(f"{nom}: absent à {instant(nom):.1f}s")
        ecrire(nom, toile)

    if photo is not None:
        toile = apercu.compose(LARGE, False)
        stream.pose_rediffusion(toile, {
            "photo": str(photo),
            "t": "2026-10-04T16:43:00Z",
            "label": "Voiture",
        }, vue=cadrage)
        ecrire("replay", toile)

    return 0


if __name__ == "__main__":
    sys.exit(main())
