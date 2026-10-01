"""Ramasse de la musique libre sur Dogmazic pour la diffusion.

Il ne peut pas y avoir que notre musique à l'antenne. Dogmazic est une
médiathèque libre francophone qui tient depuis vingt ans, et son catalogue est
consultable sans compte : chaque morceau y porte sa licence, écrite en toutes
lettres dans la page, et c'est la seule raison pour laquelle on peut s'en
servir. Un flux qui diffuse doit pouvoir dire sous quelle licence, pour chaque
titre, à chaque instant.

CE QUI EST REFUSÉ, ET POURQUOI
------------------------------
Dix-sept revendications Content ID sont tombées sur une diffusion archivée, et
toutes venaient de disques du commerce mélangés dans des DJ sets récoltés
ailleurs. La leçon n'est pas « faire attention » : c'est qu'une déclaration de
licence posée sur un mix ne couvre que le travail du mixeur, jamais les disques
qui passent dessous. On refuse donc :

- tout ce qui porte « nc » : pas d'usage commercial. Une chaîne peut être
  monétisée un jour, et surtout YouTube pose de la publicité sans nous
  demander. Le doute suffit à écarter ;
- tout ce qui porte « nd » : pas de modification. Or on coupe les morceaux en
  tranches et on baisse le son sous la voix, ce qui en est une ;
- les mixes et les sets, par leur titre comme par leur durée ;
- tout ce dont on n'a pas su lire la licence. Par défaut on refuse : une
  licence qu'on ne comprend pas n'est pas une autorisation.

Ce qui reste — CC BY, CC BY-SA, CC0, domaine public, Licence Art Libre —
autorise la diffusion commerciale et la modification, à charge de citer. La
citation est déjà à l'écran : le flux affiche en permanence l'auteur, le titre
et la licence du morceau en cours.

    .venv/bin/python -m scripts.musique_dogmazic --minutes 420
    .venv/bin/python -m scripts.musique_dogmazic --minutes 420 --essai
"""

from __future__ import annotations

import argparse
import html
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SITE = "https://play.dogmazic.net"
NAVIGATEUR = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# La famille électronique, telle que le site la range. Les nombres sont ceux du
# catalogue au premier octobre ; ils servent à savoir où chercher, pas à être
# exacts.
GENRES = [
    "Electro", "Electro Expérimentale", "Ambient", "Techno", "Trip-Hop",
    "Dub", "House", "Electro-acoustique", "Drum n Bass", "Big Beat",
    "Electro Ethnic", "Trance", "Electronic", "electronica", "Ambiant",
    "Easy Listening", "Glitch", "Chill", "Deep techno", "IDM", "Avantgarde",
]
# Celui-là est un piège : c'est un genre qui rassemble des mixes.
GENRE_INTERDIT = "mix de musique libre"

# Les morceaux trop courts ne sont pas des morceaux, les trop longs sont des
# sets. Dix minutes est aussi la frontière que la diffusion emploie entre un
# « morceau » et un « set » : en restant dessous, ce qu'on ramasse passe dans
# le paquet qui tourne le jour, qui est celui qu'on veut nourrir.
COURT_MIN_S = 60.0
LONG_MAX_S = 600.0

# Les mots qui disent un mix. « remix » en fait partie à dessein : un remix
# peut tenir une voix du commerce, et on ne saura pas laquelle avant qu'une
# revendication tombe.
MOTS_DE_MIX = ("mix", "dj ", "djset", "liveset", "live set", "podcast",
               "mixtape", "megamix", "session", "set vol")


def page(url: str, essais: int = 3) -> str:
    """Une page, avec deux reprises. Le serveur est petit, on n'insiste pas."""
    souci: Exception | None = None
    for tour in range(essais):
        try:
            requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
            with urllib.request.urlopen(requete, timeout=30) as reponse:
                return reponse.read().decode("utf-8", "replace")
        except Exception as erreur:  # réseau, 500, délai
            souci = erreur
            time.sleep(1.5 * (tour + 1))
    raise RuntimeError(f"{url} : {souci}")


def _champ(ligne: str, classe: str) -> str:
    """Le texte d'une cellule, titre de lien compris, sans balises."""
    trouve = re.search(rf'<td class="{classe}"[^>]*>(.*?)</td>', ligne, re.S)
    if not trouve:
        return ""
    dedans = trouve.group(1)
    titre = re.search(r'title="([^"]*)"', dedans)
    texte = titre.group(1) if titre else re.sub(r"<[^>]+>", " ", dedans)
    return html.unescape(texte).strip()


def _titre(ligne: str) -> str:
    """Le titre seul, pris dans le texte du lien et non dans son infobulle.

    L'infobulle vaut « Artiste - Titre », et comme l'artiste est déjà lu dans
    sa propre cellule, s'en servir afficherait « Aloges — Aloges - Solitude »
    sur toute la largeur du bandeau.
    """
    trouve = re.search(r'<td class="cel_song"[^>]*>.*?<a [^>]*>(.*?)</a>', ligne, re.S)
    if not trouve:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", " ", trouve.group(1))).strip()


def _licence(ligne: str) -> tuple[str, str]:
    """Le nom de la licence et son adresse, telles que la page les donne."""
    trouve = re.search(r'<td class="cel_license"[^>]*>(.*?)</td>', ligne, re.S)
    if not trouve:
        return "", ""
    dedans = trouve.group(1)
    lien = re.search(r'href="([^"]*)"', dedans)
    nom = html.unescape(re.sub(r"<[^>]+>", " ", dedans)).strip()
    return nom, html.unescape(lien.group(1)) if lien else ""


def _secondes(duree: str) -> float:
    """« 6:04 » ou « 1:06:04 » en secondes ; zéro si ce n'est pas une durée."""
    bouts = duree.strip().split(":")
    if not bouts or not all(b.strip().isdigit() for b in bouts):
        return 0.0
    total = 0.0
    for bout in bouts:
        total = total * 60 + int(bout)
    return total


def licence_libre(nom: str, url: str) -> bool:
    """Cette licence autorise-t-elle ce qu'on fait : diffuser et découper ?

    On lit le nom et l'adresse ensemble, parce que l'un rattrape l'autre : le
    nom dit « Creative Commons - by-nc 2.0 » et l'adresse dit
    « /licenses/by-nc/2.0/ », et il suffit que l'un des deux porte la mention.

    Toute licence qu'on ne sait pas lire est refusée. C'est le sens du dernier
    « False » : une licence qu'on ne comprend pas n'est pas une autorisation,
    et il y a assez de catalogue pour pouvoir se permettre d'être bête.
    """
    texte = f"{nom} {url}".lower()
    if not texte.strip():
        return False
    # La « Licence C reaction » est une licence maison du site, qui restreint
    # l'usage commercial. Elle n'a pas de forme « by-** » et passerait donc à
    # travers la lecture des sigles.
    if "c reaction" in texte or "créaction" in texte or "creaction" in texte:
        return False
    sigles = re.findall(r"\bby(?:-(?:nc|nd|sa)){0,3}\b", texte)
    if sigles:
        parts = {p for sigle in sigles for p in sigle.split("-")}
        return "nc" not in parts and "nd" not in parts
    return any(mot in texte for mot in
               ("cc0", "public domain", "domaine public", "art libre",
                "licenceartlibre", "artlibre", "lal 1.3"))


def sent_le_mix(titre: str, album: str, genres: str) -> bool:
    """Un mix tient des disques du commerce, quoi qu'annonce sa licence.

    La déclaration posée sur un DJ set couvre le travail du mixeur et rien
    d'autre ; Content ID, lui, reconnaît chaque disque passé dessous. C'est
    exactement ce qui a coûté dix-sept revendications.
    """
    texte = f"{titre} {album} {genres}".lower()
    if GENRE_INTERDIT in texte:
        return True
    return any(mot in texte for mot in MOTS_DE_MIX)


def morceaux_du_genre(genre: str, depuis: int = 0, combien: int = 50) -> list[dict]:
    """Une page de résultats pour un genre, lue telle quelle."""
    url = (f"{SITE}/search.php?type=song&action=search&rule_1=tag"
           f"&rule_1_operator=4&rule_1_input={urllib.parse.quote(genre)}"
           f"&offset={depuis}&limit={combien}")
    corps = page(url)
    trouves = []
    for ligne in re.split(r'<tr id="song_', corps)[1:]:
        numero = re.match(r"(\d+)", ligne)
        if not numero:
            continue
        nom_licence, url_licence = _licence(ligne)
        trouves.append({
            "id": int(numero.group(1)),
            "titre": _titre(ligne),
            "auteur": _champ(ligne, "cel_artist"),
            "album": _champ(ligne, "cel_album"),
            "genres": _champ(ligne, "cel_tags"),
            "duree": _secondes(_champ(ligne, "cel_time")),
            "licence": nom_licence,
            "url_licence": url_licence,
            "genre_cherche": genre,
        })
    return trouves


def retenu(fiche: dict) -> str:
    """Vide si on le garde, sinon la raison du refus — pour pouvoir la lire."""
    if not licence_libre(fiche["licence"], fiche["url_licence"]):
        return f"licence « {fiche['licence'] or 'absente'} »"
    if sent_le_mix(fiche["titre"], fiche["album"], fiche["genres"]):
        return "sent le mix"
    if not fiche["titre"] or not fiche["auteur"]:
        return "sans titre ou sans auteur"
    if fiche["duree"] < COURT_MIN_S:
        return f"{fiche['duree']:.0f} s, trop court"
    if fiche["duree"] > LONG_MAX_S:
        return f"{fiche['duree'] / 60:.0f} min, trop long"
    return ""


def moisson(minutes: float, par_genre: int = 150, journal=print) -> list[dict]:
    """Parcourt les genres jusqu'à tenir la durée demandée.

    Un genre après l'autre et non tout le catalogue d'un coup : ça donne un
    mélange, là où quinze cents morceaux d'« Electro » lus dans l'ordre
    donneraient surtout le même artiste quinze fois.
    """
    gardes: list[dict] = []
    vus: set[int] = set()
    refus: dict[str, int] = {}
    total = 0.0
    for genre in GENRES:
        if total >= minutes * 60:
            break
        pris_ici = 0
        for depuis in range(0, par_genre, 50):
            if total >= minutes * 60 or pris_ici >= 40:
                break
            try:
                lot = morceaux_du_genre(genre, depuis)
            except RuntimeError as souci:
                journal(f"  {genre} : {souci}")
                break
            if not lot:
                break
            for fiche in lot:
                if fiche["id"] in vus:
                    continue
                vus.add(fiche["id"])
                pourquoi = retenu(fiche)
                if pourquoi:
                    refus[pourquoi.split(" «")[0]] = refus.get(pourquoi.split(" «")[0], 0) + 1
                    continue
                gardes.append(fiche)
                pris_ici += 1
                total += fiche["duree"]
            # On ne martèle pas un serveur associatif.
            time.sleep(0.8)
        journal(f"  {genre:22s} {pris_ici:3d} gardés, {total / 60:6.1f} min au total")
    journal(f"  refusés : {dict(sorted(refus.items(), key=lambda c: -c[1]))}")
    return gardes


def rapatrie(fiche: dict, dossier: Path) -> Path | None:
    """Le fichier lui-même. Rend None si le téléchargement n'aboutit pas."""
    cible = dossier / f"dogmazic-{fiche['id']:06d}.mp3"
    if cible.is_file() and cible.stat().st_size > 100_000:
        return cible
    url = f"{SITE}/stream.php?action=download&song_id={fiche['id']}"
    try:
        requete = urllib.request.Request(url, headers={"User-Agent": NAVIGATEUR})
        with urllib.request.urlopen(requete, timeout=120) as reponse:
            octets = reponse.read()
    except Exception:
        return None
    # Un fichier trop petit n'est pas un morceau : c'est une page d'erreur
    # renvoyée avec un code 200, ce que ce genre de site fait volontiers.
    if len(octets) < 100_000:
        return None
    cible.write_bytes(octets)
    return cible


def ecris_credits(dossier: Path, fiches: list[dict]) -> None:
    """Ajoute aux crédits sans effacer les nôtres.

    Le flux lit ce fichier pour afficher l'auteur, le titre et la licence du
    morceau en cours. C'est la contrepartie de la licence, et elle n'a de sens
    que si elle est juste : on n'écrit donc que ce que la page a dit.
    """
    chemin = dossier / "credits.json"
    try:
        tout = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tout = {}
    for fiche in fiches:
        if not fiche.get("fichier"):
            continue
        tout[Path(fiche["fichier"]).name] = {
            "auteur": fiche["auteur"],
            "titre": fiche["titre"],
            "licence": fiche["licence"],
            "url": f"{SITE}/song.php?action=show_song&song_id={fiche['id']}",
            "url_licence": fiche["url_licence"],
            "source": "Dogmazic",
        }
    chemin.write_text(json.dumps(tout, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")


def main() -> int:
    partie = argparse.ArgumentParser(description=__doc__)
    partie.add_argument("--minutes", type=float, default=420.0,
                        help="durée visée, en minutes de musique")
    partie.add_argument("--dossier", default="data/musique")
    partie.add_argument("--essai", action="store_true",
                        help="lire et trier sans rien télécharger")
    partie.add_argument("--graine", type=int, default=None)
    args = partie.parse_args()

    dossier = ROOT / args.dossier
    dossier.mkdir(parents=True, exist_ok=True)
    print(f"Lecture du catalogue pour {args.minutes:.0f} min de musique")
    fiches = moisson(args.minutes)
    random.Random(args.graine).shuffle(fiches)
    duree = sum(f["duree"] for f in fiches)
    print(f"{len(fiches)} morceaux retenus, {duree / 60:.0f} min")
    if args.essai:
        for fiche in fiches[:20]:
            print(f"  {fiche['auteur'][:24]:24s} · {fiche['titre'][:34]:34s} "
                  f"· {fiche['duree'] / 60:4.1f} min · {fiche['licence']}")
        return 0

    pris = 0
    for fiche in fiches:
        chemin = rapatrie(fiche, dossier)
        if chemin is None:
            print(f"  échec : {fiche['auteur']} — {fiche['titre']}")
            continue
        fiche["fichier"] = str(chemin)
        pris += 1
        if pris % 10 == 0:
            print(f"  {pris} morceaux sur le disque")
        time.sleep(0.5)
    ecris_credits(dossier, fiches)
    gardes = [f for f in fiches if f.get("fichier")]
    print(f"{pris} morceaux téléchargés, "
          f"{sum(f['duree'] for f in gardes) / 60:.0f} min de Dogmazic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
