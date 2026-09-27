"""Collecte des morceaux d'image sur du mouvement réel, pleine résolution.

Le jeu d'essai ne doit pas être choisi par le modèle qu'on veut juger : les
gros plans déjà archivés sont ceux que YOLO avait reconnus, et s'en servir pour
mesurer YOLO reviendrait à ne l'interroger que sur ce qu'il sait déjà. On prend
donc tout ce qui bouge, nommé ou non.

    .venv/bin/python scripts/collect_crops.py 20   # pendant 20 minutes
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from watcher.config import load_config  # noqa: E402
from watcher.geometry import load_zones  # noqa: E402
from watcher.main import _frames  # noqa: E402
from watcher.motion import MotionDetector  # noqa: E402

DEST = ROOT / "data" / "crops"


def main() -> None:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    cfg = load_config()
    DEST.mkdir(parents=True, exist_ok=True)
    motion = MotionDetector(
        load_zones(Path(cfg["_root"]) / cfg["zones"]),
        motion_width=cfg["motion_width"],
        min_track_frames=cfg["min_track_frames"],
        max_foreground_ratio=cfg["max_foreground_ratio"],
    )
    fin = time.time() + minutes * 60
    carnet = []
    for frame in _frames(cfg["stream_url"]):
        now = time.time()
        if now > fin:
            break
        for track in motion.step(frame, now).ended:
            if not track.best_jpeg:
                continue
            x, y, w, h = track.best_bbox
            if w < 10 or h < 10:
                continue
            nom = f"{int(track.started)}-{track.id}-{track.zone}-{w}x{h}.jpg"
            (DEST / nom).write_bytes(track.best_jpeg)
            carnet.append({"fichier": nom, "zone": track.zone, "bbox": [x, y, w, h],
                           "frames": track.frames})
            print(f"{len(carnet):4d}  {track.zone:11s} {w}x{h} px", flush=True)
    (DEST / "carnet.json").write_text(json.dumps(carnet, ensure_ascii=False, indent=1))
    print(f"terminé : {len(carnet)} morceaux dans {DEST}")


if __name__ == "__main__":
    main()
