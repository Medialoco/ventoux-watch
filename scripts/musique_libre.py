"""Constitue la bibliothèque musicale à partir des netlabels Creative Commons.

La collection « netlabels » d'archive.org rassemble des labels qui publient
sous licence Creative Commons depuis vingt ans, électro en bonne part. Chaque
sortie déclare sa licence dans ses métadonnées : on ne garde que celles qui en
ont une, et on écrit les attributions à côté des fichiers.

L'attribution n'est pas une politesse. CC-BY l'exige, et un direct permanent
qui ne crédite personne est un direct qui finit par être réclamé. Le fichier
« attributions.md » est fait pour être recopié tel quel dans la description.

    .venv/bin/python -m scripts.musique_libre --combien 30
    .venv/bin/python -m scripts.musique_libre --combien 30 --genre ambient
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RECHERCHE = "https://archive.org/advancedsearch.php"
META = "https://archive.org/metadata/"
TELECHARGE = "https://archive.org/download/"

# Les licences qu'on accepte. Tout ce qui n'est pas là-dedans est refusé, y
# compris l'absence de licence : « rien de déclaré » ne veut pas dire « libre ».
LIBRES = ("creativecommons.org/licenses/", "creativecommons.org/publicdomain/")
# Les clauses qu'on refuse. « nd » interdit la modification, et un direct qui
# mixe, coupe et baisse le son modifie ; « nc » interdit l'usage commercial, et
# une chaîne YouTube peut en devenir un sans prévenir.
REFUSEES = ("-nd", "-nc", "/nc", "/nd")

# Du MP3, et surtout pas le FLAC d'origine. Archive.org garde les deux : la
# première sortie récoltée pesait deux cent douze mégaoctets à elle seule, soit
# cinq gigaoctets pour la bibliothèque, et du décodage sans objet sur une
# machine qui touche déjà le bridage thermique. Le flux ressort à 128 kbit/s
# en AAC de toute façon.
EXTENSIONS = (".mp3", ".ogg")
# En dessous, ce n'est pas un morceau : les sorties d'archive.org sont pleines
# d'extraits de trente kilooctets et d'empreintes acoustiques, et prendre le
# plus petit fichier revenait à récolter des bouts de deux secondes. Au-dessus,
# c'est l'album entier dans un seul fichier.
POIDS_MIN = 1_500_000
POIDS_MAX = 25 * 1024 * 1024


def _json(url: str) -> dict:
    requete = urllib.request.Request(url, headers={"User-Agent": "ventoux-watch/0.4"})
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        return json.loads(reponse.read().decode("utf-8", "replace"))


def _courte(url: str) -> str:
    """« CC BY 3.0 » plutôt qu'une adresse de soixante caractères à l'écran."""
    bout = re.sub(r"https?://creativecommons\.org/(licenses|publicdomain)/", "", url or "")
    bout = [m for m in bout.strip("/").split("/") if m]
    if not bout:
        return "CC"
    if bout[0] in {"zero", "mark"}:
        return "CC0"
    return "CC BY" + ("-" + bout[0][3:].upper() if bout[0].startswith("by-") else "") + \
           (" " + bout[1] if len(bout) > 1 else "")


def cherche(genre: str, combien: int) -> list[tuple[str, str]]:
    """Les sorties dont la licence convient, licence comprise.

    La collection « netlabels » semblait l'endroit évident, mais ses sorties ne
    déclarent presque jamais de « licenseurl » : sur huit tirées au hasard, une
    seule en avait une, et c'était du « by-nc-nd ». On cherche donc dans tout
    archive.org en exigeant la licence dans la requête, et on la demande dans
    les résultats : cela évite d'aller lire les métadonnées de cent sorties
    pour en jeter quatre-vingts.
    """
    requete = f'mediatype:(audio) AND licenseurl:(*creativecommons*) AND subject:({genre})'
    url = (f"{RECHERCHE}?q={urllib.parse.quote(requete)}"
           "&fl%5B%5D=identifier&fl%5B%5D=licenseurl&fl%5B%5D=subject"
           f"&rows={max(combien * 12, 100)}&page=1&output=json")
    trouve = _json(url)["response"]["docs"]
    mots = [m.lower() for m in re.findall(r"[\w']+", genre) if m.upper() != "OR"]
    sorties = []
    for item in trouve:
        if not licence_libre(item.get("licenseurl") or ""):
            continue
        etiquettes = item.get("subject") or []
        if isinstance(etiquettes, str):
            etiquettes = [etiquettes]
        # Relire l'étiquette nous-même. La recherche d'archive.org découpe les
        # mots à sa façon et a rendu un témoignage parlé parmi les sorties
        # « house » ; demander le genre dans la requête ne suffit pas à l'avoir.
        if not any(mot in " ".join(etiquettes).lower() for mot in mots):
            continue
        sorties.append((item["identifier"], item.get("licenseurl") or ""))
    return sorties


def licence_libre(url: str) -> bool:
    url = (url or "").lower()
    if not any(bon in url for bon in LIBRES):
        return False
    return not any(mauvais in url for mauvais in REFUSEES)


def recolte(dossier: Path, genre: str, combien: int) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    attributions = []
    # Pas « credits » : c'est déjà un objet de Python, et l'oublier ne donne
    # aucune erreur à l'écriture — seulement un « _Printer n'est pas itérable »
    # au bout de quarante secondes de téléchargement.
    fiches: dict[str, dict] = {}
    pris = 0
    for identifiant, licence in cherche(genre, combien):
        if pris >= combien:
            break
        try:
            meta = _json(META + identifiant)
        except Exception as erreur:  # noqa: BLE001
            print(f"  {identifiant} : métadonnées illisibles ({erreur})")
            continue
        infos = meta.get("metadata") or {}
        auteur = infos.get("creator") or infos.get("publisher") or "inconnu"
        if isinstance(auteur, list):
            auteur = auteur[0]
        titre_album = infos.get("title") or identifiant

        pistes = [f for f in (meta.get("files") or [])
                  if str(f.get("name", "")).lower().endswith(EXTENSIONS)
                  and POIDS_MIN <= int(f.get("size") or 0) <= POIDS_MAX]
        if not pistes:
            continue
        # Une piste par sortie, pas l'album entier : une bibliothèque de
        # trente artistes sonne comme une sélection, trente pistes du même
        # sonne comme un disque qu'on a laissé tourner. Dans l'ordre du
        # disque, pas la plus petite — la plus petite est une intro.
        piste = pistes[0]
        nom = re.sub(r"[^\w.\-]", "_", f"{identifiant}-{piste['name']}")[-120:]
        cible = dossier / nom
        if cible.exists():
            continue
        url = TELECHARGE + identifiant + "/" + urllib.parse.quote(piste["name"])
        try:
            requete = urllib.request.Request(url, headers={"User-Agent": "ventoux-watch/0.4"})
            with urllib.request.urlopen(requete, timeout=120) as reponse:
                cible.write_bytes(reponse.read())
        except Exception as erreur:  # noqa: BLE001
            print(f"  {identifiant} : téléchargement refusé ({erreur})")
            continue
        pris += 1
        titre = piste.get("title") or re.sub(r"\.\w+$", "", piste["name"])
        fiches[nom] = {"auteur": str(auteur), "titre": str(titre),
                        "licence": _courte(licence),
                        "url": f"https://archive.org/details/{identifiant}"}
        print(f"  {pris:2d}. {auteur} — {titre}")

    # Lisible par la diffusion : elle affiche à l'écran le morceau en train de
    # passer. Une liste dans la description ne crédite personne à trois heures
    # du matin, et c'est justement l'heure où le flux tourne.
    chemin = dossier / "credits.json"
    anciens = json.loads(chemin.read_text(encoding="utf-8")) if chemin.is_file() else {}
    anciens.update(fiches)
    # Ce qui n'est plus sur le disque n'est plus dans les crédits : une fiche
    # sans fichier fait croire qu'on diffuse un morceau qu'on a retiré.
    anciens = {nom: f for nom, f in anciens.items() if (dossier / nom).is_file()}
    chemin.write_text(json.dumps(anciens, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    ecris_attributions(dossier, anciens)
    print(f"\n{pris} morceaux ajoutés, {len(anciens)} en tout dans {dossier}")


def ecris_attributions(dossier: Path, fiches: dict[str, dict]) -> None:
    """La liste entière, et pas seulement ce que la dernière récolte a pris.

    Écrite depuis les crédits plutôt qu'au fil du téléchargement : sinon une
    deuxième passe efface de la description les vingt morceaux de la première,
    qui continuent pourtant de passer à l'antenne.
    """
    lignes = [f"- {f['titre']} — {f['auteur']} ({f['licence']})\n  {f['url']}"
              for f in sorted(fiches.values(), key=lambda f: f["auteur"].lower())]
    (dossier / "attributions.md").write_text(
        "# Musique\n\nToutes sous licence Creative Commons permettant l'usage\n"
        "commercial et la modification. Le direct affiche le morceau en cours à\n"
        "l'écran ; cette liste est là pour la description de la chaîne.\n\n"
        + "\n".join(lignes) + "\n", encoding="utf-8")


IMAGES = (".jpg", ".jpeg", ".png")


def pochettes(dossier: Path) -> None:
    """Va chercher la pochette de chaque sortie déjà récoltée.

    Séparé de la récolte parce qu'il s'agit d'une seconde pensée : les fichiers
    sont déjà là, on ne redescend que les images. Une sortie sans pochette n'est
    pas une erreur — beaucoup de netlabels n'en déposent aucune.
    """
    chemin = dossier / "credits.json"
    fiches = json.loads(chemin.read_text(encoding="utf-8"))
    pris = 0
    for nom, fiche in fiches.items():
        if fiche.get("pochette") and (dossier / fiche["pochette"]).is_file():
            continue
        identifiant = fiche["url"].rsplit("/", 1)[-1]
        try:
            meta = _json(META + identifiant)
        except Exception as erreur:  # noqa: BLE001
            print(f"  {identifiant} : {erreur}")
            continue
        images = [f for f in (meta.get("files") or [])
                  if str(f.get("name", "")).lower().endswith(IMAGES)
                  # Les vignettes d'archive.org pèsent quelques kilooctets et
                  # sont illisibles en grand ; les scans de livret pèsent des
                  # mégaoctets pour un dos de boîtier.
                  and 15_000 <= int(f.get("size") or 0) <= 4_000_000]
        if not images:
            continue
        images.sort(key=lambda f: int(f.get("size") or 0))
        image = images[len(images) // 2]
        cible = re.sub(r"[^\w.\-]", "_", f"{identifiant}-{image['name']}")[-120:]
        url = TELECHARGE + identifiant + "/" + urllib.parse.quote(image["name"])
        try:
            requete = urllib.request.Request(url, headers={"User-Agent": "ventoux-watch/0.4"})
            with urllib.request.urlopen(requete, timeout=60) as reponse:
                (dossier / cible).write_bytes(reponse.read())
        except Exception as erreur:  # noqa: BLE001
            print(f"  {identifiant} : pochette refusée ({erreur})")
            continue
        fiche["pochette"] = cible
        pris += 1
        print(f"  {pris:2d}. {fiche['auteur'][:30]}")
    chemin.write_text(json.dumps(fiches, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    avec = sum(1 for f in fiches.values() if f.get("pochette"))
    print(f"\n{avec} pochettes sur {len(fiches)} sorties")


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--combien", type=int, default=30)
    parseur.add_argument("--genre",
                         default="techno OR electro OR electronic OR house OR trance OR IDM")
    parseur.add_argument("--dossier", default=str(ROOT / "data" / "musique"))
    parseur.add_argument("--pochettes", action="store_true",
                         help="ne descendre que les pochettes des sorties déjà prises")
    args = parseur.parse_args(argv)
    if args.pochettes:
        pochettes(Path(args.dossier))
        return 0
    recolte(Path(args.dossier), args.genre, args.combien)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
