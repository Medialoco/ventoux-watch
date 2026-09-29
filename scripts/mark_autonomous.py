"""Dire de chaque entrée si son nom vient du modèle ou d'une règle.

Le but est de ne montrer que ce qui a été reconnu tout seul et reconnu juste.
Encore faut-il savoir lequel est lequel, ce que l'historique ne disait pas.

Ce qui est relu se lit dans `seen_as`, la lecture du modèle notée au moment de
la publication. Les entrées antérieures à cette note ne peuvent pas être
tranchées : elles reçoivent `null` et non `false`, parce que « on ne sait pas »
n'est pas « non ».
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import sys  # noqa: E402

sys.path.insert(0, str(ROOT))

from watcher.naming import AUTONOMOUS  # noqa: E402


def main() -> int:
    path = ROOT / "data" / "events.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    tally = {"autonome": 0, "règle": 0, "inconnu": 0}
    for event in payload.get("events") or []:
        detail = event.get("detail") or {}
        measured = detail.get("measured") or {}
        if "seen_as" not in measured:
            detail["autonomous"] = None
            tally["inconnu"] += 1
        else:
            reads = measured["seen_as"]
            # "car 0.58 sur 44 %" : la classe est le premier mot, et la plus
            # sûre est la première de la liste.
            best = reads[0].split()[0] if reads else ""
            ok = best in AUTONOMOUS.get(event.get("type", ""), set())
            detail["autonomous"] = ok
            tally["autonome" if ok else "règle"] += 1
        event["detail"] = detail
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(tally.values())
    print(f"{total} entrées")
    for name, count in tally.items():
        print(f"  {count:4} {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
