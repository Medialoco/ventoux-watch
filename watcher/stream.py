"""Rediffuse la webcam en retard, les identifications dessinées dessus.

Le retard n'est pas une prudence, c'est le temps qu'il faut à une
identification pour exister. La veille voit une image, suit la tache pendant
quelques secondes, interroge le modèle, puis nomme — ou refuse. Diffuser au
bord du direct obligerait à dessiner avant de savoir. En diffusant une dizaine
de secondes en arrière, on ne dessine que ce qui est déjà décidé, et le
rectangle se pose sur l'image où la chose se trouvait vraiment.

Ce retard est gratuit. Le flux est du HLS découpé en segments de sept
secondes et le serveur en garde plusieurs : il suffit de démarrer un segment
en arrière, sans une seule image en mémoire tampon.

Ce programme ne touche pas à la veille et ne lui parle que par les fichiers
qu'il lit. Si la diffusion tombe, la veille continue : c'est elle le produit,
la diffusion n'est que le spectacle.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
import logging
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import cv2
import numpy as np

from watcher import __version__, direct
from watcher.coloriage import PORT as COLORIAGE_PORT
from watcher.coloriage import Coloriage
from watcher.store import floute

log = logging.getLogger("ventoux.stream")

# COMBIEN DE SEGMENTS DE RETARD
# -----------------------------
# Le flux doit diffuser une image après que la veille a fini de la juger,
# sinon le rectangle arrive en cours de route : la voiture entre dans le champ
# sans rien autour d'elle, et le cadre ne se pose qu'à mi-parcours, quand la
# piste se termine et que le nom tombe.
#
# La veille ne nomme qu'à la fin d'une piste, parce qu'il faut l'avoir vue
# entière pour dire ce que c'est. Le retard qu'il faut est donc la durée d'une
# piste, plus les deux images qu'elle attend avant de la déclarer finie.
# Mesuré sur les 66 498 pistes de l'archive : médiane 7 s, p90 29 s, p95 40 s,
# p99 72 s. Deux segments — quatorze secondes — ne couvraient entièrement que
# la moitié des pistes.
#
# Sept segments font quarante-neuf secondes et couvrent 95 % des pistes du
# premier à leur dernier instant. Soixante secondes en couvriraient 97,9 % :
# onze secondes de plus pour trois points, et le direct doit rester un direct.
# C'est là que la courbe s'aplatit, donc c'est là qu'on s'arrête.
SEGMENTS_EN_ARRIERE = 7

# Combien de temps un nom reste affiché après l'instant qu'il décrit. Une piste
# ordinaire dure quelques secondes ; en deçà le rectangle clignote et l'œil n'a
# pas le temps de le lire.
TENUE_S = 4.0

ROUGE = (60, 60, 220)
VERT = (120, 230, 130)
AMBRE = (60, 190, 250)
CYAN = (235, 215, 70)
BLANC = (245, 245, 245)

# Une session, et non une liste de morceaux. Un flux qui tourne jour et nuit
# n'a pas d'auditeur qui arrive au début : ce qu'on entend en ouvrant la page
# doit tenir tout seul, sans avoir manqué le morceau d'avant. Bâtie par tirage
# à chaque démarrage, assez longue pour qu'une journée entière ne se répète
# pas, et rebattue le lendemain.
SESSION_H = 14.0
EXTENSIONS = {".mp3", ".ogg", ".opus", ".flac", ".m4a", ".wav"}

# Le son est tenu par ce programme et non par ffmpeg, pour qu'une voix puisse
# un jour couper la musique. Le prix en est cette comptabilité : à chaque
# battement, une image et exactement la tranche de son qui lui correspond. La
# synchronisation devient une propriété de la construction au lieu d'un espoir.
ECHANTILLONS_S = 44100
VOIES = 2
OCTETS_PAR_ECHANTILLON = 2


# La lecture de la playlist appartient à watcher.direct : c'est elle qui donne
# l'heure de prise de vue, et la veille comme la diffusion doivent lire la même.
# Reprises sous leur nom ici parce que c'est ici qu'on les attrape pour les
# essais.
_lire = direct._lire
playlist_media = direct.playlist_media
bord_du_direct = direct.bord_du_direct


# Combien de temps on insiste quand la webcam ne répond pas, et à quel rythme.
# Une demi-heure : au-delà, ce n'est plus une absence, c'est une panne, et il
# vaut mieux que le service redémarre pour repartir de zéro.
ATTENTE_WEBCAM_S = 1800.0
ATTENTE_PAS_S = 20.0
# Deux minutes sans segment neuf, ce n'est plus un hoquet. La playlist qui
# porte sa propre fin l'est tout de suite : l'éditeur a fermé le fichier.
FIGEE_APRES_S = 120.0


def attends_la_webcam(url: str) -> tuple[str, float, float]:
    """La playlist, en insistant tant qu'elle n'est pas là.

    Et surtout : sans quitter le processus. La webcam a renvoyé un 404 pendant
    deux minutes ce matin ; le flux est sorti en erreur, systemd l'a relancé
    dix secondes plus tard, qui est ressorti, huit fois de suite. Chacun de ces
    départs avait ouvert puis fermé la connexion RTMP vers YouTube, et une
    diffusion dont l'arrivée clignote huit fois en deux minutes est une
    diffusion que YouTube termine.

    La panne durait deux minutes et venait d'ailleurs. Ce qui a coûté le direct,
    ce n'est pas elle, c'est notre façon d'y répondre : on repartait de zéro
    quand il suffisait d'attendre. On attend, donc, et la connexion vers
    YouTube n'est même pas ouverte tant qu'on n'a rien à y mettre.
    """
    debut = _maintenant()
    souci: Exception | None = None
    while _maintenant() - debut < ATTENTE_WEBCAM_S:
        try:
            media = playlist_media(url)
            dernier, segment = bord_du_direct(media)
            if souci is not None:
                log.info("La webcam répond de nouveau après %.0f s",
                         _maintenant() - debut)
            return media, dernier, segment
        except Exception as erreur:  # réseau, 404, playlist vide, date absente
            if souci is None:
                log.warning("Webcam indisponible (%s) : on attend sans couper "
                            "la diffusion", erreur)
            souci = erreur
            time.sleep(ATTENTE_PAS_S)
    raise RuntimeError(f"webcam muette depuis {ATTENTE_WEBCAM_S:.0f} s : {souci}")


def playlist_figee(texte: str, maintenant: float, apres_s: float = FIGEE_APRES_S) -> bool:
    """La liste est une archive : elle a écrit sa fin, ou plus rien ne paraît.

    Un trou de quelques secondes n'est pas ça. On ne tient la dernière image
    que lorsque l'éditeur a clos la playlist, ou que le dernier segment a
    deux minutes. Avant, on rouvre l'entrée et le direct continue.
    """
    if "#EXT-X-ENDLIST" in texte:
        return True
    try:
        dates, _duree = direct.dates_des_segments(texte)
    except RuntimeError:
        return False
    return maintenant - dates[-1] > apres_s


def _derniere_image(entree: subprocess.Popen, octets: int,
                    hauteur: int, largeur: int) -> np.ndarray | None:
    """La dernière image complète que l'entrée veut bien donner."""
    assert entree.stdout is not None
    derniere = None
    while True:
        brut = entree.stdout.read(octets)
        if len(brut) < octets:
            return derniere
        derniere = np.frombuffer(brut, np.uint8).reshape(hauteur, largeur, 3).copy()


# À quel rythme on va vérifier que la diffusion existe encore, et au bout de
# combien d'absences on le dit. Dix minutes, deux fois : une page qui répond mal
# une fois ne vaut pas qu'on crie.
VEILLE_DIRECT_S = 600.0
VEILLE_DIRECT_SEUIL = 2
# Tant qu'on ignore sous quel numéro on émet, on regarde à ce rythme-là : la
# page du site n'a rien à incruster tant qu'on ne le sait pas, et c'est juste
# après un redémarrage qu'on ne le sait pas.
VEILLE_DIRECT_CHERCHE_S = 20.0


def page_du_direct(chaine: str) -> str | None:
    """La page /live de la chaîne, ou None quand on n'a pas su la lire."""
    url = f"https://www.youtube.com/channel/{chaine}/live"
    requete = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(requete, timeout=20) as reponse:
            return reponse.read().decode("utf-8", "replace")
    except Exception:
        return None


def lit_le_direct(page: str | None) -> tuple[bool | None, str]:
    """Ce que la page /live raconte : on émet ou non, et sous quel numéro.

    L'adresse /live d'une chaîne répond de deux façons, et c'est la façon qui
    porte la réponse plus que le contenu. Quand la chaîne émet, YouTube sert la
    page de la vidéo en cours : elle contient « videoDetails » et un
    « isLive: true ». Quand elle n'émet pas, il sert la page de la chaîne, qui
    contient « channelMetadataRenderer » et aucune vidéo. Tout le reste — une
    panne de réseau, une page qu'on ne reconnaît pas — n'est ni l'un ni l'autre.

    Ne vaut que pour un direct public : un direct privé est invisible d'ici et
    serait annoncé disparu à tort. D'où le None, qui dit « je ne sais pas » et
    non « non » ; on ne crie que sur ce qu'on a vraiment lu.

    Le numéro de la vidéo sort de la même lecture, et il n'est pas décoratif :
    il change à chaque fois que YouTube termine le direct et qu'on en rouvre un.
    Une page qui le garderait en dur montrerait l'ancien, c'est-à-dire un
    enregistrement fini ou rien du tout.
    """
    if not page:
        return None, ""
    numero = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', page)
    if "videoDetails" in page and '"isLive":true' in page:
        return True, numero.group(1) if numero else ""
    if "channelMetadataRenderer" in page:
        return False, ""
    return None, ""


def _compte(label: str) -> int | None:
    """Un entier écrit en toutes lettres de chiffres, ou rien.

    « 329 subscribers » et « 1 234 abonnés » sont des comptes. « 1.2K » n'en
    est pas un : l'arrondi n'est pas le nombre, et ce gag ne dit que ce qu'il
    a lu.
    """
    texte = label.replace("\u00a0", " ").replace("\u202f", " ").strip()
    trouve = re.match(r"(\d{1,3}(?: \d{3})*|\d+)", texte)
    if not trouve:
        return None
    suite = texte[trouve.end():].lstrip()
    if suite[:1].lower() in ".km":
        return None
    return int(trouve.group(1).replace(" ", ""))


def lit_la_salle(page: str | None) -> tuple[int | None, int | None]:
    """Les abonnés de la chaîne, et combien de gens regardent le direct.

    Deux chiffres différents. Le premier est le compte d'abonnés, le second
    est « watching now » : c'est lui qu'on divise par lui-même.
    """
    if not page:
        return None, None
    abonnes = None
    etiquette = re.search(
        r'"subscriberCountText":\{"accessibility":\{"accessibilityData":'
        r'\{"label":"([^"]+)"', page)
    if etiquette:
        abonnes = _compte(etiquette.group(1))
    direct = re.search(r'"originalViewCount":"(\d+)"', page)
    return abonnes, int(direct.group(1)) if direct else None


def groupe(n: int) -> str:
    """1 234, avec une espace tous les trois chiffres. La police n'a pas
    d'espace fine, une espace ordinaire suffit."""
    return f"{n:,}".replace(",", " ")


# Les mots dont on a le fichier. La voix est gravée une fois, sur le Mac :
# le Pi colle les morceaux, il ne synthétise rien.
_UN = ("zero", "un", "deux", "trois", "quatre", "cinq", "six", "sept",
       "huit", "neuf", "dix", "onze", "douze", "treize", "quatorze",
       "quinze", "seize")
_DIZ = ("", "", "vingt", "trente", "quarante", "cinquante", "soixante")


def morceaux_nombre(n: int) -> list[str]:
    """Les clés des fichiers qui, collées, disent n en français."""
    if n < 0:
        raise ValueError(n)
    if n < 17:
        return [_UN[n]]
    if n < 20:
        return [("dix_sept", "dix_huit", "dix_neuf")[n - 17]]
    if n < 70:
        dizaine, reste = divmod(n, 10)
        mots = [_DIZ[dizaine]]
        if reste == 1:
            return mots + ["et", "un"]
        if reste:
            mots.append(_UN[reste])
        return mots
    if n < 80:
        if n == 71:
            return ["soixante", "et", "onze"]
        return ["soixante", _UN[n - 60]]
    if n < 100:
        if n == 80:
            return ["quatre_vingts"]
        return ["quatre_vingt", *morceaux_nombre(n - 80)]
    if n < 1000:
        centaines, reste = divmod(n, 100)
        mots = [] if centaines == 1 else morceaux_nombre(centaines)
        mots.append("cents" if centaines > 1 and reste == 0 else "cent")
        if reste:
            mots.extend(morceaux_nombre(reste))
        return mots
    if n < 1_000_000:
        milliers, reste = divmod(n, 1000)
        mots = [] if milliers == 1 else morceaux_nombre(milliers)
        mots.append("mille")
        if reste:
            mots.extend(morceaux_nombre(reste))
        return mots
    millions, reste = divmod(n, 1_000_000)
    mots = ["un"] if millions == 1 else list(morceaux_nombre(millions))
    mots.append("million" if millions == 1 else "millions")
    if reste:
        mots.extend(morceaux_nombre(reste))
    return mots


def direct_visible(chaine: str) -> bool | None:
    """La chaîne est-elle en direct ? None quand on n'a pas su regarder."""
    return lit_le_direct(page_du_direct(chaine))[0]


def note_le_direct(racine: Path, chaine: str, numero: str) -> None:
    """Dit au reste du monde quel direct est en cours.

    Le site personnel incruste le direct ; sans ce fichier il devrait deviner
    l'adresse, et la seule qu'on puisse écrire sans le numéro — celle qui
    demande à YouTube de résoudre « le direct de cette chaîne » — n'est plus
    tenue et sert régulièrement une vidéo indisponible.

    Écrit puis renommé : une page qui lit pendant qu'on écrit doit trouver
    l'ancien fichier entier plutôt que le nouveau à moitié.
    """
    fichier = racine / "data" / "direct.json"
    fichier.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps({
        "chaine": chaine,
        "video": numero,
        "vu": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, ensure_ascii=False, indent=2)
    passage = fichier.with_suffix(".json.tmp")
    passage.write_text(texte + "\n", encoding="utf-8")
    passage.replace(fichier)


def veille_le_direct(chaine: str, coupe: threading.Event,
                     racine: Path | None = None) -> None:
    """Dire quand on pousse des octets dans le vide, et sous quel numéro on émet.

    Une diffusion terminée par YouTube ne se voit pas d'ici : l'arrivée continue
    d'accepter tout ce qu'on lui envoie, ffmpeg ne signale rien, et le journal
    reste propre. Le premier octobre, on a poussé quatre heures dans le vide
    avec un journal irréprochable, et c'est l'utilisateur qui s'en est aperçu.

    Alors on va regarder dehors. Ça ne répare rien — rouvrir une diffusion
    demande le compte — mais ça change « quatre heures sans le savoir » en
    « dix minutes et c'est écrit ».

    Le premier coup d'oeil se donne tout de suite et non au bout de dix minutes :
    c'est lui qui note le numéro du direct, et une page qui s'ouvre pendant ces
    dix minutes-là n'aurait rien eu à incruster.

    Un seul coup d'oeil immédiat ne suffisait pas. Le numéro change au
    redémarrage, et au redémarrage la chaîne n'est pas encore en direct : elle
    le devient quelques secondes après que notre arrivée s'est connectée. On
    regardait donc trop tôt, on ne trouvait rien, et le site renvoyait dix
    minutes durant vers la diffusion morte — c'est arrivé le 3 octobre. Tant
    qu'on n'a pas de numéro on cherche souvent ; une fois qu'on l'a, la
    surveillance lente suffit.
    """
    absences = 0
    connu = ""
    premier = True
    while premier or not coupe.wait(VEILLE_DIRECT_S if connu else VEILLE_DIRECT_CHERCHE_S):
        premier = False
        vu, numero = lit_le_direct(page_du_direct(chaine))
        if racine is not None and numero:
            try:
                note_le_direct(racine, chaine, numero)
                connu = numero
            except OSError as souci:
                log.warning("Numéro du direct non noté : %s", souci)
        if vu is None:
            continue
        if vu:
            if absences >= VEILLE_DIRECT_SEUIL:
                log.info("La diffusion est de nouveau visible sur la chaîne")
            absences = 0
            continue
        absences += 1
        if absences == VEILLE_DIRECT_SEUIL:
            log.error("Aucune diffusion en direct sur la chaîne depuis %.0f min "
                      "alors qu'on émet : les octets partent dans le vide. Il "
                      "faut rouvrir un direct dans YouTube Studio, la clé est "
                      "déjà alimentée.", VEILLE_DIRECT_S * absences / 60)


def identifications(chemin: Path, depuis: float) -> list[dict]:
    """Ce que la veille a nommé, avec son heure et son rectangle.

    Lu dans l'historique plutôt que dans un canal à part : c'est le même
    fichier que le site publie, donc ce que le flux montre et ce que la page
    raconte ne peuvent pas diverger.
    """
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    evenements = brut["events"] if isinstance(brut, dict) else brut
    gardes = []
    for event in evenements:
        # Les refus ne sont pas des lectures. Un rectangle rouge dit « j'ai vu
        # ceci » ; posé sur « Rien de reconnu » ou « Immobile sur la pente »,
        # il annonce un embarras comme une trouvaille, et il y en avait deux
        # fois plus que de vraies prises. Ils restent dans l'historique et dans
        # la file à juger ; ils sortent de l'écran.
        if event.get("type") == "missed":
            continue
        detail = event.get("detail") or {}
        boite = detail.get("box")
        if not boite or len(boite) != 4:
            continue
        try:
            # L'historique date en UTC ; strptime rend une heure sans fuseau,
            # que timestamp() lirait comme locale. Deux heures d'écart l'été,
            # soit un rectangle posé sur une image qui n'a rien à voir.
            quand = datetime.strptime(event["t"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc).timestamp()
        except (KeyError, ValueError):
            continue
        if quand < depuis:
            continue
        confiance = float(event.get("confidence") or 0.0)
        gardes.append({"t": quand, "box": boite, "label": event.get("label") or "",
                       "type": event.get("type"), "trace": detail.get("trace") or [],
                       "confiance": confiance,
                       "sur": nomme(event.get("label") or "", confiance)})
    return gardes


# Sous cette confiance, le rectangle reste et le mot se tait.
#
# Mesuré sur les 106 prises que l'oeil humain a tranchées : au-dessus de 0,60,
# quarante-cinq noms et pas un désaccord ; en dessous, les dix refus. Le seuil
# est posé là où la faute disparaît, pas là où elle devient rare.
#
# Il en coûte la moitié des bons noms — quarante-cinq gardés sur quatre-vingt-
# seize —, et c'est le bon prix. Un rectangle muet avoue qu'on a vu passer
# quelque chose sans savoir quoi ; un rectangle qui écrit « VOITURE » sur un
# piéton affirme. La première erreur se corrige d'un coup d'oeil, la seconde
# discrédite tout le reste.
#
# C'est un score de modèle et non une mesure de ce terrain : il se transporte
# tel quel sur une autre caméra, là où une largeur en mètres ne le ferait pas.
CONFIANCE_MOT = 0.60


def nomme(label: str, confiance: float) -> bool:
    """Vrai quand le mot désigne une chose, et qu'il est assez sûr pour l'écrire.

    Deux conditions, et elles ne disent pas la même chose. La liste des
    non-noms écarte ce qui n'est pas une identification du tout — la même liste
    que la rediffusion, et pour la même raison : ce qui ne mérite pas d'être
    remontré ne mérite pas d'être annoncé. La confiance écarte ce qui en est
    une mais qu'on ne tiendrait pas devant quelqu'un.

    On a essayé d'y ajouter l'autonomie de la lecture — n'écrire le mot que
    lorsque le modèle a lu la classe lui-même, sans l'aide de la taille au sol
    ni de l'horaire d'un car. L'idée était juste et la mesure l'a refusée :
    elle fait tomber les noms de quarante-cinq à vingt-sept sans retirer une
    seule faute, parce qu'à cette confiance-là il n'y en avait déjà plus. Vingt-
    six de ces vingt-sept sont de jour, ce qui dit surtout que la nuit ne passe
    pas cette porte — et c'est un autre chantier que celui-ci.
    """
    return (bool(label) and not label.startswith(NON_NOMS)
            and confiance >= CONFIANCE_MOT)


# Une tache de mouvement qui n'occupe plus le cinquième de la chose nommée,
# ni le tiers d'un de ses côtés, n'est plus cette chose : c'est le reliquat
# qu'elle laisse sur l'asphalte. Proportion de la boîte du modèle, pas de
# cette caméra.
TRACE_AIRE = 0.20
TRACE_COTE = 0.35
# Une flaque plus grande que la chose nommée n'est plus cette chose : c'est
# le reliquat qu'elle laisse en partant. Le 4 octobre vers 18 h, le dernier
# point était plus vaste que la voiture, et le rectangle vide s'y installait.
TRACE_GROS = 2.5


def _pied(boite: tuple[float, float, float, float]) -> tuple[float, float]:
    """Le milieu du bas : les roues, pas le centre du rectangle."""
    x, y, w, h = boite
    return x + w / 2, y + h


def _cadre_au_pied(cadre: tuple[float, float, float, float],
                   pied_x: float, pied_y: float) -> tuple[float, float, float, float]:
    """La taille que le modèle a lue, posée où les roues sont maintenant."""
    _, _, w, h = cadre
    return pied_x - w / 2, pied_y - h, w, h


def _cadre_nomme(vu: dict) -> tuple[float, float, float, float]:
    """La taille de la chose, pas de la flaque coupée qu'elle laisse en partant.

    Le 4 octobre peu avant 18 h, une voiture blanche a été publiée avec le
    rectangle de la tache finale, coupé par le bord, plus grand qu'elle :
    le flux a posé un carré vide. Si la boîte stockée est coupée et plus
    vaste que toute tache encore entière sur le trajet, on reprend celle-là.
    """
    cadre = tuple(vu["box"])
    pleines = []
    for point in vu.get("trace") or []:
        if len(point) < 5:
            continue
        _, x, y, w, h = point[:5]
        if w <= 0 or h <= 0:
            continue
        if x <= 0.002 or y <= 0.002 or x + w >= 0.998 or y + h >= 0.998:
            continue
        pleines.append((w, h))
    if not pleines:
        return cadre
    large, haut = max(pleines, key=lambda cote: cote[0] * cote[1])
    coupee = (cadre[0] <= 0.002 or cadre[1] <= 0.002
              or cadre[0] + cadre[2] >= 0.998 or cadre[1] + cadre[3] >= 0.998)
    if coupee and cadre[2] * cadre[3] > large * haut * 1.05:
        return (cadre[0], cadre[1], large, haut)
    return cadre


def _trace_utile(vu: dict) -> list:
    """Le trajet tant que la tache est encore le sujet, plus dès qu'elle n'est plus que du vide.

    Le 4 octobre, 172 des 284 passages du jour avaient un dernier point de
    trajectoire sans aucun recouvrement avec la chose nommée : la voiture
    était partie, il restait une flaque de quelques pixels, et le rectangle
    allait s'y installer. On garde les points où la tache a encore la taille
    de ce qui a été lu — ni trop petite, ni beaucoup trop grande.
    """
    cadre = _cadre_nomme(vu)
    aire = max(cadre[2] * cadre[3], 1e-9)
    large, haut = max(cadre[2], 1e-9), max(cadre[3], 1e-9)
    gardes = []
    for point in vu.get("trace") or []:
        if len(point) < 5:
            continue
        _, x, y, w, h = point[:5]
        if w * h > TRACE_GROS * aire and w > large and h > haut:
            continue
        if w * h >= TRACE_AIRE * aire or w >= TRACE_COTE * large or h >= TRACE_COTE * haut:
            gardes.append(point)
    return gardes


def _interpole(chemin: list, quand: float) -> tuple[float, float, float, float]:
    """Entre deux relevés, en ligne droite, sans sortir du trajet mesuré."""
    if quand <= chemin[0][0]:
        return tuple(chemin[0][1:5])
    if quand >= chemin[-1][0]:
        return tuple(chemin[-1][1:5])
    for avant, apres in zip(chemin, chemin[1:]):
        if avant[0] <= quand <= apres[0]:
            ecart = apres[0] - avant[0]
            part = 0.0 if ecart <= 0 else (quand - avant[0]) / ecart
            return tuple(a + (b - a) * part for a, b in zip(avant[1:5], apres[1:5]))
    return tuple(chemin[-1][1:5])


def _recouvre(a: tuple[float, float, float, float],
              b: tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    large = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    haut = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    union = aw * ah + bw * bh - large * haut
    return (large * haut) / union if union > 0 else 0.0


def _cadre_a_lechelle(cadre: tuple[float, float, float, float],
                      tache: tuple[float, float, float, float],
                      ref: tuple[float, float, float, float]
                      ) -> tuple[float, float, float, float]:
    """La taille lue, réduite à la hauteur apparente de cet instant.

    Poser le rectangle du premier plan sur la voiture encore au loin, c'est
    un carré vide. La hauteur de la tache suit la distance : on s'en sert
    comme d'une échelle, plafonnée à la lecture — une ombre n'agrandit pas
    la voiture.
    """
    _, _, cw, ch = cadre
    ref_h = max(ref[3], 1e-6)
    echelle = min(1.15, tache[3] / ref_h)
    pied_x, pied_y = _pied(tache)
    return _cadre_au_pied((0.0, 0.0, cw * echelle, ch * echelle), pied_x, pied_y)


def suit(vu: dict, quand: float) -> tuple[float, float, float, float]:
    """Où la chose est à cet instant, à la taille qu'elle a là.

    La veille suit le sujet image par image, à une image par seconde ; le flux
    en sort six. Entre deux relevés on interpole en ligne droite, ce qui est
    exact pour une voiture sur une route et bien assez pour le reste — à cette
    distance, une seconde de trajet tient dans la largeur du rectangle.

    La trajectoire est celle de la tache de mouvement, pas celle de la voiture.
    S'en servir telle quelle pose un rectangle trop grand, trop petit, ou vide :
    le 4 octobre le dernier point tombait à côté de la lecture pour six
    passages sur dix. On garde donc la taille lue, on la fait glisser en
    collant les roues au bas de la tache, et on la réduit à la hauteur que
    cette tache a maintenant — une voiture au loin n'a pas le rectangle du
    premier plan.

    Avant le premier point utile et après le dernier, on se tient au point le
    plus proche sans extrapoler. Prolonger un mouvement qu'on n'a pas mesuré,
    c'est inventer, et le rectangle inventé se poserait sur du vide avec le
    même aplomb que les autres.
    """
    cadre = _cadre_nomme(vu)
    chemin = _trace_utile(vu)
    if len(chemin) < 2:
        return cadre
    tache = _interpole(chemin, quand)
    ref = max((point[1:5] for point in chemin),
              key=lambda boite: _recouvre(cadre, tuple(boite)))
    return _cadre_a_lechelle(cadre, tache, tuple(ref))


def presence(vu: dict) -> tuple[float, float]:
    """Du moment où la chose est entrée dans le champ à celui où elle en sort.

    Quatre secondes fixes, c'était la durée d'un geste, pas celle d'un passage.
    Un piéton qui traverse met une demi-minute : le rectangle le lâchait au
    quart du chemin et le reste de la traversée se faisait en silence.

    La trajectoire porte déjà ses deux bouts, donc on les prend. Le rectangle
    vit exactement aussi longtemps que la chose a été là — ni moins, ce qui
    l'abandonnait, ni plus, ce qui le laisserait sur du vide.

    Le plancher reste pour les prises d'une seule image : sans lui, elles
    auraient une fenêtre nulle et ne s'afficheraient jamais.
    """
    chemin = _trace_utile(vu)
    if len(chemin) < 2:
        return vu["t"], vu["t"] + TENUE_S
    debut = min(vu["t"], chemin[0][0])
    return debut, chemin[-1][0]


# UNE COULEUR PAR FAMILLE, UNE FOIS QUE LA VEILLE A NOMMÉ
# ------------------------------------------------------
# Tout était rouge : la voiture, le marcheur, l'oiseau, le feu, et la tache
# dont on ne savait rien. À force, du rouge à l'écran ne voulait plus rien
# dire — c'était l'état normal du flux. En réservant le rouge à ce qui n'est
# pas nommé et à ce qui brûle, il redevient une information.
#
# Les teintes sont celles qui servent déjà ailleurs dans le flux, et c'est
# voulu : l'ambre des encarts, le cyan des lieux. Six couleurs inventées pour
# l'occasion auraient fait une légende à apprendre.
TEINTE_ESPECE = {
    "vehicle": AMBRE, "car": AMBRE, "truck": AMBRE, "bus": AMBRE,
    "tractor": AMBRE,
    "cycle": (120, 230, 130),      # le vert du direct : deux roues
    "person": CYAN,
    "bird": (210, 230, 150),
    "plane": (235, 180, 120),
    # Le feu reste rouge, et c'est tout l'intérêt d'avoir déteint le reste.
    "fire": ROUGE, "smoke": ROUGE,
}


def teinte_de(vu: dict) -> tuple[int, int, int]:
    """La couleur du rectangle : rouge tant qu'on ne sait pas."""
    if not vu.get("sur"):
        return ROUGE
    return TEINTE_ESPECE.get(vu.get("type") or "", ROUGE)


def visibles(vus: list[dict], quand: float) -> int:
    """Combien de choses sont encore dans le champ à cet instant.

    Comptées sans les dessiner : le rectangle n'est posé qu'une fois, sur la
    toile, après les effets. Le poser aussi sur l'image caméra le recopiait
    puis le redessinait à côté — le 4 octobre, deux cadres décalés sur la
    même voiture.
    """
    return sum(1 for vu in vus if presence(vu)[0] <= quand <= presence(vu)[1])


def dessine(image: np.ndarray, vus: list[dict], quand: float,
            vue: tuple[int, int, int, int] | None = None) -> int:
    """Pose un rectangle et un nom pour chaque chose vue à cet instant.

    Trait fin et cadre un peu large : le rectangle montre où regarder, il ne
    doit pas recouvrir ce qu'on demande de regarder.

    « vue » dit où est la fenêtre caméra sur la toile. Sans elle, on dessine
    sur l'image entière — c'est le cas de l'épreuve et du premier passage,
    avant les numéros. Avec elle, on redessine par-dessus les effets : un
    éléphant ou un Raspberry au milieu de la route ne doit pas éteindre la
    veille, il doit seulement passer derrière le rectangle.
    """
    if vue is None:
        gauche, cime, large, haut = 0, 0, image.shape[1], image.shape[0]
    else:
        gauche, cime, large, haut = vue
    poses = 0
    for vu in vus:
        debut, fin = presence(vu)
        if not debut <= quand <= fin:
            continue
        x, y, w, h = suit(vu, quand)
        x1, y1 = gauche + int(x * large), cime + int(y * haut)
        x2, y2 = gauche + int((x + w) * large), cime + int((y + h) * haut)
        teinte = teinte_de(vu)
        cv2.rectangle(image, (x1, y1), (x2, y2), teinte, 2)
        # Le mot seulement quand la veille a nommé quelque chose. « Mouvement
        # sur la route » n'est pas une identification, c'est l'aveu qu'il n'y en
        # a pas eu : écrit en blanc sur rouge à côté d'un rectangle, il se lit
        # pourtant avec le même aplomb que « Voiture ». Le rectangle reste — il
        # y a bien eu quelque chose à cet endroit — mais il se tait.
        nom = vu["label"] if vu.get("sur") else ""
        if nom:
            echelle = max(0.6, large / 1600)
            (tw, th), _ = cv2.getTextSize(nom, cv2.FONT_HERSHEY_SIMPLEX, echelle, 2)
            base = max(cime + th + 8, y1 - 6)
            cv2.rectangle(image, (x1, base - th - 6), (x1 + tw + 10, base + 4), teinte, -1)
            # Le mot en sombre sur les teintes claires, en blanc sur le rouge :
            # « Voiture » en blanc sur ambre ne se lisait pas.
            encre = BLANC if teinte == ROUGE else (20, 20, 20)
            cv2.putText(image, nom, (x1 + 5, base), cv2.FONT_HERSHEY_SIMPLEX, echelle, encre, 2, cv2.LINE_AA)
        poses += 1
    return poses


# LE TEMPS QUE LA CLASSE TOMBE
# ----------------------------
# La veille suit la tache bien avant de savoir ce que c'est. Jusqu'ici l'écran
# restait muet pendant tout ce temps, et un piéton qui s'arrêtait devant la
# cabane n'existait pas : la classe ne se demande qu'à la fin de la piste.
#
# On montre donc la recherche. Le rectangle est rouge, comme tout ce qui n'a
# pas encore de nom. Le code, en grand, est fait pour être recopié : trois
# signes, une lettre, un chiffre, une lettre. « K7M » dans un message suffit
# à retrouver la piste.
RECHERCHE_MOT = "DETECTION DE MOUVEMENT"
# Une piste d'une seule image doit rester assez longtemps pour qu'on lise le
# code. Au-delà, le rectangle suit le trajet et s'arrête avec lui.
RECHERCHE_LECTURE_S = 2.5


def lire_recherches(chemin: Path) -> list[dict]:
    """Les pistes que la veille est en train de suivre, code compris."""
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    tracks = brut.get("tracks") if isinstance(brut, dict) else None
    if not isinstance(tracks, list):
        return []
    propres = []
    for piste in tracks:
        code = str(piste.get("code") or "")
        points = [p for p in (piste.get("points") or []) if isinstance(p, list) and len(p) >= 5]
        if len(code) != 3 or not points:
            continue
        propres.append({"code": code, "zone": str(piste.get("zone") or ""), "points": points})
    return propres


def pistes_visibles(tracks: list[dict], quand: float) -> list[dict]:
    """Les pistes qui occupent l'image à cet instant, boîte interpolée."""
    vues = []
    for piste in tracks:
        points = piste["points"]
        debut = float(points[0][0])
        fin = float(points[-1][0])
        if fin - debut < RECHERCHE_LECTURE_S:
            fin = debut + RECHERCHE_LECTURE_S
        if not debut <= quand <= fin:
            continue
        if len(points) == 1 or quand >= float(points[-1][0]):
            boite = tuple(points[-1][1:5])
        else:
            boite = _interpole(points, quand)
        vues.append({"code": piste["code"], "box": boite})
    return vues


def cherche_encore(vu: dict, pistes: list[dict], quand: float) -> bool:
    """Vrai tant que la tache est là et que la classe n'est pas encore tombée.

    La fiche datée est la fin de la piste : avant cette heure, le nom qu'elle
    porte n'était pas connu. On laisse le rectangle rouge et le code, et le
    « good catch » attend.
    """
    if not pistes or quand >= float(vu.get("t") or 0):
        return False
    debut, fin = presence(vu)
    if not debut <= quand <= fin:
        return False
    boite = suit(vu, quand)
    return any(_recouvre(boite, tuple(piste["box"])) > 0.15 for piste in pistes)


def _classe_connue(piste: dict, vus: list[dict], quand: float) -> bool:
    """Vrai quand une prise nommée recouvre déjà cette tache."""
    for vu in vus:
        if quand < float(vu.get("t") or 0):
            continue
        debut, fin = presence(vu)
        if not debut <= quand <= fin:
            continue
        if _recouvre(suit(vu, quand), tuple(piste["box"])) > 0.15:
            return True
    return False


def pose_recherches(image: np.ndarray, pistes: list[dict],
                    vue: tuple[int, int, int, int] | None,
                    vus: list[dict], quand: float) -> None:
    """Le rectangle rouge, le mot, et le code, le temps de la recherche.

    Une fois la classe tombée, le rectangle de la prise prend la place et le
    mot s'efface. Le code reste : c'est lui qu'on recopie, que la prise ait
    abouti ou non.
    """
    if not pistes:
        return
    if vue is None:
        gauche, cime, large, haut = 0, 0, image.shape[1], image.shape[0]
    else:
        gauche, cime, large, haut = vue
    echelle = max(0.55, large / 1600)
    for piste in pistes:
        connue = _classe_connue(piste, vus, quand)
        x, y, w, h = piste["box"]
        x1, y1 = gauche + int(x * large), cime + int(y * haut)
        x2, y2 = gauche + int((x + w) * large), cime + int((y + h) * haut)
        if not connue:
            cv2.rectangle(image, (x1, y1), (x2, y2), ROUGE, 2)
        code = piste["code"]
        taille_code = 1.15 * echelle
        trait = max(2, int(3 * echelle))
        (cw, ch), _ = cv2.getTextSize(code, cv2.FONT_HERSHEY_DUPLEX, taille_code, trait)
        cx = min(max(gauche, x1), gauche + large - cw - 4)
        if not connue:
            mot = RECHERCHE_MOT
            taille_mot = 0.42 * echelle
            trait_mot = max(1, int(2 * echelle))
            (mw, mh), _ = cv2.getTextSize(mot, cv2.FONT_HERSHEY_SIMPLEX, taille_mot, trait_mot)
            while mw > large * 0.92 and taille_mot > 0.28 * echelle:
                taille_mot *= 0.9
                (mw, mh), _ = cv2.getTextSize(mot, cv2.FONT_HERSHEY_SIMPLEX, taille_mot, trait_mot)
            bloc = mh + 6 + ch
            if y1 - bloc - 8 > cime:
                y_mot = y1 - ch - 10
                y_code = y1 - 6
            else:
                y_mot = min(cime + haut - 4, y2 + mh + 8)
                y_code = min(cime + haut - 4, y_mot + ch + 6)
            mx = min(max(gauche, x1), gauche + large - mw - 4)
            _pose_encre(image, mot, (mx, y_mot), cv2.FONT_HERSHEY_SIMPLEX,
                        taille_mot, trait_mot, ROUGE)
            _pose_encre(image, code, (cx, y_code), cv2.FONT_HERSHEY_DUPLEX,
                        taille_code, trait, BLANC)
        else:
            y_code = y1 - 6 if y1 - ch - 8 > cime else min(cime + haut - 4, y2 + ch + 8)
            _pose_encre(image, code, (cx, y_code), cv2.FONT_HERSHEY_DUPLEX,
                        taille_code, trait, BLANC)


def _pose_encre(image: np.ndarray, texte: str, origine: tuple[int, int],
                police: int, taille: float, trait: int,
                couleur: tuple[int, int, int]) -> None:
    """Le mot, puis le même mot en noir un peu plus gros derrière.

    Sans le liseré, un code blanc sur la neige ou rouge sur le crépuscule
    disparaît, et un code qu'on ne lit pas ne sert à rien.
    """
    cv2.putText(image, texte, origine, police, taille, (0, 0, 0),
                trait + max(2, trait), cv2.LINE_AA)
    cv2.putText(image, texte, origine, police, taille, couleur, trait, cv2.LINE_AA)


# LE FLASH DE PRISE
# -----------------
# Un rectangle fin au bord de l'image est juste, et il se rate. Il faut déjà
# regarder là où il se pose pour le voir apparaître, et sur un flux qu'on laisse
# tourner dans un coin de l'écran personne ne regarde là.
#
# Alors on allume tout le reste. La lumière sort de la fenêtre et se répand sur
# les bandes, forte au bord et faible au loin, et le nom de ce qui passe
# s'écrit en grand sous l'image. Ça se voit du fond de la pièce.
#
# Jamais un pixel de montagne. C'est la règle de tout ce qu'on ajoute ici, et
# elle vaut doublement pour un effet qui annonce une voiture : la cacher au
# moment où on la désigne serait se moquer du monde.
ECLAT_VIE_S = 3.5
# La montée se compte en centièmes et la chute en secondes. Un éclat qui monte
# aussi lentement qu'il descend n'est pas un flash, c'est un fondu.
ECLAT_MONTEE_S = 0.09
# Jusqu'où la lumière déborde, et ce qu'il en reste au loin. En pixels à 1600
# de large, pour que la même valeur donne la même image à n'importe quelle
# définition.
ECLAT_PORTEE = 170.0
ECLAT_FOND = 0.26
_NAPPES: dict[tuple, np.ndarray] = {}


def force_eclat(age: float) -> float:
    """De zéro à un très vite, puis retour à zéro lentement."""
    if age < 0.0 or age > ECLAT_VIE_S:
        return 0.0
    if age < ECLAT_MONTEE_S:
        return age / ECLAT_MONTEE_S
    reste = (age - ECLAT_MONTEE_S) / (ECLAT_VIE_S - ECLAT_MONTEE_S)
    return float((1.0 - reste) ** 2)


def _nappe_eclat(forme: tuple[int, int], vue: tuple[int, int, int, int]) -> np.ndarray:
    """La carte de la lumière : zéro dans la fenêtre, un à son bord, décroissante.

    Calculée une fois par définition d'écran et gardée : c'est une distance au
    bord de la fenêtre, elle ne change pas d'une image à l'autre.
    """
    cle = (forme, vue)
    nappe = _NAPPES.get(cle)
    if nappe is not None:
        return nappe
    x, y, l, h = vue
    dehors = np.full(forme, 255, np.uint8)
    dehors[y:y + h, x:x + l] = 0
    loin = cv2.distanceTransform(dehors, cv2.DIST_L2, 3)
    portee = max(1.0, ECLAT_PORTEE * forme[1] / 1600)
    nappe = ECLAT_FOND + (1.0 - ECLAT_FOND) * np.exp(-loin / portee)
    nappe[y:y + h, x:x + l] = 0.0
    _NAPPES[cle] = nappe.astype(np.float32)
    return _NAPPES[cle]


def pose_eclat(toile: np.ndarray, vue: tuple[int, int, int, int], age: float,
               nom: str, teinte: tuple[int, int, int]) -> None:
    """Allume tout ce qui entoure l'image, et écrit en grand ce qu'on a vu."""
    f = force_eclat(age)
    if f <= 0.0:
        return
    x, y, l, h = vue
    echelle = toile.shape[1] / 1600
    nappe = _nappe_eclat(toile.shape[:2], vue)
    melange = (nappe * f)[:, :, None]
    couleur = np.array(teinte, np.float32)
    toile[:] = (toile * (1.0 - melange) + couleur * melange).astype(np.uint8)

    # Le liseré, posé juste à l'extérieur : il dessine la fenêtre sans mordre
    # dessus. C'est lui qui fait que la lumière a l'air de sortir de l'image
    # plutôt que d'être peinte autour.
    vif = tuple(int(c + (255 - c) * 0.65 * f) for c in teinte)
    epais = max(2, int(3 * echelle))
    cv2.rectangle(toile, (x - epais, y - epais), (x + l + epais - 1, y + h + epais - 1),
                  vif, epais)

    if not nom:
        return
    # Le nom sous l'image, en grand. Il couvre le fil des kilomètres et le haut
    # du bloc musique pendant trois secondes et demie, et c'est le bon ordre :
    # ce qui passe sur la route prime sur ce qui passe dans les enceintes.
    taille = 1.45 * echelle
    gras = max(2, int(3 * echelle))
    mot = nom.upper()
    (large, haut), _ = cv2.getTextSize(mot, cv2.FONT_HERSHEY_DUPLEX, taille, gras)
    ox = (toile.shape[1] - large) // 2
    oy = y + h + int(16 * echelle) + haut
    cv2.putText(toile, mot, (ox, oy), cv2.FONT_HERSHEY_DUPLEX, taille,
                (0, 0, 0), gras + max(3, int(7 * echelle)), cv2.LINE_AA)
    cv2.putText(toile, mot, (ox, oy), cv2.FONT_HERSHEY_DUPLEX, taille,
                BLANC, gras, cv2.LINE_AA)


def prise_a_feter(vus: list[dict], quand: float, fetes: set) -> dict | None:
    """La prise qu'on peut fêter à cette image : celle qu'on est en train de montrer.

    La veille travaille au bord du direct ; le flux, lui, le montre avec
    quelques segments de retard. Fêter une prise à l'arrivée de sa fiche
    lançait donc « GOOD CATCH » une vingtaine de secondes avant que le
    rectangle n'apparaisse : la fête saluait une image vide, et la voiture
    passait ensuite en silence. Dix-neuf secondes d'écart, mesurées sur la
    voiture verte du premier octobre.

    On attend donc que le sujet soit à l'écran. La fête et le rectangle
    partagent alors la même fenêtre et ne peuvent plus se décaler, quel que
    soit le retard, et sur n'importe quelle caméra.

    Rien si la fenêtre est déjà passée : il n'y a plus rien à montrer du doigt.
    C'est aussi ce qui fait qu'un flux qui s'allume ne fête pas tout son
    historique — il est entièrement derrière la tête de lecture.
    """
    for vu in vus:
        if (vu.get("type") or "") not in PRISES:
            continue
        if float(vu.get("confiance") or 0.0) < CONFIANCE_MOT:
            continue
        debut, fin = presence(vu)
        if not debut <= quand <= fin:
            continue
        if vu["t"] in fetes:
            continue
        return vu
    return None


def duree_audio(chemin: Path) -> float:
    """La durée d'un morceau, demandée au fichier et non devinée du poids."""
    sortie = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(chemin)],
        capture_output=True, text=True, check=False)
    try:
        return float(sortie.stdout.strip())
    except ValueError:
        return 0.0


# De combien on baisse la musique pendant que la voix parle.
#
# Pour qu'une phrase se comprenne par-dessus un fond, il lui faut environ six
# décibels d'avance : c'est une donnée d'audition et non un goût de mixeur. Les
# morceaux tournent autour de 0,22 efficace et les répliques sont gravées à
# 0,12 ; à 0,35 la musique posait 0,077 et la voix ne passait qu'un décibel et
# demi au-dessus — on l'entendait parler sans comprendre ce qu'elle disait, ce
# qui est la pire des trois possibilités. À 0,25 l'avance est de sept décibels.
#
# Et pas moins : le morceau doit rester là. C'est une plaisanterie posée sur
# une musique, pas une annonce de gare qui coupe tout.
ATTENUATION = 0.25
# Vingt minutes sans la moindre détection avant que le flux le dise, puis
# autant entre deux. Sur cette route, vingt minutes de vide sont banales la
# nuit et rares à midi : le mot arrive donc quand il est vrai.
ENNUI_S = 1200.0

# Le brouillard, dit de temps en temps et non en continu.
#
# Ici il tient des demi-journées, et pendant ce temps l'image est un mur gris :
# quelqu'un qui arrive croit que la caméra est en panne. L'écrire en
# permanence en ferait un décor, c'est-à-dire plus rien ; un quart d'heure
# entre deux, quelques secondes à chaque fois, suffit à dire que ce gris est le
# temps qu'il fait et pas un défaut.
#
# Deux mots pour deux lectures : la veille distingue le brouillard de la brume,
# et afficher « fog » sur de la brume serait lui faire dire autre chose que ce
# qu'elle a lu.
BROUILLARD_MOTS = {"brouillard": "FOOOOG", "brume": "MIIIIST"}
BROUILLARD_PAUSE_S = 900.0
BROUILLARD_TENUE_S = 3.0
# Les mêmes trois secondes pour « BOOOOORING », et pour la même raison : un mot
# doit rester assez longtemps pour être lu. Six dixièmes de seconde, ce que dure
# la réplique, font quatre images à six par seconde.
ENNUI_TENUE_S = 3.0


def repliques(dossier: Path, quand: str = "ennui") -> list[Path]:
    """Les répliques gravées pour une occasion, s'il y en a.

    Leur absence n'empêche rien : un flux sans voix est un flux, un flux qui
    s'arrête parce qu'un fichier manque n'en est plus un.
    """
    try:
        fiches = json.loads((dossier / "voix.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [dossier / f["fichier"] for f in fiches
            if f.get("quand", "ennui") == quand and (dossier / f["fichier"]).is_file()]


# Personne ne reste dix minutes sur la même chose. Les sets de mix récoltés
# durent jusqu'à cinquante-quatre minutes : on ne les jette pas, on les sert
# par tranches, et le flux change donc d'air au moins toutes les dix minutes
# même quand il s'agit du même disque.
# Quinze minutes, soit un morceau entier : le découpage avait été fait pour
# des DJ sets de cinquante minutes, qui ne sont plus dans la bibliothèque.
# Couper un morceau de quinze en deux ferait annoncer deux fois le même titre.
TRANCHE_MAX_S = 900.0
# Et en dessous de quoi une tranche ne vaut plus la peine d'exister : couper un
# set de 62 minutes donne six tranches et un bout de deux minutes, qu'on recolle
# plutôt que de le laisser traîner.
TRANCHE_MIN_S = 150.0
# La frontière entre un morceau et un set. La nuit tire d'abord dans les sets,
# le jour d'abord dans les morceaux : une route déserte à quatre heures du
# matin demande de la durée, et la même route à midi demande du changement.
LONG_S = 600.0


def _tranches(piste: Path, duree: float) -> list[dict]:
    """Un morceau, découpé en tranches d'au plus dix minutes."""
    if duree <= TRANCHE_MAX_S:
        return [{"f": piste.name, "chemin": piste, "debut": 0.0, "d": duree}]
    bouts = []
    debut = 0.0
    while debut < duree:
        fin = min(debut + TRANCHE_MAX_S, duree)
        if duree - fin < TRANCHE_MIN_S:
            fin = duree
        bouts.append({"f": piste.name, "chemin": piste, "debut": debut, "d": fin - debut})
        debut = fin
    return bouts


def _auteurs(dossier: Path) -> dict[str, str]:
    """Le nom de l'auteur par fichier, lu dans les crédits s'ils sont là."""
    try:
        credits = json.loads((dossier / "credits.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {nom: (fiche.get("auteur") or "").strip().lower()
            for nom, fiche in credits.items() if isinstance(fiche, dict)}


def _entrelace(premier: list[Path], second: list[Path],
               tirage: random.Random) -> list[Path]:
    """Mêle les deux paquets au lieu de les enchaîner.

    Chaque morceau reçoit sa place proportionnelle dans son propre paquet,
    puis on range tout le monde sur cette place commune. Les deux paquets se
    répartissent donc sur toute la durée quelles que soient leurs tailles —
    seize longs et cent dix-neuf courts donnent un long tous les sept courts
    environ, au lieu de seize longs puis cent dix-neuf courts.

    Le paquet favori passe devant à place égale : c'est tout ce que « la nuit
    penche vers les sets » peut vouloir dire honnêtement quand un paquet est
    sept fois plus petit que l'autre.
    """
    rangs = []
    for rang, paquet in enumerate((premier, second)):
        lot = paquet[:]
        tirage.shuffle(lot)
        for i, piste in enumerate(lot):
            rangs.append(((i + 0.5) / len(lot), rang, i, piste))
    rangs.sort(key=lambda r: r[:3])
    return [r[3] for r in rangs]


# Combien de noms différents au moins entre deux passages du même. Trois, parce
# qu'avec un seul on obtient une alternance à deux noms et pas de la variété :
# la règle refusait le voisin immédiat, donc un artiste bien fourni occupait les
# rangs un, trois, cinq et sept. Trois sur trente-quatre artistes est tenable
# sans jamais devoir y renoncer.
MEMOIRE_ARTISTES = 3


def _espace(suite: list[Path], auteurs: dict[str, str],
            memoire: int = MEMOIRE_ARTISTES) -> list[Path]:
    """Garde quelques noms d'écart entre deux morceaux du même artiste.

    La durée ne dit pas qui joue. Deux morceaux courts du même artiste tombent
    côte à côte aussi facilement que deux longs, et le mélange par paquets n'y
    peut rien : seul le nom le sait.

    On cherche donc le premier morceau dont l'auteur n'est pas dans les trois
    derniers passés. S'il n'y en a pas, on se contente de deux, puis d'un, puis
    de n'importe lequel : une bibliothèque d'un seul artiste doit continuer à
    jouer, un silence serait pire qu'une répétition.
    """
    if not auteurs:
        return suite
    reste = suite[:]
    ordre: list[Path] = []
    recents: list[str] = []
    while reste:
        choisi = 0
        for profondeur in range(min(memoire, len(recents)), 0, -1):
            interdits = set(recents[-profondeur:])
            trouve = next((i for i, p in enumerate(reste)
                           if auteurs.get(p.name, p.name) not in interdits), None)
            if trouve is not None:
                choisi = trouve
                break
        piste = reste.pop(choisi)
        recents.append(auteurs.get(piste.name, piste.name))
        del recents[:-memoire]
        ordre.append(piste)
    return ordre


def batir_session(dossier: Path, heures: float = SESSION_H, graine: int | None = None,
                  nuit: bool = False) -> Path | None:
    """Tire une session dans la bibliothèque et l'écrit pour ffmpeg.

    Tirée sans remise tant qu'il reste des morceaux : entendre deux fois le
    même titre avant d'avoir entendu tous les autres est ce qui fait qu'un flux
    sonne comme une boucle plutôt que comme une soirée.
    """
    if not dossier.is_dir():
        return None
    morceaux = sorted(p for p in dossier.iterdir() if p.suffix.lower() in EXTENSIONS)
    if not morceaux:
        return None
    durees = {p: duree_audio(p) for p in morceaux}
    morceaux = [p for p in morceaux if durees[p] > 1.0]
    if not morceaux:
        return None
    tirage = random.Random(graine)
    # Deux paquets : les sets et les morceaux. La nuit penche vers les sets, le
    # jour vers les morceaux — mais les deux sont mêlés, pas enchaînés.
    #
    # Enchaînés, ils donnaient quatre heures du même artiste pour ouvrir chaque
    # nuit. Les seize longs de la bibliothèque sont tous de thepriben, donc
    # « commencer par les sets » revenait à commencer par les seize, soit
    # quatre heures avant d'entendre quelqu'un d'autre. Le découpage par durée
    # était un bon moyen de distinguer une ambiance d'un morceau ; il ne l'est
    # plus dès qu'un seul nom remplit un des deux paquets.
    sets = [p for p in morceaux if durees[p] > LONG_S]
    courts = [p for p in morceaux if durees[p] <= LONG_S]
    premier, second = (sets, courts) if nuit else (courts, sets)
    auteurs = _auteurs(dossier)
    suite: list[dict] = []
    total = 0.0
    # Un tour complet d'abord. Couper au milieu du premier mélange, c'est
    # garantir que les derniers du tirage n'existent pas : le 4 octobre, la
    # bibliothèque faisait quatorze heures et quelques, la session s'arrêtait
    # à quatorze pile, et Komiku (« An anarchist utopia », soixante-quatre
    # secondes) n'était tout simplement pas dans la file.
    premier_tour = True
    while total < heures * 3600 or premier_tour:
        tour = _espace(_entrelace(premier, second, tirage), auteurs)
        if not tour:
            break
        for piste in tour:
            for bout in _tranches(piste, durees[piste]):
                suite.append(bout)
                total += bout["d"]
            if not premier_tour and total >= heures * 3600:
                break
        premier_tour = False
    chemin = dossier / "session.txt"
    chemin.write_text("".join(
        "file '%s'\ninpoint %.3f\noutpoint %.3f\n"
        % (str(b["chemin"].resolve()).replace("'", "'\\''"), b["debut"], b["debut"] + b["d"])
        for b in suite), encoding="utf-8")
    # L'ordre et les durées à côté de la liste : c'est ce qui permettra de dire
    # à l'écran quel morceau passe, sans redemander quoi que ce soit à ffmpeg.
    (dossier / "session.json").write_text(
        json.dumps([{"f": b["f"], "d": b["d"]} for b in suite]), encoding="utf-8")
    log.info("Session %s de %.1f h : %d tranches, %d sets et %d morceaux",
             "de nuit" if nuit else "de jour", total / 3600, len(suite), len(sets), len(courts))
    return chemin


class Musique:
    """La session, décodée au fil de l'eau et servie par tranches.

    Un seul ffmpeg tourne en fond et rend du son brut ; on y puise exactement
    ce qu'il faut à chaque image. Quand la session s'achève, on en tire une
    autre : un flux qui se tait est un flux que YouTube finit par couper.
    """

    def __init__(self, dossier: Path, racine: Path | None = None,
                 muet: bool = False) -> None:
        self.dossier = dossier
        self.racine = racine or dossier.parent.parent
        # Un interrupteur, et non le retrait des fichiers : le jour où une
        # réclamation tombe, il faut pouvoir se taire en une minute sans rien
        # casser ni rien perdre, et rallumer aussi vite une fois le coupable
        # trouvé.
        self.muet = muet
        self.session = None if muet else batir_session(dossier, nuit=est_nuit(self.racine))
        self.process: subprocess.Popen | None = None
        # Trois repères, et non un seul compteur remis à zéro.
        #
        # « octets » est tout ce qu'on a remis à ffmpeg depuis le début, et ne
        # revient jamais en arrière : c'est la seule grandeur qui puisse servir
        # de référence commune aux deux autres.
        # « session_a » est sa valeur quand la session en cours a commencé, de
        # quoi ramener une position absolue à une position dans la session.
        # « repere » est sa valeur quand la sortie en cours s'est ouverte : une
        # sortie neuve repart de zéro et oublie tout ce qu'on avait versé dans
        # la précédente.
        self.octets = 0
        self.session_a = 0
        self.repere = 0
        # Où en est l'image réellement diffusée, en secondes depuis l'ouverture
        # de la sortie. Posée par la boucle des images ; c'est l'horloge du
        # spectateur, et donc la seule qui ait le droit de dater un crédit.
        self.ecran = 0.0
        self.suite: list[dict] = []
        self.fiches: dict[str, dict] = {}
        self.voix = b""
        self.voix_dit = ""
        self.energie = 0.0
        self._verrou = threading.Lock()
        self.repliques = repliques(self.racine / "data" / "voix", "ennui")
        self.felicitations = repliques(self.racine / "data" / "voix", "attrape")
        self.brouillards = repliques(self.racine / "data" / "voix", "brouillard")
        self.matins = repliques(self.racine / "data" / "voix", "matin")
        self.redifferes = repliques(self.racine / "data" / "voix", "rediff")
        self.grognements = repliques(self.racine / "data" / "voix", "ours")
        self.cris_dours = repliques(self.racine / "data" / "voix", "ours_cri")
        self.remerciements = repliques(self.racine / "data" / "voix", "machine")
        self.remerciements_dogmazic = repliques(self.racine / "data" / "voix", "dogmazic")
        # Tenues hors du tableau du site : une pensée, puis la Normandie.
        self.pensees = repliques(self.racine / "data" / "voix", "pensee")
        self.deplois = repliques(self.racine / "data" / "voix", "deploi")
        self.dijons = repliques(self.racine / "data" / "voix", "dijon")
        self.dijon23 = repliques(self.racine / "data" / "voix", "dijon23")
        try:
            self.fiches = json.loads((dossier / "credits.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self._ouvre()

    def _ouvre(self) -> None:
        if self.muet or self.session is None:
            return
        try:
            self.suite = json.loads((self.dossier / "session.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.suite = []
        self.process = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(self.session),
             # Les morceaux d'une bibliothèque n'ont pas tous le même niveau,
             # et six décibels d'écart entre deux titres font sursauter à trois
             # heures du matin. « dynaudnorm » recale au fil de l'eau pour
             # quelques pour cent de processeur, là où « loudnorm » demanderait
             # une passe entière sur chaque fichier.
             "-af", "dynaudnorm=f=250:g=15",
             "-f", "s16le", "-ar", str(ECHANTILLONS_S), "-ac", str(VOIES), "-"],
            stdout=subprocess.PIPE, bufsize=10 ** 7)

    def dis(self, clip: Path) -> bool:
        """Met une réplique en attente : elle partira avec la prochaine tranche.

        Appelée depuis le fil des images alors que le son se sert dans un autre
        fil, d'où le verrou. Il ne protège que deux affectations, mais sans lui
        une tranche pourrait emporter la moitié d'un clip et la moitié du
        suivant.
        """
        try:
            brut = clip.read_bytes()
        except OSError:
            return False
        with self._verrou:
            self.voix = brut
            self.voix_dit = clip.stem
        return True

    def parle(self) -> bool:
        """Vrai tant qu'il reste de la voix à servir.

        Le compte des octets est la seule horloge honnête pour savoir si la
        voix parle encore : une minuterie posée en parallèle finirait par
        décrocher du son.

        Ce n'est plus ce qui commande la durée du mot à l'écran, qui tient
        trois secondes de son côté. Une voix intelligible dit « boring » en six
        dixièmes de seconde, et le mot clignotait quatre images. Le son dure ce
        qu'il dure, le sous-titre dure ce qu'il faut pour être lu.
        """
        with self._verrou:
            return bool(self.voix)

    def dit_quoi(self) -> str:
        """L'occasion de la réplique en cours : « ennui », « attrape », ou rien.

        Les deux voix ne veulent pas le même écran, et c'est le nom du clip qui
        le dit — pas un drapeau de plus à tenir à jour en parallèle.
        """
        with self._verrou:
            return (self.voix_dit or "").split("_")[0] if self.voix else ""

    def tranche(self, octets: int) -> bytes:
        """Le son des prochaines images, ou du silence si la musique manque.

        Rien de ce qui arrive ici ne peut faire tomber le flux. La musique est
        l'agrément, l'image est le sujet : un fichier effacé sous les pieds du
        lecteur doit faire du silence, pas une antenne noire. C'est pourtant ce
        qui est arrivé le premier octobre, et ça a coûté la diffusion.
        """
        if self.process is None or self.process.stdout is None:
            return self._avec_la_voix(b"\0" * octets)
        try:
            morceau = self.process.stdout.read(octets)
        except OSError:
            morceau = b""
        if len(morceau) < octets:
            # Soit la session est finie, soit un de ses fichiers a disparu
            # pendant qu'on jouait — ce qui se produit dès qu'on nettoie la
            # bibliothèque sans redémarrer. Dans les deux cas on en rebat une
            # et on complète la tranche, pour qu'aucun battement ne parte
            # incomplet.
            try:
                self.arrete()
                # La session neuve commence exactement là où l'ancienne s'est
                # tarie, c'est-à-dire après la fin de tranche qu'on vient de
                # lire — et non au début de la tranche, qui tient encore les
                # dernières mesures du morceau précédent.
                self.session_a = self.octets + len(morceau)
                # La session suivante est bâtie pour l'heure qu'il sera, pas
                # pour celle qu'il était : une session de jour tirée à cinq
                # heures du matin jouerait au soleil levant une sélection
                # faite pour la nuit.
                if not self.muet:
                    self.session = batir_session(self.dossier,
                                                 nuit=est_nuit(self.racine))
                    self._ouvre()
                if self.process is not None and self.process.stdout is not None:
                    morceau += self.process.stdout.read(octets - len(morceau))
            except Exception:
                log.warning("La musique s'est tue, le flux continue",
                            exc_info=True)
                self.process = None
        self.octets += octets
        servi = self._avec_la_voix(morceau.ljust(octets, b"\0"))
        self._mesure(servi)
        return servi

    def _mesure(self, morceau: bytes) -> None:
        """Garde l'énergie de ce qu'on vient de servir, pour ce qui danse dessus.

        Mesurée ici et nulle part ailleurs : c'est le seul endroit du programme
        qui tient les échantillons réellement envoyés. Un calcul fait à côté,
        sur le fichier, danserait sur ce que la musique sera dans deux secondes.

        Un échantillon sur huit suffit pour une moyenne quadratique — on ne
        cherche pas une mesure d'ingénieur du son, seulement de quoi savoir si
        ça bouge.
        """
        echantillons = np.frombuffer(morceau, np.int16)[::8]
        if echantillons.size == 0:
            return
        niveau = float(np.sqrt(np.mean(echantillons.astype(np.float32) ** 2))) / 32768.0
        with self._verrou:
            # Lissé : sans ça les danseurs clignoteraient au rythme des silences
            # entre deux coups de grosse caisse, ce qui n'est pas danser.
            self.energie = 0.82 * self.energie + 0.18 * niveau

    def pouls(self) -> float:
        """L'énergie du son servi, de 0 à 1 environ."""
        with self._verrou:
            return self.energie

    def _avec_la_voix(self, morceau: bytes) -> bytes:
        """Baisse la musique et pose la voix par-dessus, le temps qu'elle dure.

        La somme se fait en entiers larges avant d'être ramenée à seize bits :
        additionner deux signaux forts directement en seize bits ne sature pas,
        il reboucle, et un dépassement en audio ne s'entend pas comme un son
        trop fort mais comme un claquement.
        """
        with self._verrou:
            reste = self.voix
        if not reste:
            return morceau
        combien = min(len(reste), len(morceau))
        combien -= combien % (VOIES * OCTETS_PAR_ECHANTILLON)
        if combien <= 0:
            with self._verrou:
                self.voix = b""
            return morceau
        fond = np.frombuffer(morceau[:combien], np.int16).astype(np.int32)
        dessus = np.frombuffer(reste[:combien], np.int16).astype(np.int32)
        melange = np.clip((fond * ATTENUATION).astype(np.int32) + dessus, -32768, 32767)
        with self._verrou:
            self.voix = reste[combien:]
        return melange.astype(np.int16).tobytes() + morceau[combien:]

    def a_l_ecran(self, seconde: float) -> None:
        """Dit où en est l'image diffusée, en secondes depuis l'ouverture.

        C'est le compte d'images, et rien d'autre : ffmpeg date la nième image
        à n divisé par la cadence, donc ce nombre est l'instant exact où ce
        qu'on dessine maintenant sera regardé.
        """
        self.ecran = seconde

    def repart(self) -> None:
        """Une sortie neuve : son horloge repart de zéro, pas la musique.

        Tout ce qui avait été versé dans la sortie précédente est perdu avec
        elle. Le premier octet de la nouvelle est donc celui qu'on en est à
        remettre, et c'est lui qui vaut l'instant zéro de sa vidéo.
        """
        self.repere = self.octets
        self.ecran = 0.0

    def _seconde(self) -> float:
        """Où en est le morceau que le spectateur entend en ce moment.

        Et non : où en est le morceau qu'on vient de remettre à ffmpeg. Les
        deux ne sont pas du tout le même instant, et c'est ce qui désynchronisait
        le crédit de la musique.

        Le son qu'on verse ne part pas quand on le verse. Il attend dans la
        file de l'entrée — cinq cent douze paquets, soit près de deux mégaoctets,
        soit douze secondes — puis dans l'encodeur. Mesuré : le compteur
        d'octets court douze secondes devant l'image. Le titre changeait donc à
        l'écran douze secondes avant de changer dans les oreilles.

        Cette file ne se réduit pas pour autant. Si elle venait à se vider
        parce que le fil du son a été endormi une demi-seconde de trop, ffmpeg
        attendrait du son, et l'image attendrait avec lui : la musique est
        l'agrément, l'image est le sujet, et l'agrément n'a pas le droit
        d'arrêter le sujet. On garde donc le matelas, et on lit l'heure
        ailleurs.

        L'image, elle, est datée par son rang : ffmpeg place la nième image à
        n divisé par la cadence, et le son à l'octet divisé par le débit. Les
        deux horloges partent ensemble de zéro à l'ouverture de la sortie. La
        position diffusée est donc le repère d'ouverture plus l'âge de l'image,
        sans qu'aucun tampon n'entre dans le calcul et sans constante à régler.

        Plafonné à ce qu'on a vraiment remis : si la boucle des images prenait
        de l'avance sur le son, mieux vaut un crédit en retard qu'un crédit qui
        nomme un morceau qui n'a pas encore été décodé.
        """
        debit = ECHANTILLONS_S * VOIES * OCTETS_PAR_ECHANTILLON
        remis = (self.octets - self.session_a) / debit
        diffuse = (self.repere - self.session_a) / debit + self.ecran
        return max(0.0, min(remis, diffuse))

    def a_suivre(self) -> str:
        """Le morceau d'après, pour qui aime savoir ce qui arrive."""
        seconde = self._seconde()
        for i, piste in enumerate(self.suite):
            if seconde < piste["d"]:
                if i + 1 >= len(self.suite):
                    return ""
                fiche = self.fiches.get(self.suite[i + 1]["f"])
                return "" if not fiche else f"{fiche['auteur']} — {fiche['titre']}"
            seconde -= piste["d"]
        return ""

    def programme(self) -> dict:
        """Ce qui passe, où on en est dedans, et les deux morceaux qui suivent.

        Des blocs posés et lisibles valent mieux qu'un titre qui défile : on ne
        peut pas demander à quelqu'un d'attendre qu'un ruban repasse pour
        savoir ce qu'il écoute, et c'est précisément ce qu'on lui demande de
        noter s'il veut retrouver le morceau.

        Deux à suivre et non un seul, et la position dans le morceau en plus.
        Un seul titre à venir et aucune idée du temps restant, ça renseigne
        sans donner envie d'attendre ; une file et une jauge, c'est un
        programme — on sait qu'il va se passer quelque chose et quand.

        On sait où on en est sans rien demander à personne : le son est servi
        par tranches, donc le nombre d'octets versés divisé par le débit donne
        les secondes écoulées, et les durées de la session disent lequel c'est.
        """
        seconde = self._seconde()
        for i, piste in enumerate(self.suite):
            if seconde >= piste["d"]:
                seconde -= piste["d"]
                continue
            # Deux tranches du même set ne sont pas deux morceaux. Tant qu'on
            # reste sur le même fichier on est dans le même morceau : c'est
            # vrai pour la jauge, qui doit mesurer le set entier et non la
            # tranche en cours, et c'est vrai pour la file, qui annoncerait
            # sinon comme « à suivre » ce qu'on est déjà en train d'écouter.
            debut = i
            while debut > 0 and self.suite[debut - 1]["f"] == piste["f"]:
                debut -= 1
            fin = i
            while fin + 1 < len(self.suite) and self.suite[fin + 1]["f"] == piste["f"]:
                fin += 1
            ecoule = sum(self.suite[j]["d"] for j in range(debut, i)) + seconde
            duree = sum(self.suite[j]["d"] for j in range(debut, fin + 1))

            def tenue(nom: str) -> float:
                return sum(p["d"] for p in self.suite if p["f"] == nom)

            def copie(fiche: dict | None, long: float) -> dict | None:
                if not fiche:
                    return None
                vue = dict(fiche)
                vue["duree"] = long
                return vue

            avant = None
            if debut > 0:
                nom_avant = self.suite[debut - 1]["f"]
                avant = copie(self.fiches.get(nom_avant), tenue(nom_avant))
            suite, j, vus = [], fin + 1, {piste["f"]}
            while j < len(self.suite) and len(suite) < 2:
                nom = self.suite[j]["f"]
                if nom not in vus:
                    vus.add(nom)
                    fiche = copie(self.fiches.get(nom), tenue(nom))
                    if fiche:
                        suite.append(fiche)
                j += 1
            return {"avant": avant,
                    "en_cours": copie(self.fiches.get(piste["f"]), duree),
                    "ecoule": ecoule, "duree": duree, "suite": suite}
        return dict(PROG_VIDE)

    def credit(self) -> str:
        """Qui on est en train de diffuser, en toutes lettres.

        CC-BY demande de nommer l'auteur, l'œuvre et la licence. Une liste dans
        la description ne le fait pas vraiment : la session est tirée au hasard
        et change toutes les quatorze heures, donc celui qui regarde à trois
        heures du matin n'a aucun moyen de savoir laquelle des quarante lignes
        le concerne. L'écrire sur l'image pendant que ça joue, si.

        On sait où on en est sans rien demander à personne : le son est servi
        par tranches, donc le nombre d'octets versés divisé par le débit donne
        les secondes écoulées, et les durées de la session disent lequel c'est.
        """
        return qui_passe(self.suite, self.fiches, self._seconde())

    def arrete(self) -> None:
        """Ferme le lecteur de musique, s'il y en a un.

        Cette méthode avait disparu de la classe : elle était échouée à
        l'intérieur de « qui_passe », après le return, donc inaccessible et
        absente d'ici. Les deux appels la cherchaient pourtant — celui de la
        fin de session et celui de l'arrêt du programme — et tous deux
        levaient une AttributeError. C'est ce qui a terminé la diffusion du
        premier octobre à vingt heures : le fil du son est mort sur le chemin
        censé le réparer, l'écriture vidéo s'est fermée derrière lui, et
        YouTube a clos la diffusion.
        """
        if self.process is not None:
            self.process.kill()
            self.process = None


def qui_passe(suite: list[dict], fiches: dict[str, dict], seconde: float) -> str:
    """Le morceau à cette seconde de la session, nommé comme la licence l'exige."""
    for piste in suite:
        if seconde < piste["d"]:
            fiche = fiches.get(piste["f"])
            if not fiche:
                return ""
            return f"♪ {fiche['auteur']} — {fiche['titre']} · {fiche['licence']}"
        seconde -= piste["d"]
    return ""


def est_nuit(racine: Path) -> bool:
    """Ce que la veille vient d'écrire du moment de la journée.

    Le crépuscule compte pour la nuit : c'est l'heure où la route se vide, et
    c'est de la durée qu'il faut alors, pas du changement.
    """
    moment = (lecture_du_ciel(racine / "data" / "view.json").get("period") or "").lower()
    return moment in {"night", "twilight", "dusk", "dawn"}


def lecture_du_ciel(chemin: Path) -> dict:
    """Ce que la veille lit du temps qu'il fait, tel qu'elle vient de l'écrire."""
    try:
        return (json.loads(chemin.read_text(encoding="utf-8")).get("last") or {})
    except (OSError, ValueError):
        return {}


# Les mots que la veille emploie, et leur équivalent anglais. Le flux s'adresse
# à qui passe, et ce qui passe sur un direct de webcam ne parle pas français.
ANGLAIS = {
    "ciel dégagé": "clear", "peu nuageux": "fair", "nuageux": "cloudy",
    "couvert": "overcast", "brouillard": "fog", "brume": "mist",
    "pluie": "rain", "neige": "snow", "orage": "storm",
    "nuit": "night", "jour": "day",
}


COULEURS = {
    "ciel dégagé": (235, 215, 70), "peu nuageux": (225, 225, 225),
    "nuageux": (190, 190, 190), "couvert": (160, 160, 160),
    "brouillard": (200, 200, 200), "brume": (210, 210, 210),
    "pluie": (240, 180, 90), "neige": (245, 245, 245),
    "orage": (90, 90, 245), "nuit": (200, 170, 120),
}


def altitude_camera(racine: Path) -> float | None:
    """L'altitude du point de vue, prise dans notre propre modèle de terrain.

    Pas dans un almanach : le relief qu'on affiche doit être celui qui sert à
    mesurer les distances, sinon le flux raconte une montagne et la veille en
    mesure une autre. Le centre de la grille est le point de la caméra.
    """
    try:
        grille = json.loads((racine / "data" / "osm" / "terrain.json")
                            .read_text(encoding="utf-8"))["grid"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not grille:
        return None
    ligne = grille[len(grille) // 2]
    return float(ligne[len(ligne) // 2])


def ligne_lieu(camera: dict, altitude: float | None) -> str:
    """« MONT SEREIN · 44.1835 N 5.2621 E · 1 389 m »."""
    lat = camera.get("lat")
    lon = camera.get("lon")
    bouts = ["MONT SEREIN · MONT VENTOUX"]
    if lat is not None and lon is not None:
        bouts.append(f"{abs(float(lat)):.4f} {'N' if float(lat) >= 0 else 'S'}"
                     f" {abs(float(lon)):.4f} {'E' if float(lon) >= 0 else 'W'}")
    if altitude is not None:
        bouts.append(f"{altitude:.0f} m")
    return " · ".join(bouts)


# Le ruban du haut, en anglais : c'est la bande-son qu'il annonce, et la
# musique libre se parle en anglais d'un bout à l'autre du monde.
RUBAN_H = 44
VITESSE_RUBAN = 90.0  # pixels par seconde, à 1600 de large
ECART_RUBAN = "      ·      "


# Le pas du balayage qui cherche les heures du soleil. Une minute : l'astre
# monte d'au plus un quart de degré en une minute sous nos latitudes, et la
# crête en fait vingt-deux — chercher plus fin ne dirait rien de plus.
PAS_SOLEIL_S = 60.0


def heures_du_soleil(terrain, camera: dict, quand: float) -> dict:
    """Les quatre heures du jour, ici et pas ailleurs.

    Le lever et le coucher sont ceux de l'almanach : le bord haut du disque à
    l'horizon théorique. Les deux autres sont propres à ce point de vue — le
    moment où le soleil sort de derrière la crête le matin, et celui où il y
    rentre le soir. Au Mont Serein l'écart est d'une heure et quart le soir :
    la pente est dans l'ombre longtemps avant que le soleil se couche, et c'est
    la chose la plus locale qu'on puisse dire de cette image.

    Balayé minute par minute plutôt que résolu : l'horizon est un terrain, pas
    une fonction, et on n'a pas de formule pour l'instant où une montagne passe
    devant le soleil. Mille quatre cents comparaisons par jour, faites une fois
    par jour, ne se sentent pas.

    Rend un dictionnaire aux clés manquantes quand l'évènement n'a pas lieu —
    au-dessus du cercle polaire, ou derrière une crête qui ne libère jamais le
    soleil. On n'invente pas une heure pour faire joli.
    """
    from watcher.scene import solar_azimuth, solar_elevation
    minuit = datetime.fromtimestamp(quand, PARIS).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()
    oeil = float(camera.get("ele") or 0.0)
    lat, lon = camera["lat"], camera["lon"]
    heures: dict[str, float] = {}
    avant_ciel: bool | None = None
    avant_crete: bool | None = None
    pas = 0
    while pas * PAS_SOLEIL_S < 86400:
        instant = minuit + pas * PAS_SOLEIL_S
        pas += 1
        moment = datetime.fromtimestamp(instant, timezone.utc)
        haut = solar_elevation(moment, lat, lon)
        sur_ciel = haut > HORIZON
        if avant_ciel is not None and sur_ciel != avant_ciel:
            heures["lever" if sur_ciel else "coucher"] = instant
        avant_ciel = sur_ciel
        if terrain is None:
            continue
        sur_crete = sur_ciel and haut > terrain.skyline(solar_azimuth(moment, lat, lon), oeil)
        if avant_crete is not None and sur_crete != avant_crete:
            heures["crete_matin" if sur_crete else "crete_soir"] = instant
        avant_crete = sur_crete
    return heures


def _hhmm(instant: float) -> str:
    return datetime.fromtimestamp(instant, PARIS).strftime("%H:%M")


def morceaux_soleil(heures: dict, quand: float,
                    demain: dict | None = None) -> list[tuple[str, tuple[int, int, int]]]:
    """Ce que le ruban dit du soleil, selon l'heure qu'il est.

    Une seule phrase à la fois, et celle qui est vraie maintenant : annoncer
    le lever à dix-huit heures n'apprend rien à qui regarde, et quatre lignes
    d'almanach feraient du ruban un calendrier.

    Après le coucher il faut les heures du lendemain, pas celles du jour : le
    flux a annoncé « FIRST LIGHT ON THIS SLOPE 08:16 » à neuf heures du soir,
    ce qui donnait pour imminente une heure passée depuis treize heures. Sans
    les heures de demain on se taît, parce qu'une heure fausse au présent est
    pire qu'une ligne en moins.
    """
    matin, soir = heures.get("crete_matin"), heures.get("crete_soir")
    coucher, lever = heures.get("coucher"), heures.get("lever")
    if matin is not None and quand < matin:
        tard = "" if lever is None else f" · SUNRISE {_hhmm(lever)}"
        return [("SUN CLEARS THE RIDGE ", AMBRE), (_hhmm(matin) + tard, BLANC)]
    if soir is not None and quand < soir:
        tard = "" if coucher is None else f" · SUNSET {_hhmm(coucher)}"
        return [("RIDGE SHADOW AT ", AMBRE), (_hhmm(soir) + tard, BLANC)]
    if soir is not None and coucher is not None and soir <= quand < coucher:
        # L'heure qui vaut le détour : la pente est à l'ombre, et le soleil est
        # encore au-dessus de l'horizon pour tout le monde en bas. Après le
        # coucher ce n'est plus l'ombre du Ventoux, c'est la nuit, et le dire
        # serait s'attribuer l'obscurité de la Terre entière.
        return [("IN THE SHADOW OF THE VENTOUX FOR ", AMBRE),
                (f"{int((quand - soir) / 60)} MIN · SUN SETS AT {_hhmm(coucher)}", BLANC)]
    tot = (demain or {}).get("crete_matin")
    if tot is not None:
        lever_demain = (demain or {}).get("lever")
        tard = "" if lever_demain is None else f" · SUNRISE {_hhmm(lever_demain)}"
        return [("FIRST LIGHT ON THIS SLOPE TOMORROW ", AMBRE),
                (_hhmm(tot) + tard, BLANC)]
    return []


# La vue 3D à la place de la caméra, de temps en temps.
#
# Deux minutes, une demi-heure entre deux, et seulement quand il ne se passe
# rien : la webcam est ce qu'on vient voir, et un modèle de terrain par-dessus
# une voiture qui passe serait un écran de veille posé sur l'évènement.
VUE3D_TENUE_S = 120.0
VUE3D_PAUSE_S = 1800.0
# La nuit, le survol s'arrête sur une image. Une minute et demie, contre deux
# minutes le jour : un plan fixe se lit en entier dès les premières secondes
# et n'a plus rien à donner ensuite, là où un survol qui tourne apprend quelque
# chose du relief jusqu'au bout.
VUE3D_NUIT_S = 90.0
# Le rendu est en plein soleil. La nuit, le laisser tel quel dirait qu'il
# fait jour. Ce n'est pas un réglage de cette caméra : une maquette de jour
# posée sur une pente noire ment sur l'heure.
VUE3D_NUIT = 0.4


def charge_vue3d(racine: Path) -> list[Path]:
    """Les images du survol, s'il a été filmé.

    Des images et non la vidéo : la machine n'a pas de puce graphique et ne
    peut pas dessiner la scène, mais elle peut très bien ouvrir un JPEG par
    image — quelques millisecondes, contre un décodeur vidéo de plus à faire
    tourner en parallèle de celui qui encode déjà la diffusion.

    Vide si le dossier n'est pas là, et alors le flux n'en parle plus. Le
    survol est un agrément ; il ne doit pas pouvoir empêcher une webcam de
    fonctionner.
    """
    dossier = racine / "data" / "vue3d"
    if not dossier.is_dir():
        return []
    return sorted(dossier.glob("*.jpg"))


def image_vue3d(images: list[Path], age: float, par_seconde: float) -> np.ndarray | None:
    """L'image du survol à montrer après tant de secondes, en boucle.

    Le survol est un aller-retour complet, donc il reboucle sans raccord : la
    dernière image et la première sont le même point de vue.
    """
    if not images:
        return None
    rang = int(max(0.0, age) * par_seconde) % len(images)
    return cv2.imread(str(images[rang]))


def vue3d_poste(images: list[Path], nuit: bool) -> np.ndarray | None:
    """Le point de vue de la caméra, une image, qui ne bouge pas.

    La première image du survol est ce point de vue. Un rectangle mesuré
    sur la webcam s'y pose sans être traduit. La nuit, le plein soleil du
    rendu est baissé.
    """
    if not images:
        return None
    image = cv2.imread(str(images[0]))
    if image is None or not nuit:
        return image
    return np.clip(image.astype(np.float32) * VUE3D_NUIT, 0, 255).astype(np.uint8)


def vue3d_arretee(images: list[Path]) -> np.ndarray | None:
    """Une seule image du survol, toujours la même.

    Celle du milieu. Le survol est un aller-retour : ses deux extrémités sont
    le même point de vue de départ, qui est justement celui de la caméra —
    montrer ça la nuit ne dirait rien de plus que la nuit elle-même. Le milieu
    du trajet est le point le plus éloigné, celui d'où l'on voit le versant de
    côté et où le relief se lit.
    """
    if not images:
        return None
    return cv2.imread(str(images[len(images) // 2]))


def morceaux_ruban(lieu: str, ciel: dict,
                   soleil: list[tuple[str, tuple[int, int, int]]] | None = None,
                   ) -> list[tuple[str, tuple[int, int, int]]]:
    """Le ruban du haut : le lieu et le temps qu'il fait, par morceaux colorés.

    L'étiquette en couleur, la valeur en blanc. Les chaînes d'information font
    toutes cela, et pour une bonne raison : l'œil attrape la couleur, trouve
    l'étiquette, et sait quoi lire ensuite. Tout en blanc, un ruban n'est qu'une
    ligne qui bouge.

    La météo défile et la musique ne défile pas : on ne peut pas demander à
    quelqu'un d'attendre qu'un ruban repasse pour savoir ce qu'il écoute, alors
    qu'on peut très bien lui demander d'attendre pour savoir la température.
    """
    bouts: list[tuple[str, tuple[int, int, int]]] = []
    if lieu:
        bouts += [(lieu, CYAN), (ECART_RUBAN, BLANC)]
    mot = (ciel.get("webcam") or "").lower()
    if mot:
        bouts += [("CAMERA SEES ", VERT), (ANGLAIS.get(mot, mot).upper(), COULEURS.get(mot, BLANC)),
                  (ECART_RUBAN, BLANC)]
    crete = ciel.get("ridge")
    if crete is not None:
        bouts += [("VISIBILITY ", VERT), (f"{max(0, min(100, round(crete)))}/100", BLANC),
                  (ECART_RUBAN, BLANC)]
    temp = ciel.get("temp_c")
    if temp is not None:
        bouts += [("TEMPERATURE ", VERT), (f"{temp} °C", BLANC), (ECART_RUBAN, BLANC)]
    # La prévision seulement quand la caméra n'a rien lu.
    #
    # Elle s'affichait au contraire quand les deux ne disaient pas la même
    # chose, c'est-à-dire exactement quand le modèle a le plus de chances
    # d'avoir tort : il interpole une grille sur un massif de mille neuf cents
    # mètres, la caméra est posée à mille trois cent quatre-vingt-dix sur une
    # pente, et elle, elle regarde le ciel. « FORECAST CLEAR » écrit pendant
    # que le brouillard remonte ne corrige pas la caméra, il fait douter d'elle.
    #
    # Elle reste donc en réserve, pour les heures où la caméra ne voit rien —
    # la nuit, surtout, où il n'y a rien à lire sur l'image.
    prevu = (ciel.get("api") or "").lower()
    if prevu and not mot:
        bouts += [("FORECAST ", AMBRE), (ANGLAIS.get(prevu, prevu).upper(), BLANC),
                  (ECART_RUBAN, BLANC)]
    # Le soleil en dernier : c'est la phrase la plus longue, et le ruban se lit
    # mieux quand ce qui change vite est devant.
    if soleil:
        bouts += list(soleil) + [(ECART_RUBAN, BLANC)]
    # Le séparateur à la fin aussi : sans lui, la copie qui entre par la droite
    # vient coller sa première lettre à la dernière de celle qui sort.
    return bouts or [("MONT SEREIN", CYAN), (ECART_RUBAN, BLANC)]


def pose_ruban(image: np.ndarray, morceaux: list[tuple[str, tuple[int, int, int]]],
               seconde: float) -> None:
    """Le ruban défile de droite à gauche, sans couture.

    Écrit deux fois à la file : quand la première copie sort par la gauche, la
    seconde est déjà entrée par la droite, et le texte tourne sans trou. C'est
    moins cher que de fabriquer une image longue et d'y découper une fenêtre.
    """
    if not morceaux:
        return
    largeur = image.shape[1]
    echelle = largeur / 1600
    haut = int(RUBAN_H * echelle)
    fond_bandeau(image, 0, haut, echelle)
    taille = 0.66 * echelle
    larges = [cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0] for t, _ in morceaux]
    long_px = sum(larges)
    if long_px <= 0:
        return
    decalage = int(seconde * VITESSE_RUBAN * echelle) % long_px
    base = haut - int(14 * echelle)
    for depart in (-decalage, -decalage + long_px):
        x = depart
        for (texte, couleur), large in zip(morceaux, larges):
            if -large < x < largeur:
                cv2.putText(image, texte, (x, base), cv2.FONT_HERSHEY_SIMPLEX,
                            taille, couleur, 2, cv2.LINE_AA)
            x += large


# Les teintes du spectacle. Elles ne touchent que l'image diffusée, posées
# avant les rectangles : la veille ne les voit jamais, et le rouge qui désigne
# ce qui a bougé reste le même rouge d'un bout à l'autre de la nuit.
#
# La moitié des créneaux ne teinte rien. Une webcam qui change de couleur sans
# arrêt cesse d'être une webcam ; c'est l'écart qui se remarque, pas l'effet.
# Cinq créneaux sur sept teintent. La première version n'en teintait que trois
# sur dix et l'effet passait inaperçu : sur un direct qu'on regarde par
# tranches de deux minutes, un effet qui n'arrive qu'une fois sur trois
# n'arrive jamais. Il reste deux créneaux sobres sur sept, assez pour que la
# webcam se rappelle qu'elle est une webcam.
TEINTES = [("", 0.0, 0.0)] * 2 + [
    ("psyche", 1.0, 0.55),
    ("psyche", 0.6, 0.45),
    ("lent", 0.25, 0.60),
    ("lent", 0.15, 0.50),
    ("vif", 1.8, 0.45),
]
TEINTE_S = 150.0
FONDU_S = 6.0


def teinte_du_moment(seconde: float) -> tuple[float, float]:
    """Le tour de couleur de ce créneau et sa force, déduits de l'heure seule.

    Rien à retenir d'une image sur l'autre : le numéro du créneau sert de
    graine, donc deux images du même créneau tombent sur le même effet même
    après un redémarrage. Un fondu aux deux bouts évite que la couleur claque.

    La teinte tourne pendant le créneau au lieu de rester posée : une couleur
    fixe est un filtre, une couleur qui tourne est une lumière, et c'est une
    lumière qu'on veut sur de la musique.
    """
    bloc = int(seconde // TEINTE_S)
    _, vitesse, force = random.Random(bloc).choice(TEINTES)
    if force <= 0:
        return 0.0, 0.0
    dedans = seconde - bloc * TEINTE_S
    montee = min(dedans, TEINTE_S - dedans) / FONDU_S
    return dedans * vitesse * 12.0, force * max(0.0, min(1.0, montee))


PIXEL_CYCLE_S = 420.0
PIXEL_S = 20.0
PIXEL_FONDU_S = 3.5
# Le nombre de blocs en largeur au plus fort — et non le côté d'un bloc en
# pixels, qui ferait dépendre l'effet de la résolution : le même réglage
# donnerait deux images différentes sur une caméra en 1280 et une en 1920.
# Vingt-six colonnes laissent la route et la crête reconnaissables, ce qui fait
# la différence entre une image traitée et une image cassée.
PIXEL_BLOCS = 26


# Un seul effet de forme à la fois, tiré dans cette liste. Les empiler —
# pixellisation sur ondulation sur gris — ne fait pas un effet plus fort, il
# fait une image qu'on n'identifie plus, et ce flux doit rester une webcam.
# Le vide y figure deux fois sur cinq : un effet qui revient à tous les coups
# cesse d'être un effet et devient le rendu normal du flux.
FORMES = ["", "", "pixel", "gris", "ondule"]


def effet_du_moment(seconde: float) -> tuple[str, float]:
    """L'effet de forme de ce créneau et sa force, déduits de l'heure seule.

    Comme la teinte : rien à retenir d'une image sur l'autre, donc un
    redémarrage au milieu d'un créneau reprend exactement où il en était.
    """
    bloc = int(seconde // PIXEL_CYCLE_S)
    quoi = random.Random(bloc * 7919).choice(FORMES)
    if not quoi:
        return "", 0.0
    dedans = seconde - bloc * PIXEL_CYCLE_S
    if dedans > PIXEL_S:
        return "", 0.0
    # Il monte et redescend dans les vingt secondes : apparaître d'un coup
    # ressemble à une panne d'encodeur, et c'est bien la dernière chose qu'on
    # veuille faire croire sur un direct.
    return quoi, max(0.0, min(1.0, min(dedans, PIXEL_S - dedans) / PIXEL_FONDU_S))


# Le creux et la crête d'une onde, en fraction de la largeur. Trois pour cent,
# c'est assez pour que la crête ondule et trop peu pour qu'on perde la route.
ONDULE_PART = 0.03
# Des bandes assez hautes pour qu'on voie l'onde et assez nombreuses pour
# qu'elle soit lisse. Vingt-quatre reprises de numpy par image, ce qui est
# négligeable là où un remap sur deux mégapixels ne le serait pas.
ONDULE_BANDES = 28


def ondule(image: np.ndarray, force: float, seconde: float) -> None:
    """Fait glisser des bandes horizontales, comme une image dans l'eau.

    Par bandes décalées et non par un remap pixel à pixel : un remap demande
    deux cartes de deux millions de flottants à refaire à chaque image, ce que
    cette machine n'a pas les moyens de payer pendant qu'elle encode. Vingt-huit
    décalages de lignes donnent la même ondulation pour presque rien.
    """
    if force <= 0.01:
        return
    hauteur, largeur = image.shape[:2]
    ampleur = largeur * ONDULE_PART * force
    pas = max(1, hauteur // ONDULE_BANDES)
    for haut in range(0, hauteur, pas):
        bas = min(haut + pas, hauteur)
        angle = (haut / hauteur) * 3.2 * math.pi + seconde * 1.6
        combien = int(math.sin(angle) * ampleur)
        if combien:
            image[haut:bas] = np.roll(image[haut:bas], combien, axis=1)


def gris(image: np.ndarray, force: float) -> None:
    """Décolore, en partie ou tout à fait.

    Les coefficients sont ceux de la luminance perçue, pas une moyenne des trois
    voies : un ciel bleu et une prairie verte de même moyenne arithmétique n'ont
    rien de la même clarté à l'œil, et une moyenne les rendrait identiques.
    """
    if force <= 0.01:
        return
    plat = cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    cv2.addWeighted(plat, force, image, 1.0 - force, 0.0, dst=image)


def applique_effet(image: np.ndarray, quoi: str, force: float, seconde: float) -> None:
    """Pose l'effet de forme du moment, quel qu'il soit."""
    if quoi == "pixel":
        pixellise(image, force)
    elif quoi == "gris":
        gris(image, force)
    elif quoi == "ondule":
        ondule(image, force, seconde)


def pixellise(image: np.ndarray, force: float) -> None:
    """Réduit puis regrossit l'image, au plus proche, sur place.

    Moins cher que de la laisser tranquille : on redimensionne deux fois une
    image qu'on a déjà, et la descente fait l'essentiel du travail sur une
    fraction des pixels. Sur une machine qui n'a pas de puce vidéo, c'est le
    seul effet du fichier qui ne coûte rien.
    """
    if force <= 0.01:
        return
    hauteur, largeur = image.shape[:2]
    colonnes = max(PIXEL_BLOCS, int(largeur - (largeur - PIXEL_BLOCS) * force))
    lignes = max(2, round(colonnes * hauteur / largeur))
    if colonnes >= largeur:
        return
    image[:] = cv2.resize(cv2.resize(image, (colonnes, lignes), interpolation=cv2.INTER_AREA),
                          (largeur, hauteur), interpolation=cv2.INTER_NEAREST)


def _matrice_teinte(angle_deg: float) -> np.ndarray:
    """La rotation des couleurs autour de l'axe des gris, en BGR.

    Une vraie rotation de teinte demanderait de passer en TSV et d'en revenir,
    soit deux conversions de deux mégapixels par image sur une machine qui
    touche déjà sa limite thermique. Une matrice trois par trois fait presque
    la même chose en une passe, et « presque » suffit à un effet de lumière.
    """
    rad = np.deg2rad(angle_deg % 360.0)
    cos, sin = float(np.cos(rad)), float(np.sin(rad))
    un, deux = 1.0 / 3.0, float(np.sqrt(1.0 / 3.0))
    a = cos + (1.0 - cos) * un
    b = un * (1.0 - cos) - deux * sin
    c = un * (1.0 - cos) + deux * sin
    # En RVB, puis retournée deux fois pour l'ordre BGR d'OpenCV.
    rvb = np.array([[a, b, c], [c, a, b], [b, c, a]], np.float32)
    return rvb[::-1, ::-1].copy()


def applique_teinte(image: np.ndarray, angle: float, force: float) -> None:
    """Fait tourner les couleurs et mélange au naturel, sur place."""
    if force <= 0.001:
        return
    tourne = cv2.transform(image, _matrice_teinte(angle))
    cv2.addWeighted(tourne, force, image, 1.0 - force, 0.0, dst=image)


# Les bandes au-dessus et au-dessous de la caméra, en pixels à 1600 de large.
# Tout écrire par-dessus l'image marchait, mais chaque ajout se disputait une
# place avec un autre et finissait par cacher la route. En posant la webcam
# dans une fenêtre et les encarts autour, plus rien ne peut entrer en conflit :
# ce qui est à la caméra reste à la caméra.
BORD_HAUT = 46
# La bande du bas tient la console musique entière, le bandeau, et le
# mot-dièse sous la fenêtre caméra. Sans cette trentaine de pixels le
# mot n'a nulle part où s'asseoir : il recouvrirait la montagne ou la
# console.
BORD_BAS = 258


def fenetre(forme: tuple[int, int], largeur: int,
            hauteur: int) -> tuple[int, int, int, int]:
    """Où la vue se pose dans la toile : x, y, largeur, hauteur.

    Calculé à part parce que deux choses en ont besoin, et pas seulement celle
    qui dessine : savoir où finit l'image, c'est aussi savoir où commencent les
    bandes noires, et il a fallu le savoir le jour où les pantins ont eu le
    droit d'y aller.
    """
    echelle = largeur / 1600
    haut = int(BORD_HAUT * echelle)
    libre = hauteur - haut - int(BORD_BAS * echelle)
    cible_l = min(largeur, int(libre * forme[1] / forme[0]))
    cible_h = int(cible_l * forme[0] / forme[1])
    return (largeur - cible_l) // 2, haut, cible_l, cible_h


def cadre(cam: np.ndarray, largeur: int, hauteur: int) -> np.ndarray:
    """Pose l'image de la caméra dans une fenêtre, et rend la toile entière.

    La fenêtre garde les proportions de la webcam : une image étirée pour
    remplir un trou est une image qui ment sur les formes, et ce flux passe son
    temps à dire qu'il mesure des largeurs en mètres.
    """
    gauche, haut, cible_l, cible_h = fenetre(cam.shape[:2], largeur, hauteur)
    toile = np.zeros((hauteur, largeur, 3), np.uint8)
    toile[haut:haut + cible_h, gauche:gauche + cible_l] = cv2.resize(
        cam, (cible_l, cible_h), interpolation=cv2.INTER_AREA)
    return toile


def _coupe(texte: str, combien: int) -> str:
    return texte if len(texte) <= combien else texte[:combien - 1] + "…"


# Ce que le player reçoit quand il n'y a pas de musique : la radio muette
# pendant une annonce, ou la session pas encore chargée au démarrage.
PROG_VIDE = {"avant": None, "en_cours": None, "ecoule": 0.0, "duree": 0.0,
             "suite": []}


def _mmss(secondes: float) -> str:
    """Une durée comme un lecteur l'écrit, et jamais autrement."""
    secondes = max(0, int(secondes))
    return f"{secondes // 60}:{secondes % 60:02d}"


# Le player, en pixels à 1600 de large. Trois bacs : ce qui vient de jouer,
# ce qui joue, ce qui suit. La pochette du milieu est plus grande — c'est
# elle qu'on écoute. Les deux autres reculent, comme sur une platine.
PLAY_MARGE = 12
PLAY_PAS = 24
PLAY_MAINTENANT = 112
PLAY_VOISINE = 80
PLAY_JAUGE_H = 5
PLAY_BARRES = 12
PLAY_BARRE_ECART = 3
PLAY_EQ_H = 26
PLAY_EQ_L = 140
PLAY_GRIS = (120, 120, 120)
PLAY_RAIL = (64, 64, 64)
PLAY_VOILE = 0.72
PLAY_POLICE = cv2.FONT_HERSHEY_DUPLEX


def _teinte_barre(i: int, n: int, forme: str, seconde: float
                  ) -> tuple[int, int, int]:
    """La couleur d'une barre : le filtre du moment, ou le vert et l'ambre.

    Le rouge reste à LIVE. Vide, c'est l'instrument habituel. Pixel, des
    plots qui changent par paquets. Gris, le filtre a déteint l'image : les
    barres aussi. Ondulé, elles glissent du cyan au vert. Rien d'inventé
    pour l'occasion — les trois couleurs du meuble, dans un autre ordre.
    """
    if forme == "gris":
        v = 100 + int(110 * i / max(1, n - 1))
        return (v, v, v)
    if forme == "pixel":
        return (CYAN, VERT, AMBRE)[(i // 4) % 3]
    if forme == "ondule":
        mix = 0.5 + 0.5 * math.sin(seconde * 1.1 + i * 0.55)
        return tuple(int(a + (b - a) * mix) for a, b in zip(CYAN, VERT))
    return AMBRE if i >= n - 6 else VERT


def _vumetre(image: np.ndarray, x: int, base: int, largeur: int,
             echelle: float, energie: float, seconde: float,
             forme: str = "") -> None:
    """Une lame d'égaliseur, pas un mur.

    Trop grand, il mangeait l'artiste et le titre. Trop large, il barrissait
    toute la console. Ici il tient sous le crédit, court comme un instrument,
    pas comme une frise. Chaque barre a sa lenteur et un halo.

    Il ne mesure rien d'utile et ne prétend pas le contraire : il est posé
    contre l'étiquette du morceau, pas contre l'image, et personne ne peut le
    prendre pour une lecture de la montagne.
    """
    if largeur < 8:
        return
    n = PLAY_BARRES
    ecart = max(1, int(PLAY_BARRE_ECART * echelle))
    large = max(2, (largeur - (n - 1) * ecart) // n)
    haut_max = max(6, int(PLAY_EQ_H * echelle))
    force = min(1.0, energie * 6.0)
    cv2.line(image, (x, base), (x + largeur, base), PLAY_RAIL, 1, cv2.LINE_AA)
    for i in range(n):
        part = i / max(1, n - 1)
        cloche = 0.55 + 0.45 * math.sin(part * math.pi)
        onde = 0.50 + 0.50 * math.sin(seconde * (2.4 + i * 0.38) + i * 0.9)
        haut = max(2, int(haut_max * (0.12 + force * cloche * onde)))
        teinte = _teinte_barre(i, n, forme, seconde)
        gx = x + i * (large + ecart)
        halo = tuple(int(c * 0.32) for c in teinte)
        cv2.rectangle(image, (gx - 1, base - haut - 1),
                      (gx + large + 1, base), halo, -1)
        cv2.rectangle(image, (gx, base - haut), (gx + large, base), teinte, -1)


def _pochette_de(fiche: dict | None, dossier: Path, cote: int) -> np.ndarray:
    """Un carré de pochette, ou un aplat si le fichier manque.

    Manquer n'est pas une panne : une session commence parfois avant que
    toutes les images soient là, et un bac vide reste un bac.
    """
    if fiche:
        nom = fiche.get("pochette")
        if nom:
            photo = cv2.imread(str(dossier / nom))
            if photo is not None and photo.size:
                return _carre_plein(photo, cote)
    fond = np.full((max(1, cote), max(1, cote), 3), (22, 28, 32), np.uint8)
    if not fiche:
        return fond
    lettre = (str(fiche.get("auteur") or "?")[:1] or "?").upper()
    (lw, lh), _ = cv2.getTextSize(lettre, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
    cv2.putText(fond, lettre, ((cote - lw) // 2, (cote + lh) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, PLAY_GRIS, 2, cv2.LINE_AA)
    return fond


def _pose_pochette(image: np.ndarray, photo: np.ndarray, x: int, y: int,
                   cote: int, echelle: float, voile: float = 1.0) -> None:
    """Une pochette dans son bac, éventuellement reculée."""
    if cote < 4 or x < 0 or y < 0:
        return
    if y + cote > image.shape[0] or x + cote > image.shape[1]:
        return
    carre = photo
    if voile < 0.99:
        carre = (carre.astype(np.float32) * voile).clip(0, 255).astype(np.uint8)
    image[y:y + cote, x:x + cote] = carre
    cadre_encart(image, (x - 1, y - 1), (x + cote, y + cote), echelle)


def _etiquette_bac(image: np.ndarray, texte: str, x: int, y: int,
                   cote: int, echelle: float,
                   teinte: tuple[int, int, int]) -> None:
    """Le mot au-dessus d'un bac, calé sur le bord gauche de la pochette."""
    cv2.putText(image, texte, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                0.36 * echelle, teinte, 1, cv2.LINE_AA)


def _coupe_police(texte: str, large: int, echelle: float, corps: float,
                  epais: int, police: int) -> str:
    """Coupe au pixel, pas au nombre de lettres."""
    mot = str(texte or "")
    while mot and cv2.getTextSize(mot, police, corps * echelle, epais)[0][0] > large:
        mot = mot[:-1]
    return mot if mot == str(texte or "") else ((mot[:-1] + "…") if mot else "")


def _eclate(image: np.ndarray, texte: str, x: int, y: int, echelle: float,
            corps: float, teinte: tuple[int, int, int], epais: int) -> None:
    """Le titre en aberration : cyan à gauche, ambre à droite, blanc dessus.

    C'est un flux, pas une page. Un mot plat disparaît. Un mot qui se déchire
    un peu, on le lit. Le rouge reste à LIVE : ici ce sont les deux autres
    couleurs du meuble.
    """
    decal = max(1, int(round(2 * echelle)))
    corps_px = corps * echelle
    cv2.putText(image, texte, (x - decal, y), PLAY_POLICE, corps_px,
                tuple(int(c * 0.70) for c in CYAN), epais, cv2.LINE_AA)
    cv2.putText(image, texte, (x + decal, y), PLAY_POLICE, corps_px,
                tuple(int(c * 0.55) for c in AMBRE), epais, cv2.LINE_AA)
    cv2.putText(image, texte, (x, y), PLAY_POLICE, corps_px, teinte, epais,
                cv2.LINE_AA)


def _coins_bac(image: np.ndarray, x: int, y: int, cote: int, echelle: float,
               teinte: tuple[int, int, int]) -> None:
    """Quatre coins, comme un viseur posé sur la pochette qui joue."""
    bras = max(4, int(11 * echelle))
    trait = max(1, int(round(echelle)))
    coins = (
        ((x, y), (x + bras, y), (x, y + bras)),
        ((x + cote, y), (x + cote - bras, y), (x + cote, y + bras)),
        ((x, y + cote), (x + bras, y + cote), (x, y + cote - bras)),
        ((x + cote, y + cote), (x + cote - bras, y + cote),
         (x + cote, y + cote - bras)),
    )
    for coin, a, b in coins:
        cv2.line(image, coin, a, teinte, trait, cv2.LINE_AA)
        cv2.line(image, coin, b, teinte, trait, cv2.LINE_AA)


def _source_de(fiche: dict) -> str:
    if fiche.get("source"):
        return str(fiche["source"])
    url = str(fiche.get("url") or "").lower()
    if "dogmazic" in url:
        return "Dogmazic"
    if "archive.org" in url:
        return "Internet Archive"
    return ""


def _ligne_infos(fiche: dict | None, reste: float | None = None) -> str:
    """Ce qu'un lecteur dit en plus de l'artiste et du titre."""
    if not fiche:
        return ""
    bouts: list[str] = []
    if reste is not None and reste >= 0:
        bouts.append(f"{_mmss(reste)} left")
    elif fiche.get("duree"):
        bouts.append(_mmss(float(fiche["duree"])))
    album = str(fiche.get("album") or "").strip()
    if album:
        bouts.append(album)
    source = _source_de(fiche)
    if source:
        bouts.append(source)
    tempo = fiche.get("tempo")
    if tempo:
        try:
            bouts.append(f"{int(round(float(tempo)))} bpm")
        except (TypeError, ValueError):
            pass
    if reste is None:
        licence = str(fiche.get("licence") or "").strip()
        if licence:
            bouts.append(licence)
    return "  ·  ".join(bouts)


def _trame(image: np.ndarray, x: int, y: int, large: int, haut: int,
           echelle: float) -> None:
    """Quelques lignes de balayage, dans la colonne, nulle part ailleurs."""
    if large < 8 or haut < 8:
        return
    pas = max(3, int(5 * echelle))
    teinte = tuple(int(c * 0.18) for c in CYAN)
    for yy in range(y, y + haut, pas):
        cv2.line(image, (x, yy), (x + large, yy), teinte, 1, cv2.LINE_AA)


def _credit_piste(image: np.ndarray, fiche: dict | None, x: int, y: int,
                  large: int, echelle: float,
                  teinte_auteur: tuple[int, int, int],
                  teinte_titre: tuple[int, int, int],
                  corps_auteur: float, corps_titre: float,
                  infos: str = "", eclate: bool = False) -> None:
    """L'artiste, le titre, puis ce qu'on sait encore.

    Collés en une ligne, les deux se perdaient. Séparés, l'artiste est une
    signature et le titre est ce qu'on écoute. Le précédent et le suivant
    ont droit au même geste, plus petit. En cours, le titre se déchire :
    cyan et ambre derrière le blanc.
    """
    if not fiche or large < 8:
        return
    auteur = _coupe_police(str(fiche.get("auteur") or ""), large, echelle,
                           corps_auteur, 1, cv2.FONT_HERSHEY_SIMPLEX)
    titre = _coupe_police(str(fiche.get("titre") or ""), large, echelle,
                          corps_titre, 2, PLAY_POLICE)
    pas = max(16, int(26 * echelle * (corps_titre / 0.50)))
    cv2.putText(image, auteur, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                corps_auteur * echelle, teinte_auteur, 1, cv2.LINE_AA)
    if eclate:
        _eclate(image, titre, x, y + pas, echelle, corps_titre, teinte_titre, 2)
        (tw, _), _ = cv2.getTextSize(titre, PLAY_POLICE, corps_titre * echelle, 2)
        trait = min(large, max(int(28 * echelle), tw))
        yy = y + pas + max(3, int(5 * echelle))
        cv2.line(image, (x, yy), (x + trait, yy),
                 tuple(int(c * 0.55) for c in CYAN), 1, cv2.LINE_AA)
    else:
        cv2.putText(image, titre, (x, y + pas), PLAY_POLICE,
                    corps_titre * echelle, teinte_titre, 2, cv2.LINE_AA)
    if infos:
        meta = _coupe_police(infos, large, echelle, 0.34, 1,
                             cv2.FONT_HERSHEY_SIMPLEX)
        sous = pas + max(16, int(20 * echelle))
        cv2.putText(image, meta, (x, y + sous),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34 * echelle, PLAY_GRIS, 1,
                    cv2.LINE_AA)


def pose_bloc_musique(image: np.ndarray, programme: dict, dossier: Path,
                      energie: float = 0.0, seconde: float = 0.0,
                      forme: str = "") -> None:
    """La console : précédent, en cours, à suivre, sur toute la largeur.

    Ce n'est plus un pavé de texte dans le coin. Un lecteur montre trois
    choses — ce qui vient de passer, ce qui joue, ce qui vient — et il les
    montre par l'image, pas par une file de lignes. Sans la pochette du
    suivant on ne sait pas ce qu'on attend ; sans celle du précédent on
    ne sait pas d'où on vient.

    CC-BY demande l'auteur, l'œuvre, la licence et une source qu'on puisse
    taper. Le domaine seul : sur un flux rien ne se clique, et personne ne
    recopie une chaîne de requête.

    Le numéro de release est ici, pas seulement six secondes au redémarrage :
    une console qui ne dit pas quelle version la tient ment sur ce qu'on
    regarde.
    """
    en_cours = programme.get("en_cours")
    if en_cours is None:
        return
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    marge = int(PLAY_MARGE * echelle)
    maintenant = int(PLAY_MAINTENANT * echelle)
    voisine = int(PLAY_VOISINE * echelle)
    tete = int(20 * echelle)
    duree = float(programme.get("duree") or 0.0)
    ecoule = min(float(programme.get("ecoule") or 0.0), duree)
    suite = list(programme.get("suite") or [])[:2]
    avant = programme.get("avant")

    licence = str(en_cours["licence"])
    domaine = str(en_cours["url"]).split("//")[-1].split("/")[0]
    horloge = f"{_mmss(ecoule)} / {_mmss(duree)}" if duree > 0 else ""
    reste = max(0.0, duree - ecoule) if duree > 0 else None

    extra = int(22 * echelle)
    bloc_h = tete + maintenant + extra + 2 * marge
    bas = hauteur - int(AGENDA_H * echelle)
    haut = bas - bloc_h
    fond_encart(image, (0, haut), (largeur - 1, bas - 1), echelle)

    y_mot = haut + marge + tete - int(6 * echelle)
    y_now = haut + marge + tete
    y_vois = y_now + (maintenant - voisine) // 2
    credit_w = int(200 * echelle)

    x = marge
    _etiquette_bac(image, "UP PREVIOUS", x, y_mot, voisine, echelle,
                   GRIS_ENCART)
    _pose_pochette(image, _pochette_de(avant, dossier, voisine),
                   x, y_vois, voisine, echelle, PLAY_VOILE)
    if avant:
        _credit_piste(image, avant, x + voisine + int(8 * echelle),
                      y_vois + int(16 * echelle), credit_w, echelle,
                      GRIS_ENCART, BLANC, 0.42, 0.52,
                      infos=_ligne_infos(avant))
    x += voisine + credit_w + int(16 * echelle)

    _pose_pochette(image, _pochette_de(en_cours, dossier, maintenant),
                   x, y_now, maintenant, echelle, 1.0)
    _coins_bac(image, x - 1, y_now - 1, maintenant + 2, echelle, CYAN)
    x += maintenant + int(16 * echelle)

    n_suite = len(suite)
    large_suite = (n_suite * (voisine + int(8 * echelle) + credit_w)
                   + max(0, n_suite - 1) * marge) if n_suite else 0
    x_suite = largeur - marge - large_suite
    colonne = max(int(180 * echelle), x_suite - x - marge)

    _trame(image, x, y_now, colonne, maintenant, echelle)
    cv2.putText(image, "NOW PLAYING", (x, y_mot),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40 * echelle, VERT, 1, cv2.LINE_AA)
    trait = max(int(40 * echelle),
                int(colonne * (0.28 + 0.55 * min(1.0, energie * 6.0))))
    cv2.line(image, (x, y_mot + int(5 * echelle)),
             (x + min(colonne, trait), y_mot + int(5 * echelle)),
             tuple(int(c * 0.70) for c in CYAN), max(1, int(round(echelle))),
             cv2.LINE_AA)
    marque = f"v{__version__}"
    (nw, _), _ = cv2.getTextSize("NOW PLAYING", cv2.FONT_HERSHEY_SIMPLEX,
                                 0.40 * echelle, 1)
    pose_pastille(image, marque, x + nw + int(10 * echelle), y_mot, echelle)

    _credit_piste(image, en_cours, x, y_now + int(22 * echelle), colonne,
                  echelle, CYAN, BLANC, 0.50, 0.76,
                  infos=_ligne_infos(en_cours, reste), eclate=True)
    eq_base = y_now + maintenant - int(8 * echelle)
    eq_l = min(int(PLAY_EQ_L * echelle), colonne)
    _vumetre(image, x, eq_base, eq_l, echelle, energie, seconde, forme=forme)
    if duree > 0:
        rail_y = min(eq_base + int(10 * echelle), bas - marge - int(16 * echelle))
        epais = max(2, int(PLAY_JAUGE_H * echelle))
        rail = max(int(80 * echelle), colonne - int(110 * echelle))
        pose_jauge(image, x, rail_y, rail, ecoule / duree, BLANC, echelle)
        fait = int(rail * max(0.0, min(1.0, ecoule / duree)))
        cv2.circle(image, (x + fait, rail_y + epais // 2),
                   max(2, int(4 * echelle)), BLANC, -1, cv2.LINE_AA)
        cv2.putText(image, horloge, (x + rail + marge,
                                     rail_y + epais // 2 + int(5 * echelle)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46 * echelle, PLAY_GRIS, 1,
                    cv2.LINE_AA)
    suite_x = pose_pastille(image, licence, x, bas - marge - int(2 * echelle),
                            echelle)
    cv2.putText(image, domaine, (suite_x + int(8 * echelle),
                                 bas - marge - int(2 * echelle)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40 * echelle, GRIS_ENCART, 1,
                cv2.LINE_AA)

    if not suite:
        return
    _etiquette_bac(image, "UP NEXT", x_suite, y_mot, voisine, echelle, AMBRE)
    for i, fiche in enumerate(suite):
        px = x_suite + i * (voisine + int(8 * echelle) + credit_w + marge)
        _pose_pochette(image, _pochette_de(fiche, dossier, voisine),
                       px, y_vois, voisine, echelle,
                       0.72 if i == 0 else 0.45)
        _credit_piste(image, fiche, px + voisine + int(8 * echelle),
                      y_vois + int(16 * echelle), credit_w, echelle,
                      AMBRE if i == 0 else GRIS_ENCART,
                      BLANC if i == 0 else PLAY_GRIS,
                      0.42, 0.52, infos=_ligne_infos(fiche))


# Le silence qu'il faut avant d'aller chercher dans les archives, et le temps
# qu'une ancienne prise reste à l'écran. Deux minutes sans rien, sur cette
# route, c'est banal la nuit et rare à midi : la rediffusion vient donc d'elle-
# même quand il n'y a rien, et se tait quand il se passe quelque chose.
CREUX_S = 300.0
REDIFF_TENUE_S = 10.0
# La part de la largeur que prend le médaillon. Essayé à quatre-vingts pour
# cent : la rediffusion mangeait l'écran et on ne voyait plus le direct, ce qui
# est le contraire du but — le direct doit rester lisible pendant qu'on montre
# l'archive, sinon autant diffuser un diaporama.
# Un tiers de la largeur, et non quarante-deux pour cent. Ce qu'il y a dans la
# carte est une image en gros blocs gris — c'est la règle de vie privée et elle
# est bien fondée, vingt centimètres par bloc, on voit une voiture et pas qui
# conduit. Mais un rectangle gris illisible occupant la moitié de l'écran ne
# dit pas plus qu'un petit, et il a l'air d'un écran censuré. Plus petit, il
# redevient ce qu'il est : une carte d'archive posée devant la montagne, qu'on
# continue de voir.
REDIFF_PART = 0.32
REDIFF_ZOOM_MAX = 3
# Et jamais deux coup sur coup : « pas en abuser » veut dire que la rediffusion
# est une respiration, pas un programme. Dix minutes de direct entre deux.
REDIFF_PAUSE_S = 600.0
# Les noms qui ne sont pas des noms : ce que la veille écrit quand elle n'a
# justement rien reconnu. Les rediffuser serait rediffuser son embarras.
NON_NOMS = ("Mouvement", "Rien", "Vu trop", "Tache", "Toujours", "Au bord",
            "Devant", "Brouillard", "Brume", "Décor", "Lueur", "Immobile",
            "Trop ", "Sans ", "Hors ", "Aucun",
            # En entier, parce que « Véhicule » tout court est une vraie
            # lecture : de nuit la veille ne distingue plus la voiture du
            # camion et publie le mot générique. Le préfixe les emporterait
            # tous les deux.
            "Véhicule non nommé")
# Jamais de feu en rediffusion, à aucune condition.
#
# Tout le reste de ce fichier peut se tromper sans conséquence : un camion pris
# pour une voiture fait sourire. Une image de départ de feu remontrée au milieu
# d'un direct fait croire que la montagne brûle en ce moment. Le bandeau dit
# bien « replay », mais personne ne lit un bandeau quand il voit de la fumée —
# et ce serait notre faute, pas la leur.
#
# C'est aussi le seul endroit où l'on efface volontairement du travail de la
# veille : c'est que le flux est un spectacle et que la veille est une alerte,
# et qu'une alerte ne se rejoue pas.
JAMAIS_REDIFF = ("Incendie", "Départ de feu", "Feu", "Fumée", "Panache")

# Ce qui mérite d'être fêté : un sujet nommé, qui bouge, et qui est bien là.
# L'historique est surtout fait d'« avortés », ce que la veille a d'abord pris
# pour quelque chose avant de le ranger au décor — elle en a plus que de vraies
# prises. En fêter un dirait exactement l'inverse de la vérité, et c'est ce
# qu'elle a fait au premier essai, avec « Décor connu ».
#
# Le feu n'y est pas non plus. Attraper un départ de feu est la raison d'être
# de tout ce programme, mais une voix de dessin animé qui lance « good catch »
# au-dessus d'une fumée qui monte pour de bon est la dernière chose à montrer
# ce jour-là.
PRISES = {"vehicle", "car", "truck", "bus", "person", "cycle", "plane",
          "aircraft", "animal"}


def archives(racine: Path, combien: int = 400) -> list[dict]:
    """Les prises anciennes qui valent d'être remontrées, photo comprise.

    Seulement celles qu'un humain a confirmées. La veille se trompe — elle a
    appelé « Piéton » le trampoline du village et « Voiture » un reflet sur la
    chaussée mouillée — et une rediffusion est la seule chose du flux qu'on
    présente comme un fait établi. Remontrer une erreur en grand, dix minutes
    durant, c'est la republier.

    Il faut aussi un vrai nom et une vignette encore sur le disque : une
    rediffusion sans image est une ligne de texte, et une rediffusion de
    « Mouvement sur la route » n'apprend rien à personne.
    """
    try:
        brut = json.loads((racine / "data" / "events.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    brut = brut if isinstance(brut, list) else brut.get("events", [])
    gardees = []
    for fiche in brut:
        if fiche.get("review") != "accepted":
            continue
        nom = str(fiche.get("label") or "")
        if not nom or nom.startswith(NON_NOMS) or nom.startswith(JAMAIS_REDIFF):
            continue
        # La découpe d'abord, la vue d'ensemble seulement à défaut. Elle est
        # nette sur le disque, et c'est voulu : le site la montre telle quelle
        # pour qu'on puisse juger dessus. Le flou est posé plus bas, à l'instant
        # d'afficher — un passage rejoué en boucle devant des gens qui ne l'ont
        # pas demandé n'est pas une image qu'on va chercher pour l'examiner.
        nom_photo = str(fiche.get("closeup") or fiche.get("thumb") or "")
        photo = racine / nom_photo
        if not nom_photo or not photo.is_file():
            continue
        gardees.append({"photo": photo, "label": nom, "t": str(fiche.get("t") or ""),
                        "contexte": str((fiche.get("detail") or {}).get("context") or "")})
        if len(gardees) >= combien:
            break
    return gardees


# Ce qu'on appelle une prise récente, et la demi-vie à l'intérieur de ce délai.
#
# Le tirage était uniforme et la réserve n'était relue qu'une fois vidée :
# quatre-vingt-cinq fiches à une toutes les dix minutes, soit quatorze heures
# avant qu'une voiture attrapée à midi ait sa chance. Le flux remontrait donc
# surtout la semaine précédente, en se donnant l'air de n'avoir rien vu depuis.
#
# Un jour, en deux étages plutôt qu'en pente douce. Une simple pondération
# laissait encore une rediffusion sur quatre tomber sur la semaine d'avant, ce
# qui est beaucoup quand il n'en passe qu'une toutes les dix minutes : on peut
# regarder une heure et ne voir que du vieux. Tant qu'il reste quelque chose
# des dernières vingt-quatre heures, c'est cela qu'on remontre ; l'archive
# ancienne attend que le récent soit épuisé, ce qui arrive les nuits creuses,
# et elle sert alors exactement à ce pour quoi on la garde.
#
# Vingt-quatre heures glissantes et non « aujourd'hui » : un jour de calendrier
# se vide à minuit, et le flux n'aurait plus rien à montrer de la nuit jusqu'au
# premier passage du matin. La demi-vie de six heures fait le reste — à
# l'intérieur de la journée, ce qui vient d'arriver passe avant ce matin.
#
# Rien là-dedans ne tient à cette caméra : c'est une façon de dire que la
# dernière chose qui s'est passée est celle qui intéresse.
REDIFF_FRAICHEUR_H = 24.0
REDIFF_DEMI_VIE_H = 6.0


def _age_heures(iso: str, maintenant: float) -> float:
    """Depuis combien d'heures, ou zéro si la date ne se lit pas.

    Zéro et non l'infini : une fiche sans date lisible est traitée comme
    récente. Mieux vaut remontrer une fois de trop quelque chose qu'un humain a
    confirmé que de l'enterrer pour un défaut de format.
    """
    try:
        quand = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, (maintenant - quand) / 3600.0)


def marque_historique(racine: Path) -> float:
    """La date du fichier d'historique, pour savoir qu'il a bougé.

    Sans elle, la réserve n'était relue qu'une fois vidée : une prise confirmée
    à midi attendait le lendemain pour avoir le droit de repasser.
    """
    try:
        return (racine / "data" / "events.json").stat().st_mtime
    except OSError:
        return 0.0


def ordre_de_rediffusion(gardees: list[dict], tirage: random.Random,
                         maintenant: float | None = None) -> list[dict]:
    """La réserve rangée pour y puiser par la fin, la plus récente d'abord.

    Deux étages : ce qui date de moins de deux jours passe avant tout le reste,
    et à l'intérieur de chaque étage l'ordre est un hasard penché vers le
    récent. L'archive ancienne n'est pas jetée, elle attend son tour — les
    nuits où rien ne passe, elle est tout ce qu'on a.
    """
    maintenant = _maintenant() if maintenant is None else maintenant
    etages: dict[bool, list] = {True: [], False: []}
    for fiche in gardees:
        age = _age_heures(str(fiche.get("t") or ""), maintenant)
        # Le tirage pondéré sans remise, en logarithmes.
        #
        # La forme directe est « hasard puissance un sur le poids ». Écrite
        # ainsi elle ne marche pas : une fiche d'il y a une semaine pèse un
        # seize-millionième, l'exposant explose, et toutes les clés tombent à
        # zéro par sous-dépassement. Elles deviennent alors égales, le tri est
        # stable, et l'archive repasse éternellement dans le même ordre —
        # c'est-à-dire que le hasard disparaît exactement là où on en a le plus
        # besoin. Le logarithme garde la même loi sans jamais déborder.
        poids = 2.0 ** (-age / REDIFF_DEMI_VIE_H)
        cle = math.log(max(tirage.random(), 1e-12)) / max(poids, 1e-12)
        etages[age <= REDIFF_FRAICHEUR_H].append((cle, fiche))
    rangees = []
    for frais in (False, True):
        etages[frais].sort(key=lambda couple: couple[0])
        rangees += [fiche for _, fiche in etages[frais]]
    return rangees


# L'heure de la montagne, pas celle de Greenwich. Les horodatages sont écrits
# en UTC parce qu'une veille qui change d'heure deux fois par an se trompe deux
# fois par an ; mais personne ne regarde une webcam du Ventoux en UTC.
PARIS = ZoneInfo("Europe/Paris")

# Une pensée par jour, à 7 h 15, heure de Paris. Le nom reste écrit
# dix-sept secondes. Un redémarrage dans la fenêtre ne la redit pas :
# le fichier du jour s'en souvient.
PENSEE_HEURE_S = 7 * 3600 + 15 * 60
PENSEE_APRES_S = 17.0
PENSEE_GRACE_S = 240


def _pensee_lue(racine: Path) -> tuple[date | None, int, int, float]:
    """Date, rang, étape, instant du feu.

    Une étape 2 ferme la journée : la pensée de 7 h 15 a été dite, ou
    l'heure est passée. L'ancien fichier à trois champs se lit encore.
    """
    try:
        morceaux = (racine / "data" / "voix" / "pensee.jour").read_text().split()
        jour = date.fromisoformat(morceaux[0])
        if len(morceaux) >= 4:
            return jour, int(morceaux[1]), int(morceaux[2]), float(morceaux[3])
        etape = int(morceaux[1])
        feu = float(morceaux[2]) if len(morceaux) > 2 else 0.0
        if etape >= 2:
            return jour, 2, 2, feu
        return jour, 0, etape, feu
    except (OSError, ValueError, IndexError):
        return None, 0, 0, 0.0


def _pensee_ecrite(racine: Path, jour: date, rang: int, etape: int,
                   feu: float) -> None:
    try:
        (racine / "data" / "voix" / "pensee.jour").write_text(
            f"{jour.isoformat()} {rang} {etape} {feu:.3f}\n", encoding="utf-8")
    except OSError:
        pass
# L'heure de la machine, de l'autre côté. Même format, même corps : les deux
# encarts se répondent, neuf heures d'écart entre les deux.
LOS_ANGELES = ZoneInfo("America/Los_Angeles")

MOIS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _quand_dit(iso: str) -> str:
    """« 25 Sep 2026 · 08:20 » : lisible dans les deux langues sans effort.

    Sans nom de fuseau. L'horloge du coin en porte un, en haut à droite, et
    elle dit l'heure qu'il est maintenant ; celle-ci date une image d'hier. Les
    deux côte à côte se lisaient comme deux heures du même instant, et le
    « PARIS » répété appuyait la confusion au lieu de la lever.
    """
    try:
        moment = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return iso
    ici = moment.astimezone(PARIS)
    return f"{ici.day} {MOIS[ici.month - 1]} {ici.year} · {ici:%H:%M}"


def pose_rediffusion(image: np.ndarray, fiche: dict,
                     vue: tuple[int, int, int, int] | None = None) -> bool:
    """Une ancienne prise en grand, au milieu, datée.

    Datée surtout : sans la date, un spectateur croit voir la route en ce
    moment, et le flux se met à mentir — ce qui est la seule chose qu'il n'a
    pas le droit de faire. D'où la date au-dessus de l'image et non dessous,
    et le mot « replay » avant tout le reste.
    """
    vignette = cv2.imread(str(fiche["photo"]))
    if vignette is None:
        return False
    # Pixellisée ici et seulement ici. Le fichier reste net sur le disque et sur
    # le site, où l'on va chercher une image pour juger dessus ; ce qui change,
    # c'est qu'à l'antenne le même passage revient devant des gens qui ne l'ont
    # pas demandé, en boucle, sans rien à en faire. « Je trouve ça creepy » — et
    # c'est vrai. La chose reste lisible comme chose, personne n'y est
    # reconnaissable, et c'est tout ce que la rediffusion a besoin de montrer.
    vignette = floute(vignette)
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    # Jamais agrandie plus de trois fois. Les archives sont gardées petites —
    # un piéton tient dans cent pixels de large — et les étirer jusqu'à
    # quarante-deux pour cent de l'écran en faisait douze carrés gris hauts
    # comme la montagne. Ce n'était plus une image, c'était un mur, et c'est ce
    # mur qui rendait la rediffusion angoissante : on ne reconnaissait même
    # plus une scène, seulement un visage censuré qui n'en était pas un.
    #
    # Le commentaire d'en dessous disait déjà qu'on ne prétend pas retrouver ce
    # qui n'a pas été gardé. Le plafond est la même phrase, appliquée.
    cible_l = min(int(largeur * REDIFF_PART), vignette.shape[1] * REDIFF_ZOOM_MAX)
    cible_h = int(vignette.shape[0] * cible_l / vignette.shape[1])
    # Les archives sont enregistrées en petit ; agrandies autant, elles sont
    # douces. « cubic » vaut mieux que « linear » pour ce qu'on en fait, et on
    # ne prétend pas retrouver ce qui n'a pas été gardé.
    vignette = cv2.resize(vignette, (cible_l, cible_h), interpolation=cv2.INTER_CUBIC)
    pas = int(38 * echelle)
    marge = int(18 * echelle)
    # La légende sous l'image et non au-dessus : le haut de l'écran appartient
    # au ruban et à la météo, et deux textes superposés ne se lisent pas.
    pied = pas * 2
    # Centrée sur la fenêtre caméra et non sur l'image entière. Centrée sur
    # l'image, la carte descendait dans le crédit musical et mordait le
    # bandeau du bas : le bas de l'écran est occupé, et le milieu de l'écran
    # n'est pas le milieu de ce qu'on regarde. La fenêtre caméra est la scène,
    # et une rediffusion remplace le direct — elle se met donc à sa place.
    _, cime, _, haute_vue = vue or (0, 0, largeur, hauteur)
    carte_h = min(haute_vue, cible_h + pied + marge)
    cible_h = min(cible_h, carte_h - pied - marge)
    vignette = vignette[:cible_h]
    haut = cime + (haute_vue - carte_h) // 2
    # Au milieu. Elle était à droite pour laisser voir le rond-point et la
    # route, qui occupent la gauche de l'image — un bon raisonnement pour une
    # vignette posée par-dessus le direct. Mais elle n'est pas posée par-
    # dessus : pendant une rediffusion il n'y a rien d'autre à regarder, le
    # direct est caché derrière de toute façon, et une image collée contre le
    # bord droit d'un écran par ailleurs vide a juste l'air mal posée.
    gauche = (largeur - cible_l) // 2
    # Assombri, pas éteint. À un quart, le direct disparaissait complètement
    # derrière un rectangle noir et l'écran avait l'air de tomber en panne au
    # moment où une image de surveillance apparaissait dessus. À 0,45 la
    # montagne se devine encore autour de la vignette : on comprend que le flux
    # est toujours là et qu'il montre simplement autre chose.
    x0 = max(0, gauche - marge)
    x1 = min(largeur, gauche + cible_l + marge) - 1
    fond_encart(image, (x0, haut), (x1, haut + carte_h - 1), echelle)
    image[haut:haut + cible_h, gauche:gauche + cible_l] = vignette
    bas = haut + cible_h + marge
    # En ambre et non en rouge. Le rouge est la couleur de l'alerte, et il ne
    # sert ailleurs dans ce flux qu'au point qui bat à côté de l'heure. Posé en
    # grand sous une image floue de surveillance, il disait « incident » là où
    # il n'y a qu'une archive — c'est exactement ce qui rendait la chose
    # angoissante. L'ambre est déjà la couleur des encarts.
    cv2.putText(image, "REPLAY · REDIFFUSION", (gauche, bas + pas - int(12 * echelle)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.72 * echelle, AMBRE, 2, cv2.LINE_AA)
    cv2.putText(image, f"{_quand_dit(fiche['t'])}  —  {fiche['label']}",
                (gauche, bas + pas * 2 - int(14 * echelle)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.72 * echelle, BLANC, 2, cv2.LINE_AA)
    return True


# Le bandeau du bas, qui tourne. La date, le titre, la commune.
# Même vitesse que le ruban du haut : quatre pixels et demi laissaient une
# phrase six minutes dans le cadre, et un agenda qu'on ne voit pas défiler
# n'est plus un fil d'actualité.
AGENDA_H = 42
AGENDA_VITESSE = VITESSE_RUBAN
AGENDA_ECART = 70         # le blanc entre deux tours de bandeau
AGENDA_RELIT_S = 600.0    # on relit le fichier toutes les dix minutes


def pose_agenda(image: np.ndarray, rendez_vous: list, credit: str,
                seconde: float) -> None:
    """Ce qui se passe autour, en une ligne qui défile comme un fil d'actualité."""
    if not rendez_vous:
        return
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    pas = int(AGENDA_H * echelle)
    taille = 0.56 * echelle
    base = hauteur - int(13 * echelle)
    fond_bandeau(image, hauteur - pas, hauteur, echelle, inverse=True)

    morceaux: list[tuple[str, tuple[int, int, int]]] = []
    if credit:
        morceaux.append((f"{credit}   ", AMBRE))
    for quoi in rendez_vous:
        # Trois couleurs pour trois natures : quand, quoi, où. L'œil d'un
        # spectateur qui ne lit pas tout attrape au moins la date et la
        # commune, qui sont ce qui décide si l'affaire le concerne.
        morceaux.append((f"{quoi.get('jour', '')}  ", AMBRE))
        morceaux.append((str(quoi.get("titre", "")), BLANC))
        morceaux.append((f"  {quoi.get('commune', '')}", CYAN))
        morceaux.append(("   ·   ", (110, 110, 110)))
    larges = [cv2.getTextSize(m, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0]
              for m, _ in morceaux]
    tour = sum(larges) + int(AGENDA_ECART * echelle)
    if tour <= 0:
        return
    decalage = int(seconde * AGENDA_VITESSE * echelle) % tour
    for depart in (-decalage, -decalage + tour):
        x = depart
        for (mot, teinte), large in zip(morceaux, larges):
            if -large < x < largeur:
                cv2.putText(image, mot, (x, base), cv2.FONT_HERSHEY_SIMPLEX,
                            taille, teinte, 2, cv2.LINE_AA)
            x += large


# Le bandeau du bas est parti. C'était la ligne des chaînes d'information,
# filet rouge compris, et elle répétait sept phrases qui disaient toutes la
# même chose : « regardez, il y a une machine qui regarde ». Personne n'a
# besoin qu'on le lui dise sept fois ; le rectangle rouge autour d'une voiture
# le dit mieux en une fois. Le bas de l'image sert maintenant à quelque chose
# qui change vraiment — les résultats du championnat d'à côté.


def a_vol_d_oiseau(un: tuple[float, float], deux: tuple[float, float]) -> float:
    """Les kilomètres entre deux points de la Terre, par le grand cercle."""
    rayon = 6371.0088
    phi1, phi2 = math.radians(un[0]), math.radians(deux[0])
    dphi = phi2 - phi1
    dlam = math.radians(deux[1] - un[1])
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return 2 * rayon * math.asin(math.sqrt(min(1.0, a)))


FIL_MARGE = 10           # à quelle distance du bord descendent les brins
FIL_SOUS_VUE = 28        # de combien le fil passe sous la fenêtre caméra
FIL_POULIE = 7           # le rayon d'une poulie
FIL_GRIS = (120, 118, 112)
FIL_CREUX = 6            # le ventre du brin tendu, au repos


def pose_fil(image: np.ndarray, vue: tuple | None = None,
             remue: float = 0.0) -> None:
    """Un fil qui relie les deux encarts.

    Les deux encarts disaient déjà la même chose chacun de son côté — ici la
    machine, là ce qu'elle regarde — mais rien ne les reliait, et deux choses
    qui se répondent sans se toucher ne se répondent qu'à moitié. Le fil part
    du coin inférieur de chacun, descend le long du bord dans la bande noire,
    passe sur une poulie et traverse sous la fenêtre caméra.

    Il ne mord jamais sur l'image. C'est pour ça qu'il longe le bord au lieu
    de tendre tout droit d'un encart à l'autre : une corde tendue entre les
    deux coins traverserait la montagne en diagonale.

    Et il travaille. Quand les encarts flottent ils flottent en opposition,
    comme deux charges d'un même câble : celui qui descend fait monter
    l'autre, et le fil s'incline d'autant. C'est le seul endroit où le
    balancement se lit comme une mécanique plutôt que comme un défaut.

    Les kilomètres ne s'écrivent plus dessus : on en fera un effet, pas une
    légende posée en permanence.
    """
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    gauche, cime, large_vue, haute_vue = vue or (0, 0, largeur, hauteur)
    y = cime + haute_vue + int(FIL_SOUS_VUE * echelle)
    if y >= hauteur:
        return
    bord = int(FIL_MARGE * echelle)
    trait = max(1, int(1.5 * echelle))
    rayon = max(3, int(FIL_POULIE * echelle))
    haut_g = int(ENCART_BAS * echelle) + int(remue)
    haut_d = int(ENCART_BAS * echelle) - int(remue)
    bas_g, bas_d = y + int(remue), y - int(remue)

    def brin(points: list[tuple[int, int]]) -> None:
        cv2.polylines(image, [np.int32(points)], False, FIL_GRIS, trait,
                      cv2.LINE_AA)

    # Les deux descentes et les deux poulies.
    #
    # Le fil est tangent à la poulie et ne va pas à son centre : il descend du
    # côté extérieur, fait un quart de tour sur la gorge et repart à
    # l'horizontale par-dessous. Rejoignant le moyeu, les trois brins se
    # rencontraient en un point et la poulie n'était plus qu'une rondelle
    # posée sur un angle droit — ce qui se voyait surtout en bas à droite, où
    # la traversée arrive de loin et bien à plat.
    gorge_g, gorge_d = bord - rayon, largeur - 1 - bord + rayon
    moyeu_g, moyeu_d = bas_g - rayon, bas_d - rayon
    brin([(gorge_g, haut_g), (gorge_g, moyeu_g)])
    brin([(gorge_d, haut_d), (gorge_d, moyeu_d)])
    for cx, cy, depart in ((bord, moyeu_g, 180.0), (largeur - 1 - bord, moyeu_d, 270.0)):
        cv2.circle(image, (cx, cy), rayon, FIL_GRIS, trait, cv2.LINE_AA)
        cv2.circle(image, (cx, cy), max(1, rayon // 3), FIL_GRIS, -1, cv2.LINE_AA)
        # Le quart de tour du fil sur la gorge : à gauche de neuf heures à six
        # heures, à droite de six heures à trois heures.
        cv2.ellipse(image, (cx, cy), (rayon, rayon), 0.0, depart, depart + 90.0,
                    FIL_GRIS, trait, cv2.LINE_AA)
    # La traversée, avec le ventre que prend tout fil tendu à l'horizontale.
    # Elle va d'une poulie à l'autre et son dernier point tombe exactement sur
    # la seconde : calculée par pas réguliers, elle s'arrêtait jusqu'à un pas
    # avant le bord droit et laissait un trou dans l'angle.
    creux = FIL_CREUX * echelle
    combien = 48
    travee = []
    for i in range(combien + 1):
        part = i / combien
        x = bord + (largeur - 1 - 2 * bord) * part
        droit = bas_g + (bas_d - bas_g) * part
        travee.append((int(x), int(droit + creux * math.sin(math.pi * part))))
    brin(travee)


ATTRAPE_S = 1.6

# Des fractions de la pleine échelle du son, soit environ -18 dB et -21 dB.
# Une mesure du signal, pas un réglage pour cette caméra : la même valeur
# vaudra sur la suivante, avec la même bibliothèque de musique.
DANSE_SEUIL = 0.13
DANSE_ARRET = 0.09
DANSE_VOILE = 0.5
# Trois pas par seconde à pleine énergie : c'est à peu près cent quatre-vingts
# battements par minute, le haut de ce que joue la sélection.
DANSE_PAS_S = 3.0
# La taille d'un pantin, en parts de la hauteur de la vue. Une seule valeur
# pour les trois : celui du tapis est le même bonhomme que ceux du bas, parti
# faire un tour en l'air, et un troisième plus petit se lirait comme un enfant
# ou comme une erreur de perspective plutôt que comme le même personnage.
DANSE_HAUT = 0.22


# LES COULEURS CLAIRES DES PANTINS ET DE L'ÉLÉPHANT, en BGR.
#
# Toutes très pâles et toutes à peu près aussi lumineuses : ce n'est pas une
# palette de couleurs, c'est du blanc teinté. Un pantin franchement rose ou
# franchement bleu deviendrait une information — on croirait que la teinte dit
# quelque chose, et rien de ce qu'on ajoute pour le plaisir n'a le droit de
# ressembler à une mesure. Du blanc qui tire un peu vers le rose ne dit rien
# d'autre que le plaisir de ne pas toujours être blanc.
#
# Elles sont aussi ce qui reste du rose de l'éléphant, qui était seul de son
# espèce : maintenant que tout le monde est tracé de la même main, le rose
# appartient à tout le monde et à personne en particulier.
CLAIRS = (
    (245, 245, 245),   # blanc
    (228, 206, 252),   # rose
    (252, 226, 206),   # bleu pâle
    (198, 240, 252),   # jaune pâle
    (214, 248, 220),   # menthe
    (248, 218, 228),   # lavande
)
# Assez long pour qu'on ne surprenne jamais le changement : un numéro dure
# quelques secondes, celui d'après tombera dans une autre teinte sans que
# personne ait vu de transition. C'est la différence entre « ils changent de
# couleur », qui est un effet, et « ils ne sont pas toujours de la même
# couleur », qui est une respiration.
CLAIR_TENUE_S = 97.0


def un_clair(seconde: float, decalage: int = 0) -> tuple[int, int, int]:
    """La teinte claire du moment, jamais vue en train de changer."""
    return CLAIRS[(int(seconde / CLAIR_TENUE_S) + decalage) % len(CLAIRS)]


def _danseur(calque: np.ndarray, x: int, sol: int, taille: float,
             phase: float, couleur: tuple[int, int, int]) -> None:
    """Un bonhomme en tubes, volontairement décousu.

    Les membres sont posés un peu à côté des articulations plutôt que soudés
    dessus : un pantin bien assemblé a l'air d'un schéma, un pantin désarticulé
    a l'air de danser. C'est le seul endroit du flux où l'approximation est le
    but et non un défaut.
    """
    tube = max(2, int(taille * 0.045))
    corps = taille * 0.46
    hanche = (x, int(sol - corps))
    epaule = (x + int(math.sin(phase) * taille * 0.07), int(sol - corps - taille * 0.3))
    tete = int(taille * 0.09)

    # Chaque trait est doublé d'un liseré sombre : le blanc seul s'évanouit sur
    # un ciel de brouillard, et c'est le fond qu'on a la moitié du temps ici.
    ourlet = tube + max(2, tube // 2)

    def trait(a, b):
        cv2.line(calque, a, b, (0, 0, 0), ourlet, cv2.LINE_AA)
        cv2.line(calque, a, b, couleur, tube, cv2.LINE_AA)

    def membre(depuis, angle, longueur, decalage):
        bout = (int(depuis[0] + math.sin(angle) * longueur),
                int(depuis[1] + math.cos(angle) * longueur))
        trait((depuis[0] + decalage, depuis[1] + decalage), bout)
        cv2.circle(calque, bout, tube // 2 + 1, couleur, -1, cv2.LINE_AA)
        return bout

    trait(hanche, epaule)
    cv2.circle(calque, (epaule[0], epaule[1] - tete), tete, (0, 0, 0), ourlet, cv2.LINE_AA)
    cv2.circle(calque, (epaule[0], epaule[1] - tete), tete, couleur, tube, cv2.LINE_AA)
    ecart = max(1, tube)
    # L'angle se compte depuis le bas : zéro descend, π monte. Les bras partent
    # donc vers le haut et les jambes vers le sol, sans quoi le pantin marche
    # sur les mains — ce qu'il a fait au premier essai.
    coude_g = membre(epaule, 2.2 + math.sin(phase) * 0.8, taille * 0.22, -ecart)
    membre(coude_g, 2.4 + math.sin(phase * 2 + 1) * 1.1, taille * 0.2, ecart)
    coude_d = membre(epaule, -2.2 + math.sin(phase + 2) * 0.8, taille * 0.22, ecart)
    membre(coude_d, -2.4 + math.sin(phase * 2) * 1.1, taille * 0.2, -ecart)
    genou_g = membre(hanche, 0.35 + math.sin(phase + 1) * 0.45, taille * 0.26, ecart)
    membre(genou_g, 0.2 + math.sin(phase * 2 + 2) * 0.5, taille * 0.24, -ecart)
    genou_d = membre(hanche, -0.35 + math.sin(phase + 3) * 0.45, taille * 0.26, -ecart)
    membre(genou_d, -0.2 + math.sin(phase * 2 + 4) * 0.5, taille * 0.24, ecart)


# La promenade des pantins : toutes les trois minutes ils glissent vers la
# bande noire, y dansent cinq secondes et reviennent.
#
# Trois minutes parce qu'une surprise qu'on attend n'en est plus une : à une
# minute on comprend le mécanisme en deux passages et on cesse de regarder, à
# dix on ne la voit jamais. Cinq secondes dehors parce que c'est le temps de
# s'apercevoir qu'ils y sont allés ; trois pour le trajet, assez pour que ça
# ressemble à une glissade et pas à un saut.
PROMENADE_PERIODE_S = 180.0
PROMENADE_GLISSE_S = 3.0
PROMENADE_TENUE_S = 5.0
# Ils se rejoignent parfois au milieu de la fenêtre. Pas pendant la
# promenade — deux idées à la fois, on n'en lit aucune. Un décalage pour
# que les deux cycles ne tombent pas ensemble, et une période qui n'est
# pas un multiple de l'autre.
RENDEZ_PERIODE_S = 419.0
RENDEZ_DECALAGE_S = 90.0
RENDEZ_GLISSE_S = 4.0
RENDEZ_TENUE_S = 6.0


def promenade(seconde: float) -> float:
    """Où en est la sortie : zéro à sa place, un au milieu de la bande.

    Une fonction du temps et rien d'autre, donc les deux pantins partent
    ensemble et reviennent exactement d'où ils sont partis. Un tirage au sort
    aurait fait deux promeneurs indépendants, ce qui se lirait comme un défaut
    plutôt que comme une idée.
    """
    cycle = 2 * PROMENADE_GLISSE_S + PROMENADE_TENUE_S
    phase = seconde % PROMENADE_PERIODE_S
    if phase >= cycle:
        return 0.0
    if phase < PROMENADE_GLISSE_S:
        avance = phase / PROMENADE_GLISSE_S
    elif phase < PROMENADE_GLISSE_S + PROMENADE_TENUE_S:
        return 1.0
    else:
        avance = (cycle - phase) / PROMENADE_GLISSE_S
    # Départ et arrivée en douceur : à vitesse constante, le pantin s'arrête
    # net contre le bord et repart net, ce qui se voit comme une saccade.
    return avance * avance * (3 - 2 * avance)


def rendez_vous(seconde: float) -> float:
    """Où en est la rencontre : zéro chacun chez soi, un au milieu de la vue.

    Ils ne sortent pas : ils se rejoignent dans la fenêtre, devant la
    montagne, puis rentrent. Un Short n'a pas de bande, et la rencontre
    n'y a pas non plus sa place : ils restent chez eux.
    """
    cycle = 2 * RENDEZ_GLISSE_S + RENDEZ_TENUE_S
    phase = (seconde - RENDEZ_DECALAGE_S) % RENDEZ_PERIODE_S
    if phase < 0:
        phase += RENDEZ_PERIODE_S
    if phase >= cycle:
        return 0.0
    if phase < RENDEZ_GLISSE_S:
        avance = phase / RENDEZ_GLISSE_S
    elif phase < RENDEZ_GLISSE_S + RENDEZ_TENUE_S:
        return 1.0
    else:
        avance = (cycle - phase) / RENDEZ_GLISSE_S
    return avance * avance * (3 - 2 * avance)


def pose_danseurs(image: np.ndarray, seconde: float, energie: float,
                  sol: float = 0.93, marge: float = 0.10,
                  voile: float = DANSE_VOILE, haut: float = DANSE_HAUT,
                  vue: tuple[int, int, int, int] | None = None) -> None:
    """Des pantins dans les coins bas de la vue, quand la musique pousse.

    Dans les coins et translucides : le flux existe pour regarder une montagne,
    et rien de ce qu'on ajoute pour le plaisir n'a le droit de se mettre devant.

    « vue » dit où la caméra se pose dans l'image qu'on reçoit, et donc où
    commencent les bandes noires. Sans elle les pantins tiennent le cadre
    entier pour la vue, ce qui est vrai sur un Short et faux à l'antenne. C'est
    ce qui leur permet d'aller danser dehors sans qu'ils aient à connaître la
    mise en page : ils savent seulement qu'il y a un dedans et un dehors.

    Le sol, la marge, le voile et la taille se règlent parce que la même paire
    doit tenir dans deux cadres très différents. Sur un Short, l'application
    recouvre le bas de l'écran de son titre et le bord droit de ses boutons :
    des pantins posés aux valeurs du direct y danseraient derrière l'interface,
    c'est-à-dire nulle part. Et leur taille se compte en hauteur, donc un cadre
    debout les grossit par rapport à sa largeur jusqu'à ce que les bras sortent
    — d'où le réglage, qui n'est pas un goût mais une géométrie.

    Les valeurs par défaut sont celles de l'antenne, qui ne bouge pas.

    De temps en temps ils se rejoignent au milieu de la fenêtre, se
    tiennent l'un à l'autre, et rentrent. Pas pendant un survol : l'appelant
    ne les pose déjà pas. Pas sur un Short : il n'y a nulle part où aller,
    et le milieu appartient encore à la montagne.
    """
    if energie < DANSE_ARRET:
        return
    hauteur, largeur = image.shape[:2]
    gauche, cime, large_vue, haute_vue = vue or (0, 0, largeur, hauteur)
    # Entre le seuil d'arrêt et celui d'entrée, ils s'effacent au lieu de
    # disparaître d'un coup : une coupure franche se verrait plus qu'eux.
    force = min(1.0, (energie - DANSE_ARRET) / (DANSE_SEUIL - DANSE_ARRET))
    taille = haute_vue * haut
    # Jambe tendue, le pied descend quatre centièmes de la taille sous la
    # hanche, et le liseré sombre déborde encore du trait. « Sol » désigne donc
    # le pixel le plus bas du pantin et non la hauteur de ses hanches : sans
    # cela la garantie donnée à l'appelant est fausse d'une trentaine de pixels,
    # ce qui est précisément la largeur de bande qu'on essaie d'éviter.
    tube = max(2, int(taille * 0.045))
    pied = int(cime + haute_vue * sol - taille * 0.04
               - (tube + max(2, tube // 2)) / 2)
    # Un dixième de la largeur, et non un quatorzième : bras tendu, le pantin
    # atteint six centièmes de la largeur depuis son axe, et à sept il sortait
    # du cadre une fois sur trois — une main coupée par le bord ne se lit pas
    # comme un parti pris, elle se lit comme un bogue.
    bord = int(large_vue * marge)
    maison = (gauche + bord, gauche + large_vue - bord)
    # Dehors, c'est le milieu de la bande. Et seulement si le pantin y tient :
    # une bande plus étroite que sa demi-envergure lui couperait les mains, et
    # un Short n'a pas de bande du tout. Là où il n'y a nulle part où aller, ils
    # restent chez eux — la promenade est une conséquence de la mise en page,
    # pas une décoration qu'on pose dessus.
    dehors = (gauche / 2, (gauche + large_vue + largeur) / 2)
    place = min(gauche, largeur - gauche - large_vue) >= taille * 0.5
    sortie = promenade(seconde) if place else 0.0
    ensemble = rendez_vous(seconde) if place and sortie == 0.0 else 0.0
    # La cadence suit l'énergie : mou quand c'est calme, pressé quand ça tape.
    phase = seconde * DANSE_PAS_S * min(1.6, 0.5 + energie * 4)
    calque = image.copy()
    milieu = gauche + large_vue / 2
    ecart = taille * 0.55
    for i, (chez_lui, ailleurs) in enumerate(zip(maison, dehors)):
        if ensemble > 0:
            cible = milieu + (-ecart if i == 0 else ecart)
            x = int(chez_lui + (cible - chez_lui) * ensemble)
        else:
            x = int(chez_lui + (ailleurs - chez_lui) * sortie)
        _danseur(calque, x, pied, taille, phase + i * 2.1,
                 un_clair(seconde, i))
    # Pleins dehors, voilés dedans. Le voile n'est pas une esthétique, c'est
    # une politesse envers la montagne : on ne se met pas devant ce que les gens
    # sont venus regarder. Dans la bande noire il n'y a rien derrière eux, donc
    # plus rien à ménager, et le demi-effacement n'y serait qu'une timidité
    # héritée. C'est aussi ce qui fait qu'on remarque la sortie.
    opacite = (voile + (1.0 - voile) * sortie) * force
    cv2.addWeighted(calque, opacite, image, 1.0 - opacite, 0.0, dst=image)


# Les tons du tapis volant, en BGR comme tout OpenCV.
TAPIS_ETOFFE = (62, 92, 228)
TAPIS_FRANGE = (120, 205, 250)


def _elephant(calque: np.ndarray, cx: int, sol: int, taille: float,
              phase: float, couleur: tuple[int, int, int] = BLANC) -> None:
    """Un éléphanteau en tubes, de la même main que les pantins qui dansent.

    Il était rose et plein, modelé en ellipses dégradées. C'était joli et
    c'était un corps étranger : tout le reste de ce qu'on ajoute à l'image —
    les deux pantins, le surfeur sur la piste, le bonhomme du tapis — est
    tracé au tube blanc ourlé de noir, et le seul volume peint du flux se
    lisait comme un autocollant collé par-dessus le dessin. Un trait commun
    dit que tout cela vient du même endroit ; c'est aussi notre logo.

    Donc le même tube, le même ourlet, et le même parti pris que les pantins :
    les membres posés un peu à côté des articulations plutôt que soudés
    dessus. Un éléphant bien assemblé a l'air d'un schéma d'anatomie.

    Il regarde vers la gauche, du côté d'où viennent les voitures.

    « taille » est sa hauteur au garrot, « sol » la ligne où ses pieds posent.
    """
    tube = max(2, int(taille * 0.045))
    # Le même liseré sombre que les pantins : le blanc seul s'évanouit sur un
    # ciel de brouillard, et c'est le fond qu'on a la moitié du temps ici.
    ourlet = tube + max(2, tube // 2)

    def trait(a, b, epais=None):
        epais = epais or tube
        cv2.line(calque, a, b, (0, 0, 0), epais + ourlet - tube, cv2.LINE_AA)
        cv2.line(calque, a, b, couleur, epais, cv2.LINE_AA)

    def masse(centre, axes, angle=0.0):
        """Une ellipse pleine, cernée de sombre comme les membres des pantins.

        Au contour, les trois ellipses du corps, de la tête et de l'oreille se
        croisaient en un bretzel d'anneaux où personne ne reconnaissait un
        éléphant. Les pantins ne sont pas faits de contours : leurs membres
        sont des capsules pleines, et c'est le liseré sombre de la suivante
        qui détache chaque pièce de celle d'avant. Il suffit donc de dessiner
        de l'arrière vers l'avant.
        """
        cv2.ellipse(calque, centre, (axes[0] + ourlet - tube, axes[1] + ourlet - tube),
                    angle, 0, 360, (0, 0, 0), -1, cv2.LINE_AA)
        cv2.ellipse(calque, centre, axes, angle, 0, 360, couleur, -1, cv2.LINE_AA)

    # Le dandinement : il se soulève sur le temps et se balance à contretemps.
    # Deux mouvements de périodes différentes, sinon il tressaute sur place
    # comme un jouet à ressort.
    bond = int(math.sin(phase * 2) * taille * 0.05)
    roulis = math.sin(phase) * taille * 0.04
    pose = sol - bond
    axe = cx + int(roulis)

    # Les pattes d'abord, pour que le corps les recouvre à la hanche. Courtes
    # et épaisses : des pattes à l'échelle feraient un animal juste, et un
    # animal juste n'est pas drôle. Celles-ci sont des poteaux.
    for i, ecart in enumerate((-0.24, 0.11, -0.09, 0.26)):
        balance = math.sin(phase + i * 1.7) * taille * 0.05
        pied = (int(axe + taille * ecart + balance), pose)
        haut = (int(axe + taille * ecart), int(pose - taille * 0.26))
        trait(haut, pied, int(tube * 2.0))
        cv2.circle(calque, pied, int(tube * 1.1), couleur, -1, cv2.LINE_AA)

    # La queue pend derrière le corps, donc avant lui.
    fouet = math.sin(phase * 3) * 0.5
    queue = (int(axe + taille * 0.36), int(pose - taille * 0.66))
    trait(queue, (int(queue[0] + taille * 0.15 + fouet * taille * 0.06),
                  int(queue[1] + taille * 0.30)), max(2, int(tube * 0.7)))

    # Le corps puis la tête, de l'arrière vers l'avant. Le liseré sombre de la
    # tête la détache du corps sans qu'on ait à dessiner la moindre couture.
    corps = (axe, int(pose - taille * 0.56))
    masse(corps, (int(taille * 0.40), int(taille * 0.29)))

    tete = (int(axe - taille * 0.44), int(pose - taille * 0.72))
    masse(tete, (int(taille * 0.27), int(taille * 0.26)))

    # L'oreille bat, et c'est elle qui fait tout le travail : c'est à l'oreille
    # qu'on reconnaît un éléphant dessiné, pas à la trompe.
    bat = 18 * math.sin(phase * 2 + 0.7)
    oreille = (tete[0] + int(taille * 0.11), tete[1] - int(taille * 0.03))
    masse(oreille, (int(taille * 0.22), int(taille * 0.17)), angle=bat)

    # La trompe : un arc qui s'affine et qui se relève quand il saute.
    leve = math.sin(phase * 2) * 0.5
    depart = (tete[0] - taille * 0.16, tete[1] + taille * 0.10)
    courbe = []
    for pas in range(7):
        part = pas / 6
        angle = -0.3 + part * (1.9 + leve)
        courbe.append((int(depart[0] - math.sin(angle) * taille * 0.30 * part
                           - taille * 0.04),
                       int(depart[1] + math.cos(angle * 0.8) * taille * 0.32 * part)))
    for pas in range(6):
        trait(courbe[pas], courbe[pas + 1],
              max(2, int(tube * (1.7 - pas * 0.19))))

    # Pas de défenses : c'est un éléphanteau. Elles disaient surtout
    # « adulte », et un adulte qui danse sur un rond-point est moins aimable
    # qu'un petit qui danse sur un rond-point.

    # L'œil, en dernier et tout petit : plus il est petit, plus il est gentil.
    # Plein et non au trait — c'est le seul endroit du dessin où une tache
    # pleine veut dire quelque chose, et sans elle le regard est en verre.
    oeil = (tete[0] - int(taille * 0.09), tete[1] - int(taille * 0.07))
    cv2.circle(calque, oeil, max(2, int(taille * 0.05)), couleur, -1, cv2.LINE_AA)
    cv2.circle(calque, oeil, max(1, int(taille * 0.024)), (20, 20, 20), -1,
               cv2.LINE_AA)


# L'éléphant danse onze minutes et une seconde après le précédent, le tapis
# passe toutes les six minutes trente-sept, le sous-marin toutes les huit
# minutes quarante-trois. Trois nombres premiers, et c'est la seule raison de
# leur drôle de valeur : avec des périodes rondes, les numéros tomberaient
# ensemble plusieurs fois par jour et on croirait à un spectacle réglé.
# Premiers entre eux, deux d'entre eux ne se croisent qu'une fois tous les
# trois jours.
ELEPHANT_PERIODE_S = 661.0
ELEPHANT_TENUE_S = 4.0
# Ce qu'il remplit du cadre, et son encombrement — mesuré sur soixante poses,
# en multiples de sa hauteur au garrot. Les quatre nombres servent à le
# centrer : le dessin n'est pas symétrique, sa trompe lui prend une taille
# entière à gauche et sa queue une demi-taille à droite, si bien qu'un
# éléphant posé au milieu du cadre a l'air posé à droite.
ELEPHANT_PART = 0.95
ELEPHANT_GAUCHE = 1.002
ELEPHANT_DROITE = 0.578
ELEPHANT_HAUTEUR_SOL = 1.030
ELEPHANT_BAS = 0.120
ELEPHANT_LARGE = ELEPHANT_GAUCHE + ELEPHANT_DROITE
ELEPHANT_HAUT = ELEPHANT_HAUTEUR_SOL + ELEPHANT_BAS


ELEPHANT_OUVRE_H = 1      # il entre en scène à une heure du matin
ELEPHANT_FERME_H = 6      # et s'en va à six


def pose_elephant(image: np.ndarray, seconde: float, energie: float,
                  vue: tuple[int, int, int, int] | None = None,
                  nuit: bool = False, heure: int | None = None) -> bool:
    """Un éléphanteau rose vient danser en gros plan, de temps en temps.

    Plein cadre et centré, quelques secondes. Il dansait d'abord sur le
    rond-point, à sa vraie échelle, ce qui était joli et ne se voyait pas : à
    trente pixels de haut au fond d'une image sombre, un éléphant rose n'est
    plus un éléphant rose, c'est une tache.

    Et c'est bien un gros plan et non une apparition : pendant quatre secondes
    il n'y a plus rien d'autre à l'écran. C'est pour ça que l'appelant ne le
    propose que dans un creux de cinq minutes — c'est la seule chose de tout
    le flux qui cache la route, et elle ne le fait que quand il n'y a rien
    dessus. Ni la nuit ni le jour ça ne doit passer devant un évènement.

    Rend vrai quand il est là, pour que l'appelant sache qu'il se passe
    quelque chose.
    """
    if energie < DANSE_ARRET:
        return False
    # Entre une heure et six heures du matin, à la montagne. C'est la seule
    # chose du flux qui cache la route, et c'est aussi la plus difficile à
    # expliquer : un éléphant rose plein cadre à seize heures ressemble à une
    # panne, le même à trois heures du matin ressemble à ce qu'il est. Et
    # personne n'attend rien de cette route entre une heure et six heures.
    if heure is not None and not ELEPHANT_OUVRE_H <= heure < ELEPHANT_FERME_H:
        return False
    phase_cycle = en_scene("elephant", seconde, nuit)
    if phase_cycle is None:
        return False
    hauteur, largeur = image.shape[:2]
    gauche, cime, large_vue, haute_vue = vue or (0, 0, largeur, hauteur)
    # Le dessin occupe 1,58 fois sa taille en largeur et 1,15 en hauteur,
    # mesuré sur soixante poses. On prend la plus contraignante des deux, et
    # il tient alors dans le cadre quelle que soit la forme de la vue.
    taille = min(large_vue / ELEPHANT_LARGE, haute_vue / ELEPHANT_HAUT) * ELEPHANT_PART
    if taille < 12:
        return False
    cx = int(gauche + large_vue / 2 + taille * (ELEPHANT_GAUCHE - ELEPHANT_DROITE) / 2)
    sol = int(cime + haute_vue / 2 + taille * ELEPHANT_HAUT / 2 - taille * ELEPHANT_BAS)
    calque = image.copy()
    _elephant(calque, cx, sol, taille, seconde * DANSE_PAS_S * 0.8,
              un_clair(seconde, 1))
    # Il arrive et repart en fondu d'une seconde. Un éléphant qui apparaît d'un
    # coup se lit comme une image sautée ; en fondu, il se lit comme un rêve.
    # Presque opaque une fois arrivé : à quatre-vingt-huit centièmes on voyait
    # la montagne à travers lui, ce qui allait quand il faisait trente pixels
    # de haut et en fait un fantôme en gros plan.
    bord = min(phase_cycle, ELEPHANT_TENUE_S - phase_cycle, 1.0) * 0.96
    cv2.addWeighted(calque, bord, image, 1.0 - bord, 0.0, dst=image)
    return True


# L'OURS DU MONT SEREIN
# ---------------------
# Il y a une sculpture de bois debout près du chemin, entre le rond-point et la
# bergerie : un ours grandeur nature, que la carte de scène mesure à 1,73 m de
# haut et 0,64 m de large, à vingt-cinq mètres de l'objectif. Il regarde passer
# les voitures depuis des années sans rien dire.
#
# Une fois toutes les deux heures et quart, de jour, son double descend danser
# sur le rond-point en pleurant et crie que c'est chez lui. L'original ne bouge
# pas : il reste où il est, et c'est ce qui rend la chose lisible — on voit les
# deux en même temps, donc on comprend que le second est une apparition.
#
# De jour seulement, et c'est le seul numéro du plateau qui le soit. Les autres
# vont plus vite la nuit parce que la nuit il ne se passe rien ; celui-ci est
# une découpe photographique prise en plein midi, et collée sur une image
# nocturne elle ne ressemble pas à un ours, elle ressemble à une vignette
# qu'on aurait oublié d'éteindre.
OURS_PERIODE_S = 8191.0     # deux heures et quart, et premier comme les autres
# Il marche jusqu'à l'îlot, puis il y danse. La danse est le numéro : dix
# secondes au centre du rond-point, pas un passage éclair.
OURS_MARCHE_S = 2.6
OURS_DANSE_S = 10.0
OURS_TENUE_S = OURS_MARCHE_S + OURS_DANSE_S
# Le temps qu'il faut à YouTube pour que l'image du flux qui vient de démarrer
# arrive chez quelqu'un. Avant, l'ours danserait pour personne.
OURS_RETARD_S = 90.0
# Où il est et où il va, en parts du cadre de la caméra. Chez lui, relevé
# une fois. Au centre de l'îlot, lu sur la carte de scène : le barycentre
# des cellules « island », pas un point choisi à l'œil.
OURS_LA = (0.5698, 0.8593)
OURS_ILOT = (0.2304, 0.8706)
# Sa taille dans l'image d'origine, d'où la découpe a été prise.
OURS_LARGE = 72 / 1920
OURS_HAUT = 140 / 1080
# La carte de scène le donne à vingt-cinq mètres et l'îlot à vingt-sept : un
# mètre y vaut quarante-trois pixels contre quarante-sept chez lui. Le double
# n'est donc pas dessiné à une taille choisie, il est dessiné à la taille qu'un
# ours aurait là-bas.
OURS_ECHELLE_ILOT = 43.0 / 47.0
# Un peu plus grand que le vrai, pour qu'on le lise. Pas assez pour qu'il
# quitte l'îlot : à 2,5 fois il sautait hors du rond-point.
OURS_ENFLE = 1.35
OURS_CRI = "THIS IS MY HOME!!!!!"
OURS_JAUNE = (40, 230, 250)
OURS_LARME = (235, 190, 120)
# La photo-preuve : elle apparaît avec la danse, pas pendant la marche.
# Un fondu d'une seconde, aux deux bouts : claquer, ce serait une pub.
OURS_PREUVE_FONDU_S = 0.9
# En dessous, ce n'est plus une bande, c'est le bord d'un Short.
OURS_PREUVE_BANDE = 90


def _colle_decoupe(image: np.ndarray, sprite: np.ndarray, cx: float, sol: float,
                   large: int, haut: int, penche: float, aplat: float) -> tuple | None:
    """Colle la découpe, son milieu en cx et ses pieds sur sol."""
    haut = max(2, int(haut * aplat))
    large = max(2, int(large))
    petit = cv2.resize(sprite, (large, haut), interpolation=cv2.INTER_AREA)
    if abs(penche) > 0.01:
        tourne = cv2.getRotationMatrix2D((large / 2, haut), penche, 1.0)
        petit = cv2.warpAffine(petit, tourne, (large, haut), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    x, y = int(cx - large / 2), int(sol - haut)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(image.shape[1], x + large), min(image.shape[0], y + haut)
    if x1 <= x0 or y1 <= y0:
        return None
    bout = petit[y0 - y:y1 - y, x0 - x:x1 - x]
    part = bout[:, :, 3:4].astype(np.float32) / 255.0
    fond = image[y0:y1, x0:x1].astype(np.float32)
    image[y0:y1, x0:x1] = (bout[:, :, :3] * part + fond * (1 - part)).astype(np.uint8)
    return x + large / 2, y, large, haut


def _larmes(image: np.ndarray, cx: float, cime: float, large: int, haut: int,
            seconde: float) -> None:
    """Deux larmes qui partent des yeux et descendent le long du museau.

    Placées sur la hauteur du dessin et non sur sa largeur : la sculpture est
    deux fois plus haute que large, et une larme calée sur la largeur tombait
    à côté de la tête comme une bille qu'on aurait lâchée par erreur.
    """
    for i, cote in enumerate((-0.14, 0.14)):
        part = (seconde * 1.25 + i * 0.5) % 1.0
        x = int(cx + cote * large)
        y = int(cime + haut * (0.16 + part * 0.42))
        rayon = max(1, int(haut * 0.022))
        cv2.circle(image, (x, y), rayon, OURS_LARME, -1, cv2.LINE_AA)
        cv2.circle(image, (x, y + rayon), max(1, rayon - 1), (250, 225, 190), -1, cv2.LINE_AA)


def _il_crie(image: np.ndarray, vue: tuple[int, int, int, int], seconde: float) -> None:
    """THIS IS MY HOME!!!!! en jaune, et ça vibre."""
    gauche, cime, large_vue, haute_vue = vue
    echelle = image.shape[1] / 1600
    taille = 2.6 * echelle * (1 + 0.04 * math.sin(seconde * 18))
    trait = max(2, int(7 * echelle))
    (mot_l, _), _ = cv2.getTextSize(OURS_CRI, cv2.FONT_HERSHEY_DUPLEX, taille, trait)
    # Dans le ciel, au-dessus de lui. Rien de ce qu'on ajoute pour le plaisir
    # n'a le droit de couvrir ce que les gens viennent regarder, et ce qu'ils
    # viennent regarder est la route.
    x = int(gauche + (large_vue - mot_l) / 2 + math.sin(seconde * 31) * 7 * echelle)
    y = int(cime + haute_vue * 0.18 + math.cos(seconde * 27) * 7 * echelle)
    cv2.putText(image, OURS_CRI, (x, y), cv2.FONT_HERSHEY_DUPLEX, taille,
                (20, 20, 20), trait + 6, cv2.LINE_AA)
    cv2.putText(image, OURS_CRI, (x, y), cv2.FONT_HERSHEY_DUPLEX, taille,
                OURS_JAUNE, trait, cv2.LINE_AA)


OURS_PREUVE_MOT = "REPLAY · 2025"


def pose_preuve_ours(image: np.ndarray, photo: np.ndarray | None,
                     phase: float, vue: tuple[int, int, int, int]) -> None:
    """La preuve, au même coin que le direct pendant la vue 3D.

    En bas à droite de la fenêtre. La couleur reste : un léger flou suffit
    à dire que ce n'est pas le direct. Le mot est celui d'une archive.
    """
    if photo is None or photo.size == 0 or phase < OURS_MARCHE_S:
        return
    depuis = phase - OURS_MARCHE_S
    reste = OURS_TENUE_S - phase
    force = min(1.0, depuis / OURS_PREUVE_FONDU_S, max(0.0, reste) / OURS_PREUVE_FONDU_S)
    if force < 0.03:
        return
    x, y, large, haut = vue
    echelle = image.shape[1] / 1600
    marge = int(18 * echelle)
    petit_l = max(96, int(large * 0.26))
    petit_h = max(54, int(petit_l * photo.shape[0] / max(photo.shape[1], 1)))
    gx = x + large - petit_l - marge
    gy = y + haut - petit_h - marge
    if gx < x or gy < y or gx + petit_l > image.shape[1] or gy + petit_h > image.shape[0]:
        return
    petit = cv2.resize(photo, (petit_l, petit_h), interpolation=cv2.INTER_AREA)
    petit = cv2.GaussianBlur(petit, (0, 0), 1.1)
    calque = image.copy()
    calque[gy:gy + petit_h, gx:gx + petit_l] = petit
    cadre_encart(calque, (gx - 1, gy - 1), (gx + petit_l, gy + petit_h), echelle)
    taille = 0.42 * echelle
    base = gy - int(7 * echelle)
    cv2.putText(calque, OURS_PREUVE_MOT, (gx, max(int(12 * echelle), base)),
                cv2.FONT_HERSHEY_SIMPLEX, taille, AMBRE, max(1, int(echelle)),
                cv2.LINE_AA)
    cv2.addWeighted(calque, force, image, 1.0 - force, 0.0, dst=image)


def pose_ours(image: np.ndarray, seconde: float, sprite: np.ndarray | None,
              vue: tuple[int, int, int, int] | None = None,
              preuve: np.ndarray | None = None) -> float | None:
    """Le double de l'ours descend danser sur le rond-point, en pleurant.

    Rend où en est le numéro, pour que l'appelant sache quand le faire grogner
    et quand le faire crier — c'est le seul endroit qui connaît son horloge, et
    la voix ne doit partir qu'une fois, pas à chaque image.
    """
    if sprite is None or sprite.size == 0:
        return None
    phase = en_scene("ours", seconde)
    if phase is None:
        return None
    hauteur, largeur = image.shape[:2]
    gauche, cime, large_vue, haute_vue = vue or (0, 0, largeur, hauteur)
    marche = min(1.0, phase / OURS_MARCHE_S)
    douce = marche * marche * (3 - 2 * marche)   # il part et s'arrête en douceur
    ux = OURS_LA[0] + (OURS_ILOT[0] - OURS_LA[0]) * douce
    uy = OURS_LA[1] + (OURS_ILOT[1] - OURS_LA[1]) * douce
    echelle = 1.0 + (OURS_ECHELLE_ILOT - 1.0) * douce
    if marche < 1.0:
        saut, penche, aplat = abs(math.sin(phase * 7)) * 3, math.sin(phase * 7) * 3, 1.0
    else:
        # Sur l'îlot il danse, il ne saute plus : un balancement, les pieds
        # restent au centre du rond-point.
        depuis = phase - OURS_MARCHE_S
        echelle *= 1.0 + (OURS_ENFLE - 1.0) * min(1.0, depuis / 1.1)
        saut = abs(math.sin(depuis * 5)) * 4
        penche = math.sin(depuis * 2.4) * 6
        aplat = 1.0 - 0.04 * abs(math.sin(depuis * 5))
    large = OURS_LARGE * large_vue * echelle
    haut = OURS_HAUT * haute_vue * echelle
    if large < 6 or haut < 12:
        return None
    boite = _colle_decoupe(image, sprite, gauche + ux * large_vue,
                           cime + uy * haute_vue - saut, int(large), int(haut),
                           penche, aplat)
    if boite is not None and marche >= 1.0:
        _, sommet, son_large, son_haut = boite
        _larmes(image, boite[0], sommet, son_large, son_haut, phase)
        _il_crie(image, (gauche, cime, large_vue, haute_vue), phase)
        pose_preuve_ours(image, preuve, phase,
                         (gauche, cime, large_vue, haute_vue))
    return phase


# Ce qui raccourcit l'attente quand il ne se passe rien.
#
# Le jour, la route suffit : des voitures, des cars, des marcheurs, et un
# survol du relief de temps en temps. La nuit, la veille ne voit presque plus
# rien — c'est mesuré, pas supposé — et le survol ne peut pas jouer, parce
# qu'il est rendu en plein soleil et qu'au milieu d'une nuit noire il ne montre
# pas le relief, il montre qu'on a collé une autre vidéo. Il reste donc douze
# heures d'une image fixe et sombre, et c'est exactement là qu'on a besoin
# qu'il se passe quelque chose.
#
# Le facteur s'applique aux deux périodes à la fois, ce qui laisse intact ce
# qui faisait l'intérêt de nombres premiers : leur rapport ne change pas, donc
# les deux numéros ne se mettent pas à tomber ensemble.
NUIT_PLUS_SOUVENT = 3.0
# Sauf pour ceux-là. L'accélération existe parce que la nuit il ne se passe
# rien ; l'ours, lui, est rare exprès. Trois fois plus souvent ferait seize
# cris jaunes par nuit, et seize fois n'est plus rare — c'est un gag qu'on a
# usé. Il garde donc sa cadence du jour, de jour comme de nuit.
PAS_PRESSES = frozenset({"ours"})

# LE PLATEAU : UN NUMÉRO À LA FOIS
# -------------------------------
# Chaque numéro comptait son tour tout seul, sur sa propre période. Les
# périodes sont des nombres premiers, ce qui espace les coïncidences mais ne
# les empêche pas : sur une journée, le tapis volant, le sous-marin et le
# surfeur finissent par tomber ensemble, et l'écran ressemble alors à une
# vitrine de Noël. Une fois, c'est drôle. Deux fois, on cesse de croire à
# chacun d'eux séparément.
#
# La règle est donc simple et se décide sans mémoire, uniquement sur l'heure,
# ce qui compte parce que le flux redémarre et ne doit pas rejouer deux fois
# la même chose : un numéro ne monte en scène que si le plateau était libre
# à l'instant précis où son tour commençait. S'il ne l'était pas, il passe
# son tour entier — il ne s'invite pas au milieu. Un sous-marin qui
# apparaîtrait d'un coup en plein ciel, à mi-traversée, serait pire que pas
# de sous-marin du tout.
#
# L'ordre de cette table départage les ex æquo, qui existent : deux périodes
# entières tombent sur la même seconde de temps en temps.
# Remplie plus bas, quand les quatre numéros ont donné leurs nombres : elle
# ne les répète pas, elle les désigne. Deux tables de périodes, c'est une
# table de trop, et c'est celle qu'on oublie de changer.
#
# Quatrième colonne : le retard à l'allumage. Sans lui, tous les numéros ont
# leur premier tour à l'instant zéro, l'exclusion les départage sur l'ordre de
# la table, et seul le premier passe — les autres attendent une période entière
# après chaque redémarrage du flux. Pour le tapis, qui revient toutes les six
# minutes, personne ne s'en aperçoit. Pour l'ours, qui revient toutes les deux
# heures et quart, ça voulait dire ne jamais le voir le jour où on vient de le
# déployer. Un décalage le met en scène peu après l'ouverture, une fois, puis
# son tour reprend sa cadence.
PLATEAU: tuple[tuple[str, float, float, float], ...] = ()


def _debut_du_tour(instant: int, tour: int, retard: int) -> int:
    """Le début du tour en cours pour un numéro qui démarre avec du retard.

    Avant son retard, le calcul rend un début situé une période plus tôt, donc
    une phase plus longue que la durée du numéro : il ne se montre pas, ce qui
    est exactement ce qu'on veut.
    """
    return retard + (instant - retard) // tour * tour


def en_scene(nom: str, seconde: float, nuit: bool = False) -> float | None:
    """Où en est ce numéro, s'il a le droit d'être à l'écran maintenant."""
    duree = dict((a, d) for a, _, d, _ in PLATEAU).get(nom)
    if duree is None:
        return None
    # Tout le calcul se fait en millisecondes entières. La nuit les périodes
    # sont divisées par trois et 397/3 ne tombe pas juste en binaire ; deux
    # calculs du même instant finissaient par différer d'un milliardième de
    # seconde, ce qui suffit à faire croire à deux numéros qu'ils sont chacun
    # arrivés les premiers. Ils passaient alors ensemble, rarement, et c'est
    # précisément ce qu'on cherche à supprimer. Des entiers ne mentent pas.
    presse = NUIT_PLUS_SOUVENT if nuit else 1.0
    vite = {a: 1.0 if a in PAS_PRESSES else presse for a, _, _, _ in PLATEAU}
    tours = {a: max(1, round(p * 1000 / vite[a])) for a, p, _, _ in PLATEAU}
    # Le retard suit la même division que la période : la nuit tout le plateau
    # est la même journée en accéléré, et pas une autre répartition.
    retards = {a: round(r * 1000 / vite[a]) for a, _, _, r in PLATEAU}
    instant = round(seconde * 1000)
    commence = _debut_du_tour(instant, tours[nom], retards[nom])
    phase = (instant - commence) / 1000.0
    if phase >= duree:
        return None
    mon_rang = [a for a, _, _, _ in PLATEAU].index(nom)
    for rang, (autre, _, sa_duree, _) in enumerate(PLATEAU):
        if autre == nom:
            continue
        sienne = (commence - _debut_du_tour(commence, tours[autre], retards[autre])) / 1000.0
        if sienne >= sa_duree:
            continue
        # L'autre était déjà là quand mon tour a commencé. « Strictement
        # avant » compte : sienne vaut zéro quand les deux tours commencent
        # à la même seconde, et c'est le seul cas où l'ordre de la table
        # tranche. Sans cette distinction, chacun se jugeait sur les seuls
        # numéros écrits avant lui, et un numéro écrit plus haut passait
        # par-dessus celui qui était en scène depuis cinq secondes.
        if sienne > 0 or rang < mon_rang:
            return None
    return phase

TAPIS_PERIODE_S = 397.0
TAPIS_TRAVERSEE_S = 14.0
# Aux deux tiers de la descente entre le haut du cadre et la crête, et le
# reste de l'onde en plus. Plus haut, il rasait le bord et on n'en voyait que
# la moitié ; le milieu du ciel est l'endroit d'où on le regarde passer. La crête, pas une valeur fixe : à hauteur constante il passerait devant
# le sommet du Ventoux, qui est précisément ce que les gens sont venus voir. En
# la suivant, il le survole — et sur une autre caméra il survolera la sienne.
TAPIS_CIEL = 0.66
TAPIS_ONDE = 0.07
# Faute de contour du ciel, une hauteur prudente.
TAPIS_CIEL_SANS_CARTE = 0.14
# Les quatre mesures du pantin et de son tapis. Les trois premières se
# comptent en multiples de la taille du pantin : ce qu'il occupe au-dessus de
# ses pieds bras levés (mesuré à 1,207 sur quatre cents poses), ce que les
# franges pendent sous elles, et sa demi-envergure la plus grande. La dernière
# est l'amplitude de l'ondulation de l'étoffe, qui soulève ou abaisse les
# pieds — c'est elle qui lui faisait encore dépasser du cadre.
TAPIS_TETE = 1.25
TAPIS_FRANGE = 0.78
TAPIS_ENVERGURE = 1.2
TAPIS_ROULIS = 0.17


def _crete(ciel: list | None, part_x: float) -> float | None:
    """Jusqu'où le ciel descend à cette abscisse : la ligne de crête.

    On prend le point le plus bas du contour, et non le premier croisement :
    un contour de ciel peut redescendre derrière un pylône ou une antenne, et
    c'est sous le plus bas de ses passages qu'il y a de la montagne.
    """
    if not ciel or len(ciel) < 3:
        return None
    bas = None
    for (x1, y1), (x2, y2) in zip(ciel, ciel[1:] + ciel[:1]):
        if min(x1, x2) <= part_x <= max(x1, x2) and x1 != x2:
            y = y1 + (y2 - y1) * (part_x - x1) / (x2 - x1)
            bas = y if bas is None else max(bas, y)
    return bas


def pose_tapis(image: np.ndarray, seconde: float, energie: float,
               ciel: list | None = None,
               vue: tuple[int, int, int, int] | None = None,
               nuit: bool = False) -> bool:
    """Un tapis volant traverse le ciel avec un troisième danseur dessus.

    Latéralement et d'un bord à l'autre du cadre entier, bandes noires
    comprises : il entre de nulle part et sort de même, ce qui est la seule
    façon qu'un tapis volant a d'être crédible. Les deux pantins du bas, eux,
    sont chez eux et vont faire un tour ; celui-ci est de passage.

    Il suit la crête au lieu de voler droit, donc il monte au-dessus du sommet
    et redescend de l'autre côté. C'était une nécessité avant d'être une jolie
    chose : à hauteur fixe, il traversait le Ventoux par le milieu.

    Et comme il reste au-dessus du relief, il n'attend pas le creux comme
    l'éléphant — il n'y a jamais rien à regarder là-haut.
    """
    if energie < DANSE_ARRET:
        return False
    phase_cycle = en_scene("tapis", seconde, nuit)
    if phase_cycle is None:
        return False
    hauteur, largeur = image.shape[:2]
    gauche, cime, large_vue, haute_vue = vue or (0, 0, largeur, hauteur)
    avance = phase_cycle / TAPIS_TRAVERSEE_S
    # Il part entièrement hors du cadre et finit entièrement dehors.
    cx = int(-haute_vue * 0.3 + avance * (largeur + haute_vue * 0.6))
    # Au-dessus des bandes noires il n'y a pas de crête : on prolonge celle du
    # bord de la vue, sans quoi il plongerait en entrant et en sortant.
    # Le tapis est large : sous ses deux bouts la crête n'est pas celle de son
    # milieu, et c'est par un bout qu'il mordait le versant. Le plancher du vol
    # est donc la plus basse des crêtes qu'il survole, mesurée à sa plus grande
    # envergure possible — on ne connaît pas encore sa taille, et une marge
    # prise trop large ne coûte que quelques pixels d'altitude.
    envergure = haute_vue * DANSE_HAUT * TAPIS_ENVERGURE
    bouts = [_crete(ciel, min(1.0, max(0.0, (cx + bord * envergure - gauche)
                                       / max(large_vue, 1))))
             for bord in (-1, 0, 1)]
    hauteurs = [c for c in bouts if c is not None]
    ciel_haut = (min(hauteurs) if hauteurs else TAPIS_CIEL_SANS_CARTE) * haute_vue
    # Le bonhomme fait la même taille que ceux du bas, donc c'est lui qui
    # commande et le tapis se règle sur lui. L'ensemble doit tenir entre le
    # haut du cadre et ce plancher : là où le ciel est trop mince, tout
    # rapetisse plutôt que de se faire couper la tête ou de plonger dans la
    # montagne.
    #
    # Il monte plus haut que sa taille nominale : sa tête est à quatre-vingt-
    # quatorze centièmes au-dessus de ses pieds et un bras levé passe la barre
    # d'un sixième. On compte donc une taille et quart pour lui, plus les sept
    # dixièmes d'étoffe qui pendent sous ses pieds.
    ensemble = haute_vue * DANSE_HAUT * (TAPIS_TETE + (TAPIS_FRANGE
                                                      + 2 * TAPIS_ROULIS) / 1.5)
    facteur = min(1.0, ciel_haut / max(ensemble, 1.0))
    danseur = haute_vue * DANSE_HAUT * facteur
    etoffe = danseur / 1.5
    vol = math.sin(avance * math.pi * 3) * ciel_haut * TAPIS_ONDE
    # Les pieds posent à cette hauteur-là ; au-dessus il y a le danseur, en
    # dessous l'épaisseur de l'étoffe, l'amplitude de son ondulation et la
    # longueur de ses franges, qui pendent plus bas que tout le reste.
    cy = cime + TAPIS_CIEL * ciel_haut - etoffe * 0.3 + vol
    cy = max(cy, cime + danseur * TAPIS_TETE + etoffe * TAPIS_ROULIS)
    cy = min(cy, cime + ciel_haut - etoffe * (TAPIS_FRANGE + TAPIS_ROULIS))
    calque = image.copy()
    _tapis(calque, cx, int(cy), etoffe, seconde * DANSE_PAS_S, danseur=danseur,
           clair=un_clair(seconde, 2))
    cv2.addWeighted(calque, 0.9, image, 0.1, 0.0, dst=image)
    return True


# Le sous-marin jaune de benoit-prieur.fr, qui passe toutes les huit minutes
# quarante-trois et met vingt-deux secondes à traverser — lentement, parce
# qu'un sous-marin pressé n'est plus un sous-marin.
SOUS_MARIN_PERIODE_S = 523.0
SOUS_MARIN_TRAVERSEE_S = 22.0
# Sa hauteur, en parts de la hauteur de la vue. Un peu moins que les pantins :
# il est deux fois plus large que haut, et à la même hauteur qu'eux il barrerait
# le ciel d'un bout à l'autre.
SOUS_MARIN_HAUT = 0.17
SOUS_MARIN_CIEL = 0.50
# Il tangue d'un dixième de sa hauteur, deux fois et demie par traversée.
SOUS_MARIN_TANGAGE = 0.10
SOUS_MARIN_ROULIS = 2.5
# La place qu'on lui garde au-dessus de la crête, en multiples de sa hauteur :
# lui, plus de quoi tanguer des deux côtés.
SOUS_MARIN_PLACE = 1.0 + 2 * SOUS_MARIN_TANGAGE


def charge_vignette(chemin: Path) -> np.ndarray | None:
    """Un dessin avec sa transparence, ou rien s'il n'est pas là.

    Rien et non une erreur : un dessin manquant doit coûter un numéro, jamais
    la diffusion. C'est la règle de tout ce dossier — ce qu'on ajoute pour le
    plaisir n'a pas le droit de casser ce que les gens viennent regarder.
    """
    try:
        vignette = cv2.imread(str(chemin), cv2.IMREAD_UNCHANGED)
    except cv2.error:
        vignette = None
    if vignette is None or vignette.ndim != 3 or vignette.shape[2] != 4:
        log.info("Vignette illisible ou sans transparence : %s", chemin.name)
        return None
    return vignette


def _colle(image: np.ndarray, vignette: np.ndarray, x: int, y: int,
           opacite: float = 1.0) -> None:
    """Colle une vignette transparente, coin haut-gauche en (x, y).

    Elle a le droit de dépasser du cadre : c'est même nécessaire, puisque le
    sous-marin entre et sort par les côtés. On ne garde que l'intersection.
    """
    haut, large = vignette.shape[:2]
    hauteur, largeur = image.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(largeur, x + large), min(hauteur, y + haut)
    if x0 >= x1 or y0 >= y1:
        return
    bout = vignette[y0 - y:y1 - y, x0 - x:x1 - x]
    voile = bout[:, :, 3:4].astype(np.float32) * (opacite / 255.0)
    zone = image[y0:y1, x0:x1]
    zone[:] = (bout[:, :, :3] * voile + zone * (1.0 - voile)).astype(np.uint8)


def pose_sous_marin(image: np.ndarray, seconde: float,
                    vignette: np.ndarray | None,
                    ciel: list | None = None,
                    vue: tuple[int, int, int, int] | None = None,
                    nuit: bool = False) -> bool:
    """Le sous-marin jaune traverse le ciel du Ventoux, de temps en temps.

    Un sous-marin à mille quatre cents mètres d'altitude est une absurdité, et
    c'est exactement pour ça qu'il est là : il ne peut être pris pour rien
    d'autre. C'est la règle qu'on s'est donnée après la lune — tout ce qu'on
    ajoute au ciel doit être impossible à confondre avec ce que la veille
    cherche. Une lueur pâle, une traînée, un point brillant : non. Un
    sous-marin : oui.

    Il n'est pas dessiné ici. C'est celui de benoit-prieur.fr, repris tel quel
    dans `assets/`, et s'il n'y est pas il ne passe tout simplement pas.

    Comme le tapis, il suit la crête plutôt que de voler à hauteur fixe, et il
    rapetisse là où le ciel est trop mince : il ne doit jamais passer devant le
    sommet, qui est ce que les gens sont venus voir.
    """
    if vignette is None:
        return False
    phase_cycle = en_scene("sous-marin", seconde, nuit)
    if phase_cycle is None:
        return False
    hauteur, largeur = image.shape[:2]
    gauche, cime, large_vue, haute_vue = vue or (0, 0, largeur, hauteur)
    avance = phase_cycle / SOUS_MARIN_TRAVERSEE_S
    rapport = vignette.shape[1] / vignette.shape[0]
    # La plus basse des crêtes qu'il survole, mesurée à sa plus grande largeur
    # possible : c'est par un bout qu'un dessin large mord le versant.
    pleine_large = haute_vue * SOUS_MARIN_HAUT * rapport
    cx = -pleine_large + avance * (largeur + 2 * pleine_large)
    bouts = [_crete(ciel, min(1.0, max(0.0, (cx + bord * pleine_large / 2 - gauche)
                                       / max(large_vue, 1))))
             for bord in (-1, 0, 1)]
    hauteurs = [c for c in bouts if c is not None]
    ciel_haut = (min(hauteurs) if hauteurs else TAPIS_CIEL_SANS_CARTE) * haute_vue
    facteur = min(1.0, ciel_haut / max(haute_vue * SOUS_MARIN_HAUT
                                       * SOUS_MARIN_PLACE, 1.0))
    haut = haute_vue * SOUS_MARIN_HAUT * facteur
    large = haut * rapport
    if haut < 10:
        return False
    tangue = math.sin(avance * math.pi * 2 * SOUS_MARIN_ROULIS) * haut * SOUS_MARIN_TANGAGE
    milieu = cime + SOUS_MARIN_CIEL * ciel_haut + tangue
    milieu = max(milieu, cime + haut / 2)
    milieu = min(milieu, cime + ciel_haut - haut / 2)
    petit = cv2.resize(vignette, (max(2, int(large)), max(2, int(haut))),
                       interpolation=cv2.INTER_AREA)
    # Il entre et sort en fondu d'une seconde, comme l'éléphant : apparaître
    # d'un coup se lit comme une image sautée.
    bord = min(phase_cycle, SOUS_MARIN_TRAVERSEE_S - phase_cycle, 1.0)
    _colle(image, petit, int(cx - large / 2), int(milieu - haut / 2), bord)
    return True


# LE RELEVÉ DES BÂTIMENTS
# ----------------------
# Une fois toutes les dix-sept minutes quarante et une, pendant quatorze
# secondes : le temps qu'un trait fin fasse le tour de la bergerie, tienne un
# instant, et s'efface. Encore un nombre premier, pour la raison habituelle.
BATIMENT_PERIODE_S = 1061.0
BATIMENT_RELEVE_S = 14.0
# Le trait se dessine pendant la première moitié, tient, puis s'efface.
BATIMENT_TRACE = 0.45
BATIMENT_EFFACE = 0.80
BATIMENT_TRAIT = 2.0       # en pixels à 1600 de large : fin, comme demandé
BATIMENT_VOILE = 0.72
# Combien de bâtiments se relèvent à tour de rôle. Au-delà, on tombe dans des
# cabanes de quarante pixels dont le fil de fer est une tache de traits.
BATIMENT_COMBIEN = 5


def _aretes(bati: dict) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Toutes les arêtes du fil de fer, dans l'ordre où on les dessine.

    Le pied d'abord, puis les montants, puis le toit. C'est l'ordre dans
    lequel on relève un bâtiment et c'est aussi celui qui se lit le mieux :
    le contour au sol dit où il est posé, les montants le font sortir de
    terre, le toit le ferme.
    """
    pied = [tuple(p) for p in bati.get("foot") or []]
    toit = [tuple(p) for p in bati.get("roof") or []]
    if len(pied) < 3 or len(toit) != len(pied):
        return []
    aretes = [(pied[i], pied[(i + 1) % len(pied)]) for i in range(len(pied))]
    aretes += list(zip(pied, toit))
    aretes += [(toit[i], toit[(i + 1) % len(toit)]) for i in range(len(toit))]
    return aretes


def pose_batiments(image: np.ndarray, seconde: float, batis: list | None,
                   vue: tuple[int, int, int, int] | None = None,
                   nuit: bool = False) -> bool:
    """Le fil de fer d'un bâtiment se dessine sur le paysage, puis s'efface.

    Rien n'est dessiné à la main. OpenStreetMap connaît l'emprise au sol de la
    bergerie du Mont Serein ; la pose de la caméra et le modèle d'altitude
    savent où ça tombe dans l'image. On projette l'emprise deux fois, au sol
    et à la hauteur du toit, et on relie les coins. Sur une autre caméra dont
    on aura l'OSM local, la même recette rendra ses bâtiments à elle.

    Un bâtiment à la fois et un seul : relever trois maisons en même temps
    fait un plan d'architecte, en relever une fait un geste. Mais pas toujours
    le même — le tour suivant prend le suivant de la liste, et la liste va du
    plus large au plus étroit.

    ET PAS SEULEMENT DANS LA FENÊTRE CAMÉRA
    La caméra s'arrête au bord de sa fenêtre ; la projection, elle, continue.
    La bergerie finit hors du champ, à droite : son fil de fer sort de la
    fenêtre et se poursuit dans la bande noire, là où il n'y a rien à cacher.
    Et le hameau que la caméra rate d'un cheveu sur la gauche tombe lui aussi
    dans sa bande. Rien n'est déplacé pour l'occasion : chaque trait est à
    l'endroit où ce mur serait si la caméra voyait plus large. C'est la seule
    chose du flux qui montre ce qui est juste à côté du champ.

    Le trait ne reste pas. Un fil de fer permanent sur la seule construction
    du cadre finirait par ressembler à une cible, et rien de ce qu'on ajoute
    pour le plaisir n'a le droit de ressembler à une mesure. Il se dessine, il
    tient trois secondes, il s'en va.
    """
    if not batis:
        return False
    phase_cycle = en_scene("batiment", seconde, nuit)
    if phase_cycle is None:
        return False
    # Lequel : celui dont c'est le tour. Le numéro du tour se relit sur
    # l'horloge et ne se retient pas, pour que le flux puisse redémarrer sans
    # recommencer la liste.
    tour = int(seconde // (BATIMENT_PERIODE_S / (NUIT_PLUS_SOUVENT if nuit else 1.0)))
    aretes = _aretes(batis[tour % min(len(batis), BATIMENT_COMBIEN)])
    if not aretes:
        return False
    hauteur, largeur = image.shape[:2]
    gauche, cime, large_vue, haute_vue = vue or (0, 0, largeur, hauteur)
    echelle = largeur / 1600

    avance = phase_cycle / BATIMENT_RELEVE_S
    # Combien d'arêtes sont déjà tracées, et de combien la suivante est
    # entamée. Le trait avance arête par arête plutôt qu'au métré de la
    # longueur totale : un relevé se fait segment par segment, et la petite
    # hésitation à chaque coin est ce qui le fait ressembler à une main.
    part = min(1.0, avance / BATIMENT_TRACE)
    combien = part * len(aretes)

    def au_cadre(point) -> tuple[int, int]:
        return (int(gauche + point[0] * large_vue),
                int(cime + point[1] * haute_vue))

    calque = image.copy()
    trait = max(1, int(BATIMENT_TRAIT * echelle))
    for i, (a, b) in enumerate(aretes):
        fait = max(0.0, min(1.0, combien - i))
        if fait <= 0.0:
            continue
        debut, fin = au_cadre(a), au_cadre(b)
        if fait < 1.0:
            fin = (int(debut[0] + (fin[0] - debut[0]) * fait),
                   int(debut[1] + (fin[1] - debut[1]) * fait))
        # Doublé d'un liseré sombre comme les pantins, mais d'un pixel
        # seulement : à la largeur des membres d'un pantin, deux pixels de
        # noir de chaque côté ne se remarquent pas ; sur un trait de deux
        # pixels ils l'emportent, et le relevé se dessinait en noir.
        cv2.line(calque, debut, fin, (0, 0, 0), trait + 1, cv2.LINE_AA)
        cv2.line(calque, debut, fin, BLANC, trait, cv2.LINE_AA)

    # Entrée et sortie en fondu. La sortie est plus longue que l'entrée :
    # le trait se construit tout seul par le tracé, il n'a pas besoin qu'on
    # l'amène en plus, alors qu'une disparition nette ressemble à une image
    # sautée.
    if avance < BATIMENT_EFFACE:
        force = BATIMENT_VOILE
    else:
        reste = (1.0 - avance) / max(1e-6, 1.0 - BATIMENT_EFFACE)
        force = BATIMENT_VOILE * max(0.0, reste)
    cv2.addWeighted(calque, force, image, 1.0 - force, 0.0, dst=image)
    return True


# La descente : une fois toutes les treize minutes trois, et elle dure vingt
# secondes. Un nombre premier de plus, pour la raison habituelle.
PISTE_PERIODE_S = 787.0
PISTE_DESCENTE_S = 20.0

# La photo de la machine, en grand au milieu. Vingt-cinq minutes, un nombre
# premier, et sept secondes : assez pour voir que c'est un Raspberry Pi, pas
# assez pour oublier la montagne. Deux minutes de retard, le temps que
# YouTube ouvre l'image — plus tôt, on la montrerait à personne.
MACHINE_PERIODE_S = 2963.0
MACHINE_TENUE_S = 7.0
MACHINE_RETARD_S = 120.0
# Largeur de la photo, en part de la fenêtre caméra. Assez pour le ventilateur
# et les ports, pas un mur : la route reste visible autour.
MACHINE_PORTRAIT = 0.32
# Deux mots, rien derrière : un point ferait dire « dot » à la voix.
MACHINE_MERCI = "Thanks Raspberry!"

# Dogmazic, le même numéro : leur chien orange au milieu, et on les
# remercie. Moins souvent que le Raspberry, un autre premier, neuf minutes
# de retard pour ne pas tomber dessus au redémarrage.
DOGMAZIC_PERIODE_S = 3221.0
DOGMAZIC_TENUE_S = MACHINE_TENUE_S
DOGMAZIC_RETARD_S = 540.0
DOGMAZIC_PORTRAIT = MACHINE_PORTRAIT
DOGMAZIC_MERCI = "Thanks Dogmazic!"
# Deux lignes, sans photo : OpenCV voit le mouvement, YOLO11 le nomme.
# Moins souvent encore, et décalés pour ne pas parler en même temps.
OPENCV_PERIODE_S = 2477.0
OPENCV_TENUE_S = 5.0
OPENCV_RETARD_S = 900.0
OPENCV_MERCI = "Thanks OpenCV!"
YOLO_PERIODE_S = 2741.0
YOLO_TENUE_S = 5.0
YOLO_RETARD_S = 1500.0
YOLO_MERCI = "Thanks YOLO11!"

# Le plateau, maintenant que les numéros ont dit leur période et leur
# durée. L'ordre départage les ex æquo : le tapis d'abord parce qu'il passe
# au-dessus de tout et ne cache rien, l'éléphant parce qu'il occupe l'écran
# entier, la machine ensuite — un disque au milieu cède le passage à un
# éléphant rose, pas l'inverse.
PLATEAU = (
    ("tapis", TAPIS_PERIODE_S, TAPIS_TRAVERSEE_S, 0.0),
    ("sous-marin", SOUS_MARIN_PERIODE_S, SOUS_MARIN_TRAVERSEE_S, 0.0),
    ("piste", PISTE_PERIODE_S, PISTE_DESCENTE_S, 0.0),
    ("elephant", ELEPHANT_PERIODE_S, ELEPHANT_TENUE_S, 0.0),
    ("batiment", BATIMENT_PERIODE_S, BATIMENT_RELEVE_S, 0.0),
    ("machine", MACHINE_PERIODE_S, MACHINE_TENUE_S, MACHINE_RETARD_S),
    ("dogmazic", DOGMAZIC_PERIODE_S, DOGMAZIC_TENUE_S, DOGMAZIC_RETARD_S),
    ("opencv", OPENCV_PERIODE_S, OPENCV_TENUE_S, OPENCV_RETARD_S),
    ("yolo", YOLO_PERIODE_S, YOLO_TENUE_S, YOLO_RETARD_S),
    # L'ours en dernier parce qu'il écrit en travers du ciel, et qu'il vaut
    # mieux qu'il cède le passage plutôt que de crier par-dessus le tapis.
    #
    # Et avec quatre-vingt-dix secondes de retard, le seul du plateau qui en
    # ait. Les autres reviennent entre six et quinze minutes : qu'ils ratent
    # leur tour de l'instant zéro ne se voit pas. Lui revient toutes les deux
    # heures et quart, et sans ce retard on déployait l'ours à midi sans
    # pouvoir le regarder avant le milieu de l'après-midi. Quatre-vingt-dix
    # secondes, c'est le temps qu'il faut à YouTube pour que l'image arrive —
    # plus tôt, il danserait pour personne.
    ("ours", OURS_PERIODE_S, OURS_TENUE_S, OURS_RETARD_S),
)
# Ce que le surfeur fait de large : il louvoie de part et d'autre du tracé,
# comme on descend vraiment, et jamais tout droit. En parts de sa taille.
PISTE_LOUVOIE = 2.6
PISTE_VIRAGES = 5.0
# Sa taille, en parts de la hauteur de la vue. Plus petit que les pantins du
# bas : il est au loin, sur la montagne.
PISTE_HAUT = 0.085
PISTE_NEIGE = (248, 250, 252)
PISTE_PLANCHE = (64, 196, 248)


def _longueur_du_trace(trace: list) -> float:
    """La longueur du tracé à l'écran, en parts de cadre."""
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(trace, trace[1:]))


def _le_long(trace: list, part: float) -> tuple[float, float, float]:
    """Où l'on est sur le tracé, et dans quelle direction il va.

    Mesuré à la longueur parcourue et non au numéro du point : les points
    d'OpenStreetMap sont serrés dans les virages et espacés dans les lignes
    droites, et un surfeur qui avance d'un point par image accélère dans les
    lignes droites et s'arrête dans les virages — ce qui est l'inverse.
    """
    pas = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(trace, trace[1:])]
    total = _longueur_du_trace(trace) or 1.0
    vise = max(0.0, min(1.0, part)) * total
    courus = 0.0
    for i, long_pas in enumerate(pas):
        if courus + long_pas >= vise or i == len(pas) - 1:
            dedans = (vise - courus) / (long_pas or 1.0)
            a, b = trace[i], trace[i + 1]
            return (a[0] + (b[0] - a[0]) * dedans,
                    a[1] + (b[1] - a[1]) * dedans,
                    math.atan2(b[1] - a[1], b[0] - a[0]))
        courus += long_pas
    return trace[-1][0], trace[-1][1], 0.0


def _surfeur(calque: np.ndarray, x: int, y: int, taille: float, phase: float,
             penche: float) -> None:
    """Le pantin des coins, sur une planche et couché dans le virage.

    Le même dessin, littéralement : il avait son propre bonhomme, fait de
    traits droits avec une tête pleine, et à côté des trois autres il n'était
    pas le même personnage. C'était pourtant l'idée — celui du tapis volant
    est déjà celui du bas parti faire un tour en l'air, et celui-ci devait
    être le même parti faire du surf.

    Il est donc dessiné debout dans un carré, planche comprise, et le carré
    tourne. L'inclinaison vient du virage et n'est pas une animation à part :
    on ne tourne pas sans se coucher, c'est pour ça qu'elle tombe juste.
    """
    cote = max(8, int(taille * 2.6))
    pieds = int(cote * 0.78)
    bout = np.zeros((cote, cote, 3), np.uint8)
    _danseur(bout, cote // 2, pieds, taille, phase, BLANC)
    planche = max(2, int(taille * 0.12))
    cv2.line(bout, (int(cote / 2 - taille * 0.55), pieds),
             (int(cote / 2 + taille * 0.55), pieds), (0, 0, 0),
             planche + 3, cv2.LINE_AA)
    cv2.line(bout, (int(cote / 2 - taille * 0.55), pieds),
             (int(cote / 2 + taille * 0.55), pieds), PISTE_PLANCHE,
             planche, cv2.LINE_AA)
    tourne = cv2.getRotationMatrix2D((cote / 2, pieds), math.degrees(penche), 1.0)
    bout = cv2.warpAffine(bout, tourne, (cote, cote), flags=cv2.INTER_LINEAR)

    x0, y0 = int(x - cote / 2), int(y - pieds)
    hauteur, largeur = calque.shape[:2]
    gx0, gy0 = max(0, x0), max(0, y0)
    gx1, gy1 = min(largeur, x0 + cote), min(hauteur, y0 + cote)
    if gx0 >= gx1 or gy0 >= gy1:
        return
    morceau = bout[gy0 - y0:gy1 - y0, gx0 - x0:gx1 - x0]
    zone = calque[gy0:gy1, gx0:gx1]
    dessine = morceau.any(axis=2)
    zone[dessine] = morceau[dessine]


def pose_piste(image: np.ndarray, seconde: float, trace: list | None,
               vue: tuple[int, int, int, int] | None = None,
               nuit: bool = False) -> bool:
    """Quelqu'un descend la piste de ski, et la piste s'allume derrière lui.

    Le tracé n'est pas dessiné à la main : c'est la piste « André Philip » du
    Mont Serein, telle qu'OpenStreetMap la connaît, projetée dans l'image par
    la pose de la caméra et l'altitude du terrain. Elle est donc là où elle
    est vraiment, et sur une autre caméra dont on aura l'OSM local elle sera
    là où la sienne est vraiment, sans qu'on règle un pixel.

    Le trait blanc n'apparaît pas d'un coup : il se dessine derrière le
    surfeur et s'efface devant lui. Un tracé allumé d'avance dirait « voilà où
    il va passer », ce qui n'est pas une surprise, et un tracé qui reste
    allumé après son passage ferait une ligne blanche permanente en travers de
    la montagne — ce qui est exactement ce qu'on ne veut pas poser sur ce que
    les gens regardent.

    Il louvoie. Personne ne descend une piste en ligne droite, et un surfeur
    qui suivrait le tracé d'OpenStreetMap au millimètre aurait l'air d'un
    curseur qui glisse, pas de quelqu'un qui surfe.
    """
    if not trace or len(trace) < 2:
        return False
    phase_cycle = en_scene("piste", seconde, nuit)
    if phase_cycle is None:
        return False
    hauteur, largeur = image.shape[:2]
    gauche, cime, large_vue, haute_vue = vue or (0, 0, largeur, hauteur)
    avance = phase_cycle / PISTE_DESCENTE_S
    taille = haute_vue * PISTE_HAUT
    if taille < 8:
        return False

    def au_cadre(part: float) -> tuple[float, float, float]:
        x, y, cap = _le_long(trace, part)
        return gauche + x * large_vue, cime + y * haute_vue, cap

    calque = image.copy()
    # Le trait : de l'endroit qu'il vient de quitter à celui qu'il va
    # atteindre, et il s'efface vers l'arrière.
    #
    # Il s'efface, il ne s'assombrit pas. En peignant chaque morceau d'un
    # blanc de plus en plus faible, la queue de la traînée finissait en noir
    # — une barre sombre en travers de la forêt, soit exactement l'inverse de
    # ce qu'on voulait. Le dégradé doit porter sur la transparence, donc la
    # traînée se peint à part et se mélange ensuite.
    trainee = np.zeros_like(calque)
    voile = np.zeros(calque.shape[:2], np.float32)
    queue = max(0.0, avance - 0.22)
    nez = min(1.0, avance + 0.05)
    morceaux = 14
    epais = max(1, int(taille * 0.16))
    for pas in range(morceaux):
        de = queue + (nez - queue) * pas / morceaux
        a = queue + (nez - queue) * (pas + 1) / morceaux
        x0, y0, _ = au_cadre(de)
        x1, y1, _ = au_cadre(a)
        bout = ((int(x0), int(y0)), (int(x1), int(y1)))
        cv2.line(trainee, *bout, PISTE_NEIGE, epais, cv2.LINE_AA)
        cv2.line(voile, *bout, float((pas / morceaux) ** 0.7), epais, cv2.LINE_AA)
    masque = voile[:, :, None]
    calque[:] = (trainee * masque + calque * (1.0 - masque)).astype(np.uint8)

    x, y, _cap = au_cadre(avance)
    # Il louvoie en travers et jamais perpendiculairement au tracé. Vu d'ici,
    # le versant est presque de profil : la perpendiculaire au tracé est donc
    # presque verticale, et un louvoiement porté dessus le faisait remonter la
    # piste à chaque virage. On traverse une piste, on ne la remonte pas.
    balance = math.sin(avance * math.pi * 2 * PISTE_VIRAGES)
    x += balance * taille * PISTE_LOUVOIE * 0.5
    # Et c'est ce louvoiement qui décide de son inclinaison : il se couche du
    # côté où il tourne, ce qui est la seule chose qui distingue quelqu'un qui
    # surfe de quelqu'un qui est debout.
    penche = -math.cos(avance * math.pi * 2 * PISTE_VIRAGES) * 0.45
    _surfeur(calque, int(x), int(y - taille * 0.1), taille,
             seconde * DANSE_PAS_S, penche)
    # Il arrive et repart en fondu d'une seconde.
    bord = min(phase_cycle, PISTE_DESCENTE_S - phase_cycle, 1.0)
    cv2.addWeighted(calque, bord * 0.92, image, 1.0 - bord * 0.92, 0.0, dst=image)
    return True


LAMPADAIRE_M = 7.0
# Le fer est froid, la lumière est chaude : c'est tout ce qu'il faut pour
# qu'une lampe ait l'air allumée.
LAMP_FER = (104, 96, 108)
# De combien on remonte la vraie lueur au plus près de l'ampoule. Un facteur
# et non une couleur : on amplifie ce qui est là, on n'ajoute rien.
LAMP_GAIN = 0.85


def hampe_du_lampadaire(camera: dict, distance_m: float, rapport: float) -> float:
    """La longueur du mât à l'image, en parts de hauteur, d'après sa vraie taille.

    Sept mètres à vingt-cinq, vus par un objectif dont on connaît l'ouverture :
    la longueur n'est pas réglée à l'œil, elle est calculée. C'est ce qui
    permettra de poser le même dessin sur le lampadaire d'une autre caméra,
    plus loin ou plus près, sans retoucher un chiffre.
    """
    champ = math.radians(float(camera.get("fov") or 90.0))
    vertical = 2 * math.atan(math.tan(champ / 2) * rapport)
    return (LAMPADAIRE_M / max(distance_m, 1.0)) / (2 * math.tan(vertical / 2))


def pose_lampadaire(image: np.ndarray, tete: tuple[float, float],
                    epaule: tuple[float, float], pied: tuple[float, float],
                    seconde: float, allume: bool = False) -> None:
    """Un lampadaire de livre d'images, posé sur le vrai.

    Sur le vrai et non à côté : sa lanterne tombe sur l'ampoule qu'OpenStreetMap
    place là, et son mât descend le long du vrai poteau jusqu'à son pied. C'est
    la différence entre recouvrir un objet et coller un autocollant à côté — et
    au premier essai, le mât descendait tout droit depuis la lanterne pendant
    que le vrai poteau penchait, si bien qu'on voyait les deux.

    Trois points et non deux : le pied et l'épaule du poteau, mesurés sur
    l'image et notés dans `scene.json`, et la lanterne, qui vient de la carte.
    Le mât va du pied à l'épaule, la potence de l'épaule à la lanterne. Avec
    deux points seulement, le mât prenait la direction pied-lanterne, qui
    comprend le déport de la potence : il penchait deux fois trop et le vrai
    poteau ressortait de l'autre côté. Une caméra qui n'a pas mesuré son
    poteau n'a pas de lampadaire dessiné, ce qui vaut mieux qu'un mât de
    travers.

    Il ne sort que la nuit, parce que c'est la nuit que la vraie lampe est
    allumée. Dessiner une lampe éteinte en train d'éclairer serait le genre de
    petit mensonge dont ce flux n'a pas besoin.

    Sur la webcam, sa lueur n'est pas dessinée : elle est vraie, et on
    l'amplifie. La lampe est allumée pour de bon et sa lumière est dans les
    pixels. Sur la maquette de nuit, il n'y a pas d'ampoule : « allume » peint
    alors une lueur chaude, sinon le lampadaire resterait éteint sur un rendu
    de jour qu'on a seulement baissé.

    Et le souffle est lent. Pas de scintillement : une lampe qui clignote se
    lit comme une panne.
    """
    hauteur, largeur = image.shape[:2]
    x, y = int(tete[0] * largeur), int(tete[1] * hauteur)
    bas_x, bas_y = int(pied[0] * largeur), int(pied[1] * hauteur)
    haut_x, haut_y = int(epaule[0] * largeur), int(epaule[1] * hauteur)
    long_px = max(8, int(math.hypot(bas_x - haut_x, bas_y - haut_y)))
    fer = max(2, int(long_px * 0.022))
    lanterne = max(4, int(long_px * 0.055))
    souffle = 0.88 + 0.12 * math.sin(seconde * 0.5)

    # Sur la webcam, pas de halo inventé. La lampe est vraiment allumée et
    # sa lueur est dans les pixels : on l'amplifie. Multiplier et non
    # ajouter : un fond noir reste noir.
    #
    # Sur la maquette, le rendu n'a pas d'ampoule. Ajouter une lueur chaude
    # est le seul moyen qu'elle soit allumée une fois le soleil du modèle
    # baissé.
    autour = max(8, int(lanterne * (7 if allume else 5) * souffle))
    x0, y0 = max(0, x - autour), max(0, y - autour)
    x1, y1 = min(largeur, x + autour), min(hauteur, y + autour)
    if x1 > x0 and y1 > y0:
        zone = image[y0:y1, x0:x1].astype(np.float32)
        maille_y, maille_x = np.mgrid[y0:y1, x0:x1]
        loin = np.hypot(maille_x - x, maille_y - y) / autour
        pres = np.clip(1.0 - loin, 0.0, 1.0) ** 2
        if allume:
            chaud = np.array(AMBRE, np.float32) * (0.92 * souffle)
            image[y0:y1, x0:x1] = np.clip(
                zone + chaud * pres[:, :, None], 0, 255).astype(np.uint8)
        else:
            gain = 1.0 + LAMP_GAIN * pres
            image[y0:y1, x0:x1] = np.clip(
                zone * gain[:, :, None], 0, 255).astype(np.uint8)
    calque = image.copy()

    # Le mât, qui s'épaissit vers le bas comme tous les mâts dessinés, et qui
    # suit l'axe du vrai poteau au lieu de tomber à la verticale.
    for part in range(6):
        depuis = (int(haut_x + (bas_x - haut_x) * part / 6),
                  int(haut_y + (bas_y - haut_y) * part / 6))
        jusqua = (int(haut_x + (bas_x - haut_x) * (part + 1) / 6),
                  int(haut_y + (bas_y - haut_y) * (part + 1) / 6))
        epais = fer + int(fer * 0.5 * part / 5)
        cv2.line(calque, depuis, jusqua, (46, 42, 52), epais + 1, cv2.LINE_AA)
        cv2.line(calque, depuis, jusqua, LAMP_FER, epais, cv2.LINE_AA)
        # Une arête claire sur le côté éclairé, qui donne du tube au trait.
        cv2.line(calque, (depuis[0] - epais // 3, depuis[1]),
                 (jusqua[0] - epais // 3, jusqua[1]),
                 (152, 146, 156), max(1, epais // 3), cv2.LINE_AA)
    # Un socle, pour qu'il soit planté et non suspendu.
    cv2.ellipse(calque, (bas_x, bas_y), (fer * 3, max(2, fer)), 0, 180, 360,
                LAMP_FER, -1, cv2.LINE_AA)
    # La potence, du haut du poteau à la lanterne : une courbe et non un trait,
    # parce que c'est ce qui fait la différence entre un lampadaire de livre
    # d'images et une perche avec une ampoule au bout.
    potence = np.int32([[haut_x, haut_y],
                        [haut_x, haut_y - lanterne * 2],
                        [x, y - lanterne * 2],
                        [x, y + lanterne]])
    cv2.polylines(calque, [_courbe(potence)], False, (40, 36, 44),
                  fer + 2, cv2.LINE_AA)
    cv2.polylines(calque, [_courbe(potence)], False, LAMP_FER, fer, cv2.LINE_AA)
    # Deux volutes de ferronnerie, qui ne servent à rien et font tout.
    for cote in (-1, 1):
        cv2.ellipse(calque, (haut_x + cote * lanterne, haut_y + int(lanterne * 1.6)),
                    (lanterne, int(lanterne * 1.1)),
                    0, 180 if cote < 0 else 0, 270 if cote < 0 else 90,
                    LAMP_FER, max(2, fer - 1), cv2.LINE_AA)

    # La lanterne : un tronc de cône, un chapeau, une petite flèche au-dessus.
    verre = np.int32([[x - lanterne, y + lanterne],
                      [x + lanterne, y + lanterne],
                      [x + int(lanterne * 0.62), y - int(lanterne * 0.5)],
                      [x - int(lanterne * 0.62), y - int(lanterne * 0.5)]])
    # Sur la webcam le verre reste vide : la vraie ampoule est derrière.
    # Sur la maquette il n'y a rien derrière, donc le verre porte la lumière.
    if allume:
        cv2.fillPoly(calque, [verre], (150, 220, 255), cv2.LINE_AA)
    cv2.polylines(calque, [verre], True, LAMP_FER, max(2, fer - 1), cv2.LINE_AA)
    chapeau = np.int32([[x - int(lanterne * 1.25), y - int(lanterne * 0.5)],
                        [x + int(lanterne * 1.25), y - int(lanterne * 0.5)],
                        [x, y - int(lanterne * 1.45)]])
    cv2.fillPoly(calque, [chapeau], LAMP_FER, cv2.LINE_AA)
    cv2.line(calque, (x, y - int(lanterne * 1.45)), (x, y - int(lanterne * 2.0)),
             LAMP_FER, max(2, fer - 1), cv2.LINE_AA)
    cv2.circle(calque, (x, y - int(lanterne * 2.1)), max(2, fer), LAMP_FER, -1, cv2.LINE_AA)
    cv2.addWeighted(calque, 0.80, image, 0.20, 0.0, dst=image)


def _courbe(points: np.ndarray, pas: int = 18) -> np.ndarray:
    """Une Bézier cubique en quelques segments, pour la potence."""
    p0, p1, p2, p3 = points.astype(np.float64)
    t = np.linspace(0.0, 1.0, pas).reshape(-1, 1)
    trace = ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1
             + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3)
    return trace.astype(np.int32)


def _tapis(calque: np.ndarray, cx: int, cy: int, etoffe: float,
           phase: float, danseur: float = 0.0,
           clair: tuple[int, int, int] = BLANC) -> None:
    """Le tapis lui-même : une étoffe qui ondule, et quelqu'un debout dessus.

    L'ondulation court d'un bout à l'autre au lieu de monter et descendre
    ensemble : c'est ce qui fait la différence entre un tapis qui vole et une
    planche qui glisse. Le danseur suit la bosse sous ses pieds, sinon il
    flotte un peu au-dessus et tout l'effet tombe.
    """
    long_tapis = etoffe * 3.4
    def onde(part):
        return math.sin(part * 4.5 - phase * 1.4) * etoffe * 0.17

    haut, bas = [], []
    for pas in range(13):
        part = pas / 12
        x = int(cx - long_tapis / 2 + part * long_tapis)
        y = int(cy + onde(part))
        haut.append((x, y))
        bas.append((x, int(y + etoffe * 0.30)))
    corps = np.array(haut + bas[::-1], np.int32)
    cv2.fillPoly(calque, [corps], TAPIS_ETOFFE, cv2.LINE_AA)
    cv2.polylines(calque, [np.array(haut, np.int32)], False, TAPIS_FRANGE,
                  max(1, int(etoffe * 0.05)), cv2.LINE_AA)
    # Les franges aux deux bouts, qui traînent derrière.
    for bout, sens in ((haut[0], -1), (haut[-1], 1)):
        for brin in range(4):
            pied = (int(bout[0] + sens * etoffe * 0.16),
                    int(bout[1] + etoffe * (0.26 + brin * 0.07)))
            cv2.line(calque, (bout[0], int(bout[1] + etoffe * 0.1)), pied,
                     TAPIS_FRANGE, max(1, int(etoffe * 0.04)), cv2.LINE_AA)
    # Deux losanges pour le motif, et pas plus : à cette taille, un vrai tapis
    # d'orient ne serait qu'une bouillie de pixels.
    for part in (0.33, 0.67):
        centre = (int(cx - long_tapis / 2 + part * long_tapis),
                  int(cy + onde(part) + etoffe * 0.11))
        cote = int(etoffe * 0.09)
        cv2.fillPoly(calque, [np.array(
            [(centre[0], centre[1] - cote), (centre[0] + cote, centre[1]),
             (centre[0], centre[1] + cote), (centre[0] - cote, centre[1])],
            np.int32)], TAPIS_FRANGE, cv2.LINE_AA)
    # Debout au milieu du tapis, à la taille des deux autres : c'est le même
    # bonhomme, parti faire un tour en l'air. Il était calculé sur la largeur
    # de l'étoffe, donc plus petit qu'eux, et il se lisait comme un troisième
    # personnage plutôt que comme un des trois.
    _danseur(calque, cx, int(cy + onde(0.5)), danseur or etoffe * 1.5,
             phase + 1.1, clair)


# Les ciels où le soleil ne passe pas. « Peu nuageux » n'en est pas un.
SANS_SOLEIL = {"nuageux", "couvert", "brouillard", "brume", "pluie", "neige", "orage"}
# Il doit être assez haut pour être dans le ciel et non derrière la crête, et
# assez loin du bord pour tenir entier dans l'image.
SOLEIL_HAUT_MIN = 3.0
SOLEIL_CIEL = 0.45
# Le coin du ciel, pour les heures où le vrai soleil ne tient pas dans le cadre.
SOLEIL_COIN = 0.13
SOLEIL_COIN_HAUT = 0.19
SOLEIL_TAILLE = 0.085
SOLEIL_JAUNE = (70, 205, 248)
RAYONS = 11


def charge_relief(racine: Path, camera: dict):
    """Le modèle de terrain, s'il est là. Le flux s'en passe s'il ne l'est pas.

    Le direct n'a pas le droit de s'arrêter parce qu'un fichier manque : sans
    relief, on perd l'heure de l'ombre et rien d'autre.
    """
    chemin = racine / "data" / "osm" / "terrain.json"
    if not chemin.is_file():
        return None
    try:
        from watcher.terrain import Terrain

        return Terrain(float(camera["lat"]), float(camera["lon"]),
                       2500.0, cache=chemin)
    except Exception:
        log.warning("Relief illisible : pas d'heure d'ombre", exc_info=True)
        return None


def soleil_absent(terrain, camera: dict, quand: float, temps: str) -> bool:
    """Le soleil manque-t-il à la scène, à cette heure et par ce temps ?

    Deux façons de manquer, et la première ne se lit sur aucun bulletin : être
    levé mais encore derrière la montagne. Le premier octobre, le soleil passe
    l'horizon à sept heures trente-cinq et ne franchit la crête du Ventoux qu'à
    huit heures et demie ; entre les deux le ciel est clair, la météo dit
    « dégagé », et le versant nord est dans le noir. C'est exactement l'heure
    où il a été dit, en regardant l'écran, « pas encore de soleil ».

    La crête est prise dans notre propre modèle de terrain, celui qui sert déjà
    à poser les boîtes à la bonne distance. Aucune mesure nouvelle, aucun
    service à interroger, et la même fonction donnera l'heure de l'ombre sur
    n'importe quelle autre caméra dont on aura le relief.

    La seconde façon est banale : sous les nuages, il n'y est pour personne.
    """
    if temps in SANS_SOLEIL:
        return True
    if terrain is None:
        return False
    from watcher.scene import solar_azimuth, solar_elevation

    moment = datetime.fromtimestamp(quand, timezone.utc)
    haut = solar_elevation(moment, camera["lat"], camera["lon"])
    azimut = solar_azimuth(moment, camera["lat"], camera["lon"])
    return haut < terrain.skyline(azimut, float(camera.get("ele") or 0.0))


def ou_est_le_soleil(camera: dict, quand: float, rapport: float) -> tuple[float, float] | None:
    """Où le soleil se trouve dans l'image, en parts de largeur et de hauteur.

    Rien n'est lu ni deviné : l'azimut et la hauteur viennent du calcul solaire,
    l'orientation et l'ouverture de l'objectif viennent de la fiche de la
    caméra. La même fonction posera le soleil au bon endroit sur n'importe
    quelle autre webcam dont on connaît le cap et le champ.

    Il n'y a pas toujours de place : avec quatre-vingt-dix degrés d'ouverture
    et ce cap, le vrai soleil ne traverse le ciel du cadre qu'entre neuf heures
    et dix heures et demie en octobre. Le reste du temps il est trop haut, ou
    derrière l'épaule. On le dessine quand même, dans le coin du ciel et du
    côté où il se trouve vraiment — c'est exactement là qu'un enfant le met, et
    personne n'a jamais pris un soleil au crayon pour une mesure. Ce qui reste
    vrai dans ce cas, et c'est le seul engagement qu'on tienne, c'est le côté.
    """
    # Importé ici et pas en tête de fichier : c'est main() qui pose la racine
    # du dépôt sur le chemin, et stream.py doit pouvoir être lancé comme un
    # script depuis n'importe où.
    from watcher.scene import solar_azimuth, solar_elevation

    moment = datetime.fromtimestamp(quand, timezone.utc)
    haut = solar_elevation(moment, camera["lat"], camera["lon"])
    if haut < SOLEIL_HAUT_MIN:
        return None
    return _ou_dans_le_ciel(camera, solar_azimuth(moment, camera["lat"], camera["lon"]),
                            haut, rapport, SOLEIL_COIN, SOLEIL_COIN_HAUT, SOLEIL_CIEL)


def _ou_dans_le_ciel(camera: dict, azimut: float, haut: float, rapport: float,
                     coin_x: float, coin_haut: float,
                     plafond: float) -> tuple[float, float]:
    """Où un astre tombe dans l'image, d'après son azimut et sa hauteur.

    La même projection pour n'importe quel astre, parce que c'est le même
    ciel et le même objectif. Elle ne dépend que du cap, de l'ouverture et du
    piqué de la caméra : elle posera n'importe quel astre au bon endroit sur
    n'importe quelle autre webcam dont on connaît la fiche.
    """
    champ = float(camera.get("fov") or 90.0)
    ecart = (azimut - float(camera.get("bearing") or 0.0) + 180.0) % 360.0 - 180.0
    coin = (coin_x if ecart < 0 else 1.0 - coin_x, coin_haut)
    if abs(ecart) > champ / 2 - 4:
        return coin
    # Projection rectilinéaire : c'est une tangente et non une règle de trois,
    # sinon l'astre dérive d'un bon dixième d'image vers les bords.
    demi = math.tan(math.radians(champ / 2))
    x = 0.5 + math.tan(math.radians(ecart)) / (2 * demi)
    y = 0.5 - math.tan(math.radians(haut - float(camera.get("pitch") or 0.0))) / (2 * demi * rapport)
    # Plus bas que la moitié de l'image, ce n'est plus le ciel, c'est la
    # montagne : un astre planté dans un versant est un dessin faux, pas un
    # dessin d'enfant.
    if not 0.08 < x < 0.92 or not 0.06 < y < plafond:
        return coin
    return x, y


def _rond_tremble(centre: tuple[int, int], rayon: float, phase: float) -> np.ndarray:
    """Un cercle qui n'en est pas un : la main d'un enfant ne ferme pas juste."""
    angles = np.linspace(0, 2 * math.pi, 48, dtype=np.float32)
    bosse = 1.0 + 0.055 * np.sin(3 * angles + phase) + 0.035 * np.sin(5 * angles - phase * 0.7)
    points = np.stack([centre[0] + np.cos(angles) * rayon * bosse,
                       centre[1] + np.sin(angles) * rayon * bosse], axis=1)
    return points.astype(np.int32)


def pose_soleil_dessine(image: np.ndarray, ou: tuple[float, float], seconde: float) -> None:
    """Le soleil qui manque, dessiné comme à cinq ans : rond, rayons, sourire.

    Rien de ce qui est à l'écran ne prétend qu'il fait beau — le bandeau dit
    « overcast », et il a raison. Le dessin dit autre chose : qu'il est là
    quand même, et où. C'est la seule chose du flux qui console au lieu de
    constater, et elle a le droit d'être maladroite.

    Elle respire lentement, à un tour en dix secondes environ, parce qu'un
    dessin parfaitement immobile sur une image presque immobile ressemble à un
    défaut d'affichage.
    """
    hauteur, largeur = image.shape[:2]
    rayon = hauteur * SOLEIL_TAILLE
    centre = (int(ou[0] * largeur), int(ou[1] * hauteur))
    phase = seconde * 0.6
    trait = max(2, int(rayon * 0.11))
    ourlet = trait + max(2, trait // 2)
    calque = image.copy()

    def crayon(trace, ferme=False):
        cv2.polylines(calque, [trace], ferme, (40, 40, 40), ourlet, cv2.LINE_AA)
        cv2.polylines(calque, [trace], ferme, SOLEIL_JAUNE, trait, cv2.LINE_AA)

    for i in range(RAYONS):
        angle = 2 * math.pi * i / RAYONS + phase * 0.12
        # Des rayons inégaux, et qui ne partent pas tous du même cercle : un
        # soleil dont les rayons sont réguliers est un logo, pas un dessin.
        depuis = rayon * (1.22 + 0.06 * math.sin(i * 2.3))
        jusqua = rayon * (1.62 + 0.26 * math.sin(i * 1.7 + phase))
        crayon(np.int32([[centre[0] + math.cos(angle) * depuis,
                          centre[1] + math.sin(angle) * depuis],
                         [centre[0] + math.cos(angle) * jusqua,
                          centre[1] + math.sin(angle) * jusqua]]))
    crayon(_rond_tremble(centre, rayon, phase), ferme=True)

    oeil = max(2, int(rayon * 0.13))
    for cote in (-1, 1):
        yeux = (int(centre[0] + cote * rayon * 0.34), int(centre[1] - rayon * 0.26))
        cv2.circle(calque, yeux, oeil + 2, (40, 40, 40), -1, cv2.LINE_AA)
        cv2.circle(calque, yeux, oeil, SOLEIL_JAUNE, -1, cv2.LINE_AA)
    bouche = np.int32([[centre[0] + math.cos(a) * rayon * 0.48,
                        centre[1] + math.sin(a) * rayon * 0.48 + rayon * 0.08]
                       for a in np.linspace(0.45, math.pi - 0.45, 12)])
    crayon(bouche)

    # Posé par transparence : il est dans le ciel du dessin, pas collé sur la
    # vitre. À moitié, pour qu'on voie toujours le temps qu'il fait derrière.
    cv2.addWeighted(calque, 0.62, image, 0.38, 0.0, dst=image)


def pose_attrape(image: np.ndarray, age: float, nom: str = "") -> None:
    """« GOOD CATCH » en vert, avec un éclair qui retombe, et ce qu'on a pris.

    Le nom sous le mot, parce que « good catch » tout seul félicite sans dire
    de quoi. Le rectangle le porte déjà, mais il est petit, il est au bord, et
    pendant une seconde et demie l'œil est au milieu de l'écran, pas sur lui.

    Vert et non ambre : le mot de l'ennui et celui de la réussite ne doivent
    pas se ressembler, sinon le flux a l'air de dire la même chose tout le
    temps. L'éclair décroît en une demi-seconde — une lumière qui reste n'est
    plus un éclair, c'est un voile.
    """
    if age < 0 or age > ATTRAPE_S:
        return
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    eclat = max(0.0, 1.0 - age / 0.45)
    if eclat > 0.01:
        cv2.addWeighted(image, 1.0, np.full_like(image, 255), 0.22 * eclat, 0.0, dst=image)
    # Le mot monte un peu pendant qu'il s'efface : c'est ce qui le détache du
    # fond sans avoir à l'écrire plus gros.
    avance = age / ATTRAPE_S
    taille = 2.2 * echelle
    epaisseur = max(2, int(6 * echelle))
    (large, haut), _ = cv2.getTextSize("GOOD CATCH!", cv2.FONT_HERSHEY_DUPLEX, taille, epaisseur)
    x = (largeur - large) // 2
    y = int(hauteur * 0.42 + haut / 2 - 70 * echelle * avance)
    calque = image.copy()
    # Un liseré noir d'abord : le vert seul disparaît sur un ciel de brouillard,
    # et c'est exactement le fond qu'on a la moitié du temps ici.
    cv2.putText(calque, "GOOD CATCH!", (x, y), cv2.FONT_HERSHEY_DUPLEX, taille,
                (0, 0, 0), epaisseur + max(3, int(7 * echelle)), cv2.LINE_AA)
    cv2.putText(calque, "GOOD CATCH!", (x, y), cv2.FONT_HERSHEY_DUPLEX, taille,
                VERT, epaisseur, cv2.LINE_AA)
    if nom:
        petite = taille * 0.48
        fin = max(2, int(epaisseur * 0.55))
        (court, _), _ = cv2.getTextSize(nom, cv2.FONT_HERSHEY_DUPLEX, petite, fin)
        bas = y + int(haut * 0.95)
        cv2.putText(calque, nom, ((largeur - court) // 2, bas),
                    cv2.FONT_HERSHEY_DUPLEX, petite, (0, 0, 0),
                    fin + max(3, int(6 * echelle)), cv2.LINE_AA)
        cv2.putText(calque, nom, ((largeur - court) // 2, bas),
                    cv2.FONT_HERSHEY_DUPLEX, petite, BLANC, fin, cv2.LINE_AA)
    force = max(0.0, 1.0 - avance ** 2)
    cv2.addWeighted(calque, force, image, 1.0 - force, 0.0, dst=image)
    pose_confettis(image, age, ATTRAPE_S)


# Petits rectangles, pas le rouge du direct : le rouge dit « en ce moment »,
# les confettis disent « on a nommé ». Quarante, assez pour une averse,
# pas assez pour cacher celui qu'on vient d'attraper.
_CONFETTIS = (
    VERT, CYAN, AMBRE, BLANC, (210, 180, 120), (180, 220, 160),
)


def pose_confettis(image: np.ndarray, age: float, duree: float) -> None:
    """Une averse courte, la même d'une image à l'autre.

    Les positions se calculent : un tirage au sort redessinerait l'averse
    à chaque image et elle clignoterait. Chaque confetti a un retard, une
    colonne et une vitesse, et il tombe le temps du good catch.
    """
    if age < 0 or age > duree or duree <= 0:
        return
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    for i in range(42):
        retard = (i % 7) * 0.05
        temps = age - retard
        if temps < 0:
            continue
        part = temps / duree
        if part > 1:
            continue
        x = int((i * 137 + 29) % max(1, largeur))
        vitesse = 0.75 + (i % 5) * 0.08
        y = int(-12 * echelle + part * vitesse * (hauteur + 24 * echelle))
        if y < -8 or y >= hauteur:
            continue
        teinte = _CONFETTIS[i % len(_CONFETTIS)]
        long = max(3, int((5 + i % 4) * echelle))
        epais = max(2, int(2 * echelle))
        penche = -1 if i % 2 else 1
        x2 = x + penche * long
        y2 = y + long
        if 0 <= x2 < largeur and 0 <= y2 < hauteur:
            cv2.line(image, (x, y), (x2, y2), teinte, epais, cv2.LINE_AA)


def pose_ennui(image: np.ndarray, mot: str, seconde: float) -> None:
    """Le mot en très grand, en travers de la fenêtre caméra.

    Écrit tant que la voix parle et pas une image de plus : le texte et le son
    sortent du même compteur d'octets, donc ils ne peuvent pas se décaler.

    Il penche et il tremble. Un mot posé droit au milieu d'une webcam ressemble
    à un message d'erreur ; penché de quelques degrés, il ressemble à ce qu'il
    est, c'est-à-dire à quelqu'un qui s'ennuie.
    """
    if not mot:
        return
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    taille = 3.4 * echelle
    epaisseur = max(2, int(9 * echelle))
    (large, haut), _ = cv2.getTextSize(mot, cv2.FONT_HERSHEY_DUPLEX, taille, epaisseur)
    calque = np.zeros_like(image)
    x = (largeur - large) // 2
    y = (hauteur + haut) // 2
    cv2.putText(calque, mot, (x, y), cv2.FONT_HERSHEY_DUPLEX, taille, AMBRE,
                epaisseur, cv2.LINE_AA)
    # Quelques degrés de travers, et un frémissement au rythme de la voix.
    angle = 7.0 + 1.5 * float(np.sin(seconde * 9.0))
    rotation = cv2.getRotationMatrix2D((largeur / 2, hauteur / 2), angle, 1.0)
    calque = cv2.warpAffine(calque, rotation, (largeur, hauteur))
    cv2.add(image, calque, dst=image)


def pose_annonce(image: np.ndarray, vue: tuple[int, int, int, int],
                 lignes: tuple[str, ...]) -> None:
    """La phrase, dans la bande sous le nom, le temps que la voix la dit.

    Hors de la montagne : une dédicace n'a pas à cacher la route. La police
    du flux n'a pas les accents, donc l'écran écrit sans eux ; la voix, elle,
    les dit.
    """
    gx, gy, gw, gh = vue
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    taille = 0.62 * echelle
    trait = max(1, int(round(2 * echelle)))
    y = gy + gh + int(round(52 * echelle))
    for ligne in lignes:
        (large, haut), _ = cv2.getTextSize(ligne, cv2.FONT_HERSHEY_SIMPLEX,
                                           taille, trait)
        if y + haut >= hauteur:
            return
        x = gx + max(0, (gw - large) // 2)
        cv2.putText(image, ligne, (x, y + haut), cv2.FONT_HERSHEY_SIMPLEX,
                    taille, (0, 0, 0), trait + 2, cv2.LINE_AA)
        cv2.putText(image, ligne, (x, y + haut), cv2.FONT_HERSHEY_SIMPLEX,
                    taille, BLANC, trait, cv2.LINE_AA)
        y += int(round(26 * echelle))


# La moutarde de Dijon, en BGR. Assez jaune pour se lire, assez brune pour
# rester une moutarde et pas un soleil.
MOUTARDE = (36, 164, 214)
# 23 h, puis 23 h 15. L'ancien fichier qui ne portait que la date ferme
# la journée : on ne la rejoue pas le soir où le format a changé.
DIJON_HEURES = (23 * 3600, 23 * 3600 + 15 * 60)
DIJON_GRACE_S = 240
DIJON_TENUE_S = 14.0
# Une fois, à 14 h 25, heure de Los Angeles. Le mème, puis le crédit.
NEVER_HEURE = 14 * 3600 + 25 * 60
NEVER_GRACE_S = 600
NEVER_TENUE_S = 12.0


def moutarde(image: np.ndarray, force: float) -> None:
    """Pousse l'image vers la moutarde, sans lui ôter ses formes."""
    if force <= 0.01:
        return
    plat = cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    teinte = plat.astype(np.float32)
    for voie, cible in enumerate(MOUTARDE):
        teinte[:, :, voie] *= cible / 170.0
    teinte = np.clip(teinte, 0, 255).astype(np.uint8)
    cv2.addWeighted(teinte, force, image, 1.0 - force, 0.0, dst=image)


def _dijon_lue(racine: Path) -> tuple[date | None, int]:
    """La date, et le prochain créneau : 0, 1, ou 2 si la journée est close."""
    try:
        morceaux = (racine / "data" / "voix" / "dijon.jour").read_text().split()
        jour = date.fromisoformat(morceaux[0])
        if len(morceaux) == 1:
            return jour, len(DIJON_HEURES)
        return jour, int(morceaux[1])
    except (OSError, ValueError, IndexError):
        return None, 0


def _dijon_ecrite(racine: Path, jour: date, rang: int) -> None:
    try:
        (racine / "data" / "voix" / "dijon.jour").write_text(
            f"{jour.isoformat()} {rang}\n", encoding="utf-8")
    except OSError:
        pass


def pose_dijon(image: np.ndarray, vue: tuple[int, int, int, int],
               logo: np.ndarray | None, age: float, heure: str) -> None:
    """Son logo, l'heure, et la ligne UNE COLLAB AVEC BUTTERBANE.

    Quatorze secondes. La montagne prend la moutarde. Le logo reste le
    sien : on ne le repeint pas.
    """
    if age < 0 or age > DIJON_TENUE_S:
        return
    force = min(1.0, age / 0.5, (DIJON_TENUE_S - age) / 0.7)
    gx, gy, gw, gh = vue
    if gw < 8 or gh < 8:
        return
    vive = image[gy:gy + gh, gx:gx + gw].copy()
    moutarde(vive, 0.55 * force)
    image[gy:gy + gh, gx:gx + gw] = vive
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    if logo is not None:
        rayon = int(min(gw, gh) * 0.22)
        pose_photo_ronde(image, logo, gx + gw // 2, gy + gh // 2, rayon,
                         echelle, anneau=MOUTARDE)
    taille_heure = 1.6 * echelle
    trait_heure = max(2, int(5 * echelle))
    (lh, hh), _ = cv2.getTextSize(heure, cv2.FONT_HERSHEY_DUPLEX,
                                  taille_heure, trait_heure)
    xh = gx + (gw - lh) // 2
    yh = gy + int(gh * 0.16) + hh
    cv2.putText(image, heure, (xh, yh), cv2.FONT_HERSHEY_DUPLEX, taille_heure,
                (0, 0, 0), trait_heure + 3, cv2.LINE_AA)
    cv2.putText(image, heure, (xh, yh), cv2.FONT_HERSHEY_DUPLEX, taille_heure,
                MOUTARDE, trait_heure, cv2.LINE_AA)
    pose_annonce(image, vue, ("UNE COLLAB", "AVEC BUTTERBANE"))


def _never_lue(racine: Path) -> date | None:
    try:
        return date.fromisoformat(
            (racine / "data" / "voix" / "never.jour").read_text().strip())
    except (OSError, ValueError):
        return None


def _never_ecrite(racine: Path, jour: date) -> None:
    try:
        (racine / "data" / "voix" / "never.jour").write_text(
            jour.isoformat() + "\n", encoding="utf-8")
    except OSError:
        pass


def pose_never(image: np.ndarray, vue: tuple[int, int, int, int],
               photo: np.ndarray | None, logo: np.ndarray | None,
               age: float) -> None:
    """Le mème, douze secondes, et le crédit de Butterbane sur son icône."""
    if age < 0 or age > NEVER_TENUE_S or photo is None:
        return
    force = min(1.0, age / 0.4, (NEVER_TENUE_S - age) / 0.6)
    gx, gy, gw, gh = vue
    if gw < 8 or gh < 8:
        return
    ph, pl = photo.shape[:2]
    echelle_photo = min(gw * 0.92 / pl, gh * 0.78 / ph)
    lw = max(1, int(pl * echelle_photo))
    lh = max(1, int(ph * echelle_photo))
    cadre_photo = cv2.resize(photo, (lw, lh), interpolation=cv2.INTER_AREA)
    x = gx + (gw - lw) // 2
    y = gy + (gh - lh) // 2
    dessous = image[y:y + lh, x:x + lw]
    cv2.addWeighted(cadre_photo, force, dessous, 1.0 - force, 0.0, dst=dessous)
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    if logo is not None:
        rayon = int(min(gw, gh) * 0.09)
        pose_photo_ronde(image, logo, gx + gw - rayon - int(12 * echelle),
                         gy + gh - rayon - int(12 * echelle), rayon, echelle,
                         anneau=MOUTARDE)
    pose_annonce(image, vue, ("NEVER GIVE UP", "BUTTERBANE"))


# Le compte, de temps en temps, dans la bande de droite. Quatre minutes :
# assez rare pour rester une surprise, assez souvent pour qu'on l'attrape
# en passant.
SALLE_PERIODE_S = 240.0
SALLE_TENUE_S = 10.0
SALLE_PREMIER_S = 25.0
SALLE_SONDE_S = 45.0


class Salle:
    """Le dernier compte lu, partagé entre le fil qui va le chercher et
    celui qui dessine."""

    def __init__(self) -> None:
        self.abonnes: int | None = None
        self.en_direct: int | None = None
        self._verrou = threading.Lock()

    def note(self, abonnes: int | None, en_direct: int | None) -> None:
        with self._verrou:
            if abonnes is not None:
                self.abonnes = abonnes
            if en_direct is not None:
                self.en_direct = en_direct

    def lit(self) -> tuple[int | None, int | None]:
        with self._verrou:
            return self.abonnes, self.en_direct


def veille_salle(chaine: str, coupe: threading.Event, salle: Salle) -> None:
    """Va lire le compte, et se tait quand la page ne le donne pas."""
    while not coupe.is_set():
        try:
            salle.note(*lit_la_salle(page_du_direct(chaine)))
        except Exception:
            log.warning("Le compte du direct n'a pas pu être lu", exc_info=True)
        if coupe.wait(SALLE_SONDE_S):
            return


def phrase_salle(racine: Path) -> Path | None:
    """« Nous sommes en direct », puis « We are live ».

    Deux phrases entières, pas des mots collés : « deux » raccourci
    s'entendait « de ». None si un fichier manque.
    """
    dossier = racine / "data" / "voix" / "salle"
    souffle = b"\0" * int(0.45 * ECHANTILLONS_S * VOIES * 2)
    morceaux = []
    for nom in ("phrase_fr", "phrase_en"):
        try:
            morceaux.append((dossier / f"{nom}.raw").read_bytes())
        except OSError:
            return None
    cible = dossier / "salle_phrase.raw"
    try:
        cible.write_bytes(morceaux[0] + souffle + morceaux[1])
    except OSError:
        return None
    return cible


def pose_salle(image: np.ndarray, vue: tuple[int, int, int, int],
               abonnes: int | None, en_direct: int | None, age: float,
               tenue: float = SALLE_TENUE_S) -> None:
    """Plus rien. Le compte d'abonnés et « en direct » ont quitté l'image."""
    return


# Les seuils du Pi 5 lui-même : il réduit sa fréquence à 80 °C et se met à
# l'abri à 85. On prévient donc avant, pas au moment où c'est fait.
TIEDE_C = 65.0
CHAUD_C = 75.0


def etat_machine(racine: Path) -> dict | None:
    """Température, charge, disque et âge de la machine qui tient le flux.

    Lu dans /sys et /proc plutôt qu'en appelant vcgencmd : ce sont des fichiers,
    donc la lecture ne coûte rien et ne peut pas rester bloquée sur un
    sous-processus pendant qu'une image attend d'être poussée.

    Rend None là où ces fichiers n'existent pas. Le flux se met au point sur un
    portable, et un encart qui inventerait une température y serait pire que
    pas d'encart du tout.
    """
    try:
        degres = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0
    except (OSError, ValueError):
        return None
    etat = {"degres": degres, "charge": 0.0, "debout": 0.0, "libre": 0}
    try:
        etat["charge"] = min(1.0, os.getloadavg()[0] / (os.cpu_count() or 4))
    except OSError:
        pass
    try:
        etat["debout"] = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    try:
        disque = os.statvfs(racine / "data")
        etat["libre"] = disque.f_bavail * disque.f_frsize
    except OSError:
        pass
    return etat


# La largeur de la photo de la machine, en pixels d'un cadre de mille six
# cents. Elle commande la largeur de l'encart quand le texte est plus étroit.
MACHINE_PHOTO_PX = 170
# La photo passe au monochrome cyan de l'encart. En couleur, c'est une
# photographie posée dans un tableau de bord : le blanc du bureau est le point
# le plus clair de tout le coin de l'image, l'œil y va avant d'aller au
# paysage, et le relief de la carte la fait ressortir comme un objet. Réduite
# à la teinte des chiffres et à leur plage de gris, elle redevient ce qu'elle
# doit être : une ligne de l'encart, qui se lit quand on la cherche.
MACHINE_NOIR = 0.10      # le noir de la photo, en part du blanc de l'encart
MACHINE_BLANC = 0.52     # et son blanc, qui n'est plus celui du bureau


def tamise_la_photo(photo: np.ndarray) -> np.ndarray:
    """La photo au monochrome de l'encart, dans sa plage de gris."""
    gris = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    plage = MACHINE_NOIR + gris * (MACHINE_BLANC - MACHINE_NOIR)
    teinte = np.array(CYAN, np.float32)
    return np.clip(plage[:, :, None] * teinte, 0, 255).astype(np.uint8)


# Le fond d'un encart, du haut vers le bas.
#
# Un rectangle assombri d'un seul coup est une vitre posée sur l'image. Les
# mêmes pixels assombris un peu plus en haut qu'en bas font une carte éclairée
# par le haut, ce qui est la façon dont un objet se détache d'un fond depuis
# qu'on dessine des objets. L'écart est de seize centièmes et ne se remarque
# pas : c'est exactement ce qu'on lui demande.
ENCART_SOMBRE = (0.24, 0.40)
# Le rayon des coins, en pixels d'un cadre de mille six cents. Assez pour qu'un
# coin ne pique pas, trop peu pour qu'on puisse appeler ça une bulle.
ENCART_RAYON = 7
# Le gris des étiquettes. Une étiquette et sa valeur n'ont pas à se disputer le
# regard : « LOAD » ne change jamais, « 31% » change tout le temps, et c'est le
# second qu'on vient lire.
GRIS_ENCART = (142, 142, 142)


def cadre_encart(image: np.ndarray, coin_a: tuple[int, int],
                 coin_b: tuple[int, int], echelle: float,
                 rayon: int | None = None) -> None:
    """Le filet des encarts : une arête, pas un cadre doré.

    Assombri seul, un encart flotte sur l'image et ses limites bougent avec le
    ciel derrière ; un filet suffit à en faire un objet posé. Dans le cyan du
    titre mais très baissé, et le même partout — deux encarts côte à côte avec
    deux bordures différentes, on voit la différence avant de voir les
    encarts.

    Les coins sont adoucis. Un angle droit parfait est ce que trace une
    bibliothèque de dessin quand on ne lui demande rien ; tout ce qui est
    fabriqué pour être regardé a les coins cassés, des panneaux de signalisation
    aux cartes à jouer. Trois pixels suffisent à faire la différence entre un
    rectangle et un objet.
    """
    x0, y0 = coin_a
    x1, y1 = coin_b
    teinte = tuple(int(c * 0.45) for c in CYAN)
    trait = max(1, int(echelle))
    r = ENCART_RAYON if rayon is None else rayon
    r = max(0, min(int(round(r * echelle)), (x1 - x0) // 2, (y1 - y0) // 2))
    if r <= 1:
        cv2.rectangle(image, coin_a, coin_b, teinte, trait)
        return
    cv2.line(image, (x0 + r, y0), (x1 - r, y0), teinte, trait, cv2.LINE_AA)
    cv2.line(image, (x0 + r, y1), (x1 - r, y1), teinte, trait, cv2.LINE_AA)
    cv2.line(image, (x0, y0 + r), (x0, y1 - r), teinte, trait, cv2.LINE_AA)
    cv2.line(image, (x1, y0 + r), (x1, y1 - r), teinte, trait, cv2.LINE_AA)
    for cx, cy, depart in ((x0 + r, y0 + r, 180.0), (x1 - r, y0 + r, 270.0),
                           (x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, 90.0)):
        cv2.ellipse(image, (cx, cy), (r, r), depart, 0.0, 90.0,
                    teinte, trait, cv2.LINE_AA)


def fond_encart(image: np.ndarray, coin_a: tuple[int, int],
                coin_b: tuple[int, int], echelle: float) -> None:
    """Assombrit la place d'un encart en dégradé, puis pose son filet."""
    x0, y0 = coin_a
    x1, y1 = coin_b
    panneau = image[y0:y1 + 1, x0:x1 + 1]
    if not panneau.size:
        return
    haut, bas = ENCART_SOMBRE
    rampe = np.linspace(haut, bas, panneau.shape[0], dtype=np.float32)
    panneau[:] = (panneau * rampe[:, None, None]).astype(np.uint8)
    cadre_encart(image, coin_a, coin_b, echelle)


def fond_bandeau(image: np.ndarray, y0: int, y1: int, echelle: float,
                 inverse: bool = False) -> None:
    """Le même dégradé que les encarts, sur toute la largeur.

    Un bandeau n'est pas une carte : il n'a pas de coins à adoucir. Il a un
    fond, et un filet du côté de l'image — sans lui le texte se pose sur la
    montagne et on ne sait plus ce qui est écrit et ce qui est un arbre.

    Inverse : plus sombre vers le bas, pour le bandeau du bas. Le haut de
    l'écran s'éclaire vers la montagne, le bas aussi : les deux s'éloignent
    de l'image par le noir, pas par un aplat.
    """
    bande = image[y0:y1, :]
    if not bande.size:
        return
    haut, bas = ENCART_SOMBRE
    if inverse:
        haut, bas = bas, haut
    rampe = np.linspace(haut, bas, bande.shape[0], dtype=np.float32)
    bande[:] = (bande * rampe[:, None, None]).astype(np.uint8)
    teinte = tuple(int(c * 0.45) for c in CYAN)
    y = (y1 - 1) if not inverse else y0
    cv2.line(image, (0, y), (image.shape[1] - 1, y), teinte,
             max(1, int(round(echelle))), cv2.LINE_AA)


# Même corps, même écart, même trait que le badge LIVE. Les deux encarts se
# répondent : à droite le direct, à gauche la machine qui le tient.
BADGE_TAILLE = 0.70
BADGE_PAS = 34
BADGE_RAYON = 7


def pose_badge(image: np.ndarray, mot: str, x: int, y: int, echelle: float,
               quand: float, *, vivant: bool = True,
               teinte_mot: tuple[int, int, int] | None = None,
               teinte_point: tuple[int, int, int] | None = None) -> int:
    """Un mot de chaîne, avec le point qui bat à la seconde.

    Le point rouge n'appartient qu'au direct : partout ailleurs il veut dire
    « ça tourne, là, maintenant ». Le Raspberry a le même geste, en cyan —
    la machine est vivante, ce n'est pas le badge du flux.
    """
    pas = int(BADGE_PAS * echelle)
    rayon = int(BADGE_RAYON * echelle)
    taille = BADGE_TAILLE * echelle
    mot_teinte = teinte_mot if teinte_mot is not None else (BLANC if vivant else AMBRE)
    point = teinte_point if teinte_point is not None else (ROUGE if vivant else AMBRE)
    if vivant and int(quand) % 2 == 0:
        cv2.circle(image, (x + rayon, y - rayon), rayon, point, -1)
    elif not vivant:
        cv2.circle(image, (x + rayon, y - rayon), rayon, point, -1)
    cv2.putText(image, mot, (x + pas, y), cv2.FONT_HERSHEY_SIMPLEX, taille,
                mot_teinte, 2, cv2.LINE_AA)
    large = cv2.getTextSize(mot, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0]
    return pas + large


# Le seul mot qu'on laisse sur l'image. Pas un auteur, pas un dépôt : un
# mot-dièse, en pixels, pour que le flux ait un nom sans dire qui le tient.
DIESE_FLUX = "#FREETECHNORADIO"
GLYPHES_DIESE = {
    "#": ("01010", "11111", "01010", "11111", "01010", "00000", "00000"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
}


def pose_diese(image: np.ndarray, vue: tuple[int, int, int, int]) -> None:
    """Le mot-dièse, en pixels, sous la fenêtre caméra.

    YouTube ne voit pas le site. Sans ce mot sur l'image, le flux n'a pas
    de nom. Il reste dans la bande noire : la montagne n'est pas un bandeau.
    """
    gx, gy, gw, gh = vue
    echelle = image.shape[1] / 1600
    cell = max(2, int(round(3 * echelle)))
    trou = max(1, int(round(echelle)))
    pas = cell + trou
    large = len(DIESE_FLUX) * 6 * pas - trou
    haut = 7 * pas - trou
    x0 = gx + (gw - large) // 2
    y0 = gy + gh + max(4, int(round(6 * echelle)))
    if y0 + haut > image.shape[0]:
        y0 = image.shape[0] - haut
    if x0 < 0:
        x0 = 0
    teinte = CYAN
    for i, signe in enumerate(DIESE_FLUX):
        rangees = GLYPHES_DIESE.get(signe, ())
        for y, rangee in enumerate(rangees):
            for x, bit in enumerate(rangee):
                if bit != "1":
                    continue
                px = x0 + (i * 6 + x) * pas
                py = y0 + y * pas
                image[py:py + cell, px:px + cell] = teinte


def pose_titre_encart(image: np.ndarray, texte: str, x: int, ligne: int,
                      large: int, echelle: float) -> None:
    """Le nom d'un encart, souligné d'un trait court.

    Le trait ne décore pas : il sépare. Sans lui, le titre est la première des
    lignes du tableau et se lit comme une mesure de plus ; avec lui, le tableau
    commence en dessous.
    """
    taille = 0.50 * echelle
    cv2.putText(image, texte, (x, ligne), cv2.FONT_HERSHEY_SIMPLEX, taille,
                CYAN, 1, cv2.LINE_AA)
    y = ligne + int(round(5 * echelle))
    cv2.line(image, (x, y), (x + large, y),
             tuple(int(c * 0.55) for c in CYAN), max(1, int(round(echelle))),
             cv2.LINE_AA)


def pose_jauge(image: np.ndarray, x: int, y: int, large: int, part: float,
               teinte: tuple[int, int, int], echelle: float) -> None:
    """Une barre fine : la part remplie d'une grandeur qui a des bornes.

    Un nombre dit la valeur, une barre dit où elle en est de sa course. « 46 C »
    ne renseigne que celui qui sait à quelle température un Raspberry Pi se
    bride ; la même valeur au tiers de sa barre le dit à tout le monde.

    Et c'est une mesure, pas un ornement : elle n'est posée que sur des
    grandeurs réellement bornées, et sa longueur est la part, sans mise en
    valeur ni arrondi flatteur.
    """
    epais = max(2, int(round(3 * echelle)))
    cv2.rectangle(image, (x, y), (x + large, y + epais),
                  tuple(int(c * 0.20) for c in BLANC), -1)
    pleine = int(round(large * min(1.0, max(0.0, part))))
    if pleine > 0:
        cv2.rectangle(image, (x, y), (x + pleine, y + epais), teinte, -1)


def pose_pastille(image: np.ndarray, texte: str, x: int, ligne: int,
                  echelle: float, teinte: tuple[int, int, int] = CYAN) -> int:
    """Un mot court dans un cadre, et rend l'abscisse où il finit.

    Pour les mentions qui sont des étiquettes et non des phrases — une licence,
    un code de pays. Encadré, un mot de quatre signes se lit comme une marque ;
    posé nu dans une ligne de texte, il se lit comme le début de la phrase
    suivante, et c'est ce qui arrivait à « CC0 » devant une adresse.
    """
    taille = 0.44 * echelle
    (large, haut), _ = cv2.getTextSize(texte, cv2.FONT_HERSHEY_SIMPLEX, taille, 1)
    marge = int(round(6 * echelle))
    a = (x, ligne - haut - marge)
    b = (x + large + 2 * marge, ligne + marge)
    cv2.rectangle(image, a, b, tuple(int(c * 0.22) for c in teinte), -1)
    cv2.rectangle(image, a, b, tuple(int(c * 0.70) for c in teinte),
                  max(1, int(round(echelle))), cv2.LINE_AA)
    cv2.putText(image, texte, (x + marge, ligne),
                cv2.FONT_HERSHEY_SIMPLEX, taille, teinte, 1, cv2.LINE_AA)
    return b[0]


def pose_duo(image: np.ndarray, etiquette: str, valeur: str, x: int,
             bord: int, ligne: int, echelle: float,
             teinte: tuple[int, int, int] = BLANC) -> None:
    """Une étiquette à gauche, sa valeur alignée à droite.

    C'est ce qui transforme une liste en tableau. Alignées à gauche, cinq
    valeurs de longueurs différentes font un bord déchiqueté qu'on relit ligne
    à ligne ; alignées à droite, elles font une colonne qu'on lit d'un coup.
    """
    cv2.putText(image, etiquette, (x, ligne), cv2.FONT_HERSHEY_SIMPLEX,
                0.44 * echelle, GRIS_ENCART, 1, cv2.LINE_AA)
    taille = 0.54 * echelle
    large = cv2.getTextSize(valeur, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0]
    cv2.putText(image, valeur, (bord - large, ligne), cv2.FONT_HERSHEY_SIMPLEX,
                taille, teinte, 2, cv2.LINE_AA)


def pose_heros(image: np.ndarray, nombre: str, unite: str, x: int, ligne: int,
               teinte: tuple[int, int, int], echelle: float) -> int:
    """Le chiffre qu'on vient lire, en grand, son unité en petit à côté.

    Un tableau où tout a la même taille n'a pas de sujet. Celui-ci en a un : la
    température est la seule grandeur qui puisse arrêter la diffusion, les
    autres sont du renseignement.
    """
    taille = 0.95 * echelle
    cv2.putText(image, nombre, (x, ligne), cv2.FONT_HERSHEY_SIMPLEX, taille,
                teinte, 2, cv2.LINE_AA)
    large = cv2.getTextSize(nombre, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0]
    suite = x + large + int(round(4 * echelle))
    cv2.putText(image, unite, (suite, ligne - int(round(8 * echelle))),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40 * echelle, GRIS_ENCART, 1,
                cv2.LINE_AA)
    return suite + cv2.getTextSize(unite, cv2.FONT_HERSHEY_SIMPLEX,
                                   0.40 * echelle, 1)[0][0]


def pose_osm(toile: np.ndarray, vue: tuple[int, int, int, int]) -> None:
    """Le crédit des données, en bas à gauche de la maquette.

    Routes, bâtiments et bois viennent d'OpenStreetMap, sous ODbL. Le crédit
    se pose sur la vue qui les montre, et nulle part ailleurs : la webcam
    n'est pas cette carte.
    """
    x, y, large, haut = vue
    echelle = toile.shape[1] / 1600
    marge = int(14 * echelle)
    texte = "OPENSTREETMAP ODBL"
    taille = 0.38 * echelle
    trait = max(1, int(round(echelle)))
    (_, th), _ = cv2.getTextSize(texte, cv2.FONT_HERSHEY_SIMPLEX, taille, trait)
    ox = x + marge
    oy = y + haut - marge
    if oy - th < 0 or ox < 0:
        return
    _pose_encre(toile, texte, (ox, oy), cv2.FONT_HERSHEY_SIMPLEX,
                taille, trait, BLANC)


def pose_direct(toile: np.ndarray, camera: np.ndarray,
                vue: tuple[int, int, int, int], quand: float
                ) -> tuple[int, int, int, int] | None:
    """La webcam en petit, pendant que le relief tourne à sa place.

    Le survol est le seul moment où ce flux cesse de montrer la montagne. Deux
    minutes, ce n'est pas long, mais c'est deux minutes où quelqu'un qui passe
    tombe sur un décor calculé et n'a aucun moyen de savoir qu'il y a une
    caméra derrière, ni ce qu'elle voit. Le badge dit déjà « 3D MODEL » et ne
    ment pas ; il dit ce que ce n'est pas, il ne montre pas ce que c'est.

    En bas à droite, assez grande pour qu'une voiture s'y voie passer : à un
    quart de la fenêtre, le rond-point fait encore une centaine de pixels de
    large. Plus petite, elle ne serait qu'une preuve que la caméra tourne, et
    une preuve n'est pas une vue.

    Le point rouge bat à la seconde, comme celui de l'horloge et pour la même
    raison : c'est lui qui distingue une image vivante d'une vignette collée.
    """
    if camera is None or camera.size == 0:
        return None
    x, y, large, haut = vue
    echelle = toile.shape[1] / 1600
    marge = int(18 * echelle)
    petit_l = max(96, int(large * 0.26))
    petit_h = max(54, int(petit_l * camera.shape[0] / camera.shape[1]))
    gx = x + large - petit_l - marge
    gy = y + haut - petit_h - marge
    if gx < 0 or gy < 0 or gx + petit_l > toile.shape[1] or gy + petit_h > toile.shape[0]:
        return None
    toile[gy:gy + petit_h, gx:gx + petit_l] = cv2.resize(
        camera, (petit_l, petit_h), interpolation=cv2.INTER_AREA)
    cadre_encart(toile, (gx - 1, gy - 1), (gx + petit_l, gy + petit_h), echelle)
    taille = 0.48 * echelle
    ligne = max(1, int(echelle))
    base = gy - int(7 * echelle)
    cv2.putText(toile, "DIRECT", (gx + int(16 * echelle), base),
                cv2.FONT_HERSHEY_SIMPLEX, taille, CYAN, ligne, cv2.LINE_AA)
    if int(quand) % 2 == 0:
        cv2.circle(toile, (gx + int(6 * echelle), base - int(4 * echelle)),
                   max(2, int(3.5 * echelle)), (60, 60, 235), -1, cv2.LINE_AA)
    return gx, gy, petit_l, petit_h


# Le fond d'échelle de la jauge de température, en degrés. Ce n'est pas un
# goût : à quatre-vingt-cinq degrés un Raspberry Pi se bride de lui-même, les
# images se mettent à manquer et la diffusion saccade — c'est arrivé. Le bas
# d'échelle est la température d'une pièce. Les deux valent pour la machine,
# pas pour cette caméra-ci.
FROID_C = 20.0
BRIDE_C = 85.0
# Les lignes de l'encart machine, en pixels d'un cadre de mille six cents :
# titre, date, heure, ville. Date et heure sont aux mêmes cotes que l'horloge
# d'en face. Le rapport n'est pas ici : il a sa vitre, collée dessous.
# Température et charge sont sous l'iconographie.
MACHINE_LIGNES = (26, 60, 96, 180)
# La bande laissée aux deux jauges, sous le disque. Elle allonge l'encart
# d'autant, pour que la carte ne rétrécisse pas.
JAUGE_BANDE = 74
# La vitre collée sous chaque encart. Même hauteur des deux côtés.
JACKPOT_H = 86


def _pose_portrait(image: np.ndarray, seconde: float,
                   photo: np.ndarray | None, occasion: str, merci: str,
                   tenue: float, part: float,
                   vue: tuple[int, int, int, int] | None = None,
                   nuit: bool = False,
                   pied_gauche: str = "", pied_droit: str = "",
                   pied_couleur: tuple[int, int, int] | None = None) -> bool:
    """Un disque au milieu, un remerciement au-dessus, parfois une ligne au pied."""
    if photo is None or photo.size == 0:
        return False
    phase = en_scene(occasion, seconde, nuit)
    if phase is None:
        return False
    force = min(phase, tenue - phase, 1.0)
    if force < 0.02:
        return True
    hauteur, largeur = image.shape[:2]
    gauche, cime, large_vue, haute_vue = vue or (0, 0, largeur, hauteur)
    echelle = largeur / 1600
    # Une ligne au-dessus pour le remerciement, une en dessous pour le lieu
    # et la température. Le mot sous le disque se collait à la route et
    # devenait illisible dès que le trait d'un rectangle passait par là.
    pied_h = int(28 * echelle) if (pied_gauche or pied_droit) else int(8 * echelle)
    tete_h = int(36 * echelle)
    rayon = max(8, int(large_vue * part / 2))
    if 2 * rayon + pied_h + tete_h + int(16 * echelle) > haute_vue:
        return False
    cx = gauche + large_vue // 2
    cy = cime + tete_h + (haute_vue - pied_h - tete_h) // 2
    if (cx - rayon < gauche or cy - rayon < cime + tete_h
            or cx + rayon >= gauche + large_vue
            or cy + rayon + pied_h >= cime + haute_vue):
        return False
    calque = image.copy()
    pose_photo_ronde(calque, photo, cx, cy, rayon, echelle)
    taille_merci = 0.70 * echelle
    epais = max(1, int(round(2 * echelle)))
    (mw, mh), _ = cv2.getTextSize(merci, cv2.FONT_HERSHEY_SIMPLEX,
                                  taille_merci, epais)
    ligne_merci = cy - rayon - int(10 * echelle)
    ox = cx - mw // 2
    # Un bandeau, pas un liseré : à cette taille un trait autour des
    # lettres les dédouble, et une ombre aussi.
    marge = max(4, int(6 * echelle))
    cv2.rectangle(calque,
                  (ox - marge, ligne_merci - mh - marge),
                  (ox + mw + marge, ligne_merci + marge // 2),
                  (10, 16, 18), -1)
    cv2.putText(calque, merci, (ox, ligne_merci),
                cv2.FONT_HERSHEY_SIMPLEX, taille_merci, CYAN,
                epais, cv2.LINE_AA)
    ligne = cy + rayon + int(20 * echelle)
    if pied_gauche:
        pose_lieu(calque, pied_gauche, cx - rayon, ligne, 0.48 * echelle, echelle)
    if pied_droit:
        couleur = pied_couleur or VERT
        large = cv2.getTextSize(pied_droit, cv2.FONT_HERSHEY_SIMPLEX,
                                0.54 * echelle, 2)[0][0]
        cv2.putText(calque, pied_droit, (cx + rayon - large, ligne),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.54 * echelle, couleur, 2,
                    cv2.LINE_AA)
    cv2.addWeighted(calque, 0.92 * force, image, 1.0 - 0.92 * force, 0.0, dst=image)
    return True


def pose_merci(image: np.ndarray, seconde: float, occasion: str, merci: str,
               tenue: float, vue: tuple[int, int, int, int] | None = None,
               nuit: bool = False) -> bool:
    """Une ligne de remerciement, sans photo, dans le haut de la fenêtre."""
    phase = en_scene(occasion, seconde, nuit)
    if phase is None:
        return False
    force = min(phase, tenue - phase, 1.0)
    if force < 0.02:
        return True
    hauteur, largeur = image.shape[:2]
    gauche, cime, large_vue, _haute = vue or (0, 0, largeur, hauteur)
    echelle = largeur / 1600
    taille = 0.72 * echelle
    epais = max(1, int(round(2 * echelle)))
    (mw, mh), _ = cv2.getTextSize(merci, cv2.FONT_HERSHEY_SIMPLEX, taille, epais)
    ox = gauche + (large_vue - mw) // 2
    oy = cime + mh + int(18 * echelle)
    calque = image.copy()
    marge = max(4, int(6 * echelle))
    cv2.rectangle(calque, (ox - marge, oy - mh - marge),
                  (ox + mw + marge, oy + marge // 2), (10, 16, 18), -1)
    cv2.putText(calque, merci, (ox, oy), cv2.FONT_HERSHEY_SIMPLEX, taille,
                CYAN, epais, cv2.LINE_AA)
    cv2.addWeighted(calque, 0.92 * force, image, 1.0 - 0.92 * force, 0.0, dst=image)
    return True


def pose_portrait_machine(image: np.ndarray, seconde: float,
                          photo: np.ndarray | None,
                          etat: dict | None = None, ville: str = "",
                          vue: tuple[int, int, int, int] | None = None,
                          nuit: bool = False) -> bool:
    """La photo de la machine, en grand au milieu, de temps en temps.

    Dans l'encart elle fait cent pixels et on y reconnaît à peine un
    ventilateur. Ici c'est la même photo, posée au milieu de ce qu'elle
    regarde : on voit enfin que le flux tient à une carte sur un bureau.

    L'encart de gauche reste. Comme l'ours : l'original ne bouge pas, le
    double apparaît, et c'est voir les deux qui fait comprendre que le
    second est une apparition.

    En couleurs, pas au cyan de l'encart. L'encart est un tableau de bord ;
    celui-ci est le portrait. Rond : une carte rectangulaire au milieu de
    la montagne, c'est un encart de plus ; un disque, c'est la photo.
    """
    pied_droit = ""
    couleur = None
    if etat:
        couleur = VERT if etat["degres"] < TIEDE_C else (
            AMBRE if etat["degres"] < CHAUD_C else ROUGE)
        pied_droit = f"{etat['degres']:.1f} C"
    return _pose_portrait(
        image, seconde, photo, "machine", MACHINE_MERCI,
        MACHINE_TENUE_S, MACHINE_PORTRAIT, vue=vue, nuit=nuit,
        pied_gauche=ville.upper() if ville else "",
        pied_droit=pied_droit, pied_couleur=couleur)


def pose_portrait_dogmazic(image: np.ndarray, seconde: float,
                           photo: np.ndarray | None,
                           vue: tuple[int, int, int, int] | None = None,
                           nuit: bool = False) -> bool:
    """Le logo de Dogmazic, en grand au milieu, de temps en temps.

    Même disque que le Raspberry, même bandeau, autre remerciement. C'est
    de leur archive que vient presque toute la musique : quand le chien
    orange prend le milieu, on le dit.
    """
    return _pose_portrait(
        image, seconde, photo, "dogmazic", DOGMAZIC_MERCI,
        DOGMAZIC_TENUE_S, DOGMAZIC_PORTRAIT, vue=vue, nuit=nuit,
        pied_gauche="MUSIQUE LIBRE")


def _carre_plein(image: np.ndarray, cote: int) -> np.ndarray:
    """Remplit un carré, rogne le trop-plein.

    Pour un disque, contenir laisserait un croissant vide de chaque côté :
    on verrait le cercle avant de voir la carte. Remplir, et le cadre est
    le cercle.
    """
    haut, large = image.shape[:2]
    src = min(haut, large)
    x = (large - src) // 2
    y = (haut - src) // 2
    return cv2.resize(image[y:y + src, x:x + src], (max(1, cote), max(1, cote)),
                      interpolation=cv2.INTER_AREA)


def pose_photo_ronde(image: np.ndarray, photo: np.ndarray, cx: int, cy: int,
                     rayon: int, echelle: float,
                     anneau: tuple[int, int, int] = CYAN) -> None:
    """Une photo dans un disque. Le cadre est le cercle, pas un rectangle."""
    if rayon < 4:
        return
    cote = 2 * rayon + 1
    carre = _carre_plein(photo, cote)
    x0, y0 = cx - rayon, cy - rayon
    if x0 < 0 or y0 < 0 or x0 + cote > image.shape[1] or y0 + cote > image.shape[0]:
        return
    yy, xx = np.ogrid[:cote, :cote]
    dist = np.sqrt((xx.astype(np.float32) - rayon) ** 2
                   + (yy.astype(np.float32) - rayon) ** 2)
    # Un pixel et demi de fondu : un cercle OpenCV rempli a les dents, et
    # on lit un défaut avant de lire la carte.
    alpha = np.clip((rayon - dist) / 1.5, 0.0, 1.0)
    coin = image[y0:y0 + cote, x0:x0 + cote].astype(np.float32)
    if carre.ndim == 3 and carre.shape[2] == 4:
        source = carre[:, :, :3].astype(np.float32)
        alpha = alpha * (carre[:, :, 3].astype(np.float32) / 255.0)
    else:
        source = carre.astype(np.float32)
    coin[:] = coin * (1.0 - alpha[:, :, None]) + source * alpha[:, :, None]
    image[y0:y0 + cote, x0:x0 + cote] = np.clip(coin, 0, 255).astype(np.uint8)
    teinte = tuple(int(c * 0.45) for c in anneau)
    cv2.circle(image, (cx, cy), rayon, teinte,
               max(1, int(round(echelle))), cv2.LINE_AA)


def pose_carte_et_photo(image: np.ndarray, x: int, y: int, large: int,
                        haut: int, carte: list | None,
                        ou: tuple[float, float] | None,
                        photo: np.ndarray | None, echelle: float) -> None:
    """La silhouette du pays, puis le disque. Même recette des deux côtés.

    Le disque s'assoit en bas de la place, la carte se pose au-dessus. Les
    deux ont une taille fixe — celle de l'autre encart — pour que Los
    Angeles et le trampoline se répondent, plutôt qu'un côté mange tout
    l'espace parce qu'il a moins de texte.
    """
    if large < 16 or haut < 16:
        return
    rayon = min(large // 2, int(ENCART_DISQUE * echelle / 2), max(8, haut // 4))
    cx = x + large // 2
    if photo is not None and photo.size and rayon >= 8:
        cy = y + haut - rayon
        if cy - rayon >= y:
            pose_photo_ronde(image, photo, cx, cy, rayon, echelle)
            haut = cy - rayon - y - max(4, int(6 * echelle))
    if carte and ou and haut >= 16:
        cote = min(large, haut, int(ENCART_CARTE * echelle))
        if cote >= 16:
            # Juste au-dessus du disque, centrée en largeur. Recentrer dans
            # toute la place restante faisait flotter la France plus haut :
            # l'horloge a moins de texte, donc plus de vide, et les deux
            # silhouettes ne se répondaient plus.
            pose_carte(image, carte, ou[0], ou[1],
                       x + (large - cote) // 2, y + haut - cote,
                       cote, echelle)


def _date_et_heure(quand: float, fuseau) -> tuple[str, str]:
    """La date et l'heure, au même format des deux côtés de l'écran."""
    moment = datetime.fromtimestamp(quand, fuseau)
    return moment.strftime("%d %b %Y").upper(), moment.strftime("%H:%M:%S")


def pose_date_heure(image: np.ndarray, x: int, date_y: int, heure_y: int,
                    jour: str, heure: str, echelle: float) -> None:
    """Date grise, heure blanche : le même corps à Los Angeles et à Beaumont."""
    cv2.putText(image, jour, (x, date_y), cv2.FONT_HERSHEY_SIMPLEX,
                0.48 * echelle, GRIS_ENCART, 1, cv2.LINE_AA)
    cv2.putText(image, heure, (x, heure_y), cv2.FONT_HERSHEY_SIMPLEX,
                0.95 * echelle, BLANC, 2, cv2.LINE_AA)


def lire_score(chemin: Path) -> dict:
    """Les deux journées, France et Los Angeles."""
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"paris": {}, "los_angeles": {}}
    if not isinstance(brut, dict):
        return {"paris": {}, "los_angeles": {}}
    return brut


def _cellule_du_jour(compte: dict, camp: str, jour: str) -> tuple[int, int]:
    cellule = (compte.get(camp) or {}).get(jour) or {}
    if not isinstance(cellule, dict):
        return 0, 0
    return int(cellule.get("pris") or 0), int(cellule.get("vus") or 0)


def _pourcent(pris: int, vus: int) -> int:
    """Prises sûres pour cent mouvements, ou -1 si la journée n'a pas commencé."""
    if vus <= 0:
        return -1
    return (100 * pris + vus // 2) // vus


def ratios_du_jour(compte: dict | None, quand: float
                   ) -> tuple[tuple[int, int, tuple], tuple[int, int, tuple]]:
    """Los Angeles, puis Beaumont : pris, vus, et la teinte du rapport.

    Le chiffre affiché est les prises sûres sur les mouvements, 0/0 tant
    que la journée n'a rien vu. Une prise compte des deux côtés. Chaque
    côté lit sa propre date, donc minuit à Beaumont remet la vitre de
    droite à 0/0 pendant que Los Angeles continue, et l'inverse neuf heures
    plus tard. Le vert est le meilleur taux. L'autre reste blanc. À
    égalité, les deux restent blancs. 0/0 ne mène pas.
    """
    compte = compte or {}
    france = datetime.fromtimestamp(quand, PARIS).date().isoformat()
    amerique = datetime.fromtimestamp(quand, LOS_ANGELES).date().isoformat()
    los = _cellule_du_jour(compte, "los_angeles", amerique)
    beau = _cellule_du_jour(compte, "paris", france)
    p_los, p_beau = _pourcent(*los), _pourcent(*beau)

    def teinte(le_sien: int, l_autre: int) -> tuple:
        if le_sien >= 0 and le_sien > l_autre:
            return VERT
        return BLANC

    return ((*los, teinte(p_los, p_beau)),
            (*beau, teinte(p_beau, p_los)))


def _jackpot_pourcent(pris: int, vus: int) -> int:
    """Entier du rapport prises sur mouvements, fois cent."""
    if vus <= 0:
        return 0
    return _pourcent(pris, vus)


def _pose_digits_jackpot(image: np.ndarray, a: tuple, b: tuple,
                         y_haut: int, y_bas: int, chaine: str,
                         teinte: tuple, echelle: float) -> None:
    """Trois fentes, un chiffre par fente, comme un compteur de machine."""
    n = len(chaine)
    if n < 1 or y_bas - y_haut < 8:
        return
    gap = max(2, int(3 * echelle))
    marge_x = max(4, int(6 * echelle))
    inner_w = b[0] - a[0] - 2 * marge_x
    inner_h = y_bas - y_haut - 2
    slot_w = max(8, (inner_w - gap * (n - 1)) // n)
    ep = max(1, int(round(1.2 * echelle)))
    police = cv2.FONT_HERSHEY_DUPLEX
    for i, car in enumerate(chaine):
        sx0 = a[0] + marge_x + i * (slot_w + gap)
        sx1 = sx0 + slot_w
        cv2.rectangle(image, (sx0, y_haut), (sx1, y_bas), (2, 3, 8), -1)
        cv2.rectangle(image, (sx0, y_haut), (sx1, y_bas),
                      tuple(int(c * 0.55) for c in AMBRE), ep, cv2.LINE_AA)
        taille = 0.95 * echelle
        epais = max(2, int(round(2 * echelle)))
        for _ in range(6):
            (lt, ht), _ = cv2.getTextSize(car, police, taille, epais)
            if lt <= slot_w - 4 and ht <= inner_h - 4:
                break
            taille *= 0.88
            epais = max(1, int(round(epais * 0.9)))
        (lt, ht), _ = cv2.getTextSize(car, police, taille, epais)
        ox = sx0 + (slot_w - lt) // 2
        oy = y_haut + (inner_h + ht) // 2
        cv2.putText(image, car, (ox, oy), police, taille, teinte, epais,
                    cv2.LINE_AA)


def pose_jackpot(image: np.ndarray, x0: int, x1: int, y0: int,
                 pris: int, vus: int, teinte: tuple, instant: float) -> None:
    """Une vitre de machine à sous, collée sous l'encart.

    Le compteur affiche le rapport en entier, fois cent, chiffre par
    chiffre. En petit, prises sur mouvements rappellent le ratio brut.
    Le lieu est déjà écrit au-dessus. Deux rangées d'ampoules courent en
    sens inverse. Le rouge n'y entre pas : il est au direct.
    """
    hauteur, largeur = image.shape[:2]
    if x1 - x0 < 36:
        return
    echelle = largeur / 1600
    haut = int(JACKPOT_H * echelle)
    y0 = max(0, min(y0, hauteur - 2))
    y1 = min(hauteur - 1, y0 + haut - 1)
    x0 = max(0, min(x0, largeur - 2))
    x1 = max(x0 + 2, min(x1, largeur - 1))
    if y1 - y0 < 22:
        return
    fond_encart(image, (x0, y0), (x1, y1), echelle)
    marge = max(5, int(8 * echelle))
    a = (x0 + marge, y0 + marge)
    b = (x1 - marge, y1 - marge)
    if b[0] - a[0] < 16 or b[1] - a[1] < 12:
        return
    cv2.rectangle(image, a, b, (6, 8, 14), -1)
    or_trait = tuple(int(c * 0.9) for c in AMBRE)
    ep = max(1, int(round(1.5 * echelle)))
    cv2.rectangle(image, a, b, or_trait, ep, cv2.LINE_AA)
    cv2.rectangle(image, (a[0] + 3, a[1] + 3), (b[0] - 3, b[1] - 3),
                  tuple(int(c * 0.28) for c in AMBRE), max(1, ep), cv2.LINE_AA)

    def ampoules(y: int, sens: int) -> None:
        pas = max(8, int(12 * echelle))
        n = max(1, (b[0] - a[0]) // pas)
        allume = int(instant * 7) % n
        rayon = max(1, int(round(2.1 * echelle)))
        for i in range(n):
            cx = a[0] + int((i + 0.5) * (b[0] - a[0]) / n)
            if not (0 <= cx < largeur and 0 <= y < hauteur):
                continue
            rang = (n - 1 - i) if sens < 0 else i
            couleur = AMBRE if (rang + allume) % 2 == 0 else CYAN
            if rang != allume:
                couleur = tuple(max(0, c // 5) for c in couleur)
            cv2.circle(image, (cx, y), rayon, couleur, -1, cv2.LINE_AA)

    ampoules(y0 + marge // 2, 1)
    ampoules(y1 - marge // 2, -1)
    pct = _jackpot_pourcent(pris, vus)
    chiffres = f"{pct:03d}"
    petit_h = max(10, int(14 * echelle))
    y_chiffres_h = a[1] + 2
    y_chiffres_b = b[1] - petit_h - 2
    if y_chiffres_b - y_chiffres_h >= 12:
        _pose_digits_jackpot(image, a, b, y_chiffres_h, y_chiffres_b,
                             chiffres, teinte, echelle)
    detail = f"{pris}/{vus}"
    taille_p = 0.36 * echelle
    ep_p = max(1, int(round(1 * echelle)))
    (ld, hd), _ = cv2.getTextSize(detail, cv2.FONT_HERSHEY_SIMPLEX, taille_p, ep_p)
    y_detail = b[1] - max(2, int(3 * echelle))
    cv2.putText(image, detail,
                (a[0] + (b[0] - a[0] - ld) // 2, y_detail),
                cv2.FONT_HERSHEY_SIMPLEX, taille_p, GRIS_ENCART, ep_p,
                cv2.LINE_AA)


def pose_mesures(image: np.ndarray, x: int, bord: int, y: int, haut: int,
                 degres: float, charge: float, couleur: tuple,
                 echelle: float) -> None:
    """Température et charge, en bas de l'encart, l'une sous l'autre."""
    if haut < int(28 * echelle) or bord - x < 20:
        return
    pas = haut / 4
    temp = y + pas
    pose_duo(image, "TEMP", f"{degres:.1f} C", x, bord, int(temp), echelle,
             teinte=couleur)
    pose_jauge(image, x, int(temp + 4 * echelle), bord - x,
               (degres - FROID_C) / (BRIDE_C - FROID_C), couleur, echelle)
    charge_y = y + 3 * pas
    pose_duo(image, "LOAD", f"{charge * 100:.0f}%", x, bord, int(charge_y),
             echelle)
    pose_jauge(image, x, int(charge_y + 4 * echelle), bord - x, charge,
               VERT if charge < 0.75 else AMBRE, echelle)


# Huit secondes, le temps de lire la ligne. Chaque côté a le sien.
RESET_S = 8.0


def note_minuit(quand: float, memoire: dict) -> str | None:
    """La phrase du côté dont la date vient de changer, sinon rien.

    Le premier appel note les deux dates et se tait : un démarrage n'est
    pas un minuit. Ensuite, minuit à Beaumont vide la journée de droite,
    minuit à Los Angeles vide celle de gauche. Neuf heures les séparent.
    """
    los = datetime.fromtimestamp(quand, LOS_ANGELES).date()
    beau = datetime.fromtimestamp(quand, PARIS).date()
    if "beau" in memoire and beau != memoire["beau"]:
        memoire["feu_beau"] = quand
    if "los" in memoire and los != memoire["los"]:
        memoire["feu_los"] = quand
    memoire["beau"] = beau
    memoire["los"] = los
    if 0 <= quand - memoire.get("feu_beau", -1e9) < RESET_S:
        return "NEW DAY IN BEAUMONT"
    if 0 <= quand - memoire.get("feu_los", -1e9) < RESET_S:
        return "NEW DAY IN LOS ANGELES"
    return None


def pose_machine(image: np.ndarray, etat: dict | None,
                 vignette: np.ndarray | None = None, ville: str = "",
                 remue: float = 0.0,
                 carte: list | None = None,
                 ou: tuple[float, float] | None = None,
                 quand: float | None = None,
                 ratio: tuple | None = None) -> None:
    """L'encart machine, en haut à gauche, en face de l'horloge.

    Une webcam qui tourne vingt-quatre heures sur vingt-quatre tient à une
    chose : que la machine ne chauffe pas. Le dire à l'écran, c'est montrer
    qu'on le surveille, et c'est aussi le seul moyen de s'en apercevoir sans
    ouvrir un terminal.

    L'heure est celle de Los Angeles, écrite comme celle de Beaumont : même
    date, même corps, mêmes lignes. Disk et Up n'avaient pas de pendant
    à droite.
    """
    if not etat:
        return
    largeur = image.shape[1]
    echelle = largeur / 1600
    degres = etat["degres"]
    couleur = VERT if degres < TIEDE_C else (AMBRE if degres < CHAUD_C else ROUGE)
    instant = time.time() if quand is None else quand
    jour, heure = _date_et_heure(instant, LOS_ANGELES)
    marge = int(14 * echelle)
    sommet = int(RUBAN_H * echelle) + int(remue)
    taille = LIEU_CORPS * echelle
    # Les deux encarts se répondent : celui-ci dit où est la machine qui
    # regarde, celui d'en face où est ce qu'elle regarde. Huit mille
    # kilomètres entre les deux, et c'est à peu près tout le projet.
    lieu = (ville or "").upper()
    large = max(
        int(BADGE_PAS * echelle) + cv2.getTextSize(
            "RASPBERRY PI 5", cv2.FONT_HERSHEY_SIMPLEX,
            BADGE_TAILLE * echelle, 2)[0][0],
        cv2.getTextSize(jour, cv2.FONT_HERSHEY_SIMPLEX, 0.48 * echelle, 1)[0][0],
        cv2.getTextSize(heure, cv2.FONT_HERSHEY_SIMPLEX, 0.95 * echelle, 2)[0][0],
        cv2.getTextSize(f"TEMP   {degres:.1f} C", cv2.FONT_HERSHEY_SIMPLEX,
                        0.54 * echelle, 2)[0][0],
        cv2.getTextSize(f"LOAD   {etat['charge'] * 100:.0f}%",
                        cv2.FONT_HERSHEY_SIMPLEX, 0.54 * echelle, 2)[0][0],
        large_du_lieu(lieu, taille * HORLOGE_LIEU, echelle),
        int(ENCART_LARGE * echelle) if (carte and ou) or (
            vignette is not None and vignette.size) else 0,
    )
    droite = max(large + 2 * marge, int(ENCART_LARGE * echelle) + 2 * marge)
    haut_reste = sommet + int(ENCART_DESSIN * echelle)
    a_dessin = bool((carte and ou) or (vignette is not None and vignette.size))
    bande = int(JAUGE_BANDE * echelle)
    jack = int(JACKPOT_H * echelle) if ratio is not None else 0
    if a_dessin:
        bas_total = int(ENCART_BAS * echelle) + int(remue)
    else:
        bas_total = sommet + int(MACHINE_LIGNES[-1] * echelle) + bande + marge + jack
    bas = bas_total - jack
    fond_encart(image, (0, sommet), (droite - 1, bas - 1), echelle)
    bord = droite - marge
    titre, date_y, heure_y, ville_y = (
        sommet + int(r * echelle) for r in MACHINE_LIGNES)
    pose_badge(image, "RASPBERRY PI 5", marge, titre, echelle, instant,
               teinte_mot=BLANC, teinte_point=CYAN)
    trait = titre + int(round(9 * echelle))
    cv2.line(image, (marge, trait), (bord, trait),
             tuple(int(c * 0.55) for c in CYAN), max(1, int(round(echelle))),
             cv2.LINE_AA)
    pose_date_heure(image, marge, date_y, heure_y, jour, heure, echelle)
    pose_lieu(image, lieu, marge, ville_y, taille * HORLOGE_LIEU, echelle)
    if a_dessin:
        pose_carte_et_photo(
            image, marge, haut_reste, droite - 2 * marge,
            bas - haut_reste - marge - bande,
            carte, ou, tamise_la_photo(vignette) if vignette is not None else None,
            echelle)
    # Température et charge ont un plafond connu, et ce sont elles qui
    # arrêtent la diffusion. Elles ferment l'encart, sous la carte.
    pose_mesures(image, marge, bord, bas - marge - bande, bande,
                 degres, etat["charge"], couleur, echelle)
    if ratio is not None:
        pose_jackpot(image, 0, droite - 1, bas,
                     int(ratio[0]), int(ratio[1]), ratio[2], instant)


BONJOUR_S = 8.0
# Le lever au sens où tout le monde l'entend : le bord haut du disque à
# l'horizon, réfraction comprise. C'est la définition de la NOAA, elle ne doit
# rien au cadrage de cette caméra-ci et vaudra pour la suivante.
HORIZON = -0.833


DEPLOI_S = 6.0


def pose_deploiement(image: np.ndarray, version: str, age: float) -> None:
    """Le numéro qui vient d'arriver, une fois, au redémarrage du flux.

    Un déploiement sans trace à l'écran, on ne sait pas s'il a pris. Le mot
    et le numéro tiennent six secondes, comme un bonjour : assez pour le
    lire, pas assez pour rester collé sur la montagne.
    """
    if age < 0 or age > DEPLOI_S or not version:
        return
    force = min(1.0, age / 0.6, (DEPLOI_S - age) / 0.8)
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    calque = image.copy()
    for i, (mot, taille) in enumerate((("DEPLOYED", 1.15), (f"v{version}", 1.8))):
        echelle_mot = taille * echelle
        epaisseur = max(2, int(4 * echelle))
        (large, haut), _ = cv2.getTextSize(mot, cv2.FONT_HERSHEY_DUPLEX, echelle_mot, epaisseur)
        x = (largeur - large) // 2
        y = int(hauteur * 0.40) + i * int(88 * echelle) + haut // 2
        cv2.putText(calque, mot, (x, y), cv2.FONT_HERSHEY_DUPLEX, echelle_mot,
                    (0, 0, 0), epaisseur + max(3, int(6 * echelle)), cv2.LINE_AA)
        cv2.putText(calque, mot, (x, y), cv2.FONT_HERSHEY_DUPLEX, echelle_mot,
                    CYAN, epaisseur, cv2.LINE_AA)
    cv2.addWeighted(calque, force, image, 1.0 - force, 0.0, dst=image)


def pose_bonjour(image: np.ndarray, nom: str, age: float) -> None:
    """« GOOD MORNING » au lever du soleil, en grand et en ambre.

    Ambre et non vert : c'est la couleur de ce qu'on regarde à ce moment-là, et
    le flux a déjà un vert, celui des prises.
    """
    if age < 0 or age > BONJOUR_S:
        return
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    # Une apparition et une disparition d'une seconde : le mot reste lisible
    # tout le milieu, au lieu de clignoter au passage.
    force = min(1.0, age / 1.0, (BONJOUR_S - age) / 1.0)
    calque = image.copy()
    for i, (mot, taille) in enumerate((("GOOD MORNING", 1.5), (nom.upper() + " !", 2.4))):
        echelle_mot = taille * echelle
        epaisseur = max(2, int(5 * echelle))
        (large, haut), _ = cv2.getTextSize(mot, cv2.FONT_HERSHEY_DUPLEX, echelle_mot, epaisseur)
        x = (largeur - large) // 2
        y = int(hauteur * 0.36) + i * int(110 * echelle) + haut // 2
        cv2.putText(calque, mot, (x, y), cv2.FONT_HERSHEY_DUPLEX, echelle_mot,
                    (0, 0, 0), epaisseur + max(3, int(7 * echelle)), cv2.LINE_AA)
        cv2.putText(calque, mot, (x, y), cv2.FONT_HERSHEY_DUPLEX, echelle_mot,
                    AMBRE, epaisseur, cv2.LINE_AA)
    cv2.addWeighted(calque, force, image, 1.0 - force, 0.0, dst=image)


# Le lieu sous les chiffres, en part de leur taille. Les deux encarts
# emploient le même corps et la même ligne : Los Angeles à gauche,
# Beaumont-du-Ventoux à droite. Avant, l'horloge écrivait plus petit et
# plus haut, parce que le nom était un sous-titre de l'heure.
LIEU_CORPS = 0.56
HORLOGE_LIEU = 0.62
# La carte dans l'encart : une silhouette de pays avec un point dessus.
# L'encart nommait la commune et ne disait pas où elle est. Un nom de commune
# française ne dit rien à qui n'est pas français, et la moitié des gens qui
# regardent une webcam ne le sont pas. Une silhouette se lit sans savoir lire.
#
# Il y avait un drapeau à la place, minuscule, et c'était une mauvaise
# réponse : un drapeau dit un pays et rien de plus, alors qu'on voulait dire
# un endroit dans un pays — et à huit pixels de haut il ne disait même pas le
# pays, il disait « il y a quelque chose de colorié ici ».
# Les deux encarts descendent jusqu'à la même ligne et sont au moins aussi
# larges l'un que l'autre : c'est ce qui les rend symétriques pour de bon.
# Chacun écrit son texte, puis son image prend tout ce qui reste jusqu'en bas.
# Sans cette ligne commune, les deux hauteurs dépendaient du nombre de lignes
# de texte, qui n'a aucune raison d'être le même des deux côtés.
# 470, plus le creux du rapport (214 − 180) et la bande des jauges. Les
# cartes gardent leur hauteur : on a descendu le bas, pas remonté le dessin.
ENCART_BAS = 470 + JAUGE_BANDE + JACKPOT_H
ENCART_LARGE = 170
# Sous le texte, les deux encarts ont la même recette : une silhouette de
# pays, puis un disque. Même hauteur de départ, mêmes tailles, le disque
# assis en bas — c'est ça qui les rend symétriques, pas le nombre de
# lignes au-dessus. L'horloge a moins de texte ; sans cette ligne commune
# sa carte commençait plus haut et l'hexagone flottait.
ENCART_DESSIN = MACHINE_LIGNES[-1]
ENCART_CARTE = 108.0
ENCART_DISQUE = 112.0
# De temps en temps, quand la musique pousse, les deux encarts se balancent.
# En hauteur seulement : de côté, celui de gauche entrerait dans l'image et
# celui de droite sortirait de l'écran, et un tableau de bord qui empiète sur
# ce qu'on surveille est une mauvaise plaisanterie. Ils vont en sens inverse
# l'un de l'autre — ensemble ils auraient l'air de glisser, pas de danser.
# Le flottement des deux encarts. Lent et continu, et non plus un sursaut sur
# le beat : un encart qui tressaute quelques secondes toutes les cinq minutes
# ressemble à un défaut d'affichage, et c'est bien ce que ça avait l'air
# d'être. Onze secondes de période et trois pixels d'amplitude, c'est à peine
# perceptible image par image — on ne voit pas que ça bouge, on voit que ce
# n'est pas figé, ce qui n'est pas la même chose.
#
# La seconde harmonique, plus lente et plus faible, casse le métronome : deux
# sinusoïdes de périodes incommensurables ne repassent jamais ensemble au même
# endroit, et le mouvement n'a plus de mesure audible.
ENCART_FLOTTE_S = 11.0
ENCART_FLOTTE_LENT_S = 17.0
ENCART_FLOTTE_PX = 3.0


def flottement(seconde: float, echelle: float = 1.0) -> float:
    """De combien de pixels l'encart de gauche est descendu, à cet instant."""
    return ((math.sin(2 * math.pi * seconde / ENCART_FLOTTE_S)
             + 0.4 * math.sin(2 * math.pi * seconde / ENCART_FLOTTE_LENT_S))
            / 1.4 * ENCART_FLOTTE_PX * echelle)


BULLE_COLONNE = 8        # de bulles par côté, comme sur l'aquarium du site
BULLE_MIN = 5.0          # son rayon au départ, à la largeur de référence
BULLE_MAX = 10.0
BULLE_LENTE_S = 8.9      # la plus lente met neuf secondes à monter
BULLE_VIVE_S = 4.9
BULLE_DERIVE = 11.0      # de combien elle part de côté en montant
BULLE_VOILE = 0.55       # son opacité la plus forte
BULLE_TRAIT = (236, 240, 218)


# LES POISSONS DE L'AQUARIUM DE LA MAISON
# --------------------------------------
# Les mêmes que sur benoit-prieur.fr, où ils sont faits de boîtes CSS arrondies
# et non d'un dessin : un corps ovale cerné de sombre, une queue à deux lobes,
# trois nageoires, un œil crème et une bouche en arc. Trois exemplaires, un
# orange, un violet, un vert, et c'est tout — pas de rayures, le site n'en a
# pas non plus.
#
# Ils nagent dans les bandes noires avec les bulles, parce que c'est là qu'est
# l'aquarium. Jamais dans la fenêtre caméra : un poisson qui traverse la
# montagne serait exactement le genre d'apparition dont on a passé des
# semaines à se débarrasser.
#
# Verticalement, et non en travers. Une bande fait deux cent vingt pixels de
# large contre huit cents de haut : un poisson qui la traverse à l'horizontale
# a disparu avant qu'on l'ait vu.
#
# En BGR, dans l'ordre : le clair du dos, le corps, le sombre du ventre, le
# cerne. Relevés sur les variables CSS du site.
POISSONS = (
    ((88, 159, 255), (36, 100, 241), (22, 65, 197), (16, 26, 59)),    # orange
    ((255, 155, 193), (255, 107, 155), (200, 64, 102), (86, 25, 44)),  # violet
    ((154, 227, 141), (103, 181, 57), (65, 125, 31), (36, 63, 22)),    # vert
)
POISSON_CREME = (156, 212, 248)
POISSON_LONG = 58.0       # de la queue au museau, à 1600 de large
POISSON_TOUR_S = (71.0, 97.0, 127.0)   # premiers entre eux, comme le reste
POISSON_VOILE = 0.9
# Il ne traverse que la moitié de son tour ; l'autre moitié il n'est pas là.
# Trois poissons en permanence dans deux bandes, c'est un fond d'écran.
POISSON_PART = 0.45


def _poisson(image: np.ndarray, cx: int, cy: int, longueur: float,
             sens: int, phase: float, teintes: tuple) -> None:
    """Un poisson, museau vers « sens » (+1 à droite, -1 à gauche).

    Les proportions sont celles du site, rapportées à la longueur : le corps
    occupe les six dixièmes de l'avant, la queue les trois dixièmes de
    l'arrière, et l'œil est aux deux tiers du corps.
    """
    dos, corps, ventre, cerne = teintes
    trait = max(1, int(longueur * 0.028))
    demi = longueur / 2.0
    corps_l = longueur * 0.60
    corps_h = longueur * 0.34
    # La queue bat, et c'est elle qui fait avancer : sans ce battement le
    # poisson glisse, et un poisson qui glisse est un poisson en plastique.
    bat = math.sin(phase) * 0.42

    def plein(points, couleur):
        cv2.fillPoly(image, [np.int32(points)], couleur, cv2.LINE_AA)

    # La queue, derrière le corps donc avant lui.
    pied = (int(cx - sens * corps_l * 0.46), cy)
    bout = (cx - sens * demi, cy)
    for haut in (-1, 1):
        plein([pied,
               (int(bout[0]), int(bout[1] + haut * longueur * 0.17
                                  + bat * longueur * 0.10)),
               (int(bout[0] + sens * longueur * 0.07),
                int(cy + haut * longueur * 0.04))], ventre)
    cv2.polylines(image, [np.int32([
        (int(bout[0]), int(cy - longueur * 0.17 + bat * longueur * 0.10)),
        pied,
        (int(bout[0]), int(cy + longueur * 0.17 + bat * longueur * 0.10))])],
        False, cerne, trait, cv2.LINE_AA)

    # Les nageoires : dorsale, pectorale, ventrale.
    for haut, part, taille in ((-1, 0.10, 0.22), (1, 0.14, 0.17), (0, 0.30, 0.15)):
        if haut == 0:
            continue
        nx = int(cx + sens * corps_l * part)
        ny = int(cy + haut * corps_h * 0.42)
        cv2.ellipse(image, (nx, ny),
                    (max(2, int(longueur * taille * 0.6)),
                     max(2, int(longueur * taille * 0.45))),
                    haut * 28.0, 0, 360, ventre, -1, cv2.LINE_AA)
        cv2.ellipse(image, (nx, ny),
                    (max(2, int(longueur * taille * 0.6)),
                     max(2, int(longueur * taille * 0.45))),
                    haut * 28.0, 0, 360, cerne, trait, cv2.LINE_AA)

    # Le corps : plein du ventre, puis deux ellipses plus claires et plus
    # hautes par-dessus. Trois tons empilés, c'est le dégradé du site dit avec
    # les moyens d'OpenCV, et à cinquante pixels de long c'est tout ce qui se
    # voit d'un dégradé.
    axes = (max(2, int(corps_l / 2)), max(2, int(corps_h / 2)))
    cv2.ellipse(image, (cx, cy), axes, 0, 0, 360, ventre, -1, cv2.LINE_AA)
    cv2.ellipse(image, (cx, cy - int(corps_h * 0.10)),
                (axes[0], max(1, int(axes[1] * 0.82))), 0, 0, 360, corps, -1,
                cv2.LINE_AA)
    cv2.ellipse(image, (cx, cy - int(corps_h * 0.20)),
                (max(1, int(axes[0] * 0.90)), max(1, int(axes[1] * 0.48))),
                0, 0, 360, dos, -1, cv2.LINE_AA)
    cv2.ellipse(image, (cx, cy), axes, 0, 0, 360, cerne, trait, cv2.LINE_AA)

    # L'œil et la bouche, du côté du museau.
    # Un blanc, une pupille décalée vers le museau, un reflet. L'œil était un
    # disque crème cerné de sombre avec un point au milieu, ce qui à cette
    # taille ne fait pas un œil mais une cible : trois anneaux concentriques,
    # et rien qui regarde quelque part. Une pupille qui regarde devant suffit
    # à donner une direction à toute la bête.
    oeil = (int(cx + sens * corps_l * 0.26), int(cy - corps_h * 0.14))
    rayon = max(3, int(longueur * 0.075))
    cv2.circle(image, oeil, rayon, (252, 250, 246), -1, cv2.LINE_AA)
    pupille = (int(oeil[0] + sens * rayon * 0.30), oeil[1])
    cv2.circle(image, pupille, max(2, int(rayon * 0.56)), cerne, -1, cv2.LINE_AA)
    cv2.circle(image, (int(pupille[0] - sens * rayon * 0.18),
                       int(pupille[1] - rayon * 0.26)),
               max(1, int(rayon * 0.22)), (255, 255, 255), -1, cv2.LINE_AA)
    cv2.circle(image, oeil, rayon, cerne, max(1, trait - 1), cv2.LINE_AA)
    museau = (int(cx + sens * corps_l * 0.46), int(cy + corps_h * 0.16))
    cv2.ellipse(image, museau, (max(2, int(longueur * 0.055)),
                                max(2, int(longueur * 0.045))),
                0, 200.0 if sens > 0 else 300.0,
                340.0 if sens > 0 else 440.0, cerne, trait, cv2.LINE_AA)


def pose_poissons(image: np.ndarray, seconde: float,
                  vue: tuple | None = None) -> None:
    """Les trois poissons de l'aquarium traversent les bandes noires.

    Chacun sur son tour, trois nombres premiers, et seulement sur une partie
    de ce tour : trois poissons en permanence dans deux bandes, ce serait un
    fond d'écran. Ils changent de bande d'un tour à l'autre et nagent dans le
    sens de leur montée ou de leur descente.

    Dessinés avant tout le reste, comme les bulles : les encarts, les pantins
    et la fenêtre caméra passent par-dessus.
    """
    hauteur, largeur = image.shape[:2]
    gauche, cime, large_vue, haute_vue = vue or (0, 0, largeur, hauteur)
    echelle = largeur / 1600
    longueur = POISSON_LONG * echelle
    if gauche < longueur * 0.8:
        return
    calque = np.zeros_like(image)
    pose = False
    for i, tour_s in enumerate(POISSON_TOUR_S):
        tour, part = divmod(seconde, tour_s)
        part /= tour_s
        if part > POISSON_PART:
            continue
        avance = part / POISSON_PART
        # Un tour sur deux il descend, et il change de bande à chaque tour.
        descend = int(tour) % 2 == 0
        a_droite = (int(tour) + i) % 2 == 0
        bande_x = (gauche + large_vue + gauche // 2 if a_droite else gauche // 2)
        # De sous la fenêtre caméra jusqu'à son sommet, avec de quoi entrer et
        # sortir par les bords.
        haut, bas = cime - longueur, cime + haute_vue + longueur
        y = bas + (haut - bas) * avance if not descend else haut + (bas - haut) * avance
        # Il louvoie : un poisson qui monte tout droit est un ascenseur.
        x = bande_x + math.sin(avance * math.pi * 3 + i) * gauche * 0.22
        _poisson(calque, int(x), int(y), longueur,
                 1 if math.cos(avance * math.pi * 3 + i) > 0 else -1,
                 seconde * 5.0 + i, POISSONS[i % len(POISSONS)])
        pose = True
    if not pose:
        return
    # Les bandes seulement : on efface tout ce qui aurait débordé sur la
    # fenêtre caméra avant de mélanger. Plus sûr que de calculer où le poisson
    # a le droit d'être — une nageoire se calcule mal, un rectangle se vide.
    calque[cime:cime + haute_vue, gauche:gauche + large_vue] = 0
    masque = calque.any(axis=2)
    if not masque.any():
        return
    image[masque] = cv2.addWeighted(calque, POISSON_VOILE, image,
                                    1.0 - POISSON_VOILE, 0.0)[masque]


def pose_bulles(image: np.ndarray, seconde: float,
                vue: tuple | None = None) -> None:
    """Deux colonnes de bulles qui montent dans les bandes noires.

    Celles de l'aquarium du site de la maison, reprises à l'identique : un
    anneau clair, presque pas de remplissage, qui grossit en montant parce que
    la pression tombe, et qui s'efface en haut comme en bas. Elles dérivent un
    peu de côté — une bulle qui monte tout droit est une bulle dessinée.

    Dans les bandes noires seulement, et dessinées avant tout le reste : les
    encarts, les pantins et la fenêtre caméra passent par-dessus. Rien de ce
    qu'on vient regarder n'est derrière une bulle.
    """
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    gauche, _, large_vue, _ = vue or (0, 0, largeur, hauteur)
    bandes = [(0, gauche), (gauche + large_vue, largeur)]
    calque = image.copy()
    for cote, (x0, x1) in enumerate(bandes):
        large = x1 - x0
        if large < 20 * echelle:
            continue
        for n in range(BULLE_COLONNE):
            # Des nombres tirés une fois pour toutes à partir du rang : deux
            # bulles ne doivent jamais partager période ni départ, sinon la
            # colonne bat la mesure.
            graine = n * 2.399963 + cote * 1.047198
            duree = BULLE_LENTE_S + (BULLE_VIVE_S - BULLE_LENTE_S) * (
                0.5 + 0.5 * math.sin(graine * 3.1))
            part = ((seconde / duree) + 0.5 + 0.5 * math.sin(graine * 5.7)) % 1.0
            rayon = (BULLE_MIN + (BULLE_MAX - BULLE_MIN)
                     * (0.5 + 0.5 * math.sin(graine * 2.3))) * echelle
            # Elle grossit d'un tiers en montant, comme sur le site.
            rayon *= 0.72 + 0.46 * part
            depart = x0 + large * (0.18 + 0.64 * (0.5 + 0.5 * math.sin(graine)))
            x = int(depart + BULLE_DERIVE * echelle * part)
            y = int(hauteur - part * hauteur)
            if not (x0 <= x - rayon and x + rayon <= x1):
                continue
            # Nulle en bas, pleine au premier dixième, éteinte en haut : une
            # bulle qui apparaît et disparaît net se voit apparaître.
            voile = BULLE_VOILE * min(1.0, part / 0.12) * (1.0 - part) ** 0.6
            if voile <= 0.02 or rayon < 1.5:
                continue
            teinte = tuple(int(c * voile) for c in BULLE_TRAIT)
            cv2.circle(calque, (x, y), int(rayon), teinte,
                       max(1, int(1.6 * echelle)), cv2.LINE_AA)
            cv2.circle(calque, (int(x - rayon * 0.3), int(y - rayon * 0.35)),
                       max(1, int(rayon * 0.16)),
                       tuple(int(c * voile * 0.9) for c in BULLE_TRAIT),
                       -1, cv2.LINE_AA)
    cv2.max(image, calque, image)


ENCART_DANSE_PERIODE_S = 311.0
ENCART_DANSE_S = 18.0
ENCART_DANSE_PX = 7.0
CARTE_TRAIT = (150, 128, 44)
CARTE_PLEIN = (58, 50, 18)
CARTE_POINT = (235, 215, 70)


# Un point dans le coin du pays ne doit pas finir dans le coin du carré.
# Au-delà de cette part, sur les deux axes à la fois, on n'est plus « au
# sud » : on est coincé. Los Angeles est au sud de la Californie, pas dans
# un coin — on n'y touche pas. Beaumont est au sud-est de l'hexagone, et
# sans ce tirage il tombait hors cadre.
CARTE_COIN = 0.72
# Jusqu'où tirer le cadre vers le lieu, une fois qu'on est dans un coin.
# Assez pour que le point rentre, pas assez pour rapetisser le pays.
CARTE_TIRAGE = 0.40


def _cadre_du_pays(principal: list, lat: float, lon: float, cote: int
                   ) -> tuple[float, float, float, float]:
    """L'échelle et le centre : le grand morceau remplit le carré, le lieu aussi.

    Rend serre, pas, milieu_lon, milieu_lat.
    """
    p_ouest = min(p[0] for p in principal)
    p_est = max(p[0] for p in principal)
    p_sud = min(p[1] for p in principal)
    p_nord = max(p[1] for p in principal)
    serre = math.cos(math.radians((p_nord + p_sud) / 2))
    milieu_lon = (p_ouest + p_est) / 2
    milieu_lat = (p_sud + p_nord) / 2
    fx = (lon - p_ouest) / max(p_est - p_ouest, 1e-6)
    fy = (p_nord - lat) / max(p_nord - p_sud, 1e-6)
    dans_un_coin = ((fx < 1.0 - CARTE_COIN or fx > CARTE_COIN)
                    and (fy < 1.0 - CARTE_COIN or fy > CARTE_COIN))
    if dans_un_coin:
        milieu_lon += CARTE_TIRAGE * (lon - milieu_lon)
        milieu_lat += CARTE_TIRAGE * (lat - milieu_lat)
    max_dx = max(abs((p[0] - milieu_lon) * serre) for p in principal)
    max_dy = max(abs(p[1] - milieu_lat) for p in principal)
    pas = (cote / 2) / max(max_dx, max_dy, 1e-6)
    return serre, pas, milieu_lon, milieu_lat


def pose_carte(image: np.ndarray, contours: list, lat: float, lon: float,
               x: int, y: int, cote: int, echelle: float = 1.0) -> int:
    """Le pays en silhouette, avec un point là où on est.

    Rend la hauteur occupée, parce qu'elle dépend de la forme du pays et que
    l'encart doit s'ajuster dessus : la France est à peu près carrée, le Chili
    ne le serait pas.
    """
    if not contours:
        return 0
    # L'œil reconnaît le plus grand morceau : la France, pas la Corse ;
    # la Californie, pas les Channel Islands. On cadre sur lui, on dessine
    # les autres quand même — s'ils tiennent.
    principal = max(contours, key=len)
    # Les longitudes se resserrent avec la latitude : sans ce facteur la
    # France est étalée d'un tiers en largeur et ne se reconnaît plus.
    serre, pas, milieu_lon, milieu_lat = _cadre_du_pays(principal, lat, lon, cote)
    p_sud = min(p[1] for p in principal)
    p_nord = max(p[1] for p in principal)
    haut = max(1, int((p_nord - p_sud) * pas))
    cx = x + cote // 2
    cy = y + cote // 2

    def sur_la_carte(lon_p: float, lat_p: float) -> tuple[int, int]:
        return (cx + int((lon_p - milieu_lon) * serre * pas),
                cy + int((milieu_lat - lat_p) * pas))

    for anneau in contours:
        trace = np.array([sur_la_carte(*point) for point in anneau], np.int32)
        cv2.fillPoly(image, [trace], CARTE_PLEIN, cv2.LINE_AA)
        cv2.polylines(image, [trace], True, CARTE_TRAIT,
                      max(1, int(echelle)), cv2.LINE_AA)
    px, py = sur_la_carte(lon, lat)
    rayon = max(2, int(3.5 * echelle))
    cv2.circle(image, (px, py), rayon + max(1, int(echelle)), (0, 0, 0), -1,
               cv2.LINE_AA)
    cv2.circle(image, (px, py), rayon, CARTE_POINT, -1, cv2.LINE_AA)
    return haut


def large_du_lieu(texte: str, taille: float, echelle: float) -> int:
    """Ce que prend le nom du lieu, pour que l'encart s'élargisse d'autant."""
    if not texte:
        return 0
    return cv2.getTextSize(texte, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0]


def pose_lieu(image: np.ndarray, texte: str, x: int, ligne: int,
              taille: float, echelle: float) -> None:
    """Le nom d'un lieu, posé sur la ligne de base."""
    if not texte:
        return
    cv2.putText(image, texte, (x, ligne), cv2.FONT_HERSHEY_SIMPLEX,
                taille, CYAN, 2, cv2.LINE_AA)


# Les lignes de l'horloge : badge, date, heure, commune. Date, heure et
# commune sont les mêmes cotes que l'encart de gauche.
HORLOGE_LIGNES = (MACHINE_LIGNES[0], MACHINE_LIGNES[1],
                  MACHINE_LIGNES[2], MACHINE_LIGNES[-1])


def pose_mode_degrade(image: np.ndarray, vue: tuple[int, int, int, int]) -> None:
    """La webcam s'est arrêtée. On garde la photo, le direct continue.

    Deux lignes, en bas de la fenêtre, à l'ambre. Le rouge reste au direct
    vivant : une pastille rouge sur une photo dirait le contraire de ce
    qu'elle est.
    """
    gx, gy, gw, gh = vue
    if gw < 40 or gh < 40:
        return
    echelle = image.shape[1] / 1600.0
    kicker, phrase = "DEGRADED MODE", "Webcam interrupted. Last picture. Broadcast continues."
    trait = max(1, int(round(echelle)))
    tk, tp = 0.42 * echelle, 0.34 * echelle
    (lk, hk), _ = cv2.getTextSize(kicker, cv2.FONT_HERSHEY_SIMPLEX, tk, trait)
    (lp, hp), _ = cv2.getTextSize(phrase, cv2.FONT_HERSHEY_SIMPLEX, tp, trait)
    marge = int(round(14 * echelle))
    while lp > gw - 4 * marge and tp > 0.2 * echelle:
        tp *= 0.92
        (lp, hp), _ = cv2.getTextSize(phrase, cv2.FONT_HERSHEY_SIMPLEX, tp, trait)
    pad = int(round(8 * echelle))
    ecart = int(round(6 * echelle))
    large = min(gw - 2 * marge, max(lk, lp) + 2 * pad)
    haut_panneau = hk + hp + ecart + 2 * pad
    x0 = gx + marge
    y1 = gy + gh - marge
    y0 = y1 - haut_panneau
    x1 = x0 + large
    if x1 <= x0 or y0 < gy:
        return
    panneau = image[y0:y1, x0:x1]
    if not panneau.size:
        return
    panneau[:] = (panneau.astype(np.float32) * 0.38).astype(np.uint8)
    cv2.line(image, (x0, y0), (x1 - 1, y0), AMBRE, trait, cv2.LINE_AA)
    cv2.putText(image, kicker, (x0 + pad, y0 + pad + hk),
                cv2.FONT_HERSHEY_SIMPLEX, tk, AMBRE, trait, cv2.LINE_AA)
    cv2.putText(image, phrase, (x0 + pad, y0 + pad + hk + ecart + hp),
                cv2.FONT_HERSHEY_SIMPLEX, tp, BLANC, trait, cv2.LINE_AA)


def pose_horloge(image: np.ndarray, quand: float, direct: bool = True,
                 autre: str = "REPLAY", commune: str = "",
                 carte: list | None = None,
                 ou: tuple[float, float] | None = None,
                 remue: float = 0.0,
                 photo: np.ndarray | None = None,
                 ratio: tuple | None = None) -> None:
    """L'heure qui tourne, en haut à droite, avec le point rouge des chaînes.

    Le point clignote à la seconde : c'est ce qui fait qu'un écran fixe a l'air
    vivant, et ici il ne ment pas, puisqu'il bat au rythme des images.

    Il dit « REPLAY » pendant une rediffusion, et « 3D MODEL » pendant le
    survol du terrain. Un badge « LIVE » au-dessus d'une image vieille de cinq
    jours, ou au-dessus d'un décor calculé, serait la seule faute que ce flux
    n'a pas le droit de commettre.
    """
    largeur = image.shape[1]
    echelle = largeur / 1600
    # L'heure disait « PARIS », qui était le fuseau. Personne ne le lisait
    # comme tel : sous une image du Ventoux, un spectateur lit un lieu, et
    # celui-là était faux de six cents kilomètres. La commune est vraie, elle
    # dit où regarde la caméra, et elle donne le fuseau par surcroît.
    # L'heure est le sujet de cet encart, la date en est le contexte. Les deux
    # étaient écrites à la même taille, donc rien ne disait laquelle des deux
    # bouge — et c'est celle qui bouge qu'on vient regarder. Le lieu, lui, a
    # le corps de Los Angeles : ce n'est plus un sous-titre, c'est le
    # pendant de l'autre côté de la planète.
    jour, heure = _date_et_heure(quand, PARIS)
    lignes = [jour, heure]
    pas = int(34 * echelle)
    marge = int(14 * echelle)
    sommet = int(RUBAN_H * echelle) + int(remue)
    taille = 0.7 * echelle
    lieu = (commune or "").upper()
    dessin = bool((carte and ou) or (photo is not None and photo.size))
    large = max([cv2.getTextSize(l, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0]
                 for l in lignes]
                + [large_du_lieu(lieu, LIEU_CORPS * echelle * HORLOGE_LIEU, echelle)]
                + ([int(ENCART_LARGE * echelle)] if dessin else []))
    badge = "LIVE" if direct else autre
    large = max(large,
                cv2.getTextSize(heure, cv2.FONT_HERSHEY_SIMPLEX,
                                0.95 * echelle, 2)[0][0],
                cv2.getTextSize(badge, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0] + pas)
    gauche = largeur - large - 2 * marge
    badge_y, date_y, heure_y, ville_y = (
        sommet + int(r * echelle) for r in HORLOGE_LIGNES)
    haut_carte = sommet + int(ENCART_DESSIN * echelle)
    jack = int(JACKPOT_H * echelle) if ratio is not None else 0
    bas_total = (int(ENCART_BAS * echelle) + int(remue) if dessin
                 else ville_y + marge + jack)
    bas = bas_total - jack
    # La même bande que les jauges d'en face, vide ici : les deux
    # silhouettes et les deux disques s'arrêtent sur la même ligne, et
    # température et charge passent dessous, seulement du côté machine.
    bande = int(JAUGE_BANDE * echelle) if dessin else 0
    fond_encart(image, (gauche, sommet), (largeur - 1, bas - 1), echelle)
    rayon = int(7 * echelle)
    x = gauche + marge
    y = badge_y
    # Le point rouge appartient au direct et à lui seul : partout ailleurs sur
    # terre il veut dire « ça tourne, là, maintenant ». Fixe et rouge au-dessus
    # d'une archive, il disait l'inverse de ce qu'il est — et c'est ce qui
    # faisait de la rediffusion un moment inquiétant plutôt qu'un moment
    # d'archive. Hors direct il passe à l'ambre, comme le mot qu'il accompagne.
    if direct and int(quand) % 2 == 0:
        cv2.circle(image, (x + rayon, y - rayon), rayon, ROUGE, -1)
    elif not direct:
        cv2.circle(image, (x + rayon, y - rayon), rayon, AMBRE, -1)
    cv2.putText(image, badge, (x + pas, y), cv2.FONT_HERSHEY_SIMPLEX, taille,
                BLANC if direct else AMBRE, 2, cv2.LINE_AA)
    trait = y + int(round(9 * echelle))
    cv2.line(image, (x, trait), (largeur - 1 - marge, trait),
             tuple(int(c * 0.55) for c in CYAN), max(1, int(round(echelle))),
             cv2.LINE_AA)
    pose_date_heure(image, x, date_y, heure_y, jour, heure, echelle)
    pose_lieu(image, lieu, x, ville_y, LIEU_CORPS * echelle * HORLOGE_LIEU, echelle)
    if dessin:
        teinte = tamise_la_photo(photo) if photo is not None else None
        pose_carte_et_photo(
            image, x, haut_carte, largeur - marge - x,
            bas - haut_carte - marge - bande, carte, ou, teinte, echelle)
    if ratio is not None:
        pose_jackpot(image, gauche, largeur - 1, bas,
                     int(ratio[0]), int(ratio[1]), ratio[2], quand)


def _entree(url: str, recul: int) -> subprocess.Popen:
    commande = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        # Le retard, pris chez le serveur plutôt qu'en mémoire.
        "-live_start_index", str(-recul),
        "-i", url, "-an",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ]
    return subprocess.Popen(commande, stdout=subprocess.PIPE, bufsize=10 ** 8)


# Le temps qu'on laisse à l'arrivée avant de la rouvrir une deuxième fois. Une
# sortie qui lâche tout de suite après avoir été rouverte dit que la chaîne n'a
# plus de direct du tout : rouvrir en boucle ne le ferait pas revenir, ça ne
# ferait que marteler l'arrivée de YouTube.
REPRISE_SORTIE_S = 15.0


def _ferme_sortie(sortie: subprocess.Popen | None, son: int | None) -> None:
    """Rend l'arrivée et le descripteur de son, sans rien laisser derrière."""
    if son is not None:
        try:
            os.close(son)
        except OSError:
            pass
    if sortie is not None and sortie.stdin is not None:
        try:
            sortie.stdin.close()
        except OSError:
            pass
        try:
            sortie.wait(timeout=30)
        except subprocess.TimeoutExpired:
            sortie.kill()


def _sortie(cible: str, largeur: int, hauteur: int, images_par_s: int,
            debit: str, sortie_par_s: int = 25,
            vitesse: str = "veryfast") -> tuple[subprocess.Popen, int]:
    """La sortie, et le descripteur par lequel on lui donne le son.

    Deux tuyaux parce qu'un processus n'a qu'une entrée standard et qu'il faut
    en nourrir deux. L'image passe par elle, le son par un descripteur de plus
    que ffmpeg sait lire sous le nom « pipe:N ».
    """
    lecture, ecriture = os.pipe()
    commande = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        # Des files d'attente généreuses des deux côtés : sans elles, un
        # ffmpeg qui lit l'image pendant qu'on écrit le son peut s'arrêter en
        # attendant l'autre tuyau, et les deux processus s'attendent à jamais.
        "-thread_queue_size", "512",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{largeur}x{hauteur}", "-r", str(images_par_s), "-i", "pipe:0",
        "-thread_queue_size", "512",
        "-f", "s16le", "-ar", str(ECHANTILLONS_S), "-ac", str(VOIES), "-i", f"pipe:{lecture}",
        # Le Pi 5 n'a aucun encodeur matériel : il ne reste que le logiciel, et
        # « veryfast » est le compromis mesuré qui tient le temps réel sans
        # manger les cœurs dont la veille a besoin.
        # Le Pi 5 n'a aucun encodeur matériel et il n'a pas de ventilateur : à
        # vingt-cinq images par seconde en continu, avec la veille à côté, il a
        # touché quatre-vingt-trois degrés et le bridage thermique s'est
        # allumé. Ces deux réglages sont là pour qu'on puisse redescendre sans
        # toucher au code, et pour qu'on puisse remonter le jour où la machine
        # saura se refroidir.
        "-c:v", "libx264", "-preset", vitesse, "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", "-b:v", debit, "-maxrate", debit, "-bufsize", "4M",
        # La source ne donne que six images par seconde et YouTube se méfie en
        # dessous de vingt-cinq. On le laisse dupliquer lui-même plutôt que de
        # pousser quatre fois plus d'octets dans le tuyau : une image répétée
        # ne coûte presque rien à x264, et c'est exactement la configuration
        # mesurée à 2,36 fois le temps réel sur ce Pi.
        "-r", str(sortie_par_s),
        # Une image-clé toutes les deux secondes, ce que YouTube demande pour
        # découper le direct en segments.
        "-g", str(sortie_par_s * 2),
        "-c:a", "aac", "-b:a", "128k",
    ]
    commande += ["-f", "flv", cible] if cible.startswith("rtmp") else [cible]
    process = subprocess.Popen(commande, stdin=subprocess.PIPE, pass_fds=(lecture,))
    os.close(lecture)
    return process, ecriture


# Quelques secondes de photographie autour d'une prise, gardées pour monter.
# L'avant laisse voir d'où la chose arrive. L'après laisse voir qu'elle est
# passée. Une autre prise dans le quart de minute qui suit allonge le même
# fichier : c'est une seule dépêche, pas deux plans qu'il faudrait recoller.
RUSH_AVANT_S = 3.0
RUSH_APRES_S = 4.0
RUSH_ATTENTE_S = 15.0
RUSH_PLAFOND_S = 90.0
RUSH_LARGE = 1280


def _jpeg_rush(image: np.ndarray) -> bytes:
    """La photographie, assez légère pour en garder une file sans gêner l'envoi."""
    hauteur, largeur = image.shape[:2]
    if largeur > RUSH_LARGE:
        echelle = RUSH_LARGE / largeur
        image = cv2.resize(
            image, (RUSH_LARGE, max(2, int(hauteur * echelle))),
            interpolation=cv2.INTER_AREA)
    ok, code = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    return code.tobytes() if ok else b""


def _slug_rush(noms: list[str]) -> str:
    mots = []
    for nom in noms:
        mot = re.sub(r"[^0-9A-Za-z]+", "", nom).lower()[:16]
        if mot and mot not in mots:
            mots.append(mot)
    return "-".join(mots[:4]) or "prise"


def grave_rush(dossier: Path, images: list[bytes], noms: list[str],
               fps: float, quand: float) -> None:
    """Écrit le bout de film. Un échec ici ne doit jamais arrêter le direct."""
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        heure = datetime.fromtimestamp(quand, PARIS).strftime("%Y%m%d-%H%M%S")
        chemin = dossier / f"{heure}-{_slug_rush(noms)}.mp4"
        if chemin.exists():
            chemin = dossier / f"{heure}-{_slug_rush(noms)}-{int(quand)}.mp4"
        process = subprocess.Popen(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "image2pipe", "-framerate", str(max(1.0, fps)), "-i", "-",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
             str(chemin)],
            stdin=subprocess.PIPE)
        assert process.stdin is not None
        for image in images:
            process.stdin.write(image)
        process.stdin.close()
        process.wait(timeout=120)
        if process.returncode == 0 and chemin.is_file():
            log.info("Rush %s · %d images · %s", chemin.name, len(images),
                     ", ".join(noms) or "prise")
        else:
            log.warning("Rush non écrit : %s", chemin.name)
    except Exception:
        log.warning("Rush non écrit", exc_info=True)


class Journal:
    """Quelques secondes du direct, rectangle et good catch compris.

    Ce qu'on garde est l'image déjà composée : la détection du mouvement,
    le nom de la classe, et GOOD CATCH. Pendant le survol, la détection
    est dans le coin du direct, et ce passage est gardé aussi.

    Une prise ouvre un sujet. Une autre prise dans les quinze secondes
    l'allonge : la file des voitures tient dans un seul fichier. Le fichier
    part quand plus rien n'a suivi, avec trois secondes d'avant et quatre
    d'après. Au-delà d'une minute et demie, on ferme et le suivant recommence.
    """

    def __init__(self, dossier: Path, fps: float, ecrit=grave_rush) -> None:
        self.dossier = dossier
        self.fps = fps
        self.ecrit = ecrit
        self.anneau: deque[tuple[float, bytes]] = deque()
        self.ouvert: dict | None = None

    def voit(self, image: np.ndarray, quand: float) -> None:
        try:
            self.note(quand, _jpeg_rush(image))
        except Exception:
            log.warning("Rush illisible", exc_info=True)

    def note(self, quand: float, jpeg: bytes) -> None:
        if jpeg:
            self.anneau.append((quand, jpeg))
        self._taille(quand)

    def sujet(self, quand: float, nom: str) -> None:
        """Une prise. Elle ouvre, ou elle rallonge ce qui est encore chaud."""
        if self.ouvert and quand - self.ouvert["fin"] <= RUSH_ATTENTE_S:
            self.ouvert["fin"] = quand
            if nom and nom not in self.ouvert["noms"]:
                self.ouvert["noms"].append(nom)
            return
        if self.ouvert:
            self._ferme()
        self.ouvert = {"debut": quand, "fin": quand, "noms": [nom] if nom else []}

    def relache(self, quand: float) -> None:
        """Ferme le sujet si plus rien ne l'a suivi, ou s'il dure trop."""
        if not self.ouvert:
            return
        if quand - self.ouvert["debut"] >= RUSH_PLAFOND_S:
            self.ouvert["fin"] = max(self.ouvert["fin"], quand)
            self._ferme()
        elif quand >= self.ouvert["fin"] + RUSH_ATTENTE_S:
            self._ferme()

    def _taille(self, quand: float) -> None:
        plancher = quand - RUSH_AVANT_S - 1.0
        if self.ouvert:
            plancher = min(plancher, self.ouvert["debut"] - RUSH_AVANT_S - 1.0)
        while self.anneau and self.anneau[0][0] < plancher:
            self.anneau.popleft()

    def _ferme(self) -> None:
        ouvert = self.ouvert
        self.ouvert = None
        if not ouvert:
            return
        debut = ouvert["debut"] - RUSH_AVANT_S
        fin = ouvert["fin"] + RUSH_APRES_S
        images = [jpeg for t, jpeg in self.anneau if debut <= t <= fin]
        if len(images) < 2:
            return
        self._lancer(self.dossier, images, list(ouvert["noms"]), self.fps,
                     ouvert["debut"])

    def _lancer(self, dossier: Path, images: list[bytes], noms: list[str],
                fps: float, quand: float) -> None:
        threading.Thread(
            target=self.ecrit, args=(dossier, images, noms, fps, quand),
            daemon=True).start()


def diffuse(cfg: dict, racine: Path, cible: str, duree_s: float | None, recul: int) -> None:
    muet = not cfg.get("stream_musique", True)
    musique = Musique(racine / "data" / "musique", racine, muet=muet)
    if muet:
        log.warning("Musique coupée : le flux part en silence")
    if musique.session is None:
        log.warning("Aucune musique dans data/musique : le flux sortira muet")
    media, dernier, segment = attends_la_webcam(cfg["stream_url"])
    log.info("Segments de %.1f s, dernier publié il y a %.1f s", segment, _maintenant() - dernier)

    entree = _entree(cfg["stream_url"], recul)
    assert entree.stdout is not None
    # La toile, et donc ce que l'encodeur doit avaler chaque image.
    #
    # Elle était figée à 1920x1080, et c'est ce qui a fini par lâcher. Mesuré
    # sur cette machine en priorité basse et chargée comme elle l'est : 1,71 fois
    # le temps réel en 1080p, contre 2,36 quand ce choix a été fait. La marge a
    # fondu à mesure que la veille s'est alourdie, et un encodeur qui tombe sous
    # le temps réel envoie l'image en retard — YouTube le dit alors lui-même,
    # « pas assez de données vidéo », et finit par couper.
    #
    # En 1280x720 le même banc donne 2,66 fois le temps réel : la marge revient
    # au double de ce qu'il faut. C'est la moitié des pixels, et ça se voit un
    # peu ; une diffusion qui tient vaut mieux qu'une définition qui coupe. Le
    # réglage est dans la configuration pour qu'on remonte sans toucher au code
    # le jour où la machine aura de quoi.
    # Deux tailles, et il ne faut surtout pas les confondre : la webcam publie
    # du 1920x1080 et c'est sur ces octets-là que la lecture du tuyau se cale,
    # tandis que la toile qu'on encode peut être plus petite. Les avoir
    # mélangées a suffi à casser l'antenne : le lecteur prenait 1280x720x3
    # octets par image dans un flot qui en livrait deux fois plus, donc chaque
    # image commençait au milieu de la précédente et l'écran s'est mis à
    # montrer la montagne deux fois, déchirée en diagonale.
    source_l, source_h = 1920, 1080
    octets = source_l * source_h * 3
    largeur, hauteur = cfg["stream_size"]
    sortie = son = None
    # Les images déjà remises à la sortie en cours. Comptées à part de « images »,
    # qui totalise la journée : celle-ci repart à zéro avec chaque sortie, parce
    # que c'est elle qui donne l'heure de la vidéo chez le spectateur.
    diffusees = 0
    verseur: threading.Thread | None = None
    coupe = threading.Event()
    coupe_son = threading.Event()
    ouverte_a = 0.0
    chaine = cfg.get("youtube_chaine")
    salle = Salle()
    if chaine and cible.startswith("rtmp"):
        threading.Thread(target=veille_le_direct, args=(chaine, coupe, racine),
                         daemon=True).start()
        threading.Thread(target=veille_salle, args=(chaine, coupe, salle),
                         daemon=True).start()
    debut = _maintenant()
    # L'heure de la première image montrée : le bord du direct, moins ce qu'on
    # a reculé. Tout le reste s'en déduit par le compte des images.
    origine = dernier - (recul - 1) * segment
    # L'ancre de l'entrée en cours, et le compte d'images depuis son ouverture.
    # Séparées d'« origine », qui reste le début de l'émission : c'est lui qui
    # donne sa seconde au lecteur de musique, et il ne doit pas reculer parce
    # que la webcam a hoqueté.
    ouvert = origine
    vues = 0
    # L'écart entre l'heure de la montagne et l'heure d'ici, fixé sur la
    # première image et tenu ensuite. None tant qu'on n'a pas vu cette image.
    cadence: float | None = None
    images = 0
    vus: list[dict] = []
    cherches: list[dict] = []
    tableau: dict = {"paris": {}, "los_angeles": {}}
    ruban: list[tuple[str, tuple[int, int, int]]] = []
    prog: dict = dict(PROG_VIDE)
    lieu = ligne_lieu(cfg.get("camera") or {}, altitude_camera(racine))
    relu = 0.0
    # Les contours que la veille utilise pour savoir où est la chaussée servent
    # aussi à placer les deux numéros : le rond-point dit où l'éléphant danse,
    # le ciel dit jusqu'où le tapis peut descendre sans toucher la montagne.
    # Lus une fois, et pardonnés s'ils manquent — une caméra sans carte garde
    # sa diffusion, elle perd seulement ses fantaisies.
    contours = {}
    try:
        contours = json.loads(
            (racine / cfg["zones"]).read_text(encoding="utf-8")).get("polygons") or {}
    except (OSError, ValueError, KeyError):
        log.info("Pas de contour du ciel : ni tapis ni sous-marin")
    contour_ciel = contours.get("sky")
    # Le lampadaire du rond-point, s'il a été mesuré. Il faut les trois points :
    # la lanterne, que la carte donne, et les deux bouts du poteau, qu'on a
    # relevés sur l'image. Sans eux on ne dessine rien plutôt que de deviner.
    lampadaire = None
    try:
        lampe = (json.loads((racine / "config" / "scene.json")
                            .read_text(encoding="utf-8")).get("lamps") or [{}])[0]
        if all(lampe.get(coin) for coin in ("head", "shoulder", "foot")):
            lampadaire = (lampe["head"], lampe["shoulder"], lampe["foot"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        pass
    if lampadaire is None:
        log.info("Lampadaire non mesuré : il restera celui de la webcam")
    # La piste de ski, projetée hors ligne depuis OpenStreetMap par
    # scripts/build_piste.py. Absente, personne ne descend.
    # Les bâtiments viennent du même fichier et du même principe, relevés par
    # scripts/build_batiments.py. Absents, rien ne se dessine.
    try:
        decor = json.loads((racine / "config" / "scene.json")
                           .read_text(encoding="utf-8"))
        piste = (decor.get("piste") or {}).get("trace")
        batiments = decor.get("buildings") or []
    except (OSError, ValueError):
        piste, batiments = None, []
    if not piste:
        log.info("Pas de tracé de piste : personne ne descendra")
    # Le seul numéro qu'on ne dessine pas soi-même. Lu une fois, et absent sans
    # conséquence : il ne passe pas, c'est tout.
    sous_marin = charge_vignette(racine / "assets" / "sous-marin.png")
    # L'autre numéro qu'on ne dessine pas : la sculpture, découpée sur un plein
    # cadre de jour. Et de quoi se souvenir qu'il a déjà grogné à ce tour-ci,
    # puisque la voix ne doit partir qu'une fois et que la boucle repasse ici
    # chaque image.
    ours = charge_vignette(racine / "data" / "ours.png")
    preuve_ours = cv2.imread(str(racine / "assets" / "ours-maison.jpg"))
    ours_dit: tuple[int, int] = (-1, -1)
    machine_dit = -1.0
    dogmazic_dit = -1.0
    agenda, agenda_credit, agenda_lu = [], "", 0.0
    # La photo de la machine qui fait tout ça. Lue en BGR et non en BGRA :
    # c'est une photo, elle n'a pas de transparence.
    photo_machine = cv2.imread(str(racine / "assets" / "machine.jpg"))
    # Le chien orange, déjà un disque : on le pose comme la photo du Pi.
    photo_dogmazic = cv2.imread(str(racine / "assets" / "dogmazic.png"),
                               cv2.IMREAD_UNCHANGED)
    photo_butterbane = cv2.imread(str(racine / "assets" / "butterbane-logo.jpg"))
    photo_never = cv2.imread(str(racine / "assets" / "never.jpg"))
    # Le trampoline du village, côté français : le pendant du disque de
    # gauche. Recadré une fois, teinté à chaque image comme le Raspberry.
    photo_trampoline = cv2.imread(str(racine / "assets" / "trampoline.jpg"))
    # On démarre comme si on venait de voir quelque chose : une rediffusion à
    # la première seconde du direct donnerait l'impression que rien ne marche.
    dernier_vu = origine
    dernier_mouvement = origine
    attrape = origine - 1000.0
    attrape_nom = ""
    attrape_teinte = ROUGE
    # Les prises déjà fêtées, pour ne pas les fêter à chaque image des quatre
    # secondes où leur rectangle est à l'écran. Purgé à chaque fête.
    fetes: set[float] = set()
    journal = Journal(racine / "data" / "rushs", cfg["stream_fps"])
    coloriage = Coloriage(racine / "data" / "coloriage.jsonl")
    if cfg.get("coloriage_jeton"):
        try:
            coloriage.ouvre(str(cfg["coloriage_jeton"]), COLORIAGE_PORT)
            log.info("Coloriage sur le port %s", COLORIAGE_PORT)
        except OSError:
            log.warning("Coloriage injoignable", exc_info=True)
    # Importé ici et pas en tête de fichier : c'est main() qui pose la racine
    # du dépôt sur le chemin, et stream.py doit pouvoir être lancé comme un
    # script depuis n'importe où.
    from watcher.scene import solar_elevation
    machine = etat_machine(racine)
    hauteur_soleil: float | None = None
    soleil: tuple[float, float] | None = None
    relief = charge_relief(racine, cfg["camera"])
    almanach: dict = {}
    # Les heures de demain aussi : après le coucher, c'est d'elles que le ruban
    # a besoin, et un balayage de soixante-dix millisecondes fait deux fois par
    # jour ne se sent pas.
    demain: dict = {}
    jour_calcule = None
    bonjour = origine - 10_000.0
    minuit: dict = {}
    nom_du_lieu = (cfg.get("camera") or {}).get("nom") or "Ventoux"
    # La commune, résolue une fois pour toutes par scripts/commune_du_site.py
    # depuis la position de la caméra. Une autre caméra n'a qu'à relancer le
    # script : rien ici ne connaît le Ventoux.
    try:
        commune = str(((json.loads((racine / "config" / "scene.json")
                                   .read_text(encoding="utf-8"))
                        .get("site") or {}).get("commune")) or "")
    except (OSError, ValueError):
        commune = ""
    machine_ou = cfg.get("machine") or {}
    ville = str(machine_ou.get("ville") or "")
    try:
        carte_pays = json.loads((racine / "assets" / "carte-pays.json")
                                .read_text(encoding="utf-8")).get("contours")
    except (OSError, ValueError):
        carte_pays = None
    try:
        carte_californie = json.loads(
            (racine / "assets" / "carte-californie.json")
            .read_text(encoding="utf-8")).get("contours")
    except (OSError, ValueError):
        carte_californie = None
    try:
        vise = json.loads((racine / "config" / "scene.json")
                          .read_text(encoding="utf-8")).get("pose") or {}
        ou_camera = (float(vise["lat"]), float(vise["lon"]))
    except (OSError, ValueError, KeyError, TypeError):
        ou_camera = None
    # Loin en arrière, comme « bonjour » : à zéro, le flux s'ouvrirait sur
    # « BOOOOORING » pendant trois secondes, ce qui est une drôle de carte de
    # visite pour une veille qui vient de démarrer.
    dernier_ennui = origine - 10_000.0
    pensee_jour, pensee_rang, pensee_etape, pensee_feu = _pensee_lue(racine)
    dijon_jour, dijon_rang = _dijon_lue(racine)
    dijon_feu = 0.0
    dijon_heure = "23:00"
    never_jour = _never_lue(racine)
    never_feu = 0.0
    salle_feu = 0.0
    salle_tenue = SALLE_TENUE_S
    salle_prochain = time.time() + SALLE_PREMIER_S
    salle_abonnes: int | None = None
    salle_direct: int | None = None
    deploie_dit = False
    # Un quart d'heure en arrière : si la vallée est déjà dans le brouillard au
    # moment où le flux démarre, on le dit tout de suite.
    gris_depuis = origine - BROUILLARD_PAUSE_S
    mot_gris = ""
    rediff: tuple[dict, float] | None = None
    fin_rediff = origine
    reste: list[dict] = []
    # Ce qu'on a déjà remontré ce soir, et la date de l'historique quand on a
    # fait la réserve : relire à chaque fois serait inutile, ne relire jamais
    # enterrait les prises du jour.
    montrees: set[str] = set()
    historique_lu = 0.0
    images3d = charge_vue3d(racine)
    survol: float | None = None
    survol_de_jour = True
    fin_survol = origine
    if images3d:
        log.info("Survol du terrain : %d images", len(images3d))
    tirage = random.Random()
    figee = False
    photo_figee: np.ndarray | None = None
    sonde_webcam = 0.0
    try:
        figee = playlist_figee(_lire(media), _maintenant())
    except Exception:
        log.warning("Playlist illisible au départ", exc_info=True)
    if figee:
        photo_figee = _derniere_image(entree, octets, source_h, source_l)
        entree.kill()
        if photo_figee is None:
            figee = False
            entree = _entree(cfg["stream_url"], recul)
            assert entree.stdout is not None
        else:
            log.info("Webcam interrompue : dernière image tenue, le direct continue")
    try:
        while True:
            tenu = False
            if figee and photo_figee is not None:
                time.sleep(1.0 / cfg["stream_fps"])
                if _maintenant() - sonde_webcam >= ATTENTE_PAS_S:
                    sonde_webcam = _maintenant()
                    try:
                        frais = playlist_media(cfg["stream_url"])
                        if not playlist_figee(_lire(frais), _maintenant()):
                            media, dernier, segment = attends_la_webcam(cfg["stream_url"])
                            entree = _entree(cfg["stream_url"], recul)
                            assert entree.stdout is not None
                            ouvert = dernier - (recul - 1) * segment
                            vues = 0
                            cadence = None
                            figee = False
                            log.info("La webcam a repris")
                            continue
                    except Exception:
                        log.info("Webcam toujours interrompue")
                image = photo_figee.copy()
                quand = ouvert
                montre = _maintenant()
                tenu = True
            else:
                brut = entree.stdout.read(octets)
                if len(brut) < octets:
                    # Le raisonnement d'attends_la_webcam, appliqué en cours de
                    # route. Au démarrage on a appris à patienter plutôt qu'à
                    # quitter, parce qu'un départ rouvre la connexion RTMP et
                    # qu'une arrivée qui clignote fait fermer le direct. Ici on
                    # quittait quand même : la webcam s'est tarie vingt-cinq fois
                    # dans la journée, systemd a tout rouvert chaque fois, et
                    # YouTube a fini par couper. L'entrée se rouvre seule ; la
                    # sortie ne se touche pas.
                    #
                    # Sauf quand la playlist est close : là, rouvrir rejoue la
                    # dernière minute en boucle et l'horloge ment. On garde
                    # cette image, l'heure du direct, et on continue.
                    log.warning("Le flux s'est tari après %d images : on rouvre l'entrée", images)
                    entree.kill()
                    gel = photo_figee is not None
                    if gel:
                        try:
                            gel = playlist_figee(_lire(playlist_media(cfg["stream_url"])),
                                                 _maintenant())
                        except Exception:
                            gel = False
                    if gel:
                        figee = True
                        sonde_webcam = _maintenant()
                        rediff = None
                        survol = None
                        log.warning("Webcam interrompue : on tient la dernière image, "
                                    "le direct continue")
                        continue
                    _, dernier, segment = attends_la_webcam(cfg["stream_url"])
                    entree = _entree(cfg["stream_url"], recul)
                    assert entree.stdout is not None
                    # La nouvelle entrée repart au bord du direct : l'ancre et le
                    # compte d'images la suivent, et la cadence se refait sur la
                    # première image pour retrouver les mêmes quarante-deux
                    # secondes de retard.
                    ouvert = dernier - (recul - 1) * segment
                    vues = 0
                    cadence = None
                    continue
                quand = ouvert + vues / cfg["stream_fps"]
                vues += 1
                images += 1
                montre = quand
            # L'instant où l'image qu'on s'apprête à dessiner sera regardée.
            # Posé avant de dessiner quoi que ce soit, puisque c'est l'heure
            # que le crédit musical va lire.
            musique.a_l_ecran(diffusees / cfg["stream_fps"])
            if montre - relu >= 2.0:
                vus = identifications(racine / "data" / "events.json", quand - TENUE_S - 60)
                cherches = lire_recherches(racine / "data" / "cherche.json")
                tableau = lire_score(racine / "data" / "score.json")
                machine = etat_machine(racine)
                # Le soleil est calculé, pas lu : aucun service à interroger,
                # aucune panne de réseau ne peut faire rater le lever.
                haut = solar_elevation(datetime.fromtimestamp(montre, timezone.utc),
                                       cfg["camera"]["lat"], cfg["camera"]["lon"])
                if (hauteur_soleil is not None and hauteur_soleil < HORIZON <= haut
                        and montre - bonjour > 12 * 3600):
                    bonjour = montre
                    if musique.matins:
                        musique.dis(tirage.choice(musique.matins))
                    log.info("Lever du soleil : bonjour %s", nom_du_lieu)
                hauteur_soleil = haut
                ciel = lecture_du_ciel(racine / "data" / "view.json")
                # Les heures du soleil ne bougent pas dans la journée : on les
                # cherche au premier tour et au passage de minuit, pas toutes
                # les deux secondes.
                aujourdhui = datetime.fromtimestamp(montre, PARIS).date()
                if aujourdhui != jour_calcule:
                    jour_calcule = aujourdhui
                    try:
                        almanach = heures_du_soleil(relief, cfg["camera"], montre)
                        demain = heures_du_soleil(relief, cfg["camera"],
                                                  montre + 86400)
                    except Exception:
                        log.warning("Heures du soleil illisibles", exc_info=True)
                        almanach = demain = {}
                ruban = morceaux_ruban(lieu, ciel,
                                       morceaux_soleil(almanach, montre, demain))
                # Ce que la veille lit sur l'image passe avant ce que dit le
                # service : il arrive qu'il annonce « couvert » sur une vallée
                # pendant qu'il fait grand soleil à mille quatre cents mètres.
                temps = str(ciel.get("webcam") or ciel.get("api") or "")
                soleil = (ou_est_le_soleil(cfg["camera"], montre, hauteur / largeur)
                          if soleil_absent(relief, cfg["camera"], montre, temps) else None)
                mot_gris = BROUILLARD_MOTS.get(temps, "")
                prog = PROG_VIDE if muet else musique.programme()
                relu = montre
            pistes = pistes_visibles(cherches, quand)
            nommes = [vu for vu in vus if not cherche_encore(vu, pistes, quand)]
            if not tenu:
                image = np.frombuffer(brut, np.uint8).reshape(source_h, source_l, 3).copy()
                photo_figee = image.copy()
            # D'abord la teinte, ensuite seulement ce qu'on dessine dessus.
            # Pas sur la photo tenue : c'est une photographie, plus un traitement.
            if not figee:
                applique_teinte(image, *teinte_du_moment(quand - origine))
            # Le soleil d'enfant avant les filtres : il fait partie de l'image
            # du ciel, donc il se pixellise et il ondule avec elle.
            if not figee and soleil is not None:
                pose_soleil_dessine(image, soleil, quand - origine)
            # Le lampadaire au même endroit du traitement, et pour la même
            # raison : il n'est pas posé sur la vitre, il remplace un objet du
            # paysage. Il doit donc prendre la teinte et le grain comme le
            # reste de l'image, sans quoi il flotterait dessus.
            #
            # La nuit seulement, parce que c'est la nuit que la vraie lampe est
            # allumée. De jour, un lampadaire de livre d'images planté au
            # milieu d'une photo en plein soleil ne serait plus un dessin posé
            # sur un objet, ce serait un objet en moins.
            if not figee and lampadaire is not None and (hauteur_soleil or -90.0) <= HORIZON:
                pose_lampadaire(image, *lampadaire, quand - origine)
            # Le grain ne tombe jamais sur une prise. Tout l'intérêt d'un
            # rectangle rouge est qu'on puisse regarder ce qu'il entoure, et
            # une voiture en gros carrés n'est plus une voiture.
            if not figee and quand - dernier_vu > TENUE_S:
                applique_effet(image, *effet_du_moment(quand - origine), quand - origine)
            # La fête suit le rectangle, pas l'arrivée de la fiche.
            if not figee and quand - attrape > ATTRAPE_S:
                neuve = prise_a_feter(vus, quand, fetes)
                if neuve is not None and cherche_encore(neuve, pistes, quand):
                    neuve = None
                if neuve is not None:
                    fetes = {t for t in fetes if t > quand - 3600} | {neuve["t"]}
                    attrape, attrape_nom = quand, neuve["label"]
                    attrape_teinte = teinte_de(neuve)
                    if musique.felicitations:
                        musique.dis(tirage.choice(musique.felicitations))
                    log.info("Prise à l'écran : %s — %s", neuve["label"],
                             musique.voix_dit or "sans voix")
                    journal.sujet(quand, str(neuve.get("label") or ""))
            poses = visibles(vus, quand) or bool(pistes)
            if poses:
                dernier_vu = quand
                # L'horloge de l'ennui est à part, et c'est tout l'intérêt :
                # « dernier_vu » est remis à zéro par les rediffusions, donc
                # s'en servir ferait dire « boring » vingt minutes après une
                # rediffusion, c'est-à-dire juste après qu'il s'est passé
                # quelque chose à l'écran. Seule une vraie détection compte.
                dernier_mouvement = quand
                rediff = None
            elif not figee and quand - dernier_vu > CREUX_S:
                # Rien depuis deux minutes : on va chercher dans ce qu'on a
                # déjà attrapé. Sans remise, pour ne pas remontrer le même
                # camion toute la nuit.
                if rediff is None and quand - fin_rediff > REDIFF_PAUSE_S:
                    marque = marque_historique(racine)
                    if not reste or marque != historique_lu:
                        historique_lu = marque
                        fonds = archives(racine)
                        reste = [f for f in fonds if str(f["photo"]) not in montrees]
                        if not reste:
                            # Tout a déjà été montré : on repart pour un tour
                            # plutôt que de se taire.
                            montrees.clear()
                            reste = fonds
                        reste = ordre_de_rediffusion(reste, tirage)
                    choisie = reste.pop() if reste else None
                    if choisie is not None:
                        montrees.add(str(choisie["photo"]))
                        log.info("Rediffusion : %s du %s", choisie["label"], choisie["t"])
                        # Et on l'annonce en chantant. La rediffusion était le
                        # seul moment du flux qui faisait peur : l'écran
                        # s'assombrissait d'un coup et une image floue de
                        # surveillance apparaissait au milieu, sans un mot.
                        # Ce n'était pas voulu — on voulait ne pas mentir sur
                        # la date — mais c'est ce que ça faisait. Une voix qui
                        # chante le mot dit exactement la même chose et ne fait
                        # peur à personne : une alarme ne chante pas.
                        if musique.redifferes:
                            musique.dis(tirage.choice(musique.redifferes))
                    rediff = (choisie, quand) if choisie is not None else None
                    dernier_vu = quand if rediff is None else dernier_vu
            if quand - attrape <= ATTRAPE_S:
                pose_attrape(image, quand - attrape, attrape_nom)
            # Le brouillard se dit entre deux prises et jamais par-dessus : une
            # voiture qui passe est plus intéressante que le temps qu'il fait.
            if (not figee and mot_gris and quand - gris_depuis > BROUILLARD_PAUSE_S
                    and quand - attrape > ATTRAPE_S and not musique.parle()):
                gris_depuis = quand
                if musique.brouillards:
                    musique.dis(tirage.choice(musique.brouillards))
                log.info("Le flux dit « %s »", mot_gris)
            if (not figee and musique.repliques and quand - dernier_mouvement > ENNUI_S
                    and quand - dernier_ennui > ENNUI_S):
                musique.dis(tirage.choice(musique.repliques))
                dernier_ennui = quand
                log.info("Rien depuis %.0f min : le flux dit « %s »",
                         (quand - dernier_mouvement) / 60, musique.voix_dit)
            a_poser = None
            if rediff is not None:
                if quand - rediff[1] <= REDIFF_TENUE_S:
                    a_poser = rediff[0]
                else:
                    rediff, fin_rediff, dernier_vu = None, quand, quand
            # Le relief, quand rien ne se passe et pas trop souvent.
            #
            # Il ne bouge pas. Le point de vue est celui de la caméra, donc
            # le rectangle de la veille se pose dessus sans mentir sur
            # l'endroit. De jour le rendu reste en plein soleil. De nuit il
            # est le même cadre, baissé : un soleil collé sur une pente noire
            # dirait la mauvaise heure.
            #
            # Le soleil au-dessus de l'horizon reste la condition physique :
            # c'est elle qui décide lequel des deux on pose, pas une heure.
            fait_jour = (hauteur_soleil or -90.0) > HORIZON
            tenue = VUE3D_TENUE_S if survol_de_jour else VUE3D_NUIT_S
            if survol is not None and (fait_jour != survol_de_jour
                                       or quand - survol > tenue):
                fin_survol, survol = quand, None
            elif (not figee and survol is None and images3d and rediff is None and a_poser is None
                  and quand - dernier_vu > CREUX_S
                  and quand - fin_survol > VUE3D_PAUSE_S):
                survol, survol_de_jour = quand, fait_jour
                log.info("Relief fixe (%s) pendant %.0f s",
                         "jour" if fait_jour else "nuit",
                         VUE3D_TENUE_S if fait_jour else VUE3D_NUIT_S)
            vue = image
            if survol is not None:
                dessus = vue3d_poste(images3d, nuit=not survol_de_jour)
                if dessus is None:
                    fin_survol, survol = quand, None
                else:
                    # La maquette de nuit est un rendu de jour baissé. Sans
                    # cette lanterne elle n'a pas de lampe allumée.
                    if not survol_de_jour and lampadaire is not None:
                        pose_lampadaire(dessus, *lampadaire, quand - origine,
                                        allume=True)
                    vue = dessus
            # La webcam dans sa fenêtre, les encarts dans les bandes autour.
            toile = cadre(vue, largeur, hauteur)
            cadrage = fenetre(vue.shape[:2], largeur, hauteur)
            # Les bulles d'abord, pour que tout le reste passe par-dessus :
            # les encarts, les pantins, le fil. Rien de ce qu'on vient
            # regarder ne doit se trouver derrière une bulle.
            # Hors du Ventoux, ces dessins n'ont plus de lieu : l'ours danse
            # sur un rond-point qui n'est pas dans l'image.
            if not figee:
                pose_bulles(toile, quand - origine, cadrage)
                pose_poissons(toile, quand - origine, cadrage)
            # La webcam reste visible pendant le survol : le relief a pris sa
            # place dans la fenêtre, pas sa place dans l'émission.
            if survol is not None:
                pose_osm(toile, cadrage)
                # La détection ne se pose pas sur le relief : elle appartient
                # à la webcam, et pendant le survol la webcam est dans le coin.
                # Le rush de ce passage part de là, rectangle compris.
                encart = pose_direct(toile, image, cadrage, quand)
                if encart is not None and a_poser is None and (nommes or pistes):
                    dessine(toile, nommes, quand, vue=encart)
                    pose_recherches(toile, pistes, encart, vus, quand)
                    nom = next((str(vu.get("label") or "") for vu in nommes
                                if vu.get("sur") and vu.get("label")), "")
                    journal.sujet(quand, nom or "Mouvement")
            # Les pantins sur la toile et non sur l'image de la caméra, depuis
            # qu'ils ont le droit d'aller danser dans la bande noire : posés
            # sur la vue, ils étaient enfermés dedans par construction. Ils
            # gardent leur place habituelle dans le cadre, on leur dit seulement
            # où il finit.
            #
            # Et pas pendant un survol. Le relief en trois dimensions est un
            # autre sujet que la montagne en direct, et deux pantins dansant
            # dessus diraient que c'est le même plan filmé autrement.
            if not figee and survol is None:
                pose_danseurs(toile, quand - origine, musique.pouls(), vue=cadrage)
                # Le tapis vole au-dessus de la crête, donc il passe quoi qu'il
                # arrive. L'éléphant danse sur le rond-point, c'est-à-dire en
                # plein sur l'endroit où les choses se passent : il n'y va que
                # dans un creux, à la même condition que le survol du relief.
                # Un éléphant rose par-dessus une voiture entourée de rouge
                # ferait passer toute la veille pour une plaisanterie.
                #
                # Et plus souvent la nuit. La veille n'y voit presque rien, le
                # survol du relief ne peut pas jouer puisqu'il est rendu en
                # plein soleil, et il reste douze heures d'une image fixe et
                # sombre. C'est exactement là qu'on a besoin qu'il se passe
                # quelque chose.
                pose_tapis(toile, quand - origine, musique.pouls(),
                           contour_ciel, vue=cadrage, nuit=not fait_jour)
                #
                # Le creux se compte sur « dernier_mouvement » et non sur
                # « dernier_vu », qui est remis à zéro par chaque rediffusion.
                # La nuit, le flux rediffuse sans arrêt faute de mieux, donc le
                # second ne dépassait jamais cinq minutes et l'éléphant n'est
                # tout simplement jamais venu. Seule une vraie détection doit
                # le retenir ; une image d'hier n'est pas un évènement.
                if quand - dernier_mouvement > CREUX_S:
                    pose_elephant(toile, quand - origine, musique.pouls(),
                                  vue=cadrage, nuit=not fait_jour,
                                  heure=datetime.fromtimestamp(quand, PARIS).hour)
                # Le sous-marin n'attend pas de creux, lui. Il ne descend
                # jamais sous la crête, donc il ne peut pas passer devant ce
                # qu'on surveille, et il n'a pas besoin du silence pour être
                # drôle. Il ne dépend pas non plus de la musique : le tapis et
                # l'éléphant dansent, lui navigue.
                pose_sous_marin(toile, quand - origine, sous_marin,
                                contour_ciel, vue=cadrage, nuit=not fait_jour)
                # La descente non plus n'attend pas de creux : elle se passe
                # sur le versant, loin de la route, et le trait blanc s'efface
                # derrière le surfeur. Rien ne reste sur l'image.
                pose_piste(toile, quand - origine, piste, vue=cadrage,
                           nuit=not fait_jour)
                # Le relevé non plus n'attend pas de creux : il se pose sur
                # une construction, pas sur la route, et il s'efface.
                pose_batiments(toile, quand - origine, batiments, vue=cadrage,
                               nuit=not fait_jour)
                # L'ours, de nuit aussi. On l'avait d'abord réservé au jour en
                # supposant qu'une découpe prise en plein midi, collée sur une
                # image nocturne, ressemblerait à une vignette qu'on aurait
                # oublié d'éteindre. C'est faux ici : le rond-point est éclairé
                # toute la nuit par le lampadaire du chalet, le double s'y pose
                # dans la lumière et il a l'air d'un ours sous un réverbère.
                # Vérifié sur une vraie image de nuit avant de lever la règle.
                ou_en_est = pose_ours(toile, quand - origine, ours, vue=cadrage,
                                      preuve=preuve_ours)
                # Dogmazic d'abord, le Raspberry ensuite : un seul disque
                # à la fois, le plateau les départage. Les rectangles se
                # redessinent après, sur la toile.
                la_dogmazic = pose_portrait_dogmazic(
                    toile, quand - origine, photo_dogmazic,
                    vue=cadrage, nuit=not fait_jour)
                if la_dogmazic:
                    phase_dogmazic = en_scene("dogmazic", quand - origine,
                                              not fait_jour) or 0.0
                    debut_dogmazic = round(quand - origine - phase_dogmazic)
                    if dogmazic_dit != debut_dogmazic:
                        dogmazic_dit = debut_dogmazic
                        if musique.remerciements_dogmazic:
                            musique.dis(tirage.choice(
                                musique.remerciements_dogmazic))
                        log.info("Portrait de Dogmazic : %s",
                                 musique.voix_dit or "sans voix")
                # La photo de la machine, en grand. Le rectangle se redessine
                # après, sur la toile : un disque au milieu de la route ne
                # doit pas éteindre la veille.
                la_machine = pose_portrait_machine(
                    toile, quand - origine, photo_machine,
                    machine, ville, vue=cadrage, nuit=not fait_jour)
                if la_machine:
                    phase_machine = en_scene("machine", quand - origine,
                                             not fait_jour) or 0.0
                    debut_machine = round(quand - origine - phase_machine)
                    if machine_dit != debut_machine:
                        machine_dit = debut_machine
                        if musique.remerciements:
                            musique.dis(tirage.choice(musique.remerciements))
                        log.info("Portrait de la machine : %s",
                                 musique.voix_dit or "sans voix")
                pose_merci(toile, quand - origine, "opencv", OPENCV_MERCI,
                           OPENCV_TENUE_S, vue=cadrage, nuit=not fait_jour)
                pose_merci(toile, quand - origine, "yolo", YOLO_MERCI,
                           YOLO_TENUE_S, vue=cadrage, nuit=not fait_jour)
                if ou_en_est is not None:
                    # Une fois, pas à chaque image : il grogne en descendant,
                    # et il crie une fois arrivé sur l'îlot.
                    tour = int((quand - origine) // OURS_PERIODE_S)
                    if ours_dit != (tour, 0) and ou_en_est < OURS_MARCHE_S:
                        ours_dit = (tour, 0)
                        if musique.grognements:
                            musique.dis(tirage.choice(musique.grognements))
                    elif ours_dit == (tour, 0) and ou_en_est >= OURS_MARCHE_S + 1.1:
                        ours_dit = (tour, 1)
                        if musique.cris_dours:
                            musique.dis(tirage.choice(musique.cris_dours))
            if a_poser is not None:
                pose_rediffusion(toile, a_poser, vue=cadrage)
            # Les rectangles après les numéros, pas avant. Posés sur l'image
            # de la caméra ils disparaissaient sous l'éléphant ou sous le
            # Raspberry : on croyait la veille éteinte dès qu'un effet
            # occupait le milieu. Ils restent donc par-dessus, dans la
            # fenêtre. Pas sur le relief : le rectangle et le nom d'une prise
            # appartiennent à la webcam, et le direct est déjà dans le coin.
            # Pas sur une rediffusion : là, ce n'est plus la vue.
            if not figee and a_poser is None and survol is None:
                dessine(toile, nommes, quand, vue=cadrage)
                pose_recherches(toile, pistes, cadrage, vus, quand)
            # Le mot tient au moins trois secondes, et tant que la voix parle.
            #
            # Il durait exactement la voix, ce qui semblait honnête et ne
            # l'était pas : dit platement, « Boooooooring » tenait six dixièmes
            # de seconde, soit quatre images à six par seconde, et un mot
            # affiché quatre images ne se lit pas — il clignote. D'où le
            # plancher, que le brouillard avait déjà et pour la même raison.
            #
            # Mais un plancher seul ne suffit pas non plus : à qui sait traîner
            # les voyelles, la même réplique prend près de quatre secondes, et
            # le mot s'effacerait pendant qu'on l'entend encore. Les deux
            # conditions ensemble, donc. Tenir un sous-titre plus longtemps que
            # la parole n'est pas mentir, c'est sous-titrer ; le retirer avant
            # la fin de la phrase, si.
            # La pensée, à 7 h 15, heure de Paris, une fois. Le nom reste
            # écrit dix-sept secondes.
            ici = datetime.now(PARIS)
            if pensee_jour != ici.date():
                pensee_jour, pensee_rang, pensee_etape = ici.date(), 0, 0
            seconde_jour = ici.hour * 3600 + ici.minute * 60 + ici.second
            if pensee_etape < 2:
                if seconde_jour >= PENSEE_HEURE_S + PENSEE_GRACE_S:
                    pensee_etape = 2
                    _pensee_ecrite(racine, ici.date(), 1, 2, pensee_feu)
                elif (musique.pensees
                        and PENSEE_HEURE_S <= seconde_jour < PENSEE_HEURE_S + PENSEE_GRACE_S
                        and not musique.parle()):
                    if musique.dis(musique.pensees[0]):
                        pensee_feu = time.time()
                        pensee_etape = 2
                        _pensee_ecrite(racine, ici.date(), 1, 2, pensee_feu)
                        log.info("Pensée dite à %s", ici.strftime("%H:%M:%S"))
            if dijon_jour != ici.date():
                dijon_jour, dijon_rang = ici.date(), 0
            if dijon_rang < len(DIJON_HEURES):
                vise = DIJON_HEURES[dijon_rang]
                clips = (musique.dijon23, musique.dijons)[dijon_rang]
                if seconde_jour >= vise + DIJON_GRACE_S:
                    dijon_rang += 1
                    _dijon_ecrite(racine, ici.date(), dijon_rang)
                elif (vise <= seconde_jour and not musique.parle()
                      and (not clips or musique.dis(clips[0]))):
                    dijon_feu = time.time()
                    dijon_heure = "23:00" if dijon_rang == 0 else "23:15"
                    dijon_rang += 1
                    _dijon_ecrite(racine, ici.date(), dijon_rang)
                    log.info("Dijon dit à %s", ici.strftime("%H:%M:%S"))
            la = datetime.now(LOS_ANGELES)
            if never_jour != la.date():
                seconde_la = la.hour * 3600 + la.minute * 60 + la.second
                if (NEVER_HEURE <= seconde_la < NEVER_HEURE + NEVER_GRACE_S
                        and not musique.parle()):
                    never_feu = time.time()
                    never_jour = la.date()
                    _never_ecrite(racine, never_jour)
                    log.info("Never give up à %s, heure de Los Angeles",
                             la.strftime("%H:%M:%S"))
            if (time.time() >= salle_prochain and not musique.parle()
                    and not (never_feu and 0 <= time.time() - never_feu <= NEVER_TENUE_S)
                    and not (dijon_feu and 0 <= time.time() - dijon_feu <= DIJON_TENUE_S)):
                abo, directs = salle.lit()
                if abo is None and directs is None:
                    salle_prochain = time.time() + 15.0
                else:
                    salle_feu = time.time()
                    salle_abonnes, salle_direct = abo, directs
                    salle_tenue = SALLE_TENUE_S
                    if directs is not None and directs >= 1:
                        log.info("Salle : %s abonnés, %s en direct", abo, directs)
                    else:
                        log.info("Salle : %s abonnés, personne en direct", abo)
                    salle_prochain = time.time() + SALLE_PERIODE_S
            dit = musique.dit_quoi() if musique.parle() else ""
            age_never = time.time() - never_feu if never_feu else -1.0
            age_dijon = time.time() - dijon_feu if dijon_feu else -1.0
            phrase_minuit = note_minuit(quand, minuit)
            if phrase_minuit:
                pose_annonce(toile, cadrage, (phrase_minuit,))
            elif 0 <= age_never <= NEVER_TENUE_S:
                pose_never(toile, cadrage, photo_never, photo_butterbane,
                           age_never)
            elif 0 <= age_dijon <= DIJON_TENUE_S:
                pose_dijon(toile, cadrage, photo_butterbane, age_dijon,
                           dijon_heure)
            elif dit == "brouillard" or quand - gris_depuis <= BROUILLARD_TENUE_S:
                # Sans voix enregistrée, le mot tient quand même trois
                # secondes : il doit pouvoir dire le brouillard sur une machine
                # où data/voix est vide.
                pose_ennui(toile, mot_gris, quand - origine)
            elif dit == "ennui" or quand - dernier_ennui <= ENNUI_TENUE_S:
                pose_ennui(toile, "BOOOOORING", quand - origine)
            elif (pensee_feu and time.time() - pensee_feu < PENSEE_APRES_S
                    and pensee_etape >= 1):
                pose_annonce(toile, cadrage, ("DAVID VINCENT OR VINCENT DAVID",))
            pose_salle(toile, cadrage, salle_abonnes, salle_direct,
                       time.time() - salle_feu if salle_feu else -1.0,
                       salle_tenue)
            pose_ruban(toile, ruban, montre - origine)
            # Flottement lent des deux encarts, en opposition : un mouvement
            # continu, pas un sursaut sur le beat.
            remue = flottement(montre - origine, largeur / 1600)
            # L'antenne donne l'heure, des deux côtés. L'image peut être celle
            # de 8 h 49 : Beaumont et Los Angeles disent quand même l'heure
            # qu'il est sur le direct.
            heure_antenne = _maintenant()
            los, beau = ratios_du_jour(tableau, heure_antenne)
            pose_horloge(toile, heure_antenne, direct=not figee and rediff is None and survol is None,
                         autre="DEGRADED" if figee else ("REPLAY" if rediff is not None else "3D MODEL"),
                         commune=commune, carte=carte_pays, ou=ou_camera,
                         remue=-remue, photo=photo_trampoline, ratio=beau)
            if figee:
                pose_mode_degrade(toile, cadrage)
            ou_machine = None
            if machine_ou.get("lat") is not None:
                ou_machine = (float(machine_ou["lat"]), float(machine_ou["lon"]))
            pose_machine(toile, machine, photo_machine, ville, remue,
                         carte=carte_californie, ou=ou_machine, quand=heure_antenne,
                         ratio=los)
            pose_bonjour(toile, nom_du_lieu, quand - bonjour)
            pose_deploiement(toile, __version__, quand - ouvert)
            # La voix part avec le mot, une fois, dans les premières secondes.
            # Elle dit « Deployed » ; le numéro, lui, reste écrit, parce qu'il
            # change à chaque livraison et qu'une voix gravée ne peut pas le suivre.
            if (not deploie_dit and musique.deplois
                    and 0 <= quand - ouvert < 1.5 and not musique.parle()):
                if musique.dis(musique.deplois[0]):
                    deploie_dit = True
                    log.info("Déploiement dit")
            # Relu de temps en temps et jamais à chaque image : le fichier
            # est écrit par un autre programme, et un agenda ne change pas
            # plus d'une fois par jour.
            if quand - agenda_lu > AGENDA_RELIT_S:
                agenda_lu = quand
                try:
                    feuille = json.loads((racine / "data" / "agenda.json")
                                         .read_text(encoding="utf-8"))
                    agenda = feuille.get("evenements") or []
                    agenda_credit = str(feuille.get("credit") or "")
                except (OSError, ValueError):
                    agenda, agenda_credit = [], ""
            pose_agenda(toile, agenda, agenda_credit, quand - origine)
            pose_fil(toile, cadrage, remue)
            # Le seul nom du flux, sous la montagne. YouTube ne voit pas le
            # site : sans ce mot sur l'image, on n'a pas de nom.
            pose_diese(toile, cadrage)
            # La musique en dernier : c'est elle qu'on vient écouter, et c'est
            # elle que la licence oblige à nommer.
            pose_bloc_musique(toile, prog, racine / "data" / "musique",
                              musique.pouls(), quand - origine,
                              forme=effet_du_moment(quand - origine)[0])
            # Et le flash par-dessus tout le reste, parce qu'une prise prime
            # sur les encarts. Jamais par-dessus la montagne : il s'arrête au
            # bord de la fenêtre, où il est le plus vif.
            pose_eclat(toile, cadrage, quand - attrape, attrape_nom, attrape_teinte)
            # Le coloriage ne part pas en direct. L'aperçu de l'iPad montre le
            # geste, le journal le garde pour plus tard, et l'image encodée
            # reste celle de la montagne.
            apercu = toile.copy()
            coloriage.dessine(apercu, time.time())
            coloriage.retiens(apercu, time.time())
            # Le rush est cette image-ci, pas la photographie nue : le rectangle
            # du mouvement, le nom de la classe, et GOOD CATCH sont déjà posés.
            journal.voit(toile, quand)
            journal.relache(quand)
            if sortie is None:
                sortie, son = _sortie(cible, largeur, hauteur, cfg["stream_fps"],
                                      cfg["stream_bitrate"], cfg["stream_out_fps"],
                                      cfg["stream_preset"])
                assert sortie.stdin is not None
                ouverte_a = _maintenant()
                # Horloge neuve des deux côtés : la vidéo de cette sortie-ci
                # commence à zéro, et la musique note où elle en était.
                diffusees = 0
                musique.repart()
                # Propre au verseur : couper le son d'une sortie qu'on remplace
                # ne doit pas couper aussi la veille du direct, qui partage
                # l'autre événement et qui, elle, vit aussi longtemps que nous.
                coupe_son = threading.Event()
                verseur = threading.Thread(target=_verse_le_son, args=(son, musique, coupe_son),
                                           daemon=True)
                verseur.start()
            # LE RETARD SE TIENT, IL NE SE CONSOMME PAS
            # ----------------------------------------
            # On ouvre le flux sept segments en arrière pour avoir quarante-
            # deux secondes d'avance sur ce qu'on montre : c'est ce délai qui
            # laisse à la veille le temps de reconnaître une voiture avant que
            # son image ne passe à l'écran. Mais rien ne retenait la boucle, et
            # une machine qui encode plus vite que le temps réel avale cette
            # avance en une minute. Mesuré ce matin : partie avec quarante-deux
            # secondes, la diffusion était revenue à dix du direct, c'est-à-dire
            # devant la veille. La voiture était nommée après coup, le rectangle
            # arrivait sur une route vide, et le plus souvent il n'arrivait pas.
            #
            # Alors on tient la cadence : une image de film par seconde de
            # montre. Cela ne ralentit rien qui soit déjà lent — quand on est en
            # retard il n'y a pas d'attente — ça empêche seulement de prendre de
            # l'avance sur soi-même.
            if cadence is None:
                cadence = _maintenant() - quand
            attente = (quand + cadence) - _maintenant()
            if attente > 0:
                time.sleep(min(attente, 1.0))
            try:
                sortie.stdin.write(toile.tobytes())
                diffusees += 1
            except BrokenPipeError:
                # YouTube a raccroché. Mourir ici revient à laisser systemd
                # tout rouvrir, entrée comprise, et c'est le clignotement qu'on
                # cherche justement à éviter. On rouvre la seule chose qui a
                # lâché, et pas plus souvent que REPRISE_SORTIE_S : si la
                # chaîne n'a plus de direct du tout, rouvrir en boucle ne le
                # ferait pas revenir, ça ne ferait que marteler l'arrivée.
                if _maintenant() - ouverte_a < REPRISE_SORTIE_S:
                    log.error("La sortie a lâché de nouveau : on laisse reposer "
                              "%.0f s avant de rouvrir", REPRISE_SORTIE_S)
                    time.sleep(REPRISE_SORTIE_S)
                log.warning("La sortie a lâché : on la rouvre sans toucher à l'entrée")
                coupe_son.set()
                if verseur is not None:
                    verseur.join(timeout=5)
                _ferme_sortie(sortie, son)
                sortie = son = verseur = None
                cadence = None
                continue
            if duree_s is not None and _maintenant() - debut >= duree_s:
                break
    finally:
        coloriage.ferme()
        entree.kill()
        coupe.set()
        coupe_son.set()
        musique.arrete()
        if verseur is not None:
            verseur.join(timeout=5)
        _ferme_sortie(sortie, son)
    log.info("%d images diffusées", images)


def _verse_le_son(descripteur: int, musique: Musique, coupe: threading.Event) -> None:
    """Verse le son dans son tuyau, dans son propre fil.

    Depuis le fil des images, les deux tuyaux se bloquent l'un l'autre : ffmpeg
    attend l'image pendant qu'on attend que le tuyau du son se vide, et les
    deux se regardent jusqu'au bout du monde. C'est arrivé au premier essai.

    Dans son fil, l'écriture bloque sans gêner personne, et ce blocage est
    justement la cadence : le tuyau ne se vide qu'au rythme où ffmpeg consomme,
    lequel suit les images, lesquelles arrivent de la webcam en temps réel.
    Rien ne règle le débit, il s'impose.

    Ce fil ne meurt que sur ordre. Une exception non rattrapée ici ferme le
    tuyau du son, ffmpeg s'arrête, l'écriture de l'image casse derrière et
    YouTube clôt la diffusion : c'est la chaîne exacte du premier octobre à
    vingt heures. Du silence vaut toujours mieux qu'un écran noir, donc on
    verse du silence et on continue.
    """
    while not coupe.is_set():
        try:
            morceau = musique.tranche(16384)
        except Exception:
            log.warning("Le son a trébuché, on verse du silence", exc_info=True)
            morceau = b"\0" * 16384
        pose = 0
        while pose < len(morceau) and not coupe.is_set():
            try:
                pose += os.write(descripteur, morceau[pose:])
            except (BrokenPipeError, OSError):
                return


def _maintenant() -> float:
    return time.time()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    racine = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(racine))
    from watcher.config import load_config

    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--sortie", default=None,
                         help="fichier à écrire, ou adresse rtmp://. Par défaut, "
                              "YouTube si une clé est posée, sinon un fichier.")
    parseur.add_argument("--duree", type=float, default=None, help="s'arrêter après tant de secondes")
    parseur.add_argument("--recul", type=int, default=SEGMENTS_EN_ARRIERE,
                         help="combien de segments de retard")
    args = parseur.parse_args(argv)

    cfg = load_config(racine)
    cfg.setdefault("stream_fps", 6)
    cfg.setdefault("stream_out_fps", 15)
    cfg.setdefault("stream_preset", "veryfast")
    cfg.setdefault("stream_bitrate", "2500k")
    cfg.setdefault("stream_size", [1920, 1080])
    cible = args.sortie or cible_youtube(cfg) or str(racine / "data" / "diffusion.mp4")
    # Jamais l'adresse complète dans le journal : la clé y est dedans, et les
    # journaux se lisent par-dessus l'épaule et se collent dans des rapports.
    log.info("Sortie : %s", "YouTube" if cible.startswith("rtmp") else cible)
    diffuse(cfg, racine, cible, args.duree, args.recul)
    return 0


def cible_youtube(cfg: dict) -> str | None:
    """L'adresse d'ingestion, clé comprise, ou rien si la clé n'est pas posée.

    La clé vit dans « config/local.json », ignoré par git et lisible du seul
    veilleur, comme les identifiants OpenSky. Elle n'a rien à faire dans
    « config/config.json », qui est versionné et public.
    """
    youtube = cfg.get("youtube") or {}
    cle = youtube.get("key")
    if not cle:
        return None
    ingestion = youtube.get("ingest") or "rtmp://a.rtmp.youtube.com/live2"
    return f"{ingestion.rstrip('/')}/{cle}"


if __name__ == "__main__":
    raise SystemExit(main())
