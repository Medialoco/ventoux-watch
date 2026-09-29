"""Draw entries at random to be read by a human.

The fifty-four readings corrected so far are not a sample: they are the ones
that caught the eye, and what catches the eye is what looks wrong. One right
out of fifty-four says how bad the worst of it is, not how good the whole is.
A rate that means anything has to come from entries picked without looking.

Seeded, so the same draw can be made again and a later one compared with it.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 29
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    events = json.loads((ROOT / "data" / "events.json").read_text(encoding="utf-8"))["events"]
    pool = [event for event in events
            if not (event.get("detail") or {}).get("simulation") and not event.get("review")]
    drawn = random.Random(seed).sample(pool, min(count, len(pool)))
    drawn.sort(key=lambda event: event["t"])

    print(f"{len(pool)} entrées jamais relues, {len(drawn)} tirées avec la graine {seed}\n")
    for index, event in enumerate(drawn, 1):
        detail = event.get("detail") or {}
        measured = detail.get("measured") or {}
        seen = ", ".join(measured.get("seen_as") or []) or "rien"
        print(f"{index:2}. {event['t']}  {event['label']}")
        print(f"    {event.get('zone', '')} · le modèle a lu : {seen}")
        print(f"    {event.get('thumb', '')}")
        print(f"    id {event['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
