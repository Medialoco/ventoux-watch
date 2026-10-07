"""Background subtraction, then one track per compact moving blob."""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from watcher.geometry import assign_zone


# Deux minutes de présence à une image par seconde. Au-delà, ce n'est plus un
# passage mais quelque chose qui stationne, et la trajectoire n'apprend rien.
TRACE_MAX = 120

# Trois signes, dits à voix haute sans se tromper de lettre.
#
# Pas de 0, de O, de 1, de I ni de L : au téléphone comme dans un message,
# ces cinq-là se confondent et le code qu'on me rapporte ne serait plus
# celui de la piste. Vingt-trois lettres et huit chiffres font assez de
# combinaisons pour qu'une nuit chargée ne rejoue pas le même avant longtemps.
_LETTRES = "ABCDEFGHJKMNPQRSTUVWXYZ"
_CHIFFRES = "23456789"


def signe(numero: int) -> str:
    """Un code court et stable pour une piste, du genre K7M.

    On le lit sur l'image et on le redit tel quel. L'ordre est une lettre,
    un chiffre, une lettre : trois signes, jamais une suite de chiffres
    qu'on prendrait pour une heure.
    """
    n = max(0, int(numero) - 1)
    return (_LETTRES[n % len(_LETTRES)]
            + _CHIFFRES[(n // len(_LETTRES)) % len(_CHIFFRES)]
            + _LETTRES[(n // (len(_LETTRES) * len(_CHIFFRES))) % len(_LETTRES)])


@dataclass
class Track:
    id: int
    zone: str
    frames: int = 0
    misses: int = 0
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    first_centroid: tuple[float, float] = (0.0, 0.0)
    centroid: tuple[float, float] = (0.0, 0.0)
    area_ratio: float = 0.0
    first_area: float = 0.0
    best_area: float = 0.0
    best_bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    # Où la chose était, image par image, avec l'heure de chaque image.
    #
    # On n'en gardait qu'une : celle où la tache était la plus grande. Le flux
    # la reposait alors telle quelle pendant quatre secondes, si bien que le
    # rectangle restait planté pendant que la voiture continuait sa route et
    # finissait par désigner un bout de bitume vide. La trajectoire, elle, est
    # déjà connue — elle est suivie à chaque image, elle était simplement jetée.
    #
    # Quelques dizaines de points de cinq nombres : le coût est nul à côté de la
    # vignette qui accompagne la même fiche.
    trace: list[tuple[float, tuple[int, int, int, int]]] = field(default_factory=list)
    best_jpeg: bytes = b""
    started: float = 0.0
    updated: float = 0.0
    first_top: float = 0.0
    top: float = 0.0
    first_base: float = 0.0
    base: float = 0.0
    first_foot_x: float = 0.0
    foot_x: float = 0.0
    shade: float = 1.0
    texture: float = 0.0
    code: str = ""
    # Déjà fêté : on ne redemande plus la classe, et on ne compte pas deux fois.
    tenu: bool = False
    # Déjà porté au tableau. Une classe publiée compte même sous la barre
    # du good catch, et une relecture plus tard ne doit pas la compter encore.
    compte: bool = False
    essai: float = 0.0

    def __post_init__(self) -> None:
        if not self.code:
            self.code = signe(self.id)

    @property
    def rise(self) -> float:
        """How far the top of the blob has climbed, as a share of the frame.

        A plume grows upwards while a car, a walker or a shadow does not.
        """
        return max(0.0, self.first_top - self.top)

    @property
    def foot_climb(self) -> float:
        """How far the foot of the blob has lifted off the ground it began on.

        A rising top proves nothing on its own: a cloud drifting up the slope
        has one too, and on the morning of 27 September three of them were
        published as starts of fire. What separates them is the foot. Smoke is
        rooted at the point that burns, so its top climbs while its foot stays
        put, or even spreads downhill as the fire widens. A cloud carries its
        whole body along and lifts its foot by as much as its top.

        Signed on purpose. A fire that spreads downhill gives a negative
        figure, and that must not be mistaken for the thing it is the opposite
        of.
        """
        return self.first_base - self.base

    @property
    def drift(self) -> float:
        """How far the foot has crossed the picture, sideways, as a share of it.

        Fire stays where the fuel is. It widens, it climbs, it leans with the
        wind, but the ground it burns does not move. Anything whose foot walks
        across the frame carries its own source with it, which is what an
        engine does and a fire cannot.

        Recorded, not judged on, and the difference was earned. This was built
        on 28 September to refuse the tractor that had been published as a
        start of fire, and measuring it settled the matter the other way: a
        real lorry on the road gave 0.063 of its width a second and a genuine
        plume, drawn at its true size, gave 0.082. The two overlap. Rather than
        a footprint that stays put, what the plume has and the tractor has not
        is buoyancy, which is read from the climb in metres a second.

        Straightness was tried as a rescue — distance made over ground covered,
        on the idea that a machine walks in a line and a ragged foot shuffles —
        and it failed too: a plume leaning in a steady wind scored up to 0.94,
        which is as straight as anything driving. It was removed.

        The figure stays in the record because the next case of this kind will
        be diagnosed from what was written down, not from guesswork.
        """
        return abs(self.foot_x - self.first_foot_x)

    @property
    def lighting(self) -> tuple[float, float]:
        """Le niveau et la texture de la tache, comparés au fond mémorisé.

        Le premier nombre est le rapport des clartés : au-dessous de un la
        tache est plus sombre que le fond qu'elle recouvre, au-dessus elle est
        plus claire. Le second est la part de la tache où le décor d'avant se
        voit encore.

        C'est là qu'est la séparation. Une ombre qui passe et la flaque des
        phares changent la clarté sans toucher au dessin : le muret reste le
        muret, ses pierres sont à leur place, simplement plus sombres ou plus
        claires, et la part vaut un. Une chose qui passe cache ce qu'il y a
        derrière, et la part tombe à ce qu'elle laisse dépasser.

        Pris sur la vue où la tache était la plus grande, faute de quoi une
        voiture jugée sur l'image où elle n'était encore qu'un coin d'aile
        ressemblerait à un changement de lumière.
        """
        return self.shade, self.texture

    @property
    def travel(self) -> float:
        dx = self.centroid[0] - self.first_centroid[0]
        dy = self.centroid[1] - self.first_centroid[1]
        return (dx * dx + dy * dy) ** 0.5

    @property
    def area_grow(self) -> float:
        if self.first_area <= 0:
            return 1.0
        return self.area_ratio / self.first_area


@dataclass
class MotionStep:
    ended: list[Track] = field(default_factory=list)
    global_change: bool = False


class MotionDetector:
    def __init__(
        self,
        zones: dict,
        motion_width: int = 640,
        min_track_frames: int = 3,
        max_foreground_ratio: float = 0.35,
        warmup_frames: int = 8,
    ):
        self.zones = zones
        self.motion_width = motion_width
        self.min_track_frames = min_track_frames
        self.max_foreground_ratio = max_foreground_ratio
        self.warmup_frames = warmup_frames
        self.bg = cv2.createBackgroundSubtractorMOG2(history=120, varThreshold=24, detectShadows=False)
        self.tracks: list[Track] = []
        self._next_id = 1
        self._seen = 0

    def step(self, frame: np.ndarray, now: float) -> MotionStep:
        small, scale = _resize_width(frame, self.motion_width)
        self._seen += 1
        if self._seen <= self.warmup_frames:
            self.bg.apply(small, learningRate=-1)
            return MotionStep()
        mask = self.bg.apply(small, learningRate=0)
        mask = _prepare_mask(mask, self.zones, small.shape[1], small.shape[0])
        ratio = float(cv2.countNonZero(mask)) / float(mask.size)
        if ratio > self.max_foreground_ratio:
            return MotionStep(global_change=True)
        # Read before the model is taught this frame, so it still holds the
        # scene as it was without the thing that just moved.
        behind = self.bg.getBackgroundImage()
        self.bg.apply(small, learningRate=-1)
        blobs = _blobs(mask, scale)
        for blob in blobs:
            blob["shade"], blob["texture"] = _lighting(small, behind, blob["bbox"], scale)
        return self._update_tracks(blobs, frame, now)

    def _update_tracks(self, blobs: list[dict], frame: np.ndarray, now: float) -> MotionStep:
        unused = set(range(len(self.tracks)))
        for blob in formes_utiles(blobs, self.zones):
            zone = assign_zone(blob["cx"], blob["cy"], self.zones)
            span = _bbox_span(blob["bbox"], frame.shape[1], frame.shape[0])
            match = self._match(blob["cx"], blob["cy"], zone, unused, span,
                                frame.shape[:2])
            if match is None:
                track = Track(
                    id=self._next_id,
                    zone=zone,
                    bbox=blob["bbox"],
                    first_centroid=(blob["cx"], blob["cy"]),
                    centroid=(blob["cx"], blob["cy"]),
                    area_ratio=blob["area_ratio"],
                    first_area=blob["area_ratio"],
                    best_area=blob["area_ratio"],
                    best_bbox=blob["bbox"],
                    started=now,
                    updated=now,
                    frames=1,
                    first_top=blob["top"],
                    top=blob["top"],
                    first_base=blob["base"],
                    base=blob["base"],
                    first_foot_x=blob["foot_x"],
                    foot_x=blob["foot_x"],
                    shade=blob.get("shade", 1.0),
                    texture=blob.get("texture", 0.0),
                    trace=[(now, blob["bbox"])],
                )
                self._next_id += 1
                track.best_jpeg = _jpeg(frame)
                self.tracks.append(track)
                continue
            unused.discard(match)
            track = self.tracks[match]
            track.frames += 1
            track.misses = 0
            track.centroid = (blob["cx"], blob["cy"])
            track.top = blob["top"]
            track.base = blob["base"]
            track.foot_x = blob["foot_x"]
            track.bbox = blob["bbox"]
            track.area_ratio = blob["area_ratio"]
            track.updated = now
            if len(track.trace) < TRACE_MAX:
                track.trace.append((now, blob["bbox"]))
            if _better_view(track, blob, frame):
                track.best_area = blob["area_ratio"]
                track.best_bbox = blob["bbox"]
                track.best_jpeg = _jpeg(frame)
                # Sur la vue où la tache est la plus grande : une voiture jugée
                # sur l'image où elle n'était qu'un coin d'aile passerait pour
                # un changement de lumière.
                track.shade = blob.get("shade", 1.0)
                track.texture = blob.get("texture", 0.0)

        ended: list[Track] = []
        kept: list[Track] = []
        for index, track in enumerate(self.tracks):
            if index in unused and track.frames > 0 and track.updated != now:
                track.misses += 1
            if track.misses >= 2:
                needed = 3 if track.zone in {"sky", "slope"} else self.min_track_frames
                if track.frames >= needed:
                    ended.append(track)
                continue
            kept.append(track)
        self.tracks = kept
        return MotionStep(ended=ended)

    def _match(self, cx: float, cy: float, zone: str, unused: set[int],
               span: float = 0.0, frame_size: tuple[int, int] | None = None) -> int | None:
        """Nearest open track, whatever zone the blob has drifted into.

        A track keeps the zone it was born in. A plume climbs off the slope and
        its centre ends up in the sky, but it is the same fire, rooted in the
        same place: refusing the match would restart the clock every time and
        no fire would ever last long enough to be called one.

        The floor is a share of the field of view. A thing this large can also
        jump its own width in one second when it is close: two boxes one
        length apart are still the same body, not two. Adding the two spans
        is that length, in the same units, on any camera.
        """
        best_index = None
        best_distance = 0.0
        haut, large = frame_size or (0, 0)
        for index in unused:
            track = self.tracks[index]
            other = _bbox_span(track.bbox, large, haut) if frame_size else 0.0
            base = 0.28 if "sky" in {zone, track.zone} else 0.18
            limit = max(base, span + other)
            distance = ((track.centroid[0] - cx) ** 2 + (track.centroid[1] - cy) ** 2) ** 0.5
            if distance > limit:
                continue
            if best_index is not None and distance > best_distance:
                continue
            best_distance = distance
            best_index = index
        return best_index


# L'écume n'est pas une forme. En dessous, une tache sur l'eau ne devient pas
# une piste : à chaque vague elles seraient des centaines, et le modèle n'aurait
# plus le temps des voitures. Au-dessus, on n'en garde qu'une poignée, les
# plus grandes — un bateau, une déferlante — pour que le dessin reste.
SEA_MIN_AREA = 0.0012
SEA_GARDES = 4
BEACH_GARDES = 6


def formes_utiles(blobs: list[dict], zones: dict) -> list[dict]:
    """Ce qui mérite une piste.

    La route et le trottoir passent tous. La mer et le sable n'en gardent que
    les grandes taches : le reste est l'écume, et la classer ralentirait
    l'image sans rien ajouter au dessin.
    """
    mer: list[dict] = []
    plage: list[dict] = []
    reste: list[dict] = []
    for blob in blobs:
        zone = assign_zone(blob["cx"], blob["cy"], zones)
        aire = blob["area_ratio"]
        if zone == "sea":
            if aire >= SEA_MIN_AREA:
                mer.append(blob)
            continue
        if zone == "beach":
            if aire >= 0.0004:
                plage.append(blob)
            continue
        if zone == "sky" and aire < 0.00005:
            continue
        if zone != "sky" and aire < 0.0004:
            continue
        reste.append(blob)
    mer.sort(key=lambda blob: blob["area_ratio"], reverse=True)
    plage.sort(key=lambda blob: blob["area_ratio"], reverse=True)
    return reste + mer[:SEA_GARDES] + plage[:BEACH_GARDES]


# Ce qu'on dessine souvent, et qu'on ne donne pas au modèle. Plus petit que
# le plancher d'une piste : une voiture loin sur la route reste un rectangle,
# elle ne devient pas une prise.
AFFICHE_AIRE = 0.00012
AFFICHE_PLAGE = 0.0008
AFFICHE_PORTEE = 0.12
AFFICHE_TRACE = 8
AFFICHE_TROUS = 2
AFFICHE_MAX = 8


class Afficheur:
    """Le déplacement à l'écran. Aucune de ces boîtes n'est une piste.

    La veille, elle, continue de ne classer que ce qui a déjà passé son
    plancher. Ici on suit plus souvent, et plus petit, pour que le trait
    bouge. La mer et le ciel restent dehors : l'écume et les nuages
    rempliraient l'image sans rien qui se déplace.
    """

    def __init__(self, zones: dict, motion_width: int = 640, warmup_frames: int = 5):
        self.zones = zones or {"priority": [], "polygons": {}}
        self.motion_width = motion_width
        self.warmup_frames = warmup_frames
        self.max_foreground_ratio = 0.35
        self.bg = cv2.createBackgroundSubtractorMOG2(
            history=60, varThreshold=16, detectShadows=False)
        self._seen = 0
        self._numero = 1
        self._pistes: list[dict] = []

    def oublie(self) -> None:
        """Le fond d'une webcam ne vaut rien sur l'autre."""
        self.bg = cv2.createBackgroundSubtractorMOG2(
            history=60, varThreshold=16, detectShadows=False)
        self._seen = 0
        self._pistes = []

    def voit(self, image: np.ndarray) -> list[dict]:
        """Des boîtes et leur traînée, en parts d'image. Rien d'autre."""
        small, scale = _resize_width(image, self.motion_width)
        self._seen += 1
        if self._seen <= self.warmup_frames:
            self.bg.apply(small, learningRate=-1)
            return []
        mask = self.bg.apply(small, learningRate=0)
        mask = _prepare_mask(mask, self.zones, small.shape[1], small.shape[0])
        # La mer avant les contours. Chaque vague serait une tache, et Cannes
        # passerait son temps à les compter.
        _eteint(mask, self.zones, ("sea",))
        ratio = float(cv2.countNonZero(mask)) / float(mask.size)
        if ratio > self.max_foreground_ratio:
            self._vieillit()
            return []
        self.bg.apply(small, learningRate=-1)
        hauteur, largeur = image.shape[:2]
        utiles = []
        for blob in _blobs(mask, scale):
            zone = assign_zone(blob["cx"], blob["cy"], self.zones)
            aire = blob["area_ratio"]
            if zone in {"sea", "sky"}:
                continue
            if zone == "beach" and aire < AFFICHE_PLAGE:
                continue
            if zone != "beach" and aire < AFFICHE_AIRE:
                continue
            utiles.append(blob)
        self._rattache(utiles, largeur, hauteur)
        return [piste for piste in self._pistes if piste["misses"] == 0]

    def _vieillit(self) -> None:
        for piste in self._pistes:
            piste["misses"] += 1
        self._pistes = [piste for piste in self._pistes if piste["misses"] <= AFFICHE_TROUS]

    def _rattache(self, blobs: list[dict], largeur: int, hauteur: int) -> None:
        pris: set[int] = set()
        for piste in self._pistes:
            cx, cy = piste["trace"][-1]
            meilleur = None
            distance = AFFICHE_PORTEE
            for index, blob in enumerate(blobs):
                if index in pris:
                    continue
                ecart = ((blob["cx"] - cx) ** 2 + (blob["cy"] - cy) ** 2) ** 0.5
                if ecart < distance:
                    meilleur, distance = index, ecart
            if meilleur is None:
                piste["misses"] += 1
                continue
            pris.add(meilleur)
            blob = blobs[meilleur]
            piste["misses"] = 0
            piste["box"] = _boite_affiche(blob, largeur, hauteur)
            piste["trace"].append((blob["cx"], blob["cy"]))
            del piste["trace"][:-AFFICHE_TRACE]
        for index, blob in enumerate(blobs):
            if index in pris or len(self._pistes) >= AFFICHE_MAX:
                continue
            self._pistes.append({
                "box": _boite_affiche(blob, largeur, hauteur),
                "trace": [(blob["cx"], blob["cy"])],
                "misses": 0,
                "code": signe(self._numero),
            })
            self._numero += 1
        self._pistes = [piste for piste in self._pistes if piste["misses"] <= AFFICHE_TROUS]


def _eteint(mask: np.ndarray, zones: dict, noms: tuple[str, ...]) -> None:
    """Met à zéro ces zones. Les contours ne les voient plus."""
    height, width = mask.shape[:2]
    polygones = zones.get("polygons") or {}
    for nom in noms:
        poly = polygones.get(nom)
        if not poly or len(poly) < 3:
            continue
        points = np.array(
            [[int(x * (width - 1)), int(y * (height - 1))] for x, y in poly],
            np.int32)
        cv2.fillPoly(mask, [points], 0)


def _boite_affiche(blob: dict, largeur: int, hauteur: int) -> tuple[float, float, float, float]:
    x, y, w, h = blob["bbox"]
    return (x / largeur, y / hauteur, max(w, 1) / largeur, max(h, 1) / hauteur)


def _lighting(small, behind, bbox, scale: float) -> tuple[float, float]:
    """Combien la tache a changé de clarté, et combien son dessin a survécu.

    Le dessin est jugé par la corrélation des deux morceaux une fois leur
    moyenne retirée : elle vaut un si le fond est intact sous une autre
    lumière, et tombe vers zéro si quelque chose s'est mis devant. Retirer la
    moyenne est ce qui rend la mesure aveugle au niveau, donc capable de
    répondre à une question et une seule.
    """
    if behind is None or behind.size == 0:
        return 1.0, 0.0
    # Les boîtes sortent de _blobs en coordonnées pleine image ; le fond, lui,
    # est à la taille réduite où le mouvement est cherché.
    x, y, w, h = (int(round(value * scale)) for value in bbox)
    height, width = small.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + max(w, 1)), min(height, y + max(h, 1))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return 1.0, 0.0
    now = cv2.cvtColor(small[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    was = cv2.cvtColor(behind[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    shade = float(now.mean() / max(1.0, was.mean()))
    return shade, _kept(now, was)


# Le côté d'un carreau, en pixels de l'image réduite. Mesurer la corrélation
# sur la tache entière ne marche pas contre une lumière structurée : la flaque
# des phares a son propre dégradé, très fort, qui écrase le grain du bitume et
# fait tomber la corrélation d'ensemble à 0,19 alors que le bitume est toujours
# là-dessous. Sur un carreau, en revanche, l'éclairement est à peu près
# constant, et la question redevient celle qu'on voulait poser.
TILE = 4
# À partir de quoi le dessin d'un carreau est tenu pour survivant. La
# corrélation d'un carreau inchangé sous une autre lumière vaut près de un ;
# d'un carreau caché par une carrosserie, elle tourne autour de zéro. La moitié
# est loin des deux.
KEPT = 0.5


def _kept(now: np.ndarray, was: np.ndarray) -> float:
    """La part de la tache où le décor d'avant se voit encore.

    Un carreau à la fois, parce qu'une lumière peut être structurée mais reste
    lisse : sur quatre pixels de côté elle se réduit à un gain, et un gain ne
    touche pas à la corrélation. Une chose qui passe, elle, cache ce qui est
    derrière, et les carreaux qu'elle couvre perdent le dessin.

    La part plutôt que la moyenne, car c'est la question posée : une voiture qui
    n'occupe que la moitié de sa tache laisse l'autre moitié intacte, et une
    moyenne la dirait à demi transparente au lieu de dire qu'une moitié est
    cachée.

    Zéro quand rien ne peut être jugé — un fond sans grain n'a pas de dessin à
    conserver — ce qui veut dire « je ne sais pas » et non « c'est un objet ».
    """
    tiles = 0
    kept = 0
    for top in range(0, now.shape[0] - TILE + 1, TILE):
        for left in range(0, now.shape[1] - TILE + 1, TILE):
            a = now[top:top + TILE, left:left + TILE]
            b = was[top:top + TILE, left:left + TILE]
            a, b = a - a.mean(), b - b.mean()
            grain = float(np.sqrt((b * b).sum()))
            if grain < 1e-3:
                # Rien à conserver ici : ce carreau du fond n'avait pas de
                # dessin, et il ne peut donc rien dire dans un sens ni l'autre.
                continue
            tiles += 1
            trace = float(np.sqrt((a * a).sum()))
            if trace < 1e-3:
                # Le fond avait du grain et il n'en reste rien : c'est la preuve
                # la plus nette qu'une chose s'est mise devant. Une carrosserie
                # unie tombe exactement là, et sauter ces carreaux la faisait
                # passer pour un décor intact.
                continue
            if float((a * b).sum() / (grain * trace)) >= KEPT:
                kept += 1
    if not tiles:
        return 0.0
    return kept / tiles


def _masque_objet(now: np.ndarray, was: np.ndarray) -> np.ndarray | None:
    """Carreau par carreau : vrai là où le décor d'avant a disparu.

    Même question que « _kept », posée carreau par carreau et rendue en entier
    au lieu d'être résumée en un nombre. C'est la même mesure, le même seuil,
    la même justification — seul le résultat est gardé au lieu d'être compté.
    """
    hauteur = now.shape[0] // TILE
    largeur = now.shape[1] // TILE
    if hauteur < 1 or largeur < 1:
        return None
    masque = np.zeros((hauteur, largeur), np.uint8)
    for ligne in range(hauteur):
        for colonne in range(largeur):
            haut, gauche = ligne * TILE, colonne * TILE
            a = now[haut:haut + TILE, gauche:gauche + TILE]
            b = was[haut:haut + TILE, gauche:gauche + TILE]
            a, b = a - a.mean(), b - b.mean()
            grain = float(np.sqrt((b * b).sum()))
            if grain < 1e-3:
                continue
            trace = float(np.sqrt((a * a).sum()))
            if trace < 1e-3:
                masque[ligne, colonne] = 1
                continue
            if float((a * b).sum() / (grain * trace)) < KEPT:
                masque[ligne, colonne] = 1
    return masque


def _bbox_span(bbox: tuple[int, int, int, int], largeur: int, hauteur: int) -> float:
    """Le plus grand côté de la boîte, en part de l'image."""
    if not bbox or largeur < 1 or hauteur < 1:
        return 0.0
    return max(bbox[2] / largeur, bbox[3] / hauteur)


def _coeur(now: np.ndarray, was: np.ndarray) -> tuple[int, int, int, int] | None:
    """Dans la tache, la boîte de ce qui s'est vraiment mis devant le décor.

    Une tache de mouvement n'est pas la forme de la chose qui a bougé : la nuit
    elle est surtout la flaque des phares sur le bitume, qui suit la voiture et
    fait trois fois sa taille. On mesurait alors huit mètres de large pour une
    berline, et on montrait au détecteur une fenêtre pleine de goudron éclairé
    où il ne lisait rien — c'est mesuré : entre vingt heures et cinq heures,
    pas une seule lecture sur le moindre passage, toute la nuit.

    La lumière et l'objet ne font pourtant pas la même chose au décor. Une
    flaque de phares multiplie le bitume par un gain : les bandes blanches et
    le grain restent dessous, le dessin survit. Une carrosserie le remplace.
    C'est déjà ce que mesure « _kept » pour décider si une tache est un objet
    ou un changement de lumière ; ici on lui demande seulement *où*, et on
    garde cette partie-là.

    Le plus grand morceau d'un seul tenant, pas tous les carreaux : une chose
    est contiguë, et deux carreaux isolés dans un coin sont du bruit. Rien si
    aucun morceau ne tient debout — alors la tache garde sa boîte et les règles
    d'après la jugeront comme avant.
    """
    masque = _masque_objet(now, was)
    if masque is None or not masque.any():
        return None
    morceaux, reperes, stats, _ = cv2.connectedComponentsWithStats(masque, 8)
    if morceaux < 2:
        return None
    plus_gros = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = (int(stats[plus_gros, i]) for i in
                  (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
    return x * TILE, y * TILE, w * TILE, h * TILE


def _resize_width(frame: np.ndarray, width: int) -> tuple[np.ndarray, float]:
    height, frame_width = frame.shape[:2]
    if frame_width <= width:
        return frame, 1.0
    scale = width / float(frame_width)
    resized = cv2.resize(frame, (width, int(height * scale)), interpolation=cv2.INTER_AREA)
    return resized, scale


def _prepare_mask(mask: np.ndarray, zones: dict, width: int, height: int) -> np.ndarray:
    binary = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)[1]
    for circle in zones.get("exclude", []):
        center = (int(circle["cx"] * width), int(circle["cy"] * height))
        radius = int(circle["r"] * width)
        cv2.circle(binary, center, radius, 0, -1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)


def _blobs(mask: np.ndarray, scale: float) -> list[dict]:
    found = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = found[0] if len(found) == 2 else found[1]
    height, width = mask.shape[:2]
    blobs = []
    for contour in contours:
        if cv2.contourArea(contour) < 8:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        blobs.append(
            {
                "cx": (x + w / 2) / width,
                "cy": (y + h / 2) / height,
                "top": y / height,
                "base": (y + h) / height,
                "foot_x": _foot_x(contour, width),
                "bbox": (int(x / scale), int(y / scale), max(int(w / scale), 1), max(int(h / scale), 1)),
                "area_ratio": (w * h) / float(width * height),
            }
        )
    return blobs


def _blob_clipped(bbox: tuple[int, int, int, int], frame: np.ndarray) -> bool:
    """La tache touche-t-elle le bord de l'image ?

    Coupée, sa taille n'est plus une mesure de la chose : c'est un plancher.
    """
    haut, large = frame.shape[:2]
    x, y, w, h = bbox
    mx, my = max(1, int(0.002 * large)), max(1, int(0.002 * haut))
    return x <= mx or y <= my or x + w >= large - mx or y + h >= haut - my


def _better_view(track: Track, blob: dict, frame: np.ndarray) -> bool:
    """Cette tache est-elle une meilleure vue de la chose que celle qu'on garde ?

    La plus grande est d'ordinaire la plus proche. Pas quand elle est coupée
    par le cadre : cette taille est un plancher, et sur la route c'est souvent
    la flaque qu'une voiture laisse en sortant. Une plume qui grandit hors du
    haut de la pente, c'est l'inverse — là, la croissance *est* la chose —
    donc le ciel et le versant prennent encore la plus grande, coupée ou non.
    """
    if blob["area_ratio"] < track.best_area:
        return False
    if track.zone in {"sky", "slope"}:
        return True
    if not _blob_clipped(blob["bbox"], frame):
        return True
    return _blob_clipped(track.best_bbox, frame)


def _foot_x(contour: np.ndarray, width: int) -> float:
    """Where the blob touches down, as a share of the frame.

    Not the middle of the blob: the middle of a plume leans downwind within
    seconds of catching, and a plume that leans is still a fire burning in one
    spot. What stays over the fuel is the lowest part of the shape. Taking the
    average x of the rows nearest the bottom rather than a single point, so one
    stray pixel of shadow does not move the foot.
    """
    points = contour.reshape(-1, 2)
    low = points[:, 1].max()
    bottom = points[points[:, 1] >= low - 2]
    return float(bottom[:, 0].mean()) / float(width)


def _jpeg(frame: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        return b""
    return encoded.tobytes()


def _crop(jpeg: bytes, bbox=None):
    if not jpeg:
        return None
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return None
    if not bbox or not any(bbox):
        return image
    height, width = image.shape[:2]
    x, y, w, h = bbox
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + max(w, 1)), min(height, y + max(h, 1))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return image
    return image[y0:y1, x0:x1]


def warm_ratio(jpeg: bytes, bbox=None) -> float:
    """How much of the blob has the colour of a flame."""
    image = _crop(jpeg, bbox)
    if image is None:
        return 0.0
    blue = image[:, :, 0].astype(np.int16)
    green = image[:, :, 1].astype(np.int16)
    red = image[:, :, 2].astype(np.int16)
    warm = (red > 140) & (red > green + 25) & (red > blue + 25)
    return float(np.count_nonzero(warm)) / float(warm.size)


def smoke_ratio(jpeg: bytes, bbox=None) -> float:
    """How much of the blob looks like a plume: pale, grey, and not the sky.

    Smoke shows before flame, and from a kilometre away it is all a camera will
    ever see of a fire that has just started. It has almost no colour, it is
    brighter than the wood behind it, and it is never as blue as the sky.

    Measured over the whole box, and not over the moving pixels alone. That was
    tried on 27 September and taken out the same day. The reasoning looked
    sound — the box holds the hillside as well as the thing, so the share ought
    to be diluted — and it is wrong twice over. Measured, the mask changed no
    verdict at all on three simulated fires. And it cuts the wrong way: a cloud
    is pale and moving too, so counting only what moved raises its share as
    surely as a plume's, which is the opposite of what is wanted.

    The reason the detector looked blind that morning was not the denominator.
    The fire had been simulated at a spot that sits against the sky in that
    frame, where a veil of smoke stays blue and `blue - red` refuses it — one
    hundred per cent of those pixels were bright enough and a third were pale
    enough, but almost none passed the test for not being sky. Put the same
    fire on the slope and it is named within six seconds.
    """
    image = _crop(jpeg, bbox)
    if image is None:
        return 0.0
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1].astype(np.int16)
    value = hsv[:, :, 2].astype(np.int16)
    blue = image[:, :, 0].astype(np.int16)
    red = image[:, :, 2].astype(np.int16)
    plume = (saturation < 55) & (value > 90) & (blue - red < 25)
    return float(np.count_nonzero(plume)) / float(plume.size)
