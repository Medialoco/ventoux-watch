"""Hang a contrail over Mont Serein and see whether the watcher signs it.

The trail is drawn; everything that reads it is the live code in
watcher/contrail.py, on a real frame of the real sky with its real grain. The
flight is a real OpenSky state vector when one is in the visible wedge, and a
plausible one placed there when none is, because on most evenings none is:
the strip of sky above the ridge only holds aircraft between about sixteen and
thirty-two kilometres away.

Its first job is to set a threshold rather than guess one. Sweeping the trail's
brightness from nothing upwards prints the lift the code reads back at each
step, and the same sweep run on the untouched frame says what the empty sky
scores -- which is the number the threshold has to clear.

    .venv/bin/python -m scripts.simulate_contrail --sweep
    .venv/bin/python -m scripts.simulate_contrail --lift 6 --publish

Published entries say so: the label begins with "Simulation" and the entry
carries simulation: true.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from watcher import contrail
from watcher.frustum import Pose
from watcher.scenemap import SceneMap
from watcher.simulate import sensor_noise, trail
from watcher.store import Store

ROOT = Path(__file__).resolve().parents[1]
# Where a jet has to be to show above the ridge here, and where one is put when
# the real sky has none. Measured, not chosen: at eleven kilometres up, the
# strip between the Ventoux crest and the top of the frame is the ring from
# sixteen to thirty-two kilometres out.
DEFAULT_KM = 26.0
DEFAULT_ALT = 11_000.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", default="live", help="photo de départ, ou 'live'")
    parser.add_argument("--stack", type=int, default=10, help="images empilées pour calmer le grain")
    parser.add_argument("--lift", type=float, default=6.0, help="clarté de la traînée, en niveaux de gris")
    parser.add_argument("--sweep", action="store_true", help="balaye la clarté et imprime ce qui est lu")
    parser.add_argument("--null", type=int, default=0, metavar="N",
                        help="mesure N lignes tirées au hasard dans le ciel : ce que le ciel seul vaut")
    parser.add_argument("--km", type=float, default=DEFAULT_KM, help="distance de l'avion")
    parser.add_argument("--alt", type=float, default=DEFAULT_ALT, help="altitude de l'avion")
    parser.add_argument("--bearing", type=float, default=None, help="azimut de l'avion, défaut : l'axe de la caméra")
    parser.add_argument("--heading", type=float, default=45.0, help="cap de l'avion")
    parser.add_argument("--real", action="store_true", help="prend un vol réel du journal OpenSky s'il y en a un de visible")
    parser.add_argument("--publish", action="store_true", help="met la simulation dans le flux")
    parser.add_argument("--out", default="/tmp/contrail-sim.png")
    args = parser.parse_args()

    cfg = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    zones = json.loads((ROOT / "config" / "zones.json").read_text(encoding="utf-8"))
    scene_map = SceneMap.load(ROOT / "config" / "scene.json")
    pose = _pose()
    base = _base_frame(args.frame, cfg, args.stack)
    if base is None:
        print("Pas de photo de départ")
        return 1
    sky = contrail.sky_mask(base.shape, contrail.sky_test(scene_map, zones["polygons"].get("sky")))

    when = time.time()
    if args.null:
        return _null(base, sky, args.null)
    flight = _real_flight(pose, when) if args.real else None
    if flight is None:
        if args.real:
            print("Aucun vol réel dans la bande visible ; avion plausible mis à sa place")
        flight = _made_up(pose, args.km, args.alt,
                          args.bearing if args.bearing is not None else pose.yaw,
                          args.heading, when)
    icao, states = flight
    line = contrail.draw(pose, contrail.flown(states, when))
    inside = [spot for spot in line if 0 <= spot[0] <= 1 and 0 <= spot[1] <= 1]
    call = (states[-1][1].get("callsign") or icao).strip()
    print(f"{call} à {args.alt:.0f} m : {len(line)} points de trajet, {len(inside)} dans le cadre")
    if len(inside) < 2:
        print("La trace ne traverse pas l'image ; essaie une autre distance ou un autre cap")
        return 1
    print(f"  de ({inside[0][0]:.3f},{inside[0][1]:.3f}) à ({inside[-1][0]:.3f},{inside[-1][1]:.3f})")

    if args.sweep:
        return _sweep(base, pose, {icao: states}, when, sky, line)

    drawn = sensor_noise(trail(base, line, lift=args.lift), seed=7)
    found = contrail.find(drawn, pose, {icao: states}, when, sky)
    clean = contrail.find(sensor_noise(base, seed=7), pose, {icao: states}, when, sky)
    _report("ciel avec traînée", found)
    _report("même ciel sans traînée", clean)
    cv2.imwrite(args.out, _mark(drawn, line))
    print("image écrite :", args.out)

    if args.publish and found:
        _publish(found[0], drawn, when)
    return 0


def _sweep(base, pose, flights, when, sky, line) -> int:
    """What the code reads back as the trail is made brighter, step by step.

    The row at zero is the whole point: it is the empty sky measured by the
    same ruler, and any threshold below it would name a flight every night.
    """
    print(f"\n{'dessinée':>9s}  {'lue':>6s} {'sigma':>7s} {'barre':>6s} {'course':>7s} {'points':>7s}  verdict")
    for drawn_lift in (0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 9.0, 14.0):
        frame = base if drawn_lift == 0 else trail(base, line, lift=drawn_lift)
        frame = sensor_noise(frame, seed=7)
        field = contrail.relief(frame)
        lift, sigma, run, count = contrail.measure(field, line, sky)
        bar = max(contrail.MIN_LIFT, contrail.ceiling(field, sky) + contrail.MARGIN)
        named = contrail.find(frame, pose, flights, when, sky)
        verdict = f"signée ({named[0].callsign or named[0].icao24})" if named else "rien"
        print(f"{drawn_lift:9.1f}  {lift:6.2f} {sigma:7.1f} {bar:6.2f} {run:7.3f} {count:7d}  {verdict}")
    print("\nLa ligne à zéro est le ciel seul : elle doit rester sous la barre que ce ciel se fixe.")
    return 0


def _null(base: np.ndarray, sky, count: int) -> int:
    """What the sky alone scores, on lines no aircraft ever made.

    This is the number the threshold exists to clear. The sky is not flat: it
    has cirrus, a moon gradient and the camera's own vignetting, and a line
    dropped at random across it reads something. Until that something is
    measured, any threshold is a guess, and the first wispy night would fill
    the history with flights that happened to point the right way.
    """
    frame = sensor_noise(base, seed=7)
    field = contrail.relief(frame)
    rng = np.random.default_rng(3)
    rows = []
    tries = 0
    while len(rows) < count and tries < count * 40:
        tries += 1
        x1, y1 = rng.uniform(0, 1), rng.uniform(0, 0.30)
        angle = rng.uniform(0, math.pi)
        reach = rng.uniform(0.25, 0.9)
        line = [(x1, y1), (x1 + reach * math.cos(angle), y1 + reach * math.sin(angle) * 0.25)]
        lift, sigma, run, seen = contrail.measure(field, line, sky)
        if seen < 8 or run < contrail.MIN_RUN:
            continue
        rows.append((lift, sigma))
    if not rows:
        print("Aucune ligne au hasard ne tient dans le ciel ; rien à dire")
        return 1
    bar = max(contrail.MIN_LIFT, contrail.ceiling(field, sky) + contrail.MARGIN)
    lifts = np.sort(np.array([row[0] for row in rows]))
    print(f"\n{len(rows)} lignes au hasard dans le ciel, en niveaux de gris :")
    for share in (0.5, 0.9, 0.99, 1.0):
        print(f"  {share*100:5.1f} % en dessous de {np.quantile(lifts, share):+.2f}")
    over = sum(1 for lift, sigma in rows if lift >= bar and sigma >= contrail.MIN_SIGMA)
    print(f"\nLa barre que ce ciel se fixe à lui-même : {bar:.2f} niveaux.")
    print(f"{over} de ces {len(rows)} lignes vides la passeraient.")
    return 0


def _report(title: str, found: list[contrail.Trail]) -> None:
    if not found:
        print(f"{title} : rien de signé")
        return
    for item in found:
        print(f"{title} : {item.callsign or item.icao24} — {item.lift:.2f} niveaux,"
              f" {item.sigma:.0f} sigma, {item.run:.2f} de large, {item.samples} points")


def _made_up(pose: Pose, km: float, alt: float, bearing: float, heading: float,
             when: float) -> tuple[str, list[tuple[float, dict]]]:
    """A plausible airliner where one would be visible, with a flight's manners."""
    angle = math.radians(bearing)
    lat = pose.lat + km * 1000 * math.cos(angle) / 110_540.0
    lon = pose.lon + km * 1000 * math.sin(angle) / (111_320.0 * math.cos(math.radians(pose.lat)))
    state = {
        "icao24": "000sim",
        "callsign": "SIMU001",
        "lat": lat,
        "lon": lon,
        "altitude_m": alt,
        "heading": heading,
        "speed_ms": 235.0,
        "climb_ms": 0.0,
        "country": "",
        "ground": False,
    }
    return "000sim", [(when, state)]


def _real_flight(pose: Pose, when: float) -> tuple[str, list[tuple[float, dict]]] | None:
    """A real flight from the journal whose trail actually crosses the frame."""
    path = ROOT / "data" / "sky.jsonl"
    if not path.is_file():
        return None
    flights: dict[str, list[tuple[float, dict]]] = {}
    for row in path.read_text(encoding="utf-8").splitlines():
        if not row.strip():
            continue
        read = json.loads(row)
        if when - read["t"] > contrail.LOOK_BACK_S:
            continue
        for state in read["aircraft"]:
            if state.get("ground") or state.get("altitude_m") is None:
                continue
            flights.setdefault(state["icao24"], []).append((read["t"], state))
    best = None
    for icao, states in flights.items():
        line = contrail.draw(pose, contrail.flown(states, when))
        inside = [spot for spot in line if 0 <= spot[0] <= 1 and 0 <= spot[1] <= 0.4]
        if len(inside) >= 3 and (best is None or len(inside) > best[0]):
            best = (len(inside), icao, states)
    return (best[1], best[2]) if best else None


def _pose() -> Pose:
    scene = json.loads((ROOT / "config" / "scene.json").read_text(encoding="utf-8"))
    p = scene["pose"]
    return Pose(lat=p["lat"], lon=p["lon"], ele=p["ele"], yaw=p["yaw"], pitch=p["pitch"],
                hfov=p["hfov"], height_m=p.get("height_m", 2.0))


def _base_frame(which: str, cfg: dict, stack: int) -> np.ndarray | None:
    if which != "live":
        return cv2.imread(str(ROOT / which) if not Path(which).is_absolute() else which)
    frames = _grab(cfg["stream_url"], max(1, stack))
    return contrail.steady(frames)


def _grab(url: str, count: int) -> list[np.ndarray]:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", url, "-an",
               "-vf", "fps=1", "-frames:v", str(count), "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
    blob = subprocess.run(command, stdout=subprocess.PIPE, timeout=180).stdout
    frames = []
    start = 0
    while True:
        head = blob.find(b"\xff\xd8", start)
        tail = blob.find(b"\xff\xd9", head + 2) if head >= 0 else -1
        if head < 0 or tail < 0:
            break
        frame = cv2.imdecode(np.frombuffer(blob[head:tail + 2], np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            frames.append(frame)
        start = tail + 2
    return frames


def _mark(frame: np.ndarray, line: list[tuple[float, float]]) -> np.ndarray:
    """The frame with the path the code followed, for looking at afterwards."""
    out = frame.copy()
    height, width = out.shape[:2]
    for (x1, y1), (x2, y2) in zip(line, line[1:]):
        cv2.line(out, (int(x1 * width), int(y1 * height)), (int(x2 * width), int(y2 * height)),
                 (60, 200, 60), 1)
    return out


def _publish(found: contrail.Trail, frame: np.ndarray, when: float) -> None:
    store = Store(ROOT / "data", 30)
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    label = f"Simulation : traînée de {found.callsign or found.icao24.upper()}"
    store.add_event(datetime.fromtimestamp(when, timezone.utc), "contrail", label, "sky", 0.9,
                    encoded.tobytes() if ok else b"",
                    {**found.as_detail(), "simulation": True})
    print("Publié :", label)


if __name__ == "__main__":
    raise SystemExit(main())
