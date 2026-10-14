"""Publie sur Dogmazic la liste de ce que la radio passe réellement.

La chaîne affiche en permanence l'auteur, le titre et la licence du morceau en
cours : c'est ce que la licence exige et c'est fait. Mais quelqu'un qui entend
quelque chose qui lui plaît à trois heures du matin n'a aucun moyen de
retrouver le reste. Une playlist chez l'hébergeur même de la musique le lui
donne : les morceaux s'y écoutent en entier, chez ceux qui les hébergent, et
chaque auteur y est rendu à son catalogue plutôt qu'à une ligne de crédit.

Elle est bâtie depuis la bibliothèque du Pi et non depuis une liste tenue à la
main : ce qui est publié est exactement ce qui tourne. Les morceaux de la
maison y entrent aussi — ils sont sur Dogmazic comme les autres, et les
distinguer n'aurait aucun sens pour qui écoute.

Idempotent : relancé, il retrouve sa playlist par son nom et la remet à jour
au lieu d'en créer une seconde.

    .venv/bin/python scripts/dogmazic_playlist.py
    .venv/bin/python scripts/dogmazic_playlist.py --essai
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher.config import load_config  # noqa: E402

API = "https://play.dogmazic.net/server/json.server.php"
NAVIGATEUR = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

NOM = "Ventoux Watch — la webradio du Mont Serein"
FICHE_JSON = "data/dogmazic_playlist.json"
# L'album de la maison, dont les fichiers ne portent pas l'identifiant Dogmazic
# dans leur nom puisqu'ils ont été déposés à la main.
ALBUM_MAISON = "11242"


class Dogmazic:
    def __init__(self, cle: str) -> None:
        self._jeton = self._appel(action="handshake", auth=cle, version="6.0.0").get("auth")
        if not self._jeton:
            raise RuntimeError("Dogmazic a refusé la poignée de main")

    @staticmethod
    def _appel(**parametres) -> dict:
        requete = urllib.request.Request(API + "?" + urllib.parse.urlencode(parametres),
                                         headers={"User-Agent": NAVIGATEUR})
        with urllib.request.urlopen(requete, timeout=90) as reponse:
            return json.loads(reponse.read().decode("utf-8", "replace"))

    def fais(self, action: str, **parametres) -> dict:
        return self._appel(action=action, auth=self._jeton, **parametres)

    def mienne(self, nom: str) -> dict | None:
        """La playlist de ce nom qui nous appartient, si elle existe déjà.

        Dogmazic range le nom sous la forme « nom (propriétaire) » : on compare
        donc le début, et on vérifie le propriétaire à part.
        """
        for page in range(0, 2000, 200):
            lot = self.fais("playlists", limit=200, offset=page).get("playlist") or []
            for liste in lot:
                porte = str(liste.get("name") or "")
                if liste.get("owner") == "thepriben" and porte.startswith(nom):
                    return liste
            if len(lot) < 200:
                return None
        return None


def chansons_de_la_bibliotheque(site: Dogmazic, dossier: Path) -> list[tuple[int, str]]:
    """Les identifiants Dogmazic de tout ce qui est installé, avec leur titre.

    Deux sources, parce qu'il y a deux façons dont un fichier est arrivé là :
    les récoltes portent l'identifiant dans leur nom, l'album de la maison a
    été déposé à la main et se retrouve par son album.
    """
    try:
        credits = json.loads((dossier / "credits.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        credits = {}
    trouves: dict[int, str] = {}
    for fichier in sorted(dossier.glob("dogmazic-*.mp3")):
        numero = re.match(r"dogmazic-(\d+)", fichier.stem)
        if not numero:
            continue
        fiche = credits.get(fichier.name) or {}
        trouves[int(numero.group(1))] = (f"{fiche.get('auteur', '?')} — "
                                         f"{fiche.get('titre', fichier.stem)}")
    maison = site.fais("album_songs", filter=ALBUM_MAISON, limit=100).get("song") or []
    presents = {p.name for p in dossier.glob("ventoux-*.mp3")}
    for chanson in maison:
        if not presents:
            break
        trouves[int(chanson["id"])] = (f"{(chanson.get('artist') or {}).get('name', '?')} — "
                                       f"{chanson.get('title', '?')}")
    return sorted(trouves.items())


def ids_playlist(site: Dogmazic, identifiant: str) -> set[int]:
    """Tous les morceaux d'une playlist, paginés."""
    vus: set[int] = set()
    for page in range(0, 5000, 500):
        lot = site.fais("playlist_songs", filter=identifiant, limit=500, offset=page).get("song") or []
        if isinstance(lot, dict):
            lot = [lot]
        if not lot:
            break
        for chanson in lot:
            try:
                vus.add(int(chanson["id"]))
            except (KeyError, TypeError, ValueError):
                continue
        if len(lot) < 500:
            break
    return vus


def publie_fiche(
    racine: Path,
    *,
    identifiant: str,
    nom: str,
    installés: int,
    items: int,
    à_jour: bool,
) -> None:
    url = f"https://play.dogmazic.net/playlist.php?action=show_playlist&playlist_id={identifiant}"
    corps = {
        "playlist_id": int(identifiant),
        "url": url,
        "nom": nom,
        "installés": installés,
        "items": items,
        "à_jour": à_jour,
        "vu": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    fichier = racine / FICHE_JSON
    fichier.parent.mkdir(parents=True, exist_ok=True)
    passage = fichier.with_suffix(".json.tmp")
    passage.write_text(json.dumps(corps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    passage.replace(fichier)


def main() -> int:
    partie = argparse.ArgumentParser(description=__doc__)
    partie.add_argument("--dossier", default="data/musique")
    partie.add_argument("--nom", default=NOM)
    partie.add_argument("--essai", action="store_true",
                        help="montrer ce qui serait publié, sans rien écrire")
    partie.add_argument("--retire", type=int, default=0,
                        help="retirer ce numéro de la playlist existante, sans la recréer")
    partie.add_argument(
        "--verifie",
        action="store_true",
        help="ne recréer la playlist que si elle ne reflète plus la bibliothèque",
    )
    args = partie.parse_args()

    cle = (load_config().get("dogmazic") or {}).get("api_key") or ""
    if not cle:
        print("Pas de clé Dogmazic dans config/local.json", file=sys.stderr)
        return 1
    site = Dogmazic(cle)
    dossier = ROOT / args.dossier
    chansons = chansons_de_la_bibliotheque(site, dossier)
    attendus = {identifiant for identifiant, _ in chansons}
    print(f"{len(chansons)} morceaux installés et retrouvés sur Dogmazic")
    for identifiant, nom in chansons[:6]:
        print(f"   {identifiant:>7}  {nom[:60]}")
    if len(chansons) > 6:
        print(f"   … et {len(chansons) - 6} autres")
    if args.essai:
        print("\nEssai : rien n'a été écrit.")
        return 0

    existante = site.mienne(args.nom)
    if args.verifie and existante is not None and not args.retire:
        identifiant = str(existante["id"])
        en_ligne = ids_playlist(site, identifiant)
        if en_ligne == attendus:
            items = int(existante.get("items") or len(en_ligne))
            publie_fiche(
                ROOT,
                identifiant=identifiant,
                nom=args.nom,
                installés=len(chansons),
                items=items,
                à_jour=True,
            )
            print(f"playlist {identifiant} déjà à jour ({len(en_ligne)} morceaux)")
            print(f"https://play.dogmazic.net/playlist.php?action=show_playlist&playlist_id={identifiant}")
            return 0
        print(f"playlist {identifiant} : {len(en_ligne)} en ligne, {len(attendus)} installés — mise à jour")
    if args.retire:
        if existante is None:
            print("playlist introuvable", file=sys.stderr)
            return 1
        identifiant = str(existante["id"])
        reponse = site.fais("playlist_remove_song", filter=identifiant,
                            song=str(args.retire))
        relu = site.fais("playlist_songs", filter=identifiant, limit=500)
        chansons = relu.get("song") or []
        if isinstance(chansons, dict):
            chansons = [chansons]
        reste = [int(c.get("id")) for c in chansons]
        encore = int(args.retire) in reste
        print(f"playlist {identifiant} : retire {args.retire}, "
              f"{len(reste)} morceaux, encore présent : {encore}")
        if encore:
            print("retrait incomplet :", reponse.get("error") or "sans détail")
        return 0 if not encore else 1
    if existante is not None:
        # Repartir de zéro plutôt que de chercher ce qui manque : la playlist
        # doit dire ce qui tourne aujourd'hui, et un morceau retiré de la
        # bibliothèque doit en sortir.
        site.fais("playlist_delete", filter=str(existante["id"]))
        print(f"ancienne playlist {existante['id']} retirée")
    cree = site.fais("playlist_create", name=args.nom, type="public")
    identifiant = str(cree.get("id") or "")
    if not identifiant:
        print(f"création refusée : {cree}", file=sys.stderr)
        return 1
    ajoutes = 0
    for chanson, _ in chansons:
        reponse = site.fais("playlist_add_song", filter=identifiant, song=str(chanson))
        if reponse.get("success"):
            ajoutes += 1
    relu = site.fais("playlist", filter=identifiant)
    items = int(relu.get("items") or ajoutes)
    publie_fiche(
        ROOT,
        identifiant=identifiant,
        nom=args.nom,
        installés=len(chansons),
        items=items,
        à_jour=True,
    )
    print(f"playlist {identifiant} : {ajoutes} ajouts, {items} morceaux dedans")
    print(f"https://play.dogmazic.net/playlist.php?action=show_playlist&playlist_id={identifiant}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
