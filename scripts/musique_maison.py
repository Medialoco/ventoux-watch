"""Fabrique la musique du flux, au lieu d'aller la chercher.

Le premier octobre au matin, le direct est tombé deux fois pour « policy
violations ». La bibliothèque venait d'archive.org, qui déclare les licences
sans les vérifier : un DJ set de quarante-neuf minutes posé sous CC BY reste un
enchaînement de disques commerciaux, et Content ID les reconnaît sous le
mixage. Après la deuxième coupure, la conclusion s'impose — tant qu'un son
vient de dehors, le direct tient à la bonne foi d'un inconnu.

Celui-ci ne vient de nulle part. Ce sont des sinusoïdes additionnées, comme la
cloche des prises. Personne ne peut le réclamer.

Le parti pris musical est « tonique mais d'ambiance » : une pulsation franche
qui donne envie de rester, et au-dessus des nappes qui ne demandent aucune
attention. C'est ce qu'on veut sur une montagne où il ne se passe rien pendant
vingt minutes.

Tout est additif, sans filtre récursif : un filtre passe-bas demande une
boucle échantillon par échantillon, ce qui en Python coûte des minutes pour un
morceau de quinze. On obtient le même mouvement en faisant varier l'amplitude
de chaque harmonique au cours du temps — c'est une synthèse additive, et numpy
la fait d'un seul geste.

    .venv/bin/python -m scripts.musique_maison --combien 10
    .venv/bin/python -m scripts.musique_maison --combien 1 --minutes 15 --graine 7
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TAUX = 44100
AUTEUR = "thepriben"
LICENCE = "CC0"
SOURCE = "https://medialoco.github.io/ventoux-watch/"

# Un tempo de marche. Plus vite, le flux pousse ; plus lentement, il endort.
# Chaque morceau prend le sien dans cette fourchette : à tempo unique, seize
# morceaux s'entendent comme un seul très long, et c'est ce qu'ils faisaient.
TEMPO = 118.0
TEMPOS = (108.0, 112.0, 116.0, 118.0, 122.0, 125.0)
# Ce qui distingue un morceau d'un autre au-delà de la tonalité : combien la
# pulsation pèse en face des nappes. « nuit » garde la percussion en retrait et
# les nappes devant, « jour » fait l'inverse. Le flux joue les deux, et une
# nuit de quatorze heures n'a pas besoin de la même chose qu'un midi.
CARACTERES = {
    "nuit": {"frappe": 0.62, "nappe": 1.25, "arpege": 0.55, "pompe": 0.42},
    "calme": {"frappe": 0.80, "nappe": 1.10, "arpege": 0.75, "pompe": 0.50},
    "franc": {"frappe": 1.00, "nappe": 0.92, "arpege": 1.00, "pompe": 0.58},
    "poussé": {"frappe": 1.12, "nappe": 0.82, "arpege": 1.15, "pompe": 0.64},
}
# La mineure naturelle, en demi-tons depuis le la. C'est l'échelle qui sonne
# juste sans avoir à choisir : aucune de ses notes ne jure avec une autre, donc
# un tirage au hasard y reste musical, ce qui est exactement ce qu'il faut
# quand c'est une machine qui tire.
GAMME = [0, 2, 3, 5, 7, 8, 10]
# Les degrés de la suite d'accords, en demi-tons depuis la tonique.
SUITES = [[0, -4, -9, -2], [0, 3, -4, -2], [0, -5, -4, -7], [0, 5, 3, -2],
          [0, -2, -5, -4], [0, -9, -5, -2], [0, 7, 3, 5], [0, -4, 3, -2]]
LA = 220.0


def _hauteur(demi_tons: float) -> float:
    return LA * 2 ** (demi_tons / 12.0)


def _enveloppe(n: int, attaque: float, chute: float) -> np.ndarray:
    """Monte puis descend. Les deux en exponentielle, comme tout ce qui sonne."""
    t = np.arange(n, dtype=np.float32) / TAUX
    monte = 1.0 - np.exp(-t / max(attaque, 1e-4))
    tombe = np.exp(-t / max(chute, 1e-4))
    return (monte * tombe).astype(np.float32)


def grosse_caisse(n: int) -> np.ndarray:
    """Un coup de grosse caisse : une sinusoïde qui tombe de 95 à 42 hertz.

    C'est la chute de hauteur qui fait le coup. À fréquence fixe on entend une
    note basse ; c'est la descente, en cinquante millisecondes, que l'oreille
    lit comme une peau frappée.
    """
    t = np.arange(n, dtype=np.float32) / TAUX
    hauteur = 42.0 + 53.0 * np.exp(-t / 0.045)
    phase = 2 * np.pi * np.cumsum(hauteur) / TAUX
    corps = np.sin(phase) * np.exp(-t / 0.30)
    # Un souffle très court au début, sinon le coup n'a pas de bord.
    claque = np.random.default_rng(1).normal(0, 1, n).astype(np.float32) * np.exp(-t / 0.004)
    return (corps + 0.25 * claque).astype(np.float32)


def charleston(n: int, ouvert: bool = False) -> np.ndarray:
    """Du bruit filtré par différence : court, sec, en haut du spectre."""
    bruit = np.random.default_rng(2).normal(0, 1, n + 1).astype(np.float32)
    # La différence première d'un bruit blanc est un bruit penché vers l'aigu :
    # un passe-haut qui ne coûte qu'une soustraction.
    aigu = np.diff(bruit)
    return aigu * _enveloppe(n, 0.0005, 0.12 if ouvert else 0.028)


def claquement(n: int) -> np.ndarray:
    """Un clap sur les deuxième et quatrième temps.

    C'est lui qui manquait le plus. La grosse caisse dit où est le temps ; le
    clap dit qu'il y a quelqu'un. Sans lui, la pulsation est un métronome.

    Quatre bouffées de bruit espacées de dix millisecondes et non une seule :
    un clap est un geste de plusieurs mains qui ne tombent pas ensemble, et
    c'est ce léger étalement qu'on reconnaît. Une bouffée unique sonne comme
    une porte qui claque.
    """
    tirage = np.random.default_rng(7)
    t = np.arange(n, dtype=np.float32) / TAUX
    onde = np.zeros(n, np.float32)
    for retard, poids in ((0.0, 0.7), (0.010, 0.85), (0.019, 0.6), (0.028, 1.0)):
        place = int(retard * TAUX)
        if place >= n:
            break
        reste = n - place
        bruit = np.diff(tirage.normal(0, 1, reste + 1).astype(np.float32))
        onde[place:] += bruit * np.exp(-t[:reste] / (0.11 if poids == 1.0 else 0.012)) * poids
    return onde * 0.45


def pince(n: int, hauteur: float) -> np.ndarray:
    """Une note pincée, courte et claire : la voix de l'arpège.

    Une dent de scie adoucie — les harmoniques décroissent en un sur le rang —
    sous une enveloppe très brève. Les rangs s'arrêtent avant la moitié du taux
    d'échantillonnage, sinon ce qui dépasse revient se plier dans le grave et
    s'entend comme une casserole.
    """
    t = np.arange(n, dtype=np.float32) / TAUX
    onde = np.zeros(n, np.float32)
    for rang in range(1, 13):
        if hauteur * rang > TAUX * 0.45:
            break
        onde += np.sin(2 * np.pi * hauteur * rang * t) / rang
    return onde * _enveloppe(n, 0.004, 0.17) * 0.3


def cloche_note(n: int, hauteur: float, chute: float = 1.8) -> np.ndarray:
    """Une note de cloche, même principe que celle des prises.

    Partiels non harmoniques, chacun avec sa propre extinction : les aigus
    partent les premiers et le bourdon traîne, ce qui donne le timbre.
    """
    t = np.arange(n, dtype=np.float32) / TAUX
    onde = np.zeros(n, np.float32)
    for rapport, poids, tenue in ((1.0, 1.0, 1.0), (2.0, 0.5, 0.6), (2.76, 0.25, 0.4),
                                  (5.4, 0.12, 0.22), (0.5, 0.4, 1.4)):
        onde += poids * np.sin(2 * np.pi * hauteur * rapport * t) * np.exp(-t / (tenue * chute))
    onde[:40] *= np.linspace(0, 1, 40, dtype=np.float32)
    return onde * 0.4


def nappe(n: int, notes: list[float], tirage: random.Random) -> np.ndarray:
    """Une nappe : chaque note en plusieurs harmoniques qui vont et viennent.

    Les harmoniques hautes montent et redescendent sur des périodes de dix à
    trente secondes, toutes décalées. C'est ce qui remplace le filtre : la
    nappe s'ouvre et se ferme sans qu'aucun filtre n'ait été écrit.

    Deux voix par note, désaccordées de quelques centièmes de demi-ton. L'écart
    produit un battement lent, et c'est ce battement qui fait qu'une nappe
    respire au lieu de tenir.
    """
    t = np.arange(n, dtype=np.float32) / TAUX
    onde = np.zeros(n, np.float32)
    for note in notes:
        for desaccord in (-0.04, 0.04):
            base = note * 2 ** (desaccord / 12.0)
            for rang, poids in ((1, 1.0), (2, 0.34), (3, 0.17), (4, 0.09), (6, 0.05)):
                periode = tirage.uniform(11.0, 31.0)
                phase = tirage.uniform(0, 2 * math.pi)
                # L'harmonique ne disparaît jamais tout à fait : une nappe dont
                # les aigus s'éteignent à zéro semble reculer, pas s'assombrir.
                mouvement = 0.55 + 0.45 * np.sin(2 * np.pi * t / periode + phase)
                onde += poids * mouvement * np.sin(2 * np.pi * base * rang * t
                                                   + tirage.uniform(0, 6.28))
    # Assez fort pour tenir seule : c'est elle qui reste dans les creux, et un
    # creux où il ne reste presque rien s'entend comme une coupure de son.
    return onde / max(len(notes), 1) * 0.22


def echos(piste: np.ndarray, retard_s: float, reprises: int = 4,
          perte: float = 0.45) -> np.ndarray:
    """Ajoute des répétitions décroissantes. L'espace, à peu de frais.

    Une vraie réverbération demanderait une convolution de plusieurs secondes ;
    quatre reprises croisées suffisent à éloigner un son, et c'est de distance
    qu'on a besoin, pas d'une salle précise.
    """
    sortie = piste.copy()
    pas = int(retard_s * TAUX)
    gain = perte
    for reprise in range(1, reprises + 1):
        debut = pas * reprise
        if debut >= len(piste):
            break
        sortie[debut:] += piste[:len(piste) - debut] * gain
        gain *= perte
    return sortie


def souffle(n: int, monte: bool = True) -> np.ndarray:
    """Une montée de bruit, qui annonce ce qui vient.

    Du bruit différencié, donc penché vers l'aigu, sous une enveloppe qui
    s'ouvre lentement puis se coupe net. C'est le seul endroit du morceau où
    quelque chose s'arrête brutalement, et c'est ce qui donne de l'élan à ce
    qui suit.
    """
    brut = np.random.default_rng(5).normal(0, 1, n + 1).astype(np.float32)
    aigu = np.diff(brut)
    rampe = np.linspace(0, 1, n, dtype=np.float32) ** 2.2
    return aigu * (rampe if monte else rampe[::-1]) * 0.22


def chant(n: int, hauteur: float) -> np.ndarray:
    """Une voix de synthèse simple, avec un léger vibrato.

    Trois harmoniques seulement et une enveloppe douce : la ligne doit se
    poser au-dessus des nappes sans leur disputer la place. Le vibrato à cinq
    hertz suffit à la distinguer d'une tenue d'orgue.
    """
    t = np.arange(n, dtype=np.float32) / TAUX
    vibrato = 1.0 + 0.004 * np.sin(2 * np.pi * 5.0 * t)
    phase = 2 * np.pi * hauteur * np.cumsum(vibrato) / TAUX
    onde = np.sin(phase) + 0.28 * np.sin(2 * phase) + 0.1 * np.sin(3 * phase)
    return onde * _enveloppe(n, 0.09, 0.9) * 0.3


def pompe(total: int, temps: float, profondeur: float = 0.55) -> np.ndarray:
    """L'enveloppe qui fait respirer les nappes au rythme de la grosse caisse.

    C'est le geste qui définit le genre : à chaque coup, tout ce qui tient
    recule d'un instant puis revient. Sans lui, nappes et percussion sonnent
    comme deux morceaux joués en même temps ; avec lui, elles n'en font qu'un.

    Fabriquée sur un temps puis répétée, parce qu'une enveloppe calculée sur
    les quarante millions d'échantillons d'un morceau de quinze minutes coûte
    cent soixante mégaoctets pour redire mille sept cents fois la même chose.
    """
    n = int(temps * TAUX)
    t = np.arange(n, dtype=np.float32) / TAUX
    un_temps = 1.0 - profondeur * np.exp(-t / 0.17)
    return np.tile(un_temps, total // n + 1)[:total]


def intensite(avance: float) -> float:
    """Ce qui joue, à cet endroit du morceau, de 0 (nappes seules) à 1 (tout).

    Deux creux, aux deux tiers et au premier quart. Un morceau de quinze
    minutes qui garde la même densité du début à la fin n'est pas un morceau,
    c'est une boucle, et quinze minutes de boucle s'entendent comme une panne.
    """
    montee = min(1.0, avance / 0.12)
    sortie = min(1.0, (1.0 - avance) / 0.08)
    creux = 1.0
    for centre, large in ((0.28, 0.05), (0.66, 0.07)):
        creux *= 1.0 - 0.85 * math.exp(-((avance - centre) / large) ** 2)
    return max(0.0, montee * sortie * creux)


def compose(minutes: float, graine: int) -> tuple[np.ndarray, np.ndarray, dict]:
    """Un morceau, en deux couches : ce qui reste au centre, ce qui s'écarte.

    Deux couches et non un mono qu'on élargit ensuite : si la grosse caisse et
    la basse partent dans le retard stéréo avec le reste, le bas du spectre se
    dédouble et le morceau perd son assise — il devient large et mou. Ce qui
    porte le rythme reste donc exactement au milieu, et seules les nappes, les
    cloches et l'arpège s'écartent.
    """
    tirage = random.Random(graine)
    total = int(minutes * 60 * TAUX)
    nom_caractere = tirage.choice(list(CARACTERES))
    trait = CARACTERES[nom_caractere]
    allure = tirage.choice(TEMPOS)
    temps = 60.0 / allure
    mesure = temps * 4
    suite = tirage.choice(SUITES)
    # Transposer la suite d'un morceau à l'autre tout en restant dans le même
    # monde : les dix morceaux doivent pouvoir se suivre sans que le passage de
    # l'un à l'autre s'entende comme un changement de disque.
    tonalite = tirage.choice([-2, 0, 0, 3, 5])

    melange = np.zeros(total, np.float32)
    percussion = np.zeros(total, np.float32)
    cristaux = np.zeros(total, np.float32)
    basse = np.zeros(total, np.float32)

    # Les nappes, par segments de huit mesures, avec un recouvrement qui lie
    # un accord au suivant. Sans recouvrement, chaque changement d'accord fait
    # un trou qu'on entend comme un hoquet.
    segment = mesure * 8
    recouvre = int(2.5 * TAUX)
    debut = 0.0
    while debut < minutes * 60:
        indice = int(debut / segment) % len(suite)
        accord = suite[indice] + tonalite
        # La septième en plus de la triade : trois notes font un accord juste,
        # quatre font un accord qui a une couleur. C'est tout l'écart entre un
        # exercice d'harmonie et quelque chose qu'on laisse tourner.
        notes = [_hauteur(accord + GAMME[d] - 12) for d in (0, 2, 4, 6)]
        notes.append(_hauteur(accord - 24))
        n = min(int(segment * TAUX) + recouvre, total - int(debut * TAUX))
        if n <= 0:
            break
        bout = nappe(n, notes, tirage) * trait["nappe"]
        # Le dernier segment est tronqué par la fin du morceau et peut être
        # plus court que son propre fondu — ce qui arrive d'autant plus que
        # chaque morceau a maintenant son tempo, donc ses mesures à lui.
        lisiere = min(recouvre, n // 2)
        if lisiere:
            bout[:lisiere] *= np.linspace(0, 1, lisiere, dtype=np.float32)
            bout[-lisiere:] *= np.linspace(1, 0, lisiere, dtype=np.float32)
        melange[int(debut * TAUX):int(debut * TAUX) + n] += bout
        debut += segment

    # La pulsation.
    coup = grosse_caisse(int(0.45 * TAUX))
    chh = charleston(int(0.12 * TAUX))
    ohh = charleston(int(0.25 * TAUX), ouvert=True)
    clap = claquement(int(0.22 * TAUX))
    frappe = trait["frappe"]
    battement = 0
    while battement * temps < minutes * 60:
        place = int(battement * temps * TAUX)
        force = intensite(battement * temps / (minutes * 60))
        if force > 0.25:
            fin = min(place + len(coup), total)
            percussion[place:fin] += coup[:fin - place] * (0.9 * force * frappe)
        # Le clap sur les temps faibles. Il arrive plus tôt que la charleston
        # dans la montée : c'est lui qui installe la mesure, et une mesure
        # sans deuxième et quatrième temps ne se compte pas.
        if force > 0.38 and battement % 2 == 1:
            fin = min(place + len(clap), total)
            percussion[place:fin] += clap[:fin - place] * (0.42 * force * frappe)
        if force > 0.45:
            # Le contretemps : c'est lui qui fait avancer, pas la grosse caisse.
            demi = place + int(temps * TAUX / 2)
            fin = min(demi + len(chh), total)
            if demi < total:
                percussion[demi:fin] += chh[:fin - demi] * (0.22 * force * frappe)
        if force > 0.6 and battement % 4 == 3:
            demi = place + int(temps * TAUX / 2)
            fin = min(demi + len(ohh), total)
            if demi < total:
                percussion[demi:fin] += ohh[:fin - demi] * (0.16 * frappe)
        battement += 1

    # La basse : la fondamentale de l'accord, en croches, gardée très ronde.
    note_basse = np.zeros(0, np.float32)
    croche = 0
    while croche * temps / 2 < minutes * 60:
        instant = croche * temps / 2
        force = intensite(instant / (minutes * 60))
        if force > 0.35 and croche % 4 != 3:
            indice = int(instant / segment) % len(suite)
            frequence = _hauteur(suite[indice] + tonalite - 24)
            n = int(temps / 2 * TAUX)
            if len(note_basse) != n:
                note_basse = np.zeros(n, np.float32)
            t = np.arange(n, dtype=np.float32) / TAUX
            onde = (np.sin(2 * np.pi * frequence * t)
                    + 0.3 * np.sin(4 * np.pi * frequence * t))
            onde *= _enveloppe(n, 0.008, 0.16)
            place = int(instant * TAUX)
            fin = min(place + n, total)
            basse[place:fin] += onde[:fin - place] * (0.5 * force)
        croche += 1

    # L'arpège : les notes de l'accord égrenées en doubles-croches, montées
    # puis descendues. C'est ce qui donne l'allure sans rien ajouter de fort —
    # la pulsation dit l'heure, l'arpège dit qu'elle avance.
    double = temps / 4
    n_pince = int(double * 1.6 * TAUX)
    marche = 0
    while marche * double < minutes * 60:
        instant = marche * double
        force = intensite(instant / (minutes * 60))
        # Trois doubles sur quatre : un arpège qui remplit toutes les cases
        # devient un bourdon, et c'est le trou qui fait entendre le rythme.
        if force > 0.42 and marche % 4 != 2:
            indice = int(instant / segment) % len(suite)
            montant = [0, 2, 4, 6, 4, 2]
            degre = montant[marche % len(montant)]
            octave = 12 if (marche // len(montant)) % 2 else 0
            frequence = _hauteur(suite[indice] + tonalite + GAMME[degre] + octave)
            place = int(instant * TAUX)
            fin = min(place + n_pince, total)
            if fin > place:
                cristaux[place:fin] += (pince(n_pince, frequence)[:fin - place]
                                        * (0.26 * force * trait["arpege"]))
        marche += 1

    # Les cloches, posées sur la gamme, avec de l'écho. C'est ce qui donne
    # l'impression qu'il se passe quelque chose sans rien demander à personne.
    instant = mesure * 4
    while instant < minutes * 60:
        force = intensite(instant / (minutes * 60))
        if force > 0.3 and tirage.random() < 0.55:
            indice = int(instant / segment) % len(suite)
            degre = tirage.choice([0, 2, 4, 5, 6])
            octave = tirage.choice([0, 0, 12])
            frequence = _hauteur(suite[indice] + tonalite + GAMME[degre] + octave)
            n = int(2.4 * TAUX)
            place = int(instant * TAUX)
            fin = min(place + n, total)
            if fin > place:
                cristaux[place:fin] += cloche_note(n, frequence)[:fin - place] * (0.5 * force)
        instant += mesure * tirage.choice([1, 2, 2, 4])

    # La ligne mélodique, dans les parties pleines seulement. Quatre notes
    # tenues, reprises à l'octave : de quoi reconnaître le morceau, pas de quoi
    # le regarder.
    instant = mesure * 16
    while instant < minutes * 60:
        force = intensite(instant / (minutes * 60))
        if force > 0.7 and tirage.random() < 0.4:
            indice = int(instant / segment) % len(suite)
            for pas_, degre in enumerate(tirage.sample([0, 2, 4, 6], 4)):
                depart = instant + pas_ * mesure / 2
                if depart >= minutes * 60:
                    break
                frequence = _hauteur(suite[indice] + tonalite + GAMME[degre])
                n = int(mesure / 2 * TAUX)
                place = int(depart * TAUX)
                fin = min(place + n, total)
                if fin > place:
                    cristaux[place:fin] += chant(n, frequence)[:fin - place] * (0.35 * force)
        instant += mesure * 8

    # Les montées, juste avant que la densité remonte.
    for avance in (0.12, 0.33, 0.52, 0.71, 0.86):
        depart = avance * minutes * 60 - 4.0
        n = int(4.0 * TAUX)
        place = int(depart * TAUX)
        fin = min(place + n, total)
        if 0 <= place < fin:
            percussion[place:fin] += souffle(n)[:fin - place]

    cristaux = echos(cristaux, temps * 0.75, reprises=4, perte=0.42)
    # Tout ce qui tient recule à chaque coup, et revient. La percussion, elle,
    # n'est pas touchée : c'est elle qui donne l'ordre.
    respire = pompe(total, temps, trait["pompe"])
    melange *= respire
    melange += cristaux * 0.8
    # La basse respire aussi, et reste au centre avec la percussion : c'est
    # elle et la grosse caisse qui tiennent le morceau debout.
    centre = percussion + basse * respire

    # Les dix dernières et les dix premières secondes s'ouvrent et se ferment.
    # Les morceaux s'enchaînent bout à bout dans le flux, sans fondu possible :
    # c'est donc au morceau de commencer et de finir dans le silence pour que
    # le raccord s'entende comme une respiration et non comme une coupure.
    bord = int(10 * TAUX)
    for piste in (melange, centre):
        piste[:bord] *= np.linspace(0, 1, bord, dtype=np.float32) ** 2
        piste[-bord:] *= np.linspace(1, 0, bord, dtype=np.float32) ** 2

    fiche = {"caractere": nom_caractere, "tempo": allure}
    return centre, melange, fiche


def en_stereo(centre: np.ndarray, large: np.ndarray) -> np.ndarray:
    """Deux voies : le centre des deux côtés, le large décalé d'un côté.

    Douze millisecondes de retard sur la droite pour ce qui s'écarte : au-delà
    de trente l'oreille entend deux sons, en dessous de cinq elle n'entend
    rien. Ce qui porte le rythme n'est pas décalé du tout — un grave dédoublé
    perd son point d'appui, et le morceau avec.

    La normalisation vient à la fin et sur les deux voies ensemble : les
    normaliser séparément déplacerait l'image sonore à chaque crête.
    """
    decalage = int(0.012 * TAUX)
    retard = np.concatenate([np.zeros(decalage, np.float32), large[:-decalage]])
    gauche = centre + large
    droite = centre + retard * 0.97
    crete = max(float(np.abs(gauche).max()), float(np.abs(droite).max()), 1e-6)
    # Un compresseur du pauvre : on écrase les crêtes à la tangente
    # hyperbolique plutôt que de les couper. Couper fait claquer.
    gauche = np.tanh(gauche / crete * 1.6) * 0.82
    droite = np.tanh(droite / crete * 1.6) * 0.82
    return np.stack([gauche, droite], axis=1).reshape(-1).astype(np.float32)


def ecris(piste: np.ndarray, cible: Path) -> None:
    """Passe par ffmpeg : le flux lit des mp3, et un wav de quinze minutes pèse
    cent cinquante mégaoctets pour rien sur un disque qui en tient dix."""
    brut = (np.clip(piste, -1, 1) * 32767).astype(np.int16).tobytes()
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "s16le", "-ar", str(TAUX), "-ac", "2", "-i", "pipe:0",
         "-c:a", "libmp3lame", "-b:a", "192k", str(cible)],
        input=brut, check=True)


def fabrique(dossier: Path, combien: int, minutes: float, graine: int) -> int:
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / "credits.json"
    fiches = json.loads(chemin.read_text(encoding="utf-8")) if chemin.is_file() else {}
    for numero in range(combien):
        nom = f"ventoux-{graine:03d}-{numero + 1:02d}.mp3"
        cible = dossier / nom
        centre, large, fiche = compose(minutes, graine * 1000 + numero)
        ecris(en_stereo(centre, large), cible)
        fiches[nom] = {"auteur": AUTEUR, "titre": f"Mont Serein {graine:03d}.{numero + 1:02d}",
                       "licence": LICENCE, "url": SOURCE, **fiche}
        print(f"  {numero + 1:2d}/{combien}  {nom}  {minutes:.0f} min  "
              f"{fiche['tempo']:.0f} bpm  {fiche['caractere']:6s}  "
              f"{cible.stat().st_size / 1e6:.1f} Mo")
    chemin.write_text(json.dumps(fiches, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{combien} morceaux dans {dossier}, {AUTEUR}, {LICENCE}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--dossier", default=str(ROOT / "data" / "musique"))
    parseur.add_argument("--combien", type=int, default=10)
    parseur.add_argument("--minutes", type=float, default=15.0)
    parseur.add_argument("--graine", type=int, default=1)
    args = parseur.parse_args(argv)
    return fabrique(Path(args.dossier), args.combien, args.minutes, args.graine)


if __name__ == "__main__":
    raise SystemExit(main())
