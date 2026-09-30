"""Ne garder qu'une observation par carte, celle que la carte montre.

Un passage revu dans la minute rejoint la carte déjà ouverte, et la carte
n'affiche qu'une lecture : celle qu'elle a retenue. Le veilleur gardait
pourtant l'observation de chaque vue, si bien que sous un même identifiant
s'empilaient jusqu'à quatre raisonnements — neuf pour cent du fichier le
30 septembre. Un lecteur qui prend la première ligne, ou la dernière, rejoue
alors le mauvais.

store.py ne les empile plus. Reste à réparer ce qui est déjà écrit, et la
question est de savoir laquelle garder. On ne la choisit pas en demandant
laquelle redonne le mot de la carte : ce serait se donner raison d'avance.
On la choisit sur la géométrie, écrite au moment des faits de part et d'autre
— la carte porte la boîte de la vue qu'elle montre, chaque observation porte
la sienne — et la plus proche gagne.

Le critère ne sait rien de decide(), et c'est decide() qui le juge : sur les
cinquante-quatre cartes doublonnées du 30 septembre, la boîte la plus proche
retrouve le mot affiché cinquante et une fois, contre trente-cinq pour la
première ligne et vingt pour la dernière.

    .venv/bin/python scripts/tidy_observed.py            # dit ce qu'il ferait
    .venv/bin/python scripts/tidy_observed.py --ecrire   # le fait
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Au-delà, les deux boîtes ne parlent manifestement pas de la même chose, et
# l'on préfère garder la dernière ligne plutôt que de prétendre avoir tranché.
ECART_MAX = 0.5


def ecart(seen: dict, box: list) -> float:
    """Distance entre la boîte d'une observation et celle que la carte montre.

    Trois termes en parts de largeur d'image : la largeur, l'abscisse du
    milieu, l'ordonnée du pied. Pas de racine carrée, ce n'est pas une
    distance dans un plan mais une somme de désaccords.
    """
    if not box or "at_x" not in seen:
        return float("inf")
    return (abs(seen.get("box_w", 0.0) - box[2])
            + abs(seen["at_x"] - (box[0] + box[2] / 2))
            + abs(seen.get("at_y", 0.0) - (box[1] + box[3])))


def main() -> int:
    lecture = argparse.ArgumentParser(description=__doc__)
    lecture.add_argument("--ecrire", action="store_true", help="réécrire le fichier")
    lecture.add_argument("--racine", type=Path, default=ROOT)
    args = lecture.parse_args()

    chemin = args.racine / "data" / "observed.jsonl"
    if not chemin.is_file():
        print(f"Pas de fichier à ranger : {chemin}")
        return 0

    lignes = [json.loads(l) for l in chemin.read_text(encoding="utf-8").splitlines() if l.strip()]
    cartes = json.loads((args.racine / "data" / "events.json").read_text(encoding="utf-8"))["events"]
    boite = {c["id"]: (c.get("detail") or {}).get("box") for c in cartes}

    par = defaultdict(list)
    for row in lignes:
        par[row["id"]].append(row)

    gardees, jetees, faute_de_mieux = [], 0, 0
    for row in lignes:
        groupe = par[row["id"]]
        if len(groupe) == 1:
            gardees.append(row)
            continue
        if groupe[0] is not row:
            continue  # le groupe est traité à sa première ligne
        b = boite.get(row["id"])
        proche = min(groupe, key=lambda r: ecart(r.get("seen") or {}, b))
        if ecart(proche.get("seen") or {}, b) > ECART_MAX:
            proche = groupe[-1]
            faute_de_mieux += 1
        gardees.append(proche)
        jetees += len(groupe) - 1

    print(f"{len(lignes)} lignes pour {len(par)} cartes")
    print(f"   cartes portant plusieurs observations : {sum(1 for g in par.values() if len(g) > 1)}")
    print(f"   lignes écartées                       : {jetees}")
    print(f"   tranchées faute de mieux, sur la dernière vue : {faute_de_mieux}")
    print(f"   il restera                            : {len(gardees)}")

    if not args.ecrire:
        print("\nRien n'a été écrit. Relancer avec --ecrire.")
        return 0
    chemin.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in gardees), encoding="utf-8")
    print(f"\n{chemin} réécrit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
