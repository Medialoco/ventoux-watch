"""Compter ce qu'on nomme, ce qu'on rate, et pourquoi on le rate.

Le journal des observations garde, pour chaque passage, l'intégralité de ce que
« decide » a eu sous les yeux. On peut donc rejouer la décision hors ligne,
autant de fois qu'on veut, et comparer deux versions du code sur exactement les
mêmes scènes — ce qui est la seule façon honnête de dire qu'on a amélioré
quelque chose. Un taux mesuré sur les passages d'aujourd'hui et comparé à ceux
d'avant-hier ne compare que la météo.

Le dénominateur est le passage qui traverse la chaussée : c'est ce que les gens
regardent, et c'est là qu'un raté se voit. Le numérateur est le passage à qui
l'on a donné un nom. Entre les deux, on range les échecs par cause, parce qu'un
taux ne dit pas quoi réparer.

    .venv/bin/python scripts/mesure_identification.py /tmp/observed.jsonl --depuis 2026-10-03
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from dataclasses import fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher.naming import Decision, Detection, Observation, Trip, decide  # noqa: E402

# Les zones où passe ce qui nous intéresse. Le reste du cadre — ciel, pente,
# forêt — se juge autrement et n'a rien à faire dans ce compte-là.
PASSANTES = {"road", "roundabout"}
# Ce qui compte comme « nommé ». Un passage publié sous le mot « mouvement »
# n'est pas une identification : c'est l'aveu qu'on n'en a pas trouvé.
NOMMES = {"vehicle", "car", "truck", "bus", "person", "cycle", "animal",
          "plane", "aircraft"}


def relit(seen: dict) -> Observation:
    """Reconstruire l'observation telle que « decide » l'avait reçue."""
    connus = {f.name for f in fields(Observation)}
    brut = {k: v for k, v in seen.items() if k in connus}
    brut["detections"] = [
        Detection(**{k: v for k, v in d.items()
                     if k in {f.name for f in fields(Detection)}})
        for d in seen.get("detections") or []]
    brut["trips"] = [
        Trip(**{k: v for k, v in t.items() if k in {f.name for f in fields(Trip)}})
        for t in seen.get("trips") or []]
    if isinstance(brut.get("detections", None), list):
        for lecture in brut["detections"]:
            if isinstance(lecture.box, list):
                lecture.box = tuple(lecture.box)
    return Observation(**brut)


def cause(obs: Observation, verdict: Decision) -> str:
    """Pourquoi ce passage n'a pas reçu de nom, en un mot rangeable."""
    if not obs.detections:
        return "aucune lecture"
    meilleure = max(obs.detections, key=lambda d: d.conf)
    if meilleure.share < 0.2:
        return f"lecture à côté ({meilleure.cls} {meilleure.conf:.2f}, {meilleure.share:.0%})"
    if verdict.action != "publish":
        return f"écartée : {verdict.reason or 'sans motif'}"
    return f"publiée « {verdict.type} » : {verdict.reason or 'sans motif'}"


def main() -> int:
    plaidoyer = argparse.ArgumentParser(description=__doc__)
    plaidoyer.add_argument("journal", type=Path, nargs="?",
                           default=Path("data/observed.jsonl"))
    plaidoyer.add_argument("--depuis", default="", help="ne garder que les id ≥ ce préfixe")
    plaidoyer.add_argument("--detail", type=int, default=12,
                           help="combien de ratés montrer en entier")
    args = plaidoyer.parse_args()

    total = nommes = 0
    causes: collections.Counter = collections.Counter()
    # Le jour et la nuit ne se jugent pas ensemble. Une webcam qui ne voit rien
    # à trois heures du matin n'a pas de défaut à corriger ; une webcam qui rate
    # une voiture à midi, si. Les mélanger donne un taux qui ne veut rien dire
    # et qui monte ou descend avec la saison.
    #
    # C'est la ligne de fond, on n'en change pas. De jour on nomme les trois
    # quarts ; de nuit le modèle ne pose souvent aucune lecture — et ce n'est
    # ni l'exposition ni le cadrage, les deux ont été mesurés et écartés.
    # Reste la taille apparente, les lampes qui vacillent, le suivi du cœur
    # plutôt que de la flaque. On reprend ça à chaque mesure.
    periodes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    rates: list[tuple[str, Observation, str]] = []
    for ligne in args.journal.read_text().splitlines():
        if not ligne.strip():
            continue
        note = json.loads(ligne)
        if args.depuis and note["id"] < args.depuis:
            continue
        seen = note["seen"]
        if seen.get("zone") not in PASSANTES:
            continue
        total += 1
        obs = relit(seen)
        verdict = decide(obs)
        periodes[obs.period]["total"] += 1
        if verdict.action == "publish" and verdict.type in NOMMES:
            nommes += 1
            periodes[obs.period]["nommé"] += 1
            continue
        motif = cause(obs, verdict)
        causes[motif.split(" (")[0].split(" : ")[0]] += 1
        periodes[obs.period][motif.split(" (")[0].split(" : ")[0]] += 1
        rates.append((note["id"], obs, motif))

    if not total:
        print("Aucun passage sur la chaussée dans cette tranche.")
        return 1
    print(f"{nommes} nommés sur {total} passages de chaussée — {nommes / total:.0%}")
    print(f"{total - nommes} ratés, par cause :")
    for motif, combien in causes.most_common():
        print(f"   {combien:4}  {motif}")
    print()
    for moment in ("day", "twilight", "night"):
        compte = periodes.get(moment)
        if not compte:
            continue
        part = compte["nommé"] / compte["total"]
        reste = "  ".join(f"{m} {n}" for m, n in compte.most_common()
                          if m not in ("total", "nommé"))
        print(f"   {moment:9} {compte['nommé']:3}/{compte['total']:<3} {part:4.0%}   {reste}")
    print()
    for identifiant, obs, motif in rates[-args.detail:]:
        lectures = ", ".join(f"{d.cls} {d.conf:.2f}@{d.share:.0%}" for d in obs.detections) or "—"
        print(f"{identifiant}")
        print(f"      {motif}")
        print(f"      zone={obs.zone} surface={obs.surface} {obs.period} "
              f"largeur={obs.width_m:.1f}m hauteur={obs.height_m:.1f}m "
              f"doute={obs.distance_doubt:.2f} box_w={obs.box_w:.3f} images={obs.frames}")
        print(f"      lectures : {lectures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
