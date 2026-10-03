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
import json
import logging
import math
import os
import random
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import cv2
import numpy as np

from watcher.store import floute

log = logging.getLogger("ventoux.stream")

# Combien de segments de retard. Un seul suffirait à la logique, deux donnent
# de la marge quand le serveur publie en retard, et sept secondes par segment
# tombent près des dix demandées.
SEGMENTS_EN_ARRIERE = 2

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


def _lire(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as reponse:
        return reponse.read().decode("utf-8", "replace")


def playlist_media(url: str) -> str:
    """L'adresse de la liste des segments, sous la liste maîtresse."""
    for ligne in _lire(url).splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#"):
            return ligne if ligne.startswith("http") else url.rsplit("/", 1)[0] + "/" + ligne
    raise RuntimeError("aucune liste de segments dans la playlist maîtresse")


def bord_du_direct(media_url: str) -> tuple[float, float]:
    """L'heure du dernier segment publié, et la durée d'un segment.

    Le HLS porte un « EXT-X-PROGRAM-DATE-TIME » par segment : chaque image sait
    l'heure qu'il était. C'est ce qui permet de poser le bon rectangle sur la
    bonne image au lieu de l'approcher.
    """
    dates: list[float] = []
    duree = 7.0
    for ligne in _lire(media_url).splitlines():
        ligne = ligne.strip()
        if ligne.startswith("#EXTINF:"):
            duree = float(ligne.split(":", 1)[1].rstrip(","))
        elif ligne.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            dates.append(datetime.fromisoformat(ligne.split(":", 1)[1]).timestamp())
    if not dates:
        raise RuntimeError("la playlist ne date pas ses segments")
    return dates[-1], duree


# Combien de temps on insiste quand la webcam ne répond pas, et à quel rythme.
# Une demi-heure : au-delà, ce n'est plus une absence, c'est une panne, et il
# vaut mieux que le service redémarre pour repartir de zéro.
ATTENTE_WEBCAM_S = 1800.0
ATTENTE_PAS_S = 20.0


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


# À quel rythme on va vérifier que la diffusion existe encore, et au bout de
# combien d'absences on le dit. Dix minutes, deux fois : une page qui répond mal
# une fois ne vaut pas qu'on crie.
VEILLE_DIRECT_S = 600.0
VEILLE_DIRECT_SEUIL = 2


def direct_visible(chaine: str) -> bool | None:
    """La chaîne est-elle en direct ? None quand on n'a pas su regarder.

    L'adresse /live d'une chaîne répond de deux façons, et c'est la façon qui
    porte la réponse plus que le contenu. Quand la chaîne émet, YouTube sert la
    page de la vidéo en cours : elle contient « videoDetails » et un
    « isLive: true ». Quand elle n'émet pas, il sert la page de la chaîne, qui
    contient « channelMetadataRenderer » et aucune vidéo. Tout le reste — une
    panne de réseau, une page qu'on ne reconnaît pas — n'est ni l'un ni l'autre.

    Ne vaut que pour un direct public : un direct privé est invisible d'ici et
    serait annoncé disparu à tort. D'où le None, qui dit « je ne sais pas » et
    non « non » ; on ne crie que sur ce qu'on a vraiment lu.
    """
    url = f"https://www.youtube.com/channel/{chaine}/live"
    requete = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(requete, timeout=20) as reponse:
            page = reponse.read().decode("utf-8", "replace")
    except Exception:
        return None
    if "videoDetails" in page and '"isLive":true' in page:
        return True
    if "channelMetadataRenderer" in page:
        return False
    return None


def veille_le_direct(chaine: str, coupe: threading.Event) -> None:
    """Dire quand on pousse des octets dans le vide.

    Une diffusion terminée par YouTube ne se voit pas d'ici : l'arrivée continue
    d'accepter tout ce qu'on lui envoie, ffmpeg ne signale rien, et le journal
    reste propre. Le premier octobre, on a poussé quatre heures dans le vide
    avec un journal irréprochable, et c'est l'utilisateur qui s'en est aperçu.

    Alors on va regarder dehors. Ça ne répare rien — rouvrir une diffusion
    demande le compte — mais ça change « quatre heures sans le savoir » en
    « dix minutes et c'est écrit ».
    """
    absences = 0
    while not coupe.wait(VEILLE_DIRECT_S):
        vu = direct_visible(chaine)
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
        gardes.append({"t": quand, "box": boite, "label": event.get("label") or "",
                       "type": event.get("type"), "trace": detail.get("trace") or [],
                       "sur": nomme(event.get("label") or "",
                                    float(event.get("confidence") or 0.0))})
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


def suit(vu: dict, quand: float) -> tuple[float, float, float, float]:
    """Où la chose est à cet instant, entre deux points de sa trajectoire.

    La veille suit le sujet image par image, à une image par seconde ; le flux
    en sort six. Entre deux relevés on interpole en ligne droite, ce qui est
    exact pour une voiture sur une route et bien assez pour le reste — à cette
    distance, une seconde de trajet tient dans la largeur du rectangle.

    Avant le premier point et après le dernier, on se tient au point le plus
    proche sans extrapoler. Prolonger un mouvement qu'on n'a pas mesuré, c'est
    inventer, et le rectangle inventé se poserait sur du vide avec le même
    aplomb que les autres.
    """
    chemin = vu.get("trace") or []
    if len(chemin) < 2:
        return tuple(vu["box"])
    if quand <= chemin[0][0]:
        return tuple(chemin[0][1:])
    if quand >= chemin[-1][0]:
        return tuple(chemin[-1][1:])
    for avant, apres in zip(chemin, chemin[1:]):
        if avant[0] <= quand <= apres[0]:
            ecart = apres[0] - avant[0]
            part = 0.0 if ecart <= 0 else (quand - avant[0]) / ecart
            return tuple(a + (b - a) * part for a, b in zip(avant[1:], apres[1:]))
    return tuple(vu["box"])


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
    chemin = vu.get("trace") or []
    debut = min(vu["t"], chemin[0][0]) if chemin else vu["t"]
    fin = max(chemin[-1][0], debut + TENUE_S) if chemin else debut + TENUE_S
    return debut, fin


def dessine(image: np.ndarray, vus: list[dict], quand: float) -> int:
    """Pose un rectangle et un nom pour chaque chose vue à cet instant.

    Trait fin et cadre un peu large : le rectangle montre où regarder, il ne
    doit pas recouvrir ce qu'on demande de regarder.
    """
    hauteur, largeur = image.shape[:2]
    poses = 0
    for vu in vus:
        debut, fin = presence(vu)
        if not debut <= quand <= fin:
            continue
        x, y, w, h = suit(vu, quand)
        x1, y1 = int(x * largeur), int(y * hauteur)
        x2, y2 = int((x + w) * largeur), int((y + h) * hauteur)
        cv2.rectangle(image, (x1, y1), (x2, y2), ROUGE, 2)
        # Le mot seulement quand la veille a nommé quelque chose. « Mouvement
        # sur la route » n'est pas une identification, c'est l'aveu qu'il n'y en
        # a pas eu : écrit en blanc sur rouge à côté d'un rectangle, il se lit
        # pourtant avec le même aplomb que « Voiture ». Le rectangle reste — il
        # y a bien eu quelque chose à cet endroit — mais il se tait.
        nom = vu["label"] if vu.get("sur") else ""
        if nom:
            echelle = max(0.6, largeur / 1600)
            (tw, th), _ = cv2.getTextSize(nom, cv2.FONT_HERSHEY_SIMPLEX, echelle, 2)
            base = max(th + 8, y1 - 6)
            cv2.rectangle(image, (x1, base - th - 6), (x1 + tw + 10, base + 4), ROUGE, -1)
            cv2.putText(image, nom, (x1 + 5, base), cv2.FONT_HERSHEY_SIMPLEX, echelle, BLANC, 2, cv2.LINE_AA)
        poses += 1
    return poses


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
    while total < heures * 3600:
        tour = _espace(_entrelace(premier, second, tirage), auteurs)
        if not tour:
            break
        for piste in tour:
            for bout in _tranches(piste, durees[piste]):
                suite.append(bout)
                total += bout["d"]
            if total >= heures * 3600:
                break
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
        self.octets = 0
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
        try:
            self.fiches = json.loads((dossier / "credits.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self._ouvre()

    def _ouvre(self) -> None:
        if self.muet or self.session is None:
            return
        self.octets = 0
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

    def _seconde(self) -> float:
        return self.octets / (ECHANTILLONS_S * VOIES * OCTETS_PAR_ECHANTILLON)

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

    def trio(self) -> tuple[dict | None, dict | None, dict | None]:
        """Ce qui vient de passer, ce qui passe, ce qui suit.

        Trois blocs posés et lisibles valent mieux qu'un titre qui défile : on
        ne peut pas demander à quelqu'un d'attendre qu'un ruban repasse pour
        savoir ce qu'il écoute, et c'est précisément ce qu'on lui demande de
        noter s'il veut retrouver le morceau.
        """
        seconde = self._seconde()
        for i, piste in enumerate(self.suite):
            if seconde < piste["d"]:
                def fiche(j: int) -> dict | None:
                    if j < 0 or j >= len(self.suite):
                        return None
                    # Deux tranches du même set ne sont pas deux morceaux : on
                    # remonte jusqu'à un fichier différent, sinon le bloc
                    # « avant » affiche ce qui joue encore.
                    pas = 1 if j > i else -1
                    while 0 <= j < len(self.suite) and self.suite[j]["f"] == piste["f"]:
                        j += pas
                    if not 0 <= j < len(self.suite):
                        return None
                    return self.fiches.get(self.suite[j]["f"])
                return fiche(i - 1), self.fiches.get(piste["f"]), fiche(i + 1)
            seconde -= piste["d"]
        return None, None, None

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
    bande = image[0:haut, :]
    bande[:] = (bande * 0.22).astype(np.uint8)
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
# La bande du bas tient le bloc musique entier plus le bandeau : mesurée à
# 124, le bloc dépassait d'une centaine de pixels sur l'image, ce qui est
# exactement ce qu'on cherchait à éviter.
BORD_BAS = 202


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


def pose_bloc_musique(image: np.ndarray, trio: tuple[dict | None, dict | None, dict | None],
                      dossier: Path) -> None:
    """Le bloc fixe de la musique : la pochette, et avant / pendant / après.

    Fixe, et en bas à gauche, parce que c'est la seule chose du flux qu'on
    puisse avoir envie de noter. Le lien y figure en toutes lettres : CC-BY
    demande de nommer l'auteur, l'œuvre, la licence et de renvoyer à la source,
    et une adresse qu'on ne peut pas recopier ne renvoie nulle part.
    """
    avant, en_cours, apres = trio
    if en_cours is None:
        return
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    marge = int(16 * echelle)
    pas = int(27 * echelle)
    cote = int(84 * echelle)
    # Trois lignes et non cinq. Le bloc en faisait cinq, l'une sous l'autre,
    # et montait si haut qu'il entamait l'image ; pendant ce temps la moitié
    # droite de la bande noire était vide. Ce qui passe maintenant va à
    # droite, et ce qui passe en ce moment reste à gauche où l'œil le cherche.
    ici = [("NOW PLAYING", VERT, 0.50),
           (_coupe(f"{en_cours['auteur']} — {en_cours['titre']}", 40), BLANC, 0.62),
           (f"{en_cours['licence']} · {en_cours['url'].replace('https://', '')}",
            CYAN, 0.52)]
    la_suite = []
    if apres:
        la_suite.append(("UP NEXT", AMBRE,
                         _coupe(f"{apres['auteur']} — {apres['titre']}", 38)))
    if avant:
        la_suite.append(("JUST PLAYED", (150, 150, 150),
                         _coupe(f"{avant['auteur']} — {avant['titre']}", 38)))

    def large_de(texte: str, part: float) -> int:
        return cv2.getTextSize(texte, cv2.FONT_HERSHEY_SIMPLEX,
                               part * echelle, 2)[0][0]

    colonne = max(large_de(t_, s) for t_, _, s in ici)
    etiquette = max([large_de(e, 0.46) for e, _, _ in la_suite] or [0])
    suite_large = max([large_de(v, 0.52) for _, _, v in la_suite] or [0])
    bloc_h = max(cote, pas * len(ici)) + 2 * marge
    bloc_l = cote + 3 * marge + colonne
    if la_suite:
        bloc_l += marge * 2 + etiquette + marge + suite_large
    bas = hauteur - int(SPORT_H * echelle)
    haut = bas - bloc_h
    fond = image[haut:bas, 0:min(largeur, bloc_l)]
    if fond.size:
        fond[:] = (fond * 0.22).astype(np.uint8)
    cv2.rectangle(image, (0, haut), (int(6 * echelle), bas), VERT, -1)
    gauche = marge
    pochette = en_cours.get("pochette")
    if pochette:
        vignette = cv2.imread(str(dossier / pochette))
        if vignette is not None:
            vignette = cv2.resize(vignette, (cote, cote), interpolation=cv2.INTER_AREA)
            image[haut + marge:haut + marge + cote, gauche:gauche + cote] = vignette
            gauche += cote + marge
    base = haut + marge + pas - int(9 * echelle)
    for i, (texte, couleur, taille) in enumerate(ici):
        cv2.putText(image, texte, (gauche + marge, base + pas * i),
                    cv2.FONT_HERSHEY_SIMPLEX, taille * echelle, couleur, 2,
                    cv2.LINE_AA)
    if not la_suite:
        return
    # La seconde colonne, alignée sur la première : les deux étiquettes à
    # gauche, les deux titres sur une même verticale. Alignées, on lit deux
    # morceaux ; en escalier, on lit deux phrases.
    droite = gauche + marge + colonne + 2 * marge
    for i, (etiq, teinte, valeur) in enumerate(la_suite):
        ligne = base + pas * (i + (len(ici) - len(la_suite)) // 2)
        cv2.putText(image, etiq, (droite, ligne), cv2.FONT_HERSHEY_SIMPLEX,
                    0.46 * echelle, teinte, 2, cv2.LINE_AA)
        cv2.putText(image, valeur, (droite + etiquette + marge, ligne),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52 * echelle, BLANC, 2,
                    cv2.LINE_AA)


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
REDIFF_PART = 0.42
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


def pose_rediffusion(image: np.ndarray, fiche: dict) -> bool:
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
    cible_l = int(largeur * REDIFF_PART)
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
    carte_h = min(hauteur - 2 * marge, cible_h + pied + marge)
    cible_h = min(cible_h, carte_h - pied - marge)
    vignette = vignette[:cible_h]
    haut = (hauteur - carte_h) // 2
    # Au milieu. Elle était à droite pour laisser voir le rond-point et la
    # route, qui occupent la gauche de l'image — un bon raisonnement pour une
    # vignette posée par-dessus le direct. Mais elle n'est pas posée par-
    # dessus : pendant une rediffusion il n'y a rien d'autre à regarder, le
    # direct est caché derrière de toute façon, et une image collée contre le
    # bord droit d'un écran par ailleurs vide a juste l'air mal posée.
    gauche = (largeur - cible_l) // 2
    fond = image[haut:haut + carte_h, max(0, gauche - marge):min(largeur, gauche + cible_l + marge)]
    if fond.size:
        fond[:] = (fond * 0.25).astype(np.uint8)
    image[haut:haut + cible_h, gauche:gauche + cible_l] = vignette
    bas = haut + cible_h + marge
    cv2.putText(image, "REPLAY · REDIFFUSION", (gauche, bas + pas - int(12 * echelle)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.72 * echelle, ROUGE, 2, cv2.LINE_AA)
    cv2.putText(image, f"{_quand_dit(fiche['t'])}  —  {fiche['label']}",
                (gauche, bas + pas * 2 - int(14 * echelle)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.72 * echelle, BLANC, 2, cv2.LINE_AA)
    return True


# Le bandeau du bas, qui tourne. Anglais et français en alternance plutôt que
# côte à côte : deux langues sur la même ligne tiennent en quatre mots, pas en
# une phrase, et ce qu'il y a à dire ici tient mal en quatre mots.
# Le bandeau du bas, sa hauteur et sa lenteur. Quatre pixels et demi par
# seconde à la largeur de référence : il met six minutes à traverser l'écran,
# et c'est voulu. Un bandeau rapide se lit par morceaux et oblige à le
# rattraper ; celui-ci se lit par-dessus l'épaule, sans y penser, et pendant
# six minutes il ne demande rien à personne.
SPORT_H = 42
SPORT_VITESSE = 4.5      # pixels par seconde, à 1600 de large
SPORT_ECART = 70         # le blanc entre deux rencontres
SPORT_RELIT_S = 600.0    # on relit le fichier toutes les dix minutes


def pose_sport(image: np.ndarray, matchs: list, ligue: str,
               seconde: float) -> None:
    """Les résultats du championnat, en une ligne qui glisse très lentement."""
    if not matchs:
        return
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    pas = int(SPORT_H * echelle)
    taille = 0.56 * echelle
    base = hauteur - int(13 * echelle)
    bande = image[hauteur - pas:hauteur, :]
    bande[:] = (bande * 0.25).astype(np.uint8)
    cv2.line(image, (0, hauteur - pas), (largeur, hauteur - pas),
             tuple(int(c * 0.45) for c in CYAN), max(1, int(echelle)),
             cv2.LINE_AA)

    morceaux: list[tuple[str, tuple[int, int, int]]] = []
    if ligue:
        morceaux.append((f"{ligue}   ", AMBRE))
    for match in matchs:
        # L'équipe du coin en cyan : c'est tout l'intérêt d'un résultat
        # sportif sur une webcam de Provence, savoir comment a joué l'équipe
        # d'à côté. Les autres en blanc, parce qu'un classement amputé des
        # adversaires n'est plus un classement.
        teinte = CYAN if match.get("du_coin") else BLANC
        milieu = match.get("score") or "vs"
        morceaux.append((f"{match.get('chez', '')} {milieu} "
                         f"{match.get('dehors', '')}", teinte))
        morceaux.append(("   ·   ", (110, 110, 110)))
    larges = [cv2.getTextSize(m, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0]
              for m, _ in morceaux]
    tour = sum(larges) + int(SPORT_ECART * echelle)
    if tour <= 0:
        return
    decalage = int(seconde * SPORT_VITESSE * echelle) % tour
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


# La distance entre la machine et ce qu'elle regarde, écrite sobrement sous
# l'image. Les deux encarts donnent les deux lieux ; celui-ci donne ce qu'il
# y a entre, qui est la seule chose que ni l'un ni l'autre ne peut dire.
DISTANCE_TAILLE = 0.5
DISTANCE_GRIS = (150, 150, 150)


def a_vol_d_oiseau(un: tuple[float, float], deux: tuple[float, float]) -> float:
    """Les kilomètres entre deux points de la Terre, par le grand cercle."""
    rayon = 6371.0088
    phi1, phi2 = math.radians(un[0]), math.radians(deux[0])
    dphi = phi2 - phi1
    dlam = math.radians(deux[1] - un[1])
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return 2 * rayon * math.asin(math.sqrt(min(1.0, a)))


def pose_distance(image: np.ndarray, texte: str, vue: tuple | None = None) -> None:
    """Une ligne sobre sous l'image : d'où l'on regarde, et de combien loin."""
    if not texte:
        return
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    gauche, cime, large_vue, haute_vue = vue or (0, 0, largeur, hauteur)
    taille = DISTANCE_TAILLE * echelle
    long_px = cv2.getTextSize(texte, cv2.FONT_HERSHEY_SIMPLEX, taille, 1)[0][0]
    x = gauche + large_vue - long_px
    y = cime + haute_vue + int(22 * echelle)
    if y >= hauteur:
        return
    cv2.putText(image, texte, (x, y), cv2.FONT_HERSHEY_SIMPLEX, taille,
                DISTANCE_GRIS, max(1, int(echelle)), cv2.LINE_AA)


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
    # La cadence suit l'énergie : mou quand c'est calme, pressé quand ça tape.
    phase = seconde * DANSE_PAS_S * min(1.6, 0.5 + energie * 4)
    calque = image.copy()
    for i, (chez_lui, ailleurs) in enumerate(zip(maison, dehors)):
        x = int(chez_lui + (ailleurs - chez_lui) * sortie)
        _danseur(calque, x, pied, taille, phase + i * 2.1, BLANC)
    # Pleins dehors, voilés dedans. Le voile n'est pas une esthétique, c'est
    # une politesse envers la montagne : on ne se met pas devant ce que les gens
    # sont venus regarder. Dans la bande noire il n'y a rien derrière eux, donc
    # plus rien à ménager, et le demi-effacement n'y serait qu'une timidité
    # héritée. C'est aussi ce qui fait qu'on remarque la sortie.
    opacite = (voile + (1.0 - voile) * sortie) * force
    cv2.addWeighted(calque, opacite, image, 1.0 - opacite, 0.0, dst=image)


# Le rose de l'éléphant et les tons du tapis, en BGR comme tout OpenCV.
#
# Quatre roses et non un seul, parce qu'un aplat se lit comme un autocollant.
# Du plus sombre au plus clair, ils servent à dégrader chaque masse de son
# dessous vers sa lumière : c'est tout ce qu'il faut pour que des ellipses
# deviennent un volume, et à quarante pixels de haut c'est tout ce qu'on peut
# se permettre.
ROSE_NUIT = (112, 70, 158)
ROSE_OMBRE = (150, 105, 205)
ROSE = (205, 160, 250)
ROSE_CLAIR = (232, 206, 255)
TAPIS_ETOFFE = (62, 92, 228)
TAPIS_FRANGE = (120, 205, 250)


def _elephant(calque: np.ndarray, cx: int, sol: int, taille: float,
              phase: float) -> None:
    """Un éléphant rose en ellipses, qui danse de profil.

    Tout est rond et rien n'est anatomique : des oreilles trop grandes, des
    pattes trop courtes, une trompe qui se balance. C'est ce qui le sauve — un
    éléphant qu'on essaierait de dessiner juste, à quatre-vingts pixels de
    haut, ne serait qu'une tache grise de la taille d'une voiture, et on
    croirait à un défaut de l'image plutôt qu'à une intention.

    Il regarde vers la gauche, du côté d'où viennent les voitures.

    « taille » est sa hauteur au garrot, « sol » la ligne où ses pieds posent.
    """
    tube = max(2, int(taille * 0.055))

    def rond(centre, axes, couleur, angle=0.0, epaisseur=-1):
        cv2.ellipse(calque, centre, axes, angle, 0, 360, couleur, epaisseur,
                    cv2.LINE_AA)

    def masse(centre, axes, angle=0.0, sombre=ROSE_OMBRE, clair=ROSE_CLAIR,
              marches=7):
        """Une boule et non une tache : la même ellipse, de l'ombre à la lumière.

        Sept ellipses emboîtées qui rétrécissent vers le haut à gauche, du plus
        sombre au plus clair. C'est un dégradé pauvre, et il suffit : l'œil
        lit un volume dès qu'il voit une lumière décalée et un dessous plus
        foncé, et à cette taille un vrai calcul d'éclairage ne se verrait pas.

        La lumière vient d'en haut à gauche pour tout le monde, comme sur le
        reste de l'image : la webcam regarde au nord et le soleil passe de ce
        côté-là la plus grande partie du temps.
        """
        cx, cy = centre
        ax, ay = axes
        for pas in range(marches):
            part = pas / (marches - 1)
            teinte = tuple(int(a + (b - a) * part) for a, b in zip(sombre, clair))
            cv2.ellipse(calque,
                        (int(cx - ax * 0.30 * part), int(cy - ay * 0.34 * part)),
                        (max(1, int(ax * (1 - 0.46 * part))),
                         max(1, int(ay * (1 - 0.50 * part)))),
                        angle, 0, 360, teinte, -1, cv2.LINE_AA)

    # Le dandinement : il se soulève sur le temps et se balance à contretemps.
    # Deux mouvements de périodes différentes, sinon il tressaute sur place
    # comme un jouet à ressort.
    bond = int(math.sin(phase * 2) * taille * 0.05)
    roulis = math.sin(phase) * taille * 0.04
    pose = sol - bond
    axe = cx + int(roulis)

    # L'ombre portée d'abord, et elle ne bondit pas avec lui : elle s'étale
    # quand il retombe et se resserre quand il est en l'air. C'est ce qui le
    # pose au sol au lieu de le laisser flotter devant.
    au_sol = 1.0 - bond / max(1.0, taille * 0.05) * 0.18
    rond((axe, sol), (int(taille * 0.44 * au_sol), max(2, int(taille * 0.07))),
         (24, 18, 26))

    # Les pattes, pour que le corps les recouvre à la hanche. Courtes et
    # épaisses : des pattes à l'échelle feraient un animal juste, et un animal
    # juste n'est pas drôle. Celles-ci sont des poteaux. Les deux du fond sont
    # plus sombres, ce qui suffit à les mettre derrière.
    for i, ecart in enumerate((-0.24, 0.11, -0.09, 0.26)):
        derriere = i < 2
        balance = math.sin(phase + i * 1.7) * taille * 0.05
        pied = (int(axe + taille * ecart + balance), pose)
        haut = (int(axe + taille * ecart), int(pose - taille * 0.26))
        teinte = ROSE_NUIT if derriere else ROSE_OMBRE
        cv2.line(calque, haut, pied, teinte, int(tube * 2.6), cv2.LINE_AA)
        cv2.circle(calque, pied, int(tube * 1.3), teinte, -1, cv2.LINE_AA)
        if not derriere:
            # Un ongle clair sur les pattes de devant.
            cv2.circle(calque, (pied[0], pied[1] - tube // 2),
                       max(1, int(tube * 0.6)), ROSE_CLAIR, -1, cv2.LINE_AA)

    # La queue pend derrière le corps, donc avant lui.
    fouet = math.sin(phase * 3) * 0.5
    queue = (int(axe + taille * 0.36), int(pose - taille * 0.66))
    cv2.line(calque, queue,
             (int(queue[0] + taille * 0.15 + fouet * taille * 0.06),
              int(queue[1] + taille * 0.30)),
             ROSE_NUIT, max(2, int(tube * 0.6)), cv2.LINE_AA)

    corps = (axe, int(pose - taille * 0.56))
    masse(corps, (int(taille * 0.40), int(taille * 0.29)))

    tete = (int(axe - taille * 0.44), int(pose - taille * 0.72))
    masse(tete, (int(taille * 0.27), int(taille * 0.26)))
    # L'oreille bat, et c'est elle qui fait tout le travail : c'est à l'oreille
    # qu'on reconnaît un éléphant de dessin animé, pas à la trompe. Elle est
    # derrière la joue, donc plus sombre, avec un intérieur plus clair.
    bat = 18 * math.sin(phase * 2 + 0.7)
    oreille = (tete[0] + int(taille * 0.11), tete[1] - int(taille * 0.03))
    rond(oreille, (int(taille * 0.23), int(taille * 0.18)), ROSE_NUIT, angle=bat)
    masse(oreille, (int(taille * 0.20), int(taille * 0.15)), angle=bat,
          sombre=ROSE_OMBRE, clair=ROSE, marches=4)

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
        epais = max(2, int(tube * (2.0 - pas * 0.22)))
        cv2.line(calque, courbe[pas], courbe[pas + 1], ROSE_OMBRE, epais, cv2.LINE_AA)
        # La lumière sur le dessus de la trompe : un trait plus fin et plus
        # clair, décalé vers le haut. C'est le même éclairage que les masses,
        # dit avec les moyens d'une ligne.
        cv2.line(calque,
                 (courbe[pas][0], courbe[pas][1] - epais // 4),
                 (courbe[pas + 1][0], courbe[pas + 1][1] - epais // 4),
                 ROSE if pas > 2 else ROSE_CLAIR,
                 max(1, epais // 2), cv2.LINE_AA)

    # Pas de défenses : c'est un éléphanteau. Elles étaient là pour dire
    # « dessin animé » plutôt que « animal », mais elles disaient surtout
    # « adulte », et un adulte qui danse sur un rond-point est moins aimable
    # qu'un petit qui danse sur un rond-point.

    # L'œil, en dernier et tout petit : plus il est petit, plus il est gentil.
    # Avec son reflet, qui est le seul trait de tout le dessin dont on peut
    # dire qu'il sert à quelque chose — sans lui le regard est en verre.
    oeil = (tete[0] - int(taille * 0.09), tete[1] - int(taille * 0.07))
    cv2.circle(calque, oeil, max(2, int(taille * 0.055)), BLANC, -1, cv2.LINE_AA)
    cv2.circle(calque, oeil, max(1, int(taille * 0.026)), (20, 20, 20), -1, cv2.LINE_AA)
    cv2.circle(calque, (oeil[0] - max(1, int(taille * 0.016)),
                        oeil[1] - max(1, int(taille * 0.016))),
               max(1, int(taille * 0.014)), BLANC, -1, cv2.LINE_AA)


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


def pose_elephant(image: np.ndarray, seconde: float, energie: float,
                  vue: tuple[int, int, int, int] | None = None,
                  nuit: bool = False) -> bool:
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
    _elephant(calque, cx, sol, taille, seconde * DANSE_PAS_S * 0.8)
    # Il arrive et repart en fondu d'une seconde. Un éléphant qui apparaît d'un
    # coup se lit comme une image sautée ; en fondu, il se lit comme un rêve.
    # Presque opaque une fois arrivé : à quatre-vingt-huit centièmes on voyait
    # la montagne à travers lui, ce qui allait quand il faisait trente pixels
    # de haut et en fait un fantôme en gros plan.
    bord = min(phase_cycle, ELEPHANT_TENUE_S - phase_cycle, 1.0) * 0.96
    cv2.addWeighted(calque, bord, image, 1.0 - bord, 0.0, dst=image)
    return True


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
PLATEAU: tuple[tuple[str, float, float], ...] = ()


def en_scene(nom: str, seconde: float, nuit: bool = False) -> float | None:
    """Où en est ce numéro, s'il a le droit d'être à l'écran maintenant."""
    duree = dict((a, d) for a, _, d in PLATEAU).get(nom)
    if duree is None:
        return None
    # Tout le calcul se fait en millisecondes entières. La nuit les périodes
    # sont divisées par trois et 397/3 ne tombe pas juste en binaire ; deux
    # calculs du même instant finissaient par différer d'un milliardième de
    # seconde, ce qui suffit à faire croire à deux numéros qu'ils sont chacun
    # arrivés les premiers. Ils passaient alors ensemble, rarement, et c'est
    # précisément ce qu'on cherche à supprimer. Des entiers ne mentent pas.
    vite = NUIT_PLUS_SOUVENT if nuit else 1.0
    tours = {a: max(1, round(p * 1000 / vite)) for a, p, _ in PLATEAU}
    instant = round(seconde * 1000)
    commence = instant - instant % tours[nom]
    phase = (instant - commence) / 1000.0
    if phase >= duree:
        return None
    mon_rang = [a for a, _, _ in PLATEAU].index(nom)
    for rang, (autre, _, sa_duree) in enumerate(PLATEAU):
        if autre == nom:
            continue
        sienne = (commence % tours[autre]) / 1000.0
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
    _tapis(calque, cx, int(cy), etoffe, seconde * DANSE_PAS_S, danseur=danseur)
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


# La descente : une fois toutes les treize minutes trois, et elle dure vingt
# secondes. Un nombre premier de plus, pour la raison habituelle.
PISTE_PERIODE_S = 787.0
PISTE_DESCENTE_S = 20.0

# Le plateau, maintenant que les quatre numéros ont dit leur période et leur
# durée. L'ordre départage les ex æquo : le tapis d'abord parce qu'il passe
# au-dessus de tout et ne cache rien, l'éléphant en dernier parce qu'il
# occupe l'écran entier.
PLATEAU = (
    ("tapis", TAPIS_PERIODE_S, TAPIS_TRAVERSEE_S),
    ("sous-marin", SOUS_MARIN_PERIODE_S, SOUS_MARIN_TRAVERSEE_S),
    ("piste", PISTE_PERIODE_S, PISTE_DESCENTE_S),
    ("elephant", ELEPHANT_PERIODE_S, ELEPHANT_TENUE_S),
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
                    seconde: float) -> None:
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

    Sa lueur n'est pas dessinée : elle est vraie, et on l'amplifie. La lampe
    est allumée pour de bon et sa lumière est dans les pixels ; en remonter le
    contraste autour de l'ampoule donne un halo qui respire sans qu'on ait
    inventé une seule lueur. C'est la même règle que pour le ciel — ce flux
    passe son temps à juger des lueurs, il n'a pas à en fabriquer.

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

    # Pas de halo inventé. La lampe est vraiment allumée et sa lueur est
    # vraiment dans les pixels : on l'amplifie au lieu d'en dessiner une
    # par-dessus. La différence n'est pas qu'esthétique — un halo dessiné est
    # une lueur de plus dans une image où la veille passe son temps à juger
    # des lueurs, et c'est précisément ce qu'on vient de retirer du ciel.
    #
    # Multiplier et non ajouter : là où il n'y a pas de lumière, rien
    # n'apparaît. Un fond noir reste noir, et on ne peut donc pas faire naître
    # de lueur là où il n'y en avait pas.
    autour = max(8, int(lanterne * 5 * souffle))
    x0, y0 = max(0, x - autour), max(0, y - autour)
    x1, y1 = min(largeur, x + autour), min(hauteur, y + autour)
    if x1 > x0 and y1 > y0:
        zone = image[y0:y1, x0:x1].astype(np.float32)
        maille_y, maille_x = np.mgrid[y0:y1, x0:x1]
        loin = np.hypot(maille_x - x, maille_y - y) / autour
        gain = 1.0 + LAMP_GAIN * np.clip(1.0 - loin, 0.0, 1.0) ** 2
        image[y0:y1, x0:x1] = np.clip(zone * gain[:, :, None], 0, 255).astype(np.uint8)
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
    # Le verre reste vide : c'est du verre. Il était peint en jaune plein, ce
    # qui bouchait la lanterne et cachait la seule chose qu'on voulait voir
    # dedans — la vraie ampoule, qui est allumée et qui est juste derrière. On
    # ne dessine donc que la ferronnerie, et la lumière passe au travers.
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
           phase: float, danseur: float = 0.0) -> None:
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
             phase + 1.1, BLANC)


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


def _tient_dedans(image: np.ndarray, large: int, haut: int) -> np.ndarray:
    """L'image entière, centrée dans une boîte, sans être déformée.

    Contenue et non remplie. Remplir la boîte rognait la photo au centre, et
    au centre de celle-ci il y a le ventilateur : on voyait un ventilateur,
    plus une carte. Une bande sombre au-dessus et au-dessous ne coûte rien,
    elle est de la couleur de l'encart.
    """
    facteur = min(large / image.shape[1], haut / image.shape[0])
    petite = cv2.resize(image, (max(1, round(image.shape[1] * facteur)),
                                max(1, round(image.shape[0] * facteur))),
                        interpolation=cv2.INTER_AREA)
    boite = np.zeros((haut, large, 3), image.dtype)
    x = (large - petite.shape[1]) // 2
    y = (haut - petite.shape[0]) // 2
    boite[y:y + petite.shape[0], x:x + petite.shape[1]] = petite
    return boite


def tamise_la_photo(photo: np.ndarray) -> np.ndarray:
    """La photo au monochrome de l'encart, dans sa plage de gris."""
    gris = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    plage = MACHINE_NOIR + gris * (MACHINE_BLANC - MACHINE_NOIR)
    teinte = np.array(CYAN, np.float32)
    return np.clip(plage[:, :, None] * teinte, 0, 255).astype(np.uint8)


def cadre_encart(image: np.ndarray, coin_a: tuple[int, int],
                 coin_b: tuple[int, int], echelle: float) -> None:
    """Le filet des encarts : une arête, pas un cadre doré.

    Assombri seul, un encart flotte sur l'image et ses limites bougent avec le
    ciel derrière ; un filet suffit à en faire un objet posé. Dans le cyan du
    titre mais très baissé, et le même partout — deux encarts côte à côte avec
    deux bordures différentes, on voit la différence avant de voir les
    encarts.
    """
    cv2.rectangle(image, coin_a, coin_b,
                  tuple(int(c * 0.45) for c in CYAN), max(1, int(echelle)))


def pose_machine(image: np.ndarray, etat: dict | None,
                 vignette: np.ndarray | None = None, ville: str = "",
                 remue: float = 0.0) -> None:
    """L'encart machine, en haut à gauche, en face de l'horloge.

    Une webcam qui tourne vingt-quatre heures sur vingt-quatre tient à une
    chose : que la machine ne chauffe pas. Le dire à l'écran, c'est montrer
    qu'on le surveille, et c'est aussi le seul moyen de s'en apercevoir sans
    ouvrir un terminal.
    """
    if not etat:
        return
    largeur = image.shape[1]
    echelle = largeur / 1600
    degres = etat["degres"]
    couleur = VERT if degres < TIEDE_C else (AMBRE if degres < CHAUD_C else ROUGE)
    # « UP 2d 24h », qui ne veut rien dire : un jour n'a pas vingt-quatre
    # heures en plus de lui-même.
    #
    # La mise en forme arrondissait au lieu de tronquer. À quarante-sept heures
    # et demie, « heures / 24 » valait 1,98 et s'affichait « 2d », pendant que
    # « heures % 24 » valait 23,7 et s'affichait « 24h » : les deux nombres
    # faux à la même seconde, et la machine vieillie d'un jour entier. Une
    # division entière ne peut pas se tromper ainsi.
    jours, reste = divmod(int(max(0.0, etat["debout"])), 86400)
    heures, minutes = divmod(reste // 60, 60)
    if jours:
        debout = f"{jours}d {heures:02d}h"
    elif heures:
        debout = f"{heures}h {minutes:02d}m"
    else:
        # Sinon la première heure après un redémarrage affiche « UP 0h », ce
        # qui ressemble à une panne alors que c'est le contraire.
        debout = f"{minutes}m"
    lignes = [("RASPBERRY PI 5", CYAN),
              (f"{degres:.1f} C", couleur),
              (f"LOAD {etat['charge'] * 100:.0f}%", BLANC),
              (f"DISK {etat['libre'] / 1e9:.0f} GB", BLANC),
              (f"UP {debout}", BLANC)]
    pas = int(28 * echelle)
    marge = int(14 * echelle)
    sommet = int(RUBAN_H * echelle) + int(remue)
    taille = 0.56 * echelle
    # Les deux encarts se répondent : celui-ci dit où est la machine qui
    # regarde, celui d'en face où est ce qu'elle regarde. Huit mille
    # kilomètres entre les deux, et c'est à peu près tout le projet.
    lieu = (ville or "").upper()
    large = max([cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0]
                 for t, _ in lignes]
                + [large_du_lieu(lieu, taille * HORLOGE_LIEU, echelle)])
    # L'encart s'élargit pour la photo si le texte ne suffit pas. À la largeur
    # des chiffres seuls, la carte faisait cent pixels de large et on n'y
    # reconnaissait rien : une tache verte sous un tableau de bord. Cent
    # soixante-dix, et on voit que c'est un Raspberry Pi avec son ventilateur,
    # ce qui est tout l'intérêt de la montrer.
    droite = max(large + 2 * marge, int(ENCART_LARGE * echelle) + 2 * marge)
    # La photo de l'installation sous les chiffres. Les chiffres disent que la
    # machine va bien ; la photo dit laquelle. C'est une carte à cent euros sur
    # un bureau, et le flux a l'air d'une chaîne de télévision — autant le
    # montrer, c'est plus honnête et c'est plus intéressant.
    haut_photo = sommet + pas * (len(lignes) + bool(lieu)) + marge // 2
    bas = int(ENCART_BAS * echelle) + int(remue)
    photo = None
    if vignette is not None and bas - haut_photo - marge > 8:
        vu_large = droite - 2 * marge
        vu_haut = bas - haut_photo - marge
        # Contenue, ni déformée ni rognée. La boîte dépend du nombre de
        # lignes écrites au-dessus, qui n'a aucune raison d'avoir le rapport
        # de la photo : l'étirer donnait un Raspberry Pi plus long que large,
        # la rogner donnait un gros plan sur le ventilateur.
        photo = tamise_la_photo(_tient_dedans(vignette, vu_large, vu_haut))
    else:
        bas = sommet + pas * (len(lignes) + bool(lieu)) + marge
    panneau = image[sommet:bas, 0:droite]
    if panneau.size:
        panneau[:] = (panneau * 0.35).astype(np.uint8)
        cadre_encart(image, (0, sommet), (droite - 1, bas - 1), echelle)
    for i, (texte, teinte) in enumerate(lignes):
        cv2.putText(image, texte, (marge, sommet + pas * (i + 1) - int(6 * echelle)),
                    cv2.FONT_HERSHEY_SIMPLEX, taille, teinte, 2, cv2.LINE_AA)
    pose_lieu(image, lieu, marge,
              sommet + pas * (len(lignes) + 1) - int(6 * echelle),
              taille * HORLOGE_LIEU, echelle)
    if photo is not None:
        coin = image[haut_photo:haut_photo + photo.shape[0], marge:marge + photo.shape[1]]
        if coin.shape[:2] == photo.shape[:2]:
            coin[:] = photo
            cadre_encart(image, (marge - 1, haut_photo - 1),
                         (marge + photo.shape[1], haut_photo + photo.shape[0]),
                         echelle)


BONJOUR_S = 8.0
# Le lever au sens où tout le monde l'entend : le bord haut du disque à
# l'horizon, réfraction comprise. C'est la définition de la NOAA, elle ne doit
# rien au cadrage de cette caméra-ci et vaudra pour la suivante.
HORIZON = -0.833


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
# emploient la même, c'est ce qui les rend symétriques.
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
ENCART_BAS = 470         # depuis le haut de l'image, à la largeur de référence
ENCART_LARGE = 170
# De temps en temps, quand la musique pousse, les deux encarts se balancent.
# En hauteur seulement : de côté, celui de gauche entrerait dans l'image et
# celui de droite sortirait de l'écran, et un tableau de bord qui empiète sur
# ce qu'on surveille est une mauvaise plaisanterie. Ils vont en sens inverse
# l'un de l'autre — ensemble ils auraient l'air de glisser, pas de danser.
ENCART_DANSE_PERIODE_S = 311.0
ENCART_DANSE_S = 18.0
ENCART_DANSE_PX = 7.0
CARTE_TRAIT = (150, 128, 44)
CARTE_PLEIN = (58, 50, 18)
CARTE_POINT = (235, 215, 70)


def pose_carte(image: np.ndarray, contours: list, lat: float, lon: float,
               x: int, y: int, cote: int, echelle: float = 1.0) -> int:
    """Le pays en silhouette, avec un point là où regarde la caméra.

    Rend la hauteur occupée, parce qu'elle dépend de la forme du pays et que
    l'encart doit s'ajuster dessus : la France est à peu près carrée, le Chili
    ne le serait pas.
    """
    if not contours:
        return 0
    tous = [point for anneau in contours for point in anneau]
    ouest = min(p[0] for p in tous)
    est = max(p[0] for p in tous)
    sud = min(p[1] for p in tous)
    nord = max(p[1] for p in tous)
    # Les longitudes se resserrent avec la latitude : sans ce facteur la
    # France est étalée d'un tiers en largeur et ne se reconnaît plus.
    serre = math.cos(math.radians((nord + sud) / 2))
    large_deg = max((est - ouest) * serre, 1e-6)
    haut_deg = max(nord - sud, 1e-6)
    pas = cote / max(large_deg, haut_deg)
    haut = max(1, int(haut_deg * pas))
    marge = int((cote - large_deg * pas) / 2)

    def sur_la_carte(lon_p: float, lat_p: float) -> tuple[int, int]:
        return (x + marge + int((lon_p - ouest) * serre * pas),
                y + int((nord - lat_p) * pas))

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


def pose_horloge(image: np.ndarray, quand: float, direct: bool = True,
                 autre: str = "REPLAY", commune: str = "",
                 carte: list | None = None,
                 ou: tuple[float, float] | None = None,
                 remue: float = 0.0) -> None:
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
    moment = datetime.fromtimestamp(quand, PARIS)
    # L'heure disait « PARIS », qui était le fuseau. Personne ne le lisait
    # comme tel : sous une image du Ventoux, un spectateur lit un lieu, et
    # celui-là était faux de six cents kilomètres. La commune est vraie, elle
    # dit où regarde la caméra, et elle donne le fuseau par surcroît.
    # Elle est en plus petit : c'est un sous-titre de l'heure, pas une
    # troisième ligne de même importance, et « Beaumont-du-Ventoux » est long.
    lignes = [moment.strftime("%d %b %Y").upper(),
              moment.strftime("%H:%M:%S")]
    pas = int(34 * echelle)
    marge = int(14 * echelle)
    sommet = int(RUBAN_H * echelle) + int(remue)
    taille = 0.7 * echelle
    lieu = (commune or "").upper()
    dessin = bool(carte and ou)
    large = max([cv2.getTextSize(l, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0]
                 for l in lignes]
                + [large_du_lieu(lieu, taille * HORLOGE_LIEU, echelle)]
                + ([int(ENCART_LARGE * echelle)] if dessin else []))
    badge = "LIVE" if direct else autre
    large = max(large, cv2.getTextSize(badge, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0] + pas)
    gauche = largeur - large - 2 * marge
    haut_carte = sommet + pas * (len(lignes) + 1 + bool(lieu)) + marge // 2
    bas = (int(ENCART_BAS * echelle) + int(remue) if dessin
           else sommet + pas * (len(lignes) + 1 + bool(lieu)) + marge)
    coin = image[sommet:bas, gauche:largeur]
    if coin.size:
        coin[:] = (coin * 0.35).astype(np.uint8)
        cadre_encart(image, (gauche, sommet), (largeur - 1, bas - 1), echelle)
    rayon = int(7 * echelle)
    x = gauche + marge
    y = sommet + pas - int(6 * echelle)
    if direct and int(quand) % 2 == 0:
        cv2.circle(image, (x + rayon, y - rayon), rayon, ROUGE, -1)
    elif not direct:
        cv2.circle(image, (x + rayon, y - rayon), rayon, ROUGE, -1)
    cv2.putText(image, badge, (x + pas, y), cv2.FONT_HERSHEY_SIMPLEX, taille,
                BLANC if direct else ROUGE, 2, cv2.LINE_AA)
    for i, ligne in enumerate(lignes):
        cv2.putText(image, ligne, (x, sommet + pas * (i + 2) - int(6 * echelle)),
                    cv2.FONT_HERSHEY_SIMPLEX, taille, BLANC, 2, cv2.LINE_AA)
    pose_lieu(image, lieu, x,
              sommet + pas * (len(lignes) + 2) - int(6 * echelle),
              taille * HORLOGE_LIEU, echelle)
    if dessin:
        pose_carte(image, carte, ou[0], ou[1], x, haut_carte,
                   largeur - marge - x, echelle)


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
    verseur: threading.Thread | None = None
    coupe = threading.Event()
    chaine = cfg.get("youtube_chaine")
    if chaine and cible.startswith("rtmp"):
        threading.Thread(target=veille_le_direct, args=(chaine, coupe),
                         daemon=True).start()
    debut = _maintenant()
    # L'heure de la première image montrée : le bord du direct, moins ce qu'on
    # a reculé. Tout le reste s'en déduit par le compte des images.
    origine = dernier - (recul - 1) * segment
    images = 0
    vus: list[dict] = []
    ruban: list[tuple[str, tuple[int, int, int]]] = []
    trio: tuple[dict | None, dict | None, dict | None] = (None, None, None)
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
    try:
        piste = (json.loads((racine / "config" / "scene.json")
                            .read_text(encoding="utf-8")).get("piste")
                 or {}).get("trace")
    except (OSError, ValueError):
        piste = None
    if not piste:
        log.info("Pas de tracé de piste : personne ne descendra")
    # Le seul numéro qu'on ne dessine pas soi-même. Lu une fois, et absent sans
    # conséquence : il ne passe pas, c'est tout.
    sous_marin = charge_vignette(racine / "assets" / "sous-marin.png")
    sport, sport_ligue, sport_lu = [], "", 0.0
    # La photo de la machine qui fait tout ça. Lue en BGR et non en BGRA :
    # c'est une photo, elle n'a pas de transparence.
    photo_machine = cv2.imread(str(racine / "assets" / "machine.jpg"))
    # On démarre comme si on venait de voir quelque chose : une rediffusion à
    # la première seconde du direct donnerait l'impression que rien ne marche.
    dernier_vu = origine
    dernier_mouvement = origine
    attrape = origine - 1000.0
    attrape_nom = ""
    # Les prises déjà fêtées, pour ne pas les fêter à chaque image des quatre
    # secondes où leur rectangle est à l'écran. Purgé à chaque fête.
    fetes: set[float] = set()
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
        vise = json.loads((racine / "config" / "scene.json")
                          .read_text(encoding="utf-8")).get("pose") or {}
        ou_camera = (float(vise["lat"]), float(vise["lon"]))
    except (OSError, ValueError, KeyError, TypeError):
        ou_camera = None
    # La distance entre la machine et ce qu'elle regarde. Calculée une fois :
    # ni l'une ni l'autre ne bouge.
    dit_la_distance = ""
    if ou_camera and machine_ou.get("lat") is not None:
        km = a_vol_d_oiseau((float(machine_ou["lat"]), float(machine_ou["lon"])),
                            ou_camera)
        dit_la_distance = (f"{ville.upper()} - {commune.upper()}  "
                           f"{km:,.0f} KM AS THE CROW FLIES".replace(",", " "))
    # Loin en arrière, comme « bonjour » : à zéro, le flux s'ouvrirait sur
    # « BOOOOORING » pendant trois secondes, ce qui est une drôle de carte de
    # visite pour une veille qui vient de démarrer.
    dernier_ennui = origine - 10_000.0
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
    fin_survol = origine
    if images3d:
        log.info("Survol du terrain : %d images", len(images3d))
    tirage = random.Random()
    try:
        while True:
            brut = entree.stdout.read(octets)
            if len(brut) < octets:
                log.warning("Le flux s'est tari après %d images", images)
                break
            quand = origine + images / cfg["stream_fps"]
            images += 1
            if quand - relu >= 2.0:
                vus = identifications(racine / "data" / "events.json", quand - TENUE_S - 60)
                machine = etat_machine(racine)
                # Le soleil est calculé, pas lu : aucun service à interroger,
                # aucune panne de réseau ne peut faire rater le lever.
                haut = solar_elevation(datetime.fromtimestamp(quand, timezone.utc),
                                       cfg["camera"]["lat"], cfg["camera"]["lon"])
                if (hauteur_soleil is not None and hauteur_soleil < HORIZON <= haut
                        and quand - bonjour > 12 * 3600):
                    bonjour = quand
                    if musique.matins:
                        musique.dis(tirage.choice(musique.matins))
                    log.info("Lever du soleil : bonjour %s", nom_du_lieu)
                hauteur_soleil = haut
                ciel = lecture_du_ciel(racine / "data" / "view.json")
                # Les heures du soleil ne bougent pas dans la journée : on les
                # cherche au premier tour et au passage de minuit, pas toutes
                # les deux secondes.
                aujourdhui = datetime.fromtimestamp(quand, PARIS).date()
                if aujourdhui != jour_calcule:
                    jour_calcule = aujourdhui
                    try:
                        almanach = heures_du_soleil(relief, cfg["camera"], quand)
                        demain = heures_du_soleil(relief, cfg["camera"],
                                                  quand + 86400)
                    except Exception:
                        log.warning("Heures du soleil illisibles", exc_info=True)
                        almanach = demain = {}
                ruban = morceaux_ruban(lieu, ciel,
                                       morceaux_soleil(almanach, quand, demain))
                # Ce que la veille lit sur l'image passe avant ce que dit le
                # service : il arrive qu'il annonce « couvert » sur une vallée
                # pendant qu'il fait grand soleil à mille quatre cents mètres.
                temps = str(ciel.get("webcam") or ciel.get("api") or "")
                soleil = (ou_est_le_soleil(cfg["camera"], quand, hauteur / largeur)
                          if soleil_absent(relief, cfg["camera"], quand, temps) else None)
                mot_gris = BROUILLARD_MOTS.get(temps, "")
                trio = (None, None, None) if muet else musique.trio()
                relu = quand
            image = np.frombuffer(brut, np.uint8).reshape(source_h, source_l, 3).copy()
            # D'abord la teinte, ensuite seulement ce qu'on dessine dessus.
            applique_teinte(image, *teinte_du_moment(quand - origine))
            # Le soleil d'enfant avant les filtres : il fait partie de l'image
            # du ciel, donc il se pixellise et il ondule avec elle.
            if soleil is not None:
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
            if lampadaire is not None and (hauteur_soleil or -90.0) <= HORIZON:
                pose_lampadaire(image, *lampadaire, quand - origine)
            # Le grain ne tombe jamais sur une prise. Tout l'intérêt d'un
            # rectangle rouge est qu'on puisse regarder ce qu'il entoure, et
            # une voiture en gros carrés n'est plus une voiture.
            if quand - dernier_vu > TENUE_S:
                applique_effet(image, *effet_du_moment(quand - origine), quand - origine)
            # La fête suit le rectangle, pas l'arrivée de la fiche.
            if quand - attrape > ATTRAPE_S:
                neuve = prise_a_feter(vus, quand, fetes)
                if neuve is not None:
                    fetes = {t for t in fetes if t > quand - 3600} | {neuve["t"]}
                    attrape, attrape_nom = quand, neuve["label"]
                    if musique.felicitations:
                        musique.dis(tirage.choice(musique.felicitations))
                    log.info("Prise à l'écran : %s — %s", neuve["label"],
                             musique.voix_dit or "sans voix")
            poses = dessine(image, vus, quand)
            if poses:
                dernier_vu = quand
                # L'horloge de l'ennui est à part, et c'est tout l'intérêt :
                # « dernier_vu » est remis à zéro par les rediffusions, donc
                # s'en servir ferait dire « boring » vingt minutes après une
                # rediffusion, c'est-à-dire juste après qu'il s'est passé
                # quelque chose à l'écran. Seule une vraie détection compte.
                dernier_mouvement = quand
                rediff = None
            elif quand - dernier_vu > CREUX_S:
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
                    rediff = (choisie, quand) if choisie is not None else None
                    dernier_vu = quand if rediff is None else dernier_vu
            if quand - attrape <= ATTRAPE_S:
                pose_attrape(image, quand - attrape, attrape_nom)
            # Le brouillard se dit entre deux prises et jamais par-dessus : une
            # voiture qui passe est plus intéressante que le temps qu'il fait.
            if (mot_gris and quand - gris_depuis > BROUILLARD_PAUSE_S
                    and quand - attrape > ATTRAPE_S and not musique.parle()):
                gris_depuis = quand
                if musique.brouillards:
                    musique.dis(tirage.choice(musique.brouillards))
                log.info("Le flux dit « %s »", mot_gris)
            if (musique.repliques and quand - dernier_mouvement > ENNUI_S
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
            # Le survol du terrain, quand rien ne se passe et pas trop souvent.
            #
            # Il s'arrête net si la veille voit quelque chose : on a passé des
            # semaines à ne pas rater une voiture, ce n'est pas pour la cacher
            # derrière un décor calculé. Deux minutes interrompues valent mieux
            # que deux minutes complètes par-dessus l'évènement.
            # Et de jour seulement : le survol est un rendu en plein soleil, et
            # le poser au milieu d'une nuit noire ne montre pas le relief, ça
            # montre qu'on a collé une autre vidéo. Le soleil au-dessus de
            # l'horizon est la condition physique, pas une plage horaire.
            fait_jour = (hauteur_soleil or -90.0) > HORIZON
            if survol is not None and (poses or not fait_jour
                                       or quand - survol > VUE3D_TENUE_S):
                fin_survol, survol = quand, None
            elif (survol is None and images3d and rediff is None and a_poser is None
                  and fait_jour and quand - dernier_vu > CREUX_S
                  and quand - fin_survol > VUE3D_PAUSE_S):
                survol = quand
                log.info("Survol du terrain pendant %.0f s", VUE3D_TENUE_S)
            vue = image
            if survol is not None:
                dessus = image_vue3d(images3d, quand - survol, cfg["stream_fps"])
                if dessus is None:
                    fin_survol, survol = quand, None
                else:
                    vue = dessus
            # La webcam dans sa fenêtre, les encarts dans les bandes autour.
            toile = cadre(vue, largeur, hauteur)
            # Les pantins sur la toile et non sur l'image de la caméra, depuis
            # qu'ils ont le droit d'aller danser dans la bande noire : posés
            # sur la vue, ils étaient enfermés dedans par construction. Ils
            # gardent leur place habituelle dans le cadre, on leur dit seulement
            # où il finit.
            #
            # Et pas pendant un survol. Le relief en trois dimensions est un
            # autre sujet que la montagne en direct, et deux pantins dansant
            # dessus diraient que c'est le même plan filmé autrement.
            if survol is None:
                cadrage = fenetre(vue.shape[:2], largeur, hauteur)
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
                                  vue=cadrage, nuit=not fait_jour)
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
            if a_poser is not None:
                pose_rediffusion(toile, a_poser)
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
            dit = musique.dit_quoi() if musique.parle() else ""
            if dit == "brouillard" or quand - gris_depuis <= BROUILLARD_TENUE_S:
                # Sans voix enregistrée, le mot tient quand même trois
                # secondes : il doit pouvoir dire le brouillard sur une machine
                # où data/voix est vide.
                pose_ennui(toile, mot_gris, quand - origine)
            elif dit == "ennui" or quand - dernier_ennui <= ENNUI_TENUE_S:
                pose_ennui(toile, "BOOOOORING", quand - origine)
            pose_ruban(toile, ruban, quand - origine)
            # Le balancement des deux encarts : seulement quand la musique
            # pousse vraiment, et seulement de temps en temps. Tout le temps,
            # ce serait un défaut d'affichage ; jamais, ce serait dommage.
            remue = 0.0
            if (musique.pouls() > DANSE_SEUIL
                    and (quand - origine) % ENCART_DANSE_PERIODE_S < ENCART_DANSE_S):
                remue = (math.sin((quand - origine) * DANSE_PAS_S * math.pi)
                         * ENCART_DANSE_PX * (largeur / 1600)
                         * min(2.0, musique.pouls() / DANSE_SEUIL))
            pose_horloge(toile, quand, direct=rediff is None and survol is None,
                         autre="REPLAY" if rediff is not None else "3D MODEL",
                         commune=commune, carte=carte_pays, ou=ou_camera,
                         remue=-remue)
            pose_machine(toile, machine, photo_machine, ville, remue)
            pose_bonjour(toile, nom_du_lieu, quand - bonjour)
            # Relu de temps en temps et jamais à chaque image : le fichier
            # est écrit par un autre programme, et un championnat ne change
            # pas plus d'une fois par jour.
            if quand - sport_lu > SPORT_RELIT_S:
                sport_lu = quand
                try:
                    feuille = json.loads((racine / "data" / "sport.json")
                                         .read_text(encoding="utf-8"))
                    sport = (feuille.get("joues") or []) + (feuille.get("a_venir") or [])
                    sport_ligue = str(feuille.get("ligue") or "")
                except (OSError, ValueError):
                    sport, sport_ligue = [], ""
            pose_sport(toile, sport, sport_ligue, quand - origine)
            pose_distance(toile, dit_la_distance,
                          fenetre(vue.shape[:2], largeur, hauteur))
            # La musique en dernier : c'est elle qu'on vient écouter, et c'est
            # elle que la licence oblige à nommer.
            pose_bloc_musique(toile, trio, racine / "data" / "musique")
            if sortie is None:
                sortie, son = _sortie(cible, largeur, hauteur, cfg["stream_fps"],
                                      cfg["stream_bitrate"], cfg["stream_out_fps"],
                                      cfg["stream_preset"])
                assert sortie.stdin is not None
                verseur = threading.Thread(target=_verse_le_son, args=(son, musique, coupe),
                                           daemon=True)
                verseur.start()
            sortie.stdin.write(toile.tobytes())
            if duree_s is not None and _maintenant() - debut >= duree_s:
                break
    finally:
        entree.kill()
        coupe.set()
        musique.arrete()
        if verseur is not None:
            verseur.join(timeout=5)
        if son is not None:
            try:
                os.close(son)
            except OSError:
                pass
        if sortie is not None and sortie.stdin is not None:
            sortie.stdin.close()
            sortie.wait(timeout=30)
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
