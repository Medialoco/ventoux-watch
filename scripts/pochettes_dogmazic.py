#!/usr/bin/env python3
"""Les pochettes des morceaux, prises chez Dogmazic.

Le bandeau du bas sait afficher une pochette depuis le début et n'en a jamais
eu une seule : le champ était là, le fichier n'existait pas. Dogmazic a l'image
de chaque album, et l'API la donne en un champ. Autant la prendre.

Pour les seize morceaux de thepriben, qui ne sont pas encore déposés et n'ont
donc pas d'album, on prend l'avatar du compte — le logo de l'auteur. C'est le
même geste : montrer de qui est ce qu'on entend.

Les images sont réduites à 256 pixels de côté. Le bandeau en affiche cent
trente au plus ; au-delà on alourdit le dépôt pour rien.

    python3 scripts/pochettes_dogmazic.py
    python3 scripts/pochettes_dogmazic.py --refais   (reprend tout)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MUSIQUE = ROOT / "data" / "musique"
POCHETTES = MUSIQUE / "pochettes"
CREDITS = MUSIQUE / "credits.json"
API = "https://play.dogmazic.net/server/json.server.php"
API_VERSION = "6.0.0"
NAVIGATEUR = "ventoux-watch/1.0 (+https://medialoco.github.io/ventoux-watch/)"
COTE = 256
# Le numéro du morceau est dans son nom de fichier : c'est celui de Dogmazic.
NUMERO = re.compile(r"dogmazic-0*(\d+)\.mp3$")
# Le compte de l'auteur de la maison. Son avatar sert de pochette à ses
# morceaux tant qu'ils ne sont pas déposés sur Dogmazic et n'ont pas d'album.
MAISON = "thepriben"


def cle() -> str:
    """La clé de lecture, qui n'est jamais écrite nulle part."""
    try:
        local = json.loads((ROOT / "config" / "local.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str((local.get("dogmazic") or {}).get("api_key") or "")


def appelle(**parametres) -> dict:
    url = API + "?" + urllib.parse.urlencode(parametres)
    for tour in range(3):
        try:
            requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
            with urllib.request.urlopen(requete, timeout=60) as reponse:
                return json.load(reponse)
        except Exception:
            time.sleep(1.0 * (tour + 1))
    return {}


def telecharge(url: str) -> np.ndarray | None:
    """L'image à cette adresse, ou rien."""
    try:
        requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
        with urllib.request.urlopen(requete, timeout=60) as reponse:
            octets = reponse.read()
    except Exception:
        return None
    image = cv2.imdecode(np.frombuffer(octets, np.uint8), cv2.IMREAD_COLOR)
    # Ampache sert une image grise de remplacement quand il n'a rien. Elle est
    # unie : si l'écart-type des pixels est nul, il n'y a pas de pochette.
    if image is None or image.size == 0 or float(image.std()) < 3.0:
        return None
    return image


def portrait(jeton: str, artiste, _vus: dict = {}) -> np.ndarray | None:
    """Le portrait de l'artiste, demandé une fois par artiste."""
    if not artiste:
        return None
    if artiste not in _vus:
        reponse = appelle(action="artist", auth=jeton, filter=str(artiste))
        fiche = reponse.get("artist") if isinstance(reponse, dict) else None
        fiche = (fiche or [reponse])[0] if isinstance(fiche, list) else reponse
        _vus[artiste] = (telecharge(str(fiche.get("art") or ""))
                         if isinstance(fiche, dict) and fiche.get("has_art")
                         else None)
    return _vus[artiste]


def range_la(image: np.ndarray, chemin: Path) -> None:
    """Carrée, à 256, et sur le disque."""
    haut, large = image.shape[:2]
    cote = min(haut, large)
    rogne = image[(haut - cote) // 2:(haut - cote) // 2 + cote,
                  (large - cote) // 2:(large - cote) // 2 + cote]
    chemin.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(chemin),
                cv2.resize(rogne, (COTE, COTE), interpolation=cv2.INTER_AREA),
                [int(cv2.IMWRITE_JPEG_QUALITY), 90])


def main() -> int:
    sujet = argparse.ArgumentParser(description=__doc__)
    sujet.add_argument("--refais", action="store_true",
                       help="reprend les pochettes déjà là")
    args = sujet.parse_args()

    if not cle():
        print("Pas de clé Dogmazic dans config/local.json")
        return 1
    jeton = str(appelle(action="handshake", auth=cle(), version=API_VERSION)
                .get("auth") or "")
    if not jeton:
        print("Dogmazic n'ouvre pas de session")
        return 1

    credits = json.loads(CREDITS.read_text(encoding="utf-8"))
    pris, deja, sans = 0, 0, []

    # Le logo de la maison, une fois pour les seize.
    maison = POCHETTES / f"{MAISON}.jpg"
    if args.refais or not maison.is_file():
        compte = appelle(action="user", auth=jeton, username=MAISON)
        image = telecharge(str(compte.get("art") or "")) if compte.get("has_art") else None
        if image is not None:
            range_la(image, maison)
            print(f"logo de {MAISON}")

    for nom in sorted(credits):
        fiche = credits[nom]
        if fiche.get("auteur") == MAISON:
            if maison.is_file():
                fiche["pochette"] = f"pochettes/{maison.name}"
            continue
        trouve = NUMERO.search(nom)
        if not trouve:
            sans.append(nom)
            continue
        numero = trouve.group(1)
        chemin = POCHETTES / f"dogmazic-{int(numero):06d}.jpg"
        if chemin.is_file() and not args.refais:
            fiche["pochette"] = f"pochettes/{chemin.name}"
            deja += 1
            continue
        reponse = appelle(action="song", auth=jeton, filter=numero)
        morceau = reponse.get("song") if isinstance(reponse, dict) else None
        morceau = (morceau or [reponse])[0] if isinstance(morceau, list) else reponse
        if not isinstance(morceau, dict):
            sans.append(f"{fiche.get('auteur')} — {fiche.get('titre')}")
            continue
        image = telecharge(str(morceau.get("art") or "")) \
            if morceau.get("has_art") else None
        # Beaucoup de ces morceaux sont des titres isolés, sans album : leur
        # album s'appelle « Unknown » et n'a pas d'image. Le portrait de
        # l'artiste est alors la bonne réponse — c'est ce qu'on voulait
        # montrer de toute façon, de qui est ce qu'on entend.
        if image is None:
            image = portrait(jeton, (morceau.get("artist") or {}).get("id"))
        if image is None:
            sans.append(f"{fiche.get('auteur')} — {fiche.get('titre')}")
            continue
        range_la(image, chemin)
        fiche["pochette"] = f"pochettes/{chemin.name}"
        pris += 1
        print(f"  {fiche.get('auteur')} — {fiche.get('titre')}")
        time.sleep(0.3)

    CREDITS.write_text(json.dumps(credits, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
    avec = sum(1 for f in credits.values() if f.get("pochette"))
    print(f"\n{pris} prises, {deja} déjà là, {len(sans)} sans pochette")
    print(f"{avec} morceaux sur {len(credits)} ont une image")
    for manque in sans[:10]:
        print(f"  sans : {manque}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
