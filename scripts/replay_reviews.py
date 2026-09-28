"""Ask today's model what it makes of the frames we got wrong.

The full frames are gone, but the close-up kept beside each published entry is
the very crop the model was shown. Running the current weights over them tells
us which half of the pipeline each mistake belongs to: a reading the detector
cannot make, or a reading it made that our rules then misused.

Nothing is corrected here. It only reports.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher.config import load_config  # noqa: E402
from watcher.detect import YoloDetector  # noqa: E402

# The word a human used, reduced to the family the detector could name.
FAMILIES = {
    "Voiture": "car", "Voiture blanche": "car", "Voiture orange": "car",
    "Camionnette blanche": "car", "Camionnette jaune": "car", "Estafette": "car",
    "Camion": "truck", "Bus": "bus", "Vélo": "bicycle", "Deux-roues": "bicycle",
    "Moto": "motorcycle", "Piéton": "person", "Piétons": "person",
}


def family(truth: str) -> str:
    return FAMILIES.get(truth, "")


def main() -> int:
    cfg = load_config(ROOT)
    model = YoloDetector(str(ROOT / cfg["model_path"]))
    if not model.ready:
        print("Modèle indisponible")
        return 1

    rows = [json.loads(line) for line in (ROOT / "data" / "reviewed.jsonl").read_text().splitlines()]
    tally: Counter = Counter()
    lines = []
    for row in rows:
        # Matched on the second, not on the identifier: renaming an entry
        # rewrote its type, and the type is part of the identifier.
        stamp = row["at"].replace(":", "-")
        closeup = next((ROOT / "data" / "closeups").glob(f"{stamp}-*.jpg"), None)
        if closeup is None:
            tally["sans gros plan"] += 1
            continue
        image = cv2.imread(str(closeup))
        if image is None:
            tally["illisible"] += 1
            continue
        hits = model.detect(image)
        best = max(hits, key=lambda hit: hit.conf, default=None)
        said = f"{best.cls} {best.conf:.2f}" if best else "rien"
        wanted = family(row["truth"])
        if row["verdict"] == "rejected":
            verdict = "muet" if best is None else "parle"
            tally[f"rejet : le modèle {verdict}"] += 1
        elif not wanted:
            tally["vérité hors classes du modèle"] += 1
            verdict = "?"
        else:
            hit = best is not None and best.cls == wanted
            tally["bonne classe" if hit else "mauvaise classe"] += 1
            verdict = "juste" if hit else "faux"
        lines.append(f"{row['at']}  {row['truth'] or row['note'][:38]:38} dit « {said} »  {verdict}")

    for line in lines:
        print(line)
    print()
    for name, count in tally.most_common():
        print(f"{count:4}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
