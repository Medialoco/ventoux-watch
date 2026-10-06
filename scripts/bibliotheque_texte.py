"""Écrit le compte et la durée de la bibliothèque, sur le site et dans les README.

Les deux chiffres partent ensemble, et ils partent partout : le texte anglais
de la page, sa traduction, le secours écrit dans la page, et les deux README.
Une récolte qui ne met à jour que le nombre de morceaux laisse une durée
fausse à côté d'un compte juste.

La mesure se fait sur le Pi. Le dossier du Mac ne tient que l'album de la
maison : s'en servir publierait seize morceaux et quatre heures.

    .venv/bin/python -m scripts.bibliotheque_texte
    .venv/bin/python -m scripts.bibliotheque_texte --essai
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MACHINE = "ventoux@ventoux.local"
DOSSIER_PI = "/opt/ventoux-watch/data/musique"
# En dessous, c'est le dossier du Mac ou une mesure cassée. On n'écrit pas.
PLANCHER = 100

_FR = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit",
       "neuf", "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize"]
_EN = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
       "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
       "sixteen", "seventeen", "eighteen", "nineteen"]
_DIZ_EN = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
           "eighty", "ninety"]


def mots_fr(n: int) -> str:
    """Le nombre en toutes lettres, comme le reste de la page."""
    if n < 17:
        return _FR[n]
    if n < 20:
        return "dix-" + _FR[n - 10]
    if n < 70:
        dizaine, reste = divmod(n, 10)
        nom = ["", "", "vingt", "trente", "quarante", "cinquante", "soixante"][dizaine]
        if reste == 0:
            return nom
        if reste == 1:
            return nom + " et un"
        return nom + "-" + _FR[reste]
    if n < 80:
        reste = n - 60
        if reste == 11:
            return "soixante et onze"
        return "soixante-" + mots_fr(reste)
    if n < 100:
        reste = n - 80
        if reste == 0:
            return "quatre-vingts"
        return "quatre-vingt-" + mots_fr(reste)
    if n < 200:
        reste = n - 100
        return "cent" if reste == 0 else "cent " + mots_fr(reste)
    centaines, reste = divmod(n, 100)
    tete = mots_fr(centaines) + " cent" + ("s" if reste == 0 else "")
    return tete if reste == 0 else tete + " " + mots_fr(reste)


def mots_en(n: int) -> str:
    """Le nombre en toutes lettres, avec le « and » que la page emploie déjà."""
    if n < 20:
        return _EN[n]
    if n < 100:
        dizaine, reste = divmod(n, 10)
        if reste == 0:
            return _DIZ_EN[dizaine]
        return _DIZ_EN[dizaine] + "-" + _EN[reste]
    centaines, reste = divmod(n, 100)
    tete = _EN[centaines] + " hundred"
    return tete if reste == 0 else tete + " and " + mots_en(reste)


def en_heures_minutes(secondes: float) -> tuple[int, int]:
    """L'heure et la minute les plus proches. Soixante minutes redeviennent une heure."""
    minutes = int(round(secondes / 60.0))
    return divmod(minutes, 60)


def _duree(heures: int, minutes: int, langue: str) -> str:
    if langue == "fr":
        heure = "une heure" if heures == 1 else mots_fr(heures) + " heures"
        minute = "une minute" if minutes == 1 else mots_fr(minutes) + " minutes"
    else:
        heure = "one hour" if heures == 1 else mots_en(heures) + " hours"
        minute = "one minute" if minutes == 1 else mots_en(minutes) + " minutes"
    if heures and minutes:
        lien = " et " if langue == "fr" else " and "
        return heure + lien + minute
    if heures:
        return heure
    return minute


def _capital(texte: str) -> str:
    return texte[:1].upper() + texte[1:]


def phrases(morceaux: int, secondes: float, secondes_maison: float) -> dict[str, str]:
    """Les bouts de phrase, déjà accordés, prêts à remplacer les anciens."""
    heures, minutes = en_heures_minutes(secondes)
    heures_maison, minutes_maison = en_heures_minutes(secondes_maison)
    duree_fr = _duree(heures, minutes, "fr")
    duree_en = _duree(heures, minutes, "en")
    album_fr = _duree(heures_maison, minutes_maison, "fr")
    album_en = _duree(heures_maison, minutes_maison, "en")
    seul_fr = heures == 1 and minutes == 0
    seul_en = heures == 1 and minutes == 0
    seule_maison = heures_maison == 1 and minutes_maison == 0
    un_morceau = morceaux == 1
    tourne = "tourne" if seul_fr else "tournent"
    turn = "turns" if seul_en else "turn"
    play = "plays" if seul_en else "play"
    sont = "en est l\u2019album" if seule_maison else "en sont l\u2019album"
    are = "of that is the album" if seule_maison else "of that are the album"
    tiennent = "tient" if un_morceau else "tiennent"
    sit = "sits" if un_morceau else "sit"
    morceau = "morceau" if un_morceau else "morceaux"
    track = "track" if un_morceau else "tracks"
    return {
        "lead_fr": (f"{_capital(duree_fr)} {tourne} ici, {mots_fr(morceaux)} {morceau}, "
                    f"tous issus de cette bibliothèque. {_capital(album_fr)} {sont} "
                    "Mont Serein 002, écrit pour ce projet."),
        "lead_en": (f"{_capital(duree_en)} {turn} here, {mots_en(morceaux)} {track}, "
                    f"all from that library. {_capital(album_en)} {are} "
                    "Mont Serein 002, written for this project."),
        "hero_fr": (f"{_capital(duree_fr)} de musique libre {tourne} toute la journée, "
                    f"entièrement chez Dogmazic. {_capital(album_fr)} {sont} "
                    f"Mont Serein 002, écrit pour ce projet. {_capital(mots_fr(morceaux))} "
                    f"{morceau} {tiennent} dans une playlist publique, à un clic."),
        "hero_en": (f"{_capital(duree_en)} of free music {play} around the clock, "
                    f"all of it from Dogmazic. {_capital(album_en)} {are} "
                    f"Mont Serein 002, written for this project. {_capital(mots_en(morceaux))} "
                    f"{track} {sit} in a public playlist you can open in a click."),
        "readme_fr": (f"{_capital(duree_fr)}, {mots_fr(morceaux)} {morceau}. "
                      f"{_capital(album_fr)} {sont}"),
        "readme_en": (f"{_capital(duree_en)}, {mots_en(morceaux)} {track}. "
                      f"{_capital(album_en)} {are}"),
    }


def _entre(texte: str, debut: str, fin: str, milieu: str) -> str:
    i = texte.find(debut)
    if i < 0:
        raise SystemExit(f"Introuvable : {debut[:48]}")
    j = texte.find(fin, i + len(debut))
    if j < 0:
        raise SystemExit(f"Introuvable après {debut[:24]} : {fin[:48]}")
    return texte[:i + len(debut)] + milieu + texte[j:]


def _chaine_js(texte: str, cle: str, contient: str, valeur: str) -> str:
    marque = f'{cle}: "'
    curseur = 0
    while True:
        i = texte.find(marque, curseur)
        if i < 0:
            raise SystemExit(f"Introuvable : {cle} contenant {contient}")
        j = texte.find('",', i + len(marque))
        if j < 0:
            raise SystemExit(f"Chaîne non fermée : {cle}")
        if contient in texte[i:j]:
            return texte[:i + len(marque)] + valeur + texte[j:]
        curseur = j + 2


def ecris(morceaux: int, secondes: float, secondes_maison: float,
          racine: Path | None = None) -> dict[str, str]:
    """Pose les phrases. Rend celles qu'il a écrites, pour qu'on les relise."""
    racine = racine or ROOT
    dit = phrases(morceaux, secondes, secondes_maison)
    app = racine / "site" / "app.js"
    page = racine / "site" / "index.html"
    app.write_text(_chaine_js(
        _chaine_js(
            _entre(_entre(app.read_text(encoding="utf-8"),
                          "find the file. ", " The playlist is public.", dit["lead_en"]),
                   "trouver le fichier. ", " La playlist est publique.", dit["lead_fr"]),
            "heroMusic", "free music", dit["hero_en"]),
        "heroMusic", "musique libre", dit["hero_fr"]), encoding="utf-8")
    page.write_text(_entre(page.read_text(encoding="utf-8"),
                           "find the file. ", " The playlist is public.", dit["lead_en"]),
                    encoding="utf-8")
    lien = " [Mont Serein 002](https://play.dogmazic.net/albums.php?action=show&album=11242)"
    for nom, cle in (("README.md", "readme_fr"), ("README.en.md", "readme_en")):
        chemin = racine / nom
        chemin.write_text(_entre(chemin.read_text(encoding="utf-8"),
                                 "playlist_id=4803). ", lien, dit[cle]),
                          encoding="utf-8")
    return dit


_MESURE = r"""
import json, subprocess
from pathlib import Path
dossier = Path(%r)
def duree(chemin):
    rendu = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(chemin)],
        capture_output=True, text=True)
    try:
        return float(rendu.stdout.strip())
    except ValueError:
        return 0.0
total = maison = 0.0
compte = 0
for chemin in sorted(dossier.glob("*.mp3")):
    secondes = duree(chemin)
    if secondes <= 1.0:
        continue
    total += secondes
    compte += 1
    if chemin.name.startswith("ventoux-"):
        maison += secondes
print(json.dumps({"morceaux": compte, "secondes": total, "secondes_maison": maison}))
"""


def _releve(commande: list[str], dossier: str) -> dict:
    fini = subprocess.run(commande, input=_MESURE % dossier,
                          capture_output=True, text=True, check=False)
    if fini.returncode:
        raise SystemExit(fini.stderr.strip() or "mesure refusée")
    return json.loads(fini.stdout)


def mesure(dossier: Path) -> dict:
    """La durée de chaque fichier, demandée au fichier."""
    return _releve([sys.executable, "-"], str(dossier))


def mesure_pi() -> dict:
    """La bibliothèque qui tourne, pas la copie incomplète du Mac."""
    return _releve(["ssh", MACHINE, "python3", "-"], DOSSIER_PI)


def main() -> int:
    partie = argparse.ArgumentParser(description=__doc__)
    partie.add_argument("--dossier", default="",
                        help="mesurer ce dossier au lieu de la bibliothèque du Pi")
    partie.add_argument("--essai", action="store_true",
                        help="montrer les phrases sans rien écrire")
    args = partie.parse_args()
    releve = mesure(Path(args.dossier)) if args.dossier else mesure_pi()
    heures, minutes = en_heures_minutes(releve["secondes"])
    print(f"{releve['morceaux']} morceaux, {heures} h {minutes:02d}")
    if releve["morceaux"] < PLANCHER and not args.essai:
        print(f"Moins de {PLANCHER} morceaux : rien n'est écrit. "
              "Le dossier du Mac ne contient pas la bibliothèque.", file=sys.stderr)
        return 1
    dit = phrases(releve["morceaux"], releve["secondes"], releve["secondes_maison"])
    for nom in ("lead_fr", "lead_en", "readme_fr", "readme_en"):
        print(dit[nom])
        print()
    if args.essai:
        print("Essai : rien n'a été écrit.")
        return 0
    ecris(releve["morceaux"], releve["secondes"], releve["secondes_maison"])
    print("Site et README à jour.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
