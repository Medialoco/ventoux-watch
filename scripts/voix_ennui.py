"""Enregistre les quelques mots que le flux dit quand il ne se passe rien.

La machine du Ventoux n'a aucune synthèse vocale et n'en aura pas : elle tourne
déjà à la limite thermique, et installer un moteur de parole pour cinq secondes
de son par vingt minutes serait payer cher une plaisanterie. On enregistre donc
ici, une fois, et on ne livre là-bas que des fichiers.

Le format de sortie est celui que la diffusion manipule déjà — PCM brut, 44 100
hertz, deux voies, seize bits signés — pour qu'au moment de parler il n'y ait
rien à convertir : seulement des octets à additionner.

    .venv/bin/python -m scripts.voix_ennui
    .venv/bin/python -m scripts.voix_ennui --ecoute

Les voix employées sont celles de macOS. Elles conviennent pour la mise au
point ; si la chaîne doit vivre, enregistrer les mêmes phrases soi-même règle à
la fois la question du droit et celle du ton.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ECHANTILLONS_S = 44100
VOIES = 2

# Plusieurs phrases, et plusieurs voix. La même réplique toutes les vingt
# minutes pendant une nuit entière cesse d'être une blague et devient une
# alarme ; c'est la variation qui fait qu'on sourit encore à la cinquième.
# Deux occasions de parler, et deux tons. L'ennui traîne, la prise claque :
# la même voix pour les deux ferait du « good catch » une remarque de plus
# alors que c'est le seul moment où la machine a réussi quelque chose.
#
# Daniel et Samantha, et plus Bubbles, Boing ni Bad News. Les trois voix
# fantaisistes de macOS déforment les mots par construction — Bubbles parle
# sous l'eau, Boing rebondit, Bad News chante un enterrement — et à l'antenne
# on n'y comprenait rien. Or une plaisanterie qu'on n'entend pas n'est pas une
# plaisanterie, c'est un bruit, et un bruit sur un flux de surveillance
# ressemble à une panne. Le comique doit être dans la phrase : « absolutely
# nothing is happening » dit à plat par un Anglais est plus drôle que
# « boooring » dit par une bulle, et ça s'entend.
#
# Les voyelles étirées restent, elles : elles passent le mot à l'écran et la
# synthèse les allonge vraiment, donc le son suit ce qu'on lit.
PLAT, CLAIRE = "Daniel", "Samantha"
REPLIQUES = [
    ("ennui", PLAT, "Boooooooring"),
    ("ennui", PLAT, "Still nothing"),
    ("ennui", CLAIRE, "So boooring"),
    ("ennui", CLAIRE, "Nothing. Again"),
    ("ennui", PLAT, "Absolutely nothing is happening"),
    ("ennui", PLAT, "Boooooring"),
    ("attrape", CLAIRE, "Good catch!"),
    ("attrape", PLAT, "Good catch!"),
    ("attrape", CLAIRE, "Got one!"),
    ("attrape", CLAIRE, "Nice one!"),
    ("matin", CLAIRE, "Goooood morning Ventoux!"),
    ("matin", PLAT, "Goooood morning Ventoux!"),
    # Le brouillard tient des demi-journées ici, et pendant ce temps l'image
    # est un mur gris. Le dire de temps en temps est la seule façon de faire
    # comprendre que la caméra n'est pas en panne — et c'est plus drôle que de
    # laisser croire qu'elle l'est.
    ("brouillard", CLAIRE, "Foooooog"),
    ("brouillard", PLAT, "Fog. Again"),
    ("brouillard", PLAT, "Just fooog"),
    ("brouillard", CLAIRE, "I can see nothing at all"),
]


# Les rapports de fréquence d'une cloche, qui n'ont rien d'harmonique : c'est
# justement ce qui fait qu'une cloche sonne comme une cloche et pas comme une
# flûte. Le « hum » en dessous de la fondamentale, la tierce mineure au-dessus,
# puis la quinte, l'octave et ce qui traîne plus haut.
PARTIELS = [(0.56, 0.9, 2.2), (0.92, 0.6, 1.8), (1.00, 1.0, 1.6), (1.19, 0.5, 1.1),
            (1.71, 0.35, 0.8), (2.00, 0.3, 0.7), (2.74, 0.2, 0.45), (3.76, 0.12, 0.3)]
# Un sol aigu. Plus bas, la cloche pèse et annonce un malheur ; plus haut, elle
# tinte comme une notification de téléphone.
CLOCHE_HZ = 784.0


def cloche(duree: float = 1.9, hauteur: float = CLOCHE_HZ) -> np.ndarray:
    """Une cloche, fabriquée ici. PCM entier signé, deux voies.

    Faite et non trouvée : c'est trois lignes d'arithmétique, et le premier
    octobre au matin un direct est tombé parce qu'un son venait d'ailleurs.
    Celui-ci n'appartient à personne.

    Chaque partiel s'éteint à son rythme — les aigus d'abord, le bourdon en
    dernier. Une décroissance unique pour tous donnerait un accord d'orgue qu'on
    coupe, pas une cloche qu'on frappe.
    """
    t = np.arange(int(duree * ECHANTILLONS_S), dtype=np.float32) / ECHANTILLONS_S
    onde = np.zeros_like(t)
    for rapport, poids, tenue in PARTIELS:
        onde += poids * np.sin(2 * np.pi * hauteur * rapport * t) * np.exp(-t / tenue)
    # Une attaque de trois millisecondes : sans elle le premier échantillon
    # saute de zéro à pleine amplitude, et ce saut s'entend comme un clic.
    attaque = min(len(onde), int(0.003 * ECHANTILLONS_S))
    onde[:attaque] *= np.linspace(0.0, 1.0, attaque, dtype=np.float32)
    onde *= 0.55 / max(float(np.abs(onde).max()), 1e-6)
    return np.repeat((onde * 32767).astype(np.int16), VOIES)


def _mele(cloche_pcm: np.ndarray, voix: bytes, retard_s: float) -> bytes:
    """Pose la voix sur la cloche, un peu après le coup.

    Ensemble dans un seul fichier plutôt qu'enchaînés par la diffusion : le
    mélangeur du flux ne tient qu'une réplique à la fois, et lui en faire tenir
    deux pour une plaisanterie serait beaucoup de risque pour peu de chose.
    """
    debut = int(retard_s * ECHANTILLONS_S) * VOIES
    dessus = np.frombuffer(voix, np.int16)
    total = max(len(cloche_pcm), debut + len(dessus))
    melange = np.zeros(total, np.int32)
    melange[:len(cloche_pcm)] += cloche_pcm
    melange[debut:debut + len(dessus)] += dessus
    return np.clip(melange, -32768, 32767).astype(np.int16).tobytes()


def _nom(voix: str, texte: str) -> str:
    return re.sub(r"[^\w]+", "_", f"{voix}-{texte}").strip("_").lower()[:60] + ".raw"


# Le débit, en mots par minute, selon l'occasion. Ce n'est pas une coquetterie
# de mise en scène : le mot à l'écran s'affiche exactement le temps que dure la
# voix, parce que le compte des octets est la seule horloge qui ne décroche pas
# du son. Dit au débit normal, « Boooooooring » tient cinq dixièmes de seconde,
# soit trois images à six par seconde — on ne lit pas un mot en trois images.
# Ralentir allonge donc l'affichage sans poser de minuterie à côté du son, et
# ça tombe bien : une machine qui s'ennuie parle lentement.
CADENCES = {"ennui": 120, "brouillard": 120, "matin": 160, "attrape": 180}


def grave(voix: str, texte: str, cible: Path, cadence: int | None = None) -> float:
    """Dit la phrase et la pose en PCM brut. Rend sa durée en secondes."""
    with tempfile.TemporaryDirectory() as dossier:
        brut = Path(dossier) / "dit.aiff"
        commande = ["say", "-v", voix]
        if cadence:
            commande += ["-r", str(cadence)]
        subprocess.run(commande + ["-o", str(brut), texte], check=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(brut),
             # Un peu de marge sous le maximum : la voix va s'additionner à la
             # musique, et deux signaux au plafond font un écrêtage.
             "-af", f"volume=0.85,aresample={ECHANTILLONS_S}",
             "-f", "s16le", "-ar", str(ECHANTILLONS_S), "-ac", str(VOIES), str(cible)],
            check=True)
    return cible.stat().st_size / (ECHANTILLONS_S * VOIES * 2)


def enregistre(dossier: Path, ecoute: bool = False) -> int:
    if shutil.which("say") is None:
        print("« say » n'existe que sur macOS : à lancer depuis le Mac, pas depuis le Pi.")
        return 1
    dossier.mkdir(parents=True, exist_ok=True)
    fiches = []
    for quand, voix, texte in REPLIQUES:
        cible = dossier / _nom(f"{quand}-{voix}", texte)
        duree = grave(voix, texte, cible, CADENCES.get(quand))
        if quand == "attrape":
            # La cloche d'abord, la voix dans sa résonance. L'inverse ferait
            # une annonce suivie d'un bruit ; là, c'est un sourire.
            cible.write_bytes(_mele(cloche(), cible.read_bytes(), 0.42))
            duree = cible.stat().st_size / (ECHANTILLONS_S * VOIES * 2)
        fiches.append({"fichier": cible.name, "texte": texte, "voix": voix,
                       "quand": quand, "duree": round(duree, 3)})
        print(f"  {duree:4.1f} s  {quand:8s} {voix:10s} « {texte} »")
        if ecoute:
            subprocess.run(["ffplay", "-hide_banner", "-loglevel", "error", "-autoexit",
                            "-f", "s16le", "-ar", str(ECHANTILLONS_S), "-ac", str(VOIES),
                            str(cible)], check=False)
    # Et la cloche seule, deux fois sur six environ : une prise sans commentaire
    # est plus légère qu'une prise commentée, et c'est ce qu'on cherche.
    for nom, hauteur in (("attrape_cloche", CLOCHE_HZ), ("attrape_cloche_haute", CLOCHE_HZ * 1.5)):
        seule = dossier / f"{nom}.raw"
        seule.write_bytes(cloche(hauteur=hauteur).tobytes())
        duree = seule.stat().st_size / (ECHANTILLONS_S * VOIES * 2)
        fiches.append({"fichier": seule.name, "texte": "(cloche)", "voix": "maison",
                       "quand": "attrape", "duree": round(duree, 3)})
        print(f"  {duree:4.1f} s  attrape  maison     « cloche {hauteur:.0f} Hz »")

    (dossier / "voix.json").write_text(
        json.dumps(fiches, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(fiches)} répliques dans {dossier}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--dossier", default=str(ROOT / "data" / "voix"))
    parseur.add_argument("--ecoute", action="store_true", help="les jouer en les gravant")
    args = parseur.parse_args(argv)
    return enregistre(Path(args.dossier), args.ecoute)


if __name__ == "__main__":
    raise SystemExit(main())
