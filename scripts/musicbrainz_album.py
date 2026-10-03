"""Référencer un album dans MusicBrainz sans donner ses identifiants à personne.

L'éditeur de publication de MusicBrainz accepte un formulaire pré-rempli : on
lui envoie les champs, il ouvre son écran d'édition avec tout en place, et
c'est le titulaire du compte qui relit et qui valide. La modification porte
donc sa signature, pas celle d'un programme — ce qui est exactement la bonne
répartition, puisque c'est lui qui répond de ce qui est publié.

Un formulaire plutôt qu'une adresse avec des paramètres : seize pistes font
près de trois mille caractères, et une adresse de cette longueur se fait
tronquer quelque part entre le terminal, le presse-papier et la barre du
navigateur. Le formulaire se relit aussi avant d'être envoyé, ce qu'une URL ne
permet pas.

Tout est lu dans les fichiers eux-mêmes — titre, numéro de piste, durée au
millième — plutôt que recopié à la main : le dépôt et MusicBrainz doivent
décrire le même objet, et deux saisies séparées divergent toujours.

    .venv/bin/python scripts/musicbrainz_album.py ~/Desktop/"Mont Serein 002"
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EDITEUR = "https://musicbrainz.org/release/add"
# Benoît Prieur, crédité « thepriben ». Relevé dans MusicBrainz le 3 octobre
# 2026 : l'artiste existait déjà, avec cette désambiguïsation exactement.
ARTISTE_MBID = "e6460645-fca4-49cd-a68d-910b52b88027"
CREDITE = "thepriben"
# Les types de relation, lus dans la table « link_type » du serveur MusicBrainz
# et non pas devinés sur la page publique des relations : là-bas, le libellé est
# séparé de son identifiant par assez de balises pour qu'on les apparie de
# travers. C'est arrivé, et l'appariement faux donnait « purchase for download »
# à un album gratuit — l'éditeur l'a refusé, mais il aurait pu l'accepter.
#
# Ce sont des entiers, comme la documentation le dit expressément. Le champ est
# facultatif : laissé vide, il se choisit à la main dans l'éditeur.
#
# Le 85 est l'écoute gratuite, et non l'écoute tout court : le 320adf26 existe
# à côté pour les plateformes sur abonnement. La base de test l'appelle encore
# « streaming music », le site l'appelle « free streaming » — on a vérifié que
# c'était le même en passant par son identifiant long, qui, lui, ne bouge pas.
RELATION = {
    "licence": "301",
    "telechargement": "75",
    "ecoute": "85",
}
LICENCES = {
    "by": ("https://creativecommons.org/licenses/by/4.0/",
           "Creative Commons Attribution 4.0 International (CC BY 4.0)"),
    "by-sa": ("https://creativecommons.org/licenses/by-sa/4.0/",
              "Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)"),
}
# « Pas de contenu linguistique », qui est le cas d'une techno instrumentale.
# Laisser le champ vide ferait poser la question à chaque relecteur.
LANGUE = "zxx"


def etiquettes(fichier: Path) -> dict:
    """Ce que le fichier dit de lui-même, demandé à ffprobe et non deviné."""
    sortie = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags",
         "-of", "json", str(fichier)],
        capture_output=True, text=True, check=True)
    brut = json.loads(sortie.stdout).get("format") or {}
    tags = {k.lower(): v for k, v in (brut.get("tags") or {}).items()}
    return {
        "titre": tags.get("title") or fichier.stem,
        "album": tags.get("album") or "",
        "artiste": tags.get("artist") or "",
        "annee": (tags.get("date") or "")[:4],
        "piste": tags.get("track") or "",
        # MusicBrainz compte en millièmes de seconde.
        "duree_ms": int(round(float(brut.get("duration") or 0.0) * 1000)),
    }


def rang(piste: str) -> int:
    """« 3/16 » vaut 3. Sans numéro, l'ordre du nom de fichier fera foi."""
    tete = piste.split("/")[0].strip()
    return int(tete) if tete.isdigit() else 0


def champs(morceaux: list[dict], album: str, annee: str, jour: tuple[int, int],
           licence: tuple[str, str], adresses: list[str]) -> list[tuple[str, str]]:
    """Les couples nom/valeur que l'éditeur attend, dans son propre vocabulaire."""
    plan: list[tuple[str, str]] = [
        ("name", album),
        ("artist_credit.names.0.mbid", ARTISTE_MBID),
        # Crédité sous le nom qui figure sur les fichiers, qui n'est pas le nom
        # de l'artiste dans la base. MusicBrainz sait tenir les deux, et les
        # confondre effacerait l'un des deux.
        ("artist_credit.names.0.name", CREDITE),
        ("type", "Album"),
        # En minuscules : ce sont les valeurs que la documentation énumère.
        ("status", "official"),
        ("language", LANGUE),
        ("mediums.0.format", "Digital Media"),
    ]
    # Ne sont pas envoyés, faute de pouvoir les donner à coup sûr : « packaging »,
    # dont la documentation décrit les valeurs par celles d'un autre champ, et le
    # pays de parution, annoncé comme un code ISO alors qu'une sortie numérique
    # demande [Worldwide], qui n'en est pas un. Les deux se posent d'un clic dans
    # l'éditeur ; un champ refusé, lui, fait rejeter tout le formulaire.
    if annee:
        plan += [("events.0.date.year", annee),
                 ("events.0.date.month", str(jour[0])),
                 ("events.0.date.day", str(jour[1]))]
    for place, morceau in enumerate(morceaux):
        plan += [
            (f"mediums.0.track.{place}.name", morceau["titre"]),
            (f"mediums.0.track.{place}.number", str(place + 1)),
            (f"mediums.0.track.{place}.length", str(morceau["duree_ms"])),
        ]
    for numero, (adresse, genre) in enumerate(adresses):
        plan += [(f"urls.{numero}.url", adresse),
                 (f"urls.{numero}.link_type", RELATION[genre])]
    adresse_licence, nom_licence = licence
    plan.append((f"urls.{len(adresses)}.url", adresse_licence))
    plan.append((f"urls.{len(adresses)}.link_type", RELATION["licence"]))
    plan.append(("edit_note", (
        f"Album publié par l'artiste lui-même sous {nom_licence}. "
        "Titres, numéros de piste et durées relevés directement dans les "
        "fichiers diffusés.")))
    return plan


def page(plan: list[tuple[str, str]], album: str) -> str:
    """Un formulaire qu'on relit avant de l'envoyer."""
    lignes = "\n".join(
        f'  <input type="hidden" name="{html.escape(nom)}" value="{html.escape(valeur)}">'
        for nom, valeur in plan)
    table = "\n".join(
        f"<tr><td>{html.escape(nom)}</td><td>{html.escape(valeur)}</td></tr>"
        for nom, valeur in plan)
    return f"""<!doctype html>
<meta charset="utf-8">
<title>MusicBrainz — {html.escape(album)}</title>
<style>
 body {{ font: 15px/1.5 system-ui, sans-serif; margin: 3rem auto; max-width: 56rem; }}
 table {{ border-collapse: collapse; width: 100%; margin-top: 2rem; }}
 td {{ border-bottom: 1px solid #ddd; padding: .25rem .5rem; font: 13px monospace; }}
 td:first-child {{ color: #666; white-space: nowrap; }}
 button {{ font-size: 1.1rem; padding: .7rem 1.4rem; }}
</style>
<h1>{html.escape(album)}</h1>
<p>Connectez-vous d'abord à MusicBrainz, puis envoyez. L'éditeur s'ouvrira
rempli ; rien n'est publié tant que vous n'avez pas validé chez eux.</p>
<form method="post" action="{EDITEUR}" accept-charset="utf-8">
{lignes}
  <button type="submit">Ouvrir l'éditeur MusicBrainz</button>
</form>
<p>Ce qui sera envoyé, en entier :</p>
<table>{table}</table>
"""


def main() -> int:
    plaidoyer = argparse.ArgumentParser(description=__doc__)
    plaidoyer.add_argument("dossier", type=Path, help="le dossier des mp3 étiquetés")
    plaidoyer.add_argument("--licence", choices=sorted(LICENCES), default="by-sa")
    plaidoyer.add_argument("--jour", default="10-02", help="mois-jour de parution")
    plaidoyer.add_argument("--lien", action="append", default=[],
                           help="adresse où l'album s'écoute, répétable")
    plaidoyer.add_argument("--lien-genre", choices=["telechargement", "ecoute"],
                           default="ecoute")
    plaidoyer.add_argument("--sortie", type=Path, default=Path("/tmp/musicbrainz.html"))
    args = plaidoyer.parse_args()

    fichiers = sorted(args.dossier.glob("*.mp3"))
    if not fichiers:
        print(f"Aucun mp3 dans {args.dossier}")
        return 1
    morceaux = [etiquettes(f) for f in fichiers]
    morceaux.sort(key=lambda m: (rang(m["piste"]), m["titre"]))

    albums = {m["album"] for m in morceaux if m["album"]}
    if len(albums) != 1:
        print(f"Les fichiers ne s'accordent pas sur l'album : {albums or 'aucun'}")
        return 1
    album = albums.pop()
    annees = {m["annee"] for m in morceaux if m["annee"]}
    annee = annees.pop() if len(annees) == 1 else ""
    mois, jour = (int(x) for x in args.jour.split("-"))

    adresses = [(lien, args.lien_genre) for lien in args.lien]
    plan = champs(morceaux, album, annee, (mois, jour), LICENCES[args.licence], adresses)
    args.sortie.write_text(page(plan, album), encoding="utf-8")

    duree = sum(m["duree_ms"] for m in morceaux) / 60000
    print(f"{album} — {len(morceaux)} pistes, {duree:.0f} min au total, {annee or 'sans année'}")
    print(f"crédité « {CREDITE} » sur l'artiste {ARTISTE_MBID}")
    print(f"licence : {LICENCES[args.licence][1]}")
    for lien, genre in adresses:
        print(f"lien ({genre}) : {lien}")
    print(f"\nOuvrez ceci, connecté à MusicBrainz :\n  {args.sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
