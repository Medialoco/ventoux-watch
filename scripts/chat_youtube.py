"""Lit le chat du direct, sans compte et sans clé.

Le chat est le seul endroit d'où quelqu'un qui regarde peut dire au flux ce
qu'il voit. « Fog is back » vaut une mesure : la caméra lit une image, le
spectateur lit la montagne, et quand les deux divergent c'est la caméra qui a
tort — c'est elle qui est derrière la vitre.

Rien ici n'est officiel. YouTube sert la page du direct avec une clé publique
et un jeton de continuation dedans ; on les reprend tels quels et on interroge
le même point d'entrée que le navigateur. Ça marche parce que le direct est
public, et ça cesserait de marcher si YouTube changeait sa page — auquel cas on
n'aurait rien perdu, puisque personne ne dépend de ce fichier pour diffuser.

    .venv/bin/python -m scripts.chat_youtube
    .venv/bin/python -m scripts.chat_youtube --suit 300
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NAVIGATEUR = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
INNERTUBE = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key="


def _lis(url: str, corps: bytes | None = None) -> str:
    entetes = {"User-Agent": NAVIGATEUR}
    if corps is not None:
        entetes["Content-Type"] = "application/json"
    requete = urllib.request.Request(url, data=corps, headers=entetes)
    with urllib.request.urlopen(requete, timeout=25) as reponse:
        return reponse.read().decode("utf-8", "replace")


def en_direct(chaine: str) -> str | None:
    """L'identifiant de la vidéo en cours, ou None si la chaîne n'émet pas."""
    page = _lis(f"https://www.youtube.com/channel/{chaine}/live")
    if "videoDetails" not in page or '"isLive":true' not in page:
        return None
    trouve = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', page)
    return trouve.group(1) if trouve else None


def _amorce(video: str) -> tuple[str, str, str]:
    """La clé publique, la version du client et le premier jeton."""
    page = _lis(f"https://www.youtube.com/watch?v={video}")
    cle = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
    version = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', page)
    jeton = re.search(r'"liveChatRenderer":\{"continuations":\[\{'
                      r'"reloadContinuationData":\{"continuation":"([^"]+)"', page)
    if not (cle and version and jeton):
        raise RuntimeError("pas de chat sur cette vidéo "
                           "(direct terminé, chat désactivé, ou page changée)")
    return cle.group(1), version.group(1), jeton.group(1)


def _messages(bloc: dict) -> tuple[list[dict], str | None, float]:
    """Les messages d'une réponse, le jeton suivant, et le délai demandé."""
    suite = (bloc.get("continuationContents") or {}).get("liveChatContinuation") or {}
    dits = []
    for action in suite.get("actions") or []:
        objet = (action.get("addChatItemAction") or {}).get("item") or {}
        texte = objet.get("liveChatTextMessageRenderer")
        if not texte:
            continue
        mots = "".join(morceau.get("text", "")
                       for morceau in (texte.get("message") or {}).get("runs", []))
        if not mots.strip():
            continue
        dits.append({
            "qui": (texte.get("authorName") or {}).get("simpleText", "?"),
            "quoi": mots.strip(),
            "quand": int(texte.get("timestampUsec", 0)) / 1e6,
        })
    jeton = attente = None
    for suivant in suite.get("continuations") or []:
        for forme in ("invalidationContinuationData", "timedContinuationData",
                      "reloadContinuationData"):
            donnee = suivant.get(forme)
            if donnee:
                jeton = donnee.get("continuation")
                attente = donnee.get("timeoutMs")
    return dits, jeton, max(2.0, (attente or 5000) / 1000.0)


def suit(video: str, secondes: float = 0.0, journal=print) -> list[dict]:
    """Les messages du chat, une fois ou pendant un moment."""
    cle, version, jeton = _amorce(video)
    contexte = {"client": {"clientName": "WEB", "clientVersion": version}}
    debut = time.time()
    tout: list[dict] = []
    while True:
        corps = json.dumps({"context": contexte, "continuation": jeton}).encode()
        bloc = json.loads(_lis(INNERTUBE + cle, corps))
        dits, jeton, attente = _messages(bloc)
        for dit in dits:
            journal(f"  {time.strftime('%H:%M:%S', time.localtime(dit['quand']))} "
                    f"{dit['qui']} : {dit['quoi']}")
        tout += dits
        if jeton is None or time.time() - debut >= secondes:
            return tout
        time.sleep(attente)


def main() -> int:
    partie = argparse.ArgumentParser(description=__doc__)
    partie.add_argument("--chaine", default="UCvN0sNcj5JM9tklIkAlGi7g")
    partie.add_argument("--video", default=None,
                        help="par défaut, le direct en cours de la chaîne")
    partie.add_argument("--suit", type=float, default=0.0,
                        help="rester à l'écoute pendant tant de secondes")
    args = partie.parse_args()

    video = args.video or en_direct(args.chaine)
    if video is None:
        print("La chaîne n'est pas en direct.")
        return 1
    print(f"Chat de https://www.youtube.com/live/{video}")
    dits = suit(video, args.suit)
    if not dits:
        print("  (rien dans la fenêtre lue)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
