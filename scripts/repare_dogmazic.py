#!/usr/bin/env python3
"""Répare les seize morceaux déposés sans étiquettes sur Dogmazic.

Les fichiers envoyés n'avaient aucune étiquette ID3, alors Ampache s'est
rabattu sur le nom de fichier : seize titres « ventoux-002-01 » attribués à
« Inconnu (orphelin) ». La licence, elle, est bonne — c'est le seul champ
qu'on ait saisi à la main.

Ce script essaie de réparer tout seul, puis dit franchement ce qu'il n'a pas
pu faire. Il ne se connecte jamais au compte : il n'a que la clé d'API, qui
donne le niveau d'accès 25. Ampache exige 50 pour relire les étiquettes d'un
morceau et 75 pour en supprimer un, donc il est probable qu'il échoue — mais
ces seuils dépendent de la configuration du serveur, pas de la version
d'Ampache, et la seule façon de savoir est de demander.

Le site tombe régulièrement. Plutôt que de rendre la main sur une erreur
réseau, le script attend qu'il revienne.

    python3 scripts/repare_dogmazic.py
    python3 scripts/repare_dogmazic.py --attends 7200   (patiente deux heures)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://play.dogmazic.net/server/json.server.php"
API_VERSION = "6.0.0"
NAVIGATEUR = "ventoux-watch/1.0 (+https://medialoco.github.io/ventoux-watch/)"
MAISON = "thepriben"
PATIENCE_S = 300.0
ALBUM = "Mont Serein 002"
GENRE = "Techno"
ANNEE = "2026"
# Les seize dépôts, du titre qu'ils devraient porter vers leur identifiant
# Dogmazic. L'ordre des identifiants n'est pas celui des pistes : le serveur
# les a numérotés dans l'ordre où il a fini de les recevoir.
DEPOTS = {
    "Mont Serein 002.01": 68581, "Mont Serein 002.02": 68578,
    "Mont Serein 002.03": 68579, "Mont Serein 002.04": 68580,
    "Mont Serein 002.05": 68582, "Mont Serein 002.06": 68584,
    "Mont Serein 002.07": 68583, "Mont Serein 002.08": 68587,
    "Mont Serein 002.09": 68585, "Mont Serein 002.10": 68586,
    "Mont Serein 002.11": 68590, "Mont Serein 002.12": 68588,
    "Mont Serein 002.13": 68589, "Mont Serein 002.14": 68591,
    "Mont Serein 002.15": 68593, "Mont Serein 002.16": 68592,
}
# Les actions qui pourraient réparer, de la plus douce à la plus brutale.
# « update_from_tags » suffirait si on pouvait remplacer le fichier ;
# « song_delete » permettrait de tout renvoyer proprement.
REPARATIONS = (
    ("edit_object", {"type": "song", "name": ""}),
    ("update_object", {"type": "song"}),
    ("update_from_tags", {"type": "song"}),
    ("song_delete", {}),
)


def cle() -> str:
    """La clé de lecture, qui n'est jamais écrite nulle part."""
    try:
        local = json.loads(
            (ROOT / "config" / "local.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str((local.get("dogmazic") or {}).get("api_key") or "")


def appelle(**parametres) -> dict:
    """Une question à Ampache. Les erreurs métier arrivent en JSON, pas en
    exception : un refus d'accès est une réponse valide qu'on veut lire."""
    url = API + "?" + urllib.parse.urlencode(parametres)
    requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
    try:
        with urllib.request.urlopen(requete, timeout=60) as reponse:
            return json.load(reponse)
    except urllib.error.HTTPError as souci:
        try:
            return json.load(souci)
        except ValueError:
            return {"erreur_reseau": f"HTTP {souci.code}"}
    except Exception as souci:
        return {"erreur_reseau": type(souci).__name__}


def session(patience: float) -> str:
    """Un jeton, en attendant que le site revienne s'il est tombé."""
    fin = time.time() + patience
    prevenu = False
    while True:
        reponse = appelle(action="handshake", auth=cle(), version=API_VERSION)
        jeton = str(reponse.get("auth") or "")
        if jeton:
            if prevenu:
                print("Le site est revenu.")
            return jeton
        if "erreur_reseau" not in reponse:
            print("Dogmazic refuse la clé :",
                  (reponse.get("error") or {}).get("errorMessage", reponse))
            return ""
        if time.time() > fin:
            return ""
        if not prevenu:
            print("Dogmazic est injoignable. J'attends qu'il revienne…")
            prevenu = True
        # Cinq minutes, pas trente secondes. Si le silence vient d'un
        # bannissement et non d'une panne — c'est arrivé, pour avoir
        # téléchargé cent cinquante pochettes d'affilée — alors insister
        # ressemble à la raison du bannissement et le prolonge.
        time.sleep(PATIENCE_S)


def refus(reponse: dict) -> str:
    """Ce qu'Ampache reproche, en une ligne, ou rien s'il a accepté."""
    if "erreur_reseau" in reponse:
        return str(reponse["erreur_reseau"])
    erreur = reponse.get("error") or {}
    if erreur:
        return f"{erreur.get('errorMessage', '?')} ({erreur.get('errorCode', '?')})"
    return ""


def repare(jeton: str, titre: str, numero: int) -> bool:
    """Essaie de rendre son nom à un morceau. Vrai si quelque chose a pris."""
    for action, gabarit in REPARATIONS:
        champs = dict(gabarit)
        if action == "song_delete":
            champs["filter"] = str(numero)
        else:
            champs["id"] = str(numero)
        if action == "edit_object":
            champs.update(name=titre, artist=MAISON, album=ALBUM,
                          genre=GENRE, year=ANNEE)
        reponse = appelle(action=action, auth=jeton, **champs)
        souci = refus(reponse)
        if not souci:
            print(f"  {titre} : « {action} » a été accepté.")
            return True
        print(f"  {titre} : {action} refusé — {souci}")
        time.sleep(0.5)
    return False


def main() -> int:
    plaidoyer = argparse.ArgumentParser(description=__doc__)
    plaidoyer.add_argument("--attends", type=float, default=600.0,
                           help="secondes à patienter si le site est tombé")
    options = plaidoyer.parse_args()
    if not cle():
        print("Pas de clé Dogmazic dans config/local.json.")
        return 1
    jeton = session(options.attends)
    if not jeton:
        print("Pas de session : rien n'est possible pour l'instant.")
        return 1

    niveau = ((appelle(action="user", auth=jeton, username=MAISON)
               or {}).get("access"))
    print(f"Compte {MAISON}, niveau d'accès {niveau}.")
    # Un seul morceau d'abord. Si aucune action ne passe sur celui-là, les
    # quinze autres donneront le même refus et insister ne ferait que des
    # lignes de journal chez des bénévoles.
    premier = next(iter(DEPOTS.items()))
    print(f"Essai sur un seul morceau ({premier[0]}) :")
    if not repare(jeton, *premier):
        print("\nAucune action d'écriture ne passe avec cette clé.")
        print("La réparation demande soit votre session sur le site, soit un")
        print("mot à l'association. Le détail est dans :")
        print("  ~/Desktop/Mont Serein 002/A FAIRE SUR DOGMAZIC.md")
        return 2
    for titre, numero in list(DEPOTS.items())[1:]:
        repare(jeton, titre, numero)
    return 0


if __name__ == "__main__":
    sys.exit(main())
