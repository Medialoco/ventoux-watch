#!/usr/bin/env python3
"""Ce que la clarté et le décor gardé disent, une fois qu'on en a assez.

Deux nombres sont notés sur chaque tache depuis qu'on sait les prendre : la
clarté rapportée au fond qu'elle recouvre, et ce qu'il est advenu du dessin
dessous. La question qu'ils doivent trancher est simple à énoncer — est-ce
qu'une chose est passée, ou est-ce que la lumière a changé — et ce tableau est
ce qui dira s'ils la tranchent vraiment.

Il range les taches par ce qu'elles se sont révélées être : les publications
relues et confirmées d'un côté, les refus par motif de l'autre. Si la mesure
vaut quelque chose, les véhicules confirmés et les ombres doivent tomber dans
deux colonnes de décor gardé nettement séparées. Si elles se chevauchent, le seuil
n'existe pas et il ne faut pas l'inventer.

    scripts/lighting_report.py
"""

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def _mesure(ligne: dict) -> tuple[float, float] | None:
    """Les deux nombres, ou rien si l'entrée est plus vieille qu'eux."""
    mesure = (ligne.get("detail") or {}).get("measured") or {}
    if "kept" not in mesure:
        return None
    # Zéro veut dire « fond sans grain, je ne sais pas » : le garder ferait
    # descendre chaque moyenne vers une ignorance qui n'est pas un résultat.
    if mesure["kept"] == 0.0:
        return None
    return float(mesure["shade"]), float(mesure["kept"])


def _lignes(chemin: Path) -> list[dict]:
    if not chemin.exists():
        return []
    return [json.loads(ligne) for ligne in chemin.read_text().splitlines() if ligne.strip()]


def rassembler(racine: Path) -> dict[str, list[tuple[float, float]]]:
    """Les taches rangées par ce qu'elles se sont révélées être."""
    par_sorte: dict[str, list[tuple[float, float]]] = defaultdict(list)

    evenements = json.loads((racine / "data/events.json").read_text()).get("events", [])
    for entree in evenements:
        mesure = _mesure(entree)
        if mesure is None:
            continue
        verdict = entree.get("review")
        if verdict == "rejected":
            sorte = "publié puis démenti"
        elif verdict == "accepted":
            sorte = f"confirmé : {entree.get('type', '?')}"
        else:
            sorte = f"publié, non relu : {entree.get('type', '?')}"
        par_sorte[sorte].append(mesure)

    for ligne in _lignes(racine / "data/candidates.jsonl"):
        mesure = _mesure(ligne)
        if mesure is not None:
            par_sorte[f"refusé : {ligne.get('reason', '?')}"].append(mesure)

    return par_sorte


def tableau(par_sorte: dict[str, list[tuple[float, float]]]) -> None:
    if not par_sorte:
        print("Aucune tache mesurée : la veille n'a pas encore tourné avec ces deux nombres.")
        return
    print(f"{'ce que c\'était':34}{'n':>5}{'clarté':>17}{'décor gardé':>19}")
    print(f"{'':34}{'':>5}{'médiane (étendue)':>17}{'médiane (étendue)':>19}")
    for sorte, valeurs in sorted(par_sorte.items(), key=lambda couple: -len(couple[1])):
        clartes = sorted(valeur[0] for valeur in valeurs)
        textures = sorted(valeur[1] for valeur in valeurs)
        clarte = f"{st.median(clartes):.2f} ({clartes[0]:.2f}–{clartes[-1]:.2f})"
        texture = f"{st.median(textures):.2f} ({textures[0]:.2f}–{textures[-1]:.2f})"
        print(f"{sorte:34}{len(valeurs):5}{clarte:>17}{texture:>19}")

    print()
    choses = [v for sorte, vals in par_sorte.items() if sorte.startswith("confirmé") for v in vals]
    if len(choses) < 20:
        print(f"Seulement {len(choses)} taches confirmées comme des choses : trop peu pour")
        print("poser un seuil. Il en faut de jour, quand la route sert.")
        return
    bas = sorted(valeur[1] for valeur in choses)
    print(f"Décor gardé par les choses confirmées : {bas[0]:.2f} au plus bas, "
          f"{bas[int(len(bas) * 0.95)]:.2f} au 95e centile.")
    print("Un seuil ne se pose que s'il laisse passer toutes les choses confirmées.")


if __name__ == "__main__":
    tableau(rassembler(RACINE))
    sys.exit(0)
