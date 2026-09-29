"""A fire that never happened, painted on the real view.

The watcher can only be trusted on a fire if a fire has been put in front of
it. Mont Serein does not burn to order, so the plume is drawn instead: pale,
turbulent, climbing and widening with every second, the way a fire that has
just caught looks from a kilometre away. Everything downstream — background
subtraction, tracking, the smoke and flame measurements, the naming — is the
real code, untouched.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

# The fire, in metres and metres a second.
#
# These were shares of the frame until 28 September, which quietly made the
# test depend on where the spot was put: at a fixed number of pixels, a plume
# on the far ridge stands for an inferno and the same plume by the chalet for a
# camp fire. Four spots measured that day gave a column between 13 and 21
# metres wide in its first second — nothing that has just caught is that size,
# and every one of them was refused as a cloud on its width alone.
#
# In metres the drawing says what it means. A small fire in scrub lifts its
# smoke at a couple of metres a second, widens the column at about half a metre
# a second, leans with whatever wind there is, and burns outwards along the
# ground far more slowly than it climbs.
CLIMB_MS = 2.0
SPREAD_MS = 0.45
DRIFT_MS = 1.2
START_RADIUS_M = 1.2
# How fast the burning patch itself widens, in metres a second. A surface fire
# in dry scrub advances by tens of centimetres a second at most; the column
# above it climbs an order of magnitude faster.
FLAME_MS = 0.25
SMOKE_BGR = (196, 196, 196)
FLAME_BGR = (30, 95, 235)


def plume(
    frame: np.ndarray,
    spot: tuple[float, float],
    age_s: float,
    flame: bool = False,
    seed: int = 0,
    smoke_after_s: float = 0.0,
    scale: tuple[float, float] = (0.0, 0.0),
) -> np.ndarray:
    """The view as it would look age_s seconds after the fire caught at spot.

    spot is given in the normalised frame, the base of the fire. The drawing
    is turbulent and seeded on the second, so two frames never match and the
    background subtractor sees the plume move.

    scale is how much of the picture one metre covers at that spot, across and
    upwards, as the scene map reads it. It is what turns metres into pixels,
    and without it nothing here can be drawn honestly: the same fire is a
    hand's width of picture on the near meadow and a few pixels on the far
    ridge, and a test that ignores the difference is measuring its own framing.

    smoke_after_s holds the smoke back while the flame is already burning. A
    fire in dry scrub often shows colour before it shows a column: a few square
    metres of orange with nothing above them yet. That is the moment worth
    catching, because it is the one where a fire is still small enough to be
    put out, and it is the hardest, since there is no plume to look for.
    """
    if age_s <= 0:
        return frame.copy()
    height, width = frame.shape[:2]
    across, up = scale
    if not (across > 0 and up > 0):
        raise ValueError("Le panache se dessine en mètres : il faut l'échelle du terrain au foyer")
    # Pixels for one metre, sideways and upwards. They differ: the picture is
    # wider than it is tall for the same angle.
    wide_px, tall_px = across * width, up * height
    base_x, base_y = spot[0] * width, spot[1] * height
    smoke_age = max(0.0, age_s - smoke_after_s)
    column = CLIMB_MS * smoke_age * tall_px
    smoke = np.zeros((height, width), dtype=np.float32)
    rng = np.random.default_rng(seed + int(age_s * 4))
    puffs = max(8, int(column / 4)) if smoke_age > 0 else 0
    for index in range(puffs):
        along = (index + 1) / max(puffs, 1)
        radius = (START_RADIUS_M + SPREAD_MS * smoke_age * along) * wide_px
        x = base_x + DRIFT_MS * smoke_age * along * wide_px + rng.normal(0, radius * 0.5)
        y = base_y - column * along + rng.normal(0, radius * 0.3)
        weight = (1.0 - 0.55 * along) * rng.uniform(0.7, 1.0)
        cv2.circle(smoke, (int(x), int(y)), max(1, int(radius)), float(weight), -1)
    blur = max(3, int(column / 6) | 1)
    smoke = cv2.GaussianBlur(smoke, (blur, blur), 0)
    smoke = np.clip(smoke, 0, 1)[:, :, None]
    paint = np.full(frame.shape, SMOKE_BGR, dtype=np.float32)
    out = frame.astype(np.float32) * (1 - smoke) + paint * smoke
    if flame:
        # The hot core grows on its own clock, not the plume's, so that it is
        # there in the seconds before there is any plume at all.
        _flame(out, base_x, base_y, max(column, FLAME_MS * age_s * tall_px), rng)
    return np.clip(out, 0, 255).astype(np.uint8)


def _flame(out: np.ndarray, base_x: float, base_y: float, column: float, rng) -> None:
    """The hot core at the foot of the plume.

    At night this is all a camera sees of a fire: the smoke disappears into the
    dark and only the flame carries any colour.
    """
    core = np.zeros(out.shape[:2], dtype=np.float32)
    # One pixel is the floor, not four. A flame that covers less than a pixel
    # at that distance covers less than a pixel, and padding it would be a way
    # of passing the far spots by drawing them nearer than they are.
    reach = max(1.0, column * 0.22)
    for _ in range(9):
        x = base_x + rng.normal(0, reach * 0.4)
        y = base_y - abs(rng.normal(0, reach * 0.5))
        cv2.circle(core, (int(x), int(y)), max(2, int(reach * rng.uniform(0.3, 0.7))), float(rng.uniform(0.6, 1.0)), -1)
    core = cv2.GaussianBlur(core, (5, 5), 0)
    core = np.clip(core, 0, 1)[:, :, None]
    paint = np.full(out.shape, FLAME_BGR, dtype=np.float32)
    out[:] = out * (1 - core) + paint * core


CAR_WIDE_M = 1.8
CAR_TALL_M = 1.5
LAMP_M = 0.25
# How far ahead of the bumper the headlights throw a pool of light on the road,
# and how wide that pool is. Dipped beams reach about thirty metres and spill
# wider than the car itself, which is the whole trouble: the lit tarmac is a
# bigger, brighter shape than the car that carries it, and the background
# subtractor has no reason to prefer the car.
POOL_LONG_M = 30.0
POOL_WIDE_M = 6.0
# Warm, because that is what the picture shows. Blue-green-red, as OpenCV
# counts it.
LAMP_BGR = (170.0, 220.0, 245.0)


def car(
    frame: np.ndarray,
    spot: tuple[float, float],
    scale: tuple[float, float],
    *,
    lights: bool = False,
    pool_to: tuple[float, float] | None = None,
    body: int = 70,
) -> np.ndarray:
    """A car standing on the road at spot, drawn at its true size.

    spot is where its wheels touch the ground, in the normalised frame, and
    scale is how much of the picture one metre covers there, as the scene map
    reads it. Nothing here is drawn in fractions of the image: a car at a
    hundred and forty metres is eight pixels wide on this camera and a car at
    forty is thirty, and a test that draws the same rectangle at both distances
    is measuring its own framing rather than the watcher.

    pool_to is where the pool of the headlights reaches on the tarmac, given as
    another point of the picture. It is drawn between the bumper and there,
    pale and wide. Without it a night-time car is a dark shape on dark ground,
    which is not what this camera sees.
    """
    height, width = frame.shape[:2]
    across, up = scale
    if not (across > 0 and up > 0):
        raise ValueError("Une voiture se dessine en mètres : il faut l'échelle du terrain sous elle")
    wide_px, tall_px = across * width, up * height
    base_x, base_y = spot[0] * width, spot[1] * height
    out = frame.astype(np.float32)

    if pool_to is not None:
        glow = np.zeros((height, width), dtype=np.float32)
        far_x, far_y = pool_to[0] * width, pool_to[1] * height
        steps = 18
        for index in range(steps):
            along = (index + 1) / steps
            x = base_x + (far_x - base_x) * along
            y = base_y + (far_y - base_y) * along
            # The pool widens as it goes and fades with the square of the way,
            # as light does.
            radius = max(1.0, (POOL_WIDE_M * 0.5) * wide_px * (0.4 + along))
            cv2.circle(glow, (int(x), int(y)), int(radius), float((1.0 - along) ** 2), -1)
        blur = max(3, int(POOL_WIDE_M * wide_px / 4) | 1)
        glow = cv2.GaussianBlur(glow, (blur, blur), 0)
        glow = np.clip(glow, 0, 1)[:, :, None]
        out = out * (1 - glow * 0.8) + np.float32(215) * glow * 0.8

    half = CAR_WIDE_M * wide_px / 2
    tall = CAR_TALL_M * tall_px
    cv2.rectangle(out, (int(base_x - half), int(base_y - tall)), (int(base_x + half), int(base_y)),
                  (float(body), float(body), float(body)), -1)
    if lights:
        # The lamps and their glare, not the bodywork. At night this camera
        # shows almost nothing of the car itself: what reads as a yellow car on
        # the roundabout is the headlights, and the paint has no part in it. So
        # the bright thing is drawn warm and bleeding into the air around it,
        # which is what the sensor does with a light pointed at it.
        lamp = max(1, int(LAMP_M * wide_px))
        halo = np.zeros((height, width), dtype=np.float32)
        for side in (-1, 1):
            x, y = int(base_x + side * half * 0.7), int(base_y - tall * 0.45)
            cv2.circle(halo, (x, y), max(lamp * 4, 3), 1.0, -1)
        halo = cv2.GaussianBlur(halo, (max(3, lamp * 6 | 1), max(3, lamp * 6 | 1)), 0)
        halo = np.clip(halo, 0, 1)[:, :, None]
        out = out * (1 - halo) + np.float32(LAMP_BGR) * halo
        for side in (-1, 1):
            cv2.circle(out, (int(base_x + side * half * 0.7), int(base_y - tall * 0.45)), lamp,
                       (250.0, 252.0, 252.0), -1)
    return np.clip(out, 0, 255).astype(np.uint8)


def trail(frame: np.ndarray, line: list[tuple[float, float]], lift: float = 6.0,
          across: float = 0.010, seed: int = 0) -> np.ndarray:
    """Lay a condensation trail along a path through the picture.

    A contrail is not a stroke of constant brightness: it is thickest and
    sharpest where it was laid last, and older stretches have spread and faded
    into the sky. Drawing it evenly would make the detector look better than it
    is, since the faint end is the half that decides whether a real trail is
    found or missed, so the brightness falls off along the line and the width
    grows to match.

    lift is how far above the sky the freshest end sits, in levels of grey; it
    is the one number worth sweeping, because it is what the measurement in
    watcher/contrail.py reads back.
    """
    out = frame.astype(np.float32)
    if len(line) < 2:
        return np.clip(out, 0, 255).astype(np.uint8)
    height, width = frame.shape[:2]
    rng = np.random.default_rng(seed)
    paint = np.zeros((height, width), np.float32)
    for index, ((x1, y1), (x2, y2)) in enumerate(zip(line, line[1:])):
        # The line is ordered oldest first, so the fresh end is the last
        # segment and age runs backwards from it.
        age = 1.0 - index / max(1, len(line) - 1)
        fade = math.exp(-2.2 * age)
        thick = across * width * (1.0 + 2.5 * age)
        cv2.line(paint, (int(x1 * width), int(y1 * height)), (int(x2 * width), int(y2 * height)),
                 float(lift * fade), max(1, int(thick)))
    paint = cv2.GaussianBlur(paint, (0, 0), max(1.5, 0.004 * width))
    paint *= 1.0 + rng.normal(0, 0.25, paint.shape).astype(np.float32)
    return np.clip(out + paint[:, :, None], 0, 255).astype(np.uint8)


def sensor_noise(frame: np.ndarray, seed: int = 0) -> np.ndarray:
    """The grain a real webcam has, so the still frames are not identical.

    Without it the background subtractor learns a perfect background and the
    test is kinder than reality.
    """
    rng = np.random.default_rng(seed)
    grain = rng.normal(0, 1.6, frame.shape).astype(np.float32)
    return np.clip(frame.astype(np.float32) + grain, 0, 255).astype(np.uint8)
