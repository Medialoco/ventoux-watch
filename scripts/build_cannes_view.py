"""The Cannes coast as a scene you can walk round.

Writes config/cannes-relief.json and nothing else. Mont Serein's scene.json,
relief.json and OSM cache stay where they are.

The camera is node/14255983894: 43.5467593, 6.9754344, bearing 190°,
camera:mount=pole. The node has no height, so the eye is on the ground the
elevation model gives, and the page opens from above that point. The field
of view is left out: it has not been fitted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The node the site created. Direction and mount are the tags on it.
# 190° is the tag on the node. It is not the perpendicular of the shore.
LAT, LON = 43.5467593, 6.9754344
YAW = 190.0
OSM = "node/14255983894"
REACH = 380.0
# A page viewpoint, not a surveyed pole. Twenty-two metres is high enough
# to see the boulevard, the beach and the sea, and low enough that the
# groyne is still a thing.
STAND_M = 22.0
LOOK_M = 110.0
# The elevation model stays on its own step. The mesh is resampled finer
# so a beach sixty metres wide is a band, not one cell.
FINE_M = 10.0
# Cover codes shared with the page: grey city, park, sand, water.
BUILT, PARK, SAND, WATER = 3, 1, 4, 5


def main() -> int:
    from scripts.build_relief import (
        _beacons,
        _buildings,
        _figures,
        _heightfield,
        _lamps,
        _masts,
        _ribbons,
        _roads,
        _trees,
        _ways,
        _woods,
    )
    from watcher.frustum import Pose
    from watcher.osm import around
    from watcher.terrain import Terrain

    root = Path(__file__).resolve().parents[1]
    osm_dir = root / "data" / "osm"
    osm_dir.mkdir(parents=True, exist_ok=True)
    terrain = Terrain(LAT, LON, REACH, step_m=40.0, cache=osm_dir / "cannes-terrain.json")
    terrain.anchor(LAT, LON)
    holes = terrain.missing()
    if holes:
        print(f"Terrain : {len(holes)} altitudes", flush=True)
        terrain.build(say=lambda done, total: print(f"  {done}/{total}", flush=True))
        left = terrain.missing()
        if left:
            print(f"Terrain : {len(left)} altitudes manquent encore")
            return 1
    ground = float(terrain.height(0.0, 0.0))
    pose = Pose(lat=LAT, lon=LON, ele=ground, yaw=YAW, pitch=0.0, height_m=0.0)
    data = around(LAT, LON, REACH, osm_dir / "cannes-around.json", max_age_s=7 * 86400)
    ways = list(_ways(data, pose, REACH))
    field = _refine_field(_heightfield(terrain, ground, REACH))
    cover = _city_cover(ways, field)
    _flatten_sea(field, cover)

    payload = {
        "pose": {
            **pose.as_dict(),
            "roof_m": 0,
            "stand_m": STAND_M,
            "look_m": LOOK_M,
            "osm": OSM,
            "name": "Cannes : Boulevard du Midi",
        },
        "terrain": field,
        "cover": cover,
        "roads": _roads(ways, terrain, ground) + _groynes(ways),
        "ribbons": _ribbons(ways, terrain, ground) + _shores(ways),
        "buildings": _buildings(ways, terrain, ground),
        "woods": _woods(ways),
        "trees": _trees(data, pose, terrain, ground, REACH),
        "masts": _masts(data, pose, terrain, ground, REACH),
        "figures": _figures(data, pose, terrain, ground, REACH),
        "lamps": _lamps(data, pose, REACH),
        "beacons": _beacons(data, pose, REACH),
    }
    # The lens has not been fitted. Leaving the constructor's default in
    # the file would draw Cannes through a ninety-degree eye it does not have.
    del payload["pose"]["hfov"]

    out = root / "config" / "cannes-relief.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Sol     : {ground:.1f} m")
    print(f"Routes  : {len(payload['roads'])}")
    print(f"Surfaces: {len(payload['ribbons'])}")
    print(f"Bâtiments: {len(payload['buildings'])}")
    print(f"Écrit   : {out}  ({out.stat().st_size // 1024} ko)")
    return 0


def _refine_field(field: dict) -> dict:
    """Resample the heightfield so the shore can be coloured finer than the model."""
    step = float(field["step_m"])
    factor = int(round(step / FINE_M))
    if factor <= 1:
        return field
    return {
        "step_m": round(step / factor, 3),
        "reach_m": field["reach_m"],
        "grid": _refine(field["grid"], factor),
    }


def _refine(grid: list, factor: int) -> list[list[float]]:
    old = np.asarray(grid, dtype=np.float64)
    side = old.shape[0]
    fine = (side - 1) * factor + 1
    out = np.empty((fine, fine), dtype=np.float64)
    for row in range(fine):
        y = row / factor
        y0 = min(int(np.floor(y)), side - 2)
        ty = y - y0
        for col in range(fine):
            x = col / factor
            x0 = min(int(np.floor(x)), side - 2)
            tx = x - x0
            top = old[y0, x0] * (1.0 - tx) + old[y0, x0 + 1] * tx
            bottom = old[y0 + 1, x0] * (1.0 - tx) + old[y0 + 1, x0 + 1] * tx
            out[row, col] = top * (1.0 - ty) + bottom * ty
    return [[round(float(value), 1) for value in line] for line in out]


def _city_cover(ways, field: dict) -> dict:
    """City grey, then parks, then the beach, then the sea out to the edge."""
    step = float(field["step_m"])
    reach = float(field["reach_m"])
    side = len(field["grid"])
    grid = [[BUILT for _ in range(side)] for _ in range(side)]
    parks = [
        points
        for tags, points in ways
        if _is_park(tags) and len(points) >= 4 and np.allclose(points[0], points[-1])
    ]
    for row in range(side):
        north = reach - row * step
        for col in range(side):
            east = col * step - reach
            if any(_inside(east, north, ring) for ring in parks):
                grid[row][col] = PARK
    cover = {"step_m": step, "reach_m": reach, "grid": grid}
    _paint(cover, ways, reach)
    return cover


def _is_park(tags: dict) -> bool:
    return (
        tags.get("leisure") == "park"
        or tags.get("landuse") in {"grass", "meadow"}
        or tags.get("natural") in {"wood", "grassland"}
    )


def _paint(cover: dict, ways, reach: float) -> None:
    """Sand on the beach, water on the sea side of the coastline."""
    step = float(cover["step_m"])
    grid = cover["grid"]
    side = len(grid)
    beaches = [points for tags, points in ways if tags.get("natural") == "beach" and len(points) >= 4]
    coasts = [points for tags, points in ways if tags.get("natural") == "coastline" and len(points) >= 2]
    for row in range(side):
        north = reach - row * step
        for col in range(side):
            east = col * step - reach
            if any(_inside(east, north, ring) for ring in beaches):
                grid[row][col] = SAND
            elif coasts and _at_sea(east, north, coasts, reach):
                grid[row][col] = WATER


def _flatten_sea(field: dict, cover: dict) -> None:
    """The sea is a level. A noisy cell would stand up as a reef."""
    heights = []
    cells = []
    for row, line in enumerate(cover["grid"]):
        for col, code in enumerate(line):
            if code == WATER and row < len(field["grid"]) and col < len(field["grid"][row]):
                heights.append(field["grid"][row][col])
                cells.append((row, col))
    if not heights:
        return
    level = float(np.median(heights))
    for row, col in cells:
        field["grid"][row][col] = round(level, 1)


def _groynes(ways) -> list[dict]:
    out = []
    for tags, points in ways:
        if tags.get("man_made") != "groyne" or len(points) < 2:
            continue
        out.append({"k": "groyne", "w": 4.0, "r": False, "p": [[round(float(e), 1), round(float(n), 1)] for e, n in points]})
    return out


def _shores(ways) -> list[dict]:
    """The beach, as a surface. A freight yard is not one.

    The merchandise station at la Bocca is a closed landuse=railway whose
    ring contains the camera and crosses the sand. Drawn flat, it was a
    brown slab over the view. The beach ring has more corners than that
    yard, and an eighty-point cap was dropping the sand and keeping the yard.
    """
    out = []
    for tags, points in ways:
        if tags.get("natural") != "beach" or len(points) < 4 or not np.allclose(points[0], points[-1]):
            continue
        if len(points) > 400:
            continue
        out.append({"k": "beach", "p": [[round(float(e), 1), round(float(n), 1)] for e, n in points]})
    return out


def _inside(east: float, north: float, ring: np.ndarray) -> bool:
    within = False
    count = len(ring)
    j = count - 1
    for i in range(count):
        ay, ax = float(ring[i][1]), float(ring[i][0])
        by, bx = float(ring[j][1]), float(ring[j][0])
        if (ay > north) != (by > north) and east < (bx - ax) * (north - ay) / (by - ay + 1e-12) + ax:
            within = not within
        j = i
    return within


def _at_sea(east: float, north: float, coasts: list[np.ndarray], reach: float) -> bool:
    """True on the right of the nearest coastline segment inside the model.

    OpenStreetMap walks a coastline with the land on the left and the sea
    on the right. The right-hand side is the water, out to the edge of the
    mesh: a cutoff left the far sea the colour of a meadow.
    """
    best = None
    sea = False
    point = np.array([east, north], dtype=np.float64)
    origin = np.zeros(2, dtype=np.float64)
    for line in coasts:
        for a, b in zip(line[:-1], line[1:]):
            start = np.asarray(a, dtype=np.float64)
            end = np.asarray(b, dtype=np.float64)
            run = end - start
            length = float(np.hypot(run[0], run[1]))
            if length < 1.0:
                continue
            # A kink of the same way, a kilometre along the coast, is not
            # the shore in front of this camera.
            home = float(np.clip(np.dot(origin - start, run) / (length * length), 0.0, 1.0))
            if float(np.hypot(*(start + home * run))) > reach:
                continue
            along = float(np.clip(np.dot(point - start, run) / (length * length), 0.0, 1.0))
            nearest = start + along * run
            dist = float(np.hypot(*(point - nearest)))
            if best is None or dist < best:
                best = dist
                # Cross product: positive means the point is left of start→end.
                cross = float(run[0] * (point[1] - start[1]) - run[1] * (point[0] - start[0]))
                sea = cross < 0
    return bool(sea and best is not None)


if __name__ == "__main__":
    raise SystemExit(main())
