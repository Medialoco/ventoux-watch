"""Record a human yes or no on one deduction."""

from __future__ import annotations

import json
import re
from pathlib import Path

VERDICTS = {"accepted": "valide", "rejected": "rejete"}
# What a human may answer to an unnamed crossing. Wider than car and bus since
# 28 September: the road here carries walkers, cyclists and vans, and a review
# that can only say "car" teaches the wrong lesson about half of what passes.
CLASSES = {
    "voiture": ("vehicle", "Voiture"),
    "camion": ("vehicle", "Camion"),
    "bus": ("bus", "Bus"),
    "pieton": ("person", "Piéton"),
    "velo": ("cycle", "Vélo"),
    # Ajouté le 29 septembre, sur un tracteur publié comme voiture. Le modèle
    # ne connaît pas les tracteurs — COCO n'en a pas — donc il ne pourra jamais
    # en nommer un ; mais sans ce mot, le relecteur n'avait aucun moyen de dire
    # ce qu'il y avait, et la leçon se perdait en « faux ».
    "tracteur": ("vehicle", "Tracteur"),
}


# Les mots qui ne nomment rien de précis : ils disent qu'une chose est passée
# sans dire laquelle. Confirmer « voiture » sur l'un d'eux affine une lecture,
# cela ne la dément pas, et compter cela comme une faute punirait la prudence.
# Les lectures qui ne nommaient rien. Les préciser n'est pas les démentir, donc
# elles ne comptent pas comme des fautes dans le taux de justesse.
#
# « Mouvement sur la route » y est resté après son remplacement : l'historique
# en contient des centaines, et les relire comme des erreurs ferait chuter le
# taux sur un changement de mot.
VAGUE = {"véhicule", "mouvement sur la route", "mouvement", "mouvement détecté"}


def _named_something_else(label: str, truth: str) -> bool:
    """La lecture publiée désignait-elle autre chose que ce qui était là ?

    « Véhicule » pour une voiture n'est pas faux, c'est flou ; « voiture » pour
    un camion est faux. La couleur, elle, est écrite après le mot et n'entre pas
    dans la question : « voiture grise » reste une voiture.
    """
    mot = (label or "").strip().lower()
    if not mot or mot in VAGUE:
        return False
    return not mot.startswith((truth or "").strip().lower())


def parse_review(body: str, label: str) -> tuple[str, str, str] | None:
    match = re.search(r"^event_id:\s*(\S+)\s*$", body or "", re.MULTILINE)
    if not match:
        return None
    classe = ""
    found = re.search(r"^classe:\s*(\S+)\s*$", body or "", re.MULTILINE)
    if found:
        classe = found.group(1).strip().lower()
    if label == "valide":
        return match.group(1), "accepted", classe
    if label == "rejete":
        return match.group(1), "rejected", ""
    return None


def lesson(target: dict, verdict: str, classe: str, guessed: str, note: str = "") -> dict:
    """What the correction leaves behind once the entry has been mended.

    A verdict used to move two numbers in a counter, which tells us how often
    we are wrong and nothing about why. The measurements that produced the
    mistake are already on the entry; married to the human's word they become
    the one thing that can settle a threshold: a real reading with its real
    name. Rejections are kept too — knowing a shape is not a car is worth as
    much as knowing it is.
    """
    detail = target.get("detail") or {}
    return {
        "at": target.get("at") or target.get("t") or "",
        "id": target.get("id"),
        "verdict": verdict,
        "truth": CLASSES[classe][1] if classe in CLASSES else "",
        "guessed": guessed,
        # Free words, and only from the corrections written by hand before the
        # buttons existed: "a cloud, and it was in the sky" says more than a
        # rejection ever will.
        "note": note,
        "zone": target.get("zone", ""),
        "photo": target.get("thumb") or target.get("photo", ""),
        "measured": detail.get("measured") or {},
    }


def apply_review(events: list[dict], learning: dict, event_id: str, verdict: str, classe: str = "",
                 lessons: list | None = None, note: str = "") -> bool:
    if verdict not in VERDICTS:
        return False
    target = next((event for event in events if event.get("id") == event_id), None)
    if target is None:
        return False
    changed = False
    guessed = target.get("label", "")
    if classe in CLASSES:
        kind, label = CLASSES[classe]
        detail = dict(target.get("detail") or {})
        if target.get("type") != kind or target.get("label") != label:
            # La marque de correction ne se pose que si la lecture publiée
            # nommait autre chose. Depuis que la page à trancher propose les
            # cinq mots sur chaque carte, confirmer « voiture » sur un
            # « véhicule » est devenu courant : c'est un affinage, et le
            # compter comme une faute ferait mentir le taux de justesse.
            if _named_something_else(guessed, label):
                detail["correction"] = label
            target["type"] = kind
            target["label"] = label
            target["detail"] = detail
            changed = True
    # Ce que c'était vraiment, quand le relecteur a pris la peine de l'écrire.
    #
    # Une ligne barrée dit qu'on s'est trompé, elle ne dit pas sur quoi. Or
    # c'est la seule chose que le lecteur veut savoir, et la seule que nous
    # ayons apprise. « correction » est réservé au renommage par classe et ne
    # se touche jamais deux fois ; celui-ci est un mot libre, qu'on ne pose
    # qu'une fois lui aussi.
    if verdict == "rejected" and note:
        detail = dict(target.get("detail") or {})
        if not detail.get("truth"):
            detail["truth"] = note
            target["detail"] = detail
            changed = True

    previous = target.get("review")
    if previous != verdict:
        if previous in ("accepted", "rejected"):
            learning[previous] = max(0, int(learning.get(previous, 0)) - 1)
        target["review"] = verdict
        learning[verdict] = int(learning.get(verdict, 0)) + 1
        changed = True
    if changed and lessons is not None:
        lessons.append(lesson(target, verdict, classe, guessed, note))
    return changed


def apply_files(root: Path, event_id: str, verdict: str, classe: str = "", note: str = "") -> bool:
    events_path = root / "data" / "events.json"
    learning_path = root / "data" / "learning.json"
    payload = json.loads(events_path.read_text(encoding="utf-8"))
    learning = json.loads(learning_path.read_text(encoding="utf-8")) if learning_path.is_file() else {}
    lessons: list[dict] = []
    if not apply_review(payload.get("events") or [], learning, event_id, verdict, classe, lessons, note):
        return False
    events_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    learning_path.write_text(json.dumps(learning, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (root / "data" / "reviewed.jsonl").open("a", encoding="utf-8") as handle:
        for row in lessons:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True
