"""Check the distance map against the landmarks surveyed on OpenStreetMap.

Thirteen objects around the Mont Serein have a position on the map, so their
distance from the camera is known by geometry alone, without the terrain having
any say. That makes them a ruler the scene did not build itself, and the one
number this project rests on: everything the watcher measures in metres — the
height of a shape, the speed of a plume — is that shape's distance multiplied
by an angle.

Read at the foot of each landmark, never at its middle. The camera sees the
first hundred metres almost edge-on: the eye is at 1392 m and the ground at
1388, so a metre and a half of height there is worth a hundred metres of
distance. Measured at the middle the map looks sixteen per cent out across the
whole vehicle band, and that reading is the measurement's fault, not the map's.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.config import load_config  # noqa: E402
from watcher.scenemap import SceneMap  # noqa: E402


def main() -> int:
    root = Path(load_config()["_root"])
    carte = SceneMap.load(root / "config" / "scene.json")

    print(f"{'relevé':>8} {'lu':>8} {'rapport':>8}   repère")
    ecarts = []
    for mark in sorted(carte.landmarks, key=lambda m: float(m.get("distance_m") or 0)):
        releve = float(mark.get("distance_m") or 0)
        if releve <= 0:
            continue
        pied = carte.distance_at(min(0.999, mark["x"]), min(0.999, mark["y"] + mark["ry"]))
        if pied <= 0:
            # La visée sort au-dessus de la crête : le repère se détache sur le
            # ciel et le sol n'a rien à en dire.
            print(f"{releve:6.0f} m {'ciel':>8} {'':>8}   {mark['name'][:34]}")
            continue
        ecarts.append(abs(pied / releve - 1))
        print(f"{releve:6.0f} m {pied:6.0f} m {pied / releve:8.2f}   {mark['name'][:34]}")

    if not ecarts:
        print("\nAucun repère relevé : rien à vérifier.")
        return 1
    ecarts.sort()
    print(f"\n{len(ecarts)} repères mesurés, écart médian {ecarts[len(ecarts) // 2]:.1%}, "
          f"pire {ecarts[-1]:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
