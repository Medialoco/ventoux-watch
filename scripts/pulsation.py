"""Mesure ce qui fait qu'un morceau pousse : la régularité de sa grosse caisse.

Il fallait un moyen de demander « des morceaux péchus » sans se fier à
l'étiquette de genre. Une étiquette est déclarative — « Techno » est posé à la
main par qui dépose le fichier, et le catalogue range sous ce mot aussi bien
une transe à cent trente temps qu'un drone de vingt minutes. Ce qui distingue
les deux s'entend et se mesure : un coup régulier dans le grave.

On regarde donc trois choses, dans cet ordre d'importance.

La première est la FORCE : à quel point l'énergie du grave revient au même
intervalle. Techniquement l'autocorrélation du flux d'attaques sous deux cents
hertz. Un morceau construit sur une grosse caisse la fait monter près de un ;
un morceau sans batterie reste en bas, quoi qu'annonce son genre.

La deuxième est le TEMPO, qui sert surtout de garde-fou. On ne le cherche
qu'entre quatre-vingt-dix et cent soixante temps par minute : hors de cette
plage un morceau n'est pas dansant, et surtout l'autocorrélation adore
répondre à la moitié ou au double. Une première version qui cherchait partout
annonçait soixante-deux temps pour un morceau à cent vingt-cinq — la mesure
était juste, c'était la question qui était mal posée.

La troisième est le GRAVE, la valeur efficace sous deux cents hertz. Deux
morceaux également réguliers ne poussent pas pareil si l'un a une caisse et
l'autre une basse feutrée.

Et sur un passage du milieu, pas sur le morceau entier. Un morceau de huit
minutes commence souvent par une minute de nappe et finit par une minute de
sortie : les compter dilue ce qu'on mesure, et c'est ce qui se passait quand
l'analyse portait sur toute la durée.

    .venv/bin/python -m scripts.pulsation data/musique/*.mp3
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Huit mille hertz suffisent très largement : on ne regarde que sous deux
# cents, et décoder moins coûte moins.
CADENCE = 8000
GRAVE_HZ = 200.0
# La fenêtre d'analyse, et le saut entre deux. Soixante-quatre millisecondes
# donnent treize cases sous deux cents hertz, ce qui est peu pour un spectre et
# assez pour une énergie ; dix millisecondes de saut situent un coup à mieux
# qu'un centième de seconde, soit plus finement que l'oreille ne le demande.
FENETRE, PAS = 512, 80
# Le passage écouté : quatre minutes prises au milieu, ou tout si c'est plus
# court.
EXTRAIT_S = 240.0
BPM_MIN, BPM_MAX = 90.0, 160.0


def decode(chemin: Path, debut: float, secondes: float) -> np.ndarray:
    """Le morceau en mono, entre -1 et 1. Vide si ffmpeg n'en veut pas."""
    sortie = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{debut:.3f}",
         "-i", str(chemin), "-t", f"{secondes:.3f}", "-f", "s16le",
         "-ar", str(CADENCE), "-ac", "1", "-"],
        capture_output=True, check=False)
    return np.frombuffer(sortie.stdout, np.int16).astype(np.float32) / 32768


def duree(chemin: Path) -> float:
    sortie = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(chemin)],
        capture_output=True, text=True, check=False)
    try:
        return float(sortie.stdout.strip())
    except ValueError:
        return 0.0


def flux_du_grave(son: np.ndarray) -> np.ndarray:
    """Les attaques dans le grave : ce qui monte, tranche après tranche.

    Ce qui monte seulement. L'énergie qui redescend est la fin d'un coup, pas
    un coup : la garder brouillerait la périodicité qu'on cherche avec le
    double d'événements.
    """
    if len(son) < FENETRE:
        return np.zeros(0, np.float32)
    nombre = 1 + (len(son) - FENETRE) // PAS
    tranches = np.lib.stride_tricks.as_strided(
        son, (nombre, FENETRE), (son.strides[0] * PAS, son.strides[0]))
    spectre = np.abs(np.fft.rfft(tranches * np.hanning(FENETRE), axis=1))
    cases = int(GRAVE_HZ * FENETRE / CADENCE)
    return np.maximum(0.0, np.diff(spectre[:, :cases + 1].sum(axis=1)))


def mesure(chemin: Path) -> dict:
    """Le tempo, la force de la pulsation et le niveau du grave."""
    longueur = duree(chemin)
    debut = max(0.0, (longueur - EXTRAIT_S) / 2)
    son = decode(chemin, debut, min(EXTRAIT_S, longueur))
    vide = {"bpm": 0.0, "force": 0.0, "grave": 0.0, "duree": longueur}
    if len(son) < CADENCE:
        return vide

    flux = flux_du_grave(son)
    if len(flux) < 2:
        return vide
    flux = flux - flux.mean()
    auto = np.correlate(flux, flux, "full")[len(flux) - 1:]
    if auto[0] <= 0:
        return vide
    auto /= auto[0]

    # Les retards qui correspondent à la plage dansante. Chercher ailleurs,
    # c'est accepter de répondre la moitié ou le double du tempo réel.
    seconde = CADENCE / PAS
    tot, tard = int(seconde * 60 / BPM_MAX), int(seconde * 60 / BPM_MIN)
    if tard >= len(auto):
        tard = len(auto) - 1
    if tot >= tard:
        return vide
    retard = tot + int(np.argmax(auto[tot:tard + 1]))

    # Le grave, mesuré sur le signal et non sur le flux : la moyenne glissante
    # sur quarante échantillons est un passe-bas à deux cents hertz, et c'est
    # tout ce qu'il faut ici.
    lisse = np.convolve(son, np.ones(int(CADENCE / GRAVE_HZ), np.float32)
                        / int(CADENCE / GRAVE_HZ), "same")
    return {"bpm": round(60 * seconde / retard, 1),
            "force": round(float(auto[retard]), 3),
            "grave": round(float(np.sqrt((lisse ** 2).mean())), 4),
            "duree": longueur}


# Au-dessus, ça pousse. Le seuil vient de deux populations mesurées et non d'un
# jugement : les seize morceaux de la maison, qui sont de la techno et rien
# d'autre, se tiennent entre 0,788 et 0,925 ; les cent douze morceaux de la
# médiathèque, tout-venant électronique, ont pour médiane 0,219 et un quart
# d'entre eux sont sous 0,150. Rien ne se presse autour de 0,30, et c'est ce
# vide qui fait la frontière. Elle garde quarante et un morceaux sur cent
# douze, ce qui est la bonne proportion pour un mot qui veut dire « celui-ci
# pousse » et non « celui-ci a une batterie ».
FORCE_DANSANTE = 0.30


def dansant(fiche: dict) -> bool:
    """Ce morceau pousse-t-il assez pour qu'on le passe comme tel ?"""
    return (fiche["force"] >= FORCE_DANSANTE
            and BPM_MIN <= fiche["bpm"] <= BPM_MAX)


def main(argv: list[str] | None = None) -> int:
    partie = argparse.ArgumentParser(description=__doc__)
    partie.add_argument("morceaux", nargs="+")
    args = partie.parse_args(argv)
    fiches = [(mesure(Path(m)), m) for m in args.morceaux]
    for fiche, nom in sorted(fiches, key=lambda f: -f[0]["force"]):
        marque = "danse" if dansant(fiche) else "     "
        print(f"  {marque}  force {fiche['force']:5.3f}  {fiche['bpm']:5.1f} bpm"
              f"  grave {fiche['grave']:.4f}  {fiche['duree'] / 60:4.1f} min"
              f"  {Path(nom).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
