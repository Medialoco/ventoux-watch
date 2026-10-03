"""YOLO nano via ONNX Runtime. Missing model means no class labels."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from watcher.naming import Detection

COCO = {
    0: "person",
    # A rider reads as a person from here, which is how every scooter, every
    # motorbike and every cyclist on this roundabout came to be filed as a
    # walker. The machine under them has its own class and always had.
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
    4: "airplane",
    # Dogs are walked here all day. One was standing beside a pedestrian on the
    # crossing, unnamed, because nothing in the list could hold it.
    16: "dog",
    # Et le chat manquait, ce qui était pire que de ne pas savoir le nommer :
    # une ligne dont la classe de tête n'est pas des nôtres était jetée
    # entière, si bien qu'un chat lu « chat » franchement emportait avec lui la
    # lecture « chien » ou « piéton » qui l'accompagnait. On ne perdait pas le
    # nom du chat, on perdait le fait qu'il y avait quelque chose.
    15: "cat",
    17: "horse",
}
KEEP = set(COCO)
_NOTRES = np.array(sorted(KEEP))

# La part de l'image que le sujet doit occuper quand on la montre au modèle.
#
# Un réseau entraîné sur des photographies n'a jamais vu d'objet collé aux
# quatre bords : il y a toujours du décor autour. On lui en donnait pourtant un
# — la fenêtre était taillée au ras de la tache — et il répondait n'importe
# quoi. Une Renault vue de trois quarts, pleine lucarne, se lisait « bateau » à
# 0,77 tandis que « voiture » restait à 0,077. La même image reculée dans la
# toile se lit « voiture » à 0,95. Ce n'est pas un seuil à baisser : c'est un
# cadrage à rendre.
#
# Mesuré sur les passages des 2 et 3 octobre, chaque gros plan reposé à sa
# place dans une vraie image de la scène — un premier balayage qui entourait le
# sujet de gris avait fait choisir 45 %, ce qui était l'effet du gris et non
# celui du cadrage. Part occupée contre lectures exploitables :
#
#                  ancien   45 %   35 %   28 %   22 %   16 %   11 %
#   véhicules (155)   89 %   91 %   91 %   90 %   91 %   81 %   86 %
#   piétons    (40)   72 %   80 %   85 %   88 %   90 %   95 %   88 %
#
# Les deux familles ne veulent pas la même chose : une voiture se lit sur sa
# silhouette, un piéton sur ce qui l'entoure — la route sous lui, l'échelle des
# choses à côté. Vingt-deux pour cent est le point où aucune des deux ne perd.
#
# C'est une part et non un nombre de pixels, donc elle vaut pour une tache de
# trente pixels comme pour une de six cents, et elle vaudra pour la caméra
# suivante quelle que soit sa définition.
SUJET_PART = 0.22


class YoloDetector:
    def __init__(self, model_path: str):
        self.session = None
        self.input_name = ""
        path = Path(model_path)
        if not path.is_file():
            return
        import onnxruntime as ort

        self.session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    @property
    def ready(self) -> bool:
        return self.session is not None

    def detect(self, frame: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> list[Detection]:
        if self.session is None:
            return []
        left, top = 0, 0
        crop = frame
        if bbox is not None:
            left, top, crop = _cadre(frame, bbox, SUJET_PART)
        if crop.size == 0:
            return []
        blob, gain, (pad_x, pad_y) = _letterbox(crop, 640)
        raw = self.session.run(None, {self.input_name: blob})[0]
        # Where the model found it, kept. This was thrown away until 27
        # September, and the cost was a rectangle drawn on the motion blob
        # instead of on the thing named: a car and a group of walkers moved
        # together on the roundabout, the model read both, and the red box
        # landed on the walkers under the word "Voiture". The model knew where
        # the car was the whole time.
        found = []
        for x0, y0, x1, y1, conf, name in _nms(_parse(raw)):
            height, width = frame.shape[:2]
            x = min(max(0, int(left + (x0 - pad_x) / gain)), width - 1)
            y = min(max(0, int(top + (y0 - pad_y) / gain)), height - 1)
            w = min(int((x1 - x0) / gain), width - x)
            h = min(int((y1 - y0) / gain), height - y)
            found.append(Detection(name, conf, box=(x, y, max(1, w), max(1, h))))
        return found

    def locate(self, frame: np.ndarray) -> list[tuple[str, float, int, int, int, int]]:
        """Class boxes in the frame's own pixels. The box is the find, not a mask."""
        if self.session is None or frame.size == 0:
            return []
        blob, gain, (pad_x, pad_y) = _letterbox(frame, 640)
        raw = self.session.run(None, {self.input_name: blob})[0]
        height, width = frame.shape[:2]
        found = []
        for x0, y0, x1, y1, conf, name in _nms(_parse(raw)):
            left = int(round((x0 - pad_x) / gain))
            top = int(round((y0 - pad_y) / gain))
            right = int(round((x1 - pad_x) / gain))
            bottom = int(round((y1 - pad_y) / gain))
            left, top = max(0, left), max(0, top)
            right, bottom = min(width - 1, right), min(height - 1, bottom)
            if right - left < 2 or bottom - top < 2:
                continue
            found.append((name, conf, left, top, right - left, bottom - top))
        return found


def car_lights(frame: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> float:
    """How much of a blob is car lighting, between 0 and 1.

    After dark the model sees almost nothing, but a car carries its own marks:
    red tail lights, white headlights, and the pool of light they throw on the
    road. A walker carries none of that.
    """
    crop = frame if bbox is None else _crop(frame, bbox, margin=0.25)
    if crop is None or crop.size == 0:
        return 0.0
    blue, green, red = (channel.astype(np.int16) for channel in cv2.split(crop))
    tail = (red > 110) & (red - green > 45) & (red - blue > 35)
    head = (blue > 210) & (green > 210) & (red > 210)
    lit = float(np.count_nonzero(tail | head)) / float(crop.shape[0] * crop.shape[1])
    return min(1.0, lit)


def body_colour(frame: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> str:
    """The colour of a body, or nothing when it is not plain enough to say.

    Only the middle of the blob is read, because its edges are road and grass.
    Grey and black are held to a higher bar than the rest: tarmac and shadow
    are grey and black too, and a wrong colour is worse than no colour.
    """
    crop = frame if bbox is None else _crop(frame, bbox, margin=-0.22)
    if crop is None or crop.size < 24:
        return ""
    hue, saturation, value = (channel.astype(np.int16) for channel in cv2.split(cv2.cvtColor(_balanced(frame, crop), cv2.COLOR_BGR2HSV)))
    names = np.full(hue.shape, "", dtype=object)
    names[:] = "rouge"
    # A camera warms what it sees: the yellow of a post van reads near hue 17,
    # where a colour chart would call it amber. The boundary follows the camera,
    # not the chart.
    names[(hue >= 8) & (hue < 15)] = "orange"
    names[(hue >= 15) & (hue < 33)] = "jaune"
    names[(hue >= 33) & (hue < 85)] = "vert"
    names[(hue >= 85) & (hue < 130)] = "bleu"
    names[(hue >= 8) & (hue < 20) & (value < 130)] = "marron"
    names[saturation < 58] = "gris"
    names[(saturation < 58) & (value > 160)] = "blanc"
    names[value < 55] = "noir"
    counts: dict[str, int] = {}
    for name in names.ravel():
        counts[name] = counts.get(name, 0) + 1
    winner = max(counts, key=lambda key: counts[key])
    share = counts[winner] / float(names.size)
    floor = 0.60 if winner in {"gris", "noir"} else 0.40
    return winner if share >= floor else ""


def _balanced(frame: np.ndarray, crop: np.ndarray) -> np.ndarray:
    """Undo the colour of the light before naming the colour of the paint.

    At dusk the whole scene turns blue and a white van reads as a blue one.
    Taking the frame as a whole to be grey on average, and scaling the channels
    until it is, leaves the paint and drops the hour of the day.
    """
    means = frame.reshape(-1, 3).mean(axis=0)
    if float(means.min()) < 1:
        return crop
    gain = means.mean() / means
    return np.clip(crop.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def _cadre(frame: np.ndarray, bbox: tuple[int, int, int, int],
           part: float) -> tuple[int, int, np.ndarray]:
    """La vue à montrer au modèle, et le coin d'où elle est prise.

    Carrée, parce que le modèle reçoit un carré : une fenêtre large est mise à
    l'échelle sur sa largeur, une fenêtre haute sur sa hauteur, et le sujet s'y
    retrouve présenté à deux tailles différentes selon qu'il est couché ou
    debout. Ici la mise à l'échelle ne dépend plus de la forme de la tache.

    Débordante, aussi : plutôt que de rogner la fenêtre contre le bord de
    l'image — ce qui ramènerait le sujet contre le bord de la toile, c'est-à-dire
    précisément le défaut qu'on corrige — on la laisse sortir et on complète par
    le gris dont le modèle est coutumier. Un piéton au ras du bas de l'image
    garde ainsi le même cadrage qu'un piéton au milieu.
    """
    hauteur, largeur = frame.shape[:2]
    x, y, w, h = bbox
    # Jamais plus large que l'image. Au-delà du bord il n'y a pas de décor, il
    # n'y a que du gris, et du gris ne renseigne sur rien : il ne fait que
    # rapetisser le sujet. Un centième des taches sont assez grandes pour
    # réclamer trois mille pixels ici, et c'est à elles que la règle s'adresse.
    cote = max(8, int(round(max(w, h) / max(part, 0.05))))
    cote = min(cote, max(hauteur, largeur))
    x0 = int(round(x + w / 2 - cote / 2))
    y0 = int(round(y + h / 2 - cote / 2))
    vue = np.full((cote, cote, 3), 114, dtype=frame.dtype)
    gx0, gy0 = max(0, x0), max(0, y0)
    gx1, gy1 = min(largeur, x0 + cote), min(hauteur, y0 + cote)
    if gx1 > gx0 and gy1 > gy0:
        vue[gy0 - y0 : gy1 - y0, gx0 - x0 : gx1 - x0] = frame[gy0:gy1, gx0:gx1]
    return x0, y0, vue


def _crop_window(frame: np.ndarray, bbox: tuple[int, int, int, int], margin: float) -> tuple[int, int, int, int]:
    height, width = frame.shape[:2]
    x, y, w, h = bbox
    mx = int(w * margin)
    my = int(h * margin)
    x0 = max(0, x - mx)
    y0 = max(0, y - my)
    x1 = min(width, x + w + mx)
    y1 = min(height, y + h + my)
    return x0, y0, x1, y1


def _crop(frame: np.ndarray, bbox: tuple[int, int, int, int], margin: float) -> np.ndarray:
    x0, y0, x1, y1 = _crop_window(frame, bbox, margin)
    return frame[y0:y1, x0:x1]


def _letterbox(image: np.ndarray, size: int) -> tuple[np.ndarray, float, tuple[float, float]]:
    height, width = image.shape[:2]
    gain = min(size / height, size / width)
    new_w, new_h = int(round(width * gain)), int(round(height * gain))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x = (size - new_w) / 2
    pad_y = (size - new_h) / 2
    canvas[int(pad_y) : int(pad_y) + new_h, int(pad_x) : int(pad_x) + new_w] = resized
    blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    return blob, gain, (pad_x, pad_y)


def _parse(raw: np.ndarray) -> list[tuple[float, float, float, float, float, str]]:
    output = np.squeeze(raw)
    if output.ndim != 2:
        return []
    if output.shape[0] < output.shape[1]:
        output = output.T
    # La meilleure des classes qu'on sait nommer, et non la meilleure des
    # quatre-vingts.
    #
    # Le modèle donne une note à chacune des quatre-vingts classes de COCO. On
    # prenait la plus forte, et on jetait la ligne si ce n'était pas une des
    # nôtres — ce qui revient à laisser un objet qu'on ne modélise pas opposer
    # son veto à un objet qu'on modélise. Or la note d'un bateau ne dit rien
    # contre un camion : elle dit seulement qu'il n'y a pas de lac ici, ce que
    # nous savions. Mesuré sur 260 gros plans du 3 octobre : 24 lectures
    # passaient la barre et partaient à la poubelle, dont 19 camions et 5 cars,
    # volés dans 21 cas par « bateau » et dans 3 par « train ».
    #
    # Ce n'est pas un relâchement : la barre de confiance et la part de tache
    # couverte restent les mêmes, et elles continuent de faire tout le tri. La
    # Renault lue « bateau 0,77 / voiture 0,077 » reste écartée, parce que 0,077
    # ne passe pas 0,25 — et c'était déjà le cadrage qu'il fallait réparer.
    notes = output[:, 4:]
    colonnes = _NOTRES[_NOTRES < notes.shape[1]]
    if colonnes.size == 0:
        return []
    notes = notes[:, colonnes]
    rang = notes.argmax(axis=1)
    conf = notes[np.arange(notes.shape[0]), rang]
    boxes = []
    for i in np.flatnonzero(conf >= 0.25):
        cx, cy, w, h = (float(v) for v in output[i, :4])
        nom = COCO[int(colonnes[rang[i]])]
        boxes.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, float(conf[i]), nom))
    return boxes


def _nms(boxes: list[tuple[float, float, float, float, float, str]], iou_limit: float = 0.5):
    boxes = sorted(boxes, key=lambda item: item[4], reverse=True)
    kept = []
    used: list[tuple[float, float, float, float]] = []
    for item in boxes:
        x0, y0, x1, y1, _conf, _name = item
        if any(_iou((x0, y0, x1, y1), previous) > iou_limit for previous in used):
            continue
        used.append((x0, y0, x1, y1))
        kept.append(item)
    return kept


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-9)
