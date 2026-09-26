"""Condensation trails, signed by the flight that left them.

A contrail does not cross the sky: it stays in it. The sky rule asks a patch to
move before it will call it an aircraft, so the trail is thrown out with the
stars and the mast beacon, and the one thing a reader can plainly see up there
is the one thing never named. On a single evening the watcher filed a hundred
refusals reading "ça n'a pas traversé le ciel" while a trail hung over the
ridge in every frame.

Taking it the other way round works. OpenSky says where each aircraft has just
been; that path, projected into the frame, is a line drawn from a source rather
than from the picture. The photograph is then asked one question: is it
brighter along that line than it is beside it. A trail named this way can be
checked afterwards, which a trail recognised by its shape alone could not be --
thin cirrus is straight, faint and still as well, and on a wispy night the
history would fill with clouds wearing flight numbers.

Nothing here looks for a shape. If OpenSky is silent, so is this.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from watcher.frustum import Pose, project
from watcher.geometry import point_in_polygon

# How far back the trail is followed. Past a quarter of an hour a contrail has
# usually drifted off the path that made it, and the line stops standing for
# anything; under a few minutes there is rarely enough of it inside the frame
# to weigh against the sky on either side.
LOOK_BACK_S = 900.0
# The stride along the path, in seconds of flight. At cruise that is about four
# kilometres, short enough that a turn is followed and long enough that a
# quarter of an hour costs a dozen points rather than a thousand.
STRIDE_S = 30.0
# How far to either side of the line the sky is read, as a fraction of the
# width. A fresh trail is a few hundred metres across, which at the twenty to
# thirty kilometres where one is visible here fills about a hundredth of the
# frame; three hundredths clears even a trail that has spread for an hour, and
# still lands well inside the strip of sky above the ridge.
SIDE = 0.03
# The stride across the picture, in fractions of the width. Samples closer than
# the blur that smooths them are not separate measurements, and counting them
# as such would make any line look significant.
STEP = 0.004
# How much of the width the trail must run before it is worth measuring. Under
# this it is a smudge, and a smudge lands on some flight path every night.
MIN_RUN = 0.15
# How far above the sky's own best effort a trail must score. Three hundred
# lines thrown at random across the cirrus-covered evening of 26 September
# reached 1.69 levels at the very most and 0.97 at the ninety-ninth, so half a
# level of clearance puts a named trail outside what that sky could invent.
MARGIN = 0.5
# How far the line must stand above the sky beside it, in levels of grey. Set
# from the simulation in scripts/simulate_contrail.py, where a trail of the
# faintest contrast the eye can find in these frames lifts about four levels
# and the empty sky lifts a quarter of one.
MIN_LIFT = 2.0
# And how sure that lift has to be. The samples carry the grain of a night
# webcam, so the lift is required to be several times its own standard error:
# a long faint trail and a short bright one both pass, pure noise does not.
MIN_SIGMA = 5.0


@dataclass
class Trail:
    """One flight's path through the frame, and what the picture says about it."""

    icao24: str
    callsign: str
    altitude_m: float | None
    line: list[tuple[float, float]]
    lift: float
    sigma: float
    run: float
    samples: int
    bar: float = 0.0

    def as_detail(self) -> dict:
        return {
            "icao24": self.icao24,
            "callsign": self.callsign,
            "altitude_m": self.altitude_m,
            "lift": round(self.lift, 2),
            "sigma": round(self.sigma, 1),
            "run": round(self.run, 3),
            "samples": self.samples,
            # What the same sky managed on lines nobody flew. Kept with the
            # entry so a reader can see the trail was not merely bright, but
            # brighter than that evening's clouds could manage.
            "bar": round(self.bar, 2),
        }


def flown(states: list[tuple[float, dict]], until: float,
          look_back_s: float = LOOK_BACK_S, stride_s: float = STRIDE_S) -> list[tuple[float, float, float]]:
    """Where the aircraft has been, oldest first, as latitude, longitude, height.

    Readings are used where there are readings. Where there are none -- and
    tonight there is one an hour, because the sky is only asked about when
    something crosses it -- the oldest one is walked backwards along its own
    heading at its own speed. That is exact for an aircraft at cruise, which
    holds a straight line for far longer than a trail survives, and it is the
    only part of this that is inferred rather than read.
    """
    kept = sorted((t, s) for t, s in states if until - look_back_s <= t <= until + stride_s)
    if not kept:
        return []
    path = [(float(s["lat"]), float(s["lon"]), _height(s)) for _, s in kept]
    oldest_t, oldest = kept[0]
    speed = float(oldest.get("speed_ms") or 0.0)
    heading = oldest.get("heading")
    gap = oldest_t - (until - look_back_s)
    if heading is None or speed <= 0 or gap <= stride_s:
        return path
    back = math.radians(float(heading) + 180.0)
    tail = []
    step = stride_s
    while step <= gap:
        run_m = speed * step
        lat, lon, ele = path[0]
        dlat = run_m * math.cos(back) / 110_540.0
        dlon = run_m * math.sin(back) / (111_320.0 * math.cos(math.radians(lat)))
        tail.append((lat + dlat, lon + dlon, ele))
        step += stride_s
    return list(reversed(tail)) + path


def draw(pose: Pose, points: list[tuple[float, float, float]]) -> list[tuple[float, float]]:
    """The path in the picture, in fractions of the frame, dropping what is behind."""
    line = []
    for lat, lon, ele in points:
        spot = project(pose, lat, lon, ele)
        if spot is not None:
            line.append(spot)
    return line


def steady(frames: list[np.ndarray]) -> np.ndarray | None:
    """One quiet frame out of several noisy ones.

    A single night frame from this camera is mostly grain: the trail sits a
    couple of levels above the sky and the noise is one and a half. The median
    of ten frames divides that by three and costs nothing, and a contrail is
    the rare subject that holds still long enough to be stacked.
    """
    usable = [frame for frame in frames if frame is not None and frame.size]
    if not usable:
        return None
    shape = usable[0].shape
    usable = [frame for frame in usable if frame.shape == shape]
    if len(usable) == 1:
        return usable[0]
    return np.median(np.stack(usable).astype(np.float32), axis=0).astype(np.uint8)


def relief(frame: np.ndarray) -> np.ndarray:
    """The picture with the smooth glow of the sky taken out.

    The sky is far from flat: it is bright around the moon and dark away from
    it, over hundreds of pixels. Subtracting a wide blur of itself leaves only
    what is narrow, which is what a trail is and what a moonlit gradient is not.
    """
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    width = frame.shape[1]
    wide = cv2.GaussianBlur(grey, (0, 0), max(8.0, 0.06 * width))
    return cv2.GaussianBlur(grey - wide, (0, 0), max(1.0, 0.0016 * width))


def sky_test(scene_map=None, polygon: list[list[float]] | None = None):
    """What counts as sky, in order of how well it is known.

    The surveyed map is the right witness: it was built by marching a ray out
    of every square of the picture until it met the ground, so its skyline is
    the real one. The polygon in the zone file is a safe hand-drawn guess that
    stops a tenth of the frame above the crest, and using it would throw away
    most of the strip where an aircraft can be seen at all.
    """
    if scene_map is not None and getattr(scene_map, "ready", False):
        return lambda x, y: scene_map.surface_at(x, y) == "sky"
    if polygon:
        return lambda x, y: point_in_polygon(x, y, polygon)
    return lambda x, y: True


def sky_mask(shape: tuple[int, int], sky=None, cells: int = 192,
             margin: float = 0.05) -> np.ndarray:
    """Which pixels count as sky, kept well clear of the skyline.

    The wide blur that flattens the sky cannot know where a mountain begins, so
    it leaves a bright rim all along the crest. Samples taken in that rim
    measure the edge of the Ventoux rather than the air above it: on one frame
    they alone made the sky read three times more restless than its body was.
    Pulling the mask back by a twentieth of the width clears the rim.

    Built coarse and stretched rather than asked pixel by pixel, because the
    map answers slowly and the skyline does not need that much precision.
    """
    height, width = shape[:2]
    rows = max(8, int(cells * height / width))
    small = np.ones((rows, cells), np.uint8)
    if sky is not None:
        for j in range(rows):
            for i in range(cells):
                small[j, i] = 1 if sky((i + 0.5) / cells, (j + 0.5) / rows) else 0
    grown = cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST)
    step = max(3, int(margin * width) | 1)
    return cv2.erode(grown, np.ones((step, step), np.uint8)).astype(bool)


def measure(field: np.ndarray, line: list[tuple[float, float]], sky=None,
            side: float = SIDE, step: float = STEP) -> tuple[float, float, float, int]:
    """Lift, certainty, run and count for one line across one sky.

    Each sample is the difference between the line and the mean of two points
    set out at right angles from it. Reading both sides rather than the sky at
    large is what separates a trail from cirrus: a band a kilometre wide lifts
    the line and its neighbours alike and cancels here, while a trail lifts
    only the middle.
    """
    height, width = field.shape[:2]
    reach = side * width
    stride = max(2.0, step * width)
    gaps: list[float] = []
    seen: list[tuple[float, float]] = []
    for (x1, y1), (x2, y2) in zip(line, line[1:]):
        ax, ay = x1 * width, y1 * height
        bx, by = x2 * width, y2 * height
        span = math.hypot(bx - ax, by - ay)
        if span < 1e-6:
            continue
        nx, ny = -(by - ay) / span, (bx - ax) / span
        walked = 0.0
        while walked <= span:
            px, py = ax + (bx - ax) * walked / span, ay + (by - ay) * walked / span
            walked += stride
            spots = [(px, py), (px + nx * reach, py + ny * reach), (px - nx * reach, py - ny * reach)]
            if any(not (0 <= sx < width and 0 <= sy < height) for sx, sy in spots):
                continue
            if sky is not None and any(not sky[int(sy), int(sx)] for sx, sy in spots):
                continue
            middle = field[int(spots[0][1]), int(spots[0][0])]
            flank = 0.5 * (field[int(spots[1][1]), int(spots[1][0])]
                           + field[int(spots[2][1]), int(spots[2][0])])
            gaps.append(float(middle - flank))
            seen.append((px / width, py / height))
    if len(gaps) < 8:
        return 0.0, 0.0, 0.0, len(gaps)
    lift = float(np.mean(gaps))
    spread = float(np.std(gaps, ddof=1))
    # The standard error of the mean, and the lift measured in them. A trail
    # only counts when it is brighter than the scatter of its own samples can
    # explain, which is the whole difference between a measurement and a hope.
    sigma = lift / (spread / math.sqrt(len(gaps))) if spread > 1e-6 else 0.0
    xs = [x for x, _ in seen]
    run = max(xs) - min(xs) if xs else 0.0
    return lift, sigma, run, len(gaps)


def ceiling(field: np.ndarray, sky: np.ndarray, tries: int = 80, seed: int = 11,
            min_run: float = MIN_RUN) -> float:
    """The best score this sky can produce on a line no aircraft made.

    This is the bar, and it is measured on the frame being judged rather than
    chosen in advance. Every sky is different: thin cirrus comes in filaments
    of exactly the width a trail has, and a threshold that is safe under a
    clear moon would sign a cloud on a wispy night. Throwing lines at random
    across this very picture says what that picture can produce by itself, and
    a flight must beat it.

    Eighty is enough to find the tail without being felt: the whole thing runs
    in about a tenth of a second, once every half minute.
    """
    rng = np.random.default_rng(seed)
    best = 0.0
    for _ in range(tries * 6):
        x, y = rng.uniform(0, 1), rng.uniform(0, 0.35)
        angle = rng.uniform(0, math.pi)
        reach = rng.uniform(0.3, 0.9)
        line = [(x, y), (x + reach * math.cos(angle), y + reach * math.sin(angle) * 0.25)]
        lift, _, run, count = measure(field, line, sky)
        if count < 8 or run < min_run:
            continue
        best = max(best, lift)
        tries -= 1
        if tries <= 0:
            break
    return best


def find(frame: np.ndarray, pose: Pose, flights: dict[str, list[tuple[float, dict]]],
         when: float, sky=None,
         min_lift: float = MIN_LIFT, min_sigma: float = MIN_SIGMA,
         min_run: float = MIN_RUN, margin: float = MARGIN) -> list[Trail]:
    """Every trail the picture agrees with, strongest first.

    Three things must hold together. The line is brighter than the sky either
    side of it; that brightness is more than the scatter of its own samples can
    explain; and it beats the best line this same sky produces on its own, which
    is measured here rather than assumed. The last is what makes the rule safe
    on a cloudy night and still willing on a clear one.

    Two flights whose lines lie on top of each other cannot be told apart by a
    brightness that belongs to both, so neither is returned: the same answer the
    sky rule gives when several aircraft sit on one blob.
    """
    if frame is None or frame.size == 0 or not flights:
        return []
    field = relief(frame)
    sky = sky if isinstance(sky, np.ndarray) else sky_mask(frame.shape, sky)
    bar = max(min_lift, ceiling(field, sky) + margin)
    found: list[Trail] = []
    for icao, states in flights.items():
        line = draw(pose, flown(states, when))
        if len(line) < 2:
            continue
        lift, sigma, run, count = measure(field, line, sky)
        if lift < bar or sigma < min_sigma or run < min_run:
            continue
        newest = max(states, key=lambda item: item[0])[1]
        found.append(Trail(
            icao24=str(icao).strip().lower(),
            callsign=str(newest.get("callsign") or "").strip(),
            altitude_m=_height(newest),
            line=line,
            lift=lift,
            sigma=sigma,
            run=run,
            samples=count,
            bar=bar,
        ))
    found.sort(key=lambda trail: trail.lift, reverse=True)
    if len(found) >= 2 and _overlap(found[0], found[1]):
        return []
    return found


def _overlap(one: Trail, other: Trail, side: float = SIDE) -> bool:
    """True when two lines run close enough to share the same brightness."""
    near = 0
    for x, y in one.line:
        if any(math.hypot(x - ox, y - oy) <= 2 * side for ox, oy in other.line):
            near += 1
    return near >= max(2, len(one.line) // 2)


def _height(state: dict) -> float | None:
    value = state.get("altitude_m")
    return float(value) if isinstance(value, (int, float)) else None
