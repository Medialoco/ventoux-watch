"""Vérifie que la chaîne est vraiment en l'air, et pas seulement qu'on pousse.

Le 2 octobre, YouTube a terminé la diffusion à 7 h 28. Le Raspberry Pi n'a rien
remarqué : son ffmpeg gardait une connexion ouverte vers l'entrée de Google et
lui envoyait un mégaoctet toutes les cinq secondes. Tout allait bien de notre
côté du fil, et la chaîne était muette. Personne ne l'a su pendant neuf heures,
jusqu'à ce que celui qui regarde s'en aperçoive lui-même.

C'est la leçon à retenir : « le flux tourne » et « la chaîne est en direct »
sont deux faits différents, et seul le second intéresse quelqu'un. Un service
actif ne prouve rien, une connexion établie non plus, et des octets qui sortent
pas davantage. La seule preuve est de demander à YouTube.

Ce fichier ne répare rien. Il constate, il écrit ce qu'il constate, et il le
publie avec le reste pour que ça se voie d'ailleurs que du journal de la
machine. Réparer demande d'ouvrir la salle de contrôle, ce qu'aucun programme
ici n'a le droit de faire à la place de quelqu'un.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAINE = "UCvN0sNcj5JM9tklIkAlGi7g"
LIVE_URL = "https://www.youtube.com/channel/{chaine}/live"
VIDEO_URL = "https://www.youtube.com/watch?v={video}"
# Un navigateur, sinon YouTube sert une page sans le détail de la diffusion.
NAVIGATEUR = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
DELAI_S = 20

log = logging.getLogger("antenne")


def page(url: str) -> str:
    requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
    with urllib.request.urlopen(requete, timeout=DELAI_S) as reponse:
        return reponse.read().decode("utf-8", "replace")


def en_direct(ouvre, chaine: str) -> tuple[bool, str]:
    """Vrai seulement si YouTube le dit de la diffusion elle-même.

    En deux temps, et il le faut. La page /live de la chaîne ne porte pas de
    drapeau lisible : elle liste des identifiants, et elle en liste aussi quand
    la chaîne est éteinte. Mon premier essai s'y fiait et annonçait la panne en
    plein direct — une alarme qui se trompe dans ce sens-là est pire que pas
    d'alarme, parce qu'on apprend à ne plus la croire.

    Ce qui est vrai, c'est que l'identifiant en tête de cette page est celui de
    la diffusion en cours quand il y en a une. On va donc lire sa fiche, où
    « isLiveNow » dit oui ou non sans ambiguïté — c'est le même champ qui
    portait la date de fin, 7 h 28 min 34 s, le matin où la chaîne est tombée.
    """
    page_chaine = ouvre(LIVE_URL.format(chaine=chaine))
    trouve = re.search(r'"videoId":"([\w-]{11})"', page_chaine)
    if not trouve:
        return False, ""
    video = trouve.group(1)
    return '"isLiveNow":true' in ouvre(VIDEO_URL.format(video=video)), video


def releve(chaine: str = CHAINE) -> dict:
    quand = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        vivant, video = en_direct(page, chaine)
    except (urllib.error.URLError, OSError, TimeoutError) as souci:
        # Ne pas confondre « la chaîne est morte » et « on n'a pas pu demander ».
        # Déclarer la panne sur un réseau qui bronche ferait crier l'alarme pour
        # rien, et une alarme qui crie pour rien finit par ne plus être écoutée.
        return {"verifie": quand, "atteignable": False, "souci": str(souci)[:120]}
    return {"verifie": quand, "atteignable": True, "live": vivant, "video": video}


def note(etat: dict, fichier: Path) -> dict:
    """Garde depuis quand ça dure, parce que c'est ça qui dit la gravité."""
    avant = {}
    if fichier.exists():
        try:
            avant = json.loads(fichier.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            avant = {}
    if not etat.get("atteignable"):
        etat["depuis"] = avant.get("depuis", etat["verifie"])
        etat["live"] = avant.get("live")
    elif avant.get("live") == etat["live"]:
        etat["depuis"] = avant.get("depuis", etat["verifie"])
    else:
        etat["depuis"] = etat["verifie"]
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(json.dumps(etat, ensure_ascii=False) + "\n", encoding="utf-8")
    return etat


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    etat = note(releve(), ROOT / "data" / "antenne.json")
    if not etat.get("atteignable"):
        log.warning("YouTube injoignable : %s", etat.get("souci"))
        return 0
    if etat["live"]:
        log.info("En direct depuis %s : %s", etat["depuis"], etat["video"])
        return 0
    log.error("LA CHAÎNE N'EST PAS EN DIRECT depuis %s", etat["depuis"])
    return 1


if __name__ == "__main__":
    sys.exit(main())
