#!/usr/bin/env python3
"""Ce qui se passe autour de la caméra, pris chez l'office de tourisme.

Le bandeau du bas affichait la Ligue 1 faute de mieux : on voulait la N3 de la
région, aucune source ne la publie, et un championnat national n'a rien à voir
avec un versant du Ventoux. Un agenda local, lui, a tout à voir — c'est
exactement ce qu'on aurait envie de savoir en regardant cette montagne.

La source est l'office de tourisme Porte du Ventoux, qui couvre Pernes-les-
Fontaines, Monteux, Sorgues, Bédarrides et Althen-des-Paluds, au pied du
massif. Sa page d'agenda est rendue côté serveur : un seul appel suffit, et il
n'y a rien à exécuter.

Sobre veut dire trois champs. La date, le titre, la commune. Pas les tarifs,
pas les horaires, pas les numéros d'inscription : le bandeau glisse à quatre
pixels et demi par seconde et personne ne recopiera un numéro de téléphone en
regardant une webcam.

    python3 scripts/agenda.py
    python3 scripts/agenda.py --montre   (sans écrire, pour voir)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "data" / "agenda.json"
SOURCE = "https://porteduventoux.com/agenda"
CREDIT = "AGENDA PORTE DU VENTOUX"
NAVIGATEUR = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "ventoux-watch/1.0 (+https://medialoco.github.io/ventoux-watch/)")
# Le bandeau fait un tour complet en quelques minutes. Au-delà d'une
# trentaine d'entrées il ne revient plus assez souvent pour qu'on tombe
# dessus, et un agenda qu'on ne voit jamais ne sert à rien.
COMBIEN = 30
# Les titres de l'office sont longs — « Festival Ventoux Saveurs : Atelier
# cueillette et cuisine : La mûre sauvage, de la nature à la confiture. »
# Passé cette longueur, on coupe au dernier mot entier.
LARGE = 52
MOIS = {"janv": 1, "févr": 2, "fevr": 2, "mars": 3, "avri": 4, "mai": 5,
        "juin": 6, "juil": 7, "août": 8, "aout": 8, "sept": 9, "octo": 10,
        "nove": 11, "déce": 12, "dece": 12}
COURT = ("JANV", "FÉVR", "MARS", "AVR", "MAI", "JUIN",
         "JUIL", "AOÛT", "SEPT", "OCT", "NOV", "DÉC")

BLOC = re.compile(r'<a class="objAgenda"[^>]*>(.*?)</a>', re.S)
DATE = re.compile(r"<b>\s*(\d{1,2})\s*</b>\s*<small>\s*([^<]+?)\s*</small>", re.S)
TITRE = re.compile(r'<div class="objAgendaTexte">\s*<b>(.*?)</b>', re.S)
COMMUNE = re.compile(r"data-icone=[\"']marker[\"']></span>\s*([^<]+?)\s*</span>", re.S)


def propre(brut: str) -> str:
    """Le texte d'une balise, sans balises ni entités ni blancs en trop."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", brut))).strip()


def majuscule(texte: str) -> str:
    """En capitales, accents compris.

    La police du bandeau n'a pas de minuscules accentuées lisibles à cette
    taille, mais elle a les majuscules : « FÊTE » passe, « fête » bave. Les
    caractères qu'elle ne sait pas tracer du tout sont ramenés à leur lettre
    nue plutôt que remplacés par un carré.
    """
    haut = texte.upper()
    for joli, nu in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                     ("–", "-"), ("—", "-"), ("…", "...")):
        haut = haut.replace(joli, nu)
    sans = unicodedata.normalize("NFKD", haut)
    return "".join(c for c in sans if not unicodedata.combining(c))


def coupe(texte: str, large: int = LARGE) -> str:
    """Au dernier mot entier, parce qu'un titre coupé en plein mot se lit mal."""
    if len(texte) <= large:
        return texte
    bout = texte[:large].rsplit(" ", 1)[0]
    return (bout or texte[:large]).rstrip(" ,;:-") + "…"


def une_date(jour: str, mois: str, aujourd_hui: dt.date) -> dt.date | None:
    """Le jour que désigne « 04 Octo », en devinant l'année.

    L'office n'écrit jamais l'année. Un agenda ne regarde que devant lui :
    si le mois est déjà passé, c'est celui de l'an prochain. Sans cette
    règle, les expositions de janvier remonteraient en tête de bandeau tout
    l'automne, datées de l'hiver dernier.
    """
    numero = MOIS.get(mois.lower().rstrip(".")[:4])
    if numero is None:
        return None
    for annee in (aujourd_hui.year, aujourd_hui.year + 1):
        try:
            quand = dt.date(annee, numero, int(jour))
        except ValueError:
            return None
        if quand >= aujourd_hui - dt.timedelta(days=1):
            return quand
    return None


def moissonne(page: str, aujourd_hui: dt.date) -> list[dict]:
    """Les événements de la page, à partir d'aujourd'hui, par ordre de date."""
    trouves: list[dict] = []
    for bloc in BLOC.findall(page):
        titre = TITRE.search(bloc)
        commune = COMMUNE.search(bloc)
        dates = [une_date(j, m, aujourd_hui) for j, m in DATE.findall(bloc)]
        dates = [d for d in dates if d]
        if not (titre and commune and dates):
            continue
        debut, fin = dates[0], dates[-1]
        if fin < aujourd_hui:
            continue
        # Une exposition commencée en septembre et qui court jusqu'en
        # novembre n'a pas à s'annoncer au passé : ce qui intéresse alors
        # c'est la date où elle s'arrête.
        encours = debut < aujourd_hui <= fin
        marque = fin if encours else debut
        trouves.append({
            "quand": marque.isoformat(),
            "jour": majuscule(f"{'JUSQU AU ' if encours else ''}"
                              f"{marque.day} {COURT[marque.month - 1]}"),
            "titre": majuscule(coupe(propre(titre.group(1)))),
            "commune": majuscule(propre(commune.group(1))),
            "encours": encours,
        })
    trouves.sort(key=lambda e: (e["quand"], e["titre"]))
    return trouves[:COMBIEN]


def main() -> int:
    plaidoyer = argparse.ArgumentParser(description=__doc__)
    plaidoyer.add_argument("--montre", action="store_true")
    options = plaidoyer.parse_args()
    requete = urllib.request.Request(SOURCE, headers={"User-Agent": NAVIGATEUR})
    try:
        with urllib.request.urlopen(requete, timeout=60) as reponse:
            page = reponse.read().decode("utf-8", "replace")
        evenements = moissonne(page, dt.date.today())
    except Exception as souci:
        # On ne vide jamais le fichier existant. Un agenda d'il y a trois
        # jours vaut infiniment mieux qu'un bandeau vide, et la panne d'un
        # site tiers ne doit pas se voir à l'écran.
        print(f"Agenda indisponible ({type(souci).__name__}), on garde l'ancien.")
        return 1
    if not evenements:
        print("Aucun événement lu : la page a dû changer de forme.")
        return 1
    for e in evenements:
        print(f"  {e['jour']:14s} {e['commune']:22s} {e['titre']}")
    if options.montre:
        return 0
    CIBLE.parent.mkdir(parents=True, exist_ok=True)
    CIBLE.write_text(json.dumps(
        {"credit": CREDIT, "source": SOURCE,
         "lu": dt.datetime.now().isoformat(timespec="seconds"),
         "evenements": evenements}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"{len(evenements)} événements → {CIBLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
