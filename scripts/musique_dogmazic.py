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


def sent_le_dj(auteur: str) -> bool:
    """Le nom d'artiste annonce-t-il un platiniste ?

    Par mots entiers et non par morceaux de mots, contrairement au titre :
    « AlchimiX » contient « mix » et n'est pas un mix, alors que
    « Dj Pauly Beatz » est exactement ce qu'on cherche à éviter — son
    « Champion Sound » est passé par la première version de ce filtre, qui ne
    regardait que le titre et l'album.
    """
    return bool(re.search(r"\b(dj|mix|mixtape|liveset|megamix|set)\b",
                          (auteur or "").lower()))


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


# Les genres où l'on danse, parmi ceux que le site connaît. Ils servent à
# chercher moins loin, pas à décider : ce qui décide est la mesure. L'étiquette
# est posée à la main par qui dépose le fichier, et le même mot « Techno »
# couvre une transe à cent trente temps et un drone de vingt minutes.
GENRES_DANSE = ["Techno", "House", "Deep techno", "Trance", "Drum n Bass",
                "Big Beat", "Electro", "Electronic", "electronica"]


def retenu(fiche: dict, mini: float = COURT_MIN_S) -> str:
    """Vide si on le garde, sinon la raison du refus — pour pouvoir la lire."""
    if not licence_libre(fiche["licence"], fiche["url_licence"]):
        return f"licence « {fiche['licence'] or 'absente'} »"
    if sent_le_mix(fiche["titre"], fiche["album"], fiche["genres"]):
        return "sent le mix"
    if sent_le_dj(fiche["auteur"]):
        return "nom de platiniste"
    if not fiche["titre"] or not fiche["auteur"]:
        return "sans titre ou sans auteur"
    if fiche["duree"] < mini:
        return f"{fiche['duree'] / 60:.0f} min, trop court"
    if fiche["duree"] > LONG_MAX_S:
        return f"{fiche['duree'] / 60:.0f} min, trop long"
    return ""


def moisson(minutes: float, par_genre: int = 150, journal=print,
            genres: list[str] | None = None,
            mini: float = COURT_MIN_S) -> list[dict]:
    """Parcourt les genres jusqu'à tenir la durée demandée.

    Un genre après l'autre et non tout le catalogue d'un coup : ça donne un
    mélange, là où quinze cents morceaux d'« Electro » lus dans l'ordre
    donneraient surtout le même artiste quinze fois.
    """
    gardes: list[dict] = []
    vus: set[int] = set()
    refus: dict[str, int] = {}
    total = 0.0
    for genre in (genres or GENRES):
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
                pourquoi = retenu(fiche, mini)
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
    """Le fichier lui-même. Rend None si le téléchargement n'aboutit pas.

    Note au passage si le fichier était déjà là. Ça n'a l'air de rien et c'est
    la différence entre ajouter et détruire : une récolte retombe forcément sur
    des morceaux déjà installés, et qui ne sait pas les reconnaître les traite
    comme des candidats — donc les efface s'ils ne passent pas le tri du jour.
    Sept morceaux en rotation sont partis comme ça.
    """
    cible = dossier / f"dogmazic-{fiche['id']:06d}.mp3"
    fiche["telecharge"] = False
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
    fiche["telecharge"] = True
    return cible


def ecris_credits(dossier: Path, fiches: list[dict],
                  effaces: tuple[str, ...] | list[str] = ()) -> None:
    """Ajoute aux crédits sans effacer les nôtres.

    Le flux lit ce fichier pour afficher l'auteur, le titre et la licence du
    morceau en cours. C'est la contrepartie de la licence, et elle n'a de sens
    que si elle est juste : on n'écrit donc que ce que la page a dit.

    Et on retire ce qu'on vient d'effacer. Les crédits servent aussi à écrire
    la description de la chaîne, qui annoncerait sinon des morceaux qu'on ne
    passe plus — un crédit faux par excès reste un crédit faux.

    Nommément, et non en balayant le dossier : un balayage serait juste ici et
    catastrophique sur le Mac, où « data/musique » ne tient que les seize
    morceaux de la maison. Il y effacerait les cent douze autres crédits, et
    la copie suivante emporterait le trou jusqu'au Pi.
    """
    chemin = dossier / "credits.json"
    try:
        tout = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tout = {}
    for nom in effaces:
        tout.pop(Path(nom).name, None)
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
    partie.add_argument("--danse", action="store_true",
                        help="ne chercher que dans les genres où l'on danse")
    partie.add_argument("--mini-min", type=float, default=COURT_MIN_S / 60,
                        help="durée minimale d'un morceau, en minutes")
    partie.add_argument("--garde", type=int, default=0,
                        help="ne garder que les N plus pulsés, mesure à l'appui")
    args = partie.parse_args()

    dossier = ROOT / args.dossier
    dossier.mkdir(parents=True, exist_ok=True)
    print(f"Lecture du catalogue pour {args.minutes:.0f} min de musique")
    fiches = moisson(args.minutes, genres=GENRES_DANSE if args.danse else None,
                     mini=args.mini_min * 60)
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
    gardes = [f for f in fiches if f.get("fichier")]
    effaces: list[str] = []
    if args.garde:
        gardes, effaces = ecoute(gardes, args.garde)
    ecris_credits(dossier, gardes, effaces)
    print(f"{len(gardes)} morceaux gardés, "
          f"{sum(f['duree'] for f in gardes) / 60:.0f} min de Dogmazic")
    return 0


def ecoute(fiches: list[dict], combien: int) -> tuple[list[dict], list[str]]:
    """Écoute ce qu'on a téléchargé et ne garde que ce qui pousse vraiment.

    Trier sur l'étiquette de genre ne marche pas : elle est posée à la main par
    qui dépose le fichier, et le même mot « Techno » couvre une transe à cent
    trente temps et un drone de vingt minutes. On mesure donc la régularité de
    la grosse caisse, et c'est elle qui décide.

    Les recalés d'aujourd'hui sont effacés tout de suite. Les laisser sur le
    disque en se contentant de ne pas les créditer ferait pire que rien : la
    diffusion ramasse le dossier entier, elle les passerait quand même, et ils
    arriveraient à l'antenne sans attribution — ce qui est exactement ce que la
    licence interdit.

    Mais seulement ceux d'aujourd'hui. Une récolte retombe forcément sur des
    morceaux déjà installés, et les juger au tri du jour reviendrait à faire le
    ménage dans la médiathèque sous couvert d'y ajouter. Sept morceaux en
    rotation sont partis comme ça avant que cette ligne existe.
    """
    from scripts.pulsation import dansant, mesure

    for fiche in fiches:
        fiche["pulsation"] = mesure(Path(fiche["fichier"]))
    classe = sorted((f for f in fiches if dansant(f["pulsation"])),
                    key=lambda f: -f["pulsation"]["force"])
    # Deux par artiste au plus. Sur ce catalogue un seul nom fournit sept des
    # trente candidats du genre, et pris au mérite seul il raflerait la moitié
    # de ce qu'on garde : le flux sonnerait alors comme un album en boucle,
    # ce qui est le défaut qu'on passe son temps à éviter ailleurs.
    gardes, par_auteur = [], {}
    for fiche in classe:
        nom = fiche["auteur"].strip().lower()
        if par_auteur.get(nom, 0) >= 2:
            continue
        par_auteur[nom] = par_auteur.get(nom, 0) + 1
        gardes.append(fiche)
        if len(gardes) >= combien:
            break
    tenus = {f["fichier"] for f in gardes}
    effaces: list[str] = []
    for fiche in fiches:
        if fiche["fichier"] in tenus:
            marque = "gardé "
        else:
            marque = "effacé" if fiche.get("telecharge") else "laissé"
        p = fiche["pulsation"]
        print(f"  {marque} force {p['force']:5.3f}  {p['bpm']:5.1f} bpm  "
              f"{p['duree'] / 60:4.1f} min  {fiche['auteur'][:20]:20s} · "
              f"{fiche['titre'][:30]}")
        if fiche["fichier"] not in tenus and fiche.get("telecharge"):
            Path(fiche["fichier"]).unlink(missing_ok=True)
            effaces.append(fiche["fichier"])
    return gardes, effaces


if __name__ == "__main__":
    raise SystemExit(main())
