"""Fabrique un Short vertical à partir des erreurs déjà jugées.

Le sujet n'est pas ce que la machine réussit, c'est ce qu'elle rate. Cinq jours
de surveillance ont produit quarante-six identifications qu'un humain a
refusées, et chacune porte en clair ce que c'était vraiment : une statue en
bois, les pierres d'un rond-point, un nuage pris pour un avion. Mises bout à
bout, elles disent mieux que n'importe quelle promesse ce qu'est ce projet —
une machine qui se trompe en public et qu'on corrige.

    .venv/bin/python -m scripts.short_promo
    .venv/bin/python -m scripts.short_promo --combien 12 --morceau PK

Sort un fichier 1080×1920 prêt à téléverser, musique sous Creative Commons
comprise, et écrit à côté de lui le crédit à recopier dans la description.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LARGEUR, HAUTEUR = 1080, 1920
IMAGES_PAR_S = 30
PARIS = ZoneInfo("Europe/Paris")

BLANC = (245, 245, 245)
GRIS = (160, 160, 160)
ROUGE = (60, 60, 220)
VERT = (120, 230, 130)
AMBRE = (60, 190, 250)
CYAN = (235, 215, 70)

# Combien de temps chaque erreur reste à l'écran. En dessous d'une seconde et
# demie on n'a pas le temps de lire les deux lignes, au-dessus de deux on
# s'ennuie — et le Short dure alors plus longtemps que l'attention qu'on lui
# prête.
CARTE_S = 1.9
INTRO_S = 2.6
SORTIE_S = 3.4

# Ce que la veille écrit, et ce que ça dit en anglais. Les étiquettes sont en
# français dans toute la base ; les traduire ici plutôt que de les réécrire
# là-bas garde intacte la trace de ce qui a réellement été publié.
# Ce qu'on ne met pas dans un Short, quoi qu'en dise l'historique.
INTERDITS = ("feu", "Feu", "Incendie", "Fumée", "Panache")

NOMS = {
    "Véhicule": "VEHICLE", "Voiture": "CAR", "Camion": "TRUCK", "Bus": "BUS",
    # Le pluriel aussi : la veille écrit « Piétons » quand ils sont deux, et
    # un nom qui manque à cette table repart tel quel, en français, sur un
    # Short dont tout le reste est en anglais.
    "Piéton": "PEDESTRIAN", "Piétons": "PEDESTRIANS",
    "Véhicules": "VEHICLES", "Voitures": "CARS", "Camions": "TRUCKS",
    "Moto": "MOTORCYCLE", "Vélo": "BICYCLE",
    "Tracteur": "TRACTOR", "Voiture blanche": "WHITE CAR",
    "Voiture bleue": "BLUE CAR", "Voiture jaune": "YELLOW CAR",
    "Voiture verte": "GREEN CAR", "Voiture rouge": "RED CAR",
}

# Les notes des relectures se répètent : cinq jours de veille sur un seul
# rond-point produisent toujours les mêmes méprises. Une poignée de tournures
# couvre l'essentiel, et ce qui n'est pas couvert est simplement passé.
TRADUCTIONS = [
    (r"^la statue en bois.*", "a wooden statue"),
    (r"^le halo des phares.*", "the glow of headlights on the tarmac"),
    (r"^le revêtement de la chaussée.*", "the road surface catching the light"),
    (r"^l'îlot central du rond-point.*", "the middle of the roundabout"),
    (r"^les pierres de l'îlot central.*", "the stones of the roundabout"),
    (r"^le lampadaire du rond-point.*", "a street lamp in the fog"),
    (r"^ombre et soleil.*", "shadow and sunlight at the treeline"),
    (r"^un nuage sur la crête.*", "a cloud on the ridge"),
    (r"^une traînée.*", "a contrail"),
    (r"^une tache de (\d+) fois la taille de l'avion.*",
     r"a blob \1 times the size of the aircraft"),
    (r"^rien dans la découpe.*", "nothing at all in the crop"),
    (r"^un motif d'un mètre sur la chaussée.*", "a one-metre pattern on the road"),
    (r"^le soleil levant dans les arbres.*", "the rising sun in the trees"),
    (r"^la statue en bois au bord du chemin.*", "a wooden statue by the path"),
]


def en_anglais(note: str) -> str:
    for motif, remplacement in TRADUCTIONS:
        if re.match(motif, note, re.I):
            return re.sub(motif, remplacement, note, flags=re.I)
    return ""


def erreurs(racine: Path, combien: int, graine: int | None = None) -> list[dict]:
    """Les identifications qu'un humain a refusées, photo et aveu compris."""
    lignes = (racine / "data" / "reviewed.jsonl").read_text(encoding="utf-8").splitlines()
    gardees = []
    for ligne in lignes:
        if not ligne.strip():
            continue
        fiche = json.loads(ligne)
        if fiche.get("verdict") != "rejected":
            continue
        photo = racine / str(fiche.get("photo") or "")
        verite = en_anglais(str(fiche.get("note") or ""))
        if not verite or not photo.is_file():
            continue
        dit = str(fiche.get("guessed") or "")
        # Rien sur le feu dans un Short. Une vidéo de promotion qui affiche
        # « WILDFIRE STARTING » au-dessus d'un lampadaire est une fausse
        # alerte avec une bande-son, et c'est ce que celle-ci faisait.
        if any(mot in dit for mot in INTERDITS):
            continue
        gardees.append({"photo": photo, "dit": dit,
                        "vrai": verite, "at": str(fiche.get("at") or "")})
    tirage = random.Random(graine)
    tirage.shuffle(gardees)
    # Une méprise par sujet : six statues en bois à la suite ne sont qu'une
    # seule blague racontée six fois.
    vues: set[str] = set()
    choix = []
    for fiche in gardees:
        if fiche["vrai"] in vues:
            continue
        vues.add(fiche["vrai"])
        choix.append(fiche)
        if len(choix) >= combien:
            break
    return choix


def _ecrit(image: np.ndarray, texte: str, y: int, taille: float,
           couleur: tuple[int, int, int], epaisseur: int = 3) -> int:
    """Écrit centré, en repliant sur plusieurs lignes si c'est trop long."""
    mots = texte.split()
    lignes: list[str] = []
    courante = ""
    for mot in mots:
        essai = (courante + " " + mot).strip()
        if cv2.getTextSize(essai, cv2.FONT_HERSHEY_SIMPLEX, taille, epaisseur)[0][0] > LARGEUR - 110:
            lignes.append(courante)
            courante = mot
        else:
            courante = essai
    lignes.append(courante)
    for ligne in lignes:
        large = cv2.getTextSize(ligne, cv2.FONT_HERSHEY_SIMPLEX, taille, epaisseur)[0][0]
        cv2.putText(image, ligne, ((LARGEUR - large) // 2, y), cv2.FONT_HERSHEY_SIMPLEX,
                    taille, couleur, epaisseur, cv2.LINE_AA)
        y += int(taille * 62)
    return y


def carte_erreur(fiche: dict) -> np.ndarray:
    """Une erreur : ce que la machine a dit, la photo, ce que c'était."""
    image = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
    photo = cv2.imread(str(fiche["photo"]))
    y = 300
    y = _ecrit(image, "THE MACHINE SAID", y, 1.0, VERT, 2)
    nom = NOMS.get(fiche["dit"], fiche["dit"].upper())
    y = _ecrit(image, nom, y + 40, 2.0, BLANC, 5)
    if photo is not None:
        cible_h = int(LARGEUR * photo.shape[0] / photo.shape[1])
        vignette = cv2.resize(photo, (LARGEUR, cible_h), interpolation=cv2.INTER_CUBIC)
        haut = y + 60
        image[haut:haut + cible_h] = vignette
        cv2.rectangle(image, (0, haut), (LARGEUR - 1, haut + cible_h), (40, 40, 40), 3)
        y = haut + cible_h
    y = _ecrit(image, "IT WAS", y + 110, 1.0, ROUGE, 2)
    _ecrit(image, fiche["vrai"], y + 36, 1.25, AMBRE, 3)
    quand = fiche["at"]
    try:
        ici = datetime.strptime(quand, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).astimezone(PARIS)
        quand = ici.strftime("%d %b %Y · %H:%M").upper()
    except ValueError:
        pass
    _ecrit(image, quand, HAUTEUR - 120, 0.72, GRIS, 2)
    return image


def cartes_musique(racine: Path, combien: int, graine: int | None) -> list[np.ndarray]:
    """Les pochettes, les noms, les licences. Le sujet, c'est le fonds.

    Montrer les pochettes plutôt que d'écrire « musique libre » : une phrase se
    promet, une pile de disques se constate.
    """
    dossier = racine / "data" / "musique"
    fiches = json.loads((dossier / "credits.json").read_text(encoding="utf-8"))
    avec = [f for f in fiches.values() if f.get("pochette")
            and (dossier / f["pochette"]).is_file()]
    random.Random(graine).shuffle(avec)
    cartes = []
    for fiche in avec[:combien]:
        image = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
        pochette = cv2.imread(str(dossier / fiche["pochette"]))
        cote = LARGEUR - 140
        haut = 520
        if pochette is not None:
            image[haut:haut + cote, 70:70 + cote] = cv2.resize(
                pochette, (cote, cote), interpolation=cv2.INTER_AREA)
        y = _ecrit(image, "NOW PLAYING", 330, 1.0, VERT, 2)
        y = haut + cote + 120
        y = _ecrit(image, fiche["auteur"], y, 1.5, BLANC, 4)
        y = _ecrit(image, fiche["titre"], y + 30, 1.0, GRIS, 2)
        _ecrit(image, fiche["licence"], y + 70, 1.1, CYAN, 3)
        cartes.append(image)
    return cartes


def cartes_horloge(racine: Path) -> list[np.ndarray]:
    """Le sujet est la durée : ce que c'est que de regarder sans fin."""
    textes = [
        ("24 HOURS A DAY", "7 DAYS A WEEK", "NOBODY WATCHING"),
        ("MOST OF THE TIME", "NOTHING HAPPENS", "AT ALL"),
        ("BY DAY", "SHORT TRACKS", "SOMETHING CHANGES"),
        ("AT NIGHT", "LONG DJ SETS", "AN EMPTY ROAD"),
    ]
    cartes = []
    for haut, milieu, bas in textes:
        image = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
        y = _ecrit(image, haut, 700, 1.35, CYAN, 3)
        y = _ecrit(image, milieu, y + 70, 1.9, BLANC, 5)
        _ecrit(image, bas, y + 70, 1.35, GRIS, 3)
        cartes.append(image)
    ennui = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
    _ecrit(ennui, "BOOOOORING", 980, 2.1, AMBRE, 6)
    _ecrit(ennui, "SAYS THE STREAM, OUT LOUD", 1180, 1.0, GRIS, 2)
    cartes.append(ennui)
    return cartes


def cartes_lieu(racine: Path, combien: int, graine: int | None) -> list[np.ndarray]:
    """Les prises justes, celles qu'un humain a confirmées."""
    lignes = (racine / "data" / "reviewed.jsonl").read_text(encoding="utf-8").splitlines()
    bonnes = []
    for ligne in lignes:
        if not ligne.strip():
            continue
        fiche = json.loads(ligne)
        if fiche.get("verdict") != "accepted":
            continue
        photo = racine / str(fiche.get("photo") or "")
        nom = str(fiche.get("truth") or fiche.get("guessed") or "")
        if not nom or not photo.is_file():
            continue
        bonnes.append({"photo": photo, "nom": nom, "at": str(fiche.get("at") or "")})
    tirage = random.Random(graine)
    tirage.shuffle(bonnes)
    vus: set[str] = set()
    cartes = []
    for fiche in bonnes:
        if fiche["nom"] in vus:
            continue
        vus.add(fiche["nom"])
        image = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
        photo = cv2.imread(str(fiche["photo"]))
        y = _ecrit(image, "GOOD CATCH", 340, 1.4, VERT, 4)
        if photo is not None:
            cible_h = int(LARGEUR * photo.shape[0] / photo.shape[1])
            image[y + 90:y + 90 + cible_h] = cv2.resize(
                photo, (LARGEUR, cible_h), interpolation=cv2.INTER_CUBIC)
            y = y + 90 + cible_h
        nom = NOMS.get(fiche["nom"], fiche["nom"].upper())
        _ecrit(image, nom, y + 150, 1.8, BLANC, 5)
        cartes.append(image)
        if len(cartes) >= combien:
            break
    return cartes


def carte_titre(lignes: list[tuple[str, float, tuple[int, int, int]]]) -> np.ndarray:
    image = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
    y = 640
    for texte, taille, couleur in lignes:
        y = _ecrit(image, texte, y + int(taille * 40), taille, couleur,
                   3 if taille < 1.4 else 4)
    return image


def carte_intro() -> np.ndarray:
    image = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
    y = _ecrit(image, "A MACHINE HAS BEEN WATCHING", 620, 1.25, BLANC, 3)
    y = _ecrit(image, "ONE MOUNTAIN ROAD", y + 10, 1.25, BLANC, 3)
    y = _ecrit(image, "DAY AND NIGHT", y + 10, 1.25, BLANC, 3)
    y = _ecrit(image, "WATCHING ONE MOUNTAIN ROAD", y + 90, 1.0, CYAN, 2)
    _ecrit(image, "HERE IS WHAT IT THOUGHT IT SAW", y + 220, 1.15, AMBRE, 3)
    return image


def carte_sortie() -> np.ndarray:
    image = np.zeros((HAUTEUR, LARGEUR, 3), np.uint8)
    y = _ecrit(image, "IT IS WRONG IN PUBLIC", 560, 1.3, BLANC, 3)
    y = _ecrit(image, "AND IT GETS CORRECTED", y + 16, 1.3, BLANC, 3)
    y = _ecrit(image, "FREE TECHNO RADIO", y + 170, 1.5, VERT, 4)
    y = _ecrit(image, "LIVE 24/7", y + 20, 1.5, VERT, 4)
    _ecrit(image, "MONT VENTOUX · 1389 m", y + 110, 1.0, CYAN, 2)
    return image


def _tremble(image: np.ndarray, force: int) -> np.ndarray:
    """Un soubresaut d'un ou deux pixels : sans lui l'image est morte."""
    if force == 0:
        return image
    matrice = np.float32([[1, 0, force], [0, 1, -force]])
    return cv2.warpAffine(image, matrice, (LARGEUR, HAUTEUR), borderMode=cv2.BORDER_REPLICATE)


def bande_son(racine: Path, secondes: float, morceau: str | None,
              graine: int | None = None) -> tuple[Path, dict] | None:
    """Un morceau de la bibliothèque, et sa fiche pour le crédit."""
    dossier = racine / "data" / "musique"
    try:
        fiches = json.loads((dossier / "credits.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    choix = [(nom, f) for nom, f in fiches.items()
             if (dossier / nom).is_file()
             and (morceau is None or morceau.lower() in (f["auteur"] + f["titre"]).lower())]
    if not choix:
        return None
    # Tiré au hasard et assez long, pas le premier de la liste : prendre le
    # premier donnait de l'ambient à un Short qui annonce de la techno, et un
    # morceau plus court que le montage laisserait la fin en silence.
    random.Random(graine).shuffle(choix)
    for nom, fiche in choix:
        if (dossier / nom).stat().st_size / 16_000 >= secondes + 2:
            return dossier / nom, fiche
    nom, fiche = choix[0]
    return dossier / nom, fiche


def plan_du_sujet(racine: Path, sujet: str, combien: int,
                  graine: int | None) -> list[tuple[np.ndarray, float]]:
    """Les cartes d'un Short, ouverture et sortie comprises.

    Quatre angles sur la même chose : ce que la machine rate, ce qu'elle
    attrape, ce qu'on écoute pendant, et ce que c'est que de regarder sans fin.
    Un seul Short qui dirait tout cela ne dirait rien.
    """
    if sujet == "erreurs":
        fautes = erreurs(racine, combien, graine)
        return ([(carte_intro(), INTRO_S)]
                + [(carte_erreur(f), CARTE_S) for f in fautes]
                + [(carte_sortie(), SORTIE_S)])
    if sujet == "musique":
        ouverture = carte_titre([("FREE TECHNO", 1.9, VERT), ("24/7", 1.9, VERT),
                                 ("41 TRACKS", 1.1, BLANC),
                                 ("CREATIVE COMMONS ONLY", 1.0, CYAN)])
        fin = carte_titre([("EVERY ARTIST", 1.3, BLANC), ("NAMED ON SCREEN", 1.3, BLANC),
                           ("WHILE THEY PLAY", 1.3, BLANC),
                           ("LIVE FROM A MOUNTAIN", 1.1, CYAN)])
        return ([(ouverture, INTRO_S)]
                + [(c, CARTE_S + 0.5) for c in cartes_musique(racine, combien, graine)]
                + [(fin, SORTIE_S)])
    if sujet == "nuit":
        ouverture = carte_titre([("ONE ROAD", 1.9, BLANC), ("ONE CAMERA", 1.9, BLANC),
                                 ("NO PRESENTER", 1.1, GRIS)])
        fin = carte_titre([("FREE TECHNO RADIO", 1.5, VERT), ("LIVE 24/7", 1.5, VERT),
                           ("MONT VENTOUX", 1.0, CYAN)])
        return ([(ouverture, INTRO_S)]
                + [(c, CARTE_S + 0.4) for c in cartes_horloge(racine)]
                + [(fin, SORTIE_S)])
    if sujet == "lieu":
        ouverture = carte_titre([("MONT SEREIN", 1.8, BLANC),
                                 ("NORTH FACE OF MONT VENTOUX", 1.0, CYAN),
                                 ("1389 m", 1.4, BLANC),
                                 ("WATCHED AROUND THE CLOCK", 1.0, AMBRE)])
        fin = carte_titre([("IT GETS THINGS RIGHT TOO", 1.2, BLANC),
                           ("FREE TECHNO RADIO", 1.5, VERT), ("LIVE 24/7", 1.5, VERT)])
        return ([(ouverture, INTRO_S)]
                + [(c, CARTE_S) for c in cartes_lieu(racine, combien, graine)]
                + [(fin, SORTIE_S)])
    raise SystemExit(f"Sujet inconnu : {sujet}")


def fabrique(racine: Path, sortie: Path, combien: int, morceau: str | None,
             graine: int | None, sujet: str = "erreurs") -> int:
    plan = plan_du_sujet(racine, sujet, combien, graine)
    if len(plan) <= 2:
        print(f"Rien à montrer pour « {sujet} ».")
        return 1
    duree = sum(tenue for _, tenue in plan)
    son = bande_son(racine, duree, morceau, graine)
    if son is None:
        print("Pas de musique dans data/musique.")
        return 1
    piste, fiche = son

    with tempfile.TemporaryDirectory() as dossier:
        brut = Path(dossier) / "images.mp4"
        ecrivain = cv2.VideoWriter(str(brut), cv2.VideoWriter_fourcc(*"mp4v"),
                                   IMAGES_PAR_S, (LARGEUR, HAUTEUR))
        for index, (carte, tenue) in enumerate(plan):
            for i in range(int(tenue * IMAGES_PAR_S)):
                # Les trois premières images de chaque carte sautent d'un
                # pixel : c'est ce qui fait qu'une suite de photos fixes se
                # regarde comme un montage plutôt que comme un diaporama.
                ecrivain.write(_tremble(carte, 2 if i < 2 else (1 if i < 4 else 0)))
            print(f"  {index + 1:2d}/{len(plan)}")
        ecrivain.release()

        sortie.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(brut), "-i", str(piste),
             "-filter_complex",
             # Un fondu de sortie sur la dernière seconde : couper net une
             # musique donne l'impression que le fichier est tronqué.
             f"[1:a]atrim=0:{duree:.2f},afade=t=out:st={duree - 1.2:.2f}:d=1.2[a]",
             "-map", "0:v", "-map", "[a]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
             "-shortest", str(sortie)],
            check=True)

    credit = (f"Music: {fiche['titre']} — {fiche['auteur']} ({fiche['licence']})\n"
              f"{fiche['url']}\n")
    sortie.with_suffix(".credit.txt").write_text(credit, encoding="utf-8")
    poids = sortie.stat().st_size / 1_048_576
    print(f"\n{sortie} · {duree:.0f} s · {poids:.1f} Mo · {len(plan) - 2} cartes")
    print(credit)
    return 0


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--combien", type=int, default=11)
    parseur.add_argument("--morceau", default=None, help="filtre sur l'auteur ou le titre")
    parseur.add_argument("--graine", type=int, default=None)
    parseur.add_argument("--sujet", default="erreurs",
                         choices=("erreurs", "musique", "nuit", "lieu", "tous"))
    parseur.add_argument("--sortie", default=None)
    args = parseur.parse_args(argv)
    sujets = ("erreurs", "musique", "nuit", "lieu") if args.sujet == "tous" else (args.sujet,)
    for sujet in sujets:
        cible = Path(args.sortie) if args.sortie else ROOT / "data" / f"short_{sujet}.mp4"
        print(f"\n=== {sujet} ===")
        code = fabrique(ROOT, cible, args.combien, args.morceau, args.graine, sujet)
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
