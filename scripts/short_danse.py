"""Un Short vertical : une vidéo existante, notre musique, nos deux pantins.

Le flux principal fait danser deux bonshommes en tubes dans les coins bas dès
que la musique pousse. Ce sont eux qu'on emmène ailleurs : posés sur des images
qui ne viennent pas du Ventoux, ils deviennent une signature qu'on reconnaît,
et le Short cesse d'être une vidéo de plus pour devenir une annonce du direct.

Les pantins sont ceux du direct, importés et non réécrits, et leur énergie est
mesurée sur le morceau réellement collé dessous. Autrement ils danseraient sur
une cadence inventée, et le Short promettrait quelque chose que le flux ne fait
pas.

    .venv/bin/python -m scripts.short_danse --source /tmp/boissia.mp4
    .venv/bin/python -m scripts.short_danse --source v.mp4 --morceau 15 --secondes 50
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Les pantins du direct, et les mêmes seuils : un Short qui dit « ils sont sur
# le flux » doit montrer ceux du flux, au pixel et au seuil près.
from watcher.stream import pose_danseurs  # noqa: E402
from scripts.short_promo import (  # noqa: E402
    AMBRE, BLANC, CYAN, HAUTEUR, LARGEUR, VERT, _ecrit, enveloppe)

IMAGES_PAR_S = 30
# Le lissage du direct, repris tel quel : sans lui les pantins clignoteraient
# au rythme des silences entre deux coups de grosse caisse.
LISSAGE = 0.82

# L'appel au direct monte sur les dernières secondes, par-dessus l'image et non
# à la place : couper sur un carton noir, c'est rendre la fin sautable.
APPEL_S = 6.0
APPEL_MONTEE_S = 0.8

# Ce que l'application se réserve sur l'écran d'un Short : le dernier cinquième
# en bas pour le titre et la chaîne, et la colonne de droite pour ses boutons.
# C'est la seule raison pour laquelle les pantins ne dansent pas ici où ils
# dansent à l'antenne.
BAS_RESERVE, DROITE_RESERVE = 0.20, 0.15
# Ce trio est le seul qui rentre dans les deux réserves à la fois, trouvé en
# balayant les phases plutôt qu'à l'œil : un pantin ne déborde qu'à certains
# moments de son pas, et une seule image ne le dit pas.
DANSE_SOL = 1.0 - BAS_RESERVE
DANSE_MARGE = 0.28
DANSE_HAUT = 0.16


def recadre(source: Path, dest: Path, secondes: float, debut: float,
            pan: tuple[float, float] = (0.5, 0.5)) -> None:
    """La source, recadrée au neuf-seizièmes, sans son.

    La fenêtre peut dériver pendant le plan, de la première position vers la
    seconde, exprimées en fraction de ce qui dépasse à gauche et à droite.
    C'est le seul mouvement disponible quand la source n'en a aucun : une
    webcam fixe braquée sur une route vide est une photographie, et cinquante
    secondes de photographie ne se regardent pas. Panoramiquer dans une image
    qu'on possède déjà ne fabrique aucune information — on montre simplement
    tout le lieu au lieu d'en montrer un tiers.
    """
    tranche = f"(iw-ih*9/16)*({pan[0]}+({pan[1]}-{pan[0]})*t/{secondes:.2f})"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{debut:.2f}", "-i", str(source), "-t", f"{secondes:.2f}",
         "-an", "-vf",
         f"crop=ih*9/16:ih:'{tranche}':0,scale={LARGEUR}:{HAUTEUR}:flags=lanczos,"
         f"fps={IMAGES_PAR_S}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
         "-pix_fmt", "yuv420p", str(dest)],
        check=True)


def energie_par_image(piste: Path, debut: float, secondes: float) -> np.ndarray:
    """Ce que les pantins entendent, image par image.

    Mesurée sur l'extrait exact qui sera collé dessous, avec le lissage du
    direct. La valeur rendue est du même ordre que celle du flux — une
    moyenne quadratique de la pleine échelle — donc les seuils de danse, qui
    sont des fractions de cette échelle, gardent leur sens ici.
    """
    taux = 8000
    brut = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-ss", f"{debut:.2f}", "-i", str(piste), "-t", f"{secondes:.2f}",
         "-ac", "1", "-ar", str(taux), "-f", "s16le", "-"],
        capture_output=True, check=False).stdout
    echantillons = np.frombuffer(brut, np.int16).astype(np.float32) / 32768.0
    images = int(secondes * IMAGES_PAR_S)
    pas = max(1, taux // IMAGES_PAR_S)
    sortie = np.zeros(images, np.float32)
    niveau = 0.0
    for i in range(images):
        bloc = echantillons[i * pas:(i + 1) * pas]
        if bloc.size:
            niveau = (LISSAGE * niveau
                      + (1.0 - LISSAGE) * float(np.sqrt(np.mean(bloc ** 2))))
        sortie[i] = niveau
    return sortie


# Ce que dit la fin, selon d'où viennent les images. Un Short tourné ailleurs
# annonce que les pantins viennent d'un direct ; un Short pris sur la caméra
# elle-même n'a pas à l'annoncer, il le montre — et prétendre le contraire
# serait la seule contrevérité du fichier.
APPELS = {
    "ailleurs": [("THE SAME TWO DANCERS", 1.0, CYAN),
                 ("ARE ON A LIVE STREAM", 1.0, CYAN),
                 ("RIGHT NOW", 1.9, BLANC)],
    "ici": [("THIS IS THE LIVE VIEW", 1.0, CYAN),
            ("NOBODY IS WATCHING IT", 1.0, CYAN),
            ("EXCEPT A MACHINE", 1.9, BLANC)],
}


def pose_appel(image: np.ndarray, force: float, appel: str = "ailleurs") -> None:
    """L'annonce du direct, par-dessus l'image qui continue.

    Dans le tiers haut et non en bas, où le titre de la vidéo passerait par
    dessus, et au-dessus des pantins plutôt que dedans : l'argument de ce
    Short est qu'ils dansent, et un texte posé sur eux les cacherait au moment
    précis où on les montre du doigt.
    """
    if force <= 0.0:
        return
    haut, bas = int(HAUTEUR * 0.16), int(HAUTEUR * 0.56)
    calque = image.copy()
    cv2.rectangle(calque, (0, haut), (LARGEUR, bas), (0, 0, 0), -1)
    cv2.addWeighted(calque, 0.62 * force, image, 1.0 - 0.62 * force, 0.0, dst=image)
    calque = image.copy()
    y = haut + 90
    for texte, taille, couleur in APPELS[appel]:
        y = _ecrit(calque, texte, y + (64 if taille > 1.5 else 6), taille, couleur,
                   5 if taille > 1.5 else 2)
    y = _ecrit(calque, "FREE TECHNO RADIO", y + 84, 1.45, VERT, 4)
    y = _ecrit(calque, "LIVE 24/7", y + 14, 1.45, VERT, 4)
    _ecrit(calque, "MONT VENTOUX · 1389 m", y + 72, 1.0, AMBRE, 3)
    cv2.addWeighted(calque, force, image, 1.0 - force, 0.0, dst=image)


def pose_entete(image: np.ndarray, texte: str) -> None:
    """Le lieu et l'heure, discrets, tout en haut.

    Sans eux « capture du direct » est une affirmation que rien n'appuie ; avec
    eux c'est une date que n'importe qui peut recouper avec la météo du jour.
    """
    if not texte:
        return
    calque = image.copy()
    _ecrit(calque, texte, int(HAUTEUR * 0.075), 0.78, BLANC, 2)
    cv2.addWeighted(calque, 0.85, image, 0.15, 0.0, dst=image)


def choisit_extrait(piste: Path, secondes: float) -> float:
    """Où commencer dans un quart d'heure de musique.

    À l'endroit le plus fort et non au début : ces morceaux ouvrent calmement,
    et un Short qui démarre sur une nappe a perdu son spectateur avant que la
    grosse caisse arrive.
    """
    trace = enveloppe(piste, points=int(900))
    if trace is None:
        return 0.0
    duree = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(piste)],
        capture_output=True, text=True, check=False).stdout.strip() or 0.0)
    if duree <= secondes:
        return 0.0
    par_point = duree / trace.size
    large = max(1, int(secondes / par_point))
    cumul = np.concatenate([[0.0], np.cumsum(trace, dtype=np.float64)])
    moyennes = (cumul[large:] - cumul[:-large]) / large
    return float(np.argmax(moyennes) * par_point)


def morceau(racine: Path, filtre: str | None) -> tuple[Path, dict]:
    """Un des nôtres, et sa fiche pour le crédit.

    Les nôtres seulement : la bibliothèque contient aussi des morceaux
    d'autres gens, libres mais signés, et un Short qu'on pousse en publicité
    ne doit rien devoir à personne.
    """
    dossier = racine / "data" / "musique"
    fiches = json.loads((dossier / "credits.json").read_text(encoding="utf-8"))
    choix = [(nom, f) for nom, f in fiches.items()
             if f.get("source") != "Dogmazic" and (dossier / nom).is_file()
             and (filtre is None or filtre.lower() in f"{nom}{f['titre']}".lower())]
    if not choix:
        raise SystemExit("Aucun morceau maison ne correspond.")
    nom, fiche = sorted(choix)[0]
    return dossier / nom, fiche


def fabrique(racine: Path, source: Path, sortie: Path, secondes: float,
             depart: float, filtre: str | None, pan: tuple[float, float],
             appel: str, entete: str) -> int:
    piste, fiche = morceau(racine, filtre)
    debut = choisit_extrait(piste, secondes)
    energies = energie_par_image(piste, debut, secondes)
    print(f"Musique : {fiche['titre']} — {fiche['auteur']}, "
          f"extrait à {int(debut) // 60}:{int(debut) % 60:02d}, "
          f"énergie moyenne {energies.mean():.3f}")

    with tempfile.TemporaryDirectory() as dossier:
        muet = Path(dossier) / "recadre.mp4"
        recadre(source, muet, secondes, depart, pan)
        avec = Path(dossier) / "danse.mp4"
        lecture = cv2.VideoCapture(str(muet))
        ecrivain = cv2.VideoWriter(str(avec), cv2.VideoWriter_fourcc(*"mp4v"),
                                   IMAGES_PAR_S, (LARGEUR, HAUTEUR))
        index = 0
        while True:
            ok, image = lecture.read()
            if not ok:
                break
            instant = index / IMAGES_PAR_S
            force = energies[min(index, energies.size - 1)]
            pose_danseurs(image, instant, float(force), sol=DANSE_SOL,
                          marge=DANSE_MARGE, haut=DANSE_HAUT)
            pose_entete(image, entete)
            reste = secondes - instant
            if reste <= APPEL_S:
                pose_appel(image, min(1.0, (APPEL_S - reste) / APPEL_MONTEE_S),
                           appel)
            ecrivain.write(image)
            index += 1
        lecture.release()
        ecrivain.release()
        vraie = index / IMAGES_PAR_S

        sortie.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(avec), "-ss", f"{debut:.2f}", "-i", str(piste),
             "-filter_complex",
             f"[1:a]atrim=0:{vraie:.2f},afade=t=in:st=0:d=0.5,"
             f"afade=t=out:st={max(0.0, vraie - 1.2):.2f}:d=1.2[a]",
             "-map", "0:v", "-map", "[a]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             "-shortest", str(sortie)],
            check=True)

    credit = (f"Music: {fiche['titre']} — {fiche['auteur']} ({fiche['licence']})\n")
    sortie.with_suffix(".credit.txt").write_text(credit, encoding="utf-8")
    print(f"{sortie} · {vraie:.0f} s · "
          f"{sortie.stat().st_size / 1_048_576:.1f} Mo")
    return 0


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--source", required=True)
    parseur.add_argument("--sortie", default=None)
    parseur.add_argument("--secondes", type=float, default=52.0)
    parseur.add_argument("--depart", type=float, default=0.0,
                         help="où commencer dans la vidéo source")
    parseur.add_argument("--morceau", default=None)
    parseur.add_argument("--pan", nargs=2, type=float, default=(0.5, 0.5),
                         metavar=("DEBUT", "FIN"),
                         help="dérive de la fenêtre, en fraction du débord")
    parseur.add_argument("--appel", default="ailleurs", choices=tuple(APPELS))
    parseur.add_argument("--entete", default="", help="lieu et heure, en haut")
    args = parseur.parse_args(argv)
    sortie = Path(args.sortie) if args.sortie else ROOT / "data" / "short_danse.mp4"
    return fabrique(ROOT, Path(args.source), sortie, args.secondes,
                    args.depart, args.morceau, tuple(args.pan), args.appel,
                    args.entete)


if __name__ == "__main__":
    raise SystemExit(main())
