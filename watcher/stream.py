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
        gardes.append({"t": quand, "box": boite, "label": event.get("label") or "", "type": event.get("type")})
    return gardes


def dessine(image: np.ndarray, vus: list[dict], quand: float) -> int:
    """Pose un rectangle et un nom pour chaque chose vue à cet instant.

    Trait fin et cadre un peu large : le rectangle montre où regarder, il ne
    doit pas recouvrir ce qu'on demande de regarder.
    """
    hauteur, largeur = image.shape[:2]
    poses = 0
    for vu in vus:
        age = quand - vu["t"]
        if age < 0 or age > TENUE_S:
            continue
        x, y, w, h = vu["box"]
        x1, y1 = int(x * largeur), int(y * hauteur)
        x2, y2 = int((x + w) * largeur), int((y + h) * hauteur)
        cv2.rectangle(image, (x1, y1), (x2, y2), ROUGE, 2)
        nom = vu["label"]
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
        if not 0.0 <= quand - vu["t"] <= TENUE_S:
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


# De combien on baisse la musique pendant que la voix parle. À 0,35 elle reste
# présente — c'est une blague posée sur un morceau, pas une annonce de gare qui
# coupe tout.
ATTENUATION = 0.35
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
    # Deux paquets : les sets et les morceaux. La nuit on commence par les
    # sets, le jour par les morceaux ; l'autre paquet vient ensuite, car une
    # nuit qui ne passerait que des mixes finirait par n'être qu'un seul mixe.
    sets = [p for p in morceaux if durees[p] > LONG_S]
    courts = [p for p in morceaux if durees[p] <= LONG_S]
    premier, second = (sets, courts) if nuit else (courts, sets)
    suite: list[dict] = []
    total = 0.0
    while total < heures * 3600:
        tour: list[Path] = []
        for paquet in (premier, second):
            lot = paquet[:]
            tirage.shuffle(lot)
            tour += lot
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

        C'est ce qui commande le mot à l'écran. Le compte des octets est la
        seule horloge honnête ici : une minuterie posée en parallèle finirait
        par décrocher du son, et on verrait « boring » écrit en silence.
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
        """Le son des prochaines images, ou du silence si la musique manque."""
        if self.process is None or self.process.stdout is None:
            return self._avec_la_voix(b"\0" * octets)
        morceau = self.process.stdout.read(octets)
        if len(morceau) < octets:
            # La session est finie : on en rebat une et on complète la tranche,
            # pour qu'aucun battement ne parte incomplet.
            self.arrete()
            # La session suivante est bâtie pour l'heure qu'il sera, pas pour
            # celle qu'il était : une session de jour tirée à cinq heures du
            # matin jouerait au soleil levant une sélection faite pour la nuit.
            if not self.muet:
                self.session = batir_session(self.dossier, nuit=est_nuit(self.racine))
                self._ouvre()
            if self.process is not None and self.process.stdout is not None:
                morceau += self.process.stdout.read(octets - len(morceau))
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

    def arrete(self) -> None:
        if self.process is not None:
            self.process.kill()
            self.process = None


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


def morceaux_soleil(heures: dict, quand: float) -> list[tuple[str, tuple[int, int, int]]]:
    """Ce que le ruban dit du soleil, selon l'heure qu'il est.

    Une seule phrase à la fois, et celle qui est vraie maintenant : annoncer
    le lever à dix-huit heures n'apprend rien à qui regarde, et quatre lignes
    d'almanach feraient du ruban un calendrier.
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
    if matin is not None:
        return [("FIRST LIGHT ON THIS SLOPE ", AMBRE), (_hhmm(matin), BLANC)]
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


def cadre(cam: np.ndarray, largeur: int, hauteur: int) -> np.ndarray:
    """Pose l'image de la caméra dans une fenêtre, et rend la toile entière.

    La fenêtre garde les proportions de la webcam : une image étirée pour
    remplir un trou est une image qui ment sur les formes, et ce flux passe son
    temps à dire qu'il mesure des largeurs en mètres.
    """
    echelle = largeur / 1600
    haut = int(BORD_HAUT * echelle)
    libre = hauteur - haut - int(BORD_BAS * echelle)
    cible_l = min(largeur, int(libre * cam.shape[1] / cam.shape[0]))
    cible_h = int(cible_l * cam.shape[0] / cam.shape[1])
    toile = np.zeros((hauteur, largeur, 3), np.uint8)
    gauche = (largeur - cible_l) // 2
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
    pas = int(25 * echelle)
    cote = int(104 * echelle)
    lignes: list[tuple[str, tuple[int, int, int], float]] = [
        ("NOW PLAYING", VERT, 0.52),
        (_coupe(f"{en_cours['auteur']} — {en_cours['titre']}", 44), BLANC, 0.60),
        (f"{en_cours['licence']} · {en_cours['url'].replace('https://', '')}", CYAN, 0.55),
    ]
    if apres:
        lignes.append(("UP NEXT  " + _coupe(f"{apres['auteur']} — {apres['titre']}", 44),
                       AMBRE, 0.55))
    if avant:
        lignes.append(("JUST PLAYED  " + _coupe(f"{avant['auteur']} — {avant['titre']}", 40),
                       (170, 170, 170), 0.55))
    bloc_h = max(cote, pas * len(lignes)) + 2 * marge
    larges = [cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, s * echelle, 2)[0][0]
              for t, _, s in lignes]
    bloc_l = cote + 3 * marge + max(larges)
    # Au-dessus du bandeau du bas, jamais dessus : la dernière ligne du bloc
    # était avalée par la phrase qui défile, et c'était celle du morceau d'avant.
    bas = hauteur - int(BANDE_H * echelle)
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
    for i, (texte, couleur, taille) in enumerate(lignes):
        cv2.putText(image, texte, (gauche + marge, haut + marge + pas * (i + 1) - int(8 * echelle)),
                    cv2.FONT_HERSHEY_SIMPLEX, taille * echelle, couleur, 2, cv2.LINE_AA)


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
            "Trop ", "Sans ", "Hors ", "Aucun")
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
        photo = racine / str(fiche.get("thumb") or "")
        if not str(fiche.get("thumb") or "") or not photo.is_file():
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
    """« 25 Sep 2026 · 08:20 UTC » : lisible dans les deux langues sans effort."""
    try:
        moment = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return iso
    ici = moment.astimezone(PARIS)
    return f"{ici.day} {MOIS[ici.month - 1]} {ici.year} · {ici:%H:%M} {ici:%Z}"


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
    # À droite : le rond-point et la route occupent la gauche de l'image,
    # et c'est d'eux qu'il s'agit quand quelque chose se passe.
    gauche = largeur - cible_l - int(40 * echelle)
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
BANDES = [
    "LIVE from Mont Serein · north face of Mont Ventoux · Vaucluse, France",
    "Every red box was drawn by a machine that decided, on its own, that something moved",
    "About 15 seconds behind — the time it takes to name what moves",
    "Wrong name? Tell us. Being corrected is the whole point",
    "All music is Creative Commons · artist, licence and source shown bottom left",
    # Pas un mot sur le feu dans les bandeaux. Un flux qui répète qu'il guette
    # un incendie se met à en promettre un, et le jour où il en voit vraiment
    # un, plus personne ne distingue l'annonce de l'affiche.
    "One mountain road, watched around the clock. Most days, nothing happens",
    "Names are guessed in about fifteen seconds. Sometimes they are wrong. Say so",
]
BANDE_S = 11.0
# La hauteur du bandeau du bas, que le bloc musique doit savoir éviter.
BANDE_H = 42


def bande_du_moment(seconde: float) -> str:
    """Une phrase à la fois, dans l'ordre : anglais, français, anglais…"""
    return BANDES[int(seconde // BANDE_S) % len(BANDES)]


def pose_bande_basse(image: np.ndarray, texte: str) -> None:
    """Le tiers inférieur des chaînes d'information, en une ligne."""
    if not texte:
        return
    hauteur, largeur = image.shape[:2]
    echelle = largeur / 1600
    pas = int(BANDE_H * echelle)
    marge = int(16 * echelle)
    taille = 0.72 * echelle
    long_px = cv2.getTextSize(texte, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0]
    bande = image[hauteur - pas:hauteur, 0:min(largeur, long_px + 3 * marge)]
    if bande.size:
        bande[:] = (bande * 0.25).astype(np.uint8)
    # Le filet rouge à gauche, comme les chaînes en mettent : il dit où la
    # ligne commence, et c'est le seul rouge que le flux s'autorise en dehors
    # des rectangles.
    cv2.rectangle(image, (0, hauteur - pas), (int(6 * echelle), hauteur), ROUGE, -1)
    cv2.putText(image, texte, (2 * marge, hauteur - int(13 * echelle)),
                cv2.FONT_HERSHEY_SIMPLEX, taille, BLANC, 2, cv2.LINE_AA)


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


def pose_danseurs(image: np.ndarray, seconde: float, energie: float) -> None:
    """Des pantins dans les coins bas de la vue, quand la musique pousse.

    Dans les coins et translucides : le flux existe pour regarder une montagne,
    et rien de ce qu'on ajoute pour le plaisir n'a le droit de se mettre devant.
    Ils sont posés sur l'image de la caméra et non sur la toile, donc ils
    restent dans la fenêtre, du bon côté des bandes.
    """
    if energie < DANSE_ARRET:
        return
    hauteur, largeur = image.shape[:2]
    # Entre le seuil d'arrêt et celui d'entrée, ils s'effacent au lieu de
    # disparaître d'un coup : une coupure franche se verrait plus qu'eux.
    force = min(1.0, (energie - DANSE_ARRET) / (DANSE_SEUIL - DANSE_ARRET))
    taille = hauteur * 0.22
    sol = int(hauteur * 0.93)
    # Un dixième de la largeur, et non un quatorzième : bras tendu, le pantin
    # atteint six centièmes de la largeur depuis son axe, et à sept il sortait
    # du cadre une fois sur trois — une main coupée par le bord ne se lit pas
    # comme un parti pris, elle se lit comme un bogue.
    marge = int(largeur * 0.10)
    # La cadence suit l'énergie : mou quand c'est calme, pressé quand ça tape.
    phase = seconde * DANSE_PAS_S * min(1.6, 0.5 + energie * 4)
    calque = image.copy()
    for i, x in enumerate((marge, largeur - marge)):
        _danseur(calque, x, sol, taille, phase + i * 2.1, BLANC)
    voile = DANSE_VOILE * force
    cv2.addWeighted(calque, voile, image, 1.0 - voile, 0.0, dst=image)


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
    champ = float(camera.get("fov") or 90.0)
    ecart = (solar_azimuth(moment, camera["lat"], camera["lon"])
             - float(camera.get("bearing") or 0.0) + 180.0) % 360.0 - 180.0
    coin = (SOLEIL_COIN if ecart < 0 else 1.0 - SOLEIL_COIN, SOLEIL_COIN_HAUT)
    if abs(ecart) > champ / 2 - 4:
        return coin
    # Projection rectilinéaire : c'est une tangente et non une règle de trois,
    # sinon le soleil dérive d'un bon dixième d'image vers les bords.
    demi = math.tan(math.radians(champ / 2))
    x = 0.5 + math.tan(math.radians(ecart)) / (2 * demi)
    y = 0.5 - math.tan(math.radians(haut - float(camera.get("pitch") or 0.0))) / (2 * demi * rapport)
    # Plus bas que la moitié de l'image, ce n'est plus le ciel, c'est la
    # montagne : un soleil planté dans un versant est un dessin faux, pas un
    # dessin d'enfant.
    if not 0.08 < x < 0.92 or not 0.06 < y < SOLEIL_CIEL:
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


def pose_machine(image: np.ndarray, etat: dict | None) -> None:
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
    sommet = int(RUBAN_H * echelle)
    taille = 0.56 * echelle
    large = max(cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0] for t, _ in lignes)
    bas = sommet + pas * len(lignes) + marge
    droite = large + 2 * marge
    panneau = image[sommet:bas, 0:droite]
    if panneau.size:
        panneau[:] = (panneau * 0.35).astype(np.uint8)
        # Un trait léger pour que l'encart ait un bord. Assombri seul, il flotte
        # sur l'image et ses limites bougent avec le ciel derrière ; un filet
        # suffit à en faire un objet posé. Dans le cyan du titre, mais très
        # baissé : on veut une arête, pas un cadre doré.
        cv2.rectangle(image, (0, sommet), (droite - 1, bas - 1),
                      tuple(int(c * 0.45) for c in CYAN), max(1, int(echelle)))
    for i, (texte, teinte) in enumerate(lignes):
        cv2.putText(image, texte, (marge, sommet + pas * (i + 1) - int(6 * echelle)),
                    cv2.FONT_HERSHEY_SIMPLEX, taille, teinte, 2, cv2.LINE_AA)


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


def pose_horloge(image: np.ndarray, quand: float, direct: bool = True,
                 autre: str = "REPLAY") -> None:
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
    lignes = [moment.strftime("%d %b %Y").upper(),
              # « PARIS » et non « CEST » : le fuseau dit au spectateur d'où
              # vient l'heure, et personne ne convertit mentalement un sigle
              # qui change de nom deux fois par an.
              moment.strftime("%H:%M:%S") + " PARIS"]
    pas = int(34 * echelle)
    marge = int(14 * echelle)
    sommet = int(RUBAN_H * echelle)
    taille = 0.7 * echelle
    large = max(cv2.getTextSize(l, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0] for l in lignes)
    badge = "LIVE" if direct else autre
    large = max(large, cv2.getTextSize(badge, cv2.FONT_HERSHEY_SIMPLEX, taille, 2)[0][0] + pas)
    gauche = largeur - large - 2 * marge
    coin = image[sommet:sommet + pas * (len(lignes) + 1) + marge, gauche:largeur]
    if coin.size:
        coin[:] = (coin * 0.35).astype(np.uint8)
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
    largeur, hauteur = 1920, 1080
    octets = largeur * hauteur * 3
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
    jour_calcule = None
    bonjour = origine - 10_000.0
    nom_du_lieu = (cfg.get("camera") or {}).get("nom") or "Ventoux"
    dernier_ennui = origine
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
                    except Exception:
                        log.warning("Heures du soleil illisibles", exc_info=True)
                        almanach = {}
                ruban = morceaux_ruban(lieu, ciel, morceaux_soleil(almanach, quand))
                # Ce que la veille lit sur l'image passe avant ce que dit le
                # service : il arrive qu'il annonce « couvert » sur une vallée
                # pendant qu'il fait grand soleil à mille quatre cents mètres.
                temps = str(ciel.get("webcam") or ciel.get("api") or "")
                soleil = (ou_est_le_soleil(cfg["camera"], quand, hauteur / largeur)
                          if soleil_absent(relief, cfg["camera"], quand, temps) else None)
                mot_gris = BROUILLARD_MOTS.get(temps, "")
                trio = (None, None, None) if muet else musique.trio()
                relu = quand
            image = np.frombuffer(brut, np.uint8).reshape(hauteur, largeur, 3).copy()
            # D'abord la teinte, ensuite seulement ce qu'on dessine dessus.
            applique_teinte(image, *teinte_du_moment(quand - origine))
            # Le soleil d'enfant avant les filtres : il fait partie de l'image
            # du ciel, donc il se pixellise et il ondule avec elle.
            if soleil is not None:
                pose_soleil_dessine(image, soleil, quand - origine)
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
            # Les danseurs appartiennent à la vue, pas aux bandes : ils sont
            # posés sur l'image de la caméra, avant qu'elle entre dans sa
            # fenêtre. Et après les rectangles, pour qu'une détection ne passe
            # jamais derrière un pantin.
            pose_danseurs(image, quand - origine, musique.pouls())
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
            if survol is not None and (poses or quand - survol > VUE3D_TENUE_S):
                fin_survol, survol = quand, None
            elif (survol is None and images3d and rediff is None and a_poser is None
                  and quand - dernier_vu > CREUX_S
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
            if a_poser is not None:
                pose_rediffusion(toile, a_poser)
            if musique.parle() and musique.dit_quoi() != "attrape":
                pose_ennui(toile, mot_gris if musique.dit_quoi() == "brouillard"
                           else "BOOOOORING", quand - origine)
            elif quand - gris_depuis <= BROUILLARD_TENUE_S:
                # Sans voix enregistrée, le mot tient quand même trois
                # secondes : il doit pouvoir dire le brouillard sur une machine
                # où data/voix est vide.
                pose_ennui(toile, mot_gris, quand - origine)
            pose_ruban(toile, ruban, quand - origine)
            pose_horloge(toile, quand, direct=rediff is None and survol is None,
                         autre="REPLAY" if rediff is not None else "3D MODEL")
            pose_machine(toile, machine)
            pose_bonjour(toile, nom_du_lieu, quand - bonjour)
            pose_bande_basse(toile, bande_du_moment(quand - origine))
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
    """
    while not coupe.is_set():
        morceau = musique.tranche(16384)
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
