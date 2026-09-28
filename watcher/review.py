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
}


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
                 lessons: list | None = None) -> bool:
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
        if target.get("type") != kind or target.get("label") != label or detail.get("correction") != label:
            target["type"] = kind
            target["label"] = label
            detail["correction"] = label
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
        lessons.append(lesson(target, verdict, classe, guessed))
    return changed


def apply_files(root: Path, event_id: str, verdict: str, classe: str = "") -> bool:
    events_path = root / "data" / "events.json"
    learning_path = root / "data" / "learning.json"
    payload = json.loads(events_path.read_text(encoding="utf-8"))
    learning = json.loads(learning_path.read_text(encoding="utf-8")) if learning_path.is_file() else {}
    lessons: list[dict] = []
    if not apply_review(payload.get("events") or [], learning, event_id, verdict, classe, lessons):
        return False
    events_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    learning_path.write_text(json.dumps(learning, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (root / "data" / "reviewed.jsonl").open("a", encoding="utf-8") as handle:
        for row in lessons:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True
