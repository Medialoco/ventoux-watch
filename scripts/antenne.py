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
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAINE = "UCvN0sNcj5JM9tklIkAlGi7g"
LIVE_URL = "https://www.youtube.com/channel/{chaine}/live"
# Un navigateur, sinon YouTube sert une page sans le détail de la diffusion.
NAVIGATEUR = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
DELAI_S = 20

log = logging.getLogger("antenne")


def page(url: str) -> str:
    requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
    with urllib.request.urlopen(requete, timeout=DELAI_S) as reponse:
        return reponse.read().decode("utf-8", "replace")


def en_direct(html: str) -> tuple[bool, str]:
    """Vrai seulement si YouTube le dit lui-même, et l'identifiant de la vidéo.

    Le marqueur est « isLiveNow », qui n'apparaît que sur la page d'une
    diffusion. Quand la chaîne n'est pas en l'air, l'adresse /live renvoie la
    liste des vidéos passées : on y trouve toujours des identifiants, et c'est
    précisément ce qui m'a fait croire un moment que tout allait bien. Un
    identifiant ne prouve rien ; ce drapeau-là, si.
    """
    vivant = '"isLiveNow":true' in html
    debut = html.find('"videoId":"')
    video = html[debut + 11:html.find('"', debut + 11)] if debut >= 0 else ""
    return vivant, video if vivant else ""


def releve(chaine: str = CHAINE) -> dict:
    quand = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        vivant, video = en_direct(page(LIVE_URL.format(chaine=chaine)))
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
