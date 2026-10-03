"""Public history and private candidates. Only named events are published."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from . import __version__

THUMB_WIDTH = 480
THUMB_QUALITY = 52
PASSAGE_ZONES = {"road", "roundabout", "other"}
RANK = {"fire": 6, "bus": 4, "vehicle": 3, "car": 3, "person": 3, "plane": 2, "motion": 1, "habit": 0}
# Above this, on the ground, the thing is longer than a car. It is the one
# physical line the watch draws between a light vehicle and a heavy one, and it
# is drawn once here: naming reads it to choose between Voiture and Camion, the
# main loop to decide a timetable is worth opening, and open_passage to refuse
# to call a lorry and a car the same crossing.
BUS_LENGTH_M = 5.5
# What is published the moment it is seen, instead of waiting for the group.
# The whole point of the watch is the start of a fire; a quarter of an hour of
# delay would give away the only thing it is for.
URGENT_TYPES = {"fire"}


class Store:
    def __init__(self, root: Path, history_days: int = 30):
        self.root = root
        self.history_days = history_days
        self.events_path = root / "events.json"
        self.thumbs = root / "thumbs"
        self.closeups = root / "closeups"
        self.candidates_path = root / "candidates.jsonl"
        self.seen_path = root / "observed.jsonl"
        self.thumbs.mkdir(parents=True, exist_ok=True)
        self.dirty = False
        # A fire does not wait for the next round of publication. Ordinary
        # traffic is grouped to spare the machine and the network; this flag is
        # what lets one event jump the queue.
        self.urgent = False
        self._seq = 0
        # Ce que le dernier add_event a fait de la lecture qu'on lui donnait :
        # l'a-t-il adoptée, ou seulement comptée derrière une lecture déjà en
        # place ? L'appelant ne pouvait pas le savoir et gardait l'observation
        # dans les deux cas, si bien que le fichier finissait par contenir
        # l'observation d'une lecture que la carte ne montre pas. Neuf pour
        # cent des lignes étaient dans ce cas le 30 septembre.
        self.reading_kept = True
        self.events = self._load()
        self._seen_ids = self._load_seen_ids()

    def add_event(self, when: datetime, type_: str, label: str, zone: str, confidence: float, jpeg: bytes, detail: dict) -> dict:
        self.events = self._load()
        self.reading_kept = True
        if type_ in URGENT_TYPES:
            self.urgent = True
        stamp = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        self._seq += 1
        event = {
            "id": f"{stamp}-{type_}-{self._seq}",
            "t": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": type_,
            "label": label,
            "zone": zone,
            "confidence": round(confidence, 3),
            "thumb": "",
            "clip_url": "",
            "detail": detail,
        }
        host = open_passage(self.events, event)
        if host is not None:
            # L'identifiant de l'hôte garde l'heure de la première vue du
            # passage, tandis que « t » suit la vue qu'on montre. Les deux
            # divergent donc dès qu'un passage est revu, et c'est voulu : la
            # vignette, la découpe, l'observation et les tickets de relecture
            # sont tous rangés sous l'identifiant, qui ne doit plus bouger. On
            # lit l'heure dans « t », jamais dans le nom.
            if (host.get("detail") or {}).get("correction") or not better_reading(event, host):
                self.reading_kept = False
                _bump(host)
            else:
                _copy_reading(host, event)
                if jpeg:
                    _write_thumb(self.thumbs, host, small_jpeg(jpeg, box=(detail or {}).get("box")))
            self._write()
            self.dirty = True
            return host
        if jpeg:
            _write_thumb(self.thumbs, event, small_jpeg(jpeg, box=(detail or {}).get("box")))
        self.events.append(event)
        self.events.sort(key=lambda item: item["t"], reverse=True)
        self.prune(when)
        self._write()
        self.dirty = True
        return event

    def keep_closeup(self, event: dict, frame, bbox, metres: float = 0.0) -> str:
        """Le sujet, de près et net. C'est l'image de travail.

        Elle sert à juger : le site la montre en grand, et c'est dessus qu'un
        humain décide si la machine a eu raison. Un car dont on ne lit plus le
        flanc n'est plus jugeable, donc elle reste nette et elle est publiée.

        Le floutage existe, mais il ne se fait pas ici. Il se fait à l'antenne,
        au moment de composer la rediffusion, parce que c'est là qu'il est
        demandé et seulement là : une image qu'on va chercher pour l'examiner
        n'est pas la même chose qu'un passage rejoué en boucle devant des gens
        qui ne l'ont pas demandé. Floutée au dépôt, elle l'était pour tout le
        monde, y compris pour celui qui doit juger — c'était l'inverse de ce
        qu'il fallait.
        """
        if frame is None or not bbox or not any(bbox):
            return ""
        # Une lecture qu'on vient d'écarter ne repeint pas la fiche qui l'a
        # battue. La vignette était déjà protégée, le gros plan ne l'était pas :
        # une bétaillère refusée au profit d'une voiture rouge laissait sa photo
        # sur la fiche de la voiture, qui montrait donc un camion.
        if not self.reading_kept:
            return ""
        height, width = frame.shape[:2]
        x, y, w, h = bbox
        pad_x, pad_y = int(w * 0.15) + 8, int(h * 0.25) + 8
        x0, y0 = max(0, x - pad_x), max(0, y - pad_y)
        x1, y1 = min(width, x + max(w, 1) + pad_x), min(height, y + max(h, 1) + pad_y)
        if x1 - x0 < 16 or y1 - y0 < 16:
            return ""
        self.closeups.mkdir(parents=True, exist_ok=True)
        name = f"{event['id']}.jpg"
        decoupe = frame[y0:y1, x0:x1]
        ok, encoded = cv2.imencode(".jpg", decoupe, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not ok:
            return ""
        (self.closeups / name).write_bytes(encoded.tobytes())
        event["closeup"] = f"data/closeups/{name}"
        self._write()
        self.dirty = True
        return event["closeup"]

    def add_candidate(self, when: datetime, zone: str, reason: str, detail: dict) -> None:
        row = {
            "t": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "zone": zone,
            "reason": reason,
            "detail": detail,
        }
        with self.candidates_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def record_seen(self, event_id: str, seen: dict, *, habit: bool = False) -> None:
        """Garder ce que la décision a eu sous les yeux, à part de l'historique.

        À part, parce que le site télécharge events.json à chaque visite et
        qu'il n'a que faire de la chaleur des pixels ni du partage des boîtes.
        Ici, une ligne par carte, sous son identifiant : c'est ce qui permettra
        de refaire tourner le raisonnement sur un cas dont on sait aujourd'hui
        ce qu'il était vraiment.

        Une ligne par carte, et non par publication. Un passage revu dans la
        minute rejoint la carte déjà ouverte, et la carte ne montre qu'une
        lecture : celle qu'elle a retenue. Garder aussi les autres remplissait
        le fichier d'observations qui n'expliquent rien de ce qu'on voit — et
        pire, la dernière écrite pouvait être celle d'une lecture écartée, si
        bien qu'un lecteur pressé rejouait le mauvais raisonnement. C'est ce
        qui m'est arrivé le 30 septembre en enquêtant sur un piéton sous la
        pluie : la première ligne de son identifiant n'avait aucune détection,
        et j'en ai conclu que le disque perdait les lectures du modèle.
        """
        if not self.reading_kept:
            # La lecture n'a pas été retenue : la carte montre toujours celle
            # d'avant, et c'est celle-là qui doit rester explicable.
            return
        # habit dit que la mémoire du cadrage a repris la main après coup, sur
        # un compteur par cellule qui ne figure pas dans l'observation. Un tel
        # verdict ne peut pas être rejoué par decide() seul, et le rejeu doit
        # le savoir plutôt que de compter une fausse divergence.
        row = {"id": event_id, "seen": seen, "habit": habit}
        if event_id in self._seen_ids:
            # La carte a changé de lecture : l'ancienne observation n'explique
            # plus ce qu'elle montre. On réécrit au lieu d'empiler, sans quoi
            # « une ligne par carte » cesse d'être vrai. Le cas est rare —
            # cinquante-quatre cartes sur six cent soixante-treize — donc cette
            # relecture ne se paie pas à chaque passage.
            gardees = [ligne for ligne in self.seen_path.read_text(encoding="utf-8").splitlines()
                       if ligne.strip() and json.loads(ligne).get("id") != event_id]
            self.seen_path.write_text("\n".join(gardees) + ("\n" if gardees else ""), encoding="utf-8")
        self._seen_ids.add(event_id)
        with self.seen_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def set_clip(self, event_id: str, url: str) -> None:
        for event in self.events:
            if event["id"] == event_id:
                event["clip_url"] = url
                self._write()
                self.dirty = True
                return

    def prune(self, now: datetime) -> None:
        cutoff = now.timestamp() - self.history_days * 86400
        kept = []
        for event in self.events:
            moment = datetime.strptime(event["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if moment.timestamp() >= cutoff:
                kept.append(event)
                continue
            thumb = self.root / "thumbs" / Path(event.get("thumb") or "").name
            if thumb.is_file():
                thumb.unlink()
            closeup = self.closeups / Path(event.get("closeup") or "").name
            if event.get("closeup") and closeup.is_file():
                closeup.unlink()
        self.events = kept
        self._prune_seen({event["id"] for event in kept})

    def _prune_seen(self, alive: set) -> None:
        """Une observation ne survit pas à l'entrée qu'elle explique.

        Un verdict porte sur une entrée de l'historique ; passé la fenêtre, il
        n'y a plus d'entrée à corriger et l'observation n'expliquerait plus
        rien. Sans cela le fichier grossirait d'un kilooctet par publication
        sans jamais rien rendre.
        """
        if not self.seen_path.is_file():
            return
        gardees = [line for line in self.seen_path.read_text(encoding="utf-8").splitlines()
                   if line.strip() and json.loads(line).get("id") in alive]
        self.seen_path.write_text("\n".join(gardees) + ("\n" if gardees else ""), encoding="utf-8")
        self._seen_ids = {json.loads(ligne)["id"] for ligne in gardees}

    def _load_seen_ids(self) -> set:
        """Quelles cartes ont déjà leur observation sur le disque.

        Tenu en mémoire pour que le cas courant — une carte neuve — reste une
        simple ligne ajoutée en fin de fichier, et que la réécriture ne
        survienne que lorsqu'une carte change de lecture.
        """
        if not self.seen_path.is_file():
            return set()
        return {json.loads(ligne)["id"]
                for ligne in self.seen_path.read_text(encoding="utf-8").splitlines() if ligne.strip()}

    def _load(self) -> list[dict]:
        if not self.events_path.is_file():
            return []
        payload = json.loads(self.events_path.read_text(encoding="utf-8"))
        return list(payload.get("events") or [])

    def _write(self) -> None:
        payload = {"version": __version__, "events": self.events}
        self.events_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def passage_group(zone: str) -> str:
    if zone in PASSAGE_ZONES:
        return "passage"
    return zone or "other"


def gap_seconds(group: str, same_label: bool) -> int:
    if group == "sky":
        return 600 if same_label else 60
    return 60


def event_time(event: dict) -> datetime:
    return datetime.strptime(event["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def ground_width(event: dict) -> float | None:
    """La largeur au sol de cette lecture, quand elle a pu être mesurée."""
    measured = (event.get("detail") or {}).get("measured") or {}
    try:
        width = float(measured.get("width_m"))
    except (TypeError, ValueError):
        return None
    return width if width > 0 else None


def same_build(new: dict, old: dict) -> bool:
    """Une voiture ne devient pas un semi-remorque en dix secondes.

    Le regroupement ne regardait que la zone et l'heure. Une bétaillère de vingt
    mètres passant dans la même minute qu'une voiture rouge rejoignait donc son
    passage, perdait au classement des confiances, et disparaissait entièrement :
    pas de fiche, pas de carré à l'écran, alors que le modèle l'avait nommée.
    La largeur au sol les sépare, à la ligne qui sert déjà à dire Camion.
    """
    one, other = ground_width(new), ground_width(old)
    if one is None or other is None:
        return True
    return (one >= BUS_LENGTH_M) == (other >= BUS_LENGTH_M)


def open_passage(events: list[dict], event: dict) -> dict | None:
    # Une tache écartée ne rejoint aucun passage. Ce n'est pas la lecture d'une
    # chose, c'est le constat qu'on n'a rien su lire : groupée avec la voiture
    # passée dans la même minute, elle pourrait en prendre la place et
    # l'historique publié dirait « rien de reconnu » là où il disait « voiture ».
    if event.get("type") == "missed":
        return None
    group = passage_group(event.get("zone", ""))
    when = event_time(event)
    newest = None
    for item in events:
        if item.get("type") == "missed":
            continue
        if passage_group(item.get("zone", "")) != group:
            continue
        # Cherché parmi les gabarits compatibles, et non pas simplement écarté
        # sur le plus récent : sinon une voiture glissée entre deux vues du
        # camion couperait le camion en deux passages.
        if not same_build(event, item):
            continue
        if newest is None or event_time(item) > event_time(newest):
            newest = item
    if newest is None:
        return None
    same = newest.get("label") == event.get("label")
    if abs((when - event_time(newest)).total_seconds()) <= gap_seconds(group, same):
        return newest
    return None


def better_reading(new: dict, old: dict) -> bool:
    if (old.get("detail") or {}).get("correction"):
        return False
    if (new.get("detail") or {}).get("correction"):
        return True
    new_rank = RANK.get(new.get("type"), 1)
    old_rank = RANK.get(old.get("type"), 1)
    if new_rank != old_rank:
        return new_rank > old_rank
    return float(new.get("confidence") or 0) > float(old.get("confidence") or 0) + 0.05


def _bump(host: dict) -> None:
    """Another sighting of the same passage, with nothing new to say."""
    detail = dict(host.get("detail") or {})
    detail["count"] = int(detail.get("count") or 1) + 1
    # When was it first seen. The card's own hour moves to whichever sighting
    # its picture came from, so without this the start of the passage is lost.
    detail.setdefault("since", host.get("t"))
    host["detail"] = detail


def _copy_reading(host: dict, event: dict) -> None:
    count = int((host.get("detail") or {}).get("count") or 1) + 1
    correction = (event.get("detail") or {}).get("correction") or (host.get("detail") or {}).get("correction")
    review = event.get("review") or host.get("review")
    clip = host.get("clip_url") or event.get("clip_url") or ""
    host["type"] = event.get("type") or host.get("type")
    host["label"] = event.get("label") or host.get("label")
    host["zone"] = event.get("zone") or host.get("zone")
    host["confidence"] = event.get("confidence", host.get("confidence"))
    detail = dict(event.get("detail") or {})
    if correction:
        detail["correction"] = correction
        if (event.get("detail") or {}).get("correction"):
            host["label"] = correction
    detail["count"] = count
    # The card now shows this sighting's photo, its box and its words, so it
    # must show its hour too. Keeping the first one put a time on a picture
    # taken up to a minute later, which is how a rectangle drawn round a car
    # came to sit on a frame where the car had already gone.
    detail.setdefault("since", (host.get("detail") or {}).get("since") or host.get("t"))
    host["detail"] = detail
    if event.get("t"):
        host["t"] = event["t"]
    if event.get("thumb"):
        host["thumb"] = event["thumb"]
    if review:
        host["review"] = review
    if clip:
        host["clip_url"] = clip


# La taille d'un bloc, comptée au sol et non en pixels : un demi-mètre.
#
# C'est la seule façon d'écrire cette règle une fois pour toutes. Un visage
# fait une vingtaine de centimètres, une plaque une douzaine : ni l'un ni
# l'autre ne tient dans un bloc d'un demi-mètre, donc ni l'un ni l'autre ne
# peut être reconstitué — quelle que soit la définition de la caméra, son
# objectif, ou la distance du sujet. Un nombre de pixels, lui, voudrait dire
# autre chose sur la caméra suivante, et ce projet en vise mille.
FLOU_SOL_M = 0.5
# Et jamais plus fin que ça, même quand on ne sait pas mesurer. Vingt-quatre
# blocs sur la largeur d'une découpe de voiture font vingt centimètres par
# bloc : on voit une voiture, on ne voit pas qui conduit.
BLOCS_MAX = 24


def floute(decoupe: np.ndarray, metres: float = 0.0) -> np.ndarray:
    """La découpe en niveaux de gris et en gros blocs.

    Le gris autant que les blocs. La couleur d'un vêtement est un signalement
    à elle seule — « l'homme au manteau rouge » suffit à désigner quelqu'un
    dans un village — alors qu'elle n'apprend rien sur ce qu'on cherche à
    dire, qui est qu'une chose est passée là à cette heure.
    """
    hauteur, largeur = decoupe.shape[:2]
    if metres > 0.1:
        bloc = max(2.0, largeur * FLOU_SOL_M / metres)
        colonnes = max(2, min(BLOCS_MAX, int(largeur / bloc)))
    else:
        colonnes = max(2, min(BLOCS_MAX, largeur // 8))
    lignes = max(2, int(round(colonnes * hauteur / max(largeur, 1))))
    gris = cv2.cvtColor(decoupe, cv2.COLOR_BGR2GRAY)
    petit = cv2.resize(gris, (colonnes, lignes), interpolation=cv2.INTER_AREA)
    gros = cv2.resize(petit, (largeur, hauteur), interpolation=cv2.INTER_NEAREST)
    return cv2.cvtColor(gros, cv2.COLOR_GRAY2BGR)


def _write_thumb(folder: Path, event: dict, jpeg: bytes) -> None:
    name = f"{event['id']}.jpg"
    (folder / name).write_bytes(jpeg)
    event["thumb"] = f"data/thumbs/{name}"


def fold_events(events: list[dict]) -> list[dict]:
    """One card per passage. Photos of the folded lines are left on disk."""
    kept: list[dict] = []
    for event in sorted(events, key=event_time):
        item = dict(event)
        item["detail"] = dict(event.get("detail") or {})
        host = open_passage(kept, item)
        if host is None:
            item["detail"].setdefault("count", 1)
            kept.append(item)
            continue
        if (host.get("detail") or {}).get("correction") or not better_reading(item, host):
            _bump(host)
            continue
        _copy_reading(host, item)
    kept.sort(key=event_time, reverse=True)
    return kept


def _outline(image: np.ndarray, box) -> None:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return
    height, width = image.shape[:2]
    try:
        x = int(round(float(box[0]) * width))
        y = int(round(float(box[1]) * height))
        w = int(round(float(box[2]) * width))
        h = int(round(float(box[3]) * height))
    except (TypeError, ValueError):
        return
    pad_x = max(10, int(round(w * 0.45)))
    pad_y = max(10, int(round(h * 0.45)))
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(width - 1, x + max(w, 1) + pad_x)
    y1 = min(height - 1, y + max(h, 1) + pad_y)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    cv2.rectangle(image, (x0, y0), (x1, y1), (0, 0, 210), 1)


def small_jpeg(jpeg: bytes, width: int = THUMB_WIDTH, quality: int = THUMB_QUALITY, box=None) -> bytes:
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return jpeg
    height, frame_width = image.shape[:2]
    if frame_width > width:
        scale = width / float(frame_width)
        image = cv2.resize(image, (width, max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA)
    _outline(image, box)
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return jpeg
    return encoded.tobytes()
