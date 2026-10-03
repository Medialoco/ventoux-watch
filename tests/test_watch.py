import inspect
import itertools
import json
import math
import os
import re
import io
import subprocess
import sys
import tempfile
import wave
import random
import threading
import time
import unittest
from unittest import mock

import scripts.musique_dogmazic as musique_dogmazic
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np

from watcher.geometry import assign_zone
from watcher.gtfs import GtfsIndex, load_feed
from watcher.main import (STREAM_RETRY_MAX_S, STREAM_RETRY_S, _box_of_the_named, _crossed_sky,
                          _might_be_bus, _next_wait, _note_interruption, _published, _utc)
from watcher.naming import Decision
from watcher.motion import MotionDetector, Track
from watcher.naming import (RIEN_A_JUGER, SIZE_DOUBT_MAX, Detection, Observation, Trip, choose_aircraft,
                            decide, in_camera_view)
from watcher.review import apply_review, parse_review
from watcher.opensky import SkyArchive
from watcher.scene import Scene, ViewLog, moon_spot, read_sky, solar_period, weather_label
from watcher.store import Store, fold_events, small_jpeg
from watcher import stream

ROOT = Path(__file__).resolve().parents[1]
ZONES = json.loads((ROOT / "config" / "zones.json").read_text())


def _road_run(far_m: float = 110.0, near_m: float = 40.0, steps: int = 9):
    """Points of the picture where the road lies, walked towards the camera.

    Read off the scene map rather than picked by eye, so the same test would
    run on any camera whose surroundings are mapped: it asks where the road is
    at a hundred and forty metres, then at a hundred and thirty, and so on.
    """
    from watcher.scenemap import DRIVABLE, SceneMap

    scene = SceneMap.load(ROOT / "config" / "scene.json")
    cells = []
    for row in range(scene.height):
        for col in range(scene.width):
            x, y = (col + 0.5) / scene.width, (row + 0.5) / scene.height
            if scene.surface_at(x, y) in DRIVABLE:
                cells.append((scene.distance_at(x, y), x, y))
    run, last = [], None
    for index in range(steps):
        want = far_m + (near_m - far_m) * index / (steps - 1)
        near = [cell for cell in cells if abs(cell[0] - want) <= want * 0.06] or cells
        if last is None:
            # Start on the widest part of the road at that distance rather than
            # at an edge of the picture.
            spot = min(near, key=lambda cell: abs(cell[0] - want))[1:]
        else:
            # A car does not jump across the picture: of the road at the next
            # distance, take the piece nearest where it just was.
            spot = min(near, key=lambda cell: (cell[1] - last[0]) ** 2 + (cell[2] - last[1]) ** 2)[1:]
        run.append(spot)
        last = spot
    return scene, run


def _approach(scene, run):
    """Frames of a car coming at the camera at night, and where it really is."""
    from watcher.simulate import CAR_TALL_M, CAR_WIDE_M, car, sensor_noise

    frames, boxes = [], []
    for index, spot in enumerate(run):
        # Tarmac at night, with the grain of the sensor so the subtractor has
        # something to settle on.
        base = sensor_noise(np.full((1080, 1920, 3), 38, dtype=np.uint8), seed=index)
        scale = scene.share_per_metre(*spot)
        # The beams point at the camera, so the lit tarmac lies between the
        # bumper and us: nearer, lower in the picture and wider than the car.
        # That is the shape which stole the rectangle on 29 September.
        pool = run[min(len(run) - 1, index + 3)]
        frames.append(car(base, spot, scale, lights=True, pool_to=pool))
        across, up = scale
        boxes.append((spot[0] - CAR_WIDE_M * across / 2, spot[1] - CAR_TALL_M * up,
                      CAR_WIDE_M * across, CAR_TALL_M * up))
    return frames, boxes


def _empty_road(count: int):
    from watcher.simulate import sensor_noise

    return [sensor_noise(np.full((1080, 1920, 3), 38, dtype=np.uint8), seed=90 + index)
            for index in range(count)]


def _share_of(box, other) -> float:
    """What share of other the box holds."""
    ax, ay, aw, ah = box
    bx, by, bw, bh = other
    wide = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    tall = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return (wide * tall) / max(1e-9, bw * bh)


def _ahead(lat: float, lon: float, bearing: float, meters: float) -> tuple[float, float]:
    radius = 6_371_000
    br = math.radians(bearing)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(meters / radius) + math.cos(lat1) * math.sin(meters / radius) * math.cos(br))
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(meters / radius) * math.cos(lat1),
        math.cos(meters / radius) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


class NamingTests(unittest.TestCase):
    def test_unique_aircraft_is_named(self):
        chosen, reason = choose_aircraft([{"icao24": "abc123", "callsign": "AFR123", "altitude_m": 8500}])
        self.assertEqual(reason, "unique")
        self.assertEqual(chosen["callsign"], "AFR123")

    def test_three_aircraft_stay_unnamed(self):
        aircraft = [
            {"icao24": "a", "callsign": "A", "altitude_m": 9000},
            {"icao24": "b", "callsign": "B", "altitude_m": 10000},
            {"icao24": "c", "callsign": "C", "altitude_m": 11000},
        ]
        chosen, reason = choose_aircraft(aircraft)
        self.assertIsNone(chosen)
        self.assertEqual(reason, "ambiguous")

    def test_much_lower_aircraft_is_named(self):
        aircraft = [
            {"icao24": "high", "callsign": "HIGH", "altitude_m": 10000},
            {"icao24": "low", "callsign": "LOW1", "altitude_m": 3000},
        ]
        chosen, reason = choose_aircraft(aircraft)
        self.assertEqual(reason, "much_lower")
        self.assertEqual(chosen["callsign"], "LOW1")

    def test_sky_motion_without_a_single_plane_is_kept(self):
        decision = decide(Observation(zone="sky", travel=0.05, area_ratio=0.001, aircraft=[], period="night"))
        self.assertTrue(decision.publish)
        self.assertEqual(decision.type, "motion")
        self.assertEqual(decision.reason, "none")
        self.assertEqual(decision.detail["period"], "night")

    def test_cloud_is_not_called_a_plane(self):
        decision = decide(Observation(zone="sky", travel=0.2, area_ratio=0.2, aircraft=[{"icao24": "a", "callsign": "X", "altitude_m": 1000}]))
        self.assertEqual(decision.type, "motion")
        self.assertEqual(decision.label, "Masse dans le ciel")

    def test_a_person_on_the_road_is_a_pedestrian(self):
        decision = decide(Observation(zone="road", travel=0.0, detections=[Detection("person", 0.62)]))
        self.assertEqual(decision.type, "person")
        self.assertEqual(decision.label, "Piéton")

    def test_static_blob_is_not_a_car(self):
        # La durée n'était pas écrite ici, et le test passait quand même : un
        # déplacement nul sur un temps nul suffisait à prouver l'immobilité.
        # Il faut désormais que la tache ait eu le temps de bouger et ne l'ait
        # pas fait, ce qui est justement ce que ce test voulait dire.
        decision = decide(Observation(zone="roundabout", travel=0.0, duration_s=8.0,
                                      detections=[Detection("car", 0.9)]))
        self.assertEqual(decision.type, "motion")
        self.assertEqual(decision.reason, "static")
        self.assertNotEqual(decision.label, "Voiture")

    def test_a_track_too_short_to_have_moved_is_not_called_still(self):
        """Le 29 septembre, treize refus « presque immobile » sur dix-sept.

        Tous portaient sur des pistes sans durée mesurable. Un déplacement est
        une vitesse multipliée par un temps : sans temps, il n'y a rien à
        mesurer, et « ça n'a pas bougé » devient une affirmation sur le monde
        tirée d'une absence de mesure. Parmi les taches écartées ainsi, un
        camion lu à 0,65 couvrant 92 % de sa boîte sur le rond-point.
        """
        bref = dict(zone="roundabout", travel=0.0, duration_s=0.0, min_travel=0.01)

        # Rien de reconnu : on refuse toujours, mais en disant pourquoi.
        muet = decide(Observation(**bref))
        self.assertEqual(muet.type, "motion")
        self.assertEqual(muet.reason, "too_brief")

        # Reconnu franchement : le déplacement non mesuré ne peut plus servir
        # d'alibi, et le nom a la parole.
        nomme = decide(Observation(**bref, detections=[Detection("car", 0.9)]))
        self.assertEqual(nomme.action, "publish")
        self.assertEqual(nomme.type, "vehicle")

        # Et la garde ne s'ouvre que le temps de la non-mesure : dès que la
        # piste a duré assez pour qu'un passage ordinaire ait franchi la barre,
        # un déplacement nul redevient une preuve d'immobilité.
        pose = decide(Observation(zone="roundabout", travel=0.0, duration_s=0.9, min_travel=0.01,
                                  detections=[Detection("truck", 0.65)]))
        self.assertEqual(pose.reason, "static")

    def test_dusk_glow_is_not_a_fire(self):
        decision = decide(Observation(zone="slope", duration_s=25, area_grow=2.0, warm_ratio=0.2, period="twilight"))
        self.assertEqual(decision.type, "motion")
        self.assertEqual(decision.label, "Lueur du soir")

    def test_sky_motion_publishes_the_callsign(self):
        lat, lon = _ahead(44.183501, 5.2621281, 140, 2000)
        decision = decide(
            Observation(
                zone="sky",
                travel=0.05,
                area_ratio=0.001,
                aircraft=[{"icao24": "394c12", "callsign": "AFR472", "altitude_m": 1800, "lat": lat, "lon": lon}],
            )
        )
        self.assertTrue(decision.publish)
        self.assertEqual(decision.type, "plane")
        self.assertEqual(decision.label, "Air France 472")
        self.assertTrue(decision.detail["seen"])
        self.assertEqual(decision.detail["callsign"], "AFR472")
        self.assertAlmostEqual(decision.detail["distance_km"], 2.0, places=1)

    def test_the_aircraft_where_the_motion_is_gets_the_name(self):
        west = _ahead(44.183501, 5.2621281, 100, 12000)
        east = _ahead(44.183501, 5.2621281, 150, 12000)
        sky = [
            {"icao24": "aa0001", "callsign": "AFR100", "altitude_m": 3500, "lat": west[0], "lon": west[1]},
            {"icao24": "bb0002", "callsign": "BAW200", "altitude_m": 3500, "lat": east[0], "lon": east[1]},
        ]
        left = decide(Observation(zone="sky", travel=0.05, area_ratio=0.00012, aircraft=sky, at_x=0.080, at_y=0.310))
        right = decide(Observation(zone="sky", travel=0.05, area_ratio=0.00012, aircraft=sky, at_x=0.590, at_y=0.310))
        self.assertEqual(left.label, "Air France 100")
        self.assertEqual(right.label, "British Airways 200")
        self.assertEqual(left.reason, "in_frame")

    def test_nothing_is_named_when_no_aircraft_is_at_that_spot(self):
        lat, lon = _ahead(44.183501, 5.2621281, 100, 12000)
        decision = decide(
            Observation(
                zone="sky",
                travel=0.05,
                area_ratio=0.00012,
                aircraft=[{"icao24": "aa0001", "callsign": "AFR100", "altitude_m": 3500, "lat": lat, "lon": lon}],
                at_x=0.60,
                at_y=0.31,
            )
        )
        self.assertEqual(decision.type, "motion")
        self.assertEqual(decision.reason, "none_at_that_spot")
        self.assertNotIn("AFR", decision.label)

    def test_two_aircraft_at_the_same_spot_name_neither(self):
        """The real failure of 26 September, kept as a test.

        A contrail at eleven thousand metres was signed by an aircraft flying at
        four, because the old rule picked the lowest in the sector. Two jets
        side by side in the frame must produce no name at all.
        """
        one = _ahead(44.183501, 5.2621281, 128, 12000)
        two = _ahead(44.183501, 5.2621281, 131, 12000)
        low = _ahead(44.183501, 5.2621281, 150, 12000)
        decision = decide(
            Observation(
                zone="sky",
                travel=0.05,
                area_ratio=0.00012,
                aircraft=[
                    {"icao24": "aa0001", "callsign": "DLH100", "altitude_m": 3500, "lat": one[0], "lon": one[1]},
                    {"icao24": "bb0002", "callsign": "VLG200", "altitude_m": 3500, "lat": two[0], "lon": two[1]},
                    {"icao24": "cc0003", "callsign": "AAL300", "altitude_m": 3400, "lat": low[0], "lon": low[1]},
                ],
                at_x=0.408,
                at_y=0.310,
            )
        )
        self.assertEqual(decision.type, "motion")
        self.assertEqual(decision.reason, "several_at_that_spot")
        self.assertNotIn("AAL", decision.label)

    def test_a_cloud_is_too_big_to_be_the_jet_behind_it(self):
        """Eight airlines signed a day of weather because nobody checked size.

        At a hundred kilometres an airliner covers half a pixel of this frame.
        Any patch large enough for the motion detector to see is, by that fact
        alone, not the aircraft.
        """
        lat, lon = _ahead(44.183501, 5.2621281, 140, 90000)
        decision = decide(
            Observation(
                zone="sky",
                travel=0.05,
                area_ratio=0.00074,
                aircraft=[{"icao24": "aa0001", "callsign": "TUI42V", "altitude_m": 11000, "lat": lat, "lon": lon}],
                at_x=0.5,
                at_y=0.3,
            )
        )
        self.assertEqual(decision.type, "motion")
        self.assertNotIn("TUI", decision.label)

    def test_a_patch_on_the_tree_line_is_not_in_the_sky(self):
        lat, lon = _ahead(44.183501, 5.2621281, 140, 12000)
        decision = decide(
            Observation(
                zone="sky",
                travel=0.05,
                area_ratio=0.00012,
                surface="forest",
                aircraft=[{"icao24": "aa0001", "callsign": "AFR100", "altitude_m": 3500, "lat": lat, "lon": lon}],
                at_x=0.5,
                at_y=0.31,
            )
        )
        self.assertEqual(decision.reason, "against_the_ground")

    def test_an_unknown_operator_keeps_its_callsign(self):
        lat, lon = _ahead(44.183501, 5.2621281, 140, 2000)
        decision = decide(
            Observation(
                zone="sky",
                travel=0.05,
                area_ratio=0.001,
                aircraft=[{"icao24": "4d20c0", "callsign": "WMT4407", "altitude_m": 1800, "lat": lat, "lon": lon}],
            )
        )
        self.assertEqual(decision.label, "WMT4407")
        self.assertEqual(decision.detail["operator"], "")

    def test_a_high_aircraft_outside_the_picture_is_not_named(self):
        decision = decide(
            Observation(
                zone="sky",
                travel=0.05,
                area_ratio=0.001,
                aircraft=[{"icao24": "47a039", "callsign": "NSZ5525", "altitude_m": 10836, "lat": 44.25, "lon": 5.45}],
            )
        )
        self.assertEqual(decision.type, "motion")
        self.assertNotEqual(decision.label, "NSZ5525")

    def test_a_rider_is_named_by_the_machine_not_the_person(self):
        """Thirteen entries of one afternoon were filed as walkers.

        The model sees a person and a bicycle on the same rider, and the list of
        classes it was allowed to report held only the person.
        """
        for kind, word in (("bicycle", "Vélo"), ("motorcycle", "Moto")):
            decision = decide(
                Observation(
                    zone="roundabout",
                    travel=0.08,
                    width_m=1.8,
                    height_m=1.6,
                    detections=[Detection("person", 0.55), Detection(kind, 0.6)],
                )
            )
            self.assertEqual(decision.type, "cycle")
            self.assertEqual(decision.label, word)

    def test_a_dog_beside_the_road_is_named(self):
        decision = decide(
            Observation(zone="road", travel=0.05, width_m=0.9, height_m=0.7, detections=[Detection("dog", 0.6)])
        )
        self.assertEqual(decision.type, "animal")
        self.assertEqual(decision.label, "Chien")

    def test_a_walker_alone_is_still_a_walker(self):
        decision = decide(
            Observation(zone="road", travel=0.05, width_m=0.7, height_m=1.7, detections=[Detection("person", 0.7)])
        )
        self.assertEqual(decision.type, "person")
        self.assertEqual(decision.label, "Piéton")

    def test_the_rising_sun_in_the_trees_is_not_a_fire(self):
        """26 September, 08:07. Warm, wide, growing, and no smoke at all.

        The hour said daylight because the sun had cleared six degrees six
        minutes earlier, so the twilight guard let it through. Only the sun's
        own bearing settles it: ninety-seven degrees, and the patch at
        ninety-five.
        """
        glare = dict(
            zone="slope", surface="forest", duration_s=6.9, warm_ratio=0.846, smoke_ratio=0.005,
            rise=0.0, area_grow=29.21, width_m=60.9, period="day", travel=0.1038,
            area_ratio=0.01597, at_x=0.125, at_y=0.535, camera_bearing=126.713, camera_fov=78.755,
            fire_sustain_s=5.0, fire_grow=1.6, fire_warm=0.35, fire_smoke=0.35, fire_rise=0.008,
        )
        sun = decide(Observation(sun_bearing=97.0, sun_elevation=6.0, **glare))
        self.assertEqual(sun.type, "motion")
        self.assertEqual(sun.reason, "low_sun")
        # The same patch with the sun high and on the other side is a fire, and
        # must stay one: this guard may not become a way of never alerting.
        fire = decide(Observation(sun_bearing=250.0, sun_elevation=40.0, **glare))
        self.assertEqual(fire.type, "fire")

    def test_a_car_shaped_patch_is_not_a_walker(self):
        """26 September, all afternoon. The model reads a car on this
        roundabout at about a quarter confidence and the people beside it at
        half, so every car came out as a pedestrian. Four metres by one and a
        half is not somebody on foot, whatever the model is surest of.
        """
        ground = dict(zone="roundabout", travel=0.08, width_m=4.3, height_m=1.4)
        car = decide(Observation(detections=[Detection("person", 0.48), Detection("car", 0.26)], **ground))
        self.assertEqual(car.type, "vehicle")
        self.assertEqual(car.reason, "shape")
        # With no vehicle class at all it must refuse rather than invent one.
        bare = decide(Observation(detections=[Detection("person", 0.48)], **ground))
        self.assertEqual(bare.type, "motion")
        self.assertNotEqual(bare.label, "Piéton")
        # And a walker-shaped patch is still a walker.
        walk = decide(Observation(zone="roundabout", travel=0.08, width_m=0.7, height_m=1.7,
                                  detections=[Detection("person", 0.48)]))
        self.assertEqual(walk.label, "Piéton")

    def test_car_on_the_road_is_published(self):
        decision = decide(Observation(zone="road", travel=0.08, detections=[Detection("car", 0.8)]))
        self.assertEqual(decision.type, "vehicle")
        self.assertEqual(decision.label, "Voiture")

    def test_bus_with_one_trip_uses_the_line(self):
        trip = Trip("Navette", "Mont Serein", "Chalet", "10:00:00", "transcove")
        decision = decide(Observation(zone="roundabout", travel=0.05, detections=[Detection("bus", 0.7)], trips=[trip]))
        self.assertEqual(decision.label, "Bus Navette")
        self.assertEqual(decision.detail["scheduled"], "10:00:00")

    def test_a_car_beside_a_person_is_named_as_both(self):
        decision = decide(
            Observation(zone="road", travel=0.08, detections=[Detection("car", 0.7), Detection("person", 0.6)])
        )
        self.assertEqual(decision.label, "Voiture et piéton")
        self.assertEqual(decision.type, "vehicle")

    def test_bus_with_two_trips_is_not_given_a_line(self):
        trips = [
            Trip("A", "Un", "Stop", "10:00:00", "zou"),
            Trip("B", "Deux", "Stop", "10:05:00", "zou"),
        ]
        decision = decide(Observation(zone="road", travel=0.05, detections=[Detection("bus", 0.8)], trips=trips))
        self.assertNotEqual(decision.type, "bus")
        self.assertNotEqual(decision.label, "Bus")

    def test_a_lit_landmark_is_not_a_walker(self):
        decision = decide(
            Observation(zone="other", travel=0.0, landmark="statue", detections=[Detection("person", 0.6)])
        )
        self.assertEqual(decision.type, "motion")
        self.assertNotEqual(decision.label, "Piéton")

    def test_a_car_cannot_drive_through_the_forest(self):
        decision = decide(
            Observation(zone="other", travel=0.08, surface="forest", near_road=False,
                        detections=[Detection("car", 0.8)])
        )
        self.assertEqual(decision.type, "motion")

    def test_a_car_on_the_verge_is_still_a_car(self):
        decision = decide(
            Observation(zone="road", travel=0.08, surface="meadow", near_road=True,
                        detections=[Detection("car", 0.8)])
        )
        self.assertEqual(decision.type, "vehicle")

    def test_car_lights_name_a_vehicle_at_night(self):
        decision = decide(
            Observation(zone="road", travel=0.05, period="night", lit_ratio=0.06, surface="road",
                        frames=9, duration_s=5.0, detections=[Detection("person", 0.45)])
        )
        self.assertEqual(decision.type, "vehicle")
        self.assertEqual(decision.reason, "car_lights")

    def test_a_beam_sweeping_the_grass_is_not_a_vehicle(self):
        """The measurements of a real evening, and there were sixteen of them.

        Nothing detected, car-sized on the ground, bright, and gone in a fifth
        of a second: a headlight crossing the strip in front of the chalet.
        """
        beam = Observation(zone="other", surface="road", period="night", lit_ratio=0.06,
                           travel=0.1162, duration_s=0.2, frames=2, width_m=3.3, height_m=0.8)
        self.assertEqual(decide(beam).type, "motion")
        self.assertEqual(decide(replace(beam, frames=9, duration_s=5.0, travel=0.2)).type, "motion")
        steady = replace(beam, frames=9, duration_s=5.0, travel=0.2,
                         detections=[Detection("car", 0.30)])
        self.assertEqual(decide(steady).type, "vehicle")

    def test_lights_off_the_road_stay_unnamed(self):
        decision = decide(
            Observation(zone="other", travel=0.05, period="night", lit_ratio=0.06, surface="meadow")
        )
        self.assertEqual(decision.type, "motion")

    def test_a_faint_walker_on_the_night_road_is_a_car(self):
        decision = decide(
            Observation(
                zone="roundabout",
                travel=0.05,
                period="twilight",
                surface="roundabout",
                frames=9,
                duration_s=5.0,
                detections=[Detection("person", 0.42)],
                box_w=0.08,
            )
        )
        self.assertEqual(decision.type, "vehicle")

    def test_a_clear_walker_at_night_is_still_a_walker(self):
        decision = decide(
            Observation(
                zone="roundabout",
                travel=0.05,
                period="night",
                surface="roundabout",
                detections=[Detection("person", 0.72)],
            )
        )
        self.assertEqual(decision.type, "person")

    def test_a_named_bus_survives_the_night_rule(self):
        decision = decide(
            Observation(
                zone="road",
                travel=0.05,
                period="night",
                surface="road",
                lit_ratio=0.1,
                detections=[Detection("bus", 0.7)],
                trips=[Trip("5", "Sault", "Mont Serein", "20:10", "gtfs")],
            )
        )
        self.assertEqual(decision.type, "bus")

    def test_a_lorry_needs_the_width_of_a_lorry(self):
        narrow = decide(Observation(zone="road", travel=0.08, surface="road", width_m=2.6,
                                    detections=[Detection("truck", 0.8)]))
        wide = decide(Observation(zone="road", travel=0.08, surface="road", width_m=7.0,
                                  detections=[Detection("truck", 0.8)]))
        self.assertEqual(narrow.label, "Voiture")
        self.assertEqual(wide.label, "Camion")

    def test_the_colour_agrees_with_the_word(self):
        car = decide(Observation(zone="road", travel=0.08, surface="road", width_m=2.5, colour="blanc",
                                 detections=[Detection("car", 0.8)]))
        lorry = decide(Observation(zone="road", travel=0.08, surface="road", width_m=7.0, colour="blanc",
                                   detections=[Detection("truck", 0.8)]))
        self.assertEqual(car.label, "Voiture blanche")
        self.assertEqual(lorry.label, "Camion blanc")

    def test_a_still_car_on_a_car_park_is_parked(self):
        decision = decide(Observation(zone="other", travel=0.0, surface="parking",
                                      detections=[Detection("car", 0.8)]))
        self.assertEqual(decision.type, "motion")
        self.assertEqual(decision.reason, "parked")

    def test_a_walker_the_size_of_a_bus_is_not_a_walker(self):
        decision = decide(
            Observation(zone="roundabout", travel=0.05, surface="roundabout", width_m=15.8,
                        detections=[Detection("person", 0.7)])
        )
        self.assertEqual(decision.type, "motion")

    def test_a_blob_wider_than_a_lorry_is_light(self):
        decision = decide(Observation(zone="road", travel=0.2, surface="road", width_m=40.0))
        self.assertEqual(decision.reason, "oversized")

    def test_a_plume_over_the_forest_is_a_fire_starting(self):
        decision = decide(
            Observation(surface="forest", duration_s=40, area_grow=2.0, smoke_ratio=0.5, rise=0.02, width_m=12)
        )
        self.assertEqual(decision.type, "fire")
        self.assertEqual(decision.reason, "plume_rising")

    def test_a_plume_that_does_not_climb_is_not_a_fire(self):
        decision = decide(
            Observation(surface="forest", duration_s=40, area_grow=2.0, smoke_ratio=0.5, rise=0.0)
        )
        self.assertEqual(decision.type, "motion")

    def test_a_plume_over_the_roadway_is_not_a_fire(self):
        decision = decide(
            Observation(surface="road", zone="road", duration_s=40, area_grow=2.0, smoke_ratio=0.5, rise=0.02)
        )
        self.assertNotEqual(decision.type, "fire")

    def test_a_growing_warm_patch_is_a_fire_only_if_it_climbs(self):
        """Ce test affirmait le contraire, et c'est ce qu'il a coûté.

        Une tache tiède qui grossit sans monter passait pour un départ de feu.
        Le 29 septembre le veilleur en a publié sept, entre onze heures et
        seize heures, par ciel dégagé, sur un versant d'herbe sèche dont c'est
        la couleur : de 0,102 à 0,305 de pixels chauds, et pas un pixel de
        montée. Un feu est flottant — c'est la seule chose qu'une ombre de
        nuage ou une lumière qui tourne ne sait pas contrefaire.
        """
        plate = dict(zone="slope", duration_s=25, area_grow=2.0, warm_ratio=0.2)
        self.assertNotEqual(decide(Observation(**plate)).type, "fire")
        self.assertEqual(decide(Observation(**plate)).reason, "not_rising")

        # La même, montant comme monte une fumée portée par sa chaleur.
        montante = decide(Observation(**plate, smoke_ratio=0.42, rise=0.044, rise_ms=2.21))
        self.assertEqual(montante.type, "fire")

    def test_roundabout_point_is_not_sky(self):
        self.assertEqual(assign_zone(0.12, 0.9, ZONES), "roundabout")
        self.assertEqual(assign_zone(0.5, 0.05, ZONES), "sky")


class MotionTests(unittest.TestCase):
    def test_a_moving_blob_ends_as_one_track(self):
        zones = {"priority": ["road"], "polygons": {"road": [[0, 0], [1, 0], [1, 1], [0, 1]]}, "exclude": []}
        detector = MotionDetector(zones, motion_width=160, min_track_frames=3, warmup_frames=4)
        base = np.full((90, 160, 3), 40, dtype=np.uint8)
        for index in range(4):
            detector.step(base, index)
        ended = []
        for index in range(6):
            frame = base.copy()
            x = 20 + index * 12
            frame[30:50, x : x + 16] = 255
            ended.extend(detector.step(frame, 10 + index).ended)
        for index in range(3):
            ended.extend(detector.step(base, 20 + index).ended)
        self.assertEqual(len(ended), 1)
        self.assertGreater(ended[0].travel, 0.03)

    def test_a_full_frame_flash_is_ignored(self):
        detector = MotionDetector(ZONES, motion_width=160, warmup_frames=4)
        base = np.full((90, 160, 3), 30, dtype=np.uint8)
        for index in range(4):
            detector.step(base, index)
        white = np.full_like(base, 255)
        step = detector.step(white, 10)
        self.assertTrue(step.global_change)
        self.assertEqual(step.ended, [])


class GtfsTests(unittest.TestCase):
    def test_one_nearby_departure(self):
        folder = ROOT / "tests" / "fixtures" / "gtfs"
        rows = load_feed(folder, "fixture", 44.179, 5.2663, 3000)
        index = GtfsIndex(folder, [], 44.179, 5.2663)
        index.rows = rows
        when = datetime(2026, 9, 24, 10, 5, tzinfo=ZoneInfo("Europe/Paris"))
        trips = index.trips_at(when, 15)
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips[0].route, "Navette")

    def test_far_stop_is_ignored(self):
        folder = ROOT / "tests" / "fixtures" / "gtfs"
        rows = load_feed(folder, "fixture", 44.179, 5.2663, 3000)
        self.assertTrue(all(row["stop_name"] != "Avignon" for row in rows))


def _view(sky, ground=(40, 34, 30), height=80, width=160):
    """A frame shaped like this camera's: sky on top, the crest, then hillside.

    Flat colour fields will not do any more. Weather is now partly read from
    how sharp the crest of the Ventoux is against the sky, and a picture with
    no crest in it at all reads as fog, which is the right answer for a picture
    with no crest in it and the wrong one for a test fixture.
    """
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = sky
    frame[int(height * 0.30):] = ground
    return frame


class SceneTests(unittest.TestCase):
    def test_noon_is_day_and_deep_night_is_night(self):
        paris = ZoneInfo("Europe/Paris")
        self.assertEqual(solar_period(datetime(2026, 6, 21, 13, 0, tzinfo=paris), 44.179, 5.2663), "day")
        self.assertEqual(solar_period(datetime(2026, 6, 21, 2, 0, tzinfo=paris), 44.179, 5.2663), "night")

    def test_weather_words(self):
        self.assertEqual(weather_label(0), "ciel dégagé")
        self.assertEqual(weather_label(45), "brouillard")
        self.assertEqual(weather_label(95), "orage")

    def test_every_weather_word_has_an_english_twin(self):
        # site/app.js looks these up exactly, so a stray capital would reach an
        # English reader untranslated.
        said = {weather_label(code) for code in (0, 2, 3, 45, 61, 71, 95)}
        said.add(read_sky(_view((70, 62, 58), ground=(58, 52, 48))))
        known = set(re.findall(r'^  "(.+?)":', (ROOT / "site" / "app.js").read_text(encoding="utf-8"), re.M))
        self.assertTrue(said <= known, f"sans traduction : {sorted(said - known)}")

    def test_blue_sky_is_clear_and_a_dark_frame_is_night(self):
        blue = _view((210, 120, 30))
        dark = np.zeros((80, 160, 3), dtype=np.uint8)
        dark[:] = (8, 8, 8)
        gray = np.zeros((80, 160, 3), dtype=np.uint8)
        gray[:] = (150, 150, 150)
        self.assertEqual(read_sky(blue), "ciel dégagé")
        self.assertEqual(read_sky(dark), "nuit")
        # Lit, but flat from edge to edge: the crest is not there to be seen.
        self.assertEqual(read_sky(gray), "brouillard")

    def test_a_lit_night_with_no_crest_is_fog_and_not_clear_sky(self):
        # The night of 26 September, when the forecast said "ciel dégagé" until
        # dawn. The sky band stays bright all night here, so the colour tests
        # alone never had anything to go on.
        night = _view((70, 62, 58), ground=(58, 52, 48))
        self.assertEqual(read_sky(night), "brouillard")
        self.assertNotEqual(read_sky(_view((70, 62, 58), ground=(6, 6, 6))), "brouillard")

    def test_only_the_last_bulletin_is_kept(self):
        folder = ROOT / "data" / "view-test"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "view.json"
        path.unlink(missing_ok=True)
        log = ViewLog(path, every_s=900, change_s=120)
        blue = _view((210, 120, 30), height=40, width=80)
        start = datetime(2026, 9, 25, 16, 0, tzinfo=ZoneInfo("UTC"))
        log.note(blue, "peu nuageux", 21.2, start, "day")
        log.note(blue, "peu nuageux", 21, start.replace(minute=5), "day")
        self.assertEqual(log.last["webcam"], "ciel dégagé")
        self.assertEqual(log.last["api"], "peu nuageux")
        self.assertEqual(log.last["temp_c"], 21)
        self.assertEqual(log.last["period"], "day")
        self.assertFalse(log.last["moon"])
        self.assertEqual(json.loads(path.read_text())["last"]["webcam"], "ciel dégagé")
        path.unlink(missing_ok=True)
        (folder / "view.jpg").unlink(missing_ok=True)

    def test_the_moon_is_found_over_a_dark_sky(self):
        night = np.zeros((200, 400, 3), dtype=np.uint8)
        night[:] = (30, 28, 25)
        cv2.circle(night, (120, 40), 8, (245, 245, 240), -1)
        found = moon_spot(night)
        self.assertIsNotNone(found)
        # Drawn at (120, 40) of a 400 by 200 frame, radius 8.
        self.assertAlmostEqual(found["cx"], 0.30, places=2)
        self.assertAlmostEqual(found["cy"], 0.20, places=2)
        self.assertAlmostEqual(found["r"], 8 / 400, places=2)
        self.assertIsNone(moon_spot(np.full((200, 400, 3), 40, dtype=np.uint8)))

    def test_the_summit_beacon_is_not_the_moon(self):
        night = np.zeros((200, 400, 3), dtype=np.uint8)
        night[:] = (30, 28, 25)
        cv2.circle(night, (202, 55), 8, (245, 245, 240), -1)
        beacon = [{"cx": 0.505, "cy": 0.275, "r": 0.035}]
        self.assertIsNone(moon_spot(night, beacon))

    def test_onnx_accepts_a_frame(self):
        path = ROOT / "models" / "yolo11n.onnx"
        if not path.is_file():
            self.skipTest("models/yolo11n.onnx absent")
        from watcher.detect import YoloDetector

        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        self.assertEqual(YoloDetector(str(path)).detect(frame), [])


class FoldingTests(unittest.TestCase):
    """One card per passage, and the card must describe one moment."""

    def _event(self, when, label, thumb):
        return {"id": thumb, "t": when, "type": "vehicle", "label": label,
                "zone": "roundabout", "confidence": 0.8, "thumb": f"data/thumbs/{thumb}.jpg",
                "detail": {"box": [0.1, 0.8, 0.1, 0.1]}}

    def test_the_card_shows_the_hour_of_the_photo_it_shows(self):
        from watcher.store import fold_events
        folded = fold_events([
            self._event("2026-09-26T10:00:00Z", "Voiture", "a"),
            self._event("2026-09-26T10:00:40Z", "Camion", "b"),
        ])
        self.assertEqual(len(folded), 1)
        card = folded[0]
        # Whichever sighting won, the hour and the picture come from the same one.
        self.assertIn(card["t"].replace(":", "").replace("-", ""), ("20260926T100000Z", "20260926T100040Z"))
        stamp = "a" if card["t"].endswith("00:00Z") else "b"
        self.assertEqual(card["thumb"], f"data/thumbs/{stamp}.jpg")

    def test_the_first_sighting_hour_is_not_lost(self):
        from watcher.store import fold_events
        folded = fold_events([
            self._event("2026-09-26T10:00:00Z", "Voiture", "a"),
            self._event("2026-09-26T10:00:40Z", "Camion", "b"),
        ])
        detail = folded[0]["detail"]
        self.assertEqual(detail["count"], 2)
        self.assertTrue(detail.get("since"))

    def test_two_passages_far_apart_stay_two_cards(self):
        from watcher.store import fold_events
        folded = fold_events([
            self._event("2026-09-26T10:00:00Z", "Voiture", "a"),
            self._event("2026-09-26T11:30:00Z", "Voiture", "b"),
        ])
        self.assertEqual(len(folded), 2)


class SkyFromThePictureTests(unittest.TestCase):
    """The forecast answers for the valley; the camera can see its own sky."""

    def test_a_blue_band_reads_as_clear(self):
        import numpy as np
        from watcher.scene import sky_cover, weather_from_sky
        frame = np.zeros((270, 480, 3), dtype=np.uint8)
        frame[:, :] = (200, 140, 90)  # bleu franc en BGR
        self.assertLess(sky_cover(frame), 12)
        self.assertEqual(weather_from_sky(sky_cover(frame)), "ciel dégagé")

    def test_a_grey_band_reads_as_overcast(self):
        import numpy as np
        from watcher.scene import sky_cover, weather_from_sky
        frame = np.zeros((270, 480, 3), dtype=np.uint8)
        frame[:, :] = (170, 170, 170)
        self.assertGreater(sky_cover(frame), 80)
        self.assertEqual(weather_from_sky(sky_cover(frame)), "couvert")

    def test_a_dark_frame_gives_no_reading(self):
        import numpy as np
        from watcher.scene import sky_cover
        # At night there is nothing to read, and a guess would be worse than
        # the forecast the reading is there to replace.
        self.assertIsNone(sky_cover(np.zeros((270, 480, 3), dtype=np.uint8)))


class FrameOfSkyTests(unittest.TestCase):
    """The camera looks down and sideways, so height alone decides nothing."""

    def eye(self):
        return Observation(zone="sky", camera_lat=44.1833492432, camera_lon=5.262028106399995,
                           camera_ele=1390.0, camera_bearing=126.713, camera_fov=78.755,
                           camera_pitch=-6.021, camera_vfov=49.563)

    def test_an_airliner_forty_kilometres_out_is_too_far_to_be_seen(self):
        """It is in the frame and still not in the picture.

        Forty kilometres puts an airliner inside every angle the camera covers
        and makes it one pixel and a half across, which is nothing. Naming it
        was how a day of clouds came to be signed by eight airlines.
        """
        plane = {"lat": 44.15, "lon": 5.76, "altitude_m": 11000}
        self.assertFalse(in_camera_view(plane, self.eye()))

    def test_an_aircraft_close_enough_to_show_is_in_the_picture(self):
        plane = {"lat": 44.10, "lon": 5.42, "altitude_m": 3200}
        self.assertTrue(in_camera_view(plane, self.eye()))

    def test_the_same_airliner_overhead_is_not(self):
        plane = {"lat": 44.184, "lon": 5.263, "altitude_m": 11000}
        self.assertFalse(in_camera_view(plane, self.eye()))

    def test_a_water_bomber_low_and_close_is_in_the_picture(self):
        bomber = {"lat": 44.165, "lon": 5.300, "altitude_m": 2200}
        self.assertTrue(in_camera_view(bomber, self.eye()))

    def test_nothing_behind_the_camera_counts(self):
        plane = {"lat": 44.40, "lon": 5.10, "altitude_m": 6000}
        self.assertFalse(in_camera_view(plane, self.eye()))

    def test_too_far_to_read_is_refused(self):
        speck = {"lat": 43.30, "lon": 6.60, "altitude_m": 11000}
        self.assertFalse(in_camera_view(speck, self.eye()))


class SkyTests(unittest.TestCase):
    def test_archive_returns_the_aircraft_in_the_window(self):
        path = ROOT / "data" / "sky-test.jsonl"
        archive = SkyArchive(path, [44.0, 5.0, 44.3, 5.5])
        path.write_text(
            "\n".join(
                [
                    json.dumps({"t": 1000, "aircraft": [{"icao24": "aaa", "callsign": "OLD", "altitude_m": 1000}]}),
                    json.dumps({"t": 1500, "aircraft": [{"icao24": "bbb", "callsign": "NOW", "altitude_m": 2000}]}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        found = archive.around(1505, 30)
        path.unlink()
        self.assertEqual([item["callsign"] for item in found], ["NOW"])

    def test_a_reading_already_held_spends_no_question(self):
        path = ROOT / "data" / "sky-test.jsonl"
        archive = SkyArchive(path, [44.0, 5.0, 44.3, 5.5])
        archive.poll = lambda now=None: self.fail("OpenSky ne devrait pas être appelé")
        path.write_text(
            json.dumps({"t": 1500, "aircraft": [{"icao24": "bbb", "callsign": "NOW"}]}) + "\n",
            encoding="utf-8",
        )
        found = archive.ask(1505, 30)
        path.unlink()
        self.assertEqual([item["callsign"] for item in found], ["NOW"])

    def test_two_crossings_in_the_same_quiet_period_share_one_question(self):
        path = ROOT / "data" / "sky-test.jsonl"
        archive = SkyArchive(path, [44.0, 5.0, 44.3, 5.5], quiet_s=600)
        asked = []
        archive.poll = lambda now=None: asked.append(now)
        archive.ask(time.time(), 30)
        archive.ask(time.time(), 30)
        if path.exists():
            path.unlink()
        self.assertEqual(len(asked), 1)

    def test_a_band_too_low_on_the_roadway_is_the_tarmac(self):
        flat = Observation(zone="roundabout", surface="roundabout", travel=0.2, width_m=2.2, height_m=0.29,
                           detections=[Detection(cls="car", conf=0.8)])
        self.assertEqual(decide(flat).type, "motion")
        self.assertEqual(decide(flat).reason, "tarmac")
        car = Observation(zone="roundabout", surface="roundabout", travel=0.2, width_m=2.5, height_m=0.79,
                          detections=[Detection(cls="car", conf=0.8)], min_conf={"car": 0.4})
        self.assertEqual(decide(car).type, "vehicle")

    def test_a_metre_wide_on_the_roundabout_is_not_a_vehicle(self):
        speck = Observation(zone="other", surface="roundabout", period="night", travel=0.2,
                            width_m=1.13, height_m=0.98)
        self.assertEqual(decide(speck).type, "motion")
        self.assertEqual(decide(speck).reason, "too_small")
        car = Observation(zone="other", surface="roundabout", period="night", travel=0.2,
                          frames=9, duration_s=5.0, width_m=2.6, height_m=0.98,
                          detections=[Detection("car", 0.30)])
        self.assertEqual(decide(car).type, "vehicle")

    def test_what_stands_still_on_the_island_is_the_furniture(self):
        planted = Observation(zone="roundabout", surface="island", travel=0.0, width_m=1.6, height_m=1.26,
                              detections=[Detection(cls="person", conf=0.73)])
        self.assertEqual(decide(planted).type, "motion")
        self.assertEqual(decide(planted).reason, "island")
        crossing = Observation(zone="roundabout", surface="island", travel=0.2, width_m=3.0, height_m=1.4,
                               detections=[Detection(cls="car", conf=0.8)], min_conf={"car": 0.4})
        self.assertEqual(decide(crossing).type, "vehicle")

    def test_the_lamp_of_the_summit_mast_is_not_a_fire(self):
        common = dict(zone="slope", surface="forest", duration_s=30, warm_ratio=0.5,
                      area_grow=4.0, travel=0.0, period="night", width_m=6.0)
        lamp = Observation(landmark="Émetteur du mont Ventoux", **common)
        self.assertEqual(decide(lamp).type, "motion")
        self.assertEqual(decide(lamp).reason, "beacon")
        self.assertEqual(decide(Observation(**common)).type, "fire")

    def test_what_has_just_caught_is_a_start_not_a_blaze(self):
        common = dict(zone="slope", surface="forest", duration_s=30, warm_ratio=0.5,
                      area_grow=4.0, travel=0.0, period="night", width_m=6.0)
        self.assertEqual(decide(Observation(**common)).label, "Départ de feu")
        held = dict(common, duration_s=900)
        self.assertEqual(decide(Observation(**held)).label, "Incendie")

    def test_a_plume_that_climbs_into_the_sky_keeps_its_track(self):
        detector = MotionDetector(ZONES, motion_width=640, min_track_frames=1)
        detector.tracks = [Track(id=1, zone="slope", frames=4, centroid=(0.5, 0.5), first_centroid=(0.5, 0.62))]
        self.assertEqual(detector._match(0.5, 0.42, "sky", {0}), 0)
        self.assertEqual(detector.tracks[0].zone, "slope")

    def test_only_something_longer_than_a_car_opens_the_timetable(self):
        cfg = {"min_conf": 0.35}
        road = Track(id=1, zone="road")
        sky = Track(id=2, zone="sky")
        car = [Detection(cls="car", conf=0.9)]
        coach = [Detection(cls="bus", conf=0.6)]
        self.assertFalse(_might_be_bus(road, car, 3.2, cfg))
        self.assertTrue(_might_be_bus(road, car, 11.0, cfg))
        self.assertTrue(_might_be_bus(road, coach, 3.2, cfg))
        self.assertFalse(_might_be_bus(sky, coach, 11.0, cfg))

    def test_a_point_that_did_not_move_asks_nothing(self):
        cfg = {"min_travel": 0.01, "max_sky_area": 0.02}
        still = Track(id=1, zone="sky", area_ratio=0.001, first_centroid=(0.5, 0.5), centroid=(0.5, 0.5))
        cloud = Track(id=2, zone="sky", area_ratio=0.5, first_centroid=(0.1, 0.5), centroid=(0.9, 0.5))
        plane = Track(id=3, zone="sky", area_ratio=0.001, first_centroid=(0.1, 0.5), centroid=(0.9, 0.5))
        self.assertFalse(_crossed_sky(still, cfg))
        self.assertFalse(_crossed_sky(cloud, cfg))
        self.assertTrue(_crossed_sky(plane, cfg))


class StoreTests(unittest.TestCase):
    def test_a_burst_becomes_one_passage_and_keeps_the_correction(self):
        events = [
            {"id": "a", "t": "2026-09-25T08:52:04Z", "type": "motion", "label": "Mouvement", "zone": "other", "confidence": 0.3, "thumb": "data/thumbs/a.jpg", "detail": {}},
            {"id": "b", "t": "2026-09-25T08:52:21Z", "type": "car", "label": "Voiture", "zone": "roundabout", "confidence": 0.75, "thumb": "data/thumbs/b.jpg", "review": "accepted", "detail": {"correction": "Estafette", "context": "de jour, ciel dégagé"}},
            {"id": "c", "t": "2026-09-25T08:52:21Z", "type": "motion", "label": "Mouvement détecté", "zone": "road", "confidence": 0.3, "thumb": "data/thumbs/c.jpg", "detail": {}},
        ]
        folded = fold_events(events)
        self.assertEqual(len(folded), 1)
        self.assertEqual(folded[0]["label"], "Estafette")
        self.assertEqual(folded[0]["review"], "accepted")
        self.assertGreaterEqual(folded[0]["detail"]["count"], 3)

    def test_old_events_are_dropped(self):
        root = ROOT / "data" / "store-test"
        root.mkdir(parents=True, exist_ok=True)
        store = Store(root, history_days=30)
        old = datetime(2020, 1, 1, tzinfo=ZoneInfo("UTC"))
        store.add_event(old, "car", "Voiture", "road", 0.9, b"", {})
        store.prune(datetime(2026, 9, 24, tzinfo=ZoneInfo("UTC")))
        self.assertEqual(store.events, [])
        (root / "events.json").unlink(missing_ok=True)

    def test_a_card_keeps_exactly_one_observation_the_one_it_shows(self):
        """Neuf pour cent du fichier des observations était en trop.

        Un passage revu dans la minute rejoint la carte déjà ouverte, mais
        l'appelant gardait quand même l'observation de chaque vue. Sous un même
        identifiant s'empilaient donc jusqu'à quatre raisonnements, dont
        certains d'une lecture que la carte ne montre pas — et un lecteur qui
        prend la première ligne rejoue le mauvais. C'est ce qui m'a fait croire
        le 30 septembre que le disque perdait les détections du modèle.
        """
        import shutil

        root = ROOT / "data" / "store-seen-test"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        store = Store(root, history_days=30)
        depart = datetime(2026, 9, 30, 12, 0, 0, tzinfo=ZoneInfo("UTC"))

        def voir(secondes, type_, label, confiance, marque):
            quand = depart + timedelta(seconds=secondes)
            carte = store.add_event(quand, type_, label, "road", confiance, b"", {})
            store.record_seen(carte["id"], {"marque": marque})
            return carte

        premiere = voir(0, "motion", "Mouvement détecté", 0.3, "vague")
        # Mieux lu dans la même minute : la carte adopte ce mot-là.
        meilleure = voir(12, "vehicle", "Voiture", 0.8, "nette")
        # Revu encore, sans rien de neuf à dire : la carte ne bouge pas.
        pauvre = voir(24, "motion", "Mouvement détecté", 0.3, "faible")
        self.assertEqual(meilleure["id"], premiere["id"], "les trois vues font une seule carte")
        self.assertEqual(pauvre["id"], premiere["id"])
        self.assertEqual(pauvre["label"], "Voiture", "la carte a gardé la meilleure lecture")

        lignes = [json.loads(l) for l in (root / "observed.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lignes), 1, f"une carte, une observation ; trouvé {len(lignes)}")
        self.assertEqual(lignes[0]["id"], premiere["id"])
        self.assertEqual(lignes[0]["seen"]["marque"], "nette",
                         "l'observation gardée doit être celle de la lecture que la carte montre")
        shutil.rmtree(root, ignore_errors=True)


class ThumbTests(unittest.TestCase):
    def test_motion_box_is_drawn_on_the_photo(self):
        image = np.zeros((80, 160, 3), dtype=np.uint8)
        image[:] = (30, 70, 30)
        ok, encoded = cv2.imencode(".jpg", image)
        self.assertTrue(ok)
        marked = cv2.imdecode(np.frombuffer(small_jpeg(encoded.tobytes(), box=[0.4, 0.35, 0.1, 0.12]), dtype=np.uint8), cv2.IMREAD_COLOR)
        height, width = marked.shape[:2]
        subject = marked[int(0.41 * height), int(0.45 * width)]
        self.assertLess(int(subject[2]), 80)
        self.assertGreater(int(marked[:, :, 2].max()), 120)


class ReviewTests(unittest.TestCase):
    def test_motion_can_be_named_car_bus_or_wrong(self):
        body = "event_id: m1\nverdict: accepted\nlecture: Mouvement\nclasse: voiture\n"
        self.assertEqual(parse_review(body, "valide"), ("m1", "accepted", "voiture"))
        events = [{"id": "m1", "type": "motion", "label": "Mouvement", "detail": {}}]
        learning = {}
        self.assertTrue(apply_review(events, learning, "m1", "accepted", "voiture"))
        self.assertEqual(events[0]["type"], "vehicle")
        self.assertEqual(events[0]["label"], "Voiture")
        # « Mouvement » ne nommait rien : le préciser n'est pas le démentir.
        self.assertNotIn("correction", events[0]["detail"])
        self.assertTrue(apply_review(events, learning, "m1", "accepted", "bus"))
        self.assertEqual(events[0]["type"], "bus")
        self.assertEqual(events[0]["label"], "Bus")
        # Cette fois la lecture disait « voiture » : dire bus la dément.
        self.assertEqual(events[0]["detail"]["correction"], "Bus")
        self.assertTrue(apply_review(events, learning, "m1", "rejected", ""))
        self.assertEqual(events[0]["review"], "rejected")

    def test_the_script_that_records_a_verdict_runs_on_its_own(self):
        """Onze verdicts perdus parce qu'un script ne s'importait pas.

        Celui-ci tourne dans une action GitHub, sans personne devant l'écran :
        il a échoué onze fois de suite sur « No module named 'watcher' » et
        chaque échec a emporté une validation — plus la reconstruction du site,
        qui est la dernière étape du même travail. Les tests de la relecture
        appelaient les fonctions directement et ne voyaient rien.

        On l'appelle donc comme l'action l'appelle : un sous-processus, lancé
        depuis un autre répertoire, sans la racine dans PYTHONPATH.
        """
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["ISSUE_BODY"] = "event_id: inexistant\nverdict: accepted\nlecture: Voiture\nclasse: voiture\n"
        env["LABEL"] = "valide"
        fait = subprocess.run(
            [sys.executable, str(root / "scripts" / "apply_review.py")],
            cwd=root, env=env, capture_output=True, text=True,
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertNotIn("ModuleNotFoundError", fait.stderr)

    def test_every_script_can_find_the_watcher(self):
        """La même faute vaut pour tous les scripts, pas seulement celui-là.

        Sauf pour ceux qu'on lance en « -m scripts.machin » : cette forme-là
        met la racine dans le chemin d'elle-même. Chaque script dit comment on
        l'appelle dans sa propre première phrase, et c'est ce qu'on lui demande
        ici plutôt que de tenir une liste à côté.
        """
        root = Path(__file__).resolve().parents[1]
        aveugles = []
        for script in sorted((root / "scripts").glob("*.py")):
            source = script.read_text(encoding="utf-8")
            if not re.search(r"^(from|import) watcher", source, re.M):
                continue
            if f"-m scripts.{script.stem}" in source or "sys.path.insert" in source:
                continue
            aveugles.append(script.name)
        self.assertFalse(aveugles, f"importent watcher sans se donner la racine : {aveugles}")


if __name__ == "__main__":
    unittest.main()


class InterruptionTests(unittest.TestCase):
    """An empty history must say whether nothing happened or nobody watched."""

    def setUp(self):
        self.note = _note_interruption
        self.journal = ROOT / "data" / "interruptions-test.jsonl"
        self.journal.unlink(missing_ok=True)

    def tearDown(self):
        self.journal.unlink(missing_ok=True)

    def _rows(self):
        if not self.journal.exists():
            return []
        return [json.loads(line) for line in self.journal.read_text().splitlines()]

    def test_an_hour_of_blindness_is_written_down(self):
        self.assertEqual(self.note(self.journal, 1_790_000_000.0, 1_790_003_600.0), 3600.0)
        row = self._rows()[0]
        self.assertEqual(row["seconds"], 3600)
        self.assertEqual((row["start"], row["end"]), (_utc(1_790_000_000.0), _utc(1_790_003_600.0)))

    def test_one_slow_picture_is_not_an_interruption(self):
        self.assertEqual(self.note(self.journal, 1_790_000_000.0, 1_790_000_012.0), 0.0)
        self.assertEqual(self._rows(), [])

    def test_a_first_run_has_nothing_to_report(self):
        """No beat at all means no watcher before, not an infinite blind spell."""
        self.assertEqual(self.note(self.journal, 0.0, 1_790_000_000.0), 0.0)
        self.assertEqual(self._rows(), [])

    def test_each_spell_keeps_its_own_line(self):
        self.note(self.journal, 1_790_000_000.0, 1_790_003_600.0)
        self.note(self.journal, 1_790_010_000.0, 1_790_010_300.0)
        self.assertEqual([row["seconds"] for row in self._rows()], [3600, 300])


class SingleWatcherTests(unittest.TestCase):
    """Two watchers on one camera would write every event twice."""

    def test_a_second_watcher_is_turned_away(self):
        code = (
            "import sys;from pathlib import Path;from watcher.main import _only_one;"
            "print(_only_one(Path(sys.argv[1])), flush=True);import time;time.sleep(float(sys.argv[2]))"
        )
        lock = ROOT / "data" / "lock-test"
        lock.unlink(missing_ok=True)
        held = subprocess.Popen([sys.executable, "-c", code, str(lock), "5"], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(held.stdout.readline().strip(), "True")
            second = subprocess.run([sys.executable, "-c", code, str(lock), "0"], capture_output=True, text=True)
            self.assertEqual(second.stdout.strip(), "False")
        finally:
            held.terminate()
            held.wait()
        freed = subprocess.run([sys.executable, "-c", code, str(lock), "0"], capture_output=True, text=True)
        self.assertEqual(freed.stdout.strip(), "True")
        lock.unlink(missing_ok=True)


class EdgeOfFrameTests(unittest.TestCase):
    """A blob cut by the border of the picture has no size worth trusting."""

    def _clipped(self, **extra):
        return Observation(zone="roundabout", period="night", travel=0.2, clipped=True,
                           surface="", frames=9, duration_s=5.0, **extra)

    def test_a_weak_reading_at_the_edge_names_nothing(self):
        # The measurements of 20:30, which were the rear lights of a car.
        cut = self._clipped(detections=[Detection("person", 0.43)])
        self.assertEqual(decide(cut).type, "motion")
        self.assertEqual(decide(cut).reason, "edge_of_frame")

    def test_a_sure_reading_at_the_edge_still_counts(self):
        seen = self._clipped(detections=[Detection("person", 0.82)])
        self.assertEqual(decide(seen).type, "person")

    def test_the_edge_rule_waits_for_an_unsurveyed_floor(self):
        known = replace(self._clipped(detections=[Detection("person", 0.43)]), surface="roundabout")
        self.assertNotEqual(decide(known).reason, "edge_of_frame")


class WalkerWidthTests(unittest.TestCase):
    """Sixty three walkers by day were measured before this rule was written."""

    def test_a_walker_half_the_picture_wide_is_not_a_walker(self):
        # 20:55, a car going away, and 20:30 and 21:08 coming the other way.
        for width, conf in ((0.436, 0.71), (0.434, 0.44), (0.323, 0.43)):
            wide = Observation(zone="road", period="night", travel=0.2, surface="road",
                               frames=9, duration_s=5.0, box_w=width,
                               detections=[Detection("person", conf)])
            self.assertNotEqual(decide(wide).type, "person", f"largeur {width}")

    def test_a_thing_bolted_to_the_ground_is_never_a_walker(self):
        # The wooden statue beside the path, forty centimetres wide and a metre
        # sixty tall on the ground: exactly a person. It was named a walker on
        # three separate nights. The travel test never caught it because a
        # car's headlights sweeping across it lend it a movement it never had.
        carved = Observation(zone="other", period="night", travel=0.4, surface="path",
                             width_m=0.4, height_m=1.6, box_w=0.011,
                             fixture="statue", landmark="statue",
                             detections=[Detection("person", 0.44)])
        self.assertEqual(decide(carved).reason, "landmark")
        self.assertEqual(decide(carved).type, "motion")

    def test_somebody_walking_past_the_statue_is_still_named(self):
        # Beside it, not centred on it: scenemap.landmark_under says no, and
        # only that one refuses outright.
        passer = Observation(zone="other", period="night", travel=0.4, surface="path",
                             width_m=0.5, height_m=1.7, box_w=0.012,
                             landmark="statue",
                             detections=[Detection("person", 0.62)])
        self.assertEqual(decide(passer).type, "person")

    def test_a_scrap_too_short_to_stand_is_not_a_walker(self):
        # The white car coming into frame at the bottom left on 26 September at
        # 22:12. Only its corner was caught: a metre wide, seventy-seven
        # centimetres tall, and read as somebody on foot at half confidence.
        scrap = Observation(zone="roundabout", period="night", travel=0.2, surface="road",
                            width_m=1.02, height_m=0.77, box_w=0.031,
                            detections=[Detection("person", 0.497)])
        self.assertNotEqual(decide(scrap).type, "person")

    def test_the_shortest_walker_ever_measured_still_passes(self):
        # Sixty-three by daylight; the shortest stood ninety-nine centimetres.
        short = Observation(zone="road", period="day", travel=0.2, surface="road",
                            width_m=1.40, height_m=0.99, box_w=0.033,
                            detections=[Detection("person", 0.53)])
        self.assertEqual(decide(short).type, "person")

    def test_a_walker_of_the_usual_width_is_still_named(self):
        usual = Observation(zone="road", period="day", travel=0.2, surface="road",
                            box_w=0.062, detections=[Detection("person", 0.55)])
        self.assertEqual(decide(usual).type, "person")


class ColourBeforeSmokeTests(unittest.TestCase):
    """A fire that has caught but has not yet made a plume."""

    def _caught(self, **extra):
        base = dict(zone="slope", surface="forest", duration_s=5.0, travel=0.0,
                    area_grow=0.8, smoke_ratio=0.20, rise=0.0,
                    fire_sustain_s=5.0, fire_grow=1.6, fire_warm=0.35,
                    fire_smoke=0.35, fire_rise=0.008, period="day",
                    sun_bearing=250.0, sun_elevation=40.0)
        base.update(extra)
        return Observation(**base)

    def test_fire_colour_alone_raises_the_alarm(self):
        # The readings of the drawn fire at its fifth second, before any smoke.
        self.assertEqual(decide(self._caught(warm_ratio=0.41)).type, "fire")

    def test_merely_warm_and_not_growing_raises_nothing(self):
        # Over the plain threshold but under the one asked when nothing else
        # vouches for it: no growth, no plume, no movement.
        self.assertNotEqual(decide(self._caught(warm_ratio=0.37)).type, "fire")

    def test_the_rising_sun_is_still_not_a_fire(self):
        dawn = self._caught(warm_ratio=0.50, sun_bearing=97.0, sun_elevation=6.0,
                            at_x=0.153, camera_bearing=126.713, camera_fov=78.755)
        self.assertEqual(decide(dawn).type, "motion")
        self.assertEqual(decide(dawn).reason, "low_sun")


COULEURS = ("rouge", "bleue", "blanche", "noire", "grise", "verte",
            "jaune", "orange", "marron", "beige")


def _meme_chose(lu: str, attendu: str) -> bool:
    """Le même mot, à la couleur près."""
    def nu(mot: str) -> str:
        bouts = mot.split()
        return " ".join(b for b in bouts if b.lower() not in COULEURS)
    return bool(lu) and nu(lu) == nu(attendu)


class FogTests(unittest.TestCase):
    """The night of 26 September, when a street lamp was called a fire eight times."""

    def _lamp(self, **extra):
        # The readings the watcher actually filed at 01:14 UTC: warm, swelling,
        # and with no plume worth the name.
        base = dict(zone="slope", surface="forest", duration_s=7.6, travel=0.0008,
                    area_grow=9.6, warm_ratio=0.308, smoke_ratio=0.105, rise=0.0028,
                    fire_sustain_s=5.0, fire_grow=1.6, fire_warm=0.08,
                    fire_smoke=0.35, fire_rise=0.008, period="night",
                    sun_bearing=250.0, sun_elevation=-30.0)
        base.update(extra)
        return Observation(**base)

    def test_a_haloed_lamp_in_fog_is_not_a_fire(self):
        called = decide(self._lamp(fogged=True, hazy=True))
        self.assertEqual(called.type, "motion")
        self.assertEqual(called.reason, "fog")

    def test_fog_silences_every_name_and_not_only_fire(self):
        # Between 22:24 and 01:14 the fog published eight fires, two walkers
        # and two vehicles. All twelve were wrong.
        walker = Observation(zone="roundabout", period="night", surface="road", travel=0.02,
                             box_w=0.070, detections=[Detection("person", 0.62)], fogged=True, hazy=True)
        van = Observation(zone="road", period="night", surface="road", travel=0.05, width_m=4.2,
                          box_w=0.133, detections=[Detection("car", 0.71)], fogged=True, hazy=True)
        for seen in (walker, van):
            self.assertEqual(decide(seen).reason, "fog")
            self.assertEqual(decide(seen).type, "motion")

    def test_a_car_in_daylight_fog_is_still_named(self):
        # 27 September, 06:11 to 06:13 UTC: the crest read 3.9 and a car went
        # round the roundabout in plain sight. The watcher held it for two and
        # a half minutes and refused it fifty-three times. By day the lamp that
        # made every one of the twelve night mistakes is out.
        car = Observation(zone="roundabout", period="day", surface="road", travel=0.2112,
                          width_m=4.4, box_w=0.140, detections=[Detection("car", 0.68)],
                          fogged=True, hazy=True)
        self.assertNotEqual(decide(car).reason, "fog")
        self.assertEqual(decide(car).type, "vehicle")
        self.assertEqual(decide(car).action, "publish")

    def test_the_box_is_drawn_on_the_thing_that_was_named(self):
        """27 September, 16:06 local. A car and a group of walkers moved
        together on the roundabout. The word published was "Voiture" and the
        red rectangle sat on the walkers, because the box came from the motion
        blob — which holds everything that moved — while the model's own box,
        the one that knows which of the two was the car, was thrown away at the
        line that built the Detection.
        """
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        seen = [Detection("person", 0.88, box=(1400, 900, 40, 90)),
                Detection("car", 0.46, box=(1000, 950, 200, 100))]
        box = _box_of_the_named(frame, Decision("publish", "vehicle", "Voiture", "x", {}, 0.5), seen,
                                (990, 940, 220, 120))
        middle = (box[0] + box[2] / 2, box[1] + box[3] / 2)
        self.assertAlmostEqual(middle[0], 1100 / 1920, places=2)
        self.assertAlmostEqual(middle[1], 1000 / 1080, places=2)

    def test_the_parked_car_at_the_kerb_is_not_the_one_marked(self):
        """27 September, 16:25 local. The model is handed a crop wider than the
        blob, so it read both the car that drove past and one standing at the
        kerb. The parked one was the more confident of the two and took the red
        box. Confidence says what a thing is, never which of them moved.
        """
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        seen = [Detection("car", 0.82, box=(200, 600, 180, 90)),    # à l'arrêt
                Detection("car", 0.41, box=(1000, 950, 200, 100))]  # celle qui passe
        box = _box_of_the_named(frame, Decision("publish", "vehicle", "Voiture", "x", {}, 0.5), seen,
                                (990, 940, 220, 120))
        self.assertAlmostEqual(box[0] + box[2] / 2, 1100 / 1920, places=2)

    def test_the_blob_still_stands_where_the_model_said_nothing(self):
        # It says nothing about most of what moves here. Nothing is forced.
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        seen = [Detection("person", 0.88, box=(1400, 900, 40, 90))]
        self.assertIsNone(_box_of_the_named(frame, Decision("publish", "vehicle", "Voiture", "x", {}, 0.5), seen))
        self.assertIsNone(_box_of_the_named(frame, Decision("publish", "fire", "Départ de feu", "x", {}, 0.5), seen))

    def test_a_cloud_drifting_over_the_slope_is_not_a_start_of_fire(self):
        """The three false starts of 27 September, by their own measurements.

        No warmth at all, a pale mass rising and growing — which is what a
        cloud does — and 39.7 m, 56.8 m and 211.1 m wide. The forecast called
        it a clear sky because it describes the valley a thousand metres below.
        """
        for width in (39.7, 56.8, 211.1):
            cloud = Observation(zone="slope", surface="forest", period="day", width_m=width,
                                duration_s=32.3, travel=0.02, warm_ratio=0.0, smoke_ratio=0.35,
                                rise=0.0194, area_grow=2.27, fire_sustain_s=5.0, fire_grow=1.6,
                                fire_warm=0.08, fire_smoke=0.35, fire_rise=0.008)
            self.assertEqual(decide(cloud).type, "motion", f"{width} m")
            self.assertEqual(decide(cloud).reason, "cloud", f"{width} m")

    def test_a_small_plume_on_the_slope_is_still_a_fire(self):
        # The size limit must not close the door it was put there to narrow.
        start = Observation(zone="slope", surface="forest", period="day", width_m=8.0,
                            duration_s=9.0, travel=0.02, warm_ratio=0.0, smoke_ratio=0.35,
                            rise=0.0194, area_grow=2.27, fire_sustain_s=5.0, fire_grow=1.6,
                            fire_warm=0.08, fire_smoke=0.35, fire_rise=0.008)
        self.assertEqual(decide(start).type, "fire")

    def test_the_tractor_working_the_meadow_is_not_a_start_of_fire(self):
        """28 September, 14:02 Paris, by its own measurements.

        A pale grey cab on green grass reads as smoke, it rose and it grew, and
        at twenty pixels across the model returned nothing to contradict it.
        The one thing it cannot counterfeit is buoyancy: its top wandered
        upwards at half a metre a second, where every plume measured climbs at
        more than two.
        """
        tractor = Observation(zone="slope", period="day", width_m=7.0, duration_s=6.0,
                              travel=0.03, rise_ms=0.55, warm_ratio=0.0, smoke_ratio=0.426,
                              rise=0.0278, area_grow=2.8, fire_sustain_s=5.0, fire_grow=1.6,
                              fire_warm=0.08, fire_smoke=0.35, fire_rise=0.008)
        self.assertEqual(decide(tractor).type, "motion")
        self.assertEqual(decide(tractor).reason, "machine")

    def test_a_plume_climbing_at_its_measured_speed_alerts(self):
        """The slowest of eleven readings across three simulated plumes."""
        rising = Observation(zone="slope", surface="forest", period="day", width_m=18.4,
                             duration_s=7.0, travel=0.06, rise_ms=2.21, warm_ratio=0.0,
                             smoke_ratio=0.42, rise=0.044, area_grow=4.2, fire_sustain_s=5.0,
                             fire_grow=1.6, fire_warm=0.08, fire_smoke=0.35, fire_rise=0.008)
        self.assertEqual(decide(rising).type, "fire")

    def test_a_fire_the_survey_cannot_measure_still_alerts(self):
        """No metres means no test, never a refusal.

        The climb is read through the ground distance. Where the survey is
        silent there is no speed to compare, and a fire that cannot be measured
        must still be able to raise the alarm.
        """
        unmeasured = Observation(zone="slope", surface="forest", period="day", width_m=0.0,
                                 duration_s=7.0, travel=0.06, rise_ms=0.0, warm_ratio=0.0,
                                 smoke_ratio=0.42, rise=0.044, area_grow=4.2, fire_sustain_s=5.0,
                                 fire_grow=1.6, fire_warm=0.08, fire_smoke=0.35, fire_rise=0.008)
        self.assertEqual(decide(unmeasured).type, "fire")

    def test_a_hillside_alight_need_not_climb(self):
        """The climb is asked of the cold ones only.

        A front running through scrub shows colour before it shows a column.
        Asking it for a plume as well would be a way of never alerting on the
        worst case.
        """
        running = Observation(zone="slope", surface="forest", period="day", width_m=25.0,
                              duration_s=12.0, travel=0.08, rise_ms=0.2, warm_ratio=0.62,
                              smoke_ratio=0.3, rise=0.03, area_grow=3.1, fire_sustain_s=5.0,
                              fire_grow=1.6, fire_warm=0.08, fire_smoke=0.35, fire_rise=0.008)
        self.assertEqual(decide(running).type, "fire")

    def test_the_foot_of_a_blob_is_read_at_its_lowest_rows(self):
        """A plume that leans keeps its foot; its middle does not."""
        from watcher.motion import _foot_x

        leaning = np.array([[[100, 10]], [[140, 10]], [[112, 60]], [[108, 60]]], dtype=np.int32)
        self.assertAlmostEqual(_foot_x(leaning, 200), 110 / 200, places=3)

    def test_the_climb_is_read_in_metres_a_second(self):
        """The tractor of 28 September: 5.3 m tall over 0.0444 of the frame."""
        from watcher.main import _climb

        self.assertAlmostEqual(_climb(0.0278, 5.3, 0.0444, 6.0), 0.553, places=2)
        # Without the survey there is no metre, so there is no speed to give.
        self.assertEqual(_climb(0.0278, 0.0, 0.0444, 6.0), 0.0)

    def test_a_word_said_about_a_corner_does_not_name_the_whole(self):
        """28 September, 14:52. A cyclist towing a trailer, published as an
        orange car. The model read "car" at 0.30 on a box covering four per
        cent of what moved, and the footprint — 3.5 m by 2.0 — was car-shaped
        enough to let it through. Both pieces of evidence have to be about the
        same object.
        """
        seen = [Detection("car", 0.30, box=(320, 1030, 9, 15), share=0.039)]
        corner = Observation(zone="roundabout", surface="roundabout", period="day",
                             detections=seen, width_m=3.5, height_m=2.0, travel=0.25,
                             min_conf={"car": 0.45, "bus": 0.5, "person": 0.4})
        self.assertNotEqual(decide(corner).type, "vehicle")

    def test_the_same_reading_over_the_whole_thing_still_names_it(self):
        """The bar is about coverage, not confidence: a car read at the same
        0.30 over most of what moved is still named.
        """
        seen = [Detection("car", 0.30, box=(320, 1030, 200, 110), share=0.71)]
        whole = Observation(zone="roundabout", surface="roundabout", period="day",
                            detections=seen, width_m=3.5, height_m=2.0, travel=0.25,
                            min_conf={"car": 0.45, "bus": 0.5, "person": 0.4})
        self.assertEqual(decide(whole).type, "vehicle")

    def test_coverage_and_overlap_answer_opposite_questions(self):
        from watcher.main import _covers, _overlap

        blob, corner = (100, 100, 200, 100), (110, 110, 20, 10)
        # The little box sits wholly inside the blob, and holds a hundredth of it.
        self.assertAlmostEqual(_overlap(corner, blob), 1.0, places=3)
        self.assertAlmostEqual(_covers(corner, blob), 0.01, places=3)

    def test_a_shadow_keeps_the_drawing_underneath_and_a_car_hides_it(self):
        """La mesure qui sépare un changement de lumière d'une chose qui passe.

        Une ombre et la flaque des phares changent la clarté sans toucher au
        dessin : le muret reste le muret, ses pierres sont à leur place. Une
        chose qui passe cache ce qu'il y a derrière, et le dessin disparaît
        avec. Éprouvé sur le même morceau de décor, changé de trois façons.
        """
        from watcher.motion import _lighting

        rng = np.random.default_rng(7)
        # Un mur de pierres : du grain, comme tout ce que cette caméra regarde.
        wall = rng.integers(60, 190, size=(60, 90, 3), dtype=np.uint8)
        box = (0.0, 0.0, 90.0, 60.0)

        dark = (wall * 0.55).astype(np.uint8)
        shade, texture = _lighting(dark, wall, box, 1.0)
        self.assertLess(shade, 0.75, "une ombre assombrit")
        self.assertGreater(texture, 0.9, "et laisse le dessin intact")

        lit = np.clip(wall.astype(np.float32) * 1.45, 0, 255).astype(np.uint8)
        shade, texture = _lighting(lit, wall, box, 1.0)
        self.assertGreater(shade, 1.2, "la flaque des phares éclaircit")
        self.assertGreater(texture, 0.9, "et laisse le dessin intact")

        # Une carrosserie : une surface à elle, qui cache le mur. Le nombre rendu
        # est une part — celle de la tache où le décor se voit encore — et il
        # doit donc suivre ce que l'objet couvre, ni plus ni moins.
        plein = wall.copy()
        plein[:] = 80
        shade, texture = _lighting(plein, wall, box, 1.0)
        self.assertEqual(texture, 0.0, "une chose qui remplit la boîte ne laisse rien voir")

        moitie = wall.copy()
        moitie[:, :45] = 80
        shade, texture = _lighting(moitie, wall, box, 1.0)
        self.assertAlmostEqual(texture, 0.5, delta=0.1,
                               msg=f"la moitié cachée devrait rendre une moitié, or {texture:.2f}")

    def test_the_measure_survives_the_shrink_the_watcher_really_does(self):
        """La même mesure, mais par le vrai chemin, sur une image pleine taille.

        Le mouvement est cherché sur une image réduite et les boîtes en
        ressortent aux dimensions d'origine : entre les deux il y a un facteur,
        et se tromper de sens le fait lire à côté de la tache. L'épreuve à
        l'échelle un ne dit rien de cela, celle-ci si.
        """
        rng = np.random.default_rng(11)
        # Un grain à la taille des pierres, pas du bruit pixel à pixel : ce
        # dernier ne survit pas à la réduction, et ne ressemble à rien de ce
        # que cette caméra regarde.
        coarse = rng.integers(70, 180, size=(108, 192, 3), dtype=np.uint8)
        wall = cv2.resize(coarse, (1920, 1080), interpolation=cv2.INTER_NEAREST)
        detector = MotionDetector(ZONES, motion_width=640, min_track_frames=2, warmup_frames=4)
        for index in range(8):
            detector.step(wall, index)
        # Une ombre traverse : le même mur, en plus sombre, et rien d'autre.
        seen = []
        for index in range(4):
            frame = wall.copy()
            left = 500 + index * 90
            patch = frame[400:700, left:left + 300].astype(np.float32) * 0.5
            frame[400:700, left:left + 300] = patch.astype(np.uint8)
            detector.step(frame, 20 + index)
            seen.extend((track.shade, track.texture) for track in detector.tracks)

        self.assertTrue(seen, "l'ombre devrait faire au moins une tache")
        shade, texture = min(seen, key=lambda pair: pair[0])
        self.assertLess(shade, 0.8, f"l'ombre devrait assombrir, or {shade:.2f}")
        self.assertGreater(texture, 0.8, f"le mur devrait survivre, or {texture:.2f}")

    def test_a_flat_background_cannot_answer_the_question(self):
        """Sans grain, rien ne distingue une ombre d'un objet mat.

        Dit plutôt que caché : la mesure rend zéro, ce qui veut dire « je ne
        sais pas », et non une fausse certitude.
        """
        from watcher.motion import _lighting

        plain = np.full((40, 40, 3), 120, dtype=np.uint8)
        darker = np.full((40, 40, 3), 70, dtype=np.uint8)
        shade, texture = _lighting(darker, plain, (0.0, 0.0, 40.0, 40.0), 1.0)
        self.assertLess(shade, 0.7)
        self.assertEqual(texture, 0.0)

    def test_the_headlight_pool_and_the_car_do_not_read_alike(self):
        """Le cas du 29 septembre, posé sur la mesure qui doit le trancher.

        À 02 h 51 le rectangle est allé sur l'îlot éclairé et non sur la
        voiture : le faisceau qui balayait a fait quinze taches d'une image
        pendant que la piste durable se tenait sur le bitume qu'il éclairait.
        La lumière n'a pourtant pas caché le bitume — son grain est toujours
        là, en plus clair — tandis que la carrosserie, elle, le cache.

        Les deux sont donc dessinés sur le même décor, l'un après l'autre, et
        passés par le vrai détecteur. Aucun seuil n'est posé ici : ce qui est
        éprouvé, c'est que les deux ne se ressemblent pas.
        """
        from watcher.simulate import beam, car, sensor_noise

        scene, run = _road_run(far_m=90.0, near_m=45.0, steps=7)
        rng = np.random.default_rng(3)
        # Du bitume de nuit : sombre, mais pas uni. Un fond sans grain rendrait
        # zéro, c'est-à-dire « je ne sais pas », et l'épreuve ne dirait rien.
        gros = rng.integers(26, 54, size=(108, 192, 3), dtype=np.uint8)
        nuit = cv2.resize(gros, (1920, 1080), interpolation=cv2.INTER_NEAREST)

        def lire(dessine):
            detecteur = MotionDetector(ZONES, motion_width=640, min_track_frames=2, warmup_frames=4)
            for index in range(8):
                detecteur.step(sensor_noise(nuit, seed=index), index)
            vus = []
            for index, spot in enumerate(run):
                image = dessine(sensor_noise(nuit, seed=40 + index), spot, index)
                detecteur.step(image, 20 + index)
                vus.extend((piste.shade, piste.texture) for piste in detecteur.tracks
                           if piste.texture != 0.0)
            return vus

        def ombre(fond, spot, index):
            """Un pan d'ombre qui traverse, comme celle d'un nuage.

            Local, pas global : une baisse de lumière sur toute l'image est
            déjà écartée plus haut, où plus de 35 % qui change vaut pour un
            changement de jour. Ce qui reste à nommer, c'est le bord d'ombre
            qui ne couvre qu'un morceau du décor.
            """
            out = fond.copy()
            gauche = int((0.2 + index * 0.06) * fond.shape[1])
            pan = out[400:700, gauche:gauche + 260].astype(np.float32) * 0.55
            out[400:700, gauche:gauche + 260] = pan.astype(np.uint8)
            return out

        flaque = lire(lambda fond, spot, index: beam(
            fond, spot, run[min(len(run) - 1, index + 3)], scene.share_per_metre(*spot)))
        carrosserie = lire(lambda fond, spot, index: car(
            fond, spot, scene.share_per_metre(*spot), body=70))
        pan = lire(ombre)

        self.assertTrue(flaque, "la flaque devrait faire au moins une tache")
        self.assertTrue(carrosserie, "la voiture devrait faire au moins une tache")
        self.assertTrue(pan, "l'ombre devrait faire au moins une tache")

        # L'ombre assombrit sans rien cacher : c'est le cas franc, et celui qui
        # pèse le plus lourd dans les 7 607 refus d'une journée.
        self.assertLess(min(couple[0] for couple in pan), 0.8)
        self.assertGreater(max(couple[1] for couple in pan), 0.85,
                           "une ombre ne cache pas le décor qu'elle traverse")

        # La flaque est le cas dur : le faisceau a son propre dégradé, très
        # fort, et il crame le bitume en son cœur. Elle en garde tout de même
        # nettement plus que la carrosserie, qui bouche ce qu'il y a derrière.
        garde = max(couple[1] for couple in flaque)
        cache = min(couple[1] for couple in carrosserie)
        self.assertGreater(garde, cache + 0.25,
                           f"lumière {garde:.2f} et carrosserie {cache:.2f} se ressemblent trop")

    def test_a_car_coming_towards_us_is_not_called_almost_still(self):
        """The fault of 29 September at 02:51, put in front of the watcher.

        A car arrives head-on at the roundabout with its headlights on. It was
        left unnamed and the rectangle went to the pool of light its own lamps
        threw on the tarmac; the close-up kept beside the entry holds no car at
        all.

        Built from the scene map rather than from this framing: the car is
        drawn at its true 1.8 m on ground the map says is road, from 110 m
        down to 40 m, which on this camera is nineteen pixels wide growing to
        fifty-five. What it settles is that an approach here does travel — 0.08
        of the picture, well past the threshold — so being taken for still is
        not what an approach costs on this road. Its growth, three and a half
        times, is the half of the movement nothing was writing down.
        """
        scene, road = _road_run()
        frames, boxes = _approach(scene, road)
        detector = MotionDetector(ZONES, motion_width=640, min_track_frames=3, warmup_frames=4)
        for index in range(6):
            detector.step(frames[0], index)
        ended = []
        for index, frame in enumerate(frames):
            ended.extend(detector.step(frame, 20 + index).ended)
        # The car leaves: a track only closes once the thing has gone.
        for index, empty in enumerate(_empty_road(4)):
            ended.extend(detector.step(empty, 60 + index).ended)

        self.assertTrue(ended, "rien n'a été suivi du tout")
        track = max(ended, key=lambda item: item.frames)
        # What the fault looks like in numbers, and why travel cannot see it.
        self.assertLess(track.travel, 0.1, "une voiture de face ne traverse pas l'image")
        self.assertGreater(track.area_grow, 1.5, "elle grossit, et c'est là qu'est le mouvement")

    def test_the_rectangle_lands_on_the_car_and_not_on_its_light(self):
        """The pool of light is the bigger shape; the car is the true one.

        This passes today, and it is worth saying that it does not yet stand
        for the fault of 29 September. Drawn here, the lit tarmac merges with
        the car into one blob twice its size and the rectangle still holds
        three quarters of it. On the real roundabout the beams swept far wider
        and the rectangle landed hundreds of pixels away. The test guards what
        it shows — a car kept, not swapped for its own light — and the harder
        case needs the sweep itself, which is not drawn here.
        """
        scene, road = _road_run()
        frames, boxes = _approach(scene, road)
        detector = MotionDetector(ZONES, motion_width=640, min_track_frames=3, warmup_frames=4)
        for index in range(6):
            detector.step(frames[0], index)
        ended = []
        for index, frame in enumerate(frames):
            ended.extend(detector.step(frames[index], 20 + index).ended)
        # The car leaves: a track only closes once the thing has gone.
        for index, empty in enumerate(_empty_road(4)):
            ended.extend(detector.step(empty, 60 + index).ended)
        self.assertTrue(ended)
        track = max(ended, key=lambda item: item.frames)
        height, width = frames[0].shape[:2]
        x, y, w, h = track.best_bbox
        drawn = (x / width, y / height, w / width, h / height)
        self.assertGreater(_share_of(drawn, boxes[-1]), 0.25,
                           f"le rectangle {drawn} ne tient pas la voiture {boxes[-1]}")

    def test_a_name_the_model_did_not_give_is_not_autonomous(self):
        """Only what the model read itself counts as recognition.

        A name reached another way — ground size, a coach timetable, the glare
        of headlights — can be right and still prove nothing about the
        recognition, which is the thing that has to be sure before anything is
        shown. Answered on the surest reading and not on the whole list:
        publishing "Voiture" while the best reading says person is a choice
        made against the model, and eight entries of the history are that.
        """
        from watcher.naming import named_itself

        car = Detection(cls="car", conf=0.62)
        walker = Detection(cls="person", conf=0.71)
        self.assertTrue(named_itself("vehicle", [car]))
        self.assertFalse(named_itself("vehicle", [walker, car]))
        self.assertTrue(named_itself("person", [walker, car]))
        self.assertFalse(named_itself("vehicle", []))
        # A fire or an aircraft is never named by this model.
        self.assertFalse(named_itself("fire", [car]))

    def test_the_score_counts_a_corrected_entry_as_a_fault(self):
        """The gate before the site goes out is a rate, so it must not flatter.

        A corrected entry carries the right word today and was wrong when it
        was published. Counting it as right would turn fifty-two hand
        corrections into a score of 53 out of 54, which measures the correcting
        rather than the watching. The honest figure is one.
        """
        root = Path(__file__).resolve().parents[1]
        events = [event for event in json.loads(
            (root / "data" / "events.json").read_text(encoding="utf-8"))["events"]
            if not (event.get("detail") or {}).get("simulation")]
        read = [event for event in events if event.get("review")]
        right = [event for event in read if event.get("review") == "accepted"
                 and not (event.get("detail") or {}).get("correction")]
        self.assertGreater(len(read), 10, "trop peu de relectures pour juger")
        self.assertLess(len(right), len(read), "aucune faute comptée : le score flatte")
        script = (root / "site" / "app.js").read_text(encoding="utf-8")
        self.assertIn('!(event.detail || {}).correction', script)

    def test_a_wrong_reading_stays_in_the_history(self):
        """Struck through rather than removed.

        A fault taken off the page cannot be counted, and the aim is a pipeline
        that is never wrong — which is proved by a rate, not by a selection.
        """
        root = Path(__file__).resolve().parents[1]
        script = (root / "site" / "app.js").read_text(encoding="utf-8")
        self.assertIn('event.review === "rejected" ? \' class="wrong"\' : ""', script)
        style = (root / "site" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("tr.wrong", style)

    def test_what_hides_itself_stays_hidden_once_given_a_display(self):
        """Poser « display » sur un identifiant annule l'attribut « hidden ».

        La règle du navigateur, « [hidden] { display: none } », ne pèse presque
        rien : le moindre sélecteur d'identifiant la bat. Un élément qui se
        cache en JavaScript et à qui l'on donne un jour un « display » pour le
        mettre en page s'ouvre alors une fois et ne se referme plus, alors que
        le code, lui, fait exactement ce qu'on lui demande. C'est arrivé à la
        loupe le jour où elle est passée en flex pour loger la découpe à côté
        du cadre ; le test d'alors lisait la propriété « hidden », c'est-à-dire
        l'intention, et non le style calculé, c'est-à-dire l'écran.

        La règle vaut pour les treize éléments que la page écrit déjà cachés,
        et non pour le seul qui a fauté.
        """
        root = Path(__file__).resolve().parents[1]
        page = (root / "site" / "index.html").read_text(encoding="utf-8")
        style = (root / "site" / "styles.css").read_text(encoding="utf-8")
        caches = set(re.findall(r'id="([\w-]+)"[^>]*\shidden[\s>]', page))
        self.assertGreater(len(caches), 5, "plus personne ne se cache : le test ne garde plus rien")
        fautifs = []
        for nom in sorted(caches):
            # Une règle qui pose « display » sur cet identifiant, sans être
            # elle-même la règle du cas caché.
            pose = re.search(r"#%s\b(?![^{,]*\[hidden\])[^{]*\{[^}]*\bdisplay\s*:" % re.escape(nom), style)
            if pose and not re.search(r"#%s\[hidden\][^{]*\{[^}]*display\s*:\s*none" % re.escape(nom), style):
                fautifs.append(nom)
        self.assertEqual(fautifs, [], "ces éléments ont un « display » qui écrase leur « hidden » : "
                                      + ", ".join(fautifs))

    def test_what_was_thrown_away_keeps_its_rare_motives(self):
        """Un échantillon par motif, pas un échantillon en bloc.

        Quarante-neuf mille refus pour quatre cent dix-huit publications : tout
        garder ferait cent cinquante mégaoctets de vignettes par jour. Mais le
        renseignement est dans la variété des motifs et non dans leur nombre —
        six mille « rien de reconnu » disent ce que dit le premier. Pris en
        bloc, les motifs qui reviennent toutes les secondes mangeraient la place
        des rares, et ce sont justement les rares qui ont des chances d'être des
        fautes : « panache de nuit » n'est arrivé qu'une fois en cinquante mille.
        """
        from watcher.main import _worth_keeping

        cfg = {"sample_refused_s": 600}
        vus, instant = {}, 1000.0
        self.assertTrue(_worth_keeping("tarmac", cfg, vus, instant))
        # Le motif bavard est muselé jusqu'à la prochaine fenêtre...
        self.assertFalse(_worth_keeping("tarmac", cfg, vus, instant + 5))
        # ...mais il n'a pas pris la place du motif rare arrivé juste après.
        self.assertTrue(_worth_keeping("night_plume", cfg, vus, instant + 5))
        self.assertTrue(_worth_keeping("tarmac", cfg, vus, instant + 601))

        # Et on doit pouvoir tout couper d'un seul réglage.
        self.assertFalse(_worth_keeping("tarmac", {"sample_refused_s": 0}, {}, instant))

    def test_a_refused_patch_never_takes_a_published_reading_s_place(self):
        """Un refus ne rejoint aucun passage.

        Les entrées voisines d'une même zone sont regroupées en un passage, et
        la meilleure lecture l'emporte. Une tache écartée tombant dans la même
        minute qu'une voiture y serait versée comme les autres : l'historique
        publié dirait « rien de reconnu » là où il disait « voiture ».
        """
        from watcher.store import open_passage

        voiture = {"id": "a", "t": "2026-09-29T08:00:00Z", "type": "vehicle",
                   "label": "Voiture", "zone": "road"}
        ecartee = {"id": "b", "t": "2026-09-29T08:00:20Z", "type": "missed",
                   "label": "Rien de reconnu", "zone": "road"}
        self.assertIsNone(open_passage([voiture], ecartee),
                          "un refus ne doit rejoindre aucun passage")
        autre = {"id": "c", "t": "2026-09-29T08:00:30Z", "type": "vehicle",
                 "label": "Voiture", "zone": "road"}
        self.assertIsNone(open_passage([ecartee], autre),
                          "et n'en doit héberger aucun")
        # La règle ne vaut que pour les refus : deux vraies lectures voisines se
        # regroupent toujours, sans quoi chaque voiture ferait trois lignes.
        self.assertIsNotNone(open_passage([voiture], autre))

    def test_a_miss_is_asked_what_was_missed(self):
        """La question change de sens sur une tache écartée.

        Sur une publication, démentir veut dire « ce n'était pas cela ». Sur un
        refus, cela veut dire « il n'y avait rien », donc que le refus avait
        raison. Le même bouton, deux phrases opposées.
        """
        root = Path(__file__).resolve().parents[1]
        script = (root / "site" / "app.js").read_text(encoding="utf-8")
        self.assertIn('const deny = event.type === "missed" ? "nothing" : "wrong";', script)
        for mot in ('nothing: "Nothing there"', 'nothing: "Rien"'):
            self.assertIn(mot, script)
        # Et chaque motif de refus doit avoir ses mots dans les deux langues,
        # sans quoi un relecteur anglais lirait « against_the_ground ».
        from watcher.naming import REFUSAL_WORDS
        connus = set(re.findall(r'^  "(.+?)": ', script, re.M))
        absents = sorted(set(REFUSAL_WORDS.values()) - connus)
        self.assertFalse(absents, f"sans traduction : {absents}")

    def test_a_decision_can_be_lived_through_again(self):
        """Une observation doit survivre à l'aller-retour par le disque.

        C'est la condition de tout le reste : sans elle un verdict dit qu'on
        s'est trompé sans permettre de le revivre, et « on affine tant qu'il y
        a des erreurs » n'a pas de prise. Ce qui est publié n'y suffit pas —
        c'est un résumé, où manquent les détections, la chaleur et la montée du
        pied, c'est-à-dire ce sur quoi la décision s'est appuyée.
        """
        from watcher.naming import Trip, read_observation, write_observation

        obs = Observation(
            zone="road", surface="road", travel=0.061, area_ratio=0.0042, duration_s=6.0,
            frames=7, width_m=4.2, height_m=1.6, period="day", weather="ciel dégagé",
            warm_ratio=0.03, rise_ms=0.4, foot_climb=-0.002, colour="grise",
            detections=[Detection(cls="car", conf=0.71, cx=0.4, cy=0.8, box=(1, 2, 3, 4), share=0.9)],
            trips=[Trip(route="10", headsign="Malaucène", stop_name="Mont Serein",
                        scheduled="14:02", source="ZOU")],
            aircraft=[{"icao24": "abc", "callsign": "AFR1"}],
        )
        rendu = read_observation(json.loads(json.dumps(write_observation(obs))))

        avant, apres = decide(obs), decide(rendu)
        self.assertEqual((avant.type, avant.label, avant.reason),
                         (apres.type, apres.label, apres.reason))
        # Et pas seulement le verdict : les entrées elles-mêmes, sans quoi deux
        # chemins différents pourraient tomber par hasard sur le même mot.
        self.assertEqual(rendu.detections[0].cls, "car")
        self.assertEqual(rendu.detections[0].share, 0.9)
        self.assertEqual(rendu.trips[0].route, "10")
        self.assertEqual(rendu.aircraft[0]["callsign"], "AFR1")
        self.assertEqual(rendu.warm_ratio, 0.03)
        self.assertEqual(rendu.foot_climb, -0.002)

    # Ce que le code dit encore autrement qu'un humain qui a regardé la photo.
    # Chaque ligne est une dette, avec la raison pour laquelle elle n'est pas
    # payée. Elles ont été relevées le 30 septembre 2026.
    DESACCORDS_CONNUS = [
        # Un fourgon blanc. Le modèle avait dit « camion » à 0,42, et la règle
        # exige plus de 5,5 m au sol pour accorder le mot. Le seuil n'est pas
        # déplacé, et ce n'est pas un oubli : sur les quinze lectures « camion »
        # que cette règle a rétrogradées en « voiture », quatorze étaient bien
        # des voitures. La déplacer publierait dix voitures en camions pour en
        # rattraper quatre. Les mesures ne séparent pas les deux familles — une
        # berline de la planche fait 4,4 × 2,9 m et ce fourgon 4,7 × 2,7 —, donc
        # la réparation est en amont, dans la tache de mouvement, pas ici.
        # Trois fois le même défaut, et c'est maintenant le premier de la
        # liste : la porte entre « Voiture » et « Camion » est une largeur de
        # 5,5 m, mesurée sur une tache que l'ombre gonfle et que le bord du
        # cadre coupe. Elle avait raison quatorze fois sur quinze ; à trois
        # fautes du même genre, ce n'est plus du bruit, c'est une règle à
        # refaire — sur la mesure, pas sur le seuil.
        "2026-09-29T14-59-32Z-motion-222 : attendu 'Camion', obtenu 'Voiture'",
        "2026-09-30T08-40-56Z-vehicle-126 : attendu 'Camion', obtenu 'Voiture'",
        "2026-09-30T15-41-10Z-vehicle-287 : attendu 'Camion', obtenu 'Voiture'",
        # Quatrième fois. La règle de la largeur au sol reste en place et
        # continue de coûter : tant qu'elle n'est pas refaite sur la mesure,
        # chaque camion jugé par un humain vient grossir cette liste.
        "2026-10-01T12-48-39Z-vehicle-95 : attendu 'Camion', obtenu 'Voiture'",
        # Un piéton lu comme une voiture.
        # Était « Voiture », un faux nom tiré d'une lecture qui ne recouvrait
        # rien de ce qui bougeait. La règle du recouvrement nul l'a ramené à un
        # refus : toujours en désaccord avec le verdict, puisqu'on attendait
        # « Piéton », mais d'un désaccord d'une autre nature. Une machine qui
        # dit « je ne sais pas » se corrige ; une machine qui dit « Voiture »
        # pour avoir regardé ailleurs ne se corrige pas, elle a raison par
        # accident jusqu'au jour où elle a tort de la même façon.
        "2026-09-29T10-57-18Z-motion-94 : attendu 'Piéton', obtenu 'Mouvement détecté'",
        # Un tracteur lu comme un camion : le modèle n'a pas la classe.
        "2026-09-29T07-56-22Z-motion-10 : attendu 'Tracteur', obtenu 'Camion'",
        # Un camion refusé pour sa taille. C'est le même défaut que les trois
        # premiers, pris par l'autre bout : là ils rétrogradaient un camion en
        # voiture, ici la tache est si petite que la règle écarte le véhicule
        # tout entier. Les deux disent la même chose — la tache de mouvement
        # n'est pas la forme de ce qui a bougé — et les deux se répareront au
        # même endroit.
        "2026-09-30T12-56-22Z-person-225 : attendu 'Camion', obtenu "
        "'Trop petit pour un véhicule'",
    ]

    def test_every_mistake_already_paid_for_stays_fixed(self):
        """Chaque faute corrigée devient une épreuve, et le reste.

        Le verdict humain dit ce qu'il y avait ; l'observation gardée dit ce que
        la veille avait sous les yeux. Les marier et repasser par decide()
        demande à aujourd'hui de faire mieux qu'hier sur un cas réel — pas sur
        une scène dessinée pour l'occasion.

        Le compte part de zéro et grandit avec les relectures. Il vaut mieux
        qu'il le dise que de passer en silence : une épreuve qui ne vérifie rien
        doit avoir l'honnêteté de l'annoncer.
        """
        from watcher.naming import read_observation

        root = Path(__file__).resolve().parents[1]
        vus = {}
        chemin = root / "data" / "observed.jsonl"
        if chemin.is_file():
            for ligne in chemin.read_text(encoding="utf-8").splitlines():
                if ligne.strip():
                    row = json.loads(ligne)
                    vus[row["id"]] = row

        evenements = json.loads((root / "data/events.json").read_text(encoding="utf-8"))["events"]
        fautes = []
        rejoues = 0
        for entree in evenements:
            garde = vus.get(entree.get("id"))
            # Seulement ce qui a été tranché, et seulement ce dont on a gardé
            # l'observation. Une entrée non relue n'a pas de vérité à opposer.
            if not garde or entree.get("review") != "accepted":
                continue
            # Et pas ce que la mémoire du cadrage a repris après coup : son
            # verdict tient à un compteur par cellule qui n'est pas dans
            # l'observation, et decide() seul ne peut pas le retrouver. Le
            # verdict humain reste utile sur ces taches — il dit que la règle
            # d'habitude se trompe à cet endroit — mais ailleurs qu'ici.
            if garde.get("habit"):
                continue
            rejoues += 1
            dit = decide(read_observation(garde["seen"] if "seen" in garde else garde))
            attendu = entree.get("label", "")
            # La couleur ne fait pas la classe. Relire « Voiture rouge » quand
            # un humain a écrit « Voiture » n'est pas une faute : c'est la même
            # chose, dite avec un mot de plus. Compté comme désaccord, cela
            # remplirait la liste de fautes qui n'en sont pas et finirait par
            # noyer les vraies — un camion lu comme une voiture, lui, compte.
            if _meme_chose(dit.label, attendu):
                continue
            if dit.label != attendu:
                fautes.append(f"{entree['id']} : attendu {attendu!r}, obtenu {dit.label!r}")

        if not rejoues:
            self.skipTest("aucune relecture n'a encore d'observation gardée : "
                          "le compte part de zéro et grandit avec les verdicts")
        # Trois désaccords sont connus, datés et non corrigés. Les taire serait
        # mentir ; laisser l'épreuve rouge pour toujours la rendrait muette.
        # On les nomme donc un par un : une faute nouvelle fait tomber le test,
        # et une faute réparée aussi, pour qu'on pense à la rayer d'ici.
        self.assertEqual(sorted(fautes), sorted(self.DESACCORDS_CONNUS),
                         "la liste des désaccords connus ne correspond plus :\n  "
                         + "\n  ".join(fautes))

    def test_the_site_claims_no_more_than_the_checks_allow(self):
        """Douze justes sur douze ne font pas cent pour cent.

        La page doit écrire ce qu'on a le droit d'affirmer, pas ce qu'on a
        compté. Sans faute, la borne basse exacte du taux vaut 0,05^(1/n) : le
        taux le plus mauvais qui aurait tout de même une chance sur vingt de
        passer n tirages sans se faire prendre. Elle franchit 0,95 à
        cinquante-neuf, et c'est de là que vient la constante du script.
        """
        root = Path(__file__).resolve().parents[1]
        script = (root / "site" / "app.js").read_text(encoding="utf-8")
        found = re.search(r"const CLEAN_RUN = (\d+);", script)
        self.assertIsNotNone(found, "le nombre de contrôles à blanc n'est plus déclaré")
        voulu = math.ceil(math.log(0.05) / math.log(0.95))
        self.assertEqual(int(found.group(1)), voulu,
                         f"0,05^(1/n) passe 0,95 à {voulu}, pas à {found.group(1)}")
        self.assertGreaterEqual(0.05 ** (1 / voulu), 0.95)
        self.assertLess(0.05 ** (1 / (voulu - 1)), 0.95)
        # Et le tirage doit être un tirage : trier par date mettrait tout le
        # contrôle sur une journée, et choisir mesurerait nos préférences.
        self.assertIn("function scramble(id)", script)
        self.assertIn("scramble(one.id) - scramble(other.id)", script)

    def test_a_verdict_carries_its_lesson_all_the_way_home(self):
        """La ligne d'apprentissage doit survivre au trajet.

        apply_review l'écrit dans data/reviewed.jsonl, mais le workflow ne
        versait que events.json et learning.json : la ligne était produite puis
        abandonnée sur le coureur, et chaque relecture retombait à un compteur.
        Or c'est elle qui porte le mot juste avec la mesure de la tache, donc
        tout ce à partir de quoi un seuil peut se régler.
        """
        root = Path(__file__).resolve().parents[1]
        flux = (root / ".github/workflows/review.yml").read_text(encoding="utf-8")
        self.assertIn("data/reviewed.jsonl", flux)
        publie = (root / "watcher/publish.py").read_text(encoding="utf-8")
        self.assertIn("data/reviewed.jsonl", publie)

    def test_sharpening_a_vague_reading_is_not_calling_it_wrong(self):
        """« Véhicule » pour une voiture est flou, pas faux.

        La page à trancher propose maintenant les cinq mots sur chaque carte,
        et confirmer « voiture » sur un « véhicule » est devenu le geste le plus
        courant. Le marquer comme une correction ferait chuter le taux de
        justesse à chaque fois qu'on précise une lecture prudente : le taux
        mesurerait alors notre zèle plutôt que la veille.
        """
        from watcher.review import apply_review

        def juge(publie, mot):
            entree = {"id": "x", "type": "vehicle", "label": publie, "detail": {}}
            apply_review([entree], {}, "x", "accepted", mot)
            return (entree.get("detail") or {}).get("correction")

        self.assertIsNone(juge("Véhicule", "voiture"), "affiner n'est pas démentir")
        self.assertIsNone(juge("Mouvement détecté", "voiture"))
        self.assertIsNone(juge("Voiture", "voiture"))
        self.assertIsNone(juge("Voiture grise", "voiture"), "la couleur reste une voiture")
        self.assertEqual(juge("Voiture", "camion"), "Camion", "nommer autre chose est une faute")
        self.assertEqual(juge("Voiture", "pieton"), "Piéton")

        # Et le mot juste doit arriver sur l'entrée dans tous les cas : c'est
        # lui qui part dans data/reviewed.jsonl avec la mesure de la tache.
        entree = {"id": "x", "type": "vehicle", "label": "Véhicule", "detail": {}}
        lecons = []
        apply_review([entree], {}, "x", "accepted", "voiture", lecons)
        self.assertEqual(entree["label"], "Voiture")
        self.assertEqual(lecons[0]["truth"], "Voiture")
        self.assertEqual(lecons[0]["guessed"], "Véhicule")

    def test_the_history_only_keeps_what_the_model_read_by_itself(self):
        """La coupure entre ce qui est publié et ce qui attend un avis.

        Un nom trouvé par une règle de rattrapage — c'est long comme un bus,
        donc c'est un bus — dit ce que la règle savait déjà, pas ce que la
        veille a reconnu. Sur les 54 lectures relues jusqu'ici, les 53 démenties
        sont toutes de cette sorte-là, et la seule juste du premier coup est du
        côté où le modèle a lu seul. C'est la raison d'être de la coupure, et si
        elle venait à s'inverser cette épreuve doit tomber.
        """
        root = Path(__file__).resolve().parents[1]
        evenements = json.loads((root / "data/events.json").read_text(encoding="utf-8"))["events"]
        seul = [e for e in evenements if (e.get("detail") or {}).get("autonomous") is True]
        reste = [e for e in evenements if (e.get("detail") or {}).get("autonomous") is not True]

        def fautes(groupe):
            return [e for e in groupe if e.get("review") == "rejected"
                    or (e.get("review") and (e.get("detail") or {}).get("correction"))]

        self.assertTrue(seul and reste, "il faut des deux côtés pour juger la coupure")
        self.assertGreater(len(fautes(reste)), len(fautes(seul)),
                           "la coupure ne trie plus rien : les fautes sont des deux côtés")

        script = (root / "site" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function namedItself(event)", script)
        self.assertIn("events.filter(namedItself)", script)
        # Le score et les graphiques portent sur ce qui est publié, sinon ils
        # mesureraient la file d'attente plutôt que la veille.
        for bloc in ("function paintScore()", "function paintFigures()"):
            depuis = script.index(bloc)
            corps = script[depuis:depuis + 1400]
            self.assertIn("namedItself(event)", corps, bloc)
            self.assertNotIn("!namedItself", corps, bloc)

    def test_everything_not_read_by_the_model_lands_on_the_judging_page(self):
        """Rien ne doit tomber entre les deux.

        Une entrée qui quitte l'historique sans arriver ici serait perdue pour
        la relecture, et c'est justement d'elles qu'on apprend.
        """
        root = Path(__file__).resolve().parents[1]
        script = (root / "site" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function paintDoubt()", script)
        self.assertIn("events.filter((event) => !namedItself(event)", script)
        # Les boutons existaient depuis la première relecture sans être posés
        # nulle part : c'est la page à trancher qui les met enfin au travail.
        self.assertIn("reviewControls(event, { naming: true })", script)
        # Les cinq mots sont ceux du sol : proposer « voiture » sous un avion
        # n'offrirait au relecteur aucune réponse vraie.
        self.assertIn('const ground = event.type !== "plane";', script)
        page = (root / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="doubt-list"', page)
        self.assertIn('href="#doubt"', page)

    def test_the_map_draws_the_aim_that_was_measured(self):
        """The cone on the map said 140° while the fit said 126,7°.

        Thirteen degrees off, and stopping at a quarter of the range. The page
        reads config/scene.json now; the numbers left in the script are only
        what it falls back on, and they must not drift from the fit.
        """
        root = Path(__file__).resolve().parents[1]
        pose = json.loads((root / "config" / "scene.json").read_text(encoding="utf-8"))["pose"]
        script = (root / "site" / "app.js").read_text(encoding="utf-8")
        fallback = re.search(r"const AIM_FALLBACK = \{([^}]+)\}", script).group(1)
        for key, value in (("yaw", pose["yaw"]), ("hfov", pose["hfov"]), ("reach", pose["reach_m"])):
            found = re.search(rf"{key}: ([\d.]+)", fallback)
            self.assertIsNotNone(found, key)
            self.assertAlmostEqual(float(found.group(1)), value, places=2, msg=key)
        self.assertNotIn("VIEW_ANGLE", script)

    def test_every_landmark_falls_inside_the_cone_the_map_draws(self):
        """They are all visible in the picture, so all must be in the cone.

        The hand-written one held three of the nineteen: it was aimed thirteen
        degrees off and stopped at 600 m, while the furthest landmark the
        camera reads is the Tom Simpson memorial at 2447 m.
        """
        root = Path(__file__).resolve().parents[1]
        scene = json.loads((root / "config" / "scene.json").read_text(encoding="utf-8"))
        pose, marks = scene["pose"], scene["landmarks"]
        self.assertGreater(len(marks), 10)
        for mark in marks:
            # x is where the landmark sits across the picture, so its bearing
            # off the axis is that offset times the field.
            off = (mark["x"] - 0.5) * pose["hfov"]
            self.assertLessEqual(abs(off), pose["hfov"] / 2, mark["name"])
            self.assertLessEqual(mark["distance_m"], pose["reach_m"], mark["name"])

    def test_the_heading_is_counted_the_way_openstreetmap_counts_it(self):
        """Degrees clockwise from true north, so camera:direction can take it.

        Checked on the geometry itself rather than on a number copied out of
        the fit: a yaw of zero must look due north, ninety due east.
        """
        from watcher.frustum import Pose, axes

        for yaw, east, north in ((0.0, 0.0, 1.0), (90.0, 1.0, 0.0), (180.0, 0.0, -1.0)):
            _, forward, _ = axes(Pose(lat=44.18, lon=5.26, ele=1390.0, yaw=yaw, pitch=0.0, hfov=78.0))
            self.assertAlmostEqual(forward[0], east, places=6, msg=f"{yaw}° est")
            self.assertAlmostEqual(forward[1], north, places=6, msg=f"{yaw}° nord")

    def test_the_history_says_which_watcher_wrote_it(self):
        """The footer read v0.3.0 while the code called itself 0.1.0.

        Written in three places by hand, it drifted in all three. From the day
        the Mac and the Pi both publish, the page must say which one it is
        showing.
        """
        import watcher
        from watcher.store import Store

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = Store(root)
            store._write()
            payload = json.loads((root / "events.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], watcher.__version__)
        page = (Path(__file__).resolve().parents[1] / "site" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="version"></span>', page)

    def test_a_correction_keeps_the_measurements_that_caused_it(self):
        """A verdict must leave more than a tally behind.

        Counting how often we are wrong says nothing about why. The reading
        that produced the mistake, married to the human's word, is the only
        thing that can move a threshold on evidence.
        """
        event = {
            "id": "m1", "at": "2026-09-28T12:52:16Z", "type": "motion",
            "label": "Mouvement détecté", "zone": "road", "photo": "thumbs/m1.jpg",
            "detail": {"measured": {"width_m": 2.1, "rise_ms": 0.4, "seen_as": []}},
        }
        lessons: list = []
        self.assertTrue(apply_review([event], {}, "m1", "accepted", "velo", lessons))
        self.assertEqual(len(lessons), 1)
        row = lessons[0]
        self.assertEqual((row["truth"], row["guessed"]), ("Vélo", "Mouvement détecté"))
        self.assertEqual(row["measured"]["width_m"], 2.1)
        self.assertEqual(row["photo"], "thumbs/m1.jpg")

    def test_a_rejection_is_kept_as_well(self):
        # Knowing a shape is not a car is worth as much as knowing it is.
        event = {"id": "m2", "label": "Voiture", "detail": {"measured": {"width_m": 9.0}}}
        lessons: list = []
        self.assertTrue(apply_review([event], {}, "m2", "rejected", "", lessons))
        self.assertEqual(lessons[0]["verdict"], "rejected")
        self.assertEqual(lessons[0]["guessed"], "Voiture")
        self.assertEqual(lessons[0]["truth"], "")

    def test_an_unnamed_crossing_goes_to_review_once_every_five_minutes(self):
        """The one exception to keeping unnamed motion off the page.

        Twenty-six things crossed the road in the hour of 28 September when
        nothing was published, and the model returned no class at all for
        twenty-five of them. They are what there is to learn from, and they
        left no photograph behind.
        """
        from watcher.main import _worth_reviewing

        cfg = {"review_unnamed_s": 300}
        crossing = Decision("publish", "motion", "Mouvement détecté", "unnamed_vehicle", {}, 0.3)
        seen: dict = {}
        self.assertTrue(_worth_reviewing(crossing, cfg, seen, 1_000.0))
        seen["unnamed"] = 1_000.0
        self.assertFalse(_worth_reviewing(crossing, cfg, seen, 1_200.0))
        self.assertTrue(_worth_reviewing(crossing, cfg, seen, 1_300.0))

    def test_only_the_crossings_are_reviewed_and_only_when_asked(self):
        from watcher.main import _worth_reviewing

        fog = Decision("publish", "motion", "Brouillard", "fog", {}, 0.3)
        crossing = Decision("publish", "motion", "Mouvement détecté", "unnamed_vehicle", {}, 0.3)
        self.assertFalse(_worth_reviewing(fog, {"review_unnamed_s": 300}, {}, 1_000.0))
        # Zero turns the queue off without touching the code.
        self.assertFalse(_worth_reviewing(crossing, {"review_unnamed_s": 0}, {}, 1_000.0))

    def test_a_reviewer_may_answer_with_what_really_passes_here(self):
        """Les mots doivent couvrir ce qui passe vraiment ici.

        « Tracteur » est arrivé le 29 septembre, sur une tache publiée comme
        voiture et qui n'en était pas une. Le modèle ne pourra jamais en nommer
        un — COCO n'a pas de tracteurs — mais sans le mot, le relecteur n'avait
        que « faux » à répondre, et la leçon se perdait.
        """
        from watcher.review import CLASSES

        self.assertEqual(
            {name for name, _ in CLASSES.values()} | set(CLASSES),
            {"vehicle", "bus", "person", "cycle",
             "voiture", "camion", "bus", "pieton", "velo", "tracteur"},
        )
        # Et le site doit proposer exactement les mêmes : un bouton sans classe
        # en face ouvrirait un ticket que rien ne saurait appliquer.
        root = Path(__file__).resolve().parents[1]
        script = (root / "site" / "app.js").read_text(encoding="utf-8")
        bloc = script[script.index("const REVIEW_CLASSES = ["):]
        bloc = bloc[:bloc.index("];")]
        self.assertEqual(set(re.findall(r'\["(\w+)",', bloc)), set(CLASSES))

    def test_nothing_burns_in_the_sky(self):
        cloud = Observation(zone="sky", surface="forest", period="day", width_m=8.0,
                            duration_s=14.5, travel=0.02, warm_ratio=0.0, smoke_ratio=0.399,
                            rise=0.0583, area_grow=14.95, fire_sustain_s=5.0, fire_grow=1.6,
                            fire_warm=0.08, fire_smoke=0.35, fire_rise=0.008)
        self.assertNotEqual(decide(cloud).type, "fire")

    def test_a_lorry_does_not_bring_the_watcher_down(self):
        """min_conf is a threshold per class, not a number.

        Compared whole it raises a TypeError, and the line is reached only when
        the model reads a bus or a truck: the watcher ran three days before the
        first lorry of 27 September found it.
        """
        from watcher.main import _might_be_bus

        class _Track:
            zone = "road"

        cfg = {"min_conf": {"bus": 0.45, "bus_unnamed": 0.6, "car": 0.4}}
        seen = [Detection("truck", 0.78)]
        self.assertTrue(_might_be_bus(_Track(), seen, 4.0, cfg))
        self.assertFalse(_might_be_bus(_Track(), [Detection("truck", 0.20)], 4.0, cfg))

    def test_the_ground_size_alone_never_names_a_vehicle(self):
        """Car-shaped on the ground is not enough, and this is the proof.

        Naming on ground size alone ran four hours on 27 September and
        published 128 vehicles; the ones that were checked were walkers,
        nearly all of them. Of the objects the model does confirm, vehicles
        run 2.13 wide for one high and people 1.13, and the two overlap past
        any cut: demanding a ratio of 4 and a height under two metres kept
        only 32 vehicles of 256 and still let 9 people through.
        """
        car = Observation(zone="roundabout", period="day", surface="road", travel=0.2112,
                          width_m=4.4, box_w=0.140, frames=4, detections=[])
        self.assertEqual(decide(car).type, "motion")
        self.assertEqual(decide(car).reason, "unnamed_vehicle")

    def test_a_flicker_of_one_frame_is_not_named_a_vehicle(self):
        blink = Observation(zone="road", period="day", surface="road", travel=0.2,
                            width_m=4.4, box_w=0.140, frames=1, detections=[])
        # "motion" is filed among the candidates and never reaches the site.
        self.assertEqual(decide(blink).type, "motion")
        self.assertEqual(decide(blink).reason, "unnamed_vehicle")

    def test_a_thing_of_unknown_size_is_not_named_by_its_size(self):
        # A width of zero is not a small car, it is a failure to measure.
        unknown = Observation(zone="road", period="day", surface="road", travel=0.2,
                              width_m=0.0, box_w=0.140, frames=9, detections=[])
        self.assertEqual(decide(unknown).type, "motion")
        self.assertEqual(decide(unknown).reason, "unnamed_vehicle")

    def test_something_far_too_long_for_a_car_is_not_named_one(self):
        # Fog banks that morning measured 11 m to 22 m across.
        bank = Observation(zone="road", period="day", surface="road", travel=0.2,
                           width_m=21.4, box_w=0.68, frames=9, detections=[])
        self.assertEqual(decide(bank).type, "motion")
        self.assertEqual(decide(bank).reason, "oversized")

    def test_a_bank_of_fog_on_the_slope_is_still_refused_by_day(self):
        # The same morning at 06:09, fog banks measured 11 m to 22 m across.
        # Nothing on that road is twenty metres long, so ground size turns them
        # away without any help from the fog rule.
        bank = Observation(zone="slope", period="day", surface="forest", travel=0.0134,
                           width_m=21.4, box_w=0.68, detections=[Detection("car", 0.55)],
                           fogged=True, hazy=True)
        self.assertFalse(decide(bank).publish)

    def test_the_same_ones_are_named_once_the_air_clears(self):
        walker = Observation(zone="roundabout", period="night", surface="road", travel=0.02,
                             box_w=0.070, detections=[Detection("person", 0.62)])
        self.assertEqual(decide(walker).type, "person")

    def test_a_haloed_lamp_in_haze_is_not_a_fire_either(self):
        # The first alarm of that night, at a ridge of 49: not yet fog, but
        # already not clear.
        called = decide(self._lamp(hazy=True))
        self.assertEqual(called.type, "motion")
        self.assertEqual(called.reason, "haze")

    def test_the_same_readings_in_clear_air_still_raise_the_alarm(self):
        # The fire rule itself is untouched: it is the bad air that is refused,
        # not the warmth.
        self.assertEqual(decide(self._lamp()).type, "fire")

    def test_a_plume_is_believed_even_through_haze(self):
        # Smoke climbing is the one thing haze cannot counterfeit, so a fire
        # that shows one is still named.
        real = self._lamp(hazy=True, smoke_ratio=0.42, rise=0.011)
        self.assertEqual(decide(real).type, "fire")

    def test_the_distance_grid_agrees_with_the_surveyed_landmarks(self):
        """Thirteen places whose distance is known, and the map must find them.

        Read at the foot of each landmark, where the ground is, and not at its
        middle: the camera sees the first hundred metres almost edge-on — the
        eye is at 1392 m and the ground at 1388 — so a metre and a half of
        height there is worth a hundred metres of distance. Measured at the
        middle the map looks 16 % out across the whole vehicle band; measured
        where the code actually reads it, the error is 5 %.
        """
        from watcher.scenemap import SceneMap

        carte = SceneMap.load(ROOT / "config" / "scene.json")
        ecarts = []
        for mark in carte.landmarks:
            releve = float(mark.get("distance_m") or 0)
            pied = carte.distance_at(min(0.999, mark["x"]), min(0.999, mark["y"] + mark["ry"]))
            if not (releve and pied):
                continue
            ecarts.append(abs(pied / releve - 1))
        self.assertGreaterEqual(len(ecarts), 10, "trop peu de repères relevés pour juger")
        ecarts.sort()
        self.assertLess(ecarts[len(ecarts) // 2], 0.10)

    def test_a_size_read_where_the_ground_is_unknown_is_not_used(self):
        """Where the distance is a guess, the size is one too, and it is dropped.

        The same shape, judged twice: once where the camera looks down on solid
        ground, once in the near field it sees edge-on. The first is refused
        for covering twenty-five metres, which nothing that rolls or walks can
        be. The second is not refused on that ground at all — not because the
        shape changed, but because there is no longer a measurement to refuse
        it with.
        """
        from watcher.naming import SIZE_DOUBT_MAX, Observation, decide

        large = dict(zone="road", travel=0.2, width_m=25.0, height_m=3.0, surface="road")
        sur = decide(Observation(**large, distance_doubt=0.0))
        self.assertEqual(sur.reason, "oversized")
        self.assertEqual(sur.label, "Tache trop large")

        doute = decide(Observation(**large, distance_doubt=SIZE_DOUBT_MAX + 0.01))
        self.assertNotEqual(doute.reason, "oversized")

        # La vitesse de montée s'en va avec, puisqu'elle se calcule sur cette
        # même distance. Le tracteur du 28 septembre n'est écarté que parce que
        # son panache monte à un demi-mètre par seconde là où une fumée portée
        # par sa chaleur en fait plusieurs. Mesuré sur un sol inconnu, ce
        # demi-mètre par seconde n'est plus une mesure, et l'écarter là-dessus
        # serait refuser un feu sur une preuve qu'on n'a pas. On penche donc du
        # côté où l'on se trompe en alertant, pas du côté où l'on se tait.
        tracteur = dict(zone="slope", period="day", width_m=7.0, duration_s=6.0,
                        travel=0.03, rise_ms=0.55, warm_ratio=0.0, smoke_ratio=0.426,
                        rise=0.0278, area_grow=2.8, fire_sustain_s=5.0, fire_grow=1.6,
                        fire_warm=0.08, fire_smoke=0.35, fire_rise=0.008)
        self.assertEqual(decide(Observation(**tracteur, distance_doubt=0.0)).reason, "machine")
        doute = decide(Observation(**tracteur, distance_doubt=0.5))
        self.assertNotEqual(doute.reason, "machine")
        self.assertEqual(doute.type, "fire")

    def test_the_map_says_where_its_distances_are_worthless(self):
        """Knowing a distance is not enough; one must know what it is worth.

        A distance is a height divided by an angle, so it is only as firm as
        the ground under it. The camera stands two metres up and looks at ground
        four to six metres below, so its first hundred metres are seen almost
        edge-on and three metres of doubt in the elevation model move the answer
        by half. Past two hundred and fifty the slope climbs back above the lens
        and the same three metres cost nothing. Nothing in the picture tells the
        two apart, so the map has to carry it.
        """
        from watcher.scenemap import SceneMap

        carte = SceneMap.load(ROOT / "config" / "scene.json")
        self.assertTrue(carte.uncertainty, "la carte ne dit pas ce que valent ses distances")

        # Le près est rasant, le loin ne l'est pas : c'est toute la différence.
        cabane = [m for m in carte.landmarks if 50 < float(m.get("distance_m") or 0) < 70]
        lointain = [m for m in carte.landmarks if float(m.get("distance_m") or 0) > 1500]
        self.assertTrue(cabane and lointain)
        pied = lambda m: (min(0.999, m["x"]), min(0.999, m["y"] + m["ry"]))  # noqa: E731
        self.assertGreater(carte.doubt_at(*pied(cabane[0])), 0.4)
        self.assertLess(min(carte.doubt_at(*pied(m)) for m in lointain), 0.15)

        # Et il faut qu'il dise vrai : le doute annoncé doit couvrir l'écart
        # constaté sur la plupart des repères relevés. Un budget à un écart-type
        # en couvre deux tiers ; deux des treize passent au travers, tous deux à
        # dix-sept cents mètres, et on les laisse dire plutôt que d'ajuster le
        # doute jusqu'à ce qu'il ait toujours raison.
        couverts = 0
        releves = 0
        for mark in carte.landmarks:
            surveyed = float(mark.get("distance_m") or 0)
            lu = carte.distance_at(*pied(mark))
            if not (surveyed and lu):
                continue
            releves += 1
            couverts += abs(lu / surveyed - 1) <= carte.doubt_at(*pied(mark)) + 0.02
        self.assertGreaterEqual(couverts, int(releves * 0.7), f"{couverts}/{releves} seulement")

    def test_no_landmark_hides_behind_the_ground(self):
        # Un repère sert à refuser un événement : « une boîte serrée autour de
        # la statue est une ombre, pas un passage ». Six repères sur dix-neuf
        # se projetaient pourtant sur du sol bien plus proche qu'eux — le
        # mémorial de Tom Simpson, à 2 447 m derrière la crête, tombait au
        # milieu de la piste de ski, où il faisait rejeter de vrais passages.
        from watcher.scenemap import SceneMap

        carte = SceneMap.load(ROOT / "config" / "scene.json")
        self.assertTrue(carte.landmarks)
        for mark in carte.landmarks:
            releve = float(mark.get("distance_m") or 0)
            sol = carte.distance_at(min(0.999, mark["x"]), min(0.999, mark["y"]))
            # Zéro veut dire que la visée sort au-dessus de la crête : le repère
            # se détache sur le ciel et rien ne le cache.
            if not (releve and sol):
                continue
            self.assertGreaterEqual(
                sol, releve * 0.8,
                f"{mark['name']} est relevé à {releve:.0f} m mais le sol est atteint à {sol:.0f} m",
            )

    def test_a_refusing_stream_is_asked_less_and_less(self):
        # On 29 September a stream that answered nothing was asked three
        # thousand times in forty minutes, because a generator that ends
        # without raising left no pause anywhere in the loop.
        wait, asks = STREAM_RETRY_S, 0
        for _ in range(40 * 60):          # forty minutes of refusal
            asks += 1
            wait = _next_wait(0, wait)
        self.assertEqual(wait, STREAM_RETRY_MAX_S)
        # Counted in seconds rather than in turns: the ceiling means one ask a
        # minute once the wait has grown, not three thousand.
        spent, turns = 0.0, 0
        wait = STREAM_RETRY_S
        while spent < 40 * 60:
            spent += wait
            turns += 1
            wait = _next_wait(0, wait)
        self.assertLess(turns, 50)

    def test_a_stream_that_worked_is_reopened_at_once(self):
        # A stream that gave pictures and stopped is not refusing, and the
        # patience earned by a previous outage must not be held against it.
        self.assertEqual(_next_wait(1, STREAM_RETRY_MAX_S), STREAM_RETRY_S)

    def test_a_failed_publication_does_not_stop_the_watching(self):
        # A rejected push used to throw out of the picture loop, which reopened
        # the stream and threw away the background model with it — half a
        # minute of learning about this scene, lost over a git error.
        import watcher.main as main

        def refuse(_root):
            raise subprocess.CalledProcessError(1, ["git", "push"])

        kept, main.publish = main.publish, refuse
        try:
            with self.assertLogs("ventoux", level="ERROR"):
                self.assertFalse(_published(ROOT))
        finally:
            main.publish = kept

    def test_the_ridge_is_what_decides(self):
        # Every night in the archive reads 60 to 72 clear; the fogged night of
        # 27 September read 8 to 15, and the fog arriving read 49.
        clear = Scene(period="night", weather="", ridge=70.9)
        arriving = Scene(period="night", weather="", ridge=49.4)
        soup = Scene(period="night", weather="", ridge=9.3)
        self.assertFalse(clear.hazy)
        self.assertFalse(clear.fogged)
        self.assertTrue(arriving.hazy)
        self.assertFalse(arriving.fogged)
        self.assertTrue(soup.hazy)
        self.assertTrue(soup.fogged)


def _force(seconde):
    """La force de l'effet du moment, quel qu'il soit."""
    return stream.effet_du_moment(seconde)[1]


class DiffusionTests(unittest.TestCase):
    """La rediffusion en retard : ce qu'elle dessine et ce qu'elle fait entendre."""

    def test_the_time_written_in_the_history_is_read_as_utc(self):
        """Une heure sans fuseau lue comme locale déplace le rectangle.

        L'historique date en UTC. Lue comme heure locale, une identification de
        14 h 59 serait cherchée deux heures plus tôt l'été : le rectangle se
        poserait sur une image où il n'y a rien, et le flux montrerait la veille
        en train de se tromper alors qu'elle a eu raison.
        """
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "events.json"
            chemin.write_text(json.dumps([{
                "id": "x", "t": "2026-09-29T14:59:32Z", "label": "Camion",
                "type": "car", "detail": {"box": [0.1, 0.2, 0.3, 0.4]},
            }]), encoding="utf-8")
            attendu = datetime(2026, 9, 29, 14, 59, 32, tzinfo=ZoneInfo("UTC")).timestamp()
            vus = stream.identifications(chemin, attendu - 10)
            self.assertEqual(len(vus), 1)
            self.assertEqual(vus[0]["t"], attendu)

    def test_an_identification_without_a_box_is_not_drawn(self):
        # On ne sait pas où la poser ; un rectangle au hasard vaut moins que
        # pas de rectangle.
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "events.json"
            chemin.write_text(json.dumps([
                {"id": "a", "t": "2026-09-29T14:59:32Z", "label": "Avion", "detail": {}},
                {"id": "b", "t": "2026-09-29T14:59:33Z", "label": "Voiture",
                 "detail": {"box": [0.1, 0.2, 0.3, 0.4]}},
            ]), encoding="utf-8")
            vus = stream.identifications(chemin, 0)
            self.assertEqual([vu["label"] for vu in vus], ["Voiture"])

    def test_the_rectangle_lands_where_the_box_says(self):
        image = np.zeros((1080, 1920, 3), np.uint8)
        quand = 1000.0
        vu = {"t": quand, "box": [0.5, 0.25, 0.1, 0.2], "label": "", "type": "car"}
        self.assertEqual(stream.dessine(image, [vu], quand), 1)
        rouges = np.argwhere(image[:, :, 2] > 100)
        haut, gauche = rouges.min(axis=0)
        bas, droite = rouges.max(axis=0)
        # Le trait fait deux pixels, d'où la tolérance de deux.
        self.assertAlmostEqual(gauche, 0.5 * 1920, delta=2)
        self.assertAlmostEqual(droite, 0.6 * 1920, delta=2)
        self.assertAlmostEqual(haut, 0.25 * 1080, delta=2)
        self.assertAlmostEqual(bas, 0.45 * 1080, delta=2)

    def test_a_name_stops_being_shown_once_its_moment_has_passed(self):
        image = np.zeros((1080, 1920, 3), np.uint8)
        vu = {"t": 1000.0, "box": [0.5, 0.25, 0.1, 0.2], "label": "", "type": "car"}
        self.assertEqual(stream.dessine(image, [vu], 1000.0 + stream.TENUE_S - 0.1), 1)
        self.assertEqual(stream.dessine(image, [vu], 1000.0 + stream.TENUE_S + 0.1), 0)
        # Ni avant : le flux est en retard sur la veille, pas en avance sur elle.
        self.assertEqual(stream.dessine(image, [vu], 999.0), 0)

    def test_the_session_plays_every_track_before_repeating_one(self):
        """Tirage sans remise tant qu'il reste des morceaux.

        Entendre deux fois le même titre avant d'avoir entendu tous les autres
        est ce qui fait qu'un flux sonne comme une boucle plutôt que comme une
        soirée. La bibliothèque est petite au début : la faute s'entendrait.
        """
        with tempfile.TemporaryDirectory() as dossier:
            racine = Path(dossier)
            for nom in "abcdef":
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                                "-i", "sine=frequency=440:duration=3",
                                str(racine / f"{nom}.mp3")], check=True)
            session = stream.batir_session(racine, heures=0.02)
            self.assertIsNotNone(session)
            # Une entrée tient en trois lignes depuis qu'on sert les longs sets
            # par tranches : le fichier, puis son entrée et sa sortie.
            lignes = [l for l in session.read_text(encoding="utf-8").splitlines()
                      if l.startswith("file ")]
            premiers = [ligne.rsplit("/", 1)[1].rstrip("'") for ligne in lignes[:6]]
            self.assertEqual(sorted(premiers), sorted(f"{n}.mp3" for n in "abcdef"))

    def test_no_track_holds_the_stream_for_more_than_ten_minutes(self):
        """Un set de cinquante minutes se sert par tranches, pas d'un bloc.

        Personne ne reste dix minutes sur la même chose, et la bibliothèque
        contient des mixes qui durent près d'une heure : les jeter serait
        perdre le meilleur du fonds, les passer entiers serait perdre l'auditeur.
        """
        bouts = stream._tranches(Path("/x/mix.mp3"), 54 * 60.0)
        self.assertGreater(len(bouts), 1)
        self.assertLessEqual(max(b["d"] for b in bouts), stream.TRANCHE_MAX_S)
        # Rien ne se perd : les tranches bout à bout font le morceau entier.
        self.assertAlmostEqual(sum(b["d"] for b in bouts), 54 * 60.0, places=3)
        self.assertEqual(bouts[0]["debut"], 0.0)
        # Et un morceau ordinaire n'est pas découpé pour rien.
        self.assertEqual(len(stream._tranches(Path("/x/court.mp3"), 240.0)), 1)

    def test_a_fire_is_never_replayed(self):
        """Une image de feu remontrée ferait croire que la montagne brûle.

        C'est la seule sortie du flux qui puisse causer un tort réel, et le
        bandeau « replay » n'y change rien : personne ne lit un bandeau quand
        il voit de la fumée.
        """
        with tempfile.TemporaryDirectory() as dossier:
            racine = Path(dossier)
            (racine / "data" / "thumbs").mkdir(parents=True)
            photo = "data/thumbs/x.jpg"
            (racine / photo).write_bytes(b"\xff\xd8\xff")
            # Tous confirmés : c'est la règle du feu qu'on éprouve ici, pas
            # celle du verdict, et un feu confirmé reste un feu à ne pas
            # remontrer.
            (racine / "data" / "events.json").write_text(json.dumps([
                {"t": "2026-09-29T14:59:32Z", "label": "Départ de feu", "thumb": photo,
                 "review": "accepted"},
                {"t": "2026-09-29T15:00:00Z", "label": "Incendie", "thumb": photo,
                 "review": "accepted"},
                {"t": "2026-09-29T15:01:00Z", "label": "Panache de nuit", "thumb": photo,
                 "review": "accepted"},
                {"t": "2026-09-29T15:02:00Z", "label": "Camion", "thumb": photo,
                 "review": "accepted"},
                # Et celui-ci n'a jamais été vérifié : il ne passe pas non plus.
                {"t": "2026-09-29T15:03:00Z", "label": "Voiture", "thumb": photo},
            ]), encoding="utf-8")
            gardees = stream.archives(racine)
            self.assertEqual([f["label"] for f in gardees], ["Camion"])

    def test_a_voice_ducks_the_music_without_clipping_it(self):
        """La voix se pose sur la musique, elle ne la remplace pas.

        Deux signaux forts additionnés en seize bits ne saturent pas : ils
        rebouclent, et un dépassement en audio ne s'entend pas comme un son
        trop fort mais comme un claquement. D'où la somme en entiers larges.
        """
        musique = stream.Musique.__new__(stream.Musique)
        musique.voix = b""
        musique.voix_dit = ""
        musique._verrou = threading.Lock()

        plein = np.full(400, 30000, np.int16)
        fond = plein.tobytes()
        musique.voix = plein.tobytes()
        melange = np.frombuffer(musique._avec_la_voix(fond), np.int16)

        self.assertEqual(len(melange), 400)
        # Rien n'a rebouclé : une somme qui déborde aurait produit du négatif.
        self.assertTrue((melange > 0).all())
        self.assertLessEqual(int(melange.max()), 32767)
        # Et la musique est bien passée dessous, pas effacée : 30000 de voix
        # plus 35 % de 30000 de musique dépasse la voix seule, donc écrête.
        self.assertEqual(int(melange[0]), 32767)

        # Une fois la réplique servie, le son repart intact et la voix se tait.
        self.assertFalse(musique.parle())
        self.assertEqual(musique._avec_la_voix(fond), fond)

    def test_the_voice_stops_exactly_when_the_clip_runs_out(self):
        """Le mot à l'écran suit le compte des octets, pas une minuterie."""
        musique = stream.Musique.__new__(stream.Musique)
        musique.voix_dit = ""
        musique._verrou = threading.Lock()
        # Une réplique d'un dixième de seconde, servie en deux tranches.
        echantillons = stream.ECHANTILLONS_S // 10 * stream.VOIES
        musique.voix = np.zeros(echantillons, np.int16).tobytes()
        moitie = len(musique.voix) // 2
        silence = b"\0" * moitie

        musique._avec_la_voix(silence)
        self.assertTrue(musique.parle())
        musique._avec_la_voix(silence)
        self.assertFalse(musique.parle())

    def test_each_occasion_draws_only_its_own_voices(self):
        """Féliciter avec la voix de l'ennui dirait l'inverse de ce qu'on veut."""
        temporaire = tempfile.TemporaryDirectory()
        self.addCleanup(temporaire.cleanup)
        dossier = Path(temporaire.name) / "voix"
        dossier.mkdir()
        fiches = [{"fichier": "ennui_a.raw", "quand": "ennui"},
                  {"fichier": "attrape_b.raw", "quand": "attrape"},
                  {"fichier": "vieux.raw"}]
        for f in fiches:
            (dossier / f["fichier"]).write_bytes(b"\0\0")
        (dossier / "voix.json").write_text(json.dumps(fiches), encoding="utf-8")

        # Une fiche sans « quand » date d'avant les félicitations : elle doit
        # rester de l'ennui, pas devenir une prise.
        ennui = [p.name for p in stream.repliques(dossier, "ennui")]
        self.assertEqual(sorted(ennui), ["ennui_a.raw", "vieux.raw"])
        self.assertEqual([p.name for p in stream.repliques(dossier, "attrape")],
                         ["attrape_b.raw"])

    def test_the_catch_is_celebrated_while_its_box_is_on_screen(self):
        """« GOOD CATCH » sur une image vide : la f\u00eate doit suivre le rectangle.

        La veille travaille au bord du direct, le flux le montre avec du
        retard. F\u00eater \u00e0 l'arriv\u00e9e de la fiche criait victoire dix-neuf secondes
        avant que le rectangle n'apparaisse, et la voiture passait ensuite en
        silence.
        """
        vu = {"t": 1000.0, "type": "vehicle", "label": "Voiture verte",
              "box": [0.4, 0.8, 0.1, 0.1]}
        # Trop t\u00f4t : la t\u00eate de lecture n'a pas encore atteint la voiture.
        self.assertIsNone(stream.prise_a_feter([vu], 1000.0 - 5.0, set()))
        # Pendant : le rectangle est \u00e0 l'\u00e9cran, donc la f\u00eate a quelque chose \u00e0
        # montrer du doigt.
        for age in (0.0, stream.TENUE_S / 2, stream.TENUE_S):
            self.assertIs(stream.prise_a_feter([vu], 1000.0 + age, set()), vu)
        # Trop tard : plus rien \u00e0 montrer, donc rien \u00e0 f\u00eater. C'est aussi ce qui
        # emp\u00eache un flux qui s'allume de f\u00eater tout son historique.
        self.assertIsNone(stream.prise_a_feter([vu], 1000.0 + stream.TENUE_S + 0.1, set()))
        # Et jamais deux fois : quatre secondes \u00e0 six images par seconde font
        # vingt-quatre occasions de crier pour une seule voiture.
        self.assertIsNone(stream.prise_a_feter([vu], 1000.0 + 1.0, {1000.0}))

    def test_a_replay_shows_today_before_last_week(self):
        """La r\u00e9serve remontrait surtout le 25 septembre.

        Tirage uniforme sur quatre-vingt-cinq fiches, \u00e0 une toutes les dix
        minutes : quatorze heures avant qu'une voiture attrap\u00e9e \u00e0 midi ait sa
        chance. Le flux avait l'air de n'avoir rien vu depuis une semaine.
        """
        maintenant = datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc).timestamp()

        def fiche(iso, nom):
            return {"photo": Path(f"/tmp/{nom}.jpg"), "label": nom, "t": iso,
                    "contexte": ""}

        vieilles = [fiche("2026-09-25T08:20:51Z", f"vieille{i}") for i in range(85)]
        fraiches = [fiche("2026-10-01T14:35:30Z", "Voiture verte"),
                    fiche("2026-10-01T13:28:35Z", "Voiture")]

        # On puise par la fin : les deux derniers sortis sont les deux premiers
        # montr\u00e9s. Sur vingt tirages, les fra\u00eeches doivent gagner \u00e0 tous les
        # coups — elles p\u00e8sent deux cents fois plus qu'une fiche d'il y a une
        # semaine.
        for graine in range(20):
            ordre = stream.ordre_de_rediffusion(
                vieilles + fraiches, random.Random(graine), maintenant)
            self.assertEqual(len(ordre), 87)
            deux_premieres = {ordre[-1]["label"], ordre[-2]["label"]}
            self.assertEqual(deux_premieres, {"Voiture verte", "Voiture"})

    def test_an_old_catch_still_gets_its_turn(self):
        """L'archive doit rester une archive : les nuits creuses n'ont qu'elle."""
        maintenant = datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc).timestamp()
        meme_age = [{"photo": Path(f"/tmp/{i}.jpg"), "label": f"Voiture {i}",
                     "t": "2026-09-25T08:20:51Z", "contexte": ""} for i in range(12)]
        premieres = set()
        for graine in range(30):
            ordre = stream.ordre_de_rediffusion(meme_age, random.Random(graine), maintenant)
            self.assertEqual(len(ordre), 12, "rien n'est jet\u00e9")
            premieres.add(ordre[-1]["label"])
        self.assertGreater(len(premieres), 5, "\u00e0 \u00e2ge \u00e9gal, l'ordre reste du hasard")

    def test_a_replay_pool_survives_a_date_it_cannot_read(self):
        """Une date illisible ne doit pas enterrer une prise qu'un humain a confirm\u00e9e."""
        maintenant = datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc).timestamp()
        bancale = {"photo": Path("/tmp/x.jpg"), "label": "Bus", "t": "", "contexte": ""}
        ordre = stream.ordre_de_rediffusion([bancale], random.Random(0), maintenant)
        self.assertEqual(len(ordre), 1)
        self.assertEqual(stream._age_heures("pas une date", maintenant), 0.0)

    def test_the_box_follows_the_subject_instead_of_waiting_for_it(self):
        """Tenue quatre secondes sur une seule position, elle finit sur du vide.

        Une voiture traverse le champ en six secondes. Au milieu de la tenue, le
        rectangle doit être au milieu du trajet, pas à son départ.
        """
        debut = 1_000_000.0
        vu = {"t": debut, "label": "Voiture", "sur": True,
              "box": [0.10, 0.50, 0.05, 0.03],
              "trace": [[debut, 0.10, 0.50, 0.05, 0.03],
                        [debut + 6.0, 0.70, 0.50, 0.05, 0.03]]}
        x, _, _, _ = stream.suit(vu, debut + 3.0)
        self.assertAlmostEqual(x, 0.40, places=3)
        # Et le rectangle posé sur l'image suit vraiment : deux instants
        # différents ne peuvent pas donner la même image.
        tot, tard = (np.zeros((360, 640, 3), np.uint8) for _ in range(2))
        stream.dessine(tot, [dict(vu)], debut + 0.5)
        stream.dessine(tard, [dict(vu)], debut + 3.5)
        self.assertFalse(np.array_equal(tot, tard))

    def test_the_box_stays_as_long_as_the_subject_does(self):
        """Quatre secondes, c'est la durée d'un geste, pas celle d'un passage.

        Un piéton met une demi-minute à traverser. Le rectangle le lâchait au
        quart du chemin et le reste se faisait en silence, alors que le flux a
        toute la trajectoire en main bien avant de diffuser l'image.
        """
        debut = 1_000_000.0
        traverse = {"t": debut, "label": "Piéton", "sur": True,
                    "box": [0.10, 0.50, 0.03, 0.05],
                    "trace": [[debut, 0.10, 0.50, 0.03, 0.05],
                              [debut + 30.0, 0.80, 0.50, 0.03, 0.05]]}
        ouvre, ferme = stream.presence(traverse)
        self.assertEqual((ouvre, ferme), (debut, debut + 30.0))
        fond = np.zeros((360, 640, 3), np.uint8)
        for instant in (debut + 1.0, debut + 15.0, debut + 29.0):
            toile = fond.copy()
            self.assertEqual(stream.dessine(toile, [dict(traverse)], instant), 1,
                             f"abandonn\u00e9 \u00e0 {instant - debut:.0f} s")
        # Et une fois sorti du champ, le rectangle s'en va.
        tard = fond.copy()
        stream.dessine(tard, [dict(traverse)], debut + 31.0)
        self.assertTrue(np.array_equal(tard, fond))
        # Une prise d'une seule image garde son plancher, sinon sa fen\u00eatre
        # serait nulle et elle ne s'afficherait jamais.
        bref = {"t": debut, "label": "Voiture", "sur": True,
                "box": [0.4, 0.4, 0.1, 0.1], "trace": []}
        self.assertEqual(stream.presence(bref), (debut, debut + stream.TENUE_S))

    def test_the_box_never_goes_where_nothing_was_measured(self):
        """Hors du trajet relevé, on se tient au dernier point connu.

        Prolonger la droite serait inventer une position, et un rectangle
        inventé se pose sur du vide avec le même aplomb que les autres.
        """
        debut = 1_000_000.0
        vu = {"t": debut, "label": "Voiture", "sur": True,
              "box": [0.10, 0.50, 0.05, 0.03],
              "trace": [[debut, 0.10, 0.50, 0.05, 0.03],
                        [debut + 6.0, 0.70, 0.50, 0.05, 0.03]]}
        self.assertEqual(stream.suit(vu, debut - 10.0)[0], 0.10)
        self.assertEqual(stream.suit(vu, debut + 600.0)[0], 0.70)
        # Sans trajectoire — un événement d'avant cette version, ou une prise
        # d'une seule image —, la boîte d'origine sert telle quelle.
        seul = {"t": debut, "box": [0.2, 0.3, 0.1, 0.1], "trace": []}
        self.assertEqual(stream.suit(seul, debut + 2.0), (0.2, 0.3, 0.1, 0.1))

    def test_the_word_is_written_only_when_the_watch_named_something(self):
        """« Mouvement détecté » est un aveu, pas une identification."""
        sur = 0.9
        self.assertTrue(stream.nomme("Voiture", sur))
        self.assertTrue(stream.nomme("Camion", sur))
        # De nuit la veille ne sépare plus la voiture du camion et publie le
        # mot générique. C'est une lecture, elle a droit au sien.
        self.assertTrue(stream.nomme("Véhicule", sur))
        self.assertTrue(stream.nomme("Véhicule rouge", sur))
        for aveu in ("Mouvement détecté", "Rien de reconnu", "Tache trop large",
                     "Véhicule non nommé", "Brouillard", "Immobile sur la pente", ""):
            self.assertFalse(stream.nomme(aveu, sur), aveu)
        # Le rectangle reste dans les deux cas — il y a bien eu quelque chose —
        # mais il ne parle que dans un seul.
        fond = np.zeros((360, 640, 3), np.uint8)
        quand = 1_000_000.0
        boite = {"t": quand, "box": [0.4, 0.4, 0.1, 0.1], "trace": []}
        dit = fond.copy()
        stream.dessine(dit, [dict(boite, label="Voiture", sur=True)], quand + 1.0)
        tait = fond.copy()
        stream.dessine(tait, [dict(boite, label="Mouvement détecté", sur=False)],
                       quand + 1.0)
        self.assertFalse(np.array_equal(dit, fond), "le nommé est entouré")
        self.assertFalse(np.array_equal(tait, fond), "l'innommé aussi")
        self.assertGreater(int(dit.any(axis=2).sum()), int(tait.any(axis=2).sum()),
                           "le mot ne s'écrit que dans un des deux cas")

    def test_a_name_is_only_written_when_the_watch_is_sure_of_it(self):
        """Un rectangle muet avoue ; un rectangle qui se trompe de mot affirme.

        Le seuil n'est pas choisi, il est relevé : sur les cent six prises
        tranchées par un humain, aucune faute au-dessus de 0,60, les dix refus
        en dessous. Et c'est un score de modèle, donc il se transporte sur une
        autre caméra — une largeur en mètres ne le ferait pas.
        """
        self.assertGreaterEqual(stream.CONFIANCE_MOT, 0.6)
        self.assertTrue(stream.nomme("Voiture", stream.CONFIANCE_MOT))
        self.assertFalse(stream.nomme("Voiture", stream.CONFIANCE_MOT - 0.01),
                         "un nom douteux ne s'\u00e9crit pas")
        # Et la fiche porte bien la confiance jusqu'\u00e0 l'\u00e9cran : sans \u00e7a le seuil
        # ne s'appliquerait \u00e0 rien.
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "events.json"
            boite = {"box": [0.1, 0.1, 0.2, 0.2]}
            chemin.write_text(json.dumps({"events": [
                {"t": "2026-10-01T06:00:00Z", "type": "car", "label": "Voiture",
                 "confidence": 0.90, "detail": boite},
                {"t": "2026-10-01T06:00:02Z", "type": "car", "label": "Camion",
                 "confidence": 0.41, "detail": boite},
                # Une fiche sans confiance du tout : on ne devine pas \u00e0 sa place.
                {"t": "2026-10-01T06:00:04Z", "type": "car", "label": "Bus",
                 "detail": boite},
            ]}), encoding="utf-8")
            vus = stream.identifications(chemin, 0.0)
        self.assertEqual([v["label"] for v in vus], ["Voiture", "Camion", "Bus"],
                         "les trois gardent leur rectangle")
        self.assertEqual([v["sur"] for v in vus], [True, False, False])

    def test_the_path_is_published_in_absolute_hours(self):
        """Le flux pose les rectangles sur une image qui porte son heure.

        Des écarts au début l'obligeraient à deviner à quoi ils se rapportent ;
        des heures entières laissent la question du calage là où elle est déjà
        résolue.
        """
        from watcher.main import _trace_of

        class _Suivi:
            trace = [(1_000_000.0, (320, 180, 64, 36)),
                     (1_000_001.0, (384, 180, 64, 36))]

        image = np.zeros((360, 640, 3), np.uint8)
        chemin = _trace_of(image, _Suivi())
        self.assertEqual(len(chemin), 2)
        self.assertEqual(chemin[0], [1_000_000.0, 0.5, 0.5, 0.1, 0.1])
        self.assertGreater(chemin[1][0], 1_000_000.0, "des heures, pas des \u00e9carts")
        # Un seul point ne fait pas une trajectoire : on n'en publie pas.
        class _Immobile:
            trace = [(1_000_000.0, (320, 180, 64, 36))]

        self.assertEqual(_trace_of(image, _Immobile()), [])
        self.assertEqual(_trace_of(None, _Suivi()), [])

    def test_the_carpet_flies_over_the_ridge_and_never_through_it(self):
        """À hauteur fixe, il traversait le Ventoux par le milieu.

        La crête descend de 0,30 à gauche à 0,16 à droite dans le contour du
        ciel : un tapis volant à hauteur constante passe donc devant le sommet,
        qui est exactement ce que les gens sont venus voir.
        """
        ciel = [[0.0, 0.0], [1.0, 0.0], [1.0, 0.16], [0.48, 0.18],
                [0.22, 0.26], [0.0, 0.30]]
        for part, attendu in ((0.0, 0.30), (0.22, 0.26), (1.0, 0.16)):
            self.assertAlmostEqual(stream._crete(ciel, part), attendu, places=3)
        self.assertIsNone(stream._crete(None, 0.5), "sans carte, pas de cr\u00eate")
        # Et à chaque instant de la traversée, le tapis reste au-dessus d'elle.
        vols = 0
        for instant in np.arange(0.0, stream.TAPIS_TRAVERSEE_S, 0.5):
            toile = np.zeros((720, 1280, 3), np.uint8)
            self.assertTrue(stream.pose_tapis(toile, float(instant), 0.9, ciel))
            pose = np.argwhere(toile.any(axis=2))
            if not len(pose):
                # Il entre de nulle part et sort de même : aux deux extrémités
                # de la traversée il est entièrement hors du cadre.
                continue
            vols += 1
            bas = pose[:, 0].max()
            for bord in (pose[:, 1].min(), pose[:, 1].max()):
                sol = stream._crete(ciel, bord / 1280) * 720
                self.assertLess(bas, sol, f"dans la montagne \u00e0 {instant:.1f} s")
        self.assertGreater(vols, 20, "il doit passer, pas seulement exister")
        # Hors de sa fenêtre, le ciel est vide.
        vide = np.zeros((720, 1280, 3), np.uint8)
        self.assertFalse(stream.pose_tapis(vide, stream.TAPIS_TRAVERSEE_S + 1, 0.9, ciel))
        self.assertFalse(vide.any())

    def test_the_elephant_stands_on_the_roundabout_and_yields_to_the_watch(self):
        """Il danse à l'endroit même où les choses se passent.

        C'est tout le charme et tout le risque : un éléphant rose par-dessus
        une voiture entourée de rouge ferait passer la veille pour une
        plaisanterie. Il est donc posé sur le rond-point, à l'échelle du
        rond-point, et l'appelant ne le propose que dans un creux.
        """
        rond = [[0.0, 0.78], [0.34, 0.72], [0.40, 0.86], [0.30, 1.0], [0.0, 1.0]]
        toile = np.zeros((720, 1280, 3), np.uint8)
        self.assertTrue(stream.pose_elephant(toile, 4.0, 0.9, rond))
        pose = np.argwhere(toile.any(axis=2))
        hauteur = pose[:, 0].max() - pose[:, 0].min()
        # Sa taille vient du rond-point et de rien d'autre : c'est ce qui lui
        # permettra d'exister sur une autre caméra sans qu'on règle un pixel.
        attendu = (1.0 - 0.72) * 720 * stream.ELEPHANT_PART
        self.assertLess(abs(hauteur - attendu) / attendu, 0.6)
        # Il est bien sur le rond-point, pas à côté.
        milieu = pose[:, 1].mean() / 1280
        self.assertLess(abs(milieu - 0.208), 0.08)
        # Sans rond-point, pas d'éléphant — et c'est la bonne réponse, il n'y
        # aurait nulle part où le faire danser.
        vide = np.zeros((720, 1280, 3), np.uint8)
        self.assertFalse(stream.pose_elephant(vide, 4.0, 0.9, None))
        self.assertFalse(vide.any())
        # Et il ne reste pas : neuf secondes, puis onze minutes de silence.
        apres = np.zeros((720, 1280, 3), np.uint8)
        self.assertFalse(stream.pose_elephant(apres, stream.ELEPHANT_TENUE_S + 1,
                                              0.9, rond))
        self.assertFalse(apres.any())

    def test_the_night_gets_the_turns_more_often(self):
        """Douze heures d'image fixe et sombre, c'est là qu'on en a besoin.

        La veille n'y voit presque rien et le survol du relief ne peut pas
        jouer : il est rendu en plein soleil, et au milieu d'une nuit noire il
        ne montre pas le relief, il montre qu'on a collé une autre vidéo.
        """
        self.assertGreater(stream.NUIT_PLUS_SOUVENT, 1.0)
        rond = [[0.0, 0.78], [0.34, 0.72], [0.40, 0.86], [0.30, 1.0], [0.0, 1.0]]

        def combien(nuit):
            vus = 0
            for seconde in range(2 * 3600):
                # Assez grande pour que l'éléphant y tienne : sous une douzaine
                # de pixels de haut il renonce, et il aurait raison.
                toile = np.zeros((240, 320, 3), np.uint8)
                vus += bool(stream.pose_elephant(toile, float(seconde), 0.9, rond,
                                                 nuit=nuit))
            return vus

        self.assertAlmostEqual(combien(True) / combien(False),
                               stream.NUIT_PLUS_SOUVENT, delta=0.4)

    def test_the_elephant_waits_on_a_clock_replays_cannot_reset(self):
        """Il n'est jamais venu, et le fichier disait pourquoi trois lignes plus haut.

        Il y a deux horloges du vide. « dernier_vu » est remis à zéro par
        chaque rediffusion ; « dernier_mouvement » ne l'est que par une vraie
        détection. La nuit, le flux rediffuse sans arrêt faute de mieux, donc
        la première ne dépassait jamais cinq minutes et le creux ne s'ouvrait
        pas. Une image d'hier n'est pas un évènement.
        """
        source = inspect.getsource(stream.diffuse)
        appel = source[source.index("pose_elephant") - 400:source.index("pose_elephant")]
        self.assertIn("dernier_mouvement > CREUX_S", appel)
        self.assertNotIn("dernier_vu > CREUX_S", appel)
        # Et la raison du piège est toujours écrite là où on tombe dedans.
        self.assertIn("dernier_vu", inspect.getsource(stream.diffuse))

    def test_the_submarine_crosses_the_sky_and_never_the_mountain(self):
        """Il traverse en entier, il reste au-dessus de la crête, et il attend.

        Au-dessus de la crête parce que c'est la règle de tout ce qu'on ajoute
        au ciel : un dessin qui passe devant le sommet cache ce que les gens
        sont venus voir. Et comme il est deux fois plus large que haut, c'est
        par un bout qu'il mordrait le versant, pas par son milieu.
        """
        racine = Path(__file__).resolve().parent.parent
        vignette = stream.charge_vignette(racine / "assets" / "sous-marin.png")
        self.assertIsNotNone(vignette, "le sous-marin est dans le d\u00e9p\u00f4t")
        ciel = [[0.0, 0.0], [1.0, 0.0], [1.0, 0.16], [0.48, 0.18],
                [0.22, 0.26], [0.0, 0.30]]
        gauche_atteint = droite_atteint = False
        passages = 0
        for pas in range(90):
            instant = pas * stream.SOUS_MARIN_TRAVERSEE_S / 89
            toile = np.zeros((720, 1280, 3), np.uint8)
            if not stream.pose_sous_marin(toile, instant, vignette, ciel):
                continue
            pose = np.argwhere(toile.any(axis=2))
            if not len(pose):
                continue
            passages += 1
            haut, bas = pose[:, 0].min(), pose[:, 0].max()
            bord_g, bord_d = pose[:, 1].min(), pose[:, 1].max()
            self.assertGreaterEqual(haut, 0)
            for bord in (bord_g, bord_d):
                sol = stream._crete(ciel, bord / 1280) * 720
                self.assertLess(bas, sol, f"dans la montagne \u00e0 {instant:.1f} s")
            gauche_atteint = gauche_atteint or bord_g <= 1
            droite_atteint = droite_atteint or bord_d >= 1278
        self.assertGreater(passages, 60, "il doit traverser")
        self.assertTrue(gauche_atteint and droite_atteint,
                        "il entre par un bord et sort par l'autre")
        # Et le reste du temps il n'est pas là. C'est un numéro, pas un décor :
        # un sous-marin en permanence dans le ciel cesse d'être une surprise au
        # bout de dix minutes et devient une gêne au bout d'une heure.
        vide = np.zeros((720, 1280, 3), np.uint8)
        self.assertFalse(stream.pose_sous_marin(
            vide, stream.SOUS_MARIN_TRAVERSEE_S + 1, vignette, ciel))
        self.assertFalse(vide.any())
        # Sans le dessin, pas de numéro et pas de panne.
        self.assertFalse(stream.pose_sous_marin(vide, 1.0, None, ciel))
        self.assertIsNone(stream.charge_vignette(racine / "assets" / "pas-la.png"))

    def test_the_two_turns_almost_never_happen_at_once(self):
        """Des périodes rondes les feraient tomber ensemble plusieurs fois par jour.

        Et un numéro qui revient toujours avec l'autre cesse d'être une
        surprise : on croit à un spectacle réglé.
        """
        numeros = {
            "tapis": (stream.TAPIS_PERIODE_S, stream.TAPIS_TRAVERSEE_S),
            "\u00e9l\u00e9phant": (stream.ELEPHANT_PERIODE_S, stream.ELEPHANT_TENUE_S),
            "sous-marin": (stream.SOUS_MARIN_PERIODE_S, stream.SOUS_MARIN_TRAVERSEE_S),
        }
        for periode, _ in numeros.values():
            entier = int(periode)
            self.assertEqual(periode, entier)
            self.assertTrue(all(entier % d for d in range(2, int(entier ** 0.5) + 1)),
                            f"{entier} n'est pas premier")
        self.assertEqual(len({p for p, _ in numeros.values()}), len(numeros))
        # Ce qu'on vérifie n'est pas qu'ils se croisent rarement — avec six
        # numéros par heure, ils se croiseront forcément de temps en temps —
        # mais qu'ils ne se croisent pas plus souvent que le hasard. C'est ce
        # que le fait de ne pas avoir de diviseur commun achète, et c'est la
        # seule chose qui se voie à l'œil : deux numéros calés l'un sur
        # l'autre, on l'appelle un spectacle réglé.
        for un, deux in itertools.combinations(numeros, 2):
            (pa, da), (pb, db) = numeros[un], numeros[deux]
            ensemble = sum(1 for s in range(24 * 3600)
                           if s % pa < da and s % pb < db)
            hasard = 24 * 3600 * (da / pa) * (db / pb)
            self.assertLess(ensemble, 2.0 * hasard + 10,
                            f"{un} et {deux} sont cal\u00e9s l'un sur l'autre")
        # Et la preuve que l'épreuve mord : des périodes rondes se calent.
        cales = sum(1 for s in range(24 * 3600) if s % 400 < 14 and s % 500 < 22)
        self.assertGreater(cales, 2.0 * 24 * 3600 * (14 / 400) * (22 / 500) + 10)

    def test_fog_gets_said_in_the_words_the_watch_used(self):
        """Un mur gris sans un mot ressemble \u00e0 une cam\u00e9ra en panne.

        Mais « fog » sur de la brume ferait dire \u00e0 la veille autre chose que ce
        qu'elle a lu, donc chaque lecture garde son mot.
        """
        self.assertEqual(stream.BROUILLARD_MOTS.get("brouillard"), "FOOOOG")
        self.assertNotEqual(stream.BROUILLARD_MOTS.get("brume"),
                            stream.BROUILLARD_MOTS.get("brouillard"))
        # Les cl\u00e9s sont le vocabulaire de la veille, pas un vocabulaire \u00e0 nous :
        # sans \u00e7a le mot ne sortirait jamais.
        for lecture in stream.BROUILLARD_MOTS:
            self.assertIn(lecture, stream.ANGLAIS)
        # Et un ciel d\u00e9gag\u00e9 ne dit rien du tout.
        for clair in ("ciel d\u00e9gag\u00e9", "peu nuageux", "nuageux", "couvert", ""):
            self.assertEqual(stream.BROUILLARD_MOTS.get(clair, ""), "")

    def test_fog_is_said_now_and_then_not_all_day(self):
        """Il tient des demi-journ\u00e9es : \u00e9crit en continu, le mot devient un d\u00e9cor."""
        self.assertGreaterEqual(stream.BROUILLARD_PAUSE_S, 600.0)
        self.assertLess(stream.BROUILLARD_TENUE_S, stream.BROUILLARD_PAUSE_S / 100)
        fond = np.full((360, 640, 3), 128, np.uint8)
        dit = fond.copy()
        stream.pose_ennui(dit, "FOOOOG", 1.0)
        self.assertFalse(np.array_equal(dit, fond))
        tait = fond.copy()
        stream.pose_ennui(tait, "", 1.0)
        self.assertTrue(np.array_equal(tait, fond), "pas de mot, pas de trace")

    def test_the_machine_age_is_truncated_not_rounded(self):
        """« UP 2d 24h » : un jour n'a pas vingt-quatre heures en plus de lui-m\u00eame.

        La mise en forme arrondissait. \u00c0 quarante-sept heures et demie,
        « heures / 24 » valait 1,98 et sortait « 2d » pendant que « heures % 24 »
        valait 23,7 et sortait « 24h » : les deux faux \u00e0 la m\u00eame seconde.
        """
        def affiche(secondes):
            toile = np.zeros((420, 1600, 3), np.uint8)
            stream.pose_machine(toile, {"degres": 52.0, "charge": 0.4,
                                        "debout": secondes, "libre": 800e9})
            return toile

        # Le cas qui a \u00e9t\u00e9 vu \u00e0 l'\u00e9cran : 47 h 42 doit se lire 1d 23h.
        heure = 3600
        for secondes in (47.7 * heure, 23.9 * heure, 24 * heure, 0.0):
            toile = affiche(secondes)
            self.assertTrue(toile.any(), "l'encart doit s'\u00e9crire")
        # Deux dur\u00e9es qui diff\u00e8rent d'un jour entier ne peuvent pas s'afficher
        # pareil ; avec l'arrondi, 47,7 h et 71,7 h donnaient toutes deux « 24h ».
        self.assertFalse(np.array_equal(affiche(47.7 * heure), affiche(71.7 * heure)))
        # Et une machine qui vient de d\u00e9marrer ne dit pas « 0h ».
        self.assertFalse(np.array_equal(affiche(0.0), affiche(40 * 60)))

    def test_the_machine_panel_has_an_edge(self):
        """Assombri seul, l'encart flotte : ses limites bougent avec le ciel."""
        fond = np.full((420, 1600, 3), 200, np.uint8)
        avec = fond.copy()
        stream.pose_machine(avec, {"degres": 52.0, "charge": 0.4,
                                   "debout": 200000.0, "libre": 800e9})
        # Le filet se voit sur le bord droit de l'encart, l\u00e0 o\u00f9 il n'y a aucun
        # texte : une colonne au moins doit diff\u00e9rer du simple assombrissement.
        assombri = (fond * 0.35).astype(np.uint8)
        bande = avec[:300, :400]
        self.assertFalse(np.array_equal(bande, assombri[:300, :400]))

    def test_the_ridge_puts_the_slope_in_shadow_before_sunset(self):
        """Ici le soleil quitte la cr\u00eate une heure avant de se coucher.

        C'est la chose la plus locale qu'on puisse dire de cette image, et elle
        ne se calcule qu'avec le relief : l'almanach, lui, ne conna\u00eet que
        l'horizon plat.
        """
        racine = Path(__file__).resolve().parents[1]
        camera = json.loads((racine / "config" / "config.json").read_text(
            encoding="utf-8"))["camera"]
        relief = stream.charge_relief(racine, camera)
        if relief is None:
            self.skipTest("pas de mod\u00e8le de terrain")
        quand = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc).timestamp()
        heures = stream.heures_du_soleil(relief, camera, quand)
        for nom in ("lever", "crete_matin", "crete_soir", "coucher"):
            self.assertIn(nom, heures, nom)
        # L'ordre de la journ\u00e9e, qui ne peut pas s'inverser.
        self.assertLess(heures["lever"], heures["crete_matin"])
        self.assertLess(heures["crete_matin"], heures["crete_soir"])
        self.assertLess(heures["crete_soir"], heures["coucher"])
        # Et l'\u00e9cart du soir, qui est tout l'int\u00e9r\u00eat : la montagne passe devant
        # le soleil bien avant l'horizon.
        avance = (heures["coucher"] - heures["crete_soir"]) / 60
        self.assertGreater(avance, 20, "sans relief, cet \u00e9cart serait nul")

    def test_the_sun_line_says_only_what_is_true_now(self):
        """Annoncer le lever \u00e0 dix-huit heures n'apprend rien \u00e0 qui regarde."""
        jour = datetime(2026, 10, 1, tzinfo=stream.PARIS)

        def a(heure, minute=0):
            return (jour + timedelta(hours=heure, minutes=minute)).timestamp()

        heures = {"lever": a(7, 35), "crete_matin": a(8, 16),
                  "crete_soir": a(18, 27), "coucher": a(19, 22)}
        lendemain = {"lever": a(31, 36), "crete_matin": a(32, 17)}

        def dit(heure, minute=0):
            return "".join(t for t, _ in stream.morceaux_soleil(
                heures, a(heure, minute), lendemain))

        self.assertIn("CLEARS THE RIDGE", dit(4))
        self.assertIn("RIDGE SHADOW", dit(15))
        self.assertIn("SHADOW OF THE VENTOUX", dit(18, 45))
        # Une fois le soleil couch\u00e9, l'obscurit\u00e9 n'est plus celle du Ventoux :
        # c'est la nuit, et se l'attribuer serait se vanter.
        self.assertNotIn("SHADOW OF THE VENTOUX", dit(20))
        # Et c'est le matin de demain qu'on annonce la nuit, pas celui du jour
        # qui vient de finir : le flux a donn\u00e9 pour imminent un 08:16 pass\u00e9
        # depuis treize heures.
        self.assertIn("FIRST LIGHT ON THIS SLOPE TOMORROW", dit(23))
        self.assertIn("08:17", dit(23))
        self.assertNotIn("08:16", dit(23))
        # Sans relief, on ne dit rien plut\u00f4t que d'inventer une heure.
        self.assertEqual(stream.morceaux_soleil({}, a(12)), [])

    def test_the_terrain_flyover_loops_and_never_says_live(self):
        """Un badge « LIVE » au-dessus d'un d\u00e9cor calcul\u00e9 serait un mensonge."""
        with tempfile.TemporaryDirectory() as coin:
            racine = Path(coin)
            self.assertEqual(stream.charge_vue3d(racine), [],
                             "sans dossier, le flux n'en parle pas")
            dossier = racine / "data" / "vue3d"
            dossier.mkdir(parents=True)
            for i in range(4):
                cv2.imwrite(str(dossier / f"{i:04d}.jpg"),
                            np.full((72, 128, 3), 40 + i * 50, np.uint8))
            images = stream.charge_vue3d(racine)
            self.assertEqual(len(images), 4)
            # La lecture reboucle : le survol est un aller-retour ferm\u00e9, donc
            # la derni\u00e8re image et la premi\u00e8re sont le m\u00eame point de vue.
            debut = stream.image_vue3d(images, 0.0, 6.0)
            self.assertTrue(np.array_equal(debut, stream.image_vue3d(images, 4 / 6, 6.0)))
            self.assertFalse(np.array_equal(debut, stream.image_vue3d(images, 1 / 6, 6.0)))
            # Et un \u00e2ge n\u00e9gatif ne fait pas sortir du tableau.
            self.assertIsNotNone(stream.image_vue3d(images, -5.0, 6.0))
        self.assertIsNone(stream.image_vue3d([], 0.0, 6.0))

        toile = np.zeros((420, 1600, 3), np.uint8)
        stream.pose_horloge(toile, 1_790_000_000.0, direct=False, autre="3D MODEL")
        direct = np.zeros((420, 1600, 3), np.uint8)
        stream.pose_horloge(direct, 1_790_000_000.0, direct=True)
        self.assertFalse(np.array_equal(toile, direct))

    def test_the_flyover_never_covers_something_that_moves(self):
        """On n'a pas pass\u00e9 des semaines \u00e0 ne pas rater une voiture pour la cacher."""
        source = inspect.getsource(stream.diffuse)
        # L'interruption est dans la m\u00eame condition que la fin du compte \u00e0
        # rebours : s\u00e9par\u00e9es, l'une pourrait un jour \u00eatre d\u00e9plac\u00e9e sans l'autre.
        self.assertIn("if survol is not None and (poses or", source)
        self.assertIn("or quand - survol > VUE3D_TENUE_S)", source)
        self.assertLess(stream.VUE3D_TENUE_S, stream.VUE3D_PAUSE_S / 4,
                        "le survol doit rester une respiration, pas un programme")

    def test_a_verdict_survives_the_watch_writing_its_counters(self):
        """Quatre-vingt-quatorze verdicts effac\u00e9s quelques secondes apr\u00e8s coup.

        La veille r\u00e9\u00e9crivait le fichier entier \u00e0 chaque passage, comptes de
        relecture compris, alors qu'elle ne les incr\u00e9mente jamais : elle y
        remettait la valeur qu'ils avaient \u00e0 son d\u00e9marrage, c'est-\u00e0-dire z\u00e9ro,
        puisque son \u00e9tat vient d'un autre fichier qui ne les porte pas.
        """
        from watcher.memory import Memory
        with tempfile.TemporaryDirectory() as coin:
            chemin = Path(coin) / "learning.json"
            chemin.write_text(json.dumps({"seen": 10, "named": 2,
                                          "accepted": 94, "rejected": 9}),
                              encoding="utf-8")
            memoire = Memory(chemin)
            memoire.observe("road", (0.5, 0.5),
                            Decision("publish", "vehicle", "Voiture", "car", {}, 0.8))
            ecrit = json.loads(chemin.read_text(encoding="utf-8"))
            self.assertEqual(ecrit["accepted"], 94)
            self.assertEqual(ecrit["rejected"], 9)
            self.assertEqual(ecrit["seen"], 11, "ses propres comptes avancent")
            # Et un verdict rendu pendant que la veille tourne n'est pas perdu
            # non plus : elle relit le disque, elle ne se souvient pas.
            chemin.write_text(json.dumps({**ecrit, "accepted": 95}), encoding="utf-8")
            memoire.observe("road", (0.5, 0.5),
                            Decision("publish", "vehicle", "Voiture", "car", {}, 0.8))
            self.assertEqual(json.loads(chemin.read_text(encoding="utf-8"))["accepted"], 95)

    def test_a_miss_is_never_celebrated_as_a_catch(self):
        """« Décor connu » est un raté rangé, pas une prise. Et le feu ne se fête pas."""
        self.assertNotIn("missed", stream.PRISES)
        self.assertNotIn("motion", stream.PRISES)
        self.assertNotIn("fire", stream.PRISES)
        for vrai in ("vehicle", "person", "truck", "cycle"):
            self.assertIn(vrai, stream.PRISES)
        for refus in ("missed", "motion", "fire"):
            fiche = {"t": 1000.0, "type": refus, "label": "Décor connu",
                     "box": [0.4, 0.8, 0.1, 0.1]}
            self.assertIsNone(stream.prise_a_feter([fiche], 1001.0, set()),
                              f"{refus} ne se fête pas")

    def test_the_catch_says_what_it_caught(self):
        """« Good catch » tout seul félicite sans dire de quoi."""
        fond = np.full((360, 640, 3), 40, np.uint8)
        muet = fond.copy()
        stream.pose_attrape(muet, 0.3)
        nomme = fond.copy()
        stream.pose_attrape(nomme, 0.3, "Voiture verte")
        self.assertFalse(np.array_equal(muet, nomme),
                         "le nom doit apparaître sous le mot")
        # Et il reste dans le cadre, sans déborder sur les bandes.
        self.assertTrue(np.array_equal(nomme[:, :40], muet[:, :40]))

    def test_the_catch_flash_fades_instead_of_veiling_the_view(self):
        """L'éclair doit retomber : une lumière qui reste cache la montagne."""
        fond = np.full((360, 640, 3), 40, np.uint8)
        debut = fond.copy()
        stream.pose_attrape(debut, 0.0)
        tard = fond.copy()
        stream.pose_attrape(tard, stream.ATTRAPE_S * 0.95)
        fini = fond.copy()
        stream.pose_attrape(fini, stream.ATTRAPE_S + 0.1)

        self.assertGreater(float(debut.mean()), float(fond.mean()) + 20)
        self.assertLess(float(tard.mean()), float(debut.mean()))
        self.assertTrue(np.array_equal(fini, fond))

    def test_the_replay_branch_still_hangs_off_the_drawing(self):
        """Le « elif » des rediffusions doit suivre « dessine », rien d'autre.

        Glisser une ligne entre les deux rend le fichier parfaitement valide et
        change tout : la rediffusion se déclenche alors sur l'absence d'un
        effet à l'écran au lieu de l'absence d'une détection. C'est arrivé.
        """
        lignes = inspect.getsource(stream.diffuse).splitlines()
        [i] = [i for i, l in enumerate(lignes) if l.strip() == "if poses:"]
        [j] = [j for j, l in enumerate(lignes) if l.strip().startswith("elif quand - dernier_vu")]
        entre = [l for l in lignes[i + 1:j] if l.strip() and not l.strip().startswith("#")]
        retrait = len(lignes[i]) - len(lignes[i].lstrip())
        self.assertTrue(all(len(l) - len(l.lstrip()) > retrait for l in entre), entre)

    def test_every_shape_effect_is_offered_and_none_is_permanent(self):
        """Un seul effet à la fois, et du net assez souvent pour que ça compte."""
        from collections import Counter
        vus = Counter(stream.effet_du_moment(b * stream.PIXEL_CYCLE_S + 10)[0]
                      for b in range(400))
        for effet in ("pixel", "gris", "ondule"):
            self.assertGreater(vus[effet], 20, vus)
        self.assertGreater(vus[""], 100, vus)

    def test_the_wave_slides_the_picture_without_losing_any_of_it(self):
        """Une bande décalée revient par l'autre bord : rien ne sort du cadre."""
        image = np.random.default_rng(1).integers(0, 255, (360, 640, 3), dtype=np.uint8)
        plie = image.copy()
        stream.ondule(plie, 1.0, 3.0)
        self.assertFalse(np.array_equal(plie, image))
        self.assertEqual(sorted(plie.reshape(-1).tolist()), sorted(image.reshape(-1).tolist()))
        rien = image.copy()
        stream.ondule(rien, 0.0, 3.0)
        self.assertTrue(np.array_equal(rien, image))

    def test_grey_uses_perceived_brightness_and_not_an_average(self):
        """Un ciel bleu et une prairie verte n'ont pas la même clarté à l'œil."""
        bleu = np.zeros((8, 8, 3), np.uint8)
        bleu[:, :, 0] = 160
        vert = np.zeros((8, 8, 3), np.uint8)
        vert[:, :, 1] = 160
        for image in (bleu, vert):
            stream.gris(image, 1.0)
        self.assertNotEqual(int(bleu[0, 0, 0]), int(vert[0, 0, 0]))
        self.assertGreater(int(vert[0, 0, 0]), int(bleu[0, 0, 0]))

    def test_the_drawn_sun_is_always_on_the_side_the_real_one_is_on(self):
        """Le dessin est naïf ; le côté, lui, est mesuré.

        C'est le seul engagement du soleil au crayon : à l'est le matin, à
        l'ouest le soir. S'il se trompe de côté, ce n'est plus de la candeur,
        c'est une erreur d'orientation — et ce flux en publie en mètres.
        """
        camera = {"lat": 44.1835, "lon": 5.2621, "bearing": 140, "fov": 90, "pitch": 0}
        paris = ZoneInfo("Europe/Paris")
        matin = datetime(2026, 7, 15, 8, 0, tzinfo=paris).timestamp()
        soir = datetime(2026, 7, 15, 18, 0, tzinfo=paris).timestamp()
        gauche = stream.ou_est_le_soleil(camera, matin, 9 / 16)
        droite = stream.ou_est_le_soleil(camera, soir, 9 / 16)
        self.assertLess(gauche[0], 0.5)
        self.assertGreater(droite[0], 0.5)

    def test_the_drawn_sun_never_lands_on_the_mountain(self):
        """Un soleil planté dans un versant est un dessin faux, pas un dessin d'enfant."""
        camera = {"lat": 44.1835, "lon": 5.2621, "bearing": 140, "fov": 90, "pitch": 0}
        paris = ZoneInfo("Europe/Paris")
        for mois in range(1, 13):
            for heure in range(5, 22):
                quand = datetime(2026, mois, 10, heure, 0, tzinfo=paris).timestamp()
                ou = stream.ou_est_le_soleil(camera, quand, 9 / 16)
                if ou is None:
                    continue
                self.assertLess(ou[1], stream.SOLEIL_CIEL, (mois, heure))
                self.assertTrue(0.05 < ou[0] < 0.95, (mois, heure))

    def test_the_shadow_of_the_mountain_counts_as_having_no_sun(self):
        """Levé n'est pas arrivé : le versant nord reste noir une heure de plus.

        Le premier octobre, le soleil passe l'horizon à 7 h 35 et la crête du
        Ventoux vers 8 h 30. Entre les deux, la météo dit « ciel dégagé » et
        il n'y a pas de soleil sur la scène — c'est ce qui a été constaté à
        l'écran, et c'est le relief, pas le bulletin, qui le sait.
        """
        camera = {"lat": 44.1835, "lon": 5.2621, "ele": 1390}
        paris = ZoneInfo("Europe/Paris")

        class Crete:
            def skyline(self, azimut, oeil):
                return 18.0

        avant = datetime(2026, 10, 1, 8, 0, tzinfo=paris).timestamp()
        apres = datetime(2026, 10, 1, 11, 0, tzinfo=paris).timestamp()
        self.assertTrue(stream.soleil_absent(Crete(), camera, avant, "ciel dégagé"))
        self.assertFalse(stream.soleil_absent(Crete(), camera, apres, "ciel dégagé"))
        # Sous les nuages, il n'y est pour personne, crête ou pas.
        self.assertTrue(stream.soleil_absent(Crete(), camera, apres, "couvert"))
        # Et sans modèle de terrain le flux continue, il perd juste l'ombre.
        self.assertFalse(stream.soleil_absent(None, camera, avant, "ciel dégagé"))

    def test_a_missing_webcam_never_takes_the_broadcast_down_with_it(self):
        """Deux minutes de 404 ont coûté le direct : on attend, on ne ressort pas.

        Chaque redémarrage rouvrait puis refermait la connexion vers YouTube, et
        une arrivée qui clignote huit fois en deux minutes est une diffusion que
        YouTube termine. La panne venait d'ailleurs ; c'est notre façon d'y
        répondre qui a coûté quelque chose.
        """
        essais = []

        def capricieuse(url):
            essais.append(url)
            if len(essais) < 3:
                raise OSError("HTTP Error 404: Not Found")
            return "media.m3u8"

        with mock.patch.object(stream, "playlist_media", capricieuse), \
                mock.patch.object(stream, "bord_du_direct", lambda _: (1000.0, 7.0)), \
                mock.patch.object(stream.time, "sleep", lambda _: None):
            media, dernier, segment = stream.attends_la_webcam("http://camera/x.m3u8")
        self.assertEqual((media, dernier, segment), ("media.m3u8", 1000.0, 7.0))
        self.assertEqual(len(essais), 3)

    def test_the_wait_for_the_webcam_gives_up_eventually(self):
        """Passé une demi-heure ce n'est plus une absence, c'est une panne."""
        horloge = iter([0.0] + [i * 60.0 for i in range(1, 60)])

        with mock.patch.object(stream, "playlist_media",
                               mock.Mock(side_effect=OSError("muette"))), \
                mock.patch.object(stream, "_maintenant", lambda: next(horloge)), \
                mock.patch.object(stream.time, "sleep", lambda _: None):
            with self.assertRaises(RuntimeError):
                stream.attends_la_webcam("http://camera/x.m3u8")

    def test_pushing_into_a_void_gets_said_out_loud(self):
        """Quatre heures d'emission dans le vide avec un journal irreprochable.

        Une diffusion terminee par YouTube ne se voit pas depuis le Pi : l'arrivee
        accepte toujours les octets. La seule facon de l'apprendre est de regarder
        la chaine du dehors.
        """
        coupe = threading.Event()
        attentes = []

        def patiente(_):
            attentes.append(1)
            if len(attentes) > 3:
                coupe.set()
            return coupe.is_set()

        with mock.patch.object(stream, "direct_visible", lambda _: False), \
                mock.patch.object(coupe, "wait", patiente), \
                self.assertLogs(stream.log, level="ERROR") as journal:
            stream.veille_le_direct("UCxxxx", coupe)
        cris = [m for m in journal.output if "dans le vide" in m]
        self.assertEqual(len(cris), 1, "on le dit une fois, pas a chaque tour")

    def test_a_channel_we_cannot_read_is_never_declared_dead(self):
        """« Je ne sais pas » n'est pas « non ».

        Un direct prive est invisible du dehors, et une page qui repond mal l'est
        aussi. Crier sur une incertitude, c'est apprendre a l'utilisateur a ne
        plus nous croire.
        """
        coupe = threading.Event()
        tours = []

        def patiente(_):
            tours.append(1)
            if len(tours) > 5:
                coupe.set()
            return coupe.is_set()

        with mock.patch.object(stream, "direct_visible", lambda _: None), \
                mock.patch.object(coupe, "wait", patiente):
            with self.assertNoLogs(stream.log, level="ERROR"):
                stream.veille_le_direct("UCxxxx", coupe)

    def test_a_refusal_never_gets_a_red_box_on_the_stream(self):
        """Un rectangle rouge dit « j'ai vu ceci », pas « je n'ai rien su lire »."""
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "events.json"
            boite = {"box": [0.1, 0.1, 0.2, 0.2]}
            chemin.write_text(json.dumps({"events": [
                {"t": "2026-10-01T06:00:00Z", "type": "missed",
                 "label": "Immobile sur la pente", "detail": boite},
                {"t": "2026-10-01T06:00:02Z", "type": "car",
                 "label": "Voiture blanche", "detail": boite},
            ]}), encoding="utf-8")
            vus = stream.identifications(chemin, 0.0)
        self.assertEqual([v["label"] for v in vus], ["Voiture blanche"])

    def test_an_absence_is_never_put_up_for_judgement(self):
        """« Immobile sur la pente » ne demande rien à personne : rien n'y était."""
        from watcher.main import _worth_keeping

        for motif in ("none", "unclassified", "sky_still", "slope_still",
                      "against_the_ground", "repeated_spot"):
            self.assertIn(motif, RIEN_A_JUGER)
            self.assertFalse(_worth_keeping(motif, {"sample_refused_s": 60}, {}, 0.0))
        # Celui-là affirme quelque chose, et peut donc se tromper.
        self.assertNotIn("tarmac", RIEN_A_JUGER)
        self.assertTrue(_worth_keeping("tarmac", {"sample_refused_s": 60}, {}, 1e9))

    def test_the_drawn_sun_stays_in_the_sky_and_leaves_the_road_alone(self):
        """Il est dessiné dans le ciel : le bas de l'image ne doit pas bouger."""
        image = np.full((360, 640, 3), 120, np.uint8)
        stream.pose_soleil_dessine(image, (0.2, 0.15), 3.0)
        self.assertTrue(np.any(image[:180] != 120))
        self.assertTrue(np.all(image[250:] == 120))

    def test_a_replay_only_shows_what_a_human_confirmed(self):
        """Une rediffusion est présentée comme un fait : elle doit en être un."""
        source = inspect.getsource(stream.archives)
        self.assertIn('fiche.get("review") != "accepted"', source)

    def test_the_pixels_never_last_more_than_twenty_seconds(self):
        """Vingt secondes est une expérience, deux minutes est une panne."""
        self.assertEqual(stream.PIXEL_S, 20.0)
        for bloc in range(12):
            debut = bloc * stream.PIXEL_CYCLE_S
            dedans = [d / 2 for d in range(0, int(stream.PIXEL_CYCLE_S) * 2)
                      if _force(debut + d / 2) > 0]
            self.assertLessEqual(len(dedans) / 2, stream.PIXEL_S, bloc)

    def test_the_pixels_come_and_go_instead_of_snapping(self):
        """Un grain qui apparaît d'un coup se lit comme un encodeur qui lâche."""
        actif = next(b for b in range(12)
                     if _force(b * stream.PIXEL_CYCLE_S + 10) > 0)
        debut = actif * stream.PIXEL_CYCLE_S
        self.assertEqual(_force(debut), 0.0)
        self.assertLess(_force(debut + 1), _force(debut + 10))
        self.assertGreater(_force(debut + 10),
                           _force(debut + stream.PIXEL_S - 1))
        self.assertEqual(_force(debut + stream.PIXEL_S + 1), 0.0)
        # Et pas à tous les créneaux, sinon c'est le rendu normal du flux.
        self.assertTrue(any(_force(b * stream.PIXEL_CYCLE_S + 10) == 0
                            for b in range(12)))

    def test_the_pixels_keep_away_from_anything_caught(self):
        """Un rectangle rouge sert à regarder ce qu'il entoure."""
        source = inspect.getsource(stream.diffuse)
        appel = [l for l in source.splitlines() if "applique_effet(" in l]
        self.assertTrue(appel)
        garde = source.split("applique_effet(")[0].splitlines()[-3:]
        self.assertTrue(any("dernier_vu > TENUE_S" in l for l in garde), garde)

    def test_the_pixels_keep_the_picture_readable(self):
        """Gros carrés, mais la crête et la route restent des formes."""
        # Deux résolutions, parce que le réglage se compte en blocs et doit
        # donner la même image sur l'une et sur l'autre.
        for largeur, hauteur in ((1920, 1080), (1280, 720)):
            # Un dégradé, pas du bruit : du bruit moyenné sur un bloc donne
            # toujours le même gris, et les blocs deviendraient indiscernables
            # pour une raison qui ne doit rien à la fonction testée.
            rampe = np.linspace(0, 255, largeur, dtype=np.uint8)
            image = np.repeat(np.tile(rampe, (hauteur, 1))[:, :, None], 3, axis=2)
            fort = image.copy()
            stream.pixellise(fort, 1.0)
            self.assertEqual(fort.shape, image.shape)
            blocs = len(np.unique(fort[hauteur // 2], axis=0))
            self.assertGreaterEqual(blocs, stream.PIXEL_BLOCS - 2, largeur)
            self.assertLessEqual(blocs, stream.PIXEL_BLOCS + 2, largeur)
        rien = image.copy()
        stream.pixellise(rien, 0.0)
        self.assertTrue(np.array_equal(rien, image))

    def test_the_dancers_wait_for_the_music_to_push(self):
        """Pas de pantins sur un morceau calme, et une entrée en fondu."""
        self.assertLess(stream.DANSE_ARRET, stream.DANSE_SEUIL)
        fond = np.full((400, 700, 3), 70, np.uint8)
        calme = fond.copy()
        stream.pose_danseurs(calme, 3.0, stream.DANSE_ARRET - 0.01)
        self.assertTrue(np.array_equal(calme, fond))

        entre = fond.copy()
        stream.pose_danseurs(entre, 3.0, (stream.DANSE_ARRET + stream.DANSE_SEUIL) / 2)
        fort = fond.copy()
        stream.pose_danseurs(fort, 3.0, stream.DANSE_SEUIL + 0.2)
        ecart = lambda im: float(np.abs(im.astype(int) - fond).mean())
        self.assertGreater(ecart(entre), 0.0)
        self.assertGreater(ecart(fort), ecart(entre))

    def test_the_dancers_stay_in_the_corners_of_the_view(self):
        """Le milieu de l'image appartient à la montagne, pas aux pantins."""
        fond = np.full((400, 700, 3), 70, np.uint8)
        dessus = fond.copy()
        stream.pose_danseurs(dessus, 3.0, 0.3)
        milieu = dessus[:, 230:470]
        self.assertTrue(np.array_equal(milieu, fond[:, 230:470]))

    def test_the_beat_is_measured_on_the_samples_actually_served(self):
        """L'énergie vient du son servi, sinon elle danse deux secondes avant."""
        musique = stream.Musique.__new__(stream.Musique)
        musique._verrou = threading.Lock()
        musique.energie = 0.0
        silence = np.zeros(4000, np.int16).tobytes()
        fort = (np.ones(4000, np.int16) * 16000).tobytes()

        for _ in range(60):
            musique._mesure(fort)
        self.assertGreater(musique.pouls(), stream.DANSE_SEUIL)
        for _ in range(60):
            musique._mesure(silence)
        self.assertLess(musique.pouls(), stream.DANSE_ARRET)

        source = inspect.getsource(stream.Musique.tranche)
        self.assertIn("self._mesure(servi)", source)

    def test_the_machine_panel_colours_the_heat_on_the_chip_s_own_limits(self):
        """Vert, ambre, rouge : les seuils sont ceux du Pi, pas un goût à moi."""
        self.assertLess(stream.TIEDE_C, stream.CHAUD_C)
        self.assertLess(stream.CHAUD_C, 80.0)
        for degres, attendu in ((48.0, stream.VERT), (70.0, stream.AMBRE), (82.0, stream.ROUGE)):
            toile = np.zeros((300, 900, 3), np.uint8)
            stream.pose_machine(toile, {"degres": degres, "charge": 0.3,
                                        "debout": 90_000.0, "libre": 800e9})
            pixels = toile.reshape(-1, 3)
            vifs = pixels[pixels.max(axis=1) > 150]
            self.assertTrue(any(tuple(p) == attendu for p in vifs), degres)

    def test_the_machine_panel_stays_away_when_there_is_no_machine_to_read(self):
        """Pas de /sys, pas d'encart : inventer une température serait mentir."""
        toile = np.zeros((300, 900, 3), np.uint8)
        stream.pose_machine(toile, None)
        self.assertFalse(toile.any())

    def test_good_morning_fires_once_when_the_sun_clears_the_horizon(self):
        """Le lever est calculé, franchi vers le haut, et pas deux fois par jour."""
        source = inspect.getsource(stream.diffuse)
        self.assertIn("hauteur_soleil < HORIZON <= haut", source)
        # Douze heures de garde : un soleil qui oscille autour de l'horizon
        # une seconde sur deux ne doit pas dire bonjour une seconde sur deux.
        self.assertIn("quand - bonjour > 12 * 3600", source)
        self.assertAlmostEqual(stream.HORIZON, -0.833, places=3)

    def test_good_morning_appears_and_leaves_without_blinking(self):
        fond = np.full((360, 640, 3), 30, np.uint8)
        milieu = fond.copy()
        stream.pose_bonjour(milieu, "Ventoux", stream.BONJOUR_S / 2)
        bord = fond.copy()
        stream.pose_bonjour(bord, "Ventoux", 0.05)
        fini = fond.copy()
        stream.pose_bonjour(fini, "Ventoux", stream.BONJOUR_S + 0.1)

        self.assertFalse(np.array_equal(milieu, fond))
        self.assertLess(float(np.abs(bord.astype(int) - fond).mean()),
                        float(np.abs(milieu.astype(int) - fond).mean()))
        self.assertTrue(np.array_equal(fini, fond))

    def test_the_clock_names_the_city_and_not_the_abbreviation(self):
        """« CEST » ne dit rien à personne, et change de nom deux fois par an."""
        toile = np.zeros((300, 900, 3), np.uint8)
        stream.pose_horloge(toile, 1_760_000_000.0)
        source = inspect.getsource(stream.pose_horloge)
        self.assertIn('" PARIS"', source)
        self.assertNotIn('strftime("%Z")', source)

    def test_boredom_is_measured_on_the_road_and_not_on_the_screen(self):
        """L'horloge de l'ennui ne doit pas être celle des rediffusions.

        « dernier_vu » est remis à zéro quand une rediffusion s'achève, pour
        espacer les suivantes. S'en servir pour l'ennui ferait dire « boring »
        vingt minutes après une rediffusion, c'est-à-dire juste après qu'il
        s'est passé quelque chose à l'écran. Ce test fige la séparation.
        """
        source = inspect.getsource(stream.diffuse)
        # Les deux horloges existent et sont distinctes.
        self.assertIn("dernier_mouvement", source)
        self.assertIn("dernier_vu", source)
        # L'ennui se décide sur la seule horloge que les rediffusions ne
        # touchent pas.
        declenchement = [l for l in source.splitlines() if "ENNUI_S" in l and "quand -" in l]
        self.assertTrue(declenchement)
        self.assertTrue(all("dernier_vu" not in l for l in declenchement), declenchement)
        # Et la remise à zéro de « dernier_mouvement » n'arrive qu'après une
        # vraie détection, jamais dans le bloc des rediffusions.
        apres_dessine = source.split("if poses:")[1].split("elif")[0]
        self.assertIn("dernier_mouvement = quand", apres_dessine)

    def test_the_credit_follows_the_music_from_one_track_to_the_next(self):
        """CC-BY se paie à l'écran, sur le morceau qui passe.

        Le compte se fait sur les octets versés, donc une erreur d'une seconde
        au passage d'un titre créditerait le mauvais auteur. On vérifie les
        deux bords.
        """
        suite = [{"f": "a.mp3", "d": 120.0}, {"f": "b.mp3", "d": 90.0}]
        fiches = {"a.mp3": {"auteur": "Nemeton", "titre": "01nocti27", "licence": "CC BY 4.0"},
                  "b.mp3": {"auteur": "Naxar", "titre": "Night Sky", "licence": "CC BY-SA 3.0"}}
        self.assertIn("Nemeton", stream.qui_passe(suite, fiches, 0.0))
        self.assertIn("Nemeton", stream.qui_passe(suite, fiches, 119.9))
        self.assertIn("Naxar", stream.qui_passe(suite, fiches, 120.1))
        self.assertIn("CC BY-SA 3.0", stream.qui_passe(suite, fiches, 200.0))
        # Passé la session, et pour un morceau sans fiche, on se tait plutôt
        # que de créditer au hasard : un faux crédit est pire que pas de crédit.
        self.assertEqual(stream.qui_passe(suite, fiches, 400.0), "")
        self.assertEqual(stream.qui_passe(suite, {}, 10.0), "")

    def test_an_empty_library_does_not_stop_the_stream(self):
        # Le silence vaut mieux que pas d'image : la veille est le produit.
        with tempfile.TemporaryDirectory() as dossier:
            self.assertIsNone(stream.batir_session(Path(dossier)))
        self.assertIsNone(stream.batir_session(Path("/inexistant/nulle/part")))


class RecouvrementTests(unittest.TestCase):
    """Une lecture qui ne recouvre rien de ce qui a bougé parle d'autre chose."""

    def _tache(self, **extra):
        base = dict(zone="road", travel=0.2, duration_s=6.0, area_ratio=0.002,
                    width_m=4.0, height_m=1.8, frames=4, min_travel=0.01, cross_rate=0.034)
        base.update(extra)
        return base

    def test_a_reading_that_touches_none_of_the_motion_cannot_name_it(self):
        """Le 29 septembre à 12 h 33, un « car » de cinq pixels sur cinq, à
        quatre cents pixels de la tache, a publié « Voiture ». La réponse était
        juste et la raison ne valait rien."""
        ailleurs = Detection("car", 0.9, share=0.0)
        self.assertNotEqual(decide(Observation(**self._tache(), detections=[ailleurs])).type, "vehicle")
        dessus = Detection("car", 0.9, share=0.8)
        self.assertEqual(decide(Observation(**self._tache(), detections=[dessus])).type, "vehicle")

    def test_a_blob_swollen_by_its_shadow_still_gets_named(self):
        """On ne touche qu'au zéro, pas au cinquième.

        Une voiture qui traîne son ombre ne recouvre qu'une part de la tache
        qu'elle a produite ; elle en recouvre toujours quelque chose.
        """
        maigre = Detection("car", 0.9, share=0.08)
        self.assertEqual(decide(Observation(**self._tache(), detections=[maigre])).type, "vehicle")

    def test_a_reading_without_a_box_keeps_its_say(self):
        """Faute de boîte, la part vaut un par défaut et non zéro : on ne sait
        pas où la lecture s'est posée, et un « on ne sait pas » ne témoigne pas
        à charge."""
        self.assertEqual(Detection("car", 0.9).share, 1.0)
        self.assertEqual(decide(Observation(**self._tache(),
                                            detections=[Detection("car", 0.9)])).type, "vehicle")

    def test_the_size_rules_vanish_but_the_overlap_rule_does_not(self):
        """Le trou par lequel le trampoline est passé.

        Au-dessus du doute de distance, les tailles s'effacent — à raison — et
        plus rien ne contredisait le modèle. Le recouvrement, lui, se lit dans
        l'image seule : aucune distance, aucun relevé, et il tient sur toutes
        les caméras à venir.
        """
        loin = self._tache(zone="other", width_m=6.6, height_m=8.1,
                           distance_doubt=SIZE_DOUBT_MAX + 0.4, travel=0.135)
        faux = Detection("person", 0.56, share=0.0)
        self.assertNotEqual(decide(Observation(**loin, detections=[faux])).type, "person")


class DescriptionDeChaine(unittest.TestCase):
    """Ce qu'on écrit sous la vidéo, et ce que YouTube en fait."""

    CREDITS = {
        "a.mp3": {"auteur": "#NarNaöud#", "titre": "Bongo Jazzy",
                  "licence": "Licence Art Libre", "source": "Dogmazic",
                  "url": "https://play.dogmazic.net/song.php?song_id=1"},
        "b.mp3": {"auteur": "Aloges", "titre": "Solitude", "source": "Dogmazic",
                  "licence": "Creative Commons - by 3.0", "url": ""},
        "c.mp3": {"auteur": "thepriben", "titre": "Mont Serein 002.01",
                  "licence": "CC0"},
    }

    def test_every_artist_is_named_and_their_licence_given(self):
        from scripts.description_youtube import description
        texte = description(self.CREDITS)
        for fiche in self.CREDITS.values():
            self.assertIn(fiche["auteur"], texte)
        self.assertIn("Licence Art Libre", texte)
        self.assertIn("CC BY 3.0", texte)

    def test_an_artist_name_cannot_cancel_the_hashtags(self):
        """« #NarNaöud# » est un nom, mais YouTube y lit un mot-dièse.

        Au-delà de quinze il les ignore tous, les nôtres compris : un nom
        propre pouvait donc effacer la liste entière.
        """
        from scripts.description_youtube import MAX_DIESE, description
        texte = description(self.CREDITS)
        self.assertLessEqual(len(re.findall(r"#\w", texte)), MAX_DIESE)
        self.assertIn("#MontVentoux", texte)

    def test_a_long_list_is_cut_between_artists_and_says_so(self):
        gros = {f"{i}.mp3": {"auteur": f"Artiste numéro {i}", "titre": "x" * 60,
                             "licence": "CC0", "source": "Dogmazic", "url": ""}
                for i in range(400)}
        from scripts.description_youtube import description
        texte = description(gros, limite=5000)
        self.assertLessEqual(len(texte), 5000)
        self.assertIn("more tracks", texte)

    def test_the_watch_never_promises_to_watch_for_anything(self):
        """La chaîne est une caméra, pas un service d'alerte. On le dit."""
        from scripts.description_youtube import description
        texte = description(self.CREDITS).lower()
        self.assertIn("not a monitoring service", texte)
        self.assertNotIn("fire", texte)


class PantinsAilleurs(unittest.TestCase):
    """Les deux danseurs, quand ils sortent du cadre de l'antenne."""

    def _ou_dansent_ils(self, seconde: float = 4.0, **reglages):
        from watcher.stream import pose_danseurs
        image = np.zeros((1920, 1080, 3), np.uint8)
        pose_danseurs(image, seconde, 0.20, **reglages)
        dessine = np.argwhere(image.any(axis=2))
        self.assertTrue(dessine.size, "rien n'a été dessiné")
        return dessine[:, 0].max(), dessine[:, 1].max()

    def test_the_dancers_stand_on_the_floor_they_are_given(self):
        """Sur un Short, le bas de l'écran appartient à l'application.

        Le titre de la vidéo et le nom de la chaîne couvrent le dernier
        cinquième, et les boutons une colonne à droite : aux valeurs de
        l'antenne les pantins dansent derrière l'interface, donc nulle part.
        """
        from scripts.short_danse import DANSE_HAUT, DANSE_MARGE, DANSE_SOL
        pire_bas = pire_droite = 0
        for pas in range(40):
            bas, droite = self._ou_dansent_ils(
                seconde=pas * 0.13, sol=DANSE_SOL, marge=DANSE_MARGE,
                haut=DANSE_HAUT)
            pire_bas, pire_droite = max(pire_bas, bas), max(pire_droite, droite)
        self.assertLessEqual(pire_bas, 1920 * 0.80)
        self.assertLess(pire_droite, 1080 * 0.85)
        bas_antenne, _ = self._ou_dansent_ils()
        self.assertGreater(bas_antenne, pire_bas)

    def test_the_stream_keeps_its_own_placing(self):
        """Les réglages par défaut sont ceux du direct, qui ne bouge pas."""
        import inspect
        from watcher.stream import pose_danseurs
        defauts = inspect.signature(pose_danseurs).parameters
        self.assertEqual(defauts["sol"].default, 0.93)
        self.assertEqual(defauts["marge"].default, 0.10)


class DeploiementSansCouper(unittest.TestCase):
    """Le déploiement a tué la diffusion deux fois le premier octobre."""

    def test_the_stream_is_not_restarted_for_every_change(self):
        """La veille redémarre librement, le flux non.

        La veille écrit des fichiers et ne touche pas à l'antenne ; le flux
        tient la connexion que YouTube surveille. Les traiter pareil est ce
        qui a terminé la diffusion à dix-huit heures, en trois coupures pour
        trois corrections que rien n'obligeait à livrer séparément.
        """
        from scripts import deploie
        appels = []
        with mock.patch.object(deploie, "_ssh", lambda c, muet=False: appels.append(c) or ""), \
             mock.patch.object(deploie.subprocess, "run"):
            deploie.main([])
        restarts = [c for c in appels if "restart" in c]
        self.assertEqual(restarts, ["sudo systemctl restart ventoux-watch"])

    def test_a_stream_too_freshly_started_is_left_alone(self):
        """Trois coupures en vingt-cinq minutes terminent la diffusion."""
        from scripts import deploie
        appels = []
        with mock.patch.object(deploie, "_ssh", lambda c, muet=False: appels.append(c) or ""), \
             mock.patch.object(deploie, "depuis_quand", lambda s: 600.0), \
             mock.patch.object(deploie.subprocess, "run"):
            code = deploie.main(["--flux"])
        self.assertEqual(code, 2)
        self.assertNotIn("sudo systemctl restart ventoux-stream", appels)

    def test_the_rest_can_be_overridden_on_purpose(self):
        from scripts import deploie
        appels = []
        with mock.patch.object(deploie, "_ssh", lambda c, muet=False: appels.append(c) or ""), \
             mock.patch.object(deploie, "depuis_quand", lambda s: 10.0), \
             mock.patch.object(deploie, "chaine_en_direct", lambda: True), \
             mock.patch.object(deploie.time, "sleep", lambda s: None), \
             mock.patch.object(deploie.subprocess, "run"):
            deploie.main(["--flux", "--quand-meme"])
        self.assertIn("sudo systemctl restart ventoux-stream", appels)


class LeSonNeTuePasLImage(unittest.TestCase):
    """Le premier octobre à vingt heures, la musique a emporté la diffusion."""

    def _musique(self):
        from watcher.stream import Musique
        with tempfile.TemporaryDirectory() as dossier:
            yield Musique(Path(dossier), Path(dossier), muet=True)

    def test_the_music_knows_how_to_stop(self):
        """« arrete » était échouée dans qui_passe, après son return.

        Inaccessible, et donc absente de la classe : les deux appels — la fin
        de session et l'arrêt du programme — levaient une AttributeError.
        """
        from watcher.stream import Musique, qui_passe
        self.assertTrue(callable(getattr(Musique, "arrete", None)))
        self.assertFalse(hasattr(qui_passe, "arrete"))

    def test_a_track_deleted_under_the_player_only_costs_silence(self):
        """Nettoyer la bibliothèque sans redémarrer ne doit rien coûter.

        Un fichier effacé pendant qu'on joue fait une lecture courte, donc le
        chemin de bascule ; si ce chemin lève, le fil du son meurt, l'écriture
        de l'image casse derrière et la diffusion se termine.
        """
        from watcher.stream import Musique
        with tempfile.TemporaryDirectory() as dossier:
            musique = Musique(Path(dossier), Path(dossier), muet=True)

            class Tari:
                stdout = io.BytesIO(b"\x01\x02")

                def kill(self):
                    raise RuntimeError("le lecteur a déjà disparu")

            musique.process = Tari()
            morceau = musique.tranche(4096)
        self.assertEqual(len(morceau), 4096)

    def test_the_audio_thread_never_takes_the_picture_down_with_it(self):
        from watcher.stream import _verse_le_son
        lecture, ecriture = os.pipe()
        coupe = threading.Event()
        essais = []

        class Cassee:
            def tranche(self, octets):
                essais.append(octets)
                if len(essais) == 1:
                    raise RuntimeError("plus de musique du tout")
                coupe.set()
                return b"\0" * octets

        try:
            _verse_le_son(ecriture, Cassee(), coupe)
        finally:
            os.close(lecture)
            os.close(ecriture)
        # Il a survécu au premier accident et versé la tranche suivante.
        self.assertEqual(len(essais), 2)


class LeRubanEtLeSoleilCouche(unittest.TestCase):
    """Le ruban a donné pour imminente une heure passée depuis treize heures."""

    HEURES = {"lever": 1000.0, "crete_matin": 2000.0,
              "crete_soir": 8000.0, "coucher": 9000.0}
    # Pas 2000 + 86400 : la même heure d'horloge à un jour d'écart rendait le
    # test incapable de distinguer aujourd'hui de demain.
    DEMAIN = {"lever": 87520.0, "crete_matin": 88520.0}

    def test_after_sunset_the_ribbon_looks_at_tomorrow(self):
        from watcher.stream import morceaux_soleil
        dit = "".join(bout for bout, _ in
                      morceaux_soleil(self.HEURES, 9500.0, self.DEMAIN))
        self.assertIn("TOMORROW", dit)
        from watcher.stream import _hhmm
        self.assertIn(_hhmm(self.DEMAIN["crete_matin"]), dit)
        self.assertNotIn(_hhmm(self.HEURES["crete_matin"]), dit)

    def test_without_tomorrow_it_says_nothing_rather_than_something_false(self):
        from watcher.stream import morceaux_soleil
        self.assertEqual(morceaux_soleil(self.HEURES, 9500.0), [])
        self.assertEqual(morceaux_soleil(self.HEURES, 9500.0, {}), [])

    def test_the_daytime_lines_are_untouched(self):
        from watcher.stream import morceaux_soleil
        avant = "".join(b for b, _ in morceaux_soleil(self.HEURES, 500.0, self.DEMAIN))
        self.assertIn("SUN CLEARS THE RIDGE", avant)
        midi = "".join(b for b, _ in morceaux_soleil(self.HEURES, 5000.0, self.DEMAIN))
        self.assertIn("RIDGE SHADOW AT", midi)
        soir = "".join(b for b, _ in morceaux_soleil(self.HEURES, 8500.0, self.DEMAIN))
        self.assertIn("IN THE SHADOW OF THE VENTOUX", soir)


class CeQuOnMontreEtQuandOnLeMontre(unittest.TestCase):
    """Deux reproches de l'antenne, un soir d'octobre."""

    def test_a_replay_says_paris_like_the_clock_does(self):
        """La date d'une rediffusion ne porte pas de fuseau.

        L'horloge du coin en porte un et dit l'heure qu'il est maintenant ;
        celle-ci date une image d'hier. Les deux côte à côte se lisaient comme
        deux heures du même instant. L'heure reste celle de Paris, elle n'est
        simplement plus annoncée.
        """
        dit = stream._quand_dit("2026-10-01T15:37:29Z")
        self.assertNotIn("PARIS", dit)
        self.assertNotIn("CEST", dit)
        self.assertNotIn("CET", dit)
        # L'heure reste celle de Paris, pas celle d'UTC : quinze heures
        # trente-sept en UTC font dix-sept heures trente-sept ici.
        self.assertIn("17:37", dit)
        # Et une date illisible repart telle quelle plutôt que de disparaître.
        self.assertEqual(stream._quand_dit("pas une date"), "pas une date")

    def test_the_flyover_waits_for_daylight(self):
        """Un rendu en plein soleil posé sur une nuit noire ne montre rien.

        La condition est le soleil au-dessus de l'horizon, pas une plage
        horaire : la même règle vaudra sur la caméra suivante.
        """
        source = inspect.getsource(stream.diffuse)
        self.assertIn("fait_jour = (hauteur_soleil or -90.0) > HORIZON", source)
        # Le survol s'arrête quand le jour tombe, et ne part pas sans lui.
        self.assertIn("or not fait_jour", source)
        self.assertIn("and fait_jour and quand - dernier_vu > CREUX_S", source)


class LeMotSeLitOuNeSertARien(unittest.TestCase):
    """« Boooooooring » clignotait quatre images, et personne ne lisait."""

    def test_the_boredom_word_outlasts_the_voice(self):
        """Six dixièmes de seconde font quatre images à six par seconde.

        Le mot durait exactement la voix, ce qui semblait honnête et ne
        l'était pas. Tenir un sous-titre plus longtemps que la parole n'est
        pas mentir, c'est sous-titrer.
        """
        source = inspect.getsource(stream.diffuse)
        self.assertIn('elif dit == "ennui" or quand - dernier_ennui <= ENNUI_TENUE_S:',
                      source)
        self.assertNotIn('else "BOOOOORING"', source)
        # Assez long pour être lu à la cadence du flux.
        self.assertGreaterEqual(stream.ENNUI_TENUE_S * 6, 12)

    def test_the_word_also_stays_as_long_as_the_voice_speaks(self):
        """Le plancher seul effacerait le mot avant la fin de la phrase.

        Une voix à qui on demande de traîner met près de quatre secondes à
        dire « Boooooooring », soit plus que la tenue minimale.
        """
        source = inspect.getsource(stream.diffuse)
        self.assertIn('dit = musique.dit_quoi() if musique.parle() else ""', source)
        self.assertIn('if dit == "brouillard" or quand - gris_depuis', source)

    def test_the_stream_does_not_open_on_boooooring(self):
        """À zéro, le flux s'ouvrait trois secondes sur « BOOOOORING »."""
        source = inspect.getsource(stream.diffuse)
        self.assertIn("dernier_ennui = origine - 10_000.0", source)

    def test_the_voices_can_be_understood(self):
        """Bubbles parle sous l'eau, Boing rebondit, Bad News chante.

        Une plaisanterie qu'on n'entend pas est un bruit, et un bruit sur un
        flux de surveillance ressemble à une panne.
        """
        from scripts.voix_ennui import CADENCES, JEU, REPLIQUES, VOIX
        roles = {v for _, v, _ in REPLIQUES}
        self.assertTrue(roles)
        for moteur, timbres in VOIX.items():
            self.assertFalse(set(timbres.values()) & {"Bubbles", "Boing", "Bad News"},
                             moteur)
            # Chaque rôle a un timbre dans chaque moteur, sinon changer de
            # moteur lève une KeyError au milieu d'une gravure.
            self.assertFalse(roles - set(timbres), moteur)
        # Et chaque occasion a sa consigne de jeu, qui est tout l'intérêt.
        for quand, _, _ in REPLIQUES:
            self.assertIn(quand, JEU)
        # Et l'ennui parle plus lentement que la prise : il traîne, elle claque.
        self.assertLess(CADENCES["ennui"], CADENCES["attrape"])
        for quand, _, _ in REPLIQUES:
            self.assertIn(quand, CADENCES)


class LaVoixPasseAuDessusDeLaMusique(unittest.TestCase):
    """On l'entendait parler sans comprendre : la pire des trois possibilités."""

    @staticmethod
    def _wav(niveau: float, secondes: float = 1.0, cadence: int = 24000) -> bytes:
        t = np.arange(int(secondes * cadence)) / cadence
        onde = (np.sin(2 * np.pi * 220 * t) * niveau * 32767).astype(np.int16)
        tampon = io.BytesIO()
        with wave.open(tampon, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(cadence)
            f.writeframes(onde.tobytes())
        return tampon.getvalue()

    def test_speech_clears_the_ducked_music_by_six_decibels(self):
        """Six décibels d'avance : c'est une donnée d'audition, pas un goût."""
        from scripts.voix_ennui import CIBLE_RMS
        # La valeur efficace mesurée sur les morceaux de la médiathèque.
        fond = 0.22 * stream.ATTENUATION
        self.assertGreaterEqual(20 * math.log10(CIBLE_RMS / fond), 6.0)

    def test_the_music_is_still_there_under_the_joke(self):
        """Une plaisanterie posée sur un morceau, pas une annonce de gare."""
        self.assertGreater(stream.ATTENUATION, 0.15)

    def test_the_sum_never_clips(self):
        """Le mélangeur additionne : les deux crêtes doivent tenir dans un."""
        from scripts.voix_ennui import PLAFOND
        self.assertLess(PLAFOND + stream.ATTENUATION, 1.0)

    def test_the_level_is_read_on_the_speech_not_on_the_silence(self):
        """Une phrase précédée d'un blanc n'est pas une phrase plus faible.

        La moyenne sur tout le fichier le croirait et remonterait trop.
        """
        from scripts.voix_ennui import mesure_pcm
        son = np.frombuffer(self._wav(0.5, 1.0), np.int16)[22:]
        blanc = np.zeros(24000 * 3, np.int16)
        parole, _ = mesure_pcm(np.concatenate([blanc, son, blanc]).tobytes(),
                               voies=1, cadence=24000)
        self.assertAlmostEqual(parole, 0.5 / math.sqrt(2), delta=0.03)

    def test_a_mute_answer_is_asked_again_and_then_refused(self):
        """Le modèle rend parfois un fichier bien formé et parfaitement vide.

        Livré tel quel, il ferait à l'antenne un mot affiché sur rien — la
        panne même qu'on essaie d'éviter, et invisible à la relecture du code
        puisque le code avait bien fonctionné.
        """
        from scripts import voix_ennui
        essais = []

        def muet(texte, voix, jeu):
            essais.append(texte)
            return self._wav(0.0)

        with mock.patch.object(voix_ennui, "_demande", muet):
            with self.assertRaises(SystemExit):
                voix_ennui._parle_openai("Foooooog", "nova", "", essais=3)
        self.assertEqual(len(essais), 3)

        with mock.patch.object(voix_ennui, "_demande",
                               lambda *_: self._wav(0.3)):
            self.assertTrue(voix_ennui._parle_openai("Foooooog", "nova", ""))

    def test_the_bell_and_the_voice_together_stay_under_the_ceiling(self):
        """Un écrêtage sur une attaque de cloche s'entend comme un craquement."""
        from scripts.voix_ennui import PLAFOND, cloche, _mele
        forte = (np.ones(44100 * 2, np.int16) * int(0.6 * 32767)).tobytes()
        melange = np.frombuffer(_mele(cloche(), forte, 0.42), np.int16)
        self.assertLessEqual(float(np.abs(melange).max()) / 32768, PLAFOND + 1e-3)

    def test_the_key_never_lands_in_the_tracked_config(self):
        """config/config.json est suivi par git ; local.json ne l'est pas."""
        from scripts.voix_ennui import cle_openai
        suivi = json.loads((ROOT / "config" / "config.json").read_text())
        self.assertNotIn("openai", suivi)
        self.assertIn("config/local.json",
                      (ROOT / ".gitignore").read_text().splitlines())
        self.assertIsInstance(cle_openai(), str)


class UneRecolteNEffacePasLaMediatheque(unittest.TestCase):
    """Sept morceaux en rotation sont partis sous couvert d'en ajouter."""

    @staticmethod
    def _fiche(nom, auteur, force, telecharge):
        return {"fichier": nom, "auteur": auteur, "titre": nom,
                "telecharge": telecharge, "force_voulue": force}

    def _ecoute(self, fiches, combien):
        """« ecoute » mesure les fichiers ; ici on lui souffle la mesure."""
        import scripts.pulsation as pulsation
        forces = {f["fichier"]: f["force_voulue"] for f in fiches}
        with mock.patch.object(
                pulsation, "mesure",
                lambda c: {"force": forces[str(c)], "bpm": 130.0,
                           "grave": 0.1, "duree": 400.0}):
            return musique_dogmazic.ecoute(fiches, combien)

    def test_only_todays_candidates_can_be_deleted(self):
        """Une récolte retombe forcément sur des morceaux déjà installés.

        Les juger au tri du jour revient à faire le ménage dans la
        médiathèque sous couvert d'y ajouter.
        """
        with tempfile.TemporaryDirectory() as dossier:
            ancien = Path(dossier) / "deja-la.mp3"
            neuf = Path(dossier) / "tout-neuf.mp3"
            for p in (ancien, neuf):
                p.write_bytes(b"x")
            fiches = [self._fiche(str(ancien), "Un", 0.05, False),
                      self._fiche(str(neuf), "Deux", 0.05, True)]
            gardes, effaces = self._ecoute(fiches, 5)
            self.assertEqual(gardes, [])
            self.assertTrue(ancien.is_file(), "un morceau installé a disparu")
            self.assertFalse(neuf.is_file())
            self.assertEqual(effaces, [str(neuf)])

    def test_one_artist_cannot_take_the_whole_harvest(self):
        """Sur ce catalogue un seul nom fournit sept des trente candidats."""
        with tempfile.TemporaryDirectory() as dossier:
            fiches = []
            for i in range(6):
                p = Path(dossier) / f"m{i}.mp3"
                p.write_bytes(b"x")
                fiches.append(self._fiche(str(p), "AlchimiX", 0.9 - i / 100, True))
            autre = Path(dossier) / "autre.mp3"
            autre.write_bytes(b"x")
            fiches.append(self._fiche(str(autre), "Blashko", 0.5, True))
            gardes, _ = self._ecoute(fiches, 4)
            auteurs = [f["auteur"] for f in gardes]
            self.assertEqual(auteurs.count("AlchimiX"), 2)
            self.assertIn("Blashko", auteurs)

    def test_a_deleted_track_stops_being_credited(self):
        """La description de la chaîne annoncerait des morceaux qu'on ne passe plus."""
        from scripts.musique_dogmazic import ecris_credits
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier)
            (chemin / "credits.json").write_text(json.dumps({
                "parti.mp3": {"auteur": "Un", "titre": "Parti"},
                "reste.mp3": {"auteur": "Deux", "titre": "Reste"}}),
                encoding="utf-8")
            ecris_credits(chemin, [], effaces=["/ailleurs/parti.mp3"])
            tout = json.loads((chemin / "credits.json").read_text())
            self.assertNotIn("parti.mp3", tout)
            self.assertIn("reste.mp3", tout)

    def test_the_pulse_of_a_beat_is_read_and_a_drone_is_not(self):
        """Ce qui décide est la mesure, pas l'étiquette de genre."""
        from scripts.pulsation import CADENCE, FORCE_DANSANTE, flux_du_grave
        t = np.arange(int(CADENCE * 20)) / CADENCE
        # Une grosse caisse à 130 temps : une enveloppe qui retombe, à 50 Hz.
        periode = 60 / 130
        coup = np.exp(-(t % periode) * 30) * np.sin(2 * np.pi * 50 * t)
        nappe = np.sin(2 * np.pi * 50 * t) * 0.5

        def force(x):
            flux = flux_du_grave(x.astype(np.float32))
            flux = flux - flux.mean()
            auto = np.correlate(flux, flux, "full")[len(flux) - 1:]
            auto /= auto[0]
            return float(auto[int(100 * periode)])

        self.assertGreater(force(coup), FORCE_DANSANTE)
        self.assertLess(force(nappe), FORCE_DANSANTE)


class UneNuitNEstPasUnSeulArtiste(unittest.TestCase):
    """Les seize premiers morceaux de chaque nuit étaient du même."""

    def _bibliotheque(self, dossier, longs, courts):
        """Des fichiers vides, et des crédits qui disent qui joue."""
        credits = {}
        for nom, auteur in list(longs) + list(courts):
            (Path(dossier) / nom).write_bytes(b"x")
            credits[nom] = {"auteur": auteur, "titre": nom}
        (Path(dossier) / "credits.json").write_text(json.dumps(credits))
        durees = {Path(dossier) / nom: (900.0 if (nom, a) in longs else 300.0)
                  for nom, a in list(longs) + list(courts)}
        return durees

    def _session(self, dossier, durees, nuit):
        with mock.patch.object(stream, "duree_audio",
                               lambda p: durees.get(p, 0.0)):
            stream.batir_session(Path(dossier), heures=4.0, graine=1, nuit=nuit)
        credits = json.loads((Path(dossier) / "credits.json").read_text())
        noms = []
        for ligne in (Path(dossier) / "session.txt").read_text().splitlines():
            if ligne.startswith("file "):
                nom = ligne.split("/")[-1].rstrip("'")
                if not noms or noms[-1] != nom:
                    noms.append(nom)
        return [credits[n]["auteur"] for n in noms]

    def test_the_night_does_not_open_on_four_hours_of_one_name(self):
        """Tous les longs sont de thepriben : « commencer par les sets »
        revenait à commencer par les seize, soit quatre heures.
        """
        with tempfile.TemporaryDirectory() as dossier:
            longs = [(f"maison-{i:02d}.mp3", "thepriben") for i in range(16)]
            courts = [(f"autre-{i:03d}.mp3", f"Artiste {i}") for i in range(119)]
            durees = self._bibliotheque(dossier, longs, courts)
            auteurs = self._session(dossier, durees, nuit=True)
            self.assertLessEqual(auteurs[:16].count("thepriben"), 4,
                                 "la nuit rouvre sur un bloc du même artiste")

    def test_the_long_pieces_are_spread_and_not_dropped(self):
        """Mêlés et non enchaînés : ils doivent rester présents partout."""
        with tempfile.TemporaryDirectory() as dossier:
            longs = [(f"maison-{i:02d}.mp3", "thepriben") for i in range(16)]
            courts = [(f"autre-{i:03d}.mp3", f"Artiste {i}") for i in range(119)]
            durees = self._bibliotheque(dossier, longs, courts)
            auteurs = self._session(dossier, durees, nuit=True)
            moitie = len(auteurs) // 2
            self.assertGreater(auteurs[:moitie].count("thepriben"), 0)
            self.assertGreater(auteurs[moitie:].count("thepriben"), 0)

    def test_the_same_name_never_follows_itself_when_avoidable(self):
        from watcher.stream import _espace
        pistes = [Path(f"{n}.mp3") for n in ("a1", "a2", "a3", "b1", "c1")]
        auteurs = {"a1.mp3": "a", "a2.mp3": "a", "a3.mp3": "a",
                   "b1.mp3": "b", "c1.mp3": "c"}
        noms = [auteurs[p.name] for p in _espace(pistes, auteurs)]
        colles = sum(1 for i in range(1, len(noms)) if noms[i] == noms[i - 1])
        # Trois « a » pour deux autres : une répétition est inévitable à la fin.
        self.assertLessEqual(colles, 1)
        self.assertEqual(sorted(noms), ["a", "a", "a", "b", "c"])

    def test_a_well_stocked_artist_does_not_take_every_other_slot(self):
        """Refuser le seul voisin immédiat donne une alternance, pas de la
        variété : un nom bien fourni prenait les rangs un, trois, cinq, sept.
        """
        from watcher.stream import MEMOIRE_ARTISTES, _espace
        # Les proportions de la vraie bibliothèque : le nom le plus fourni y
        # pèse dix-sept morceaux sur cent trente-cinq. Une moitié sous un seul
        # nom rendrait trois noms d'écart arithmétiquement impossible.
        pistes, auteurs = [], {}
        for i in range(15):
            pistes.append(Path(f"gros{i}.mp3"))
            auteurs[f"gros{i}.mp3"] = "le gros"
        for i in range(45):
            pistes.append(Path(f"petit{i}.mp3"))
            auteurs[f"petit{i}.mp3"] = f"petit {i % 15}"
        noms = [auteurs[p.name] for p in _espace(pistes, auteurs)]
        for depart in range(0, len(noms) - 8):
            tranche = noms[depart:depart + 8]
            self.assertLessEqual(
                tranche.count("le gros"), 8 // (MEMOIRE_ARTISTES + 1) + 1,
                f"un seul nom tient la tranche {depart}")

    def test_a_library_of_one_artist_still_plays(self):
        """Un silence serait pire qu'une répétition."""
        from watcher.stream import _espace
        pistes = [Path(f"a{i}.mp3") for i in range(4)]
        auteurs = {p.name: "seul" for p in pistes}
        self.assertEqual(len(_espace(pistes, auteurs)), 4)


class LaPromenadeDesPantins(unittest.TestCase):
    """Ils glissent dans la bande noire, y dansent, et reviennent."""

    VUE = (264, 55, 1392, 783)          # la fenêtre réelle d'une toile 1920×1080

    def _ou(self, seconde, largeur=1920, hauteur=1080, vue=None):
        """Les abscisses des deux pantins à cet instant."""
        toile = np.zeros((hauteur, largeur, 3), np.uint8)
        stream.pose_danseurs(toile, seconde, 1.0, voile=1.0,
                             vue=vue if vue is not None else self.VUE)
        colonnes = np.where(toile.max(axis=(0, 2)) > 0)[0]
        milieu = largeur // 2
        return (int(colonnes[colonnes < milieu].mean()),
                int(colonnes[colonnes >= milieu].mean()))

    def test_they_come_back_exactly_where_they_started(self):
        """« Et reviendrait au point initial. »

        Sur « promenade » et non sur le dessin : les membres bougent tout le
        temps, donc deux silhouettes diffèrent même quand le pantin n'a pas
        bougé d'un pixel. C'est l'écart qui doit retomber à zéro, et c'est lui
        seul qui déplace l'ancre.
        """
        cycle = 2 * stream.PROMENADE_GLISSE_S + stream.PROMENADE_TENUE_S
        for seconde in (0.0, cycle, cycle + 1, stream.PROMENADE_PERIODE_S,
                        3 * stream.PROMENADE_PERIODE_S - 1):
            self.assertEqual(stream.promenade(seconde), 0.0, seconde)
        # Et à écart nul, les deux pantins sont bien dans la vue.
        gauche, _, large, _ = self.VUE
        chez_eux = self._ou(cycle + 1)
        self.assertGreater(chez_eux[0], gauche)
        self.assertLess(chez_eux[1], gauche + large)

    def test_at_the_far_point_they_stand_in_the_black_band(self):
        """Dehors, c'est la bande — pas le bord de l'image."""
        gauche, cime, large, haute = self.VUE
        sortis = self._ou(stream.PROMENADE_GLISSE_S + 1)
        self.assertLess(sortis[0], gauche, "le gauche n'a pas quitté la vue")
        self.assertGreater(sortis[1], gauche + large,
                           "le droit n'a pas quitté la vue")

    def test_nobody_is_cut_by_the_edge_of_the_picture(self):
        """Une main coupée par le bord se lit comme un bogue."""
        for seconde in np.arange(0, 2 * stream.PROMENADE_GLISSE_S
                                 + stream.PROMENADE_TENUE_S, 0.4):
            toile = np.zeros((1080, 1920, 3), np.uint8)
            stream.pose_danseurs(toile, float(seconde), 1.0, voile=1.0,
                                 vue=self.VUE)
            colonnes = np.where(toile.max(axis=(0, 2)) > 0)[0]
            self.assertGreater(colonnes.min(), 0, f"coupé à gauche à {seconde}")
            self.assertLess(colonnes.max(), 1919, f"coupé à droite à {seconde}")

    def test_they_stay_home_where_there_is_no_band(self):
        """Un Short n'a pas de bande : il n'y a nulle part où aller."""
        plein = (0, 0, 1080, 1920)
        toile = np.zeros((1920, 1080, 3), np.uint8)
        poses = []
        for seconde in (0.0, stream.PROMENADE_GLISSE_S + 1):
            toile[:] = 0
            stream.pose_danseurs(toile, seconde, 1.0, voile=1.0, vue=plein)
            colonnes = np.where(toile.max(axis=(0, 2)) > 0)[0]
            poses.append((int(colonnes.min()), int(colonnes.max())))
        self.assertEqual(poses[0], poses[1])

    def test_the_outing_is_rare_enough_to_stay_a_surprise(self):
        """Une surprise qu'on attend n'en est plus une."""
        dehors = sum(1 for s in np.arange(0, stream.PROMENADE_PERIODE_S, 0.5)
                     if stream.promenade(float(s)) > 0)
        part = dehors / (stream.PROMENADE_PERIODE_S * 2)
        self.assertLess(part, 0.1)
        self.assertGreater(part, 0.02)

    def test_the_window_is_where_the_picture_actually_lands(self):
        """La bande noire est ce que « cadre » laisse autour, rien d'autre."""
        cam = np.full((1080, 1920, 3), 255, np.uint8)
        toile = stream.cadre(cam, 1920, 1080)
        gauche, cime, large, haute = stream.fenetre((1080, 1920), 1920, 1080)
        self.assertEqual(toile[cime + 1, gauche + 1].tolist(), [255, 255, 255])
        self.assertEqual(toile[cime + 1, gauche - 1].tolist(), [0, 0, 0])
        self.assertEqual(toile[cime + 1, gauche + large + 1].tolist(), [0, 0, 0])


class RienDeReconnaissableNeSort(unittest.TestCase):
    """« Tu peux stocker les originaux mais pas les diffuser. »"""

    @staticmethod
    def _scene(largeur=400, hauteur=300):
        """Un damier fin : ce qui survit au flou se voit tout de suite."""
        x = np.arange(largeur) // 3 % 2
        y = np.arange(hauteur) // 3 % 2
        motif = (np.logical_xor.outer(y, x) * 255).astype(np.uint8)
        return cv2.merge([motif, motif // 2, motif // 4])

    def test_nothing_smaller_than_half_a_metre_survives(self):
        """Un visage fait vingt centimètres, une plaque douze.

        Le seuil se compte au sol et non en pixels : c'est la seule façon de
        l'écrire une fois pour mille caméras.
        """
        from watcher.store import FLOU_SOL_M, floute
        for largeur, metres in ((400, 4.5), (900, 12.0), (120, 2.0)):
            decoupe = self._scene(largeur, largeur * 3 // 4)
            flou = floute(decoupe, metres)
            # La plus petite case uniforme, mesurée sur l'image rendue.
            colonnes = len({flou[:, i].tobytes() for i in range(largeur)})
            bloc_m = metres / max(colonnes, 1)
            self.assertGreaterEqual(bloc_m, FLOU_SOL_M * 0.9,
                                    f"{largeur} px pour {metres} m")

    def test_colour_goes_too(self):
        """« L'homme au manteau rouge » suffit à désigner quelqu'un."""
        from watcher.store import floute
        flou = floute(self._scene(), 4.5)
        self.assertTrue((flou[:, :, 0] == flou[:, :, 2]).all())

    def test_an_unmeasured_crop_is_blurred_hard_anyway(self):
        """Quand on ne sait pas mesurer, on floute franchement."""
        from watcher.store import BLOCS_MAX, floute
        flou = floute(self._scene(600, 400), 0.0)
        colonnes = len({flou[:, i].tobytes() for i in range(600)})
        self.assertLessEqual(colonnes, BLOCS_MAX)

    def test_both_pictures_are_published_and_sharp(self):
        """Le site montre les deux, et nettes : c'est dessus qu'on juge.

        La vue d'ensemble dit où la chose est passée, la découpe dit ce que
        c'était. Floutées au dépôt, elles l'étaient aussi pour celui qui doit
        trancher, et un car dont on ne lit plus le flanc n'est plus jugeable.
        """
        from watcher import publish
        from watcher import store
        chemins = inspect.getsource(publish.publish)
        self.assertIn('"data/thumbs"', chemins)
        self.assertIn('"data/closeups"', chemins)
        depose = inspect.getsource(store.Store.keep_closeup)
        self.assertNotIn("floute(", depose)

    def test_the_replay_blurs_at_the_moment_it_shows(self):
        """Le flou est posé à l'antenne, et nulle part ailleurs.

        La différence n'est pas dans l'image : elle est dans qui la regarde.
        On va chercher une photo sur le site pour l'examiner ; à l'antenne le
        même passage revient en boucle devant des gens qui ne l'ont pas
        demandé.
        """
        source = inspect.getsource(stream.pose_rediffusion)
        self.assertIn("floute(vignette)", source)
        self.assertLess(source.index("imread"), source.index("floute(vignette)"))
