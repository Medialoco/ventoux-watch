import json
import math
import re
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np

from watcher.geometry import assign_zone
from watcher.gtfs import GtfsIndex, load_feed
from watcher.main import _box_of_the_named, _crossed_sky, _might_be_bus, _note_interruption, _utc
from watcher.naming import Decision
from watcher.motion import MotionDetector, Track
from watcher.naming import Detection, Observation, Trip, choose_aircraft, decide, in_camera_view
from watcher.review import apply_review, parse_review
from watcher.opensky import SkyArchive
from watcher.scene import Scene, ViewLog, moon_spot, read_sky, solar_period, weather_label
from watcher.store import Store, fold_events, small_jpeg

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
        decision = decide(Observation(zone="roundabout", travel=0.0, detections=[Detection("car", 0.9)]))
        self.assertEqual(decision.type, "motion")
        self.assertNotEqual(decision.label, "Voiture")

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

    def test_growing_warm_patch_on_the_slope_is_fire(self):
        decision = decide(Observation(zone="slope", duration_s=25, area_grow=2.0, warm_ratio=0.2))
        self.assertEqual(decision.type, "fire")

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
            {"id": "c", "t": "2026-09-25T08:52:21Z", "type": "motion", "label": "Mouvement sur la route", "zone": "road", "confidence": 0.3, "thumb": "data/thumbs/c.jpg", "detail": {}},
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
        self.assertTrue(_worth_keeping("none", cfg, vus, instant))
        # Le motif bavard est muselé jusqu'à la prochaine fenêtre...
        self.assertFalse(_worth_keeping("none", cfg, vus, instant + 5))
        # ...mais il n'a pas pris la place du motif rare arrivé juste après.
        self.assertTrue(_worth_keeping("night_plume", cfg, vus, instant + 5))
        self.assertTrue(_worth_keeping("none", cfg, vus, instant + 601))

        # Et on doit pouvoir tout couper d'un seul réglage.
        self.assertFalse(_worth_keeping("none", {"sample_refused_s": 0}, {}, instant))

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
            if dit.label != attendu:
                fautes.append(f"{entree['id']} : attendu {attendu!r}, obtenu {dit.label!r}")

        if not rejoues:
            self.skipTest("aucune relecture n'a encore d'observation gardée : "
                          "le compte part de zéro et grandit avec les verdicts")
        self.assertFalse(fautes, "des fautes déjà corrigées sont revenues :\n  "
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
        self.assertIsNone(juge("Mouvement sur la route", "voiture"))
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
            "label": "Mouvement sur la route", "zone": "road", "photo": "thumbs/m1.jpg",
            "detail": {"measured": {"width_m": 2.1, "rise_ms": 0.4, "seen_as": []}},
        }
        lessons: list = []
        self.assertTrue(apply_review([event], {}, "m1", "accepted", "velo", lessons))
        self.assertEqual(len(lessons), 1)
        row = lessons[0]
        self.assertEqual((row["truth"], row["guessed"]), ("Vélo", "Mouvement sur la route"))
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
        crossing = Decision("publish", "motion", "Mouvement sur la route", "unnamed_vehicle", {}, 0.3)
        seen: dict = {}
        self.assertTrue(_worth_reviewing(crossing, cfg, seen, 1_000.0))
        seen["unnamed"] = 1_000.0
        self.assertFalse(_worth_reviewing(crossing, cfg, seen, 1_200.0))
        self.assertTrue(_worth_reviewing(crossing, cfg, seen, 1_300.0))

    def test_only_the_crossings_are_reviewed_and_only_when_asked(self):
        from watcher.main import _worth_reviewing

        fog = Decision("publish", "motion", "Brouillard", "fog", {}, 0.3)
        crossing = Decision("publish", "motion", "Mouvement sur la route", "unnamed_vehicle", {}, 0.3)
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
