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
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
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
BLANC = (245, 245, 245)

# Une session, et non une liste de morceaux. Un flux qui tourne jour et nuit
# n'a pas d'auditeur qui arrive au début : ce qu'on entend en ouvrant la page
# doit tenir tout seul, sans avoir manqué le morceau d'avant. Bâtie par tirage
# à chaque démarrage, assez longue pour qu'une journée entière ne se répète
# pas, et rebattue le lendemain.
SESSION_H = 14.0
EXTENSIONS = {".mp3", ".ogg", ".opus", ".flac", ".m4a", ".wav"}


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


def batir_session(dossier: Path, heures: float = SESSION_H, graine: int | None = None) -> Path | None:
    """Tire une session dans la bibliothèque et l'écrit pour ffmpeg.

    Tirée sans remise tant qu'il reste des morceaux : entendre deux fois le
    même titre avant d'avoir entendu tous les autres est ce qui fait qu'un flux
    sonne comme une boucle plutôt que comme une soirée.
    """
    import random

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
    suite: list[Path] = []
    total = 0.0
    while total < heures * 3600:
        tour = morceaux[:]
        tirage.shuffle(tour)
        for piste in tour:
            suite.append(piste)
            total += durees[piste]
            if total >= heures * 3600:
                break
    chemin = dossier / "session.txt"
    chemin.write_text(
        "".join("file '%s'\n" % str(p.resolve()).replace("'", "'\\''") for p in suite),
        encoding="utf-8")
    log.info("Session de %.1f h tirée dans %d morceaux", total / 3600, len(morceaux))
    return chemin


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


def _sortie(cible: str, largeur: int, hauteur: int, images_par_s: int, debit: str,
            session: Path | None) -> subprocess.Popen:
    commande = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{largeur}x{hauteur}", "-r", str(images_par_s), "-i", "-",
    ]
    if session is not None:
        # « stream_loop » parce qu'une session finit toujours par finir, et
        # qu'un flux qui se tait est un flux que YouTube coupe.
        commande += ["-f", "concat", "-safe", "0", "-stream_loop", "-1", "-i", str(session)]
    else:
        # Même muette, YouTube veut une piste son : sans elle l'ingestion refuse.
        commande += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    commande += [
        # Le Pi 5 n'a aucun encodeur matériel : il ne reste que le logiciel, et
        # « veryfast » est le compromis mesuré qui tient le temps réel sans
        # manger les cœurs dont la veille a besoin.
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", "-b:v", debit, "-maxrate", debit, "-bufsize", "4M",
        "-g", str(images_par_s * 2),
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        # Les morceaux d'une bibliothèque n'ont pas tous le même niveau, et un
        # écart de six décibels entre deux titres fait sursauter à trois heures
        # du matin. « dynaudnorm » recale au fil de l'eau, pour quelques pour
        # cent de processeur, là où « loudnorm » demanderait une passe entière.
        "-af", "dynaudnorm=f=250:g=15",
        # La vidéo commande : quand le tuyau d'images se ferme, la sortie
        # s'arrête au lieu d'attendre une musique qui boucle sans fin. Seul,
        # « -shortest » ne suffit pas quand l'autre entrée boucle à l'infini :
        # le multiplexeur garde de l'avance et la piste son dépasse la vidéo
        # de trente secondes. Les deux drapeaux qui suivent lui retirent cette
        # avance.
        "-shortest", "-fflags", "+shortest", "-max_interleave_delta", "100000",
    ]
    commande += ["-f", "flv", cible] if cible.startswith("rtmp") else [cible]
    return subprocess.Popen(commande, stdin=subprocess.PIPE)


def diffuse(cfg: dict, racine: Path, cible: str, duree_s: float | None, recul: int) -> None:
    session = batir_session(racine / "data" / "musique")
    if session is None:
        log.warning("Aucune musique dans data/musique : le flux sortira muet")
    media = playlist_media(cfg["stream_url"])
    dernier, segment = bord_du_direct(media)
    log.info("Segments de %.1f s, dernier publié il y a %.1f s", segment, _maintenant() - dernier)

    entree = _entree(cfg["stream_url"], recul)
    assert entree.stdout is not None
    largeur, hauteur = 1920, 1080
    octets = largeur * hauteur * 3
    sortie = None
    debut = _maintenant()
    # L'heure de la première image montrée : le bord du direct, moins ce qu'on
    # a reculé. Tout le reste s'en déduit par le compte des images.
    origine = dernier - (recul - 1) * segment
    images = 0
    vus: list[dict] = []
    relu = 0.0
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
                relu = quand
            image = np.frombuffer(brut, np.uint8).reshape(hauteur, largeur, 3).copy()
            dessine(image, vus, quand)
            if sortie is None:
                sortie = _sortie(cible, largeur, hauteur, cfg["stream_fps"],
                                 cfg["stream_bitrate"], session)
                assert sortie.stdin is not None
            sortie.stdin.write(image.tobytes())
            if duree_s is not None and _maintenant() - debut >= duree_s:
                break
    finally:
        entree.kill()
        if sortie is not None and sortie.stdin is not None:
            sortie.stdin.close()
            sortie.wait(timeout=30)
    log.info("%d images diffusées", images)


def _maintenant() -> float:
    return time.time()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    racine = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(racine))
    from watcher.config import load_config  # noqa: E402

    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--sortie", default=str(racine / "data" / "diffusion.mp4"),
                         help="fichier à écrire, ou adresse rtmp://")
    parseur.add_argument("--duree", type=float, default=None, help="s'arrêter après tant de secondes")
    parseur.add_argument("--recul", type=int, default=SEGMENTS_EN_ARRIERE,
                         help="combien de segments de retard")
    args = parseur.parse_args(argv)

    cfg = load_config(racine)
    cfg.setdefault("stream_fps", 6)
    cfg.setdefault("stream_bitrate", "2500k")
    diffuse(cfg, racine, args.sortie, args.duree, args.recul)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
