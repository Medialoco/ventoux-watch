#!/usr/bin/env python3
"""Les résultats du football, pour le bandeau du bas.

Le bandeau du bas répétait sept phrases sur le flux lui-même. Il dit
maintenant quelque chose qui change tout seul, ce qui est la seule raison
d'avoir un bandeau qui défile.

Sur la National 3, qui serait le championnat du coin : elle n'est lisible
nulle part. L'API de la Fédération répond 403 à qui n'est pas son propre
site, aucune base ouverte ne descend sous la Ligue 2, et Wikipédia n'a pas
de page pour la saison. On ne l'invente pas. Si une source apparaît, elle se
branche ici et le reste ne bouge pas.

En attendant, la Ligue 1, dont deux clubs sont de la région que regarde la
caméra — Marseille et Nice. Ceux-là sont marqués ; le reste est donné parce
qu'un classement amputé n'est plus un classement.

    python3 scripts/sport.py
    python3 scripts/sport.py --montre
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "data" / "sport.json"
# La clé « 3 » est celle que TheSportsDB laisse ouverte. Elle rend cinq
# rencontres par appel, ce qui est peu et largement assez pour un bandeau qui
# met une minute à traverser l'écran.
API = "https://www.thesportsdb.com/api/v1/json/3"
NAVIGATEUR = ("ventoux-watch/1.0 "
              "(+https://medialoco.github.io/ventoux-watch/)")
LIGUE = 4334
LIGUE_NOM = "LIGUE 1"
SAISON = "2026-2027"
# Jusqu'où remonter pour trouver la dernière journée jouée et la suivante.
# Une trentaine de journées fait une saison ; on s'arrête à la première qui
# n'est pas finie, donc ce nombre n'est qu'un garde-fou.
JOURNEES = 34
# Les clubs de la région que regarde la caméra. Ils sont signalés dans le
# bandeau, parce que c'est l'intérêt d'un résultat sportif sur une webcam de
# Provence : savoir comment a joué l'équipe d'à côté.
DU_COIN = {"Marseille", "Nice", "Montpellier", "Nîmes", "Toulon"}


def appelle(chemin: str) -> dict:
    requete = urllib.request.Request(f"{API}/{chemin}",
                                     headers={"User-Agent": NAVIGATEUR})
    try:
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            return json.load(reponse) or {}
    except Exception:
        return {}


def une_ligne(match: dict) -> dict:
    """Une rencontre réduite à ce qui se lit en passant."""
    chez, dehors = (str(match.get("strHomeTeam") or ""),
                    str(match.get("strAwayTeam") or ""))
    pour = match.get("intHomeScore")
    contre = match.get("intAwayScore")
    joue = pour is not None and contre is not None
    return {
        "date": str(match.get("dateEvent") or ""),
        "chez": chez,
        "dehors": dehors,
        "score": f"{pour}-{contre}" if joue else "",
        "joue": joue,
        "du_coin": chez in DU_COIN or dehors in DU_COIN,
    }


def main() -> int:
    sujet = argparse.ArgumentParser(description=__doc__)
    sujet.add_argument("--montre", action="store_true",
                       help="affiche sans écrire")
    args = sujet.parse_args()

    # Par journées et non par « derniers résultats » : les deux points
    # d'entrée du palier gratuit ne rendent qu'une seule rencontre chacun,
    # ce qui ne fait pas un bandeau. Une journée en rend cinq.
    joues, a_venir = [], []
    for tour in range(1, JOURNEES + 1):
        rencontres = [une_ligne(m) for m in
                      (appelle(f"eventsround.php?id={LIGUE}&r={tour}"
                               f"&s={SAISON}").get("events") or [])]
        if not rencontres:
            continue
        if all(m["joue"] for m in rencontres):
            joues = rencontres
        else:
            a_venir = [m for m in rencontres if not m["joue"]]
            break
    if not joues and not a_venir:
        # On ne vide pas ce qui est déjà là : un bandeau figé sur le résultat
        # d'avant-hier vaut mieux qu'un bandeau vide, et bien mieux qu'un
        # bandeau qui invente.
        print("Aucune rencontre lue, l'ancien fichier reste en place")
        return 1

    tout = {
        "ligue": LIGUE_NOM,
        "saison": SAISON,
        "source": "TheSportsDB",
        "lu": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "joues": sorted(joues, key=lambda m: m["date"], reverse=True),
        "a_venir": sorted(a_venir, key=lambda m: m["date"]),
    }
    for match in tout["joues"] + tout["a_venir"]:
        marque = "·" if match["du_coin"] else " "
        print(f" {marque} {match['date']}  {match['chez']:>26s} "
              f"{match['score'] or '  vs':^7s} {match['dehors']}")
    if args.montre:
        return 0
    CIBLE.parent.mkdir(parents=True, exist_ok=True)
    CIBLE.write_text(json.dumps(tout, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
    print(f"\n{len(joues)} joués, {len(a_venir)} à venir, "
          f"dans {CIBLE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
