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
from zoneinfo import ZoneInfo

import cv2
import numpy as np

from watcher import __version__
from watcher.airports import describe_route
from watcher.config import load_config
from watcher.detect import YoloDetector, body_colour, car_lights
from watcher import direct
from watcher.drive import DriveUploader
from watcher.geometry import load_zones
from watcher.gtfs import GtfsIndex, PARIS
from watcher.memory import Memory
from watcher.motion import MotionDetector, smoke_ratio, warm_ratio
from watcher.naming import (CLASSES_SURES, CONFIANCE_SURE, RIEN_A_JUGER,
                            Observation, decide, named_itself, refusal_words,
                            write_observation)
from watcher.opensky import SkyArchive
from watcher.publish import publish
from watcher.scene import SceneReader, ViewLog, solar_azimuth, solar_elevation
from watcher.scenemap import FLAMMABLE, SceneMap
from watcher.store import BUS_LENGTH_M, Store

log = logging.getLogger("ventoux")
CLIP_TYPES = {"plane", "bus", "fire"}
# How long the stream may say nothing before it is opened again. It gives an
# image a second, so half a minute of silence is already a stream that has
# stopped, not one that is merely slow.
STREAM_SILENCE_S = 30
# Below this, the gap is a restart caught in flight rather than a spell of
# blindness worth a line of its own.
INTERRUPTION_FLOOR_S = 30
# How long to wait before opening the stream again, and how long that wait may
# grow. A stream that refuses once will usually refuse the next second too:
# ffmpeg gives up in under a second on an unreadable playlist, so a loop with
# no pause in it asks the server three thousand times in forty minutes. That
# is what happened on 29 September, and on a thousand cameras the same loop
# would be an attack on the very provider we depend on.
STREAM_RETRY_S = 2
# Combien de temps les pistes restent lisibles par le flux.
#
# Le flux montre la montagne avec une vingtaine de secondes de retard. Une
# piste effacée à la seconde où elle se ferme n'atteint jamais l'écran : le
# rectangle et son code se dessineraient sur une image déjà passée, dans un
# fichier qui ne les contient plus. Quatre-vingt-dix secondes couvrent ce
# retard, et la lecture du code, sans garder la nuit entière en mémoire.
CHERCHE_S = 150.0
# Un piéton reste souvent une minute. On redemande la classe tant qu'il est
# là, pas seulement quand il part : le spectateur voit la recherche, et la
# classe peut tomber pendant qu'il est encore dans le champ.
RELIRE_S = 4.0
LOS_ANGELES = ZoneInfo("America/Los_Angeles")
STREAM_RETRY_MAX_S = 60


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


CRETE_PAS_S = 300.0


def _note_ridge(journal: Path, current, now: float) -> None:
    """La jauge de brouillard, relevée toutes les cinq minutes.

    Le seuil qui fait taire la veille sous brouillard est un nombre absolu, et
    la jauge ne lit pas la même chose selon l'heure : une crête n'a pas de
    contraste dans le noir. Sur treize cents vues d'archive, la médiane de jour
    tient entre 106 et 144 et celle de nuit entre 40 et 59 — le seuil est posé
    à 40, c'est-à-dire au milieu du bruit nocturne. Les quarante-neuf
    observations nocturnes conservées ont toutes été refusées pour brouillard,
    nuit claire comprise.

    Pour poser un seuil de nuit il faut savoir ce que la jauge lit par nuit
    claire, et rien ne le gardait : le relevé n'existait qu'au moment de la
    décision, jamais dans le temps. Ceci le garde. Quelques nuits de ce journal
    suffiront à écrire le seuil nocturne sur des mesures plutôt que sur une
    intuition, ce qui est la seule façon de pouvoir ensuite le refaire sur une
    autre caméra.
    """
    ligne = {
        "t": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
        "ridge": round(current.ridge, 1),
        "period": current.period,
        "weather": current.weather,
    }
    with journal.open("a", encoding="utf-8") as sortie:
        sortie.write(json.dumps(ligne, ensure_ascii=False) + "\n")


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


def _next_wait(seen: int, wait: float) -> float:
    """How long to wait before asking the stream again.

    A stream that gave pictures and then stopped deserves to be reopened at
    once: it was working a second ago. One that gave nothing at all is
    refusing, and asking faster will not make it answer — it only turns our
    watch into a hammer on somebody else's server.
    """
    if seen:
        return STREAM_RETRY_S
    return min(wait * 2, STREAM_RETRY_MAX_S)


def _published(root: Path) -> bool:
    """Send the history out, and never let that failure stop the watching.

    Publishing goes through git, which depends on a network, a remote and a
    history that two machines may have touched. All three can fail, and none
    of them is a reason to stop looking at the mountain. Before this, a
    rejected push threw out of the picture loop: the stream was reopened and
    the background model — half a minute of learning about this scene — was
    thrown away with it, over a git error.

    What is not published stays marked as owed, and goes out at the next turn.
    """
    try:
        publish(root)
        return True
    except Exception:
        log.exception("Publication impossible, la veille continue")
        return False


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
    _crete = root / "data" / "crete.jsonl"
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
    # Les pistes encore assez fraîches pour que le flux les dessine, code
    # compris. L'identifiant de piste en clé : une piste qui se ferme y
    # reste jusqu'à ce que son dernier point ait plus de CHERCHE_S.
    cherche: dict[int, dict] = {}
    annonces: set[int] = set()
    score = _charge_score(root / "data" / "score.json")
    _aligne_prises(score, store.events, root / "data" / "score.json")
    pending: list[dict] = []
    last_fire: dict[str, float] = {}
    alerted: set[int] = set()
    last_gtfs = 0.0
    last_publish = 0.0
    last_view = 0.0
    last_ridge = 0.0

    wait = STREAM_RETRY_S
    while True:
        seen = 0
        try:
            # Deux heures, et il ne faut jamais les confondre. « now » est
            # l'heure d'ici : elle dit si ce programme est vivant et quand il a
            # publié pour la dernière fois. « prise » est l'heure de la
            # montagne : elle date tout ce qui parle de l'image — la piste, le
            # relevé, l'événement — parce que c'est la seule que la diffusion
            # saura retrouver pour poser le rectangle au bon endroit.
            url, secours = _choisir_la_webcam(cfg)
            if secours:
                _repart_le_fond(motion, _zones_secours(cfg) or zones)
                carte = SceneMap()
                log.info("Veille sur la webcam de secours")
            elif motion.zones is not zones:
                _repart_le_fond(motion, zones)
                carte = scene_map
            else:
                carte = scene_map
            cherche.clear()
            annonces.clear()
            sonde_source = time.time()
            for frame, prise in _frames(url, horloge=secours):
                seen += 1
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
                    ring.append((prise, encoded.tobytes()))
                if now - last_gtfs >= cfg["gtfs_refresh_s"]:
                    gtfs.refresh()
                    last_gtfs = now
                if now - last_view >= 30:
                    moment = datetime.fromtimestamp(prise, timezone.utc)
                    current = scene.read(frame, moment)
                    view.note(frame, current.weather, current.temperature_c, moment, current.period)
                    last_view = now
                    if now - last_ridge >= CRETE_PAS_S:
                        _note_ridge(_crete, current, prise)
                        last_ridge = now
                step = motion.step(frame, prise)
                _note_cherche(cherche, annonces, motion.tracks, step.ended, frame, prise,
                              root / "data" / "cherche.json", score, root / "data" / "score.json")
                for track in step.ended:
                    _on_track(track, prise, cfg, yolo, sky, gtfs, store, last_fire, pending, scene, memory, carte, score)
                for track in _burning(motion.tracks, prise, cfg, carte, alerted):
                    _on_track(track, prise, cfg, yolo, sky, gtfs, store, last_fire, pending, scene, memory, carte, score)
                for track in _a_relire(motion.tracks, prise):
                    _on_track(track, prise, cfg, yolo, sky, gtfs, store, last_fire, pending, scene, memory, carte, score, tot=True)
                if now - sonde_source >= 60.0 and _mont_serein_vif(cfg) != (not secours):
                    log.info("La veille change de webcam")
                    break
                _flush_clips(pending, ring, prise, drive, store)
                due = store.urgent or now - last_publish >= cfg["publish_interval_s"]
                if (store.dirty or view.dirty) and due:
                    if _published(root):
                        store.dirty = False
                        store.urgent = False
                        view.dirty = False
                    last_publish = now
        except Exception:
            log.exception("Flux interrompu")
        if not seen:
            log.warning("Flux muet, nouvel essai dans %s s", wait)
        time.sleep(wait)
        wait = _next_wait(seen, wait)


def _on_track(track, now, cfg, yolo, sky, gtfs, store, last_fire, pending, scene, memory, scene_map=None, score=None, tot: bool = False) -> None:
    if getattr(track, "tenu", False):
        return
    # La mer et le sable sont dessinés, pas nommés. Une vague lue « piéton »
    # féliciterait l'écume, et le modèle n'a pas le temps : il reste aux
    # voitures et aux passants, sur la route et le trottoir.
    if track.zone in {"sea", "beach"}:
        return
    frame = cv2.imdecode(np.frombuffer(track.best_jpeg, dtype=np.uint8), cv2.IMREAD_COLOR) if track.best_jpeg else None
    # L'image et la boîte doivent venir du même instant.
    #
    # « best_jpeg » est la vue où la tache était la plus grande ; « best_bbox »
    # est son rectangle, écrit sur la même ligne. « bbox », lui, est réécrit à
    # chaque image et désigne la dernière position connue. On découpait donc la
    # bonne image à l'endroit où le sujet n'était plus, et le détecteur
    # regardait de l'herbe. Sur 306 passages traversant la chaussée sans être
    # nommés, 268 n'avaient reçu aucune lecture, pas même fausse — un réseau à
    # qui l'on montre une voiture de cent soixante pixels ne rend pas une liste
    # vide. C'est aussi pourquoi le gros plan, lui, se lisait : il est découpé
    # sur « best_bbox » depuis toujours.
    moved = track.best_bbox if any(track.best_bbox) else track.bbox
    detections = yolo.detect(frame, moved) if frame is not None else []
    detections = [replace(hit, share=_covers(hit.box, moved)) if hit.box else hit for hit in detections]
    when = datetime.fromtimestamp(track.updated, timezone.utc)
    current = scene.read(frame, when)
    scene_map = scene_map or SceneMap()
    box = _norm_box(frame, track)
    surface = scene_map.surface_under(box) if box else ""
    landmark = scene_map.landmark_at(box) if box else None
    fixture = scene_map.landmark_under(box) if box else None
    lit = car_lights(frame, moved) if frame is not None and current.period != "day" else 0.0
    aircraft = sky.ask(track.updated, cfg["opensky"]["match_window_s"]) if _crossed_sky(track, cfg) else []
    width_m = scene_map.metres_across(box) if box else 0.0
    height_m = scene_map.metres_tall(box) if box else 0.0
    # Lu au pied de la boîte, comme la distance elle-même : c'est là que la
    # chose touche le sol, et c'est le sol qui porte toute la mesure.
    doubt = scene_map.doubt_at(min(0.999, box[0] + box[2] / 2), min(0.999, box[1] + box[3])) if box else 0.0
    # La même chose mesurée sur la boîte du modèle plutôt que sur la tache.
    # Notée sans être encore employée : la décision attendra qu'on ait de quoi
    # comparer les deux sur de vrais passages.
    named = _named_box(frame, detections)
    width_named_m = scene_map.metres_across(named) if named else 0.0
    height_named_m = scene_map.metres_tall(named) if named else 0.0
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
        # La durée est le temps regardé, toujours. Le verrou du feu est
        # fire_ready, pas un zéro ici : ce zéro faisait taire la nuit.
        duration_s=duration,
        fire_ready=fire_ready,
        warm_ratio=warm_ratio(track.best_jpeg, track.best_bbox) if fire_ready else 0.0,
        smoke_ratio=smoke_ratio(track.best_jpeg, track.best_bbox) if fire_ready else 0.0,
        rise=track.rise,
        foot_climb=track.foot_climb,
        drift_rate=_foot_walk(track.drift, box[2] if box else 0.0, duration),
        rise_ms=_climb(track.rise, height_m, box[3] if box else 0.0, duration),
        width_m=width_m,
        height_m=height_m,
        distance_doubt=doubt,
        area_grow=track.area_grow,
        min_travel=cfg["min_travel"],
        cross_rate=cfg["cross_rate"],
        max_sky_area=cfg["max_sky_area"],
        min_conf=cfg["min_conf"],
        fire_sustain_s=cfg["fire"]["sustain_s"],
        fire_grow=cfg["fire"]["grow_ratio"],
        fire_warm=cfg["fire"]["warm_ratio"],
        fire_smoke=float(cfg["fire"].get("smoke_ratio") or 0.35),
        fire_rise=float(cfg["fire"].get("rise") or 0.008),
        period=current.period,
        fogged=current.fogged,
        blind=current.blind,
        hazy=current.hazy,
        weather=current.weather,
        surface=surface,
        near_road=scene_map.drivable_near(box) if box else True,
        colour=body_colour(frame, _paint_box(detections, moved) or track.best_bbox) if frame is not None and current.period == "day" else "",
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
        # La clarté de la tache rapportée au fond qu'elle recouvre, et la part
        # de la tache où ce fond se voit encore. Une ombre et la flaque des
        # phares changent la première en laissant la seconde près de un ; une
        # chose qui passe cache ce qu'il y a derrière et la fait tomber. Noté et
        # pas encore jugé : le seuil se mesurera sur de vrais passages, comme
        # celui de la montée en mètres par seconde avant lui.
        "shade": round(track.shade, 3),
        "kept": round(track.texture, 3),
        "area_ratio": round(obs.area_ratio, 5),
        "duration_s": round(max(0.0, track.updated - track.started), 1),
        "frames": track.frames,
        # The surveyed footprint and what the model actually returned. Every
        # correction so far has had to be diagnosed by guessing at these after
        # the fact; written down, the next one is read straight off the entry.
        "width_m": round(width_m, 1),
        "height_m": round(obs.height_m, 1),
        # Mesurées sur la boîte du modèle et non sur la tache de mouvement.
        # Zéro quand le modèle n'a rien posé. Le 28 septembre à 10 h 43 un
        # tracteur a été publié comme voiture : la tache disait 6,7 m sur 4,5,
        # ce qui n'est pas une voiture, mais les voitures publiées mesurent
        # elles-mêmes 2,30 m de haut de médiane, donc le chiffre ne pouvait rien
        # refuser. C'est la mesure qu'il faut redresser avant la règle.
        "width_named_m": round(width_named_m, 1),
        "height_named_m": round(height_named_m, 1),
        "rise_ms": round(obs.rise_ms, 2),
        "drift_rate": round(obs.drift_rate, 3),
        "seen_as": [f"{hit.cls} {hit.conf:.2f} sur {hit.share:.0%}" for hit in detections[:4]],
    }
    # Le nom vient-il du modèle, ou d'une règle de rattrapage ? Seul le premier
    # cas prouve quelque chose de la reconnaissance, et c'est elle qu'on veut
    # sûre avant de montrer quoi que ce soit.
    decision.detail.setdefault("autonomous", named_itself(decision.type, detections))
    decision.detail.setdefault("measured", measured)
    if decision.type == "plane" and decision.detail.get("icao24"):
        # Asked now and not before: a route costs a call to OpenSky, and until
        # the rule has settled on one aircraft there is nothing to ask about.
        decision.detail.update(describe_route(sky.route(decision.detail["icao24"], track.updated)))
    # Pendant que la piste est ouverte, on ne garde que ce dont on est sûr.
    # Le reste continue d'être cherché : un refus écrit toutes les quatre
    # secondes noierait le journal et féliciterait un doute.
    sure = (decision.publish and decision.type in CLASSES_SURES
            and float(decision.confidence or 0) >= CONFIANCE_SURE)
    if tot and not sure:
        return
    def refuse(quiet: bool = False) -> None:
        """Écarter la tache, et en garder la trace quand son motif se fait rare.

        Un refus gardé devient une carte à trancher comme une autre : sa photo,
        le mot de son motif, et les cinq noms à choisir. Dire « c'était une
        voiture » sur une chose écartée est la leçon la plus précieuse qui soit,
        puisque c'est un raté, et le raté est la seule chose qui apprenne
        quelque chose qu'on ne savait pas déjà.
        """
        store.add_candidate(when, track.zone, decision.reason, decision.detail)
        if track.zone != "sky":
            _ligne_code(track, decision)
        if not quiet:
            log.info("Candidat %s %s [%s]", track.zone, decision.reason, track.code)
        if not _worth_keeping(decision.reason, cfg, last_fire, now):
            return
        detail = dict(decision.detail)
        detail["refused"] = decision.reason
        # Faite par une règle, donc jamais revendiquée comme une lecture du
        # modèle : une carte écartée n'a rien à faire dans l'historique publié.
        detail["autonomous"] = False
        if box:
            detail["box"] = [round(value, 4) for value in box]
        entry = store.add_event(when, "missed", refusal_words(decision.reason), track.zone,
                                decision.confidence, track.best_jpeg, detail)
        store.keep_closeup(entry, frame, track.best_bbox, width_m)
        store.record_seen(entry["id"], write_observation(obs), habit=decision.type == "habit")
        log.info("Refus gardé pour relecture : %s [%s]", decision.reason, track.code)

    if decision.type == "motion" and track.zone == "sky":
        refuse(quiet=True)
        return
    if not decision.publish:
        refuse()
        return
    if memory.observe(track.zone, track.centroid, decision) != "record":
        log.info("Compté sans nouvelle carte %s [%s]", decision.label, track.code)
        _ligne_code(track, decision)
        return
    if decision.type in {"motion", "habit"}:
        if _worth_reviewing(decision, cfg, last_fire, now):
            last_fire["unnamed"] = now
            if box:
                decision.detail["box"] = [round(value, 4) for value in box]
            entry = store.add_event(when, decision.type, decision.label, track.zone,
                                    decision.confidence, track.best_jpeg, decision.detail)
            store.keep_closeup(entry, frame, track.best_bbox, width_m)
            store.record_seen(entry["id"], write_observation(obs))
            log.info("Passage soumis à revue %s [%s]", track.zone, track.code)
            _ligne_code(track, decision)
            return
        refuse(quiet=True)
        return
    if decision.type == "fire":
        last_fire["fire"] = now
    if surface:
        decision.detail["surface"] = surface
    drawn = _box_of_the_named(frame, decision, detections, moved) or box
    if drawn:
        decision.detail["box"] = [round(value, 4) for value in drawn]
    trace = _trace_of(frame, track)
    if trace:
        decision.detail["trace"] = trace
    event = store.add_event(when, decision.type, decision.label, track.zone, decision.confidence, track.best_jpeg, decision.detail)
    close = store.keep_closeup(event, frame, track.best_bbox, width_m)
    # Ce que la décision a eu sous les yeux, gardé à part de l'historique. Un
    # verdict rendu dans trois jours pourra ainsi repasser par decide() au lieu
    # de se réduire à un compteur.
    store.record_seen(event["id"], write_observation(obs))
    if close and width_m >= BUS_LENGTH_M:
        log.info("Recadrage gardé pour %s : %s [%s]", decision.label, close, track.code)
    log.info("Publié %s %s [%s]", decision.type, decision.label, track.code)
    _ligne_code(track, decision)
    # Le good catch attend 0,60. Le compteur, lui, retient toute classe
    # publiée : sinon un vélo lu à 0,50 disparaît des deux journées, et
    # passé minuit en France il ne reste plus que du côté américain.
    if (score is not None and decision.type in CLASSES_SURES
            and not getattr(track, "compte", False)):
        track.compte = True
        _marque_prise(score, now, store.root / "score.json")
    if sure and score is not None:
        track.tenu = True
    if decision.type in CLIP_TYPES:
        pending.append({"id": event["id"], "after": now + 4, "started": track.started - 8})


_LOCK = None


def _ligne_code(track, decision) -> None:
    """Une ligne, le code en tête, pour retrouver la piste qu'on a lue à l'écran.

    Le code est fait pour être recopié. La suite dit ce que la règle a décidé
    et ce que le modèle avait lu, afin qu'un « K7M » reçu dans un message
    suffise à savoir si la classe a manqué, et de combien.
    """
    mesures = (decision.detail or {}).get("measured") or {}
    lu = " ".join(mesures.get("seen_as") or []) or "rien"
    issue = decision.type if decision.publish else "refus"
    log.info("Code %s %s %s | %s", track.code, issue, decision.reason, lu)


def _note_cherche(souvenir: dict, annonces: set, tracks, ended, frame, prise: float, chemin: Path,
                  score: dict | None = None, score_chemin: Path | None = None) -> None:
    """Écrit les pistes en cours, avec leur code, pour le flux.

    Le ciel n'y entre pas. Une tache dans le ciel est presque toujours un
    nuage ou un bord de capteur, et en écrire le code remplirait l'image
    sans rien qu'on puisse aller vérifier sur la route.

    Une piste n'est annoncée qu'une fois. Le fichier, lui, est réécrit à
    chaque image : le flux lit le trajet, pas un événement.
    """
    if frame is None or not getattr(frame, "size", 0):
        return
    hauteur, largeur = frame.shape[:2]
    if largeur < 1 or hauteur < 1:
        return
    for track in list(tracks) + list(ended):
        if track.zone == "sky" or track.frames < 1:
            continue
        x, y, w, h = track.bbox
        point = [round(float(prise), 2), round(x / largeur, 4), round(y / hauteur, 4),
                 round(max(w, 1) / largeur, 4), round(max(h, 1) / hauteur, 4)]
        fiche = souvenir.get(track.id)
        if fiche is None:
            fiche = {"code": track.code, "zone": track.zone, "points": []}
            souvenir[track.id] = fiche
        if track.id not in annonces:
            annonces.add(track.id)
            log.info("Mouvement %s %s", track.code, track.zone)
            if score is not None and score_chemin is not None:
                _marque_vue(score, prise, score_chemin)
        if not fiche["points"] or abs(fiche["points"][-1][0] - point[0]) > 0.01:
            fiche["points"].append(point)
    for identifiant in [i for i, fiche in souvenir.items()
                        if not fiche["points"] or prise - fiche["points"][-1][0] > CHERCHE_S]:
        del souvenir[identifiant]
    for fiche in souvenir.values():
        fiche["points"] = [p for p in fiche["points"] if prise - p[0] <= CHERCHE_S]
    payload = {"tracks": [{"code": fiche["code"], "zone": fiche["zone"], "points": fiche["points"]}
                          for fiche in souvenir.values() if fiche["points"]]}
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        temporaire = chemin.with_suffix(".json.tmp")
        temporaire.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporaire.replace(chemin)
    except OSError:
        log.warning("Pistes en cours non écrites", exc_info=True)


def _a_relire(tracks, maintenant: float) -> list:
    """Les pistes encore ouvertes à qui on redemande la classe.

    Un piéton qui reste une minute ne doit pas attendre d'être parti pour
    avoir un nom. On redemande toutes les quelques secondes, et on ne publie
    que si la lecture est assez sûre pour un point.
    """
    dus = []
    for track in tracks:
        if track.zone == "sky" or track.tenu or track.frames < 4:
            continue
        if maintenant - track.essai < RELIRE_S:
            continue
        track.essai = maintenant
        dus.append(track)
    return dus


def _charge_score(chemin: Path) -> dict:
    vide = {"paris": {}, "los_angeles": {}}
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return vide
    if not isinstance(brut, dict):
        return vide
    for camp in vide:
        jours = brut.get(camp) or {}
        if isinstance(jours, dict):
            vide[camp] = {k: {"vus": int(v.get("vus") or 0), "pris": int(v.get("pris") or 0)}
                          for k, v in jours.items() if isinstance(v, dict)}
    return vide


def _jours_de(prise: float) -> tuple[str, str]:
    """La date française et la date américaine de cet instant.

    Neuf heures les séparent. Un même passage tombe donc parfois sur deux
    jours différents, et c'est tout l'écart entre les deux camps.
    """
    moment = datetime.fromtimestamp(prise, timezone.utc)
    return (moment.astimezone(PARIS).date().isoformat(),
            moment.astimezone(LOS_ANGELES).date().isoformat())


def _cellule(score: dict, camp: str, jour: str) -> dict:
    jours = score.setdefault(camp, {})
    cellule = jours.get(jour)
    if not isinstance(cellule, dict):
        cellule = {"vus": 0, "pris": 0}
        jours[jour] = cellule
    return cellule


def _ecrit_score(chemin: Path, score: dict) -> None:
    # Trois jours suffisent : le tableau montre aujourd'hui, et la veille
    # reste lisible si on veut comprendre un écart de minuit.
    garde = {}
    for camp in ("paris", "los_angeles"):
        jours = score.get(camp) or {}
        cles = sorted(jours)[-3:]
        garde[camp] = {cle: jours[cle] for cle in cles}
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        temporaire = chemin.with_suffix(".json.tmp")
        temporaire.write_text(json.dumps(garde, ensure_ascii=False), encoding="utf-8")
        temporaire.replace(chemin)
    except OSError:
        log.warning("Le tableau du jour n'a pas été écrit", exc_info=True)


def _marque_vue(score: dict, prise: float, chemin: Path) -> None:
    """Un mouvement compte pour les deux journées en cours."""
    france, amerique = _jours_de(prise)
    _cellule(score, "paris", france)["vus"] += 1
    _cellule(score, "los_angeles", amerique)["vus"] += 1
    _ecrit_score(chemin, score)


def _aligne_prises(score: dict, events: list, chemin: Path) -> None:
    """Le numérateur reprend les classes déjà publiées.

    Le fichier du jour ne gardait que les good catch, au-dessus de 0,60.
    Une classe publiée en dessous existait dans l'historique et manquait
    au tableau. On réécrit le numérateur depuis l'historique, sans toucher
    aux mouvements déjà comptés.
    """
    comptes: dict[str, dict[str, int]] = {"paris": {}, "los_angeles": {}}
    for event in events:
        if not isinstance(event, dict) or event.get("type") not in CLASSES_SURES:
            continue
        try:
            instant = datetime.strptime(event["t"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc).timestamp()
        except (KeyError, TypeError, ValueError):
            continue
        france, amerique = _jours_de(instant)
        comptes["paris"][france] = comptes["paris"].get(france, 0) + 1
        comptes["los_angeles"][amerique] = comptes["los_angeles"].get(amerique, 0) + 1
    for camp in ("paris", "los_angeles"):
        jours = score.setdefault(camp, {})
        for jour in list(jours):
            cellule = jours.get(jour)
            if not isinstance(cellule, dict):
                continue
            # Une journée sans mouvement n'est pas affichée. En créer une
            # seulement pour y poser d'anciennes classes donnait un 538/0
            # qui n'a jamais été compté par le tableau.
            if int(cellule.get("vus") or 0) <= 0:
                del jours[jour]
                continue
            cellule["pris"] = comptes[camp].get(jour, 0)
    _ecrit_score(chemin, score)


def _marque_prise(score: dict, prise: float, chemin: Path) -> None:
    """Une classe publiée profite aux deux camps, chacun sur sa journée en cours."""
    france, amerique = _jours_de(prise)
    _cellule(score, "paris", france)["pris"] += 1
    _cellule(score, "los_angeles", amerique)["pris"] += 1
    _ecrit_score(chemin, score)


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
    "cycle": {"motorcycle", "bicycle"},
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


def _pieds_sur_la_tache(box, moved) -> bool:
    """Les roues de la chose lue sont-elles encore sur la tache, même sans recouvrement ?

    Le modèle cadre serré, la tache traîne derrière : leurs rectangles peuvent
    ne plus se toucher alors que c'est la même voiture, une longueur plus loin.
    Une voiture à l'arrêt au bord, elle, a les roues ailleurs.
    """
    ax, ay, aw, ah = box
    bx, by, bw, bh = moved
    dx = abs((ax + aw / 2) - (bx + bw / 2))
    dy = abs((ay + ah) - (by + bh))
    portee = 1.5 * max(aw, bw)
    return dx <= portee and dy <= portee


# Ce que la veille écarte est plus nombreux que ce qu'elle publie, d'un facteur
# cent : 49 775 refus pour 418 publications. Et un refus ne laisse aujourd'hui
# ni photo ni observation, donc aucun moyen de savoir s'il avait raison. Tout ce
# qu'on rate est perdu, ce qui est le contraire de ce qu'on veut.
#
# Tout garder est hors de portée : sept mille taches par jour, une vignette
# chacune, feraient cent cinquante mégaoctets par jour. Mais le renseignement
# est dans la variété des motifs, pas dans leur nombre — six mille « rien de
# reconnu » disent ce que dit le premier. Un échantillon par motif garde donc
# presque tout ce qu'il y a à apprendre, en gardant presque rien.
SAMPLE_REFUSED_S = 3600


def _worth_keeping(reason: str, cfg: dict, seen: dict, now: float) -> bool:
    """Ce refus-là mérite-t-il d'être montré, son motif n'ayant rien donné depuis un moment ?

    Par motif et non en bloc, sinon les motifs qui reviennent toutes les
    secondes mangeraient la place des rares, et ce sont justement les rares qui
    ont des chances d'être des fautes.

    Sauf ceux dont le motif est qu'il n'y avait rien : on ne demande pas à un
    humain de trancher une absence.
    """
    if reason in RIEN_A_JUGER:
        return False
    gap = float(cfg.get("sample_refused_s", SAMPLE_REFUSED_S) or 0)
    if not gap:
        return False
    key = f"refused:{reason}"
    if now - seen.get(key, 0.0) < gap:
        return False
    seen[key] = now
    return True


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


def _paint_box(detections, moved=None):
    """La carrosserie lue, pas la tache : c'est là qu'est la peinture.

    Le 4 octobre peu avant 18 h, une voiture blanche a été publiée « Voiture »
    sans couleur : on lisait le milieu de la tache, donc surtout le bitume.
    """
    hits = [hit for hit in detections if hit.box]
    if not hits:
        return None
    if moved:
        recouvre = [hit for hit in hits if _overlap(hit.box, moved) >= BOX_OVERLAP]
        hits = recouvre or hits
    return max(hits, key=lambda hit: hit.conf).box


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
        recouvre = [hit for hit in hits if _overlap(hit.box, moved) >= BOX_OVERLAP]
        hits = recouvre or [hit for hit in hits if _pieds_sur_la_tache(hit.box, moved)]
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


def _trace_of(frame, track) -> list[list[float]]:
    """Le chemin suivi, en heures absolues et en parts d'image.

    Une seule boîte suffisait tant que le flux la posait un instant. Tenue
    quatre secondes, elle reste en arrière : le sujet avance, le rectangle non,
    et au bout de la quatrième seconde il désigne un bout de route vide.

    En heures absolues, pas en écart au début : le flux diffuse avec une
    quinzaine de secondes de retard et pose chaque rectangle sur l'image qui
    porte la bonne heure. Lui donner des heures entières lui évite d'avoir à
    deviner à quoi l'écart se rapporte, et laisse la question du calage là où
    elle est déjà résolue.

    Arrondi à quatre décimales : un millième de la largeur fait deux pixels, et
    personne ne voit un rectangle bouger de deux pixels.
    """
    suite = getattr(track, "trace", None)
    if frame is None or not suite or len(suite) < 2:
        return []
    hauteur, largeur = frame.shape[:2]
    chemin = []
    for quand, (x, y, w, h) in suite:
        if not any((x, y, w, h)):
            continue
        chemin.append([round(quand, 2), round(x / largeur, 4), round(y / hauteur, 4),
                       round(max(w, 1) / largeur, 4), round(max(h, 1) / hauteur, 4)])
    return chemin if len(chemin) >= 2 else []


def _norm_box(frame, track) -> tuple[float, float, float, float] | None:
    bbox = track.best_bbox if any(track.best_bbox) else track.bbox
    if frame is None or not any(bbox):
        return None
    height, width = frame.shape[:2]
    x, y, w, h = bbox
    return x / width, y / height, max(w, 1) / width, max(h, 1) / height


def _named_box(frame, detections) -> tuple[float, float, float, float] | None:
    """Où le modèle a posé la chose, plutôt que tout ce qui a bougé.

    La tache de mouvement est ce qui a changé : elle contient la chose, son
    ombre, l'éclat de son pare-brise et ce qui passait à côté. Mesurée dessus,
    une voiture fait 2,30 m de haut de médiane quand une vraie en fait 1,50, et
    un piéton 2,10 quand il en fait 1,70. La boîte du modèle, elle, colle à la
    chose.

    C'est la même cause que le rectangle parti sur la flaque des phares le 29
    septembre : la tache n'est pas la forme de ce qui a bougé.

    De nuit, le modèle ne nomme rien et cette boîte n'existe pas — et on ne
    peut pas la remplacer en retaillant la tache sur la lumière. C'est mesuré,
    sur la voiture du 2 octobre à 00:50 que la veille a vue et refusée : sa
    tache valait 21,4 m de large, et le noyau de l'éclat 17,6 m à mi-hauteur,
    11,9 m au plus serré. Une voiture en fait moins de deux. Le pic est à 255
    et le centile 99 à 247 : le faisceau sature autant que les phares, donc
    aucun seuil de clarté ne sépare la source de sa portée. Le faisceau fait
    réellement une dizaine de mètres sur la route, et c'est lui qu'on mesure.

    Ce qu'il faut en conclure n'est pas qu'il reste à mieux mesurer : c'est que
    de nuit, à cette distance, le véhicule n'est pas résolu. Seule sa lumière
    l'est. Largeur au sol, hauteur et pied sur la chaussée ne veulent alors
    rien dire, et une décision nocturne ne peut s'appuyer que sur ce qui se
    mesure encore — le trajet le long de la route, l'allure, et la signature
    des feux.
    """
    best = max((hit for hit in detections if hit.box), key=lambda hit: hit.conf, default=None)
    if frame is None or best is None:
        return None
    height, width = frame.shape[:2]
    x, y, w, h = best.box
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


# De combien de segments on recule pour ouvrir le flux.
#
# Trois, qui est ce que ffmpeg prend de lui-même quand on ne lui dit rien :
# c'est donc exactement là où la veille lisait déjà, et on ne change pas sa
# réactivité en passant par ici. On l'écrit seulement, au lieu de le subir,
# parce qu'il faut le savoir pour dater les images.
RECUL_VEILLE = 3


def _mont_serein_vif(cfg: dict) -> bool:
    """La playlist du Mont Serein a encore des segments neufs."""
    from watcher.stream import playlist_figee

    try:
        return not playlist_figee(direct._lire(direct.playlist_media(cfg["stream_url"])),
                                  time.time())
    except Exception:
        return False


def _choisir_la_webcam(cfg: dict) -> tuple[str, bool]:
    """L'adresse à ouvrir, et si c'est l'autre webcam de la collection.

    Le booléen dit que l'heure des images est celle de la machine : cette
    playlist ne date pas ses segments, et le flux non plus.
    """
    if _mont_serein_vif(cfg):
        return cfg["stream_url"], False
    from watcher.stream import _camera_secours, adresse_youtube

    cam = _camera_secours(cfg)
    if not cam:
        return cfg["stream_url"], False
    try:
        if cam.get("youtube"):
            return adresse_youtube(str(cam["youtube"])), True
        if cam.get("url"):
            return str(cam["url"]), True
    except Exception:
        log.warning("Secours illisible pour la veille", exc_info=True)
    return cfg["stream_url"], False


def _zones_secours(cfg: dict) -> dict | None:
    from watcher.stream import _camera_secours

    cam = _camera_secours(cfg) or {}
    zones = cam.get("zones")
    if isinstance(zones, dict) and zones.get("polygons") and zones.get("priority"):
        return zones
    return None


def _repart_le_fond(motion, zones: dict) -> None:
    """Le fond appris sur une webcam ne vaut rien sur l'autre."""
    motion.zones = zones
    motion.bg = cv2.createBackgroundSubtractorMOG2(history=120, varThreshold=24, detectShadows=False)
    motion.tracks.clear()
    motion._seen = 0


def _frames(url: str, horloge: bool = False):
    """Les images, et l'heure à laquelle la montagne les a vues.

    Pas l'heure qu'il est ici. Entre les deux il y a vingt et une secondes
    mesurées — le temps que le flux nous parvienne — et c'est ce décalage qui
    posait les rectangles sur la route vide : la veille datait à sa montre, la
    diffusion dessinait à l'heure de la montagne, et les deux croyaient parler
    de la même seconde.

    Le filtre « fps=1 » rend une image par seconde de film et non par seconde
    d'horloge : il double quand le réseau bégaie, il saute quand il rattrape.
    Compter les images, c'est donc compter les secondes de là-bas, et il suffit
    de savoir à quelle heure commence la première.
    """
    if horloge:
        # Pas de date dans cette playlist : l'heure est celle de la réception,
        # la même que l'horloge du flux quand il montre cette webcam.
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-user_agent", "Mozilla/5.0",
            "-rw_timeout", "15000000",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            # Plus près du bord que l'antenne : la minute de marge du flux
            # est le temps qu'on a pour nommer avant que l'image ne passe.
            "-live_start_index", str(-RECUL_VEILLE),
            "-i", url, "-an", "-vf", "fps=1",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-",
        ]
    else:
        depart, _ = direct.depart(direct.playlist_media(url), RECUL_VEILLE)
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            "-live_start_index", str(-RECUL_VEILLE),
            "-i", url, "-an", "-vf", "fps=1",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-",
        ]
    vues = 0
    retard_horloge = 0.0
    if horloge:
        from watcher.stream import duree_de_segment
        retard_horloge = RECUL_VEILLE * duree_de_segment(url)
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
                    yield frame, (time.time() - retard_horloge if horloge else depart + vues)
                    vues += 1
    finally:
        process.kill()


if __name__ == "__main__":
    main()
