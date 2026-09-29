"""How well is a candidate webcam's neighbourhood mapped?

The whole bet of this project is that a scene known from OpenStreetMap can be
measured instead of guessed. That bet is only worth making where the map is
rich, so before pointing the watcher at a second camera the question has to be
asked out loud and answered in numbers rather than hoped for.

Counted against the Mont Serein, which is the only neighbourhood whose map has
been walked through by hand and is therefore the yardstick. Three things
matter, and they are not the same thing:

  - surfaces, because they tell tarmac from meadow and so tell a car that may
    be there from a plume that may not;
  - buildings with a real height, because a height turns a shape into a ruler
    and a default of six metres turns it into a guess;
  - landmarks, the small fixed things that must never be mistaken for a passer-by.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.osm import around  # noqa: E402

RADIUS_M = 600.0
FIXTURE_KEYS = ("man_made", "artwork_type", "historic", "tourism", "amenity", "highway")
SURFACE_KEYS = ("landuse", "natural", "amenity", "leisure")


def look(name: str, lat: float, lon: float, cache: Path) -> dict:
    data = around(lat, lon, RADIUS_M, cache, max_age_s=30 * 86400)
    elements = data.get("elements") or []
    built = [e for e in elements if (e.get("tags") or {}).get("building")]
    tall = [e for e in built if (e.get("tags") or {}).get("height")
            or (e.get("tags") or {}).get("building:levels")]
    roads = [e for e in elements if (e.get("tags") or {}).get("highway")
             and e.get("type") == "way"]
    ground = [e for e in elements if any((e.get("tags") or {}).get(k) for k in SURFACE_KEYS)]
    marks = [e for e in elements
             if e.get("type") == "node" and any((e.get("tags") or {}).get(k) for k in FIXTURE_KEYS)]
    named = [e for e in elements if (e.get("tags") or {}).get("name")]
    return {"nom": name, "objets": len(elements), "bâtis": len(built), "chiffrés": len(tall),
            "routes": len(roads), "surfaces": len(ground), "repères": len(marks), "nommés": len(named)}


def main(candidates: list[tuple[str, float, float]]) -> int:
    root = Path(__file__).resolve().parent.parent
    nest = root / "data" / "osm" / "candidats"
    nest.mkdir(parents=True, exist_ok=True)

    colonnes = ("objets", "bâtis", "chiffrés", "routes", "surfaces", "repères", "nommés")
    print(f"Dans un rayon de {RADIUS_M:.0f} m\n")
    print(f"{'caméra':<26}" + "".join(f"{c:>10}" for c in colonnes))
    etalon = None
    for name, lat, lon in candidates:
        try:
            row = look(name, lat, lon, nest / f"{name}.json")
        except Exception as erreur:  # une carte absente est une réponse, pas une panne
            print(f"{name:<26} illisible : {str(erreur)[:40]}")
            continue
        etalon = etalon or row
        part = "".join(f"{row[c]:>10}" for c in colonnes)
        print(f"{row['nom']:<26}{part}")
        time.sleep(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main([
        ("montserein", 44.183415, 5.262119),
        ("sault", 44.1021, 5.3949),
        ("mormoiron", 44.0686, 5.1832),
        ("castellane", 43.8455, 6.5140),
        ("roquebrune", 43.3433, 6.6828),
        ("grambois", 43.7623, 5.5898),
        ("villelaure", 43.7237, 5.4284),
        ("colmiane", 44.0584, 7.2180),
        ("psv", 44.8087, 6.4734),
        ("montclar", 44.4122, 6.3524),
        ("marseille2", 43.2416, 5.3692),
        ("charance", 44.5638, 6.0671),
    ]))
