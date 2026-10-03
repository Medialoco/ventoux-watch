"""Les morceaux les plus écoutés de Dogmazic, dans les genres où l'on danse.

La récolte habituelle tire au hasard dans le catalogue et garde ce qui pulse,
mesure à l'appui. C'est bien pour remplir quatorze heures sans se répéter, et
ça ignore complètement une information que le site tient pourtant : combien de
fois chaque morceau a été écouté. Vingt ans de médiathèque, soixante et un
mille morceaux, et quelques-uns que les gens sont revenus écouter mille fois.

Ici on demande ceux-là. Par l'API d'Ampache et non en grattant les pages : elle
donne le nombre d'écoutes et l'adresse de la licence morceau par morceau, ce
qui est précisément ce dont la décision a besoin.

Les refus sont les mêmes qu'ailleurs et pour les mêmes raisons — pas de « nc »,
pas de « nd », pas de mix, pas de licence illisible, et jamais un auteur déjà
revendiqué sur YouTube. Être le plus écouté n'autorise rien de plus.

    .venv/bin/python scripts/dogmazic_ecoutes.py --combien 10
    .venv/bin/python scripts/dogmazic_ecoutes.py --combien 10 --essai
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.musique_dogmazic import (  # noqa: E402
    LONG_MAX_S, SITE, ecris_credits, rapatrie, retenu,
)
from watcher.config import load_config  # noqa: E402

API = "https://play.dogmazic.net/server/json.server.php"
NAVIGATEUR = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# Ce que « trance, tektonik, dance » désigne dans le rangement du site, avec le
# nombre de morceaux relevé le 3 octobre. Les identifiants sont ceux du
# catalogue ; les noms sont là pour qu'on relise la liste sans la deviner.
GENRES = {
    38: "Techno",
    29: "Hard Tek - Hardcore",
    39: "Trance",
    47: "Techno Punk",
    76: "dance",
    30: "House",
    61: "Deep techno",
    26: "Drum n Bass",
}

# De quoi rendre une adresse de licence lisible à l'écran. Le flux affiche ce
# nom en permanence pendant que le morceau passe : c'est la contrepartie de la
# licence, elle doit se lire.
NOMS = [
    ("artlibre", "Licence Art Libre"),
    ("publicdomain/zero", "CC0 1.0"),
    # L'adresse du formulaire qui a posé la licence, et non celle de son texte.
    # Creative Commons rend les deux ; seule la première se lit comme un sigle.
    ("choose/zero", "CC0 1.0"),
    ("publicdomain/mark", "Domaine public"),
]


def nom_de_licence(url: str) -> str:
    """Le nom à afficher, tiré de l'adresse et de rien d'autre.

    L'API ne donne que l'adresse. La déduire est sans risque parce que
    l'adresse est ce qui fait foi : c'est elle qu'on a lue pour accepter le
    morceau, et c'est elle qu'on enregistre à côté du nom.
    """
    bas = (url or "").lower()
    for morceau, nom in NOMS:
        if morceau in bas:
            return nom
    bouts = [b for b in bas.split("/") if b]
    for i, bout in enumerate(bouts):
        if bout == "licenses" and i + 2 < len(bouts):
            return f"CC {bouts[i + 1].upper()} {bouts[i + 2]}"
    return url or ""


class Dogmazic:
    """Une session d'API. Le jeton ne sort jamais de l'objet."""

    def __init__(self, cle: str) -> None:
        self._jeton = self._appel(action="handshake", auth=cle, version="6.0.0").get("auth")
        if not self._jeton:
            raise RuntimeError("Dogmazic a refusé la poignée de main")

    @staticmethod
    def _appel(**parametres) -> dict:
        url = API + "?" + urllib.parse.urlencode(parametres)
        requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
        with urllib.request.urlopen(requete, timeout=90) as reponse:
            return json.loads(reponse.read().decode("utf-8", "replace"))

    def morceaux_du_genre(self, identifiant: int, combien: int = 2500) -> list[dict]:
        """Tous les morceaux d'un genre, par paquets de cinq cents.

        Le serveur est petit et vingt ans de dépôts tiennent dedans : on ne lui
        demande pas deux mille morceaux d'un coup.
        """
        trouves: list[dict] = []
        while len(trouves) < combien:
            lot = self._appel(action="genre_songs", auth=self._jeton,
                              filter=str(identifiant), offset=len(trouves),
                              limit=500).get("song") or []
            trouves.extend(lot)
            if len(lot) < 500:
                break
        return trouves


def en_fiche(chanson: dict, genre: str) -> dict:
    """La forme que les filtres déjà écrits savent lire."""
    url_licence = str(chanson.get("license") or "")
    return {
        "id": int(chanson.get("id") or 0),
        "titre": str(chanson.get("title") or chanson.get("name") or ""),
        "auteur": str((chanson.get("artist") or {}).get("name") or ""),
        "album": str((chanson.get("album") or {}).get("name") or ""),
        "genres": ", ".join(str(g.get("name") or "") for g in (chanson.get("genre") or [])),
        "duree": float(chanson.get("time") or 0),
        "licence": nom_de_licence(url_licence),
        "url_licence": url_licence,
        "genre_cherche": genre,
        "ecoutes": int(chanson.get("playcount") or 0),
    }


def main() -> int:
    partie = argparse.ArgumentParser(description=__doc__)
    partie.add_argument("--combien", type=int, default=10)
    partie.add_argument("--dossier", default="data/musique")
    partie.add_argument("--essai", action="store_true",
                        help="choisir et montrer sans rien télécharger")
    partie.add_argument("--par-auteur", type=int, default=2,
                        help="au plus N morceaux du même auteur")
    args = partie.parse_args()

    cle = (load_config().get("dogmazic") or {}).get("api_key") or ""
    if not cle:
        print("Pas de clé Dogmazic dans config/local.json", file=sys.stderr)
        return 1
    site = Dogmazic(cle)

    tout: dict[int, dict] = {}
    for identifiant, nom in GENRES.items():
        lot = site.morceaux_du_genre(identifiant)
        for chanson in lot:
            fiche = en_fiche(chanson, nom)
            if fiche["id"] and fiche["id"] not in tout:
                tout[fiche["id"]] = fiche
        print(f"  {nom:22} {len(lot):5} morceaux lus")
    print(f"{len(tout)} morceaux distincts dans les genres de danse")

    dossier = ROOT / args.dossier
    deja = {int(p.stem.split("-")[1]) for p in dossier.glob("dogmazic-*.mp3")
            if p.stem.split("-")[-1].isdigit()}
    gardes, refus = [], {}
    par_auteur: dict[str, int] = {}
    for fiche in sorted(tout.values(), key=lambda f: -f["ecoutes"]):
        if fiche["id"] in deja:
            continue
        raison = retenu(fiche)
        if raison:
            refus[raison] = refus.get(raison, 0) + 1
            continue
        auteur = fiche["auteur"].strip().lower()
        if par_auteur.get(auteur, 0) >= args.par_auteur:
            continue
        par_auteur[auteur] = par_auteur.get(auteur, 0) + 1
        gardes.append(fiche)
        if len(gardes) >= args.combien:
            break

    print()
    print(f"{'écoutes':>8}  {'durée':>6}  {'auteur':24} {'titre':34} {'licence':22} genre")
    for fiche in gardes:
        print(f"{fiche['ecoutes']:8}  {fiche['duree'] / 60:5.1f}m  "
              f"{fiche['auteur'][:24]:24} {fiche['titre'][:34]:34} "
              f"{fiche['licence'][:22]:22} {fiche['genre_cherche']}")
    print()
    print("écartés :", ", ".join(f"{n} pour {r}" for r, n in
                                 sorted(refus.items(), key=lambda x: -x[1])[:6]))
    if args.essai:
        print()
        print("Essai : rien n'a été téléchargé.")
        return 0

    dossier.mkdir(parents=True, exist_ok=True)
    pris = []
    for fiche in gardes:
        chemin = rapatrie(fiche, dossier)
        if chemin is None:
            print(f"  échec : {fiche['auteur']} — {fiche['titre']}")
            continue
        fiche["fichier"] = str(chemin)
        pris.append(fiche)
        print(f"  {'pris' if fiche.get('telecharge') else 'déjà là'} : "
              f"{fiche['auteur']} — {fiche['titre']}")
    ecris_credits(dossier, pris)
    minutes = sum(f["duree"] for f in pris) / 60
    print(f"{len(pris)} morceaux, {minutes:.0f} min, crédits à jour.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
