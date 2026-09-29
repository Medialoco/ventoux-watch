"""Watch the Mont Serein stream: motion, then a name, then the history."""

from __future__ import annotations

import fcntl
import json
import logging
import math
import os
import select
import subprocess
import tempfile
import time
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from watcher import __version__
from watcher.airports import describe_route
from watcher.config import load_config
from watcher.detect import YoloDetector, body_colour, car_lights
from watcher.drive import DriveUploader
from watcher.geometry import load_zones
from watcher.gtfs import GtfsIndex, PARIS
from watcher.memory import Memory
from watcher.motion import MotionDetector, smoke_ratio, warm_ratio
from watcher.naming import Observation, decide
from watcher.opensky import SkyArchive
from watcher.publish import publish
from watcher.scene import SceneReader, ViewLog, solar_azimuth, solar_elevation
from watcher.scenemap import FLAMMABLE, SceneMap
from watcher.store import Store

log = logging.getLogger("ventoux")
# Above this, on the ground, the thing is longer than a car and the timetable
# is worth opening.
BUS_LENGTH_M = 5.5
CLIP_TYPES = {"plane", "bus", "fire"}
# How long the stream may say nothing before it is opened again. It gives an
# image a second, so half a minute of silence is already a stream that has
# stopped, not one that is merely slow.
STREAM_SILENCE_S = 30
# Below this, the gap is a restart caught in flight rather than a spell of
# blindness worth a line of its own.
INTERRUPTION_FLOOR_S = 30


def _foot_walk(drift: float, span: float, duration_s: float) -> float:
    """How fast the foot walks away from its own footprint, in widths a second.

    Measured against the thing's own width rather than in metres, and that is
    deliberate. Metres would need the survey, which not every webcam will have,
    and they flatter a big blob: a plume sixty metres across that wavers by a
    twentieth of itself moves three metres, which sounds like walking and is
    not. A share of its own width says the same thing about a tractor at eight
    hundred metres and a tractor at eighty, on this camera and on the next one,
    with nothing to calibrate.
    """
    if not (drift and span and duration_s):
        return 0.0
    return drift / span / duration_s


def _climb(rise: float, height_m: float, span: float, duration_s: float) -> float:
    """How fast the top of the shape is climbing, in metres a second.

    Smoke is buoyant: a column off a fire that has just caught lifts at metres
    a second and keeps lifting. Nothing else on this mountain does. A machine,
    a walker, a patch of light have tops that wander with the shape and go
    nowhere, which is a tenth of that.

    Metres again, not pixels, and for the same reason as the width: the number
    means the same thing at four hundred metres and at nine hundred, and on the
    next webcam whose surroundings are surveyed.
    """
    if not (rise > 0 and height_m and span and duration_s):
        return 0.0
    return rise * (height_m / span) / duration_s


def _utc(when: float) -> str:
    return datetime.fromtimestamp(when, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _last_beat(beat: Path) -> float:
    """The second of the last picture treated, or zero on a first run."""
    try:
        return float(beat.read_text().strip())
    except (OSError, ValueError):
        return 0.0


def _note_interruption(journal: Path, stopped: float, now: float) -> float:
    """Write down how long nobody was watching, before watching resumes.

    The distance between two beats is, by construction, the length of a blind
    spell: the beat is written at every picture, so anything longer than a
    second is time the mountain spent unwatched. Read at a start it measures a
    watcher that was down; read inside the loop it measures a stream that went
    quiet. Both are the same thing seen from the outside, and both are written
    here.

    It has to be caught at this instant. One picture later the beat has been
    overwritten and the interruption has left no trace anywhere — which is
    exactly what happened on 27 September, when four hours held barely a minute
    of real watching and it took a reconstruction after the fact to know it.

    It matters because an empty stretch of history has two readings that look
    alike and are not: nothing happened, or nobody was there.
    """
    gap = now - stopped
    if not stopped or gap < INTERRUPTION_FLOOR_S:
        return 0.0
    row = {"start": _utc(stopped), "end": _utc(now), "seconds": int(gap)}
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    spell = f"{int(gap)} s" if gap < 120 else f"{int(gap // 60)} min"
    log.warning("Surveillance interrompue %s, de %s à %s", spell, row["start"], row["end"])
    return gap


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("Veilleur v%s", __version__)
    cfg = load_config()
    root = Path(cfg["_root"])
    if not _only_one(root / "data" / "watch.lock"):
        log.error("Un veilleur tourne déjà. Celui-ci s'arrête.")
        return
    _heartbeat = root / "data" / "battement"
    _interruptions = root / "data" / "interruptions.jsonl"
    # Read before anything else writes it: loading the model and the scene map
    # takes half a minute, and that half minute is blind time too.
    beat_at = _last_beat(_heartbeat)
    zones = load_zones(root / cfg["zones"])
    motion = MotionDetector(
        zones,
        motion_width=cfg["motion_width"],
        min_track_frames=cfg["min_track_frames"],
        max_foreground_ratio=cfg["max_foreground_ratio"],
    )
    yolo = YoloDetector(str(root / cfg["model_path"]))
    if not yolo.ready:
        log.warning("Modèle absent (%s) : les voitures et bus attendront l'export ONNX", cfg["model_path"])
    sky = SkyArchive(
        root / "data" / "sky.jsonl",
        cfg["opensky"]["bbox"],
        cfg["opensky"]["retain_days"],
        cfg["opensky"].get("username") or "",
        cfg["opensky"].get("password") or "",
        cfg["opensky"].get("quiet_s", 240),
        cfg["opensky"].get("client_id") or "",
        cfg["opensky"].get("client_secret") or "",
    )
    camera = cfg["camera"]
    gtfs = GtfsIndex(root / "data" / "gtfs", cfg["gtfs"], camera["lat"], camera["lon"], cfg["gtfs_radius_m"])
    store = Store(root / "data", cfg["history_days"])
    scene = SceneReader(camera["lat"], camera["lon"])
    view = ViewLog(root / "data" / "view.json", exclude=zones.get("exclude") or [])
    memory = Memory(root / "data" / "learning.json")
    scene_map = SceneMap.load(root / "config" / "scene.json")
    if scene_map.ready:
        log.info("Carte de la scène : %d repères, calage %s", len(scene_map.landmarks), scene_map.pose.get("rms"))
    else:
        log.warning("Pas de config/scene.json : lance scripts/build_scene.py pour lire les surfaces")
    drive = DriveUploader(str(root / cfg["drive"]["credentials"]), cfg["drive"].get("folder_id") or "")
    ring: deque[tuple[float, bytes]] = deque(maxlen=14)
    pending: list[dict] = []
    last_fire: dict[str, float] = {}
    alerted: set[int] = set()
    last_gtfs = 0.0
    last_publish = 0.0
    last_view = 0.0

    while True:
        try:
            for frame in _frames(cfg["stream_url"]):
                now = time.time()
                # A sign of life, once a second. Nothing reads it here: it is
                # for the machine watching from outside. The watcher can hang
                # without dying — ffmpeg waiting on a stream that stopped
                # answering keeps the process alive and silent — and a service
                # that is still running is not a service that is still working.
                _note_interruption(_interruptions, beat_at, now)
                beat_at = now
                _heartbeat.write_text(str(int(now)))
                ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if ok:
                    ring.append((now, encoded.tobytes()))
                if now - last_gtfs >= cfg["gtfs_refresh_s"]:
                    gtfs.refresh()
                    last_gtfs = now
                if now - last_view >= 30:
                    moment = datetime.fromtimestamp(now, timezone.utc)
                    current = scene.read(frame, moment)
                    view.note(frame, current.weather, current.temperature_c, moment, current.period)
                    last_view = now
                step = motion.step(frame, now)
                for track in step.ended:
                    _on_track(track, now, cfg, yolo, sky, gtfs, store, last_fire, pending, scene, memory, scene_map)
                for track in _burning(motion.tracks, now, cfg, scene_map, alerted):
                    _on_track(track, now, cfg, yolo, sky, gtfs, store, last_fire, pending, scene, memory, scene_map)
                _flush_clips(pending, ring, now, drive, store)
                due = store.urgent or now - last_publish >= cfg["publish_interval_s"]
                if (store.dirty or view.dirty) and due:
                    publish(root)
                    store.dirty = False
                    store.urgent = False
                    view.dirty = False
                    last_publish = now
        except Exception:
            log.exception("Flux interrompu, nouvel essai dans 10 s")
            time.sleep(10)


def _on_track(track, now, cfg, yolo, sky, gtfs, store, last_fire, pending, scene, memory, scene_map=None) -> None:
    frame = cv2.imdecode(np.frombuffer(track.best_jpeg, dtype=np.uint8), cv2.IMREAD_COLOR) if track.best_jpeg else None
    detections = yolo.detect(frame, track.bbox) if frame is not None else []
    moved = track.best_bbox if any(track.best_bbox) else track.bbox
    detections = [replace(hit, share=_covers(hit.box, moved)) if hit.box else hit for hit in detections]
    when = datetime.fromtimestamp(track.updated, timezone.utc)
    current = scene.read(frame, when)
    scene_map = scene_map or SceneMap()
    box = _norm_box(frame, track)
    surface = scene_map.surface_under(box) if box else ""
    landmark = scene_map.landmark_at(box) if box else None
    fixture = scene_map.landmark_under(box) if box else None
    lit = car_lights(frame, track.bbox) if frame is not None and current.period != "day" else 0.0
    aircraft = sky.ask(track.updated, cfg["opensky"]["match_window_s"]) if _crossed_sky(track, cfg) else []
    width_m = scene_map.metres_across(box) if box else 0.0
    height_m = scene_map.metres_tall(box) if box else 0.0
    trips = gtfs.trips_at(when.astimezone(PARIS), cfg["gtfs_window_min"]) if _might_be_bus(track, detections, width_m, cfg) else []
    duration = max(0.0, track.updated - track.started)
    on_fuel = surface in FLAMMABLE or (track.zone == "slope" and not surface)
    fire_ready = on_fuel and now - last_fire.get("fire", 0.0) >= cfg["fire"]["cooldown_s"]
    obs = Observation(
        zone=track.zone,
        detections=detections,
        aircraft=aircraft,
        trips=trips,
        travel=track.travel,
        area_ratio=track.area_ratio,
        duration_s=duration if fire_ready else 0.0,
        warm_ratio=warm_ratio(track.best_jpeg, track.best_bbox) if fire_ready else 0.0,
        smoke_ratio=smoke_ratio(track.best_jpeg, track.best_bbox) if fire_ready else 0.0,
        rise=track.rise,
        foot_climb=track.foot_climb,
        drift_rate=_foot_walk(track.drift, box[2] if box else 0.0, duration),
        rise_ms=_climb(track.rise, height_m, box[3] if box else 0.0, duration),
        width_m=width_m,
        height_m=height_m,
        area_grow=track.area_grow,
        min_travel=cfg["min_travel"],
        max_sky_area=cfg["max_sky_area"],
        min_conf=cfg["min_conf"],
        fire_sustain_s=cfg["fire"]["sustain_s"],
        fire_grow=cfg["fire"]["grow_ratio"],
        fire_warm=cfg["fire"]["warm_ratio"],
        fire_smoke=float(cfg["fire"].get("smoke_ratio") or 0.35),
        fire_rise=float(cfg["fire"].get("rise") or 0.008),
        period=current.period,
        fogged=current.fogged,
        hazy=current.hazy,
        weather=current.weather,
        surface=surface,
        near_road=scene_map.drivable_near(box) if box else True,
        colour=body_colour(frame, track.best_bbox) if frame is not None and current.period == "day" else "",
        landmark=(landmark or {}).get("name", ""),
        fixture=(fixture or {}).get("name", ""),
        lit_ratio=lit,
        # The middle of the blob, not its corner: an aircraft is matched against
        # where the thing is, and a box records where it begins.
        frames=track.frames,
        # Running off the edge of the picture means the size on the ground is
        # a measurement of whatever part stayed inside it.
        box_w=box[2] if box else 0.0,
        clipped=bool(box) and (box[0] <= 0.002 or box[1] <= 0.002
                               or box[0] + box[2] >= 0.998 or box[1] + box[3] >= 0.998),
        at_x=box[0] + box[2] / 2 if box else -1.0,
        at_y=box[1] + box[3] / 2 if box else -1.0,
        sun_bearing=solar_azimuth(when, cfg["camera"]["lat"], cfg["camera"]["lon"]),
        sun_elevation=solar_elevation(when, cfg["camera"]["lat"], cfg["camera"]["lon"]),
        **_eye(cfg, scene_map),
    )
    decision = decide(obs)
    measured = {
        # What the rule actually weighed. Written down because a refusal with no
        # number behind it cannot be argued with later: the sky has turned down
        # thousands of things and left no way to tell a jet from a cloud edge.
        "travel": round(obs.travel, 4),
        # Travel alone says nothing about a car coming straight at the camera:
        # it barely crosses the picture while it doubles in size. Growth is the
        # other half of the movement, and it was the missing number on the
        # night of 29 September, when a car arriving head-on at the roundabout
        # was left unnamed and the rectangle went to the pool of light its own
        # headlights threw on the tarmac.
        "area_grow": round(track.area_grow, 2),
        # Whether the blob runs into the edge of the picture. A shape cut by
        # the frame has no true size, and the footprint measured from it is a
        # floor rather than a measurement.
        "clipped": bool(obs.clipped),
        "area_ratio": round(obs.area_ratio, 5),
        "duration_s": round(max(0.0, track.updated - track.started), 1),
        "frames": track.frames,
        # The surveyed footprint and what the model actually returned. Every
        # correction so far has had to be diagnosed by guessing at these after
        # the fact; written down, the next one is read straight off the entry.
        "width_m": round(width_m, 1),
        "height_m": round(obs.height_m, 1),
        "rise_ms": round(obs.rise_ms, 2),
        "drift_rate": round(obs.drift_rate, 3),
        "seen_as": [f"{hit.cls} {hit.conf:.2f} sur {hit.share:.0%}" for hit in detections[:4]],
    }
    decision.detail.setdefault("measured", measured)
    if decision.type == "plane" and decision.detail.get("icao24"):
        # Asked now and not before: a route costs a call to OpenSky, and until
        # the rule has settled on one aircraft there is nothing to ask about.
        decision.detail.update(describe_route(sky.route(decision.detail["icao24"], track.updated)))
    if decision.type == "motion" and track.zone == "sky":
        store.add_candidate(when, track.zone, decision.reason, decision.detail)
        return
    if not decision.publish:
        store.add_candidate(when, track.zone, decision.reason, decision.detail)
        log.info("Candidat %s %s", track.zone, decision.reason)
        return
    if memory.observe(track.zone, track.centroid, decision) != "record":
        log.info("Compté sans nouvelle carte %s", decision.label)
        return
    if decision.type in {"motion", "habit"}:
        if _worth_reviewing(decision, cfg, last_fire, now):
            last_fire["unnamed"] = now
            if box:
                decision.detail["box"] = [round(value, 4) for value in box]
            entry = store.add_event(when, decision.type, decision.label, track.zone,
                                    decision.confidence, track.best_jpeg, decision.detail)
            store.keep_closeup(entry, frame, track.best_bbox)
            log.info("Passage soumis à revue %s", track.zone)
            return
        store.add_candidate(when, track.zone, decision.reason, decision.detail)
        return
    if decision.type == "fire":
        last_fire["fire"] = now
    if surface:
        decision.detail["surface"] = surface
    drawn = _box_of_the_named(frame, decision, detections, moved) or box
    if drawn:
        decision.detail["box"] = [round(value, 4) for value in drawn]
    event = store.add_event(when, decision.type, decision.label, track.zone, decision.confidence, track.best_jpeg, decision.detail)
    close = store.keep_closeup(event, frame, track.best_bbox)
    if close and width_m >= BUS_LENGTH_M:
        log.info("Recadrage gardé pour %s : %s", decision.label, close)
    log.info("Publié %s %s", decision.type, decision.label)
    if decision.type in CLIP_TYPES:
        pending.append({"id": event["id"], "after": now + 4, "started": track.started - 8})


_LOCK = None


def _only_one(path: Path) -> bool:
    """True when no other watcher holds the lock.

    Two watchers on one camera read the same frames and write the same history
    twice, and the second copy of an event is indistinguishable from a real one.
    The handle is kept in a module global on purpose: closed, the lock would be
    released and the guard would protect nothing.
    """
    global _LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    _LOCK = path.open("w")
    try:
        fcntl.flock(_LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _LOCK.close()
        _LOCK = None
        return False
    _LOCK.write(f"{os.getpid()}\n")
    _LOCK.flush()
    return True


def _eye(cfg, scene_map) -> dict:
    """Where the camera is and where it points, preferring the fitted pose.

    The figures typed into the config were a first guess; the pose in the scene
    file was fitted against surveyed marks and sits fourteen degrees off it in
    bearing. Asking whether an aircraft is in frame with the guess put it in the
    wrong part of the sky.
    """
    camera = cfg["camera"]
    pose = getattr(scene_map, "pose", None) or {}
    hfov = float(pose.get("hfov") or camera.get("fov") or 90)
    aspect = float(pose.get("aspect") or (16 / 9))
    vfov = 2 * math.degrees(math.atan(math.tan(math.radians(hfov / 2)) / aspect))
    return {
        "camera_lat": float(pose.get("lat") or camera["lat"]),
        "camera_lon": float(pose.get("lon") or camera["lon"]),
        "camera_ele": float(pose.get("ele") or camera.get("ele") or 1390),
        "camera_bearing": float(pose.get("yaw") if pose.get("yaw") is not None else (camera.get("bearing") or 140)),
        "camera_fov": hfov,
        "camera_pitch": float(pose.get("pitch") or 0.0),
        "camera_vfov": vfov,
    }


def _burning(tracks, now, cfg, scene_map, alerted: set) -> list:
    """Tracks that must be judged now, without waiting for them to end.

    A car is read when it has gone, which is soon enough. A fire never goes:
    the plume keeps growing and the track stays open, so waiting for the end
    would mean waiting for the fire to burn out. Once a shape has held on
    flammable ground for the sustain time, it is judged where it stands.
    """
    sustain = float(cfg["fire"]["sustain_s"])
    due = []
    live = {track.id for track in tracks}
    alerted.intersection_update(live)
    for track in tracks:
        if track.id in alerted or now - track.started < sustain:
            continue
        surface = scene_map.surface_under(_norm_box_of(track)) if scene_map.ready else ""
        if surface in FLAMMABLE or (track.zone == "slope" and not surface):
            alerted.add(track.id)
            due.append(track)
    return due


def _norm_box_of(track) -> tuple[float, float, float, float] | None:
    box = track.best_bbox if any(track.best_bbox) else track.bbox
    if not any(box) or not track.best_jpeg:
        return None
    frame = cv2.imdecode(np.frombuffer(track.best_jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    return _norm_box(frame, track)


def _might_be_bus(track, detections, width_m, cfg) -> bool:
    """Worth opening the timetable.

    A car has no departure time, so it is not worth reading the timetable for
    every one that passes. Either the model saw something long, or the ground
    width says the thing is longer than a car.
    """
    if track.zone not in {"road", "roundabout"}:
        return False
    if width_m >= BUS_LENGTH_M:
        return True
    # min_conf is a threshold per class in the config file and a plain number
    # in some callers. Compared whole against a confidence it raised a TypeError,
    # and this line is reached only when the model reads a bus or a truck: the
    # fault lay hidden until the first lorry of 27 September took the watcher
    # down in the middle of the afternoon.
    floor = cfg["min_conf"]
    if isinstance(floor, dict):
        floor = floor["bus"]
    return any(item.cls in {"bus", "truck"} and item.conf >= floor for item in detections)


def _crossed_sky(track, cfg) -> bool:
    """Worth asking OpenSky who was up there.

    A point that stayed put is a star or the mast beacon, and a wide patch is
    a cloud. Neither has a flight number, so neither spends a question.
    """
    if track.zone != "sky":
        return False
    return track.travel >= cfg["min_travel"] and track.area_ratio <= cfg["max_sky_area"]


# Which classes stand behind each word the watcher publishes.
NAMED_BY = {
    "vehicle": {"car", "truck", "bus", "motorcycle", "bicycle"},
    "car": {"car", "truck"},
    "bus": {"bus", "truck"},
    "person": {"person"},
    "animal": {"dog", "horse"},
}
# How much room to leave around the model's box. Tight enough to point at one
# thing, loose enough not to sit on top of it.
BOX_MARGIN = 0.14
# How much of the model's box must fall inside what actually moved. The model
# is given a crop wider than the blob, so it also reads the cars parked at the
# kerb; a third is enough to tell the one that drove past from the ones that
# did not, and low enough that a blob lagging behind a moving car still counts.
BOX_OVERLAP = 0.33


def _overlap(box, other) -> float:
    """What share of the model's box lies inside the thing that moved."""
    ax, ay, aw, ah = box
    bx, by, bw, bh = other
    wide = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    tall = max(0, min(ay + ah, by + bh) - max(ay, by))
    return (wide * tall) / float(max(1, aw * ah))


REVIEW_REASONS = {"unnamed_vehicle"}


def _worth_reviewing(decision, cfg, seen: dict, now: float) -> bool:
    """Should this crossing be put in front of somebody, having no name?

    Unnamed motion is not published — the history is a list of things the
    watcher could name, and filling it with shrugs would make it useless. This
    is the one exception, and it exists because the shrugs are the problem: on
    the evening of 28 September, twenty-six things crossed the road in an hour
    and the model returned no class at all for twenty-five of them. Those are
    the cases worth a human's eye, and until now they left no photograph to
    look at.

    Rate-limited on purpose. A busy afternoon would otherwise put hundreds of
    them on the page, which is not a review queue but a second stream. One
    every five minutes is enough to learn from and few enough to read.
    """
    gap = float(cfg.get("review_unnamed_s") or 0)
    if not gap or decision.reason not in REVIEW_REASONS:
        return False
    return now - seen.get("unnamed", 0.0) >= gap


def _covers(box, other) -> float:
    """The other way round: what share of the thing that moved this box holds.

    The pair are easy to confuse and they answer opposite questions. Overlap
    asks whether the model was looking at the moving thing at all, which is
    what decides where the rectangle goes. This asks whether it was looking at
    all of it, which is what decides whether its word can stand for the whole.
    """
    ax, ay, aw, ah = box
    bx, by, bw, bh = other
    wide = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    tall = max(0, min(ay + ah, by + bh) - max(ay, by))
    return (wide * tall) / float(max(1, bw * bh))


def _box_of_the_named(frame, decision, detections, moved=None) -> tuple[float, float, float, float] | None:
    """Where the model put the thing that was named, if it named one.

    The motion blob holds everything that moved together, and on a roundabout
    that is often a car and a group of walkers at once. Drawing the blob then
    marks the wrong subject: on 27 September a car was published with the red
    box around the pedestrians beside it. The model had read the car and knew
    where it was.

    But the model reads the whole crop, parked cars included, and the most
    confident car in the picture is often the one standing still at the kerb —
    which is exactly what went out at 16:25 the same afternoon. So the two
    must be crossed: the model says what a thing is and where, the motion says
    which of them moved. Confidence only breaks a tie.

    Nothing is forced. Where the model said nothing about the word used — and
    it says nothing about most of what moves here — the blob stands.
    """
    wanted = NAMED_BY.get(decision.type)
    if frame is None or not wanted:
        return None
    hits = [hit for hit in detections if hit.cls in wanted and hit.box]
    if moved:
        hits = [hit for hit in hits if _overlap(hit.box, moved) >= BOX_OVERLAP]
    if not hits:
        return None
    x, y, w, h = max(hits, key=lambda hit: (round(_overlap(hit.box, moved), 2) if moved else 0, hit.conf)).box
    height, width = frame.shape[:2]
    mx, my = w * BOX_MARGIN, h * BOX_MARGIN
    x0 = max(0.0, (x - mx) / width)
    y0 = max(0.0, (y - my) / height)
    x1 = min(1.0, (x + w + mx) / width)
    y1 = min(1.0, (y + h + my) / height)
    if x1 - x0 < 0.002 or y1 - y0 < 0.002:
        return None
    return x0, y0, x1 - x0, y1 - y0


def _norm_box(frame, track) -> tuple[float, float, float, float] | None:
    bbox = track.best_bbox if any(track.best_bbox) else track.bbox
    if frame is None or not any(bbox):
        return None
    height, width = frame.shape[:2]
    x, y, w, h = bbox
    return x / width, y / height, max(w, 1) / width, max(h, 1) / height


def _flush_clips(pending, ring, now, drive, store) -> None:
    ready = [item for item in pending if now >= item["after"]]
    for item in ready:
        pending.remove(item)
        frames = [jpeg for stamp, jpeg in ring if item["started"] <= stamp <= now]
        if len(frames) < 2 or not drive.enabled:
            continue
        url = _encode_and_upload(frames, item["id"], drive)
        if url:
            store.set_clip(item["id"], url)


def _encode_and_upload(frames: list[bytes], event_id: str, drive: DriveUploader) -> str:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"{event_id}.mp4"
        process = subprocess.Popen(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-framerate", "1", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
            stdin=subprocess.PIPE,
        )
        assert process.stdin is not None
        for frame in frames:
            process.stdin.write(frame)
        process.stdin.close()
        process.wait(timeout=60)
        if process.returncode != 0 or not path.is_file():
            return ""
        return drive.upload(path, path.name)


def _frames(url: str):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-i", url, "-an", "-vf", "fps=1",
        "-f", "image2pipe", "-vcodec", "mjpeg", "-",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    assert process.stdout is not None
    buffer = b""
    try:
        while True:
            # Waiting with a limit, because waiting without one is how the
            # watch stops without anyone noticing. The stream gives an image a
            # second; when it dries up, ffmpeg does not die — its own reconnect
            # keeps it alive while it tries to catch the stream again — so a
            # plain read simply never returns. On 27 September the watcher sat
            # like that for forty-six minutes, process alive, log silent, no
            # exception to catch. Twice in the same hour.
            #
            # Running out here ends the generator, which ends the loop that
            # drives it, and the caller opens the stream afresh.
            ready, _, _ = select.select([process.stdout], [], [], STREAM_SILENCE_S)
            if not ready:
                log.warning("Aucune image depuis %s s, le flux est repris", STREAM_SILENCE_S)
                break
            # read1 takes what has arrived; read would wait for the full count.
            chunk = process.stdout.read1(65536)
            if not chunk:
                break
            buffer += chunk
            while True:
                start = buffer.find(b"\xff\xd8")
                end = buffer.find(b"\xff\xd9", start + 2 if start >= 0 else 0)
                if start < 0 or end < 0:
                    if start > 0:
                        buffer = buffer[start:]
                    elif start < 0 and len(buffer) > 1_000_000:
                        buffer = b""
                    break
                payload = buffer[start : end + 2]
                buffer = buffer[end + 2 :]
                frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    yield frame
    finally:
        process.kill()


if __name__ == "__main__":
    main()
